"""Train the existing 95x156 Conv5=16 topology on explicitly separate sessions."""
import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np
from dataset import image_array, load_sessions


def build_model(tf):
    layers = tf.keras.layers
    inputs = layers.Input((95, 156, 3), name="img_in")
    x = inputs
    for i, (channels, kernel, stride) in enumerate([(24, 5, 2), (32, 5, 2), (64, 5, 2), (64, 3, 1), (16, 3, 1)], 1):
        x = layers.Conv2D(channels, kernel, strides=stride, activation="relu", padding="valid", name=f"conv2d_{i}")(x)
        x = layers.Dropout(.2)(x)
    x = layers.Flatten()(x)
    for i, units in enumerate([100, 50], 1):
        x = layers.Dense(units, activation="relu", name=f"dense_{i}")(x)
        x = layers.Dropout(.2)(x)
    return tf.keras.Model(inputs, [layers.Dense(1, name="n_outputs0")(x), layers.Dense(1, name="n_outputs1")(x)])


def make_dataset(tf, records, batch_size, training, seed):
    # Generator avoids loading all image bytes into RAM.
    def generate():
        for r in records:
            yield image_array(r).astype(np.float32) / 255., (np.array([r["user/angle"]], np.float32), np.array([r["user/throttle"]], np.float32))
    signature = (tf.TensorSpec((95, 156, 3), tf.float32), (tf.TensorSpec((1,), tf.float32), tf.TensorSpec((1,), tf.float32)))
    ds = tf.data.Dataset.from_generator(generate, output_signature=signature)
    ds = ds.apply(tf.data.experimental.assert_cardinality(len(records)))
    if training:
        ds = ds.shuffle(min(2048, len(records)), seed=seed)
        def augment(x, y):
            flip = tf.random.uniform(()) < .5
            x = tf.cond(flip, lambda: tf.image.flip_left_right(x), lambda: x)
            x = tf.clip_by_value(tf.image.random_brightness(x, .1), 0., 1.)
            return x, (tf.where(flip, -y[0], y[0]), y[1])
        ds = ds.map(augment, num_parallel_calls=1)
    return ds.batch(batch_size).prefetch(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train-sessions", nargs="+", required=True, type=Path)
    p.add_argument("--val-sessions", nargs="+", required=True, type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--allow-synthetic", action="store_true", help="pipeline smoke test only")
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args()
    if args.epochs < 1 or args.batch_size < 1:
        p.error("epochs and batch size must be positive")
    train, train_ids = load_sessions(args.train_sessions, args.allow_synthetic)
    val, val_ids = load_sessions(args.val_sessions, args.allow_synthetic)
    if set(train_ids) & set(val_ids):
        raise ValueError("Training and validation sessions overlap; adjacent frames must not leak across the split")
    config = {"topology": "mypilot Conv5=16, Dense100/50, two linear heads", "crop": [25, 120, 2, 158],
              "input": [95, 156, 3], "normalization": "RGB uint8 / 255", "seed": args.seed,
              "train_sessions": train_ids, "validation_sessions": val_ids,
              "train_records": len(train), "validation_records": len(val), "synthetic_allowed": args.allow_synthetic,
              "epochs": args.epochs, "batch_size": args.batch_size,
              "training_records_sha256": hashlib.sha256(json.dumps(train, sort_keys=True).encode()).hexdigest(),
              "validation_records_sha256": hashlib.sha256(json.dumps(val, sort_keys=True).encode()).hexdigest()}
    print(json.dumps(config, indent=2))
    if args.check_only:
        return
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "training_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    import tensorflow as tf
    tf.keras.utils.set_random_seed(args.seed)
    model = build_model(tf)
    model.compile(optimizer=tf.keras.optimizers.Adam(.0005), loss=["mse", "mse"])
    train_ds = make_dataset(tf, train, args.batch_size, True, args.seed)
    val_ds = make_dataset(tf, val, args.batch_size, False, args.seed)
    history = model.fit(train_ds, validation_data=val_ds, epochs=args.epochs, callbacks=[
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True),
        tf.keras.callbacks.ModelCheckpoint(args.output / "pilot.keras", monitor="val_loss", save_best_only=True),
        tf.keras.callbacks.CSVLogger(args.output / "history.csv")])
    best = tf.keras.models.load_model(args.output / "pilot.keras", compile=False)
    predictions = best.predict(val_ds.map(lambda x, y: x), verbose=0)
    labels = np.array([[r["user/angle"], r["user/throttle"]] for r in val], dtype=np.float32)
    pred = np.concatenate(predictions, axis=1)
    metrics = {"steering_mae": float(np.abs(pred[:, 0]-labels[:, 0]).mean()),
               "throttle_mae": float(np.abs(pred[:, 1]-labels[:, 1]).mean()),
               "epochs_run": len(history.history["loss"]), "synthetic_test_only": args.allow_synthetic}
    # Calibration uses training data only. Quantization parameters are exported;
    # retrained weights are NOT automatically compatible with existing RTL ROMs.
    def representative():
        # Cover the sensor's full uint8 range, preserving the existing FPGA
        # input contract q = pixel - 128 (scale 1/255, zero point -128).
        yield [np.zeros((1, 95, 156, 3), np.float32)]
        yield [np.ones((1, 95, 156, 3), np.float32)]
        for index in np.linspace(0, len(train)-1, min(300, len(train)), dtype=int):
            r = train[index]
            yield [image_array(r).astype(np.float32)[None] / 255.]
    converter = tf.lite.TFLiteConverter.from_keras_model(best)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    binary = converter.convert()
    (args.output / "pilot.int8.tflite").write_bytes(binary)
    interpreter = tf.lite.Interpreter(model_content=binary)
    interpreter.allocate_tensors()
    def tensor_info(t):
        return {"name": t["name"], "index": int(t["index"]), "shape": t["shape"].tolist(),
                "dtype": str(t["dtype"]), "quantization": list(t["quantization"])}
    # Use TFLite signature output names, never assume the tensor order.
    signatures = interpreter.get_signature_list()
    runner = interpreter.get_signature_runner()
    inputs = runner.get_input_details()
    outputs = runner.get_output_details()
    if set(outputs) != {"output_0", "output_1"} or set(inputs) != {"img_in"}:
        raise ValueError("Unexpected TFLite signature; verify output-head mapping")
    input_scale, input_zero = inputs["img_in"]["quantization"]
    if not np.isclose(input_scale, 1 / 255, rtol=1e-5) or input_zero != -128:
        raise ValueError("TFLite input quantization does not match pixel - 128")
    quantized_predictions = []
    for r in val[:200]:
        x = image_array(r).astype(np.float32)[None] / 255.
        q = np.clip(np.rint(x / input_scale + input_zero), -128, 127).astype(np.int8)
        result = runner(img_in=q)
        quantized_predictions.append([
            float((result[key].astype(np.float32) - outputs[key]["quantization"][1]).item()
                  * outputs[key]["quantization"][0]) for key in ("output_0", "output_1")])
    int8_pred = np.array(quantized_predictions)
    int8_error = np.abs(int8_pred - labels[:len(int8_pred)])
    metrics.update(int8_eval_frames=len(int8_pred), int8_steering_mae=float(int8_error[:, 0].mean()),
                   int8_throttle_mae=float(int8_error[:, 1].mean()),
                   int8_vs_float_mae=np.abs(int8_pred - pred[:len(int8_pred)]).mean(axis=0).tolist())
    quant = {"sha256": hashlib.sha256(binary).hexdigest(), "signatures": signatures,
             "inputs": {k: tensor_info(v) for k, v in inputs.items()},
             "outputs": {k: tensor_info(v) for k, v in outputs.items()},
             "output_semantics": {"output_0": "steering", "output_1": "throttle"},
             "fpga_export_required": True}
    (args.output / "quantization.json").write_text(json.dumps(quant, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
