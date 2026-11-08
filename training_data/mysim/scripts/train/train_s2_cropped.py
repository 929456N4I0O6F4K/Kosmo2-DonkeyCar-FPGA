#!/usr/bin/env python3
"""
方案2 (Conv5=16) 裁剪版训练脚本

核心改进：裁剪而非白色填充
  - 原版: Input [120, 160, 3], 顶部 25 行白色填充 → Dense1 输入 1664
  - 裁剪版: Input [95, 160, 3], 顶部 25 行直接切掉 → Dense1 输入 1040
  - Dense1 参数: 166,400 → 104,000 (降 37.5%)
  - INT8 大小: 293 KB → 222 KB
  - BRAM 占用: 50% → 34%

训练策略（全部达标）：
1. 数据源：mypilot1 中的 3 个场景
2. 场景等量采样：取最小场景数 5014
3. 角度分箱平衡：7 个角度区间等量抽样
4. 数据增强：水平翻转 + 亮度扰动 ±30 + 随机旋转 ±5°
5. 输入裁剪：ROI_CROP_TOP=25（直接切掉，不填充）
6. 学习率 0.0005, Adam 优化器
7. 训练 50 epochs, batch_size 64
8. 训练/验证 8:2 划分
9. 早停 (val_loss 5 epochs 无改善)

输出：
  - models/mypilot1_s2_cropped/
    - mypilot1_s2_cropped.keras
    - mypilot1_s2_cropped.tflite
    - training_config.json
    - data_split.json
"""
import os
import sys
import json
import random
import logging
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

# ============ 路径配置 ============
DATA_DIR = os.path.join(MYSIM_DIR, 'datasets/sim/mypilot1')
OUTPUT_DIR = os.path.join(MYSIM_DIR, 'models/mypilot1_s2_cropped')
SCENES = ['1_generated-track', '2_generated-roads', '3_warehouse']

# ============ 训练超参数 ============
IMG_H_ORIG = 120          # 原始图像高度
IMG_W_ORIG = 160          # 原始图像宽度
IMG_C = 3
ROI_CROP_TOP = 25         # 裁剪顶部 25 行
ROI_CROP_LEFT = 2         # 裁剪左侧 2 列（对齐 BRAM: 160→156→...→12）
ROI_CROP_RIGHT = 2        # 裁剪右侧 2 列
IMG_H = IMG_H_ORIG - ROI_CROP_TOP  # 裁剪后高度 = 95
IMG_W = IMG_W_ORIG - ROI_CROP_LEFT - ROI_CROP_RIGHT  # 裁剪后宽度 = 156
LEARNING_RATE = 0.0005
BATCH_SIZE = 64
EPOCHS = 50
EARLY_STOP_PATIENCE = 5
VALIDATION_SPLIT = 0.2
SEED = 42

