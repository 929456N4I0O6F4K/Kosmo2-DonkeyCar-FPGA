#!/usr/bin/env python3
"""
池化架构对比训练脚本

目的：验证用 GAP / GMP / 1x1Conv 替代 Flatten 后的精度损失是否可接受
- 原始模型: Flatten(8x13x64=6656) -> Dense(100) -> Dense(50) -> Dense(1)x2
  参数量: 817,028 (dense_1 占 665,600 = 81%)
- GAP 模型: GAP(64) -> Dense(100) -> Dense(50) -> Dense(1)x2
  参数量: ~157,828 (dense_1 仅 6,500 = 4.1%)
  结果: angle 输出恒定, GAP 丢失空间位置信息 -> 失败
- GMP 模型: GMP(64) -> Dense(100) -> Dense(50) -> Dense(1)x2
  参数量: ~157,828
  保留最强响应位置, 可能更适合车道线检测
- 1x1Conv 模型: 1x1Conv(64->64, stride=4) -> Flatten(64) -> Dense(100)...
  参数量: ~161,000
  可学习空间降维, 保留部分位置信息

FPGA BRAM 节省: Dense 层权重从 2.54MB 降至 ~0.03MB (98.8%)
"""
import os
import sys
import json
import random
import logging
import numpy as np
from PIL import Image

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.layers import (Dense, Input, Conv2D, Dropout,
                                     GlobalAveragePooling2D,
                                     GlobalMaxPooling2D, Flatten,
                                     Reshape)
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

# ============ 路径配置 ============
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


# ============ 模型定义 ============
def conv2d(filters, kernel, strides, layer_num):
    return Conv2D(filters=filters,
                  kernel_size=(kernel, kernel),
                  strides=(strides, strides),
                  activation='relu',
                  name='conv2d_' + str(layer_num))


def build_cnn_base(img_in, drop=0.2):
    """共享 CNN 层 (5 层 Conv2D, 与原始 PilotNet 完全一致)"""
    x = conv2d(24, 5, 2, 1)(img_in)
    x = Dropout(drop)(x)
    x = conv2d(32, 5, 2, 2)(x)
    x = Dropout(drop)(x)
    x = conv2d(64, 5, 2, 3)(x)
    x = Dropout(drop)(x)
    x = conv2d(64, 3, 1, 4)(x)
    x = Dropout(drop)(x)
    x = conv2d(64, 3, 1, 5)(x)
    x = Dropout(drop)(x)
    return x


def build_dense_head(x, num_outputs=2, drop=0.2):
    """共享 Dense 层"""
    x = Dense(100, activation='relu', name='dense_1')(x)
    x = Dropout(drop)(x)
    x = Dense(50, activation='relu', name='dense_2')(x)
    x = Dropout(drop)(x)
    outputs = []
    for i in range(num_outputs):
        outputs.append(
            Dense(1, activation='linear', name='n_outputs' + str(i))(x))
    return outputs


def build_pool_model(pool_type='gap', input_shape=(120, 160, 3),
                     num_outputs=2):
    """
    池化架构模型

    pool_type:
      'gap'  - Global Average Pooling (已证明失败: angle 恒定)
      'gmp'  - Global Max Pooling (保留最强响应位置)
      'avg+max' - GAP + GMP 拼接 (128 维, 信息更丰富)
      '1x1conv' - 1x1 Conv stride=4 降维后 Flatten (可学习降维)
    """
    drop = 0.2
    img_in = Input(shape=input_shape, name='img_in')
    x = build_cnn_base(img_in, drop)

    if pool_type == 'gap':
        x = GlobalAveragePooling2D(name='gap')(x)
    elif pool_type == 'gmp':
        x = GlobalMaxPooling2D(name='gmp')(x)
    elif pool_type == 'avg+max':
        gap = GlobalAveragePooling2D(name='gap')(x)
        gmp = GlobalMaxPooling2D(name='gmp')(x)
        from tensorflow.keras.layers import Concatenate
        x = Concatenate(name='pool_concat')([gap, gmp])
    elif pool_type == '1x1conv':
        # 用 1x1 卷积将 8x13x64 降维到 2x4x64=512, 再 Flatten
        x = Conv2D(64, 1, strides=4, activation='relu',
                   name='conv_1x1_reduce')(x)
        x = Flatten(name='flattened')(x)
    else:
        raise ValueError(f"Unknown pool_type: {pool_type}")

    outputs = build_dense_head(x, num_outputs, drop)
    model = Model(inputs=[img_in], outputs=outputs,
                  name=f'linear_{pool_type.replace("+", "_")}')
    return model


