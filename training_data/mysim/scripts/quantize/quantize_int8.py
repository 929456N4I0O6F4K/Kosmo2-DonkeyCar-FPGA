#!/usr/bin/env python3
"""
mypilot1 模型 INT8 量化与模拟器测试脚本

目标：
1. 将 mypilot1.keras 转换为 TFLite INT8 量化模型
2. 在模拟器真实图像上对比 FP32 vs INT8 推理输出
3. 提取各层量化参数（scale/zero_point）供 Vitis HLS 使用

预处理（与训练/推理一致）：
  - 输入图像 120x160 RGB
  - CROP: 顶部 25 行用白色 (255,255,255) 遮盖
  - 归一化: pixel / 255.0 -> [0, 1]
"""
import os
import sys
import glob
import json
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf
from PIL import Image
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

# ============ 路径配置 ============
MODEL_PATH = f'{MYSIM_DIR}/models/mypilot1/mypilot.keras'
OUTPUT_DIR = f'{MYSIM_DIR}/artifacts/quantization'
CALIB_IMG_DIR = f'{MYSIM_DIR}/datasets/sim/mypilot1/3_warehouse/images'
ROI_CROP_TOP = 25
IMG_H, IMG_W, IMG_C = 120, 160, 3

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============ 1. 图像预处理（与训练一致）============
def preprocess_image(img_arr):
    """应用 CROP mask + 归一化"""
    arr = img_arr.copy()
    # CROP mask: 顶部 ROI_CROP_TOP 行设为白色 (255)
    if ROI_CROP_TOP > 0:
        arr[:ROI_CROP_TOP, :, :] = 255
    # 归一化到 [0, 1]
    arr = arr.astype(np.float32) / 255.0
    return arr

def load_and_preprocess(img_path):
    img = Image.open(img_path).convert('RGB').resize((IMG_W, IMG_H))
    arr = np.array(img, dtype=np.uint8)
    return preprocess_image(arr)

# ============ 2. 加载 FP32 模型 ============
print('=' * 70)
print('1. 加载 FP32 模型')
print('=' * 70)
model = tf.keras.models.load_model(MODEL_PATH, compile=False)
total_weights = int(sum(np.prod(v.shape) for v in model.weights))
print(f'  总参数量: {total_weights:,}')
print(f'  FP32 大小: {total_weights * 4 / 1048576:.2f} MB')
print(f'  输入: {model.inputs[0].shape}')
print(f'  输出: angle={model.outputs[0].shape}, throttle={model.outputs[1].shape}')

