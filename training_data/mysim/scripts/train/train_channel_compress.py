#!/usr/bin/env python3
"""
通道压缩架构训练脚本 v2 — 直接训练，不通过 KerasPilot

方案1: Conv5=32 + 1x1Conv(32→16) + Flatten(1664)
方案2: Conv5=16 + Flatten(1664)

关键修复: 不使用 kl.compile()/kl.set_optimizer()，直接 model.compile() + model.fit()
"""
import os
import sys
import json
import logging
import numpy as np
from PIL import Image

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.layers import (Dense, Input, Conv2D, Dropout, Flatten)
from tensorflow.keras import Model
logging.getLogger('tensorflow').setLevel(logging.WARNING)

from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, MYSIM_DIR)
import donkeycar as dk
from donkeycar.pipeline.types import TubDataset
from donkeycar.pipeline.training import BatchSequence
from donkeycar.utils import train_test_split

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

TUBS = [
    f'{MYSIM_DIR}/datasets/sim/mypilot1/1_generated-track',
    f'{MYSIM_DIR}/datasets/sim/mypilot1/2_generated-roads',
    f'{MYSIM_DIR}/datasets/sim/mypilot1/3_warehouse',
]
ORIG_MODEL_PATH = f'{MYSIM_DIR}/models/mypilot1/mypilot.keras'
MODEL_DIR = f'{MYSIM_DIR}/models/mypilot1'
INPUT_SHAPE = (120, 160, 3)
ROI_CROP_TOP = 25
BATCH_SIZE = 64
EPOCHS = 50
LEARNING_RATE = 0.001


def conv2d(filters, kernel, strides, layer_num):
    return Conv2D(filters=filters,
                  kernel_size=(kernel, kernel),
                  strides=(strides, strides),
                  activation='relu',
                  name='conv2d_' + str(layer_num))


def build_scheme1(input_shape=(120, 160, 3), num_outputs=2):
    """方案1: Conv5=32 + 1x1Conv(32→16) + Flatten(1664)"""
    drop = 0.2
    img_in = Input(shape=input_shape, name='img_in')
    x = conv2d(24, 5, 2, 1)(img_in)
    x = Dropout(drop)(x)
    x = conv2d(32, 5, 2, 2)(x)
    x = Dropout(drop)(x)
    x = conv2d(64, 5, 2, 3)(x)
    x = Dropout(drop)(x)
    x = conv2d(64, 3, 1, 4)(x)
    x = Dropout(drop)(x)
    x = conv2d(32, 3, 1, 5)(x)          # Conv5: 64→32
    x = Dropout(drop)(x)
    x = Conv2D(16, 1, strides=1, activation='relu',
               name='conv_1x1_compress')(x)  # 32→16, 空间不变
    x = Dropout(drop)(x)
    x = Flatten(name='flattened')(x)    # 8*13*16 = 1664
    x = Dense(100, activation='relu', name='dense_1')(x)
    x = Dropout(drop)(x)
    x = Dense(50, activation='relu', name='dense_2')(x)
    x = Dropout(drop)(x)
    outputs = [Dense(1, activation='linear',
                     name='n_outputs' + str(i))(x) for i in range(num_outputs)]
    return Model(inputs=[img_in], outputs=outputs, name='linear_s1')


def build_scheme2(input_shape=(120, 160, 3), num_outputs=2):
    """方案2: Conv5=16 + Flatten(1664)"""
    drop = 0.2
    img_in = Input(shape=input_shape, name='img_in')
    x = conv2d(24, 5, 2, 1)(img_in)
    x = Dropout(drop)(x)
    x = conv2d(32, 5, 2, 2)(x)
    x = Dropout(drop)(x)
    x = conv2d(64, 5, 2, 3)(x)
    x = Dropout(drop)(x)
    x = conv2d(64, 3, 1, 4)(x)
    x = Dropout(drop)(x)
    x = conv2d(16, 3, 1, 5)(x)          # Conv5: 64→16
    x = Dropout(drop)(x)
    x = Flatten(name='flattened')(x)    # 8*13*16 = 1664
    x = Dense(100, activation='relu', name='dense_1')(x)
    x = Dropout(drop)(x)
    x = Dense(50, activation='relu', name='dense_2')(x)
    x = Dropout(drop)(x)
    outputs = [Dense(1, activation='linear',
                     name='n_outputs' + str(i))(x) for i in range(num_outputs)]
    return Model(inputs=[img_in], outputs=outputs, name='linear_s2')