# ============ 数据加载 ============
def load_all_records(cfg, tub_paths):
    """加载所有场景的 records"""
    all_records = []
    for tp in tub_paths:
        if not os.path.isdir(tp):
            logger.warning(f"跳过不存在的 tub: {tp}")
            continue
        dataset = TubDataset(config=cfg, tub_paths=[tp], seq_size=0)
        records = dataset.get_records()
        dataset.close()
        all_records.extend(records)
        logger.info(f"  {os.path.basename(tp)}: {len(records)} 条")
    return all_records


def preprocess_image(img_arr):
    """CROP mask + 归一化"""
    arr = img_arr.copy()
    arr[:ROI_CROP_TOP, :, :] = 255
    return arr.astype(np.float32) / 255.0


# ============ 训练 ============
def train_pool_model(pool_type='gmp', epochs=EPOCHS):
    """训练指定池化类型的模型"""
    model_name = f'mypilot_{pool_type}'
    model_path = os.path.join(MODEL_DIR, f'{model_name}.keras')

    logger.info("=" * 70)
    logger.info(f"训练 {pool_type.upper()} 架构模型")
    logger.info("=" * 70)

    cfg = dk.load_config()
    cfg.BATCH_SIZE = BATCH_SIZE
    cfg.MAX_EPOCHS = epochs
    cfg.LEARNING_RATE = LEARNING_RATE
    cfg.TRANSFORMATIONS = ['CROP']
    cfg.ROI_CROP_TOP = ROI_CROP_TOP

    # 加载数据
    logger.info("=== 加载训练数据 ===")
    all_records = load_all_records(cfg, TUBS)
    logger.info(f"总记录数: {len(all_records)}")

    if len(all_records) == 0:
        raise ValueError("无训练数据")

    # 分割
    train_records, val_records = train_test_split(
        all_records, shuffle=True, test_size=1. - cfg.TRAIN_TEST_SPLIT)
    logger.info(f"训练集: {len(train_records)} 条, 验证集: {len(val_records)} 条")

    # 构建模型
    keras.backend.clear_session()
    model = build_pool_model(pool_type, INPUT_SHAPE, num_outputs=2)
    model.summary()

    total_params = int(sum(np.prod(v.shape) for v in model.weights))
    logger.info(f"{pool_type.upper()} 模型总参数: {total_params:,} "
                f"({total_params*4/1048576:.2f} MB)")

    # 编译
    optimizer = keras.optimizers.Adam(learning_rate=LEARNING_RATE)
    model.compile(optimizer=optimizer, loss='mse')

    # 数据管道
    kl = dk.utils.get_model_by_type('linear', cfg)
    kl.interpreter.model = model
    kl.interpreter._model = model
    kl.compile()
    kl.set_optimizer('adam', LEARNING_RATE, 0)

    train_pipe = BatchSequence(kl, cfg, train_records, is_train=True)
    val_pipe = BatchSequence(kl, cfg, val_records, is_train=False)

    tune = tf.data.experimental.AUTOTUNE
    ds_train = train_pipe.create_tf_data().prefetch(tune)
    ds_val = val_pipe.create_tf_data().prefetch(tune)

    train_steps = len(train_pipe)
    val_steps = len(val_pipe)
    logger.info(f"训练步数/epoch: {train_steps}, 验证步数: {val_steps}")

    # 回调
    callbacks = [
        keras.callbacks.EarlyStopping(
            monitor='val_loss', patience=10, restore_best_weights=True,
            min_delta=0.0001),
        keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss', factor=0.5, patience=5, min_lr=1e-6),
    ]

    # 训练
    logger.info(f"=== 开始训练 (epochs={epochs}, lr={LEARNING_RATE}) ===")
    history = model.fit(
        ds_train,
        steps_per_epoch=train_steps,
        validation_data=ds_val,
        validation_steps=val_steps,
        epochs=epochs,
        callbacks=callbacks,
        verbose=1)

    # 保存
    model.save(model_path)
    logger.info(f"模型已保存: {model_path}")

    # 训练配置
    train_config = {
        "MODEL_TYPE": "linear",
        "TRANSFORMATIONS": ["CROP"],
        "ROI_CROP_TOP": ROI_CROP_TOP,
        "LEARNING_RATE": LEARNING_RATE,
        "MAX_EPOCHS": epochs,
        "ARCHITECTURE": f"{pool_type} pooling",
    }
    config_path = model_path.replace('.keras', '.train_config.json')
    with open(config_path, 'w') as f:
        json.dump(train_config, f, indent=2)

    # 训练结果
    if history and hasattr(history, 'history'):
        loss = history.history.get('loss', [])
        val_loss = history.history.get('val_loss', [])
        if loss and val_loss:
            logger.info(f"训练 loss: {loss[0]:.4f} -> {loss[-1]:.4f}")
            logger.info(f"验证 loss: {val_loss[0]:.4f} -> {val_loss[-1]:.4f}")

    return model, history


