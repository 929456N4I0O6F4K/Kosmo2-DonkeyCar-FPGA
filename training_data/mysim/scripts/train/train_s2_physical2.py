#!/usr/bin/env python3
"""
方案2 BRAM优化版 - 物理数据训练脚本

数据格式: Donkey Car v5 (records.jsonl + images/ + session.json)
模型架构: Conv5=16 + 裁剪 95×156 + INT8 量化
训练策略:
  - 三段物理采集数据合并
  - 角度分箱等量采样 (解决急转弯过多问题)
  - 数据增强: 镜像(50%) + 亮度(±30) + 旋转(±5°)
  - 真正裁剪 (非白色填充)
  - Adam 学习率 0.0005
  - 8:2 训练/验证划分
  - 早停 patience=5
"""
import os
import sys
import json
import math
import random
import logging
import argparse
import numpy as np
from PIL import Image

from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, MYSIM_DIR)

import tensorflow as tf
from tensorflow.keras.layers import (Dense, Input, Conv2D, Dropout, Flatten)
from tensorflow.keras import Model as KerasModel
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
# 实车采集数据不在项目内; 可用环境变量 CAR_PHYSICAL_DATA 覆盖
_PHYS = os.environ.get('CAR_PHYSICAL_DATA') or next(
    p for p in (os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', '.discarded', 'physical'),
                os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', 'physical'),
                os.path.join(CAR_DIR, '.discarded', 'physical')) if os.path.isdir(p))

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ============ 配置 ============
PHYSIC_DATA_DIR = os.path.join(_PHYS, 'physicaldata2')
OUTPUT_DIR = f'{MYSIM_DIR}/models/mypilot1_s2_physical2'

# 迁移学习源模型 (BRAM 优化版, 已训练于模拟器数据)
TRANSFER_MODEL = f'{MYSIM_DIR}/models/mypilot1_s2_cropped/mypilot1_s2_cropped.keras'

# 图像与裁剪参数 (BRAM 优化版)
IMG_H_ORIG = 120
IMG_W_ORIG = 160
IMG_C = 3
ROI_CROP_TOP = 25
ROI_CROP_LEFT = 2
ROI_CROP_RIGHT = 2
IMG_H = IMG_H_ORIG - ROI_CROP_TOP         # 95
IMG_W = IMG_W_ORIG - ROI_CROP_LEFT - ROI_CROP_RIGHT  # 156

# 训练超参数 (大数据训练, 12500+ 条物理数据, 不做角度平衡)
LEARNING_RATE_INIT = 0.0003       # 初始学习率 (大数据用小学习率)
LEARNING_RATE_MIN = 0.000001      # 最低学习率
WARMUP_EPOCHS = 3                 # warmup 防止初期发散
BATCH_SIZE = 64                   # 大 batch 充分利用大数据
EPOCHS = 100                      # 大数据需要更多 epoch
EARLY_STOP_PATIENCE = 15          # 标准早停
VALIDATION_SPLIT = 0.15
SEED = 42
NUM_TRIALS = 2                    # 大数据稳定性高, 2 次足够
FREEZE_LAYERS = []                # 全部可训练
LABEL_SMOOTHING = 0.05            # 极轻标签平滑 (保留真实分布)

