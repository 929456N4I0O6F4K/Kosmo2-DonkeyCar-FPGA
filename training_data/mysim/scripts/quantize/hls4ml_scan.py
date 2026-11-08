"""
hls4ml 精度扫描脚本 - 找到最小可部署位宽
输出重定向到日志文件避免缓冲问题
"""
import os
import sys
from pathlib import Path

MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

# 在 import hls4ml 之前重定向 stdout 到日志
LOG_PATH = f'{MYSIM_DIR}/artifacts/hls4ml_out/scan.log'
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
log_file = open(LOG_PATH, 'w', buffering=1)  # line-buffered
class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, data):
        for s in self.streams: s.write(data); s.flush()
    def flush(self):
        for s in self.streams: s.flush()
sys.stdout = Tee(sys.__stdout__, log_file)
sys.stderr = sys.stdout

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['HLS4ML_BACKEND'] = 'vivado'

import numpy as np
import tensorflow as tf
import hls4ml
import json

MODEL_PATH = f'{MYSIM_DIR}/models/mypilot/mypilot.keras'
OUTPUT_DIR = f'{MYSIM_DIR}/artifacts/hls4ml_out'
PART = 'xc7k325tffg900-2'
CLOCK = 50  # MHz

print('=' * 60, flush=True)
print('1. 加载模型', flush=True)
print('=' * 60, flush=True)
model = tf.keras.models.load_model(MODEL_PATH, compile=False)
total_weights = int(sum(np.prod(v.shape) for v in model.weights))
print(f'总参数量: {total_weights:,}', flush=True)
print(f'FP32 大小: {total_weights*4/1048576:.2f} MB', flush=True)

# 生成测试输入
np.random.seed(42)
X_test = np.random.rand(50, 120, 160, 3).astype(np.float32)
y_ref = model.predict(X_test, verbose=0)
print(f'参考输出 shapes: {y_ref[0].shape}, {y_ref[1].shape}', flush=True)

print('\n' + '=' * 60, flush=True)
print('2. hls4ml 精度扫描', flush=True)
print('=' * 60, flush=True)

# 关键档位
precision_configs = [
    ('INT16', 16),
    ('INT8',   8),
    ('INT4',   4),
    ('INT2',   2),
]

results = []
for name, bw in precision_configs:
    print(f'\n--- 测试 {name} (bw={bw}) ---', flush=True)
    try:
        config = hls4ml.utils.config_from_keras_model(
            model, granularity='name', backend='Vivado'
        )
        precision_str = f'ap_fixed<{bw},{bw//2},AP_RND,AP_SAT>'
        for layer in config['LayerName'].values():
            layer['Precision'] = {
                'result': precision_str,
                'weight': precision_str,
                'bias': precision_str,
                'accum': f'ap_fixed<{bw+8},{bw//2+4},AP_RND,AP_SAT>'
            }
            layer['ReuseFactor'] = 1
        config['Model']['Strategy'] = 'Latency'
        config['Model']['Precision'] = precision_str

        hls_model = hls4ml.converters.convert_from_keras_model(
            model,
            hls_config=config,
            output_dir=os.path.join(OUTPUT_DIR, f'bw_{bw}'),
            part=PART,
            clock_period=CLOCK
        )
        print(f'  HLS 项目已生成', flush=True)
        
        hls_model.compile()
        print(f'  csim 编译完成', flush=True)
        
        y_hls = hls_model.predict(X_test)
        if isinstance(y_hls, list):
            err0 = np.mean(np.abs(y_hls[0] - y_ref[0])) / (np.mean(np.abs(y_ref[0])) + 1e-8)
            err1 = np.mean(np.abs(y_hls[1] - y_ref[1])) / (np.mean(np.abs(y_ref[1])) + 1e-8)
            rel_err = (err0 + err1) / 2
        else:
            rel_err = np.mean(np.abs(y_hls - y_ref)) / (np.mean(np.abs(y_ref)) + 1e-8)
        
        size_mb = total_weights * (bw/8) / 1048576
        results.append({
            'precision': name, 'bit_width': bw,
            'rel_error': float(rel_err), 'size_mb': float(size_mb),
            'status': 'ok'
        })
        print(f'  相对误差: {rel_err*100:.2f}%', flush=True)
        print(f'  权重大小: {size_mb:.3f} MB', flush=True)
    except Exception as e:
        print(f'  失败: {e}', flush=True)
        results.append({
            'precision': name, 'bit_width': bw,
            'rel_error': None, 'size_mb': None,
            'status': f'fail: {str(e)[:200]}'
        })

print('\n' + '=' * 60, flush=True)
print('3. 精度扫描汇总报告', flush=True)
print('=' * 60, flush=True)
print(f'{"精度":<10} {"位宽":<6} {"相对误差":<12} {"权重大小":<12} {"状态":<10}', flush=True)
print('-' * 60, flush=True)
for r in results:
    err_str = f"{r['rel_error']*100:.2f}%" if r['rel_error'] is not None else 'N/A'
    size_str = f"{r['size_mb']:.3f} MB" if r['size_mb'] is not None else 'N/A'
    print(f"{r['precision']:<10} {r['bit_width']:<6} {err_str:<12} {size_str:<12} {r['status'][:10]:<10}", flush=True)

with open(os.path.join(OUTPUT_DIR, 'precision_scan.json'), 'w') as f:
    json.dump({
        'model': 'mypilot', 'part': PART, 'clock_mhz': CLOCK,
        'total_weights': total_weights,
        'fp32_mb': total_weights * 4 / 1048576,
        'results': results
    }, f, indent=2, ensure_ascii=False)
print(f'\n结果已保存: {OUTPUT_DIR}/precision_scan.json', flush=True)
log_file.close()