# ============ 精度对比 ============
def compare_models(pool_type='gmp'):
    """对比原始模型和池化模型的推理输出"""
    model_name = f'mypilot_{pool_type}'
    pool_model_path = os.path.join(MODEL_DIR, f'{model_name}.keras')

    logger.info("\n" + "=" * 70)
    logger.info(f"精度对比: 原始(Flatten) vs {pool_type.upper()}")
    logger.info("=" * 70)

    # 参数量对比
    orig_model = tf.keras.models.load_model(ORIG_MODEL_PATH, compile=False)
    pool_model = tf.keras.models.load_model(pool_model_path, compile=False)

    orig_params = int(sum(np.prod(v.shape) for v in orig_model.weights))
    pool_params = int(sum(np.prod(v.shape) for v in pool_model.weights))
    logger.info(f"原始模型参数: {orig_params:,} ({orig_params*4/1048576:.2f} MB)")
    logger.info(f"{pool_type.upper()} 模型参数: {pool_params:,} "
                f"({pool_params*4/1048576:.2f} MB)")
    logger.info(f"参数减少: {orig_params - pool_params:,} "
                f"({(orig_params - pool_params) / orig_params * 100:.1f}%)")

    # 加载测试图像
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
        X_test[i] = preprocess_image(arr)

    # 推理
    y_orig = orig_model.predict(X_test, verbose=0, batch_size=32)
    y_pool = pool_model.predict(X_test, verbose=0, batch_size=32)

    orig_angle = y_orig[0].flatten()
    orig_throttle = y_orig[1].flatten()
    pool_angle = y_pool[0].flatten()
    pool_throttle = y_pool[1].flatten()

    # 统计
    results = {"pool_type": pool_type,
                "original_params": orig_params,
                "pool_params": pool_params}

    for name, orig, pool in [("转向角 angle", orig_angle, pool_angle),
                              ("油门 throttle", orig_throttle, pool_throttle)]:
        abs_err = np.abs(orig - pool)
        mae = float(np.mean(abs_err))
        max_err = float(np.max(abs_err))
        if np.std(orig) > 0 and np.std(pool) > 0:
            corr = float(np.corrcoef(orig, pool)[0, 1])
        else:
            corr = 0.0

        logger.info(f"\n  --- {name} ---")
        logger.info(f"    原始范围: [{orig.min():.4f}, {orig.max():.4f}]")
        logger.info(f"    {pool_type.upper()}范围: [{pool.min():.4f}, {pool.max():.4f}]")
        logger.info(f"    MAE:      {mae:.6f}")
        logger.info(f"    Max误差:  {max_err:.6f}")
        logger.info(f"    相关系数: {corr:.6f}")
        logger.info(f"    误差<0.01: {np.mean(abs_err < 0.01) * 100:.1f}%")
        logger.info(f"    误差<0.05: {np.mean(abs_err < 0.05) * 100:.1f}%")
        logger.info(f"    误差<0.10: {np.mean(abs_err < 0.10) * 100:.1f}%")

        key = name.split()[-1]
        results[key] = {"mae": mae, "max_err": max_err, "corr": corr,
                        "orig_range": [float(orig.min()), float(orig.max())],
                        "pool_range": [float(pool.min()), float(pool.max())]}

    # 逐样本对比 (前 10 个)
    logger.info(f"\n  前 10 个样本对比:")
    logger.info(f"  {'#':<4} {'Orig_ang':<12} {'Pool_ang':<12} "
                f"{'diff':<10} {'Orig_thr':<12} {'Pool_thr':<12} {'diff':<10}")
    for i in range(min(10, len(X_test))):
        da = orig_angle[i] - pool_angle[i]
        dt = orig_throttle[i] - pool_throttle[i]
        logger.info(f"  {i:<4} {orig_angle[i]:<12.6f} {pool_angle[i]:<12.6f} "
                    f"{da:<10.6f} {orig_throttle[i]:<12.6f} "
                    f"{pool_throttle[i]:<12.6f} {dt:<10.6f}")

    # 可行性判断
    angle_mae = results['angle']['mae']
    angle_corr = results['angle']['corr']
    throttle_corr = results['throttle']['corr']

    logger.info("\n" + "=" * 70)
    logger.info("结论")
    logger.info("=" * 70)
    logger.info(f"  参数减少: {(orig_params - pool_params) / orig_params * 100:.1f}% "
                f"({orig_params:,} -> {pool_params:,})")
    logger.info(f"  Angle:    MAE={angle_mae:.6f}, corr={angle_corr:.4f}")
    logger.info(f"  Throttle: corr={throttle_corr:.4f}")

    if angle_corr > 0.95 and angle_mae < 0.05:
        logger.info(f"  -> {pool_type.upper()} 架构可行！精度损失在可接受范围")
    elif angle_corr > 0.8:
        logger.info(f"  -> {pool_type.upper()} 架构基本可行，精度有一定损失")
    else:
        logger.info(f"  -> {pool_type.upper()} 架构精度损失较大")

    # 保存结果
    results_path = f'{MYSIM_DIR}/artifacts/quantization/{pool_type}_comparison_results.json'
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"\n  结果已保存: {results_path}")

    return results


