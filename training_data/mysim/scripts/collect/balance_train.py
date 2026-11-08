#!/usr/bin/env python3
"""
平衡采样训练：从每个场景抽样相同数量记录，消除数据不平衡导致的场景偏置。

用法:
    python balance_train.py --model <model_path> --tubs <tub1,tub2,...>
                             [--balance-mode min|mean] [--seed 42]
                             [--transfer <prev_model>] [--epochs N]

与 donkey train 的区别：
  - donkey train 加载所有 records 合并训练，大数据场景主导
  - 本脚本从每个 tub 等量抽样，确保每个场景贡献相同
"""
import os
import sys
import random
import argparse
import logging

# 添加 mysim 到 path 以加载 myconfig
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, MYSIM_DIR)

import donkeycar as dk
from donkeycar.pipeline.types import TubDataset
from donkeycar.pipeline.training import BatchSequence
from donkeycar.utils import get_model_by_type, train_test_split
from donkeycar.parts.interpreter import keras_model_to_tflite

try:
    import tensorflow as tf
    logging.getLogger('tensorflow').setLevel(logging.WARNING)
except ImportError:
    tf = None

logging.basicConfig(level=logging.INFO,
                    format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def load_scene_records(cfg, tub_paths):
    """逐个加载每个场景的 records，返回 {path: [records]} 字典"""
    scene_records = {}
    for tp in tub_paths:
        tp = os.path.expanduser(tp)
        if not os.path.isdir(tp):
            logger.warning(f"跳过不存在的 tub: {tp}")
            continue
        dataset = TubDataset(config=cfg, tub_paths=[tp], seq_size=0)
        records = dataset.get_records()
        scene_records[tp] = records
        dataset.close()
        logger.info(f"  {os.path.basename(tp)}: {len(records)} 条")
    return scene_records


def balanced_sample(scene_records, mode='min', seed=42):
    """从每个场景等量抽样，返回合并后的 records 列表"""
    rng = random.Random(seed)
    counts = [len(r) for r in scene_records.values()]
    logger.info(f"各场景记录数: {counts}")

    if mode == 'min':
        sample_size = min(counts)
    elif mode == 'mean':
        sample_size = int(sum(counts) / len(counts))
    else:
        sample_size = min(counts)

    logger.info(f"平衡模式: {mode}, 每场景采样: {sample_size} 条")

    balanced = []
    for path, records in scene_records.items():
        if len(records) > sample_size:
            sampled = rng.sample(records, sample_size)
        else:
            sampled = records
        balanced.extend(sampled)
        logger.info(f"  {os.path.basename(path)}: 抽样 {len(sampled)} 条")

    rng.shuffle(balanced)
    logger.info(f"合并后总记录数: {len(balanced)} (原 {sum(counts)})")
    return balanced


def main():
    parser = argparse.ArgumentParser(description='平衡采样训练')
    parser.add_argument('--model', required=True, help='模型保存路径')
    parser.add_argument('--tubs', required=True,
                        help='tub 路径列表，逗号分隔')
    parser.add_argument('--transfer', default=None,
                        help='增量训练时加载的初始模型路径')
    parser.add_argument('--type', default='linear', help='模型类型')
    parser.add_argument('--balance-mode', default='min',
                        choices=['min', 'mean'], help='平衡策略')
    parser.add_argument('--seed', type=int, default=42, help='随机种子')
    parser.add_argument('--epochs', type=int, default=None,
                        help='覆盖 myconfig 的 MAX_EPOCHS')
    args = parser.parse_args()

    cfg = dk.load_config()
    logger.info("=== 配置 ===")
    logger.info(f"  LEARNING_RATE: {cfg.LEARNING_RATE}")
    logger.info(f"  MAX_EPOCHS: {cfg.MAX_EPOCHS}")
    logger.info(f"  BATCH_SIZE: {cfg.BATCH_SIZE}")
    logger.info(f"  TRANSFORMATIONS: {cfg.TRANSFORMATIONS}")
    logger.info(f"  AUGMENTATIONS: {getattr(cfg, 'AUGMENTATIONS', [])}")

    if args.epochs:
        cfg.MAX_EPOCHS = args.epochs
        logger.info(f"  覆盖 MAX_EPOCHS -> {cfg.MAX_EPOCHS}")

    tub_paths = [t.strip() for t in args.tubs.split(',') if t.strip()]
    logger.info(f"\n=== 加载场景数据 ({len(tub_paths)} 个) ===")
    scene_records = load_scene_records(cfg, tub_paths)
    if len(scene_records) == 0:
        logger.error("无可用数据")
        sys.exit(1)

    logger.info(f"\n=== 平衡采样 ===")
    balanced_records = balanced_sample(
        scene_records, mode=args.balance_mode, seed=args.seed)

    logger.info(f"\n=== 分割训练/验证集 ===")
    training_records, validation_records = train_test_split(
        balanced_records, shuffle=True,
        test_size=(1. - cfg.TRAIN_TEST_SPLIT))
    logger.info(f"  训练集: {len(training_records)} 条")
    logger.info(f"  验证集: {len(validation_records)} 条")

    if tf is not None:
        from tensorflow import keras as _keras
        _keras.backend.clear_session()
    kl = get_model_by_type(args.type, cfg)
    # 关键：设置优化器学习率（否则 Keras 用默认 0.001，忽略 myconfig 的 LEARNING_RATE）
    kl.set_optimizer('adam', cfg.LEARNING_RATE, getattr(cfg, 'LR_DECAY', 0))
    logger.info(f"优化器: Adam, learning_rate={cfg.LEARNING_RATE}")
    if args.transfer:
        logger.info(f"加载初始模型: {args.transfer}")
        kl.load(args.transfer)
        if getattr(cfg, 'FREEZE_LAYERS', False):
            kl.freeze_first_layers()

    if getattr(cfg, 'PRINT_MODEL_SUMMARY', False):
        kl.interpreter.summary()

    training_pipe = BatchSequence(kl, cfg, training_records, is_train=True)
    validation_pipe = BatchSequence(kl, cfg, validation_records, is_train=False)

    tune = tf.data.experimental.AUTOTUNE
    dataset_train = training_pipe.create_tf_data().prefetch(tune)
    dataset_validate = validation_pipe.create_tf_data().prefetch(tune)

    train_size = len(training_pipe)
    val_size = len(validation_pipe)
    assert val_size > 0, "验证集不足，减小 BATCH_SIZE 或增加数据"

    logger.info(f"\n=== 开始训练 ===")
    logger.info(f"  训练步数/epoch: {train_size}")
    logger.info(f"  验证步数: {val_size}")
    logger.info(f"  epochs: {cfg.MAX_EPOCHS}")

    history = kl.train(
        model_path=args.model,
        train_data=dataset_train,
        train_steps=train_size,
        batch_size=cfg.BATCH_SIZE,
        validation_data=dataset_validate,
        validation_steps=val_size,
        epochs=cfg.MAX_EPOCHS,
        verbose=getattr(cfg, 'VERBOSE_TRAIN', True),
        min_delta=cfg.MIN_DELTA,
        patience=cfg.EARLY_STOP_PATIENCE,
        show_plot=getattr(cfg, 'SHOW_PLOT', False))

    # 生成 tflite
    if getattr(cfg, 'CREATE_TF_LITE', True):
        base_path, _ = os.path.splitext(args.model)
        tflite_path = f'{base_path}.tflite'
        keras_model_to_tflite(args.model, tflite_path)
        logger.info(f"TFLite 转换完成: {tflite_path}")

    logger.info("\n=== 训练完成 ===")
    logger.info(f"模型: {args.model}")
    if history and hasattr(history, 'history'):
        loss = history.history.get('loss', [])
        val_loss = history.history.get('val_loss', [])
        if loss:
            logger.info(f"  训练 loss: {loss[0]:.4f} -> {loss[-1]:.4f}")
        if val_loss:
            logger.info(f"  验证 loss: {val_loss[0]:.4f} -> {val_loss[-1]:.4f}")


if __name__ == '__main__':
    main()