# ============ 3. 准备校准数据 ============
print('\n' + '=' * 70)
print('2. 准备校准数据（仓库赛道真实图像）')
print('=' * 70)
img_files = sorted(glob.glob(os.path.join(CALIB_IMG_DIR, '*.jpg')))
print(f'  找到 {len(img_files)} 张图像')
# 采样 200 张做校准（均匀采样覆盖不同场景）
n_calib = min(200, len(img_files))
step = max(1, len(img_files) // n_calib)
calib_files = img_files[::step][:n_calib]
print(f'  采样 {len(calib_files)} 张用于校准')

calib_data = np.zeros((len(calib_files), IMG_H, IMG_W, IMG_C), dtype=np.float32)
for i, f in enumerate(calib_files):
    calib_data[i] = load_and_preprocess(f)
print(f'  校准数据 shape: {calib_data.shape}')
print(f'  像素范围: [{calib_data.min():.3f}, {calib_data.max():.3f}]')

# 选 100 张做测试集
n_test = min(100, len(img_files))
test_files = [f for f in img_files if f not in calib_files][:n_test]
if len(test_files) < n_test:
    test_files = img_files[-n_test:]
test_data = np.zeros((len(test_files), IMG_H, IMG_W, IMG_C), dtype=np.float32)
for i, f in enumerate(test_files):
    test_data[i] = load_and_preprocess(f)
print(f'  测试数据 shape: {test_data.shape}')

# ============ 4. FP32 参考推理 ============
print('\n' + '=' * 70)
print('3. FP32 参考推理')
print('=' * 70)
y_fp32 = model.predict(test_data, verbose=0)
angle_fp32 = y_fp32[0].flatten()
throttle_fp32 = y_fp32[1].flatten()
print(f'  angle 范围: [{angle_fp32.min():.4f}, {angle_fp32.max():.4f}]')
print(f'  throttle 范围: [{throttle_fp32.min():.4f}, {throttle_fp32.max():.4f}]')

# ============ 5. TFLite INT8 量化 ============
print('\n' + '=' * 70)
print('4. TFLite INT8 量化')
print('=' * 70)

def representative_dataset():
    for i in range(len(calib_data)):
        yield [calib_data[i:i+1]]

converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_dataset
# 强制 INT8 量化（权重和激活都为 INT8）
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.float32  # 输出保持 float32 便于对比

tflite_model = converter.convert()
int8_path = os.path.join(OUTPUT_DIR, 'mypilot1_int8.tflite')
with open(int8_path, 'wb') as f:
    f.write(tflite_model)
int8_size = os.path.getsize(int8_path)
print(f'  INT8 模型已保存: {int8_path}')
print(f'  INT8 大小: {int8_size / 1048576:.3f} MB (压缩比 {total_weights*4/int8_size:.1f}x)')

# ============ 6. INT8 推理测试 ============
print('\n' + '=' * 70)
print('5. INT8 推理测试')
print('=' * 70)
interpreter = tf.lite.Interpreter(model_path=int8_path)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
print(f'  输入 dtype: {input_details[0]["dtype"]}, shape: {input_details[0]["shape"]}')
print(f'  输出 dtype: {output_details[0]["dtype"]}')

# 获取输入量化参数
inp_scale, inp_zero = input_details[0]['quantization']
print(f'  输入 scale={inp_scale:.6f}, zero_point={inp_zero}')

# 映射 TFLite 输出到 angle/throttle（TFLite 输出顺序可能与 Keras 不同）
angle_idx = 0
throttle_idx = 1
# 通过全部测试样本的输出范围判断：angle 变化范围大，throttle 变化范围小
ranges = [[], []]
for i in range(len(test_data)):
    inp = test_data[i:i+1]
    inp_q = np.round(inp / inp_scale + inp_zero).astype(np.int8)
    interpreter.set_tensor(input_details[0]['index'], inp_q)
    interpreter.invoke()
    ranges[0].append(float(interpreter.get_tensor(output_details[0]['index'])[0][0]))
    ranges[1].append(float(interpreter.get_tensor(output_details[1]['index'])[0][0]))
range0 = max(ranges[0]) - min(ranges[0])
range1 = max(ranges[1]) - min(ranges[1])
print(f'  output[0] 范围: [{min(ranges[0]):.4f}, {max(ranges[0]):.4f}] (跨度={range0:.4f})')
print(f'  output[1] 范围: [{min(ranges[1]):.4f}, {max(ranges[1]):.4f}] (跨度={range1:.4f})')
if range0 > range1:
    angle_idx, throttle_idx = 0, 1
else:
    angle_idx, throttle_idx = 1, 0
print(f'  输出映射: output[{angle_idx}]=angle, output[{throttle_idx}]=throttle')

y_int8_angle = np.zeros(len(test_data), dtype=np.float32)
y_int8_throttle = np.zeros(len(test_data), dtype=np.float32)

for i in range(len(test_data)):
    inp = test_data[i:i+1]
    inp_q = np.round(inp / inp_scale + inp_zero).astype(np.int8)
    interpreter.set_tensor(input_details[0]['index'], inp_q)
    interpreter.invoke()
    y_int8_angle[i] = interpreter.get_tensor(output_details[angle_idx]['index'])[0][0]
    y_int8_throttle[i] = interpreter.get_tensor(output_details[throttle_idx]['index'])[0][0]

print(f'  INT8 angle 范围: [{y_int8_angle.min():.4f}, {y_int8_angle.max():.4f}]')
print(f'  INT8 throttle 范围: [{y_int8_throttle.min():.4f}, {y_int8_throttle.max():.4f}]')

# ============ 7. 精度对比分析 ============
print('\n' + '=' * 70)
print('6. FP32 vs INT8 精度对比')
print('=' * 70)

def analyze_diff(name, fp32, int8):
    abs_err = np.abs(fp32 - int8)
    rel_err = abs_err / (np.abs(fp32) + 1e-8)
    mae = np.mean(abs_err)
    max_err = np.max(abs_err)
    # 相关性
    corr = np.corrcoef(fp32, int8)[0, 1] if np.std(fp32) > 0 and np.std(int8) > 0 else 0.0
    print(f'\n  --- {name} ---')
    print(f'    MAE (平均绝对误差): {mae:.6f}')
    print(f'    Max 绝对误差: {max_err:.6f}')
    print(f'    平均相对误差: {np.mean(rel_err)*100:.2f}%')
    print(f'    相关系数: {corr:.6f}')
    # 误差分布
    print(f'    误差 < 0.01: {np.mean(abs_err < 0.01)*100:.1f}%')
    print(f'    误差 < 0.05: {np.mean(abs_err < 0.05)*100:.1f}%')
    print(f'    误差 < 0.10: {np.mean(abs_err < 0.10)*100:.1f}%')
    return {'mae': float(mae), 'max_err': float(max_err), 'corr': float(corr)}

angle_stats = analyze_diff('转向角 (angle)', angle_fp32, y_int8_angle)
throttle_stats = analyze_diff('油门 (throttle)', throttle_fp32, y_int8_throttle)

# 逐样本对比（前 10 个）
print('\n  前 10 个样本对比:')
print(f'  {"#":<4} {"FP32_angle":<12} {"INT8_angle":<12} {"diff":<10} {"FP32_thr":<12} {"INT8_thr":<12} {"diff":<10}')
for i in range(min(10, len(test_data))):
    da = angle_fp32[i] - y_int8_angle[i]
    dt = throttle_fp32[i] - y_int8_throttle[i]
    print(f'  {i:<4} {angle_fp32[i]:<12.6f} {y_int8_angle[i]:<12.6f} {da:<10.6f} '
          f'{throttle_fp32[i]:<12.6f} {y_int8_throttle[i]:<12.6f} {dt:<10.6f}')

# ============ 8. 提取量化参数（供 Vitis HLS 使用）============
print('\n' + '=' * 70)
print('7. 提取各层量化参数（供 Vitis HLS 使用）')
print('=' * 70)

# 用 TFLite 解析器提取每层的 scale/zero_point
# TFLite 的 tensor 量化参数
quant_params = {'input': {'scale': float(inp_scale), 'zero_point': int(inp_zero)}}

# 获取所有 tensor 的量化参数
for tensor_detail in interpreter.get_tensor_details():
    name = tensor_detail['name']
    scale, zero = tensor_detail['quantization']
    if scale != 0.0:  # 只记录量化过的 tensor
        quant_params[name] = {
            'scale': float(scale),
            'zero_point': int(zero),
            'dtype': str(tensor_detail['dtype']),
            'shape': [int(s) for s in tensor_detail['shape']]
        }

print(f'  共提取 {len(quant_params)} 个量化 tensor')
print(f'\n  主要层量化参数:')
print(f'  {"层名":<30} {"scale":<14} {"zero_point":<12} {"dtype":<8}')
print('  ' + '-' * 70)
for name, params in sorted(quant_params.items()):
    if 'scale' in params:
        print(f'  {name:<30} {params["scale"]:<14.8f} {params["zero_point"]:<12} {params.get("dtype",""):<8}')

# 保存量化参数
params_path = os.path.join(OUTPUT_DIR, 'quantization_params.json')
with open(params_path, 'w') as f:
    json.dump(quant_params, f, indent=2, ensure_ascii=False)
print(f'\n  量化参数已保存: {params_path}')

# ============ 9. 保存测试结果 ============
results = {
    'model': 'mypilot1',
    'total_weights': total_weights,
    'fp32_mb': total_weights * 4 / 1048576,
    'int8_mb': int8_size / 1048576,
    'compression_ratio': total_weights * 4 / int8_size,
    'n_test_samples': len(test_data),
    'angle': angle_stats,
    'throttle': throttle_stats,
    'quantization_params_path': params_path,
    'int8_model_path': int8_path,
}
results_path = os.path.join(OUTPUT_DIR, 'quantization_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f'\n  测试结果已保存: {results_path}')

# ============ 10. 结论 ============
print('\n' + '=' * 70)
print('8. 结论')
print('=' * 70)
angle_ok = angle_stats['corr'] > 0.95 and angle_stats['mae'] < 0.05
throttle_ok = throttle_stats['corr'] > 0.90 and throttle_stats['mae'] < 0.05
print(f'  转向角量化质量: {"PASS" if angle_ok else "FAIL"} '
      f'(corr={angle_stats["corr"]:.4f}, mae={angle_stats["mae"]:.6f})')
print(f'  油门量化质量: {"PASS" if throttle_ok else "FAIL"} '
      f'(corr={throttle_stats["corr"]:.4f}, mae={throttle_stats["mae"]:.6f})')
if angle_ok and throttle_ok:
    print('  ✓ INT8 量化精度满足 Vitis HLS 部署要求')
    print('  ✓ 可以基于 quantization_params.json 中的 scale/zero_point')
    print('    进行 Vitis HLS 定点数 (ap_fixed<8,...>) 设计')
else:
    print('  ✗ INT8 量化精度不足，建议:')
    print('    1. 增加校准数据量')
    print('    2. 尝试 INT16 量化')
    print('    3. 使用 Quantization-Aware Training (QAT)')
print('\n' + '=' * 70)