# ============ 主函数 ============
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='池化架构模型训练与对比')
    parser.add_argument('--pool-type', default='gmp',
                        choices=['gap', 'gmp', 'avg+max', '1x1conv'],
                        help='池化类型 (默认 gmp)')
    parser.add_argument('--train-only', action='store_true',
                        help='仅训练，不对比')
    parser.add_argument('--compare-only', action='store_true',
                        help='仅对比，不训练')
    parser.add_argument('--epochs', type=int, default=EPOCHS,
                        help=f'训练 epochs (默认 {EPOCHS})')
    parser.add_argument('--all', action='store_true',
                        help='训练所有方案并对比')
    args = parser.parse_args()

    if args.all:
        # 训练所有方案
        all_results = {}
        for pt in ['gmp', 'avg+max', '1x1conv']:
            print(f"\n{'#' * 70}")
            print(f"# 训练方案: {pt.upper()}")
            print(f"{'#' * 70}")
            train_pool_model(pool_type=pt, epochs=args.epochs)
            r = compare_models(pool_type=pt)
            all_results[pt] = r

        # 汇总
        print(f"\n{'=' * 70}")
        print("汇总对比")
        print(f"{'=' * 70}")
        print(f"{'方案':<12} {'参数量':<10} {'angle_MAE':<12} "
              f"{'angle_corr':<12} {'throttle_corr':<14}")
        print('-' * 60)
        for pt, r in all_results.items():
            print(f"{pt:<12} {r['pool_params']:<10,} "
                  f"{r['angle']['mae']:<12.6f} "
                  f"{r['angle']['corr']:<12.4f} "
                  f"{r['throttle']['corr']:<14.4f}")
    else:
        if not args.compare_only:
            train_pool_model(pool_type=args.pool_type, epochs=args.epochs)

        if not args.train_only:
            compare_models(pool_type=args.pool_type)
