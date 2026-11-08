"""Export the supplied physical model unchanged; verify and generate RTL cases."""
import argparse
import io
import json
import os
from pathlib import Path
import zipfile

os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
import numpy as np
from PIL import Image
import tensorflow as tf
from tensorflow.lite.python import schema_py_generated as schema
import reference as ref
from rtl_layout import write_parallel_roms

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT/'deployment_config.json').read_text(encoding='utf-8'))
MODEL = ROOT.parent / CONFIG['model']
OUT = ROOT / 'sim/generated'


def validate_graph(path):
    model = schema.Model.GetRootAsModel(path.read_bytes(), 0)
    graph = model.Subgraphs(0)
    conv = dense = 0
    names = []
    for index in range(graph.OperatorsLength()):
        op = graph.Operators(index)
        code = model.OperatorCodes(op.OpcodeIndex()).BuiltinCode()
        if code == schema.BuiltinOperator.CONV_2D:
            options = schema.Conv2DOptions()
            table = op.BuiltinOptions()
            options.Init(table.Bytes, table.Pos)
            stride = 2 if conv < 3 else 1
            assert (options.StrideH(), options.StrideW()) == (stride, stride)
            assert options.Padding() == schema.Padding.VALID
            assert (options.DilationHFactor(), options.DilationWFactor()) == (1, 1)
            assert options.FusedActivationFunction() == schema.ActivationFunctionType.RELU
            conv += 1
        elif code == schema.BuiltinOperator.FULLY_CONNECTED:
            options = schema.FullyConnectedOptions()
            table = op.BuiltinOptions()
            options.Init(table.Bytes, table.Pos)
            assert options.FusedActivationFunction() == (schema.ActivationFunctionType.RELU if dense < 2 else schema.ActivationFunctionType.NONE)
            assert options.WeightsFormat() == schema.FullyConnectedOptionsWeightsFormat.DEFAULT
            dense += 1
        elif code not in (schema.BuiltinOperator.SHAPE, schema.BuiltinOperator.STRIDED_SLICE,
                           schema.BuiltinOperator.PACK, schema.BuiltinOperator.RESHAPE):
            raise ValueError(f'Unsupported operator: {code}')
        names.append(int(code))
    assert (conv, dense) == (5, 3)
    return names


def rgb565_bytes(rgb):
    """Inverse of the capture conversion; check actual PNGs lie on RGB565 grid."""
    p = ((rgb[..., 0].astype(np.uint16) >> 3) << 11) | ((rgb[..., 1].astype(np.uint16) >> 2) << 5) | (rgb[..., 2].astype(np.uint16) >> 3)
    return np.stack((p >> 8, p & 255), axis=-1).astype(np.uint8).reshape(-1)


def rgb888(raw):
    a = np.asarray(raw, dtype=np.uint8).reshape(120, 160, 2).astype(np.uint16)
    p = (a[..., 0] << 8) | a[..., 1]
    r, g, b = p >> 11, (p >> 5) & 63, p & 31
    return np.stack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)), -1).astype(np.uint8)


