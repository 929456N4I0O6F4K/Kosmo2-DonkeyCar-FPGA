"""
hls4ml 压缩部署脚本 - 优化版
策略:
1. 用 hls4ml 的 QKeras-aware 量化做精度评估 (Python 端, 无需 csim)
2. 用高 ReuseFactor 让 dense 层权重存 BRAM, 避免编译爆炸
3. 生成 HLS 项目用于后续 Vivado 综合
"""
import os, sys, json
from pathlib import Path

MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

LOG_PATH = f'{MYSIM_DIR}/artifacts/hls4ml_out/quant.log'
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
log_file = open(LOG_PATH, 'w', buffering=1)
class Tee:
    def __init__(self, *s): self.s = s
    def write(self, d):
        for x in self.s: x.write(d); x.flush()
    def flush(self):
        for x in self.s: x.flush()
sys.stdout = Tee(sys.__stdout__, log_file)
sys.stderr = sys.stdout

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import numpy as np
import tensorflow as tf
import hls4ml
from tensorflow.keras.models import load_model
from tensorflow.keras.layers import Conv2D, Dense, Dropout, Flatten, Input, Model

MODEL_PATH = f'{MYSIM_DIR}/models/mypilot/mypilot.keras'
OUTPUT_DIR = f'{MYSIM_DIR}/artifacts/hls4ml_out'
PART = 'xc7k325tffg900-2'
CLOCK = 50

print('=' * 70, flush=True)
print('hls4ml 压缩部署 - 阶段 1: 量化精度评估 (Python 端)', flush=True)
print('=' * 70, flush=True)

# ============ 1. 加载原始 FP32 模型 ============
model = load_model(MODEL_PATH, compile=False)
total_weights = int(sum(np.prod(v.shape) for v in model.weights))
print(f'原始模型: 817,028 参数, FP32 = {total_weights*4/1048576:.2f} MB', flush=True)

# 用真实图像做评估 (从训练数据取)
import glob
from PIL import Image
img_files = sorted(glob.glob(f'{MYSIM_DIR}/data/images/*.jpg'))[:50]
print(f'加载 {len(img_files)} 张真实图像用于精度评估', flush=True)
X_test = np.zeros((50, 120, 160, 3), dtype=np.float32)
for i, f in enumerate(img_files):
    img = Image.open(f).resize((160, 120))
    X_test[i] = np.array(img, dtype=np.float32) / 255.0
y_ref = model.predict(X_test, verbose=0)
print(f'参考输出: angle 范围 [{y_ref[0].min():.3f}, {y_ref[0].max():.3f}], '
      f'throttle 范围 [{y_ref[1].min():.3f}, {y_ref[1].max():.3f}]', flush=True)

# ============ 2. 量化精度扫描 (Python 端, 不跑 csim) ============
print('\n' + '=' * 70, flush=True)
print('阶段 2: 量化精度扫描 (Python 量化, 不需 csim)', flush=True)
print('=' * 70, flush=True)

def quantize_array(arr, bw, signed=True):
    """简单均匀量化器, 模拟 ap_fixed<bw, bw/2>"""
    if bw >= 32:
        return arr.astype(np.float32)
    integer_bits = max(1, bw // 2)
    frac_bits = bw - integer_bits
    scale = 1.0 / (2 ** frac_bits)
    max_val = (2 ** (bw - 1)) - 1 if signed else (2 ** bw) - 1
    q = np.round(arr / scale)
    q = np.clip(q, -max_val if signed else 0, max_val)
    return (q * scale).astype(np.float32)

results = []
for bw in [16, 12, 8, 6, 4, 3, 2, 1]:
    name = f'INT{bw}' if bw > 1 else 'BNN(1bit)'