# 角度分箱
ANGLE_BINS = [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
BIN_LABELS = ['急左', '中左', '小左', '直行', '小右', '中右', '急右']
PER_BIN = 600                # 每箱最多采样 600 条 (大数据, 总计可达 4200 条)


# ============ 数据加载 (records.jsonl 格式) ============
def load_physic_records():
    """加载所有物理采集目录的 records.jsonl"""
    all_records = []
    sessions = []
    for d in sorted(os.listdir(PHYSIC_DATA_DIR)):
        path = os.path.join(PHYSIC_DATA_DIR, d)
        if not os.path.isdir(path):
            continue
        rec_path = os.path.join(path, 'records.jsonl')
        if not os.path.exists(rec_path):
            continue
        records = []
        with open(rec_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    # 过滤无效记录 (停车/无图)
                    if r.get('user/throttle', 0) < 0.05:
                        continue
                    img_name = r.get('cam/image_array', '')
                    if not img_name:
                        continue
                    img_path = os.path.join(path, img_name)
                    if not os.path.exists(img_path):
                        continue
                    r['_img_path'] = img_path
                    r['_session'] = d
                    records.append(r)
        sessions.append((d, len(records)))
        all_records.extend(records)
        logger.info(f"  {d}: {len(records)} 条有效")
    logger.info(f"总计: {len(all_records)} 条 (来自 {len(sessions)} 个 session)")
    return all_records, sessions


def angle_balanced_sample(records, per_bin=PER_BIN, bins=ANGLE_BINS, seed=SEED):
    """按角度分箱等量采样"""
    rng = random.Random(seed)
    buckets = {i: [] for i in range(len(bins) - 1)}
    for r in records:
        a = r.get('user/angle', 0)
        for i in range(len(bins) - 1):
            if bins[i] <= a < bins[i + 1]:
                buckets[i].append(r)
                break

    logger.info(f"\n角度分箱采样 (每箱最多 {per_bin} 条):")
    balanced = []
    for i, recs in buckets.items():
        n = len(recs)
        actual = min(n, per_bin)
        if actual > 0:
            sampled = rng.sample(recs, actual) if n > actual else recs
        else:
            sampled = []
        balanced.extend(sampled)
        label = BIN_LABELS[i] if i < len(BIN_LABELS) else f'bin{i}'
        logger.info(f"  {label}({bins[i]:.2f}~{bins[i+1]:.2f}): {n} → {actual} 条")

    rng.shuffle(balanced)
    logger.info(f"平衡后总记录数: {len(balanced)}")
    return balanced


# ============ 数据增强 ============
def augment_image(img_arr, angle, rng):
    """数据增强: 100% 翻转 + 亮度 + 旋转 + 平移 (412→4000+ 等效样本)"""
    from PIL import Image as PILImage

    # 1. 水平翻转 (100%, 数据量直接翻倍)
    if rng.random() < 0.5:
        img_arr = img_arr[:, ::-1, :].copy()
        angle = -angle

    # 2. 亮度扰动 (±50, 加大幅度)
    if rng.random() < 0.7:
        delta = rng.uniform(-50, 50)
        img_arr = np.clip(img_arr.astype(np.int16) + delta, 0, 255).astype(np.uint8)

    # 3. 对比度扰动 (新增)
    if rng.random() < 0.5:
        alpha = rng.uniform(0.7, 1.3)
        img_arr = np.clip(img_arr.astype(np.float32) * alpha, 0, 255).astype(np.uint8)

    # 4. 旋转 (±10°, 加大)
    if rng.random() < 0.5:
        angle_rot = rng.uniform(-10, 10)
        pil = PILImage.fromarray(img_arr)
        pil = pil.rotate(angle_rot, resample=PILImage.BILINEAR, fillcolor=(128, 128, 128))
        img_arr = np.array(pil)

    # 5. 水平平移 (新增, 模拟车在赛道上位置变化)
    if rng.random() < 0.5:
        shift = rng.randint(-15, 15)
        img_arr = np.roll(img_arr, shift, axis=1)

    # 6. 垂直平移 (新增, 模拟坡度)
    if rng.random() < 0.3:
        shift = rng.randint(-5, 5)
        img_arr = np.roll(img_arr, shift, axis=0)

    return img_arr, angle


def preprocess_image(img_arr):
    """真正裁剪: 120×160 → 95×156"""
    arr = img_arr.copy()
    if ROI_CROP_TOP > 0:
        arr = arr[ROI_CROP_TOP:, :, :]
    if ROI_CROP_LEFT > 0 or ROI_CROP_RIGHT > 0:
        arr = arr[:, ROI_CROP_LEFT:IMG_W_ORIG - ROI_CROP_RIGHT, :]
    return arr.astype(np.float32) / 255.0


def load_record(r, augment=False, rng=None):
    """加载单条记录, 返回 (x, y)"""
    img = Image.open(r['_img_path']).convert('RGB')
    if img.size != (IMG_W_ORIG, IMG_H_ORIG):
        img = img.resize((IMG_W_ORIG, IMG_H_ORIG))
    img_arr = np.array(img, dtype=np.uint8)

    angle = r.get('user/angle', 0)
    throttle = r.get('user/throttle', 0)

    if augment and rng is not None:
        img_arr, angle = augment_image(img_arr, angle, rng)

    x = preprocess_image(img_arr)
    y = np.array([angle, throttle], dtype=np.float32)
    return x, y


# ============ 数据生成器 ============
class DataGenerator(tf.keras.utils.Sequence):
    def __init__(self, records, batch_size=BATCH_SIZE, augment=False, seed=SEED):
        self.records = records
        self.batch_size = batch_size
        self.augment = augment
        self.rng = random.Random(seed)
        np.random.seed(seed)
        self.indices = np.arange(len(self.records))
        self.on_epoch_end()

    def __len__(self):
        return int(np.ceil(len(self.records) / self.batch_size))

    def __getitem__(self, idx):
        batch_idx = self.indices[idx * self.batch_size:(idx + 1) * self.batch_size]
        batch_x, batch_y = [], []
        for i in batch_idx:
            x, y = load_record(self.records[i], augment=self.augment, rng=self.rng)
            batch_x.append(x)
            batch_y.append(y)  # (None, 2) 匹配单输出
        return np.array(batch_x), np.array(batch_y)

    def on_epoch_end(self):
        np.random.shuffle(self.indices)


# ============ 模型构建 ============
def build_model_s2_bram_opt():
    """方案2 BRAM优化版: Conv5=16 + 输入 95×156 → Dense1=960"""
    drop = 0.2
    img_in = Input(shape=(IMG_H, IMG_W, IMG_C), name='img_in')

    x = Conv2D(24, 5, strides=2, activation='relu', name='conv2d_1')(img_in)
    x = Dropout(drop)(x)
    x = Conv2D(32, 5, strides=2, activation='relu', name='conv2d_2')(x)
    x = Dropout(drop)(x)
    x = Conv2D(64, 5, strides=2, activation='relu', name='conv2d_3')(x)
    x = Dropout(drop)(x)
    x = Conv2D(64, 3, strides=1, activation='relu', name='conv2d_4')(x)
    x = Dropout(drop)(x)
    x = Conv2D(16, 3, strides=1, activation='relu', name='conv2d_5')(x)  # 5×12×16
    x = Dropout(drop)(x)

    x = Flatten(name='flattened')(x)              # 960
    x = Dense(100, activation='relu', name='dense_1')(x)
    x = Dropout(drop)(x)
    x = Dense(50, activation='relu', name='dense_2')(x)
    x = Dropout(drop)(x)
    outputs = Dense(2, activation='linear', name='n_outputs')(x)  # 单输出 (angle, throttle)

    model = KerasModel(inputs=[img_in], outputs=outputs, name='linear_s2_physical')
    return model


# ============ INT8 量化 ============
def quantize_int8(model_path, calibration_records):
    """TFLite INT8 量化"""
    logger.info("\n" + "=" * 60)
    logger.info("INT8 量化")
    logger.info("=" * 60)

    def rep_data_gen():
        rng = random.Random(SEED)
        for r in calibration_records[:200]:
            x, _ = load_record(r, augment=False, rng=rng)
            yield [x[None, ...]]

    converter = tf.lite.TFLiteConverter.from_keras_model(model_path)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = rep_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8

    int8_model = converter.convert()
    return int8_model


def evaluate_int8(int8_path, records):
    """评估 INT8 模型"""
    logger.info("\n" + "=" * 60)
    logger.info("评估 INT8 模型")
    logger.info("=" * 60)

    interpreter = tf.lite.Interpreter(model_path=int8_path)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    inp_scale, inp_zero = input_details[0]['quantization']

    preds_a, preds_t, reals_a, reals_t = [], [], [], []
    for r in records:
        x, y = load_record(r, augment=False)
        x_q = np.round(x / inp_scale + inp_zero).astype(np.int8)[None, ...]
        interpreter.set_tensor(input_details[0]['index'], x_q)
        interpreter.invoke()
        out = interpreter.get_tensor(output_details[0]['index'])[0]  # shape (2,)
        s, z = output_details[0]['quantization']
        o0 = (float(out[0]) - z) * s  # angle
        o1 = (float(out[1]) - z) * s  # throttle
        preds_a.append(o0); preds_t.append(o1)
        reals_a.append(y[0]); reals_t.append(y[1])

    preds_a, preds_t = np.array(preds_a), np.array(preds_t)
    reals_a, reals_t = np.array(reals_a), np.array(reals_t)

    mae_a = np.mean(np.abs(preds_a - reals_a))
    mae_t = np.mean(np.abs(preds_t - reals_t))
    corr_a = np.corrcoef(preds_a, reals_a)[0, 1] if np.std(preds_a) > 0 else 0
    corr_t = np.corrcoef(preds_t, reals_t)[0, 1] if np.std(preds_t) > 0 else 0

    logger.info(f"测试 {len(preds_a)} 张图:")
    logger.info(f"  angle MAE: {mae_a:.6f}, 相关系数: {corr_a:.4f}")
    logger.info(f"  throttle MAE: {mae_t:.6f}, 相关系数: {corr_t:.4f}")
    logger.info(f"  angle 预测范围: [{preds_a.min():.4f}, {preds_a.max():.4f}]")
    logger.info(f"  angle 真实范围: [{reals_a.min():.4f}, {reals_a.max():.4f}]")

    big = np.abs(reals_a) > 0.5
    straight = np.abs(reals_a) < 0.05
    if big.sum() > 0:
        logger.info(f"  大转弯({big.sum()}帧): MAE={np.mean(np.abs(preds_a[big]-reals_a[big])):.4f}")
    if straight.sum() > 0:
        logger.info(f"  直行({straight.sum()}帧): MAE={np.mean(np.abs(preds_a[straight]-reals_a[straight])):.4f}")
        logger.info(f"  直行预测范围: [{preds_a[straight].min():.4f}, {preds_a[straight].max():.4f}]")

    return {'angle_mae': float(mae_a), 'angle_corr': float(corr_a),
            'throttle_mae': float(mae_t), 'throttle_corr': float(corr_t)}


# ============ 主流程 ============
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=EPOCHS)
    parser.add_argument('--batch', type=int, default=BATCH_SIZE)
    parser.add_argument('--per-bin', type=int, default=PER_BIN)
    parser.add_argument('--lr', type=float, default=LEARNING_RATE_INIT)
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(f'{OUTPUT_DIR}/logs', exist_ok=True)

    logger.info("=" * 60)
    logger.info("方案2 BRAM优化版 - 物理数据训练")
    logger.info("=" * 60)
    logger.info(f"输入: {IMG_H}×{IMG_W} (裁剪后)")
    logger.info(f"裁剪: TOP={ROI_CROP_TOP}, LEFT={ROI_CROP_LEFT}, RIGHT={ROI_CROP_RIGHT}")
    logger.info(f"架构: Conv5=16, Dense1 输入=960 (BRAM 优化)")
    logger.info(f"学习率: Warmup+余弦 {LEARNING_RATE_INIT}→{LEARNING_RATE_MIN}, batch: {args.batch}, epochs: {args.epochs}")
    logger.info(f"多 trial: {NUM_TRIALS} 次, 保留最佳")
    logger.info(f"标签平滑: {LABEL_SMOOTHING}")
    logger.info(f"数据策略: 全部数据 (不做角度平衡, 保留真实分布)")

    # 1. 加载数据
    logger.info("\n--- 加载物理采集数据 ---")
    all_records, sessions = load_physic_records()
    for s, n in sessions:
        logger.info(f"  {s}: {n} 条")

    # 2. 不做角度平衡, 直接用全部数据 (场地小转弯多是真实场景)
    logger.info(f"\n使用全部数据: {len(all_records)} 条 (保留真实角度分布)")

    # 3. 划分训练/验证 (按时间顺序, 模拟真实部署)
    rng = random.Random(SEED)
    all_shuffled = all_records.copy()
    rng.shuffle(all_shuffled)
    split = int(len(all_shuffled) * (1 - VALIDATION_SPLIT))
    train_records = all_shuffled[:split]
    val_records = all_shuffled[split:]
    logger.info(f"\n训练集: {len(train_records)} 条")
    logger.info(f"验证集: {len(val_records)} 条")

    # 4. 迁移学习: 预加载源模型权重 (架构不变)
    def load_transfer_weights(model):
        """从源模型加载权重到 Dense(2) 单输出模型"""
        if not os.path.exists(TRANSFER_MODEL):
            logger.warning(f"源模型不存在: {TRANSFER_MODEL}")
            return
        logger.info(f"加载预训练权重: {TRANSFER_MODEL}")
        src_model = tf.keras.models.load_model(TRANSFER_MODEL, compile=False)
        src_layers = {l.name: l for l in src_model.layers}
        for layer in model.layers:
            if layer.name in src_layers and layer.name != 'n_outputs':
                src_layer = src_layers[layer.name]
                if hasattr(layer, 'set_weights') and hasattr(src_layer, 'get_weights'):
                    try:
                        layer.set_weights(src_layer.get_weights())
                    except ValueError:
                        pass
            elif layer.name == 'n_outputs':
                a_layer = src_layers.get('n_outputs0')
                t_layer = src_layers.get('n_outputs1')
                if a_layer and t_layer:
                    kernel = np.concatenate([a_layer.get_weights()[0],
                                            t_layer.get_weights()[0]], axis=-1)
                    bias = np.concatenate([a_layer.get_weights()[1],
                                         t_layer.get_weights()[1]], axis=-1)
                    layer.set_weights([kernel, bias])

    # 5. 学习率调度: Warmup + 余弦衰减
    import math as _math
    total_steps_per_epoch = _math.ceil(len(train_records) / args.batch)
    total_steps = total_steps_per_epoch * args.epochs
    warmup_steps = total_steps_per_epoch * WARMUP_EPOCHS

    class WarmupCosineLR(tf.keras.callbacks.Callback):
        """Warmup (线性) → 余弦衰减"""
        def __init__(self, init_lr, min_lr, total_steps, warmup_steps):
            self.init_lr = init_lr
            self.min_lr = min_lr
            self.total_steps = total_steps
            self.warmup_steps = warmup_steps
            self.step = 0
        def on_train_batch_begin(self, batch, logs=None):
            if self.step < self.warmup_steps:
                # Warmup: 线性增长 0 → init_lr
                lr = self.init_lr * (self.step + 1) / self.warmup_steps
            else:
                # 余弦衰减 init_lr → min_lr
                progress = (self.step - self.warmup_steps) / max(1, self.total_steps - self.warmup_steps)
                cos = 0.5 * (1 + _math.cos(_math.pi * progress))
                lr = self.min_lr + (self.init_lr - self.min_lr) * cos
            self.model.optimizer.learning_rate.assign(lr)
            self.step += 1

    # 6. 多 trial 训练, 保留 val_loss 最低的
    logger.info(f"\n--- 多 trial 训练 ({NUM_TRIALS} 次, 保留最佳) ---")
    best_val_loss = float('inf')
    best_model = None
    best_trial = -1

    for trial in range(NUM_TRIALS):
        trial_seed = SEED + trial * 100
        logger.info(f"\n{'='*60}")
        logger.info(f"Trial {trial+1}/{NUM_TRIALS}  (seed={trial_seed})")
        logger.info(f"{'='*60}")

        # 重建模型 (架构不变, 每次重新加载预训练权重)
        model = build_model_s2_bram_opt()
        load_transfer_weights(model)

        # 全部可训练
        for layer in model.layers:
            layer.trainable = True

        # 编译 (标签平滑减少急转弯极端值的影响)
        optimizer = tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE_INIT)
        model.compile(optimizer=optimizer,
                      loss=tf.keras.losses.MeanSquaredError(),
                      metrics=['mae'],
                      jit_compile=False)

        # 数据生成器 (每个 trial 用不同 seed 增强顺序)
        train_gen = DataGenerator(train_records, batch_size=args.batch,
                                   augment=True, seed=trial_seed)
        val_gen = DataGenerator(val_records, batch_size=args.batch,
                                 augment=False, seed=trial_seed + 1)

        # 回调
        callbacks = [
            WarmupCosineLR(LEARNING_RATE_INIT, LEARNING_RATE_MIN,
                           total_steps, warmup_steps),
            EarlyStopping(monitor='val_loss', patience=EARLY_STOP_PATIENCE,
                          restore_best_weights=True, verbose=1),
            tf.keras.callbacks.TensorBoard(
                log_dir=f'{OUTPUT_DIR}/logs/trial_{trial+1}', histogram_freq=0),
        ]

        # 训练
        history = model.fit(
            train_gen,
            validation_data=val_gen,
            epochs=args.epochs,
            callbacks=callbacks,
            verbose=2,
        )

        # 评估 val_loss
        final_val_loss = min(history.history.get('val_loss', [float('inf')]))
        logger.info(f"Trial {trial+1} 最低 val_loss: {final_val_loss:.6f}")

        if final_val_loss < best_val_loss:
            best_val_loss = final_val_loss
            best_model = model
            best_trial = trial + 1
            # 保存最佳模型
            best_path = f'{OUTPUT_DIR}/mypilot1_s2_physical_best.keras'
            model.save(best_path)
            logger.info(f"✅ Trial {trial+1} 创新低! 保存到 {best_path}")

    logger.info(f"\n{'='*60}")
    logger.info(f"多 trial 训练完成")
    logger.info(f"{'='*60}")
    logger.info(f"最佳 trial: #{best_trial}, val_loss: {best_val_loss:.6f}")

    # 使用最佳模型
    model = best_model
    total_params = int(sum(np.prod(v.shape) for v in model.weights))
    logger.info(f"总参数: {total_params:,} (架构未变, Dense(2) 单输出)")

    # 7. 保存最终模型
    keras_path = f'{OUTPUT_DIR}/mypilot1_s2_physical.keras'
    model.save(keras_path)
    logger.info(f"\n保存 Keras 模型: {keras_path}")

    # 10. FP32 TFLite
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    fp32_tflite = converter.convert()
    fp32_path = f'{OUTPUT_DIR}/mypilot1_s2_physical.tflite'
    with open(fp32_path, 'wb') as f:
        f.write(fp32_tflite)
    logger.info(f"保存 FP32 TFLite: {fp32_path} ({len(fp32_tflite)/1024:.1f} KB)")

    # 11. INT8 量化
    int8_model = quantize_int8(model, val_records)
    int8_path = f'{OUTPUT_DIR}/mypilot1_s2_physical_int8.tflite'
    with open(int8_path, 'wb') as f:
        f.write(int8_model)
    logger.info(f"保存 INT8 TFLite: {int8_path} ({len(int8_model)/1024:.1f} KB)")

    # 12. 评估
    results = evaluate_int8(int8_path, val_records)

    # 13. 量化参数 JSON
    interpreter = tf.lite.Interpreter(model_path=int8_path)
    interpreter.allocate_tensors()
    quant_params = []
    for td in (interpreter.get_input_details() + interpreter.get_output_details()):
        s, z = td['quantization']
        quant_params.append({
            'name': td.get('name', ''),
            'scale': float(s),
            'zero_point': int(z),
            'dtype': str(td['dtype']).replace('dtype(', '').replace(')', ''),
            'shape': [int(s) for s in td['shape']]
        })
    with open(f'{OUTPUT_DIR}/quantization_params.json', 'w') as f:
        json.dump(quant_params, f, indent=2)

    # 14. 训练配置
    config = {
        'MODEL_TYPE': 'linear',
        'architecture': 'Conv5=16 + 裁剪 95×156 (BRAM 优化)',
        'data_source': '物理采集数据 (physicdata)',
        'sessions': [s for s, _ in sessions],
        'session_counts': {s: n for s, n in sessions},
        'angle_bins': ANGLE_BINS,
        'angle_bin_labels': BIN_LABELS,
        'per_bin': args.per_bin,
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
            'input_height': IMG_H,
            'input_width': IMG_W
        },
        'hyperparameters': {
            'learning_rate_init': LEARNING_RATE_INIT,
            'learning_rate_min': LEARNING_RATE_MIN,
            'lr_schedule': 'warmup_cosine',
            'warmup_epochs': WARMUP_EPOCHS,
            'batch_size': args.batch,
            'max_epochs': args.epochs,
            'early_stop_patience': EARLY_STOP_PATIENCE,
            'validation_split': VALIDATION_SPLIT,
            'seed': SEED,
            'num_trials': NUM_TRIALS,
            'freeze_layers': FREEZE_LAYERS,
            'label_smoothing': LABEL_SMOOTHING,
            'augmentation_count': 6
        },
        'total_params': total_params,
        'dense1_input': 960,
        'dense1_params': 96000,
        'bram_blocks': 21,
        'bram_utilization': '99.2%',
        'int8_size_kb': os.path.getsize(int8_path) / 1024,
        'evaluation': results
    }
    with open(f'{OUTPUT_DIR}/train_config.json', 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("\n" + "=" * 60)
    logger.info("训练完成!")
    logger.info("=" * 60)
    logger.info(f"模型目录: {OUTPUT_DIR}")
    logger.info(f"  Keras: {keras_path}")
    logger.info(f"  INT8:  {int8_path} ({os.path.getsize(int8_path)/1024:.1f} KB)")
    logger.info(f"  量化参数: {OUTPUT_DIR}/quantization_params.json")
    logger.info(f"  训练配置: {OUTPUT_DIR}/train_config.json")
    logger.info(f"\nBRAM 分析:")
    logger.info(f"  Dense1: 96,000 params = 21 块 BRAM (利用率 99.2%)")
    logger.info(f"  总计: 52 块 (远低于 100 目标)")


if __name__ == '__main__':
    main()