def real_images(count):
    archives = sorted(ROOT.parent.glob(CONFIG['recording_archives']))
    if not archives:
        raise RuntimeError('No real capture archives')
    result = []
    for zi in np.linspace(0, len(archives)-1, min(count, len(archives)), dtype=int):
        archive = archives[zi]
        with zipfile.ZipFile(archive) as z:
            records_files = sorted(n for n in z.namelist() if n.endswith('records.jsonl'))
            if len(records_files) != 1:
                raise ValueError(f'Ambiguous session: {archive}')
            records_name = records_files[0]
            records = [json.loads(line) for line in z.read(records_name).decode().splitlines() if line.strip()]
            record = records[len(records)//2]
            image_name = str(Path(records_name).parent / record['cam/image_array']).replace('\\', '/')
            rgb = np.asarray(Image.open(io.BytesIO(z.read(image_name))).convert('RGB'))
            assert rgb.shape == (120, 160, 3)
            raw = rgb565_bytes(rgb)
            # No additional quantization loss is allowed in the real test data.
            np.testing.assert_array_equal(rgb888(raw), rgb)
            result.append((raw, {'archive': archive.name, 'archive_sha256': ref.sha256(archive),
                                 'image': image_name, 'angle': record['user/angle'],
                                 'throttle': record['user/throttle']}))
    return result


def verify_reference(interpreter, layers, q):
    interpreter.set_tensor(interpreter.get_input_details()[0]['index'], q[None])
    interpreter.invoke()
    current = q
    golden = []
    for layer in layers:
        if layer['op'] == 'CONV_2D':
            current = ref.conv_reference(current, layer)
        else:
            current = ref.dense_reference(current, layer)
        expected = interpreter.get_tensor(layer['output_index']).reshape(current.shape)
        np.testing.assert_array_equal(current, expected, err_msg=layer['name'])
        golden.append(expected.reshape(-1))
    return np.concatenate(golden), current.reshape(-1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-cases', type=int, default=8)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    generated = ROOT / 'rtl/generated'
    generated.mkdir(parents=True, exist_ok=True)
    codes = validate_graph(MODEL)
    interpreter, ops = ref.load_graph(MODEL)
    layers = ref.extract_layers(interpreter, ops)
    assert interpreter.get_input_details()[0]['dtype'] == np.int8
    scale, zero = ref.scalar_quant(interpreter.get_input_details()[0])
    assert np.isclose(scale, 1/255, rtol=1e-7) and zero == -128
    assert len(interpreter.get_output_details()) == 1
    assert interpreter.get_output_details()[0]['shape'].tolist() == [1, 2]
    assert layers[-1]['output_index'] == interpreter.get_output_details()[0]['index']
    layout = write_parallel_roms(layers, interpreter, generated)
    samples = [(f'real_{i:02d}', raw, meta) for i, (raw, meta) in enumerate(real_images(args.real_cases))]
    rng = np.random.default_rng(0x4D50)
    raw_random = rng.integers(0, 256, 38400, dtype=np.uint8)
    # Spatial pattern catches row/column origin, channel, and byte-order errors.
    yy, xx = np.indices((120, 160))
    pattern = np.stack(((xx*7+yy*3)%256, (yy*11+xx)%256, (xx*13+yy*17)%256), -1).astype(np.uint8)
    samples.extend([('black', np.zeros(38400, np.uint8), {}),
                    ('white', np.full(38400, 255, np.uint8), {}),
                    ('pattern', rgb565_bytes(pattern), {}),
                    ('random', raw_random, {})])
    # Matching float TFLite is used only to report the supplied INT8 model's
    # pre-existing quantization error. The deployment file is never converted.
    float_model = ROOT.parent / CONFIG['float_model']
    floating = tf.lite.Interpreter(model_content=float_model.read_bytes())
    floating.allocate_tensors()
    cases = []
    for name, raw, metadata in samples:
        rgb = rgb888(raw)
        q = (rgb[25:120, 2:158].astype(np.int16)-128).astype(np.int8)
        golden, output = verify_reference(interpreter, layers, q)
        ref.write_hex(OUT / f'{name}_raw.mem', raw.tolist(), 2)
        ref.write_hex(OUT / f'{name}_input.mem', q.view(np.uint8).reshape(-1).tolist(), 2)
        ref.write_hex(OUT / f'{name}_expected.mem', golden.view(np.uint8).tolist(), 2)
        floating.set_tensor(floating.get_input_details()[0]['index'], rgb[None, 25:120, 2:158].astype(np.float32)/255)
        floating.invoke()
        fp = floating.get_tensor(floating.get_output_details()[0]['index']).reshape(-1)
        dequant = (output.astype(float)-layers[-1]['output_zp'])*layers[-1]['output_scale']
        case = dict(name=name, source=metadata, input_sha256=__import__('hashlib').sha256(q.tobytes()).hexdigest(),
                    golden_bytes=len(golden), int8_outputs=output.tolist(),
                    steering_q16=ref.q16(int(output[0]), layers[-1]),
                    throttle_q16=ref.q16(int(output[1]), layers[-1]),
                    dequantized=dequant.tolist(), float_outputs=fp.tolist(),
                    int8_vs_float_abs_error=np.abs(dequant-fp).tolist(), reference_mismatches=0)
        cases.append(case)
        print(f'{name}: all {len(golden)} layer bytes exact, int8={output.tolist()}', flush=True)
    ref.VECTORS = OUT
    quantizer_count = ref.write_quantizer_vectors()
    offsets = np.cumsum([0]+[x['out_h']*x['out_w']*x['out_c'] for x in layout['stages']])
    config = [f'localparam FRAME_BYTES=44460, GOLDEN_BYTES={int(offsets[-1])}, QUANTIZER_CASES={quantizer_count};\n',
              'function integer layer_offset; input integer index; begin case(index)\n']
    config += [f'{i}: layer_offset={int(v)};\n' for i,v in enumerate(offsets[:-1])]
    config += ['default: layer_offset=0; endcase end endfunction\n']
    (OUT/'test_config.vh').write_text(''.join(config))
    sequence = cases + [cases[0]]
    (OUT/'run_cases.vh').write_text(''.join(f'run_case("{c["name"]}", {c["steering_q16"]}, {c["throttle_q16"]});\n' for c in sequence))
    fields = ['name','op','input_zp','output_zp','input_scale','output_scale']
    final=layers[-1]
    manifest = dict(model=str(MODEL.relative_to(ROOT.parent)), model_sha256=ref.sha256(MODEL),
                    output_quantization=dict(scale=final['output_scale'],zero_point=final['output_zp'],scale_q30=round(final['output_scale']*(1<<30))),
                    float_model_sha256=ref.sha256(float_model), model_modified=False, puf=False,
                    crop='RGB[25:120,2:158,:]', input_quantization='q=pixel-128',
                    rgb565_conversion='MSB first; bit replication, identical to training/uio_linux.go',
                    output_semantics=['steering','throttle'], operators=codes,
                    layers=[dict({k:l[k] for k in fields}, weight_shape=list(l['weights'].shape)) for l in layers],
                    layout=layout, quantizer_cases=quantizer_count, cases=cases)
    (ROOT/'model_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('EXPORT PASS',flush=True)


if __name__ == '__main__':
    main()