# 角度分箱边界
ANGLE_BINS = [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
BIN_LABELS = ['急左(<=-0.5)', '中左(-0.5~-0.2)', '小左(-0.2~-0.05)',
              '直行(-0.05~0.05)', '小右(0.05~0.2)', '中右(0.2~0.5)', '急右(>=0.5)']

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.makedirs(OUTPUT_DIR, exist_ok=True)

import tensorflow as tf
from tensorflow.keras import Model
from tensorflow.keras.layers import (Dense, Input, Conv2D, Dropout,
                                      Flatten, BatchNormalization)
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import (EarlyStopping, ModelCheckpoint,
                                         TensorBoard, CSVLogger)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ============================================================
# 1. 数据加载 - 从 catalog 读取记录
# ============================================================
def load_scene_records(scene_path):
    """从场景目录读取所有记录"""
    records = []
    cats = sorted([f for f in os.listdir(scene_path)
                   if f.endswith('.catalog')])
    for cat in cats:
        cat_path = os.path.join(scene_path, cat)
        with open(cat_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rec['_scene'] = os.path.basename(scene_path)
                records.append(rec)
    return records


def get_angle(rec):
    """从记录获取转向角"""
    mode = rec.get('user/mode', 'user')
    if mode == 'auto':
        return rec.get('pilot/angle', 0)
    return rec.get('user/angle', 0)


def get_throttle(rec):
    """从记录获取油门"""
    mode = rec.get('user/mode', 'user')
    if mode == 'auto':
        return rec.get('pilot/throttle', 0)
    return rec.get('user/throttle', 0)


# ============================================================
# 2. 场景等量采样
# ============================================================
def scene_balanced_sample(scene_records, seed=SEED):
    """每场景等量采样（取最小场景数）"""
    rng = random.Random(seed)
    counts = {s: len(r) for s, r in scene_records.items()}
    min_count = min(counts.values())

    logger.info("=== 场景等量采样 ===")
    logger.info(f"原始场景分布:")
    for s, c in counts.items():
        logger.info(f"  {s}: {c} 条")
    logger.info(f"目标: 每场景 {min_count} 条")

    balanced = []
    for scene, records in scene_records.items():
        sampled = rng.sample(records, min_count)
        balanced.extend(sampled)
        logger.info(f"  {scene}: 抽样 {len(sampled)} 条")

    rng.shuffle(balanced)
    logger.info(f"合并后总记录: {len(balanced)} 条")
    return balanced


# ============================================================
# 3. 角度分箱平衡
# ============================================================
def angle_balanced_sample(records, bins=ANGLE_BINS, labels=BIN_LABELS,
                           seed=SEED):
    """按角度分箱等量抽样"""
    rng = random.Random(seed + 1)

    bin_to_records = {i: [] for i in range(len(bins) - 1)}
    for rec in records:
        angle = get_angle(rec)
        for i in range(len(bins) - 1):
            if bins[i] <= angle < bins[i + 1]:
                bin_to_records[i].append(rec)
                break

    counts = [len(v) for v in bin_to_records.values()]
    target = min(counts)

    logger.info("\n=== 角度分箱平衡 ===")
    logger.info(f"分箱前分布 (总 {len(records)} 条):")
    for i, label in enumerate(labels):
        pct = counts[i] / len(records) * 100 if records else 0
        logger.info(f"  {label}: {counts[i]} ({pct:.1f}%)")
    logger.info(f"每箱目标: {target} 条 (取最小箱)")

    balanced = []
    for i, label in enumerate(labels):
        recs = bin_to_records[i]
        if len(recs) > target:
            sampled = rng.sample(recs, target)
        else:
            sampled = recs
        balanced.extend(sampled)
        logger.info(f"  {label}: 抽样 {len(sampled)} 条")

    rng.shuffle(balanced)
    logger.info(f"平衡后总记录: {len(balanced)} 条")
    return balanced


# ============================================================
# 4. 数据增强
# ============================================================
def augment_image(img_arr, angle, throttle, rng=None):
    """
    数据增强:
    1. 50% 概率水平翻转 (angle 取反)
    2. 亮度扰动 ±30
    3. 随机旋转 ±5°
    """
    if rng is None:
        rng = random.Random()

    new_angle = angle
    new_throttle = throttle

    # 1. 水平翻转
    if rng.random() < 0.5:
        img_arr = img_arr[:, ::-1, :].copy()
        new_angle = -angle

    # 2. 亮度扰动
    brightness_delta = rng.randint(-30, 30)
    img_arr = np.clip(img_arr.astype(np.int16) + brightness_delta,
                      0, 255).astype(np.uint8)

    # 3. 随机旋转 ±5°
    angle_deg = rng.uniform(-5, 5)
    pil_img = Image.fromarray(img_arr)
    pil_img = pil_img.rotate(angle_deg, resample=Image.BILINEAR,
                              fillcolor=(128, 128, 128))
    img_arr = np.array(pil_img)

    return img_arr, new_angle, new_throttle


def preprocess_image(img_arr):
    """
    核心改进：裁剪而非白色填充
    - 原版: img_arr[:25, :, :] = 255 (白色填充, 仍 120 行)
    - 裁剪版: img_arr = img_arr[25:, :, :] (直接切掉, 95 行)
    - BRAM 优化版: 同时裁剪左右 2 列，宽度 160→156，使 Conv5 输出 5×12=60
                  Dense1 输入 960，参数 96,000，BRAM 利用率 99.2%
    """
    arr = img_arr.copy()
    if ROI_CROP_TOP > 0:
        arr = arr[ROI_CROP_TOP:, :, :]  # 裁剪顶部
    if ROI_CROP_LEFT > 0 or ROI_CROP_RIGHT > 0:
        arr = arr[:, ROI_CROP_LEFT:IMG_W_ORIG - ROI_CROP_RIGHT, :]  # 裁剪左右
    return arr.astype(np.float32) / 255.0


def load_image(img_path, scene_path):
    """加载图像（原始 120×160）"""
    full_path = os.path.join(scene_path, 'images', img_path)
    if not os.path.exists(full_path):
        return None
    img = Image.open(full_path).convert('RGB').resize((IMG_W_ORIG, IMG_H_ORIG))
    return np.array(img, dtype=np.uint8)


# ============================================================
# 5. 数据集构建
# ============================================================
def build_dataset(records, augment=True, seed=SEED):
    """构建 (X, y) 数据集"""
    rng = random.Random(seed + 2)
    X, y_angle, y_throttle = [], [], []
    scene_stats = {s: 0 for s in SCENES}

    for rec in records:
        scene = rec.get('_scene', '')
        scene_path = os.path.join(DATA_DIR, scene)
        img_name = rec.get('cam/image_array')
        if not img_name:
            continue

        img_arr = load_image(img_name, scene_path)
        if img_arr is None:
            continue

        angle = get_angle(rec)
        throttle = get_throttle(rec)

        if augment:
            img_arr, angle, throttle = augment_image(img_arr, angle,
                                                       throttle, rng)

        img_arr = preprocess_image(img_arr)
        X.append(img_arr)
        y_angle.append(angle)
        y_throttle.append(throttle)
        scene_stats[scene] = scene_stats.get(scene, 0) + 1

    X = np.array(X, dtype=np.float32)
    y_angle = np.array(y_angle, dtype=np.float32)
    y_throttle = np.array(y_throttle, dtype=np.float32)

    logger.info(f"\n=== 数据集构建 ===")
    logger.info(f"X shape: {X.shape} (裁剪后高度 {IMG_H})")
    logger.info(f"angle 范围: [{y_angle.min():.4f}, {y_angle.max():.4f}]")
    logger.info(f"throttle 范围: [{y_throttle.min():.4f}, {y_throttle.max():.4f}]")
    logger.info(f"场景分布: {scene_stats}")
    return X, y_angle, y_throttle


def train_test_split_balanced(X, y_angle, y_throttle,
                                val_split=VALIDATION_SPLIT, seed=SEED):
    """按比例划分训练/验证"""
    rng = np.random.RandomState(seed + 3)
    n = len(X)
    idx = rng.permutation(n)
    val_size = int(n * val_split)
    val_idx = idx[:val_size]
    train_idx = idx[val_size:]

    X_train, X_val = X[train_idx], X[val_idx]
    y_a_train, y_a_val = y_angle[train_idx], y_angle[val_idx]
    y_t_train, y_t_val = y_throttle[train_idx], y_throttle[val_idx]

    logger.info(f"\n=== 数据划分 ===")
    logger.info(f"训练: {len(X_train)} 条")
    logger.info(f"验证: {len(X_val)} 条")
    return (X_train, y_a_train, y_t_train), (X_val, y_a_val, y_t_val)


# ============================================================
# 6. 模型架构 (方案2 裁剪版: Conv5=16, Input 95×160)
# ============================================================
def build_model_s2_cropped():
    """
    方案2 裁剪版架构 (BRAM 优化: 5×12=960):
      Input [95, 156, 3]            ← 裁剪后高度 95, 宽度 156
      → Conv1 (3→24, 5×5, s2) → [24, 46, 76]
      → Conv2 (24→32, 5×5, s2) → [32, 21, 36]
      → Conv3 (32→64, 5×5, s2) → [64, 9, 16]
      → Conv4 (64→64, 3×3, s1) → [64, 7, 14]
      → Conv5 (64→16, 3×3, s1) → [16, 5, 12]   ← filter 16, 5×12=60
      → Flatten → [960]                       ← BRAM 优化: 原 1040 → 960
      → Dense1 (960→100)                      ← 96,000 params, 21 BRAM, 利用率 99.2%
      → Dense2 (100→50)
      → Out (50→2: angle, throttle)
    """
    drop = 0.2
    img_in = Input(shape=(IMG_H, IMG_W, IMG_C), name='img_in')

    x = Conv2D(24, (5, 5), strides=(2, 2), activation='relu',
               name='conv2d_1')(img_in)
    x = Dropout(drop)(x)

    x = Conv2D(32, (5, 5), strides=(2, 2), activation='relu',
               name='conv2d_2')(x)
    x = Dropout(drop)(x)

    x = Conv2D(64, (5, 5), strides=(2, 2), activation='relu',
               name='conv2d_3')(x)
    x = Dropout(drop)(x)

    x = Conv2D(64, (3, 3), strides=(1, 1), activation='relu',
               name='conv2d_4')(x)
    x = Dropout(drop)(x)

    # 方案2: Conv5 filter 从 64 减到 16
    x = Conv2D(16, (3, 3), strides=(1, 1), activation='relu',
               name='conv2d_5')(x)
    x = Dropout(drop)(x)

    x = Flatten(name='flattened')(x)
    x = Dense(100, activation='relu', name='dense_1')(x)
    x = Dropout(drop)(x)
    x = Dense(50, activation='relu', name='dense_2')(x)
    x = Dropout(drop)(x)

    angle_out = Dense(1, activation='linear', name='n_outputs0')(x)
    throttle_out = Dense(1, activation='linear', name='n_outputs1')(x)

    model = Model(inputs=[img_in], outputs=[angle_out, throttle_out],
                  name='linear_s2_cropped')
    return model


# ============================================================
# 主训练流程
# ============================================================
def main():
    logger.info("=" * 70)
    logger.info("方案2 裁剪版训练 (Conv5=16 + 裁剪 95×160 + 增强)")
    logger.info(f"  输入尺寸: [{IMG_H}, {IMG_W}, {IMG_C}] (裁剪 {ROI_CROP_TOP} 行)")
    logger.info(f"  Dense1 输入: 1040 (原 1664, 降 37.5%)")
    logger.info("=" * 70)

    # 1. 加载所有场景数据
    logger.info("\n[1/7] 加载场景数据")
    scene_records = {}
    for scene in SCENES:
        sp = os.path.join(DATA_DIR, scene)
        recs = load_scene_records(sp)
        scene_records[scene] = recs
        logger.info(f"  {scene}: {len(recs)} 条")

    # 2. 场景等量采样
    logger.info("\n[2/7] 场景等量采样")
    scene_balanced = scene_balanced_sample(scene_records)

    # 3. 角度分箱平衡
    logger.info("\n[3/7] 角度分箱平衡")
    angle_balanced = angle_balanced_sample(scene_balanced)

    # 4. 构建数据集（含数据增强）
    logger.info("\n[4/7] 构建数据集（含数据增强）")
    X, y_angle, y_throttle = build_dataset(angle_balanced, augment=True)

    # 5. 训练/验证划分
    logger.info("\n[5/7] 训练/验证划分")
    (X_tr, y_a_tr, y_t_tr), (X_val, y_a_val, y_t_val) = \
        train_test_split_balanced(X, y_angle, y_throttle)

    # 6. 构建模型
    logger.info("\n[6/7] 构建方案2 裁剪版模型")
    model = build_model_s2_cropped()
    model.compile(
        optimizer=Adam(learning_rate=LEARNING_RATE),
        loss={'n_outputs0': 'mse', 'n_outputs1': 'mse'},
        loss_weights={'n_outputs0': 0.5, 'n_outputs1': 0.5},
        metrics={'n_outputs0': 'mae', 'n_outputs1': 'mae'},
        jit_compile=False
    )
    total_params = int(sum(np.prod(v.shape) for v in model.weights))
    logger.info(f"  总参数: {total_params:,}")
    for layer in model.layers:
        if 'conv' in layer.name or 'dense' in layer.name or 'flat' in layer.name:
            logger.info(f"  {layer.name}: out={layer.output.shape} "
                        f"params={layer.count_params():,}")

    # 7. 训练
    logger.info("\n[7/7] 训练")
    log_dir = os.path.join(OUTPUT_DIR, 'logs',
                           f"train_{__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(log_dir, exist_ok=True)

    callbacks = [
        EarlyStopping(monitor='val_loss', patience=EARLY_STOP_PATIENCE,
                      restore_best_weights=True, verbose=1),
        ModelCheckpoint(os.path.join(OUTPUT_DIR, 'mypilot1_s2_cropped_best.keras'),
                        monitor='val_loss', save_best_only=True, verbose=1),
        TensorBoard(log_dir=log_dir),
        CSVLogger(os.path.join(OUTPUT_DIR, 'training_log.csv'))
    ]

    history = model.fit(
        X_tr,
        {'n_outputs0': y_a_tr, 'n_outputs1': y_t_tr},
        validation_data=(X_val, {'n_outputs0': y_a_val, 'n_outputs1': y_t_val}),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        callbacks=callbacks,
        verbose=2
    )

    # 加载最佳权重
    best_path = os.path.join(OUTPUT_DIR, 'mypilot1_s2_cropped_best.keras')
    if os.path.exists(best_path):
        model = tf.keras.models.load_model(best_path, compile=False)
        logger.info(f"已加载最佳权重: {best_path}")

    # 重新编译以支持 evaluate
    model.compile(
        optimizer=Adam(learning_rate=LEARNING_RATE),
        loss={'n_outputs0': 'mse', 'n_outputs1': 'mse'},
        loss_weights={'n_outputs0': 0.5, 'n_outputs1': 0.5},
        metrics={'n_outputs0': 'mae', 'n_outputs1': 'mae'},
        jit_compile=False
    )

    # 保存最终 Keras 模型
    keras_path = os.path.join(OUTPUT_DIR, 'mypilot1_s2_cropped.keras')
    model.save(keras_path)
    logger.info(f"\nKeras 模型已保存: {keras_path}")

    # 8. 评估
    logger.info("\n=== 评估 ===")
    eval_results = model.evaluate(X_val,
        {'n_outputs0': y_a_val, 'n_outputs1': y_t_val}, verbose=0)
    logger.info(f"验证集评估: {eval_results}")

    y_pred = model.predict(X_val, verbose=0)
    pred_angle = y_pred[0].flatten()
    pred_throttle = y_pred[1].flatten()

    angle_mae = np.mean(np.abs(pred_angle - y_a_val))
    throttle_mae = np.mean(np.abs(pred_throttle - y_t_val))
    angle_corr = np.corrcoef(pred_angle, y_a_val)[0, 1]
    throttle_corr = np.corrcoef(pred_throttle, y_t_val)[0, 1]

    logger.info(f"angle MAE: {angle_mae:.6f}, 相关系数: {angle_corr:.4f}")
    logger.info(f"throttle MAE: {throttle_mae:.6f}, 相关系数: {throttle_corr:.4f}")
    logger.info(f"angle 预测范围: [{pred_angle.min():.4f}, {pred_angle.max():.4f}]")
    logger.info(f"angle 真实范围: [{y_a_val.min():.4f}, {y_a_val.max():.4f}]")

    # 9. 转换 TFLite FP32
    logger.info("\n=== 转换 TFLite FP32 ===")
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    tflite_model = converter.convert()
    tflite_path = os.path.join(OUTPUT_DIR, 'mypilot1_s2_cropped.tflite')
    with open(tflite_path, 'wb') as f:
        f.write(tflite_model)
    logger.info(f"TFLite FP32 已保存: {tflite_path} "
               f"({os.path.getsize(tflite_path)/1048576:.3f} MB)")

    # 10. INT8 量化
    logger.info("\n=== INT8 量化 ===")

    def representative_dataset():
        """用验证集作为校准数据"""
        for i in range(min(300, len(X_val))):
            yield [X_val[i:i+1].astype(np.float32)]

    converter_int8 = tf.lite.TFLiteConverter.from_keras_model(model)
    converter_int8.optimizations = [tf.lite.Optimize.DEFAULT]
    converter_int8.representative_dataset = representative_dataset
    converter_int8.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter_int8.inference_input_type = tf.int8
    converter_int8.inference_output_type = tf.int8

    tflite_int8 = converter_int8.convert()
    int8_path = os.path.join(OUTPUT_DIR, 'mypilot1_s2_cropped_int8.tflite')
    with open(int8_path, 'wb') as f:
        f.write(tflite_int8)
    logger.info(f"INT8 模型已保存: {int8_path} "
               f"({os.path.getsize(int8_path)/1024:.1f} KB)")

    # 11. INT8 精度验证
    logger.info("\n=== INT8 精度验证 ===")
    interpreter = tf.lite.Interpreter(model_path=int8_path)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    inp_scale, inp_zero = input_details[0]['quantization']

    int8_preds_a, int8_preds_t = [], []
    for i in range(len(X_val)):
        x = X_val[i:i+1]
        x_q = np.round(x / inp_scale + inp_zero).astype(np.int8)
        interpreter.set_tensor(input_details[0]['index'], x_q)
        interpreter.invoke()
        o0 = interpreter.get_tensor(output_details[0]['index'])[0][0]
        o1 = interpreter.get_tensor(output_details[1]['index'])[0][0]
        # 确定 angle 输出
        if abs(o0) > abs(o1) or i == 0:
            int8_preds_a.append(o0 if abs(o0) > abs(o1) else o1)
            int8_preds_t.append(o1 if abs(o0) > abs(o1) else o0)
        else:
            int8_preds_a.append(o1)
            int8_preds_t.append(o0)

    # 简化: 用 std 判断
    test_o0, test_o1 = [], []
    for i in range(min(20, len(X_val))):
        x = X_val[i:i+1]
        x_q = np.round(x / inp_scale + inp_zero).astype(np.int8)
        interpreter.set_tensor(input_details[0]['index'], x_q)
        interpreter.invoke()
        test_o0.append(interpreter.get_tensor(output_details[0]['index'])[0][0])
        test_o1.append(interpreter.get_tensor(output_details[1]['index'])[0][0])

    angle_idx = 0 if np.std(test_o0) > np.std(test_o1) else 1

    int8_preds_a, int8_preds_t = [], []
    for i in range(len(X_val)):
        x = X_val[i:i+1]
        x_q = np.round(x / inp_scale + inp_zero).astype(np.int8)
        interpreter.set_tensor(input_details[0]['index'], x_q)
        interpreter.invoke()
        if angle_idx == 0:
            int8_preds_a.append(interpreter.get_tensor(output_details[0]['index'])[0][0])
            int8_preds_t.append(interpreter.get_tensor(output_details[1]['index'])[0][0])
        else:
            int8_preds_a.append(interpreter.get_tensor(output_details[1]['index'])[0][0])
            int8_preds_t.append(interpreter.get_tensor(output_details[0]['index'])[0][0])

    int8_preds_a = np.array(int8_preds_a)
    int8_preds_t = np.array(int8_preds_t)

    int8_angle_mae = np.mean(np.abs(int8_preds_a - y_a_val))
    int8_throttle_mae = np.mean(np.abs(int8_preds_t - y_t_val))
    int8_angle_corr = np.corrcoef(int8_preds_a, y_a_val)[0, 1]

    logger.info(f"INT8 angle MAE: {int8_angle_mae:.6f}, 相关系数: {int8_angle_corr:.4f}")
    logger.info(f"INT8 angle 范围: [{int8_preds_a.min():.4f}, {int8_preds_a.max():.4f}]")
    logger.info(f"FP32 vs INT8 angle MAE: {angle_mae:.6f} vs {int8_angle_mae:.6f}")

    # 12. 保存量化参数
    quant_params = {
        'input': {
            'scale': float(inp_scale),
            'zero_point': int(inp_zero),
            'shape': [int(s) for s in input_details[0]['shape']]
        },
        'outputs': []
    }
    for od in output_details:
        scale, zp = od['quantization']
        quant_params['outputs'].append({
            'name': od.get('name', ''),
            'scale': float(scale),
            'zero_point': int(zp),
            'shape': [int(s) for s in od['shape']]
        })
    quant_path = os.path.join(OUTPUT_DIR, 'quantization_params.json')
    with open(quant_path, 'w') as f:
        json.dump(quant_params, f, indent=2, ensure_ascii=False)

    # 13. 保存配置和数据划分记录
    config = {
        'model_type': 's2_cropped',
        'architecture': 'Conv5=16 + 裁剪 95×156 + streaming (BRAM 优化)',
        'data_source': 'mypilot1 三个场景',
        'scenes': SCENES,
        'scene_original_counts': {s: len(scene_records[s]) for s in SCENES},
        'scene_balanced_count': min(len(r) for r in scene_records.values()),
        'angle_bins': ANGLE_BINS,
        'angle_bin_labels': BIN_LABELS,
        'augmentation': {
            'horizontal_flip': '50% (angle 取反)',
            'brightness': '±30',
            'rotation': '±5°'
        },
        'crop': {
            'ROI_CROP_TOP': ROI_CROP_TOP,
            'ROI_CROP_LEFT': ROI_CROP_LEFT,
            'ROI_CROP_RIGHT': ROI_CROP_RIGHT,
            'method': 'crop (直接裁剪, 非白色填充)',
            'input_height_original': IMG_H_ORIG,
            'input_width_original': IMG_W_ORIG,
            'input_height_cropped': IMG_H,
            'input_width_cropped': IMG_W
        },
        'hyperparameters': {
            'learning_rate': LEARNING_RATE,
            'batch_size': BATCH_SIZE,
            'max_epochs': EPOCHS,
            'early_stop_patience': EARLY_STOP_PATIENCE,
            'validation_split': VALIDATION_SPLIT,
            'seed': SEED
        },
        'total_params': total_params,
        'dense1_input': 960,
        'dense1_params': 96000,
        'int8_size_kb': os.path.getsize(int8_path) / 1024,
        'evaluation': {
            'fp32_angle_mae': float(angle_mae),
            'fp32_angle_corr': float(angle_corr),
            'fp32_throttle_mae': float(throttle_mae),
            'int8_angle_mae': float(int8_angle_mae),
            'int8_angle_corr': float(int8_angle_corr),
            'int8_throttle_mae': float(int8_throttle_mae),
            'fp32_angle_range': [float(pred_angle.min()),
                                 float(pred_angle.max())],
            'int8_angle_range': [float(int8_preds_a.min()),
                                 float(int8_preds_a.max())]
        }
    }
    config_path = os.path.join(OUTPUT_DIR, 'training_config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    logger.info(f"\n训练配置已保存: {config_path}")

    # 保存数据划分索引
    split_info = {
        'total_after_balance': len(angle_balanced),
        'train_size': len(X_tr),
        'val_size': len(X_val),
        'angle_distribution_train': {
            BIN_LABELS[i]: int(np.sum((y_a_tr >= ANGLE_BINS[i]) &
                                       (y_a_tr < ANGLE_BINS[i+1])))
            for i in range(len(BIN_LABELS))
        },
        'angle_distribution_val': {
            BIN_LABELS[i]: int(np.sum((y_a_val >= ANGLE_BINS[i]) &
                                       (y_a_val < ANGLE_BINS[i+1])))
            for i in range(len(BIN_LABELS))
        }
    }
    split_path = os.path.join(OUTPUT_DIR, 'data_split.json')
    with open(split_path, 'w') as f:
        json.dump(split_info, f, indent=2, ensure_ascii=False)
    logger.info(f"数据划分记录已保存: {split_path}")

    logger.info("\n" + "=" * 70)
    logger.info("训练完成！所有文件位于:")
    logger.info(f"  {OUTPUT_DIR}")
    logger.info("=" * 70)
    logger.info(f"\n模型对比:")
    logger.info(f"  原始方案2:     Dense1=166,400, INT8=293 KB, BRAM=37 块")
    logger.info(f"  裁剪版方案2:   Dense1=104,000, INT8=239 KB, BRAM=23 块")
    logger.info(f"  BRAM优化版:    Dense1=96,000,  INT8={os.path.getsize(int8_path)/1024:.1f} KB, BRAM=21 块")
    logger.info(f"  参数减少: {(166400-96000)/166400*100:.1f}% (vs 原始)")
    logger.info(f"  BRAM 利用率: 99.2% (Dense1)")


if __name__ == '__main__':
    main()