def load_all_records(cfg, tub_paths):
    all_records = []
    for tp in tub_paths:
        if not os.path.isdir(tp):
            continue
        dataset = TubDataset(config=cfg, tub_paths=[tp], seq_size=0)
        records = dataset.get_records()
        dataset.close()
        all_records.extend(records)
        logger.info(f"  {os.path.basename(tp)}: {len(records)} 条")
    return all_records


def train_scheme(scheme=1, epochs=EPOCHS):
    model_name = f'mypilot_s{scheme}'
    model_path = os.path.join(MODEL_DIR, f'{model_name}.keras')

    logger.info("=" * 70)
    logger.info(f"训练方案{scheme}")
    logger.info("=" * 70)

    cfg = dk.load_config()
    cfg.BATCH_SIZE = BATCH_SIZE
    cfg.MAX_EPOCHS = epochs
    cfg.LEARNING_RATE = LEARNING_RATE
    cfg.TRANSFORMATIONS = ['CROP']
    cfg.ROI_CROP_TOP = ROI_CROP_TOP

    logger.info("=== 加载训练数据 ===")
    all_records = load_all_records(cfg, TUBS)
    logger.info(f"总记录数: {len(all_records)}")

    train_records, val_records = train_test_split(
        all_records, shuffle=True, test_size=1. - cfg.TRAIN_TEST_SPLIT)
    logger.info(f"训练集: {len(train_records)} 条, 验证集: {len(val_records)} 条")

    # 构建模型
    keras.backend.clear_session()
    if scheme == 1:
        model = build_scheme1(INPUT_SHAPE, num_outputs=2)
    else:
        model = build_scheme2(INPUT_SHAPE, num_outputs=2)
    model.summary()

    total_params = int(sum(np.prod(v.shape) for v in model.weights))
    logger.info(f"方案{scheme} 总参数: {total_params:,} "
                f"({total_params*4/1048576:.2f} MB)")

    # 直接编译模型，不通过 kl
    optimizer = keras.optimizers.Adam(learning_rate=LEARNING_RATE)
    model.compile(optimizer=optimizer, loss='mse')
    logger.info(f"模型已编译: optimizer=Adam, lr={LEARNING_RATE}, loss=mse")

    # 使用 DonkeyCar 的 BatchSequence 但传入 kl 作为数据管道
    # kl 只用于 output_shapes/output_types/y_transform，不用于训练
    kl = dk.utils.get_model_by_type('linear', cfg)
    # 替换 kl 的内部模型为我们的自定义模型（仅用于 output_shapes 等）
    kl.interpreter.model = model
    # 更新 output_keys 以匹配新模型
    kl.interpreter.output_keys = model.output_names
    # 不调用 kl.compile() 和 kl.set_optimizer()！

    train_pipe = BatchSequence(kl, cfg, train_records, is_train=True)
    val_pipe = BatchSequence(kl, cfg, val_records, is_train=False)

    tune = tf.data.experimental.AUTOTUNE
    ds_train = train_pipe.create_tf_data().prefetch(tune)
    ds_val = val_pipe.create_tf_data().prefetch(tune)

    train_steps = len(train_pipe)
    val_steps = len(val_pipe)
    logger.info(f"训练步数/epoch: {train_steps}, 验证步数: {val_steps}")

    # 验证数据管道
    logger.info("=== 验证数据管道 ===")
    for batch_x, batch_y in ds_train.take(1):
        logger.info(f"  输入: img_in shape={batch_x['img_in'].shape}, "
                    f"dtype={batch_x['img_in'].dtype}")
        logger.info(f"  标签 keys: {list(batch_y.keys())}")
        for k, v in batch_y.items():
            logger.info(f"    {k}: shape={v.shape}, dtype={v.dtype}, "
                        f"range=[{float(np.min(v)):.4f}, {float(np.max(v)):.4f}]")
        # 测试模型是否能处理这个 batch
        test_out = model(batch_x, training=False)
        for i, o in enumerate(test_out):
            logger.info(f"  模型输出[{i}] ({model.output_names[i]}): "
                        f"shape={o.shape}, "
                        f"range=[{float(np.min(o)):.4f}, {float(np.max(o)):.4f}]")
        break

    callbacks = [
        keras.callbacks.EarlyStopping(
            monitor='val_loss', patience=10, restore_best_weights=True,
            min_delta=0.0001),
        keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss', factor=0.5, patience=5, min_lr=1e-6),
    ]

    logger.info(f"=== 开始训练 (epochs={epochs}, lr={LEARNING_RATE}) ===")
    history = model.fit(
        ds_train, steps_per_epoch=train_steps,
        validation_data=ds_val, validation_steps=val_steps,
        epochs=epochs, callbacks=callbacks, verbose=1)

    model.save(model_path)
    logger.info(f"模型已保存: {model_path}")

    train_config = {
        "MODEL_TYPE": "linear",
        "TRANSFORMATIONS": ["CROP"],
        "ROI_CROP_TOP": ROI_CROP_TOP,
        "LEARNING_RATE": LEARNING_RATE,
        "MAX_EPOCHS": epochs,
        "ARCHITECTURE": f"Scheme {scheme}: channel compression",
    }
    config_path = model_path.replace('.keras', '.train_config.json')
    with open(config_path, 'w') as f:
        json.dump(train_config, f, indent=2)

    if history and hasattr(history, 'history'):
        loss = history.history.get('loss', [])
        val_loss = history.history.get('val_loss', [])
        if loss and val_loss:
            logger.info(f"训练 loss: {loss[0]:.4f} -> {loss[-1]:.4f}")
            logger.info(f"验证 loss: {val_loss[0]:.4f} -> {val_loss[-1]:.4f}")

    return model, history


