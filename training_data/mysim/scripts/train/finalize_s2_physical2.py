#!/usr/bin/env python3
"""
physicaldata2 训练被打断后的后处理脚本
- 加载 best.keras (Trial 1, val_loss 0.0321)
- 完成 INT8 量化、评估、保存配置
"""
import os
import sys
import json
import random
import logging
import numpy as np
from PIL import Image

from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, MYSIM_DIR)

# 复用原训练脚本的常量和函数
import importlib.util
spec = importlib.util.spec_from_file_location(
    'train_s2_physical2',
    f'{MYSIM_DIR}/scripts/train/train_s2_physical2.py'
)
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

import tensorflow as tf
from tensorflow.keras.layers import (Dense, Input, Conv2D, Dropout, Flatten)
from tensorflow.keras import Model as KerasModel

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

BEST_KERAS = f'{tr.OUTPUT_DIR}/mypilot1_s2_physical_best.keras'
KERAS_OUT = f'{tr.OUTPUT_DIR}/mypilot1_s2_physical.keras'
FP32_OUT = f'{tr.OUTPUT_DIR}/mypilot1_s2_physical.tflite'
INT8_OUT = f'{tr.OUTPUT_DIR}/mypilot1_s2_physical_int8.tflite'


def main():
    logger.info("=" * 60)
    logger.info("physicaldata2 训练后处理 (INT8 量化 + 评估)")
    logger.info("=" * 60)

    # 1. 加载数据 (用于量化校准和评估)
    logger.info("\n--- 加载物理采集数据 ---")
    all_records, sessions = tr.load_physic_records()
    for s, n in sessions:
        logger.info(f"  {s}: {n} 条")

    rng = random.Random(tr.SEED)
    all_shuffled = all_records.copy()
    rng.shuffle(all_shuffled)
    split = int(len(all_shuffled) * (1 - tr.VALIDATION_SPLIT))
    train_records = all_shuffled[:split]
    val_records = all_shuffled[split:]
    logger.info(f"训练集: {len(train_records)} 条")
    logger.info(f"验证集: {len(val_records)} 条")

    # 2. 加载 best 模型
    logger.info(f"\n--- 加载 best 模型: {BEST_KERAS} ---")
    model = tf.keras.models.load_model(BEST_KERAS, compile=False)
    total_params = int(sum(np.prod(v.shape) for v in model.weights))
    logger.info(f"总参数: {total_params:,}")

    # 3. 评估 Keras 模型在验证集上的表现
    logger.info("\n--- Keras 模型验证集评估 ---")
    preds_a, preds_t, reals_a, reals_t = [], [], [], []
    for r in val_records:
        x, y = tr.load_record(r, augment=False)
        out = model.predict(x[None, ...], verbose=0)[0]
        preds_a.append(out[0]); preds_t.append(out[1])
        reals_a.append(y[0]); reals_t.append(y[1])

    preds_a = np.array(preds_a); preds_t = np.array(preds_t)
    reals_a = np.array(reals_a); reals_t = np.array(reals_t)

    keras_mae_a = float(np.mean(np.abs(preds_a - reals_a)))
    keras_corr_a = float(np.corrcoef(preds_a, reals_a)[0, 1]) if np.std(preds_a) > 0 else 0
    logger.info(f"Keras - angle MAE: {keras_mae_a:.6f}, 相关系数: {keras_corr_a:.4f}")
    logger.info(f"Keras - angle 预测范围: [{preds_a.min():.4f}, {preds_a.max():.4f}]")
    logger.info(f"Keras - throttle MAE: {float(np.mean(np.abs(preds_t - reals_t))):.6f}")

    big = np.abs(reals_a) > 0.5
    straight = np.abs(reals_a) < 0.05
    if big.sum() > 0:
        logger.info(f"Keras - 大转弯({big.sum()}帧): MAE={float(np.mean(np.abs(preds_a[big]-reals_a[big]))):.4f}")
    if straight.sum() > 0:
        logger.info(f"Keras - 直行({straight.sum()}帧): MAE={float(np.mean(np.abs(preds_a[straight]-reals_a[straight]))):.4f}")
        logger.info(f"Keras - 直行预测范围: [{preds_a[straight].min():.4f}, {preds_a[straight].max():.4f}]")

    # 4. 复制 best.keras 到最终模型名
    if not os.path.exists(KERAS_OUT):
        import shutil
        shutil.copy(BEST_KERAS, KERAS_OUT)
        logger.info(f"复制 best.keras -> {KERAS_OUT}")

    # 5. FP32 TFLite
    logger.info("\n--- 生成 FP32 TFLite ---")
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    fp32_tflite = converter.convert()
    with open(FP32_OUT, 'wb') as f:
        f.write(fp32_tflite)
    logger.info(f"FP32 TFLite: {FP32_OUT} ({len(fp32_tflite)/1024:.1f} KB)")

    # 6. INT8 量化
    logger.info("\n--- INT8 量化 ---")
    int8_model = tr.quantize_int8(model, val_records)
    with open(INT8_OUT, 'wb') as f:
        f.write(int8_model)
    logger.info(f"INT8 TFLite: {INT8_OUT} ({len(int8_model)/1024:.1f} KB)")

    # 7. 评估 INT8
    results = tr.evaluate_int8(INT8_OUT, val_records)

    # 8. 量化参数 JSON
    interpreter = tf.lite.Interpreter(model_path=INT8_OUT)
    interpreter.allocate_tensors()
    quant_params = []
    for td in (interpreter.get_input_details() + interpreter.get_output_details()):
        s, z = td['quantization']
        quant_params.append({
            'name': td.get('name', ''),
            'scale': float(s),
            'zero_point': int(z),
            'dtype': str(td['dtype']).replace('dtype(', '').replace(')', ''),
            'shape': [int(s_) for s_ in td['shape']]
        })
    with open(f'{tr.OUTPUT_DIR}/quantization_params.json', 'w') as f:
        json.dump(quant_params, f, indent=2)

    # 9. 训练配置
    config = {
        'MODEL_TYPE': 'linear',
        'architecture': 'Conv5=16 + 裁剪 95×156 (BRAM 优化)',
        'data_source': '物理采集数据 physicaldata2 (独立训练版)',
        'sessions': [s for s, _ in sessions],
        'session_counts': {s: n for s, n in sessions},
        'total_records': len(all_records),
        'angle_bins': tr.ANGLE_BINS,
        'angle_bin_labels': tr.BIN_LABELS,
        'per_bin': tr.PER_BIN,
        'data_strategy': '不做角度平衡, 使用全部数据 (保留真实角度分布)',
        'augmentation': {
            'horizontal_flip': '50% (angle 取反)',
            'brightness': '±50',
            'contrast': '0.7~1.3',
            'rotation': '±10°',
            'horizontal_shift': '±15',
            'vertical_shift': '±5'
        },
        'crop': {
            'ROI_CROP_TOP': tr.ROI_CROP_TOP,
            'ROI_CROP_LEFT': tr.ROI_CROP_LEFT,
            'ROI_CROP_RIGHT': tr.ROI_CROP_RIGHT,
            'method': 'crop (直接裁剪, 非白色填充)',
            'input_height': tr.IMG_H,
            'input_width': tr.IMG_W
        },
        'hyperparameters': {
            'learning_rate_init': tr.LEARNING_RATE_INIT,
            'learning_rate_min': tr.LEARNING_RATE_MIN,
            'lr_schedule': 'warmup_cosine',
            'warmup_epochs': tr.WARMUP_EPOCHS,
            'batch_size': tr.BATCH_SIZE,
            'max_epochs': tr.EPOCHS,
            'early_stop_patience': tr.EARLY_STOP_PATIENCE,
            'validation_split': tr.VALIDATION_SPLIT,
            'seed': tr.SEED,
            'num_trials': tr.NUM_TRIALS,
            'freeze_layers': tr.FREEZE_LAYERS,
            'label_smoothing': tr.LABEL_SMOOTHING,
            'augmentation_count': 6
        },
        'transfer_model': tr.TRANSFER_MODEL,
        'training_status': '被打断于 Trial 2 Epoch 56, 使用 Trial 1 best (val_loss 0.0321)',
        'total_params': total_params,
        'dense1_input': 960,
        'dense1_params': 96000,
        'bram_blocks': 21,
        'bram_utilization': '99.2%',
        'keras_evaluation': {
            'angle_mae': keras_mae_a,
            'angle_corr': keras_corr_a,
            'angle_pred_range': [float(preds_a.min()), float(preds_a.max())],
            'angle_real_range': [float(reals_a.min()), float(reals_a.max())]
        },
        'int8_size_kb': os.path.getsize(INT8_OUT) / 1024,
        'evaluation': results
    }
    with open(f'{tr.OUTPUT_DIR}/train_config.json', 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("\n" + "=" * 60)
    logger.info("后处理完成!")
    logger.info("=" * 60)
    logger.info(f"模型目录: {tr.OUTPUT_DIR}")
    logger.info(f"  Keras: {KERAS_OUT}")
    logger.info(f"  FP32 TFLite: {FP32_OUT}")
    logger.info(f"  INT8 TFLite: {INT8_OUT}")
    logger.info(f"  train_config.json")
    logger.info(f"  quantization_params.json")


if __name__ == '__main__':
    main()