def compare_scheme(scheme=1):
    model_name = f'mypilot_s{scheme}'
    scheme_model_path = os.path.join(MODEL_DIR, f'{model_name}.keras')

    logger.info("\n" + "=" * 70)
    logger.info(f"精度对比: 原始(Flatten) vs 方案{scheme}")
    logger.info("=" * 70)

    orig_model = tf.keras.models.load_model(ORIG_MODEL_PATH, compile=False)
    scheme_model = tf.keras.models.load_model(scheme_model_path, compile=False)

    orig_params = int(sum(np.prod(v.shape) for v in orig_model.weights))
    scheme_params = int(sum(np.prod(v.shape) for v in scheme_model.weights))
    logger.info(f"原始模型参数: {orig_params:,} ({orig_params*4/1048576:.2f} MB)")
    logger.info(f"方案{scheme}参数: {scheme_params:,} "
                f"({scheme_params*4/1048576:.2f} MB)")
    logger.info(f"参数减少: {(orig_params-scheme_params)/orig_params*100:.1f}%")

    # Dense1 对比
    for layer in scheme_model.layers:
        if layer.name == 'dense_1':
            o_kernel = None
            for ol in orig_model.layers:
                if ol.name == 'dense_1':
                    o_kernel = ol.kernel
                    break
            s_in = layer.kernel.shape[0] if hasattr(layer, 'kernel') else '?'
            o_in = o_kernel.shape[0] if o_kernel is not None else '?'
            logger.info(f"\nDense1 对比:")
            logger.info(f"  原始: 输入维度 {o_in}")
            logger.info(f"  方案{scheme}: 输入维度 {s_in}, "
                        f"参数 {layer.count_params():,}")
            logger.info(f"  Dense1 INT8 BRAM: "
                        f"{layer.count_params()/1024:.1f} KB "
                        f"(原始: "
                        f"{(int(o_in)*100+100)/1024:.1f} KB)")
            break

    import glob
    img_files = sorted(glob.glob(
        f'{MYSIM_DIR}/models/'
        'mypilot1/3_warehouse/images/*.jpg'))
    test_files = img_files[:200]
    logger.info(f"\n加载 {len(test_files)} 张测试图像")

    X_test = np.zeros((len(test_files), 120, 160, 3), dtype=np.float32)
    for i, f in enumerate(test_files):
        img = Image.open(f).convert('RGB').resize((160, 120))
        arr = np.array(img, dtype=np.uint8)
        arr[:ROI_CROP_TOP, :, :] = 255
        X_test[i] = arr.astype(np.float32) / 255.0

    y_orig = orig_model.predict(X_test, verbose=0, batch_size=32)
    y_scheme = scheme_model.predict(X_test, verbose=0, batch_size=32)

    orig_angle = y_orig[0].flatten()
    orig_throttle = y_orig[1].flatten()
    scheme_angle = y_scheme[0].flatten()
    scheme_throttle = y_scheme[1].flatten()

    results = {"scheme": scheme,
               "orig_params": orig_params,
               "scheme_params": scheme_params}

    for name, orig, comp in [("转向角 angle", orig_angle, scheme_angle),
                             ("油门 throttle", orig_throttle, scheme_throttle)]:
        abs_err = np.abs(orig - comp)
        mae = float(np.mean(abs_err))
        max_err = float(np.max(abs_err))
        corr = float(np.corrcoef(orig, comp)[0, 1]) \
            if np.std(orig) > 0 and np.std(comp) > 0 else 0.0

        logger.info(f"\n  --- {name} ---")
        logger.info(f"    原始范围:   [{orig.min():.4f}, {orig.max():.4f}]")
        logger.info(f"    方案{scheme}范围: [{comp.min():.4f}, {comp.max():.4f}]")
        logger.info(f"    MAE:        {mae:.6f}")
        logger.info(f"    Max误差:    {max_err:.6f}")
        logger.info(f"    相关系数:   {corr:.6f}")
        logger.info(f"    误差<0.01:  {np.mean(abs_err<0.01)*100:.1f}%")
        logger.info(f"    误差<0.03:  {np.mean(abs_err<0.03)*100:.1f}%")
        logger.info(f"    误差<0.05:  {np.mean(abs_err<0.05)*100:.1f}%")

        key = name.split()[-1]
        results[key] = {"mae": mae, "max_err": max_err, "corr": corr,
                        "orig_range": [float(orig.min()), float(orig.max())],
                        "scheme_range": [float(comp.min()), float(comp.max())]}

    logger.info(f"\n  前 10 个样本:")
    logger.info(f"  {'#':<4} {'Orig_ang':<12} {'S_ang':<12} {'diff':<10} "
                f"{'Orig_thr':<12} {'S_thr':<12} {'diff':<10}")
    for i in range(min(10, len(X_test))):
        da = orig_angle[i] - scheme_angle[i]
        dt = orig_throttle[i] - scheme_throttle[i]
        logger.info(f"  {i:<4} {orig_angle[i]:<12.6f} {scheme_angle[i]:<12.6f} "
                    f"{da:<10.6f} {orig_throttle[i]:<12.6f} "
                    f"{scheme_throttle[i]:<12.6f} {dt:<10.6f}")

    a_mae = results['angle']['mae']
    a_corr = results['angle']['corr']
    t_corr = results['throttle']['corr']

    logger.info("\n" + "=" * 70)
    logger.info(f"结论")
    logger.info("=" * 70)
    logger.info(f"  参数减少: {(orig_params-scheme_params)/orig_params*100:.1f}%")
    logger.info(f"  Angle:    MAE={a_mae:.6f}, corr={a_corr:.4f}")
    logger.info(f"  Throttle: corr={t_corr:.4f}")

    if a_corr > 0.95 and a_mae < 0.03:
        logger.info(f"  -> 方案{scheme} 可行！精度损失在可接受范围 (MAE<0.03)")
    elif a_corr > 0.9 and a_mae < 0.05:
        logger.info(f"  -> 方案{scheme} 基本可行，精度有少量损失")
    elif a_corr > 0.8:
        logger.info(f"  -> 方案{scheme} 有明显精度损失，需评估实际驾驶效果")
    else:
        logger.info(f"  -> 方案{scheme} 精度损失过大")

    results_path = f'{MYSIM_DIR}/artifacts/quantization/scheme{scheme}_results.json'
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"  结果已保存: {results_path}")

    return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='通道压缩架构训练 v2')
    parser.add_argument('--scheme', type=int, default=0,
                        choices=[0, 1, 2],
                        help='1=Conv5=32+1x1Conv, 2=Conv5=16, 0=全部')
    parser.add_argument('--epochs', type=int, default=EPOCHS)
    args = parser.parse_args()

    if args.scheme == 0:
        all_results = {}
        for s in [1, 2]:
            train_scheme(scheme=s, epochs=args.epochs)
            r = compare_scheme(scheme=s)
            all_results[s] = r

        logger.info(f"\n{'=' * 70}")
        logger.info("汇总对比")
        logger.info(f"{'=' * 70}")
        logger.info(f"{'方案':<8} {'参数量':<10} {'ang_MAE':<12} "
                    f"{'ang_corr':<12} {'thr_corr':<12} {'可行?':<8}")
        logger.info('-' * 62)
        for s, r in all_results.items():
            ok = "YES" if r['angle']['corr'] > 0.95 and r['angle']['mae'] < 0.03 \
                else "评估"
            logger.info(f"  S{s}    {r['scheme_params']:<10,} "
                       f"{r['angle']['mae']:<12.6f} "
                       f"{r['angle']['corr']:<12.4f} "
                       f"{r['throttle']['corr']:<12.4f} {ok:<8}")
    else:
        train_scheme(scheme=args.scheme, epochs=args.epochs)
        compare_scheme(scheme=args.scheme)
