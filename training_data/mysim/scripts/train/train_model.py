#!/usr/bin/env python3
"""
统一模型训练脚本 - 解决 donkey train 的学习率不生效和模型输出恒定问题

核心改进：
1. 不修改 myconfig.py，参数通过命令行传递
2. 强制调用 set_optimizer 设置正确学习率
3. 训练后自动验证模型推理输出，拒绝输出恒定的坏模型
4. 支持平衡采样（多场景等量抽样）

用法:
    python train_model.py --model <path> --tubs <tub1,tub2,...> [options]

示例:
    # 单场景从头训练
    python train_model.py --model models/mypilot.keras --tubs data/scene1

    # 多场景平衡训练
    python train_model.py --model models/mypilot.keras --tubs data/s1,data/s2 \
        --balance min --lr 0.0005 --epochs 50 --crop-top 45

    # 增量训练
    python train_model.py --model models/mypilot.keras --tubs data/s1 \
        --transfer models/mypilot.keras --lr 0.0001 --epochs 15
"""
import os
import sys
import json
import random
import argparse
import logging
import numpy as np
from PIL import Image

# 添加 mysim 到 path 以加载 myconfig
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, MYSIM_DIR)

import donkeycar as dk
from donkeycar.pipeline.types import TubDataset, TubRecord
from donkeycar.pipeline.training import BatchSequence
from donkeycar.utils import get_model_by_type, train_test_split
from donkeycar.parts.interpreter import keras_model_to_tflite

try:
    import tensorflow as tf
    from tensorflow import keras as _keras
    logging.getLogger('tensorflow').setLevel(logging.WARNING)
    # 抑制冗余日志
    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
except ImportError:
    tf = None

logging.basicConfig(level=logging.INFO,
                    format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ============================================================
# 数据加载
# ============================================================

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


def angle_balanced_sample(scene_records, bins=None, seed=42):
    """
    按角度分箱等量抽样,解决急转弯样本不足问题

    将所有场景数据按角度分成若干区间(分箱),
    从每个区间等量抽样,让直行/中弯/急转弯样本数接近

    参数:
        scene_records: {path: [records]} 字典
        bins: 分箱边界列表,默认 [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
              对应: 急左/中左/小左/直行/小右/中右/急右
        seed: 随机种子

    返回:
        平衡后的 records 列表
    """
    rng = random.Random(seed)

    if bins is None:
        bins = [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
        bin_labels = ['急左(<=-0.5)', '中左(-0.5~-0.2)', '小左(-0.2~-0.05)',
                      '直行(-0.05~0.05)', '小右(0.05~0.2)',
                      '中右(0.2~0.5)', '急右(>=0.5)']

    # 合并所有 records,提取角度
    all_records = []
    for records in scene_records.values():
        all_records.extend(records)

    # 按角度分箱
    bin_to_records = {i: [] for i in range(len(bins) - 1)}
    for rec in all_records:
        mode = rec.underlying.get('user/mode', 'user')
        angle = rec.underlying.get('pilot/angle', 0) if mode == 'auto' \
            else rec.underlying.get('user/angle', 0)
        for i in range(len(bins) - 1):
            if bins[i] <= angle < bins[i + 1]:
                bin_to_records[i].append(rec)
                break

    # 统计原始分布
    logger.info(f"=== 角度分箱平衡 ===")
    logger.info(f"原始分布 (总 {len(all_records)} 条):")
    for i, label in enumerate(bin_labels):
        count = len(bin_to_records[i])
        pct = count / len(all_records) * 100 if all_records else 0
        logger.info(f"  {label}: {count} ({pct:.1f}%)")

    # 等量抽样: 每箱取 min(各箱数量) 但至少 100
    counts = [len(v) for v in bin_to_records.values()]
    target_per_bin = min(counts)
    if target_per_bin < 100:
        # 急转弯样本太少,用少数类的全部,其他箱按比例
        target_per_bin = max(min(counts), 100)
        logger.info(f"警告: 最小箱样本数 {min(counts)}, "
                   f"使用 {target_per_bin} 作为目标")
    logger.info(f"每箱目标: {target_per_bin} 条")

    balanced = []
    for i, label in enumerate(bin_labels):
        records_in_bin = bin_to_records[i]
        if len(records_in_bin) > target_per_bin:
            sampled = rng.sample(records_in_bin, target_per_bin)
        else:
            # 样本不足,全部使用(可考虑重复采样)
            sampled = records_in_bin
            if len(sampled) < target_per_bin:
                # 重复采样补足
                extra = rng.choices(records_in_bin,
                                   k=target_per_bin - len(sampled))
                sampled = sampled + extra
                logger.info(f"  {label}: 重复采样补足 "
                           f"({len(records_in_bin)}→{len(sampled)})")
        balanced.extend(sampled)
        logger.info(f"  {label}: 抽样 {len(sampled)} 条")

    rng.shuffle(balanced)
    logger.info(f"平衡后总记录数: {len(balanced)} (原 {len(all_records)})")

    # 统计平衡后分布
    balanced_angles = []
    for rec in balanced:
        mode = rec.underlying.get('user/mode', 'user')
        angle = rec.underlying.get('pilot/angle', 0) if mode == 'auto' \
            else rec.underlying.get('user/angle', 0)
        balanced_angles.append(angle)
    balanced_arr = np.array(balanced_angles)
    logger.info(f"平衡后角度: min={balanced_arr.min():.3f}, "
               f"max={balanced_arr.max():.3f}, "
               f"std={balanced_arr.std():.3f}")
    sharp = (np.abs(balanced_arr) >= 0.5).sum()
    logger.info(f"急转弯比例: {sharp}/{len(balanced_arr)} "
               f"({sharp/len(balanced_arr)*100:.1f}%)")

    return balanced


# ============================================================
# 配置覆盖（不修改 myconfig.py 文件）
# ============================================================

class ConfigOverride:
    """临时覆盖 cfg 对象的属性，不修改 myconfig.py 文件"""

    def __init__(self, cfg):
        self.cfg = cfg
        self._overrides = {}

    def set(self, key, value):
        self._overrides[key] = value
        setattr(self.cfg, key, value)

    def restore(self):
        for key, old_value in self._overrides.items():
            setattr(self.cfg, key, old_value)


# ============================================================
# 训练
# ============================================================

def train_model(cfg, model_path, tub_paths, model_type='linear',
                transfer=None, balance=None, epochs=None,
                verbose=True):
    """
    执行训练，返回训练历史和模型对象

    关键修复：调用 set_optimizer 设置正确学习率
    """
    # 加载数据
    if balance:
        logger.info("=== 加载场景数据（平衡采样）===")
        scene_records = load_scene_records(cfg, tub_paths)
        if len(scene_records) == 0:
            raise ValueError("无可用数据")
        if balance == 'angle':
            all_records = angle_balanced_sample(scene_records)
        else:
            all_records = balanced_sample(scene_records, mode=balance)
    else:
        logger.info("=== 加载场景数据（标准合并）===")
        dataset = TubDataset(config=cfg, tub_paths=tub_paths,
                            seq_size=0)
        all_records = dataset.get_records()
        dataset.close()

    logger.info(f"总记录数: {len(all_records)}")

    # 分割训练/验证集
    training_records, validation_records = train_test_split(
        all_records, shuffle=True,
        test_size=(1. - cfg.TRAIN_TEST_SPLIT))
    logger.info(f"训练集: {len(training_records)} 条")
    logger.info(f"验证集: {len(validation_records)} 条")

    if len(validation_records) == 0:
        raise ValueError("验证集为空，请增加数据或减小 BATCH_SIZE")

    # 创建模型
    _keras.backend.clear_session()
    kl = get_model_by_type('linear', cfg)

    # 通道压缩架构: 替换默认模型
    if model_type in ('s1', 's2'):
        from tensorflow.keras.layers import (Dense, Input, Conv2D, Dropout,
                                              Flatten)
        from tensorflow.keras import Model as KerasModel

        def _conv2d(f, k, s, n):
            return Conv2D(filters=f, kernel_size=(k, k), strides=(s, s),
                          activation='relu', name=f'conv2d_{n}')

        drop = 0.2
        img_in = Input(shape=kl.input_shape, name='img_in')
        x = _conv2d(24, 5, 2, 1)(img_in)
        x = Dropout(drop)(x)
        x = _conv2d(32, 5, 2, 2)(x)
        x = Dropout(drop)(x)
        x = _conv2d(64, 5, 2, 3)(x)
        x = Dropout(drop)(x)
        x = _conv2d(64, 3, 1, 4)(x)
        x = Dropout(drop)(x)

        if model_type == 's1':
            # 方案1: Conv5=32 + 1x1Conv(32→16) + Flatten(1664)
            x = _conv2d(32, 3, 1, 5)(x)
            x = Dropout(drop)(x)
            x = Conv2D(16, 1, strides=1, activation='relu',
                       name='conv_1x1_compress')(x)
            x = Dropout(drop)(x)
        elif model_type == 's2':
            # 方案2: Conv5=16 + Flatten(1664)
            x = _conv2d(16, 3, 1, 5)(x)
            x = Dropout(drop)(x)

        x = Flatten(name='flattened')(x)
        x = Dense(100, activation='relu', name='dense_1')(x)
        x = Dropout(drop)(x)
        x = Dense(50, activation='relu', name='dense_2')(x)
        x = Dropout(drop)(x)
        outputs = [Dense(1, activation='linear',
                         name='n_outputs' + str(i))(x)
                   for i in range(2)]
        custom_model = KerasModel(inputs=[img_in], outputs=outputs,
                                  name=f'linear_{model_type}')
        kl.interpreter.model = custom_model
        kl.interpreter.output_keys = custom_model.output_names
        logger.info(f"使用通道压缩架构: {model_type}")
        logger.info(f"  总参数: "
                    f"{int(sum(np.prod(v.shape) for v in custom_model.weights)):,}")
        for layer in custom_model.layers:
            if layer.name == 'dense_1':
                logger.info(f"  Dense1 参数: {layer.count_params():,} "
                            f"(原始: 665,700)")
                break

    # 关键修复：设置优化器学习率
    # 否则 Keras 用默认 0.001，忽略 myconfig 的 LEARNING_RATE
    kl.set_optimizer('adam', cfg.LEARNING_RATE,
                     getattr(cfg, 'LR_DECAY', 0))
    logger.info(f"优化器: Adam, learning_rate={cfg.LEARNING_RATE}")

    # 增量训练：加载已有权重
    if transfer:
        logger.info(f"加载初始模型: {transfer}")
        kl.load(transfer)
        if getattr(cfg, 'FREEZE_LAYERS', False):
            kl.freeze_first_layers()

    if getattr(cfg, 'PRINT_MODEL_SUMMARY', False):
        kl.interpreter.summary()

    # 验证学习率已正确设置
    kl.compile()
    model = kl.interpreter.model
    actual_lr = float(model.optimizer.learning_rate.numpy()) \
        if hasattr(model.optimizer.learning_rate, 'numpy') \
        else float(model.optimizer.learning_rate)
    logger.info(f"模型实际学习率: {actual_lr:.6f}")
    if abs(actual_lr - cfg.LEARNING_RATE) > 1e-7:
        logger.warning(f"学习率不匹配! 配置={cfg.LEARNING_RATE}, "
                       f"实际={actual_lr}")

    # 创建数据管道
    training_pipe = BatchSequence(kl, cfg, training_records, is_train=True)
    validation_pipe = BatchSequence(kl, cfg, validation_records,
                                    is_train=False)
    tune = tf.data.experimental.AUTOTUNE
    dataset_train = training_pipe.create_tf_data().prefetch(tune)
    dataset_validate = validation_pipe.create_tf_data().prefetch(tune)

    train_size = len(training_pipe)
    val_size = len(validation_pipe)
    logger.info(f"训练步数/epoch: {train_size}, 验证步数: {val_size}")

    # 训练
    logger.info(f"=== 开始训练 (epochs={epochs}) ===")
    history = kl.train(
        model_path=model_path,
        train_data=dataset_train,
        train_steps=train_size,
        batch_size=cfg.BATCH_SIZE,
        validation_data=dataset_validate,
        validation_steps=val_size,
        epochs=epochs,
        verbose=verbose,
        min_delta=cfg.MIN_DELTA,
        patience=cfg.EARLY_STOP_PATIENCE,
        show_plot=getattr(cfg, 'SHOW_PLOT', False))

    # 训练结果
    if history and hasattr(history, 'history'):
        loss = history.history.get('loss', [])
        val_loss = history.history.get('val_loss', [])
        if loss:
            logger.info(f"训练 loss: {loss[0]:.4f} -> {loss[-1]:.4f}")
        if val_loss:
            logger.info(f"验证 loss: {val_loss[0]:.4f} -> {val_loss[-1]:.4f}")

    return kl, history


# ============================================================
# 模型验证
# ============================================================

def verify_model(model_path, tub_paths, cfg, num_samples=5):
    """
    验证模型推理输出是否随输入变化

    返回 (is_valid, details)

    支持模型类型:
    - linear: 单图像输入
    - radar:  图像 + 雷达距离向量双输入
    """
    logger.info("=== 验证模型推理 ===")

    model = _keras.models.load_model(model_path)

    # 从第一个 tub 读取样本
    tub_path = tub_paths[0]
    dataset = TubDataset(config=cfg, tub_paths=[tub_path], seq_size=0)
    records = dataset.get_records()
    dataset.close()

    if len(records) == 0:
        return False, {"error": "无样本可验证"}

    # 检测模型输入类型
    model_input_names = [inp.name for inp in model.inputs] \
        if hasattr(model, 'inputs') and model.inputs else []
    has_radar_input = any('radar' in n for n in model_input_names)
    num_radar_inputs = 13
    if has_radar_input:
        # 从模型层获取 radar 输入维度
        for inp in model.inputs:
            if 'radar' in inp.name:
                try:
                    num_radar_inputs = int(inp.shape[-1])
                except (TypeError, IndexError):
                    pass
                break
    logger.info(f"模型输入: {model_input_names}, "
                f"has_radar={has_radar_input}, "
                f"radar_dim={num_radar_inputs}")

    # CROP 配置
    has_crop = 'CROP' in getattr(cfg, 'TRANSFORMATIONS', [])
    crop_top = getattr(cfg, 'ROI_CROP_TOP', 0)
    crop_bottom = getattr(cfg, 'ROI_CROP_BOTTOM', 0)
    crop_left = getattr(cfg, 'ROI_CROP_LEFT', 0)
    crop_right = getattr(cfg, 'ROI_CROP_RIGHT', 0)

    # 随机选择样本
    rng = random.Random(42)
    sample_indices = rng.sample(range(len(records)),
                               min(num_samples, len(records)))

    predictions = []
    for idx in sample_indices:
        rec = records[idx]
        # 自动驾驶模式: 用 pilot/angle 作为真实值
        mode = rec.underlying.get('user/mode', 'user')
        if mode == 'auto':
            true_angle = rec.underlying.get('pilot/angle', 0)
        else:
            true_angle = rec.underlying.get('user/angle', 0)
        img = rec.image()

        # 应用 CROP
        if has_crop:
            mask = np.zeros(img.shape, dtype=bool)
            h, w = img.shape[:2]
            mask[crop_top:h - crop_bottom,
                 crop_left:w - crop_right, :] = True
            img = np.multiply(img, mask)

        # 归一化
        img_norm = img.astype(np.float32) / 255.0
        img_batch = np.expand_dims(img_norm, axis=0)

        # 构建推理输入
        if has_radar_input:
            radar_arr = np.array(
                rec.underlying.get('radar/dist_array',
                                   [0.0] * num_radar_inputs),
                dtype=np.float32)
            if len(radar_arr) < num_radar_inputs:
                radar_arr = np.pad(radar_arr,
                                   (0, num_radar_inputs - len(radar_arr)))
            elif len(radar_arr) > num_radar_inputs:
                radar_arr = radar_arr[:num_radar_inputs]
            radar_batch = np.expand_dims(radar_arr, axis=0)
            input_dict = {'img_in': img_batch,
                          'radar_in': radar_batch}
            out = model.predict(input_dict, verbose=0)
        else:
            out = model.predict(img_batch, verbose=0)

        if isinstance(out, (list, tuple)):
            pred_angle = float(np.asarray(out[0]).flatten()[0])
        else:
            pred_angle = float(np.asarray(out).flatten()[0])
        predictions.append((true_angle, pred_angle))

    # 分析预测
    pred_angles = [p[1] for p in predictions]
    true_angles = [p[0] for p in predictions]
    pred_range = max(pred_angles) - min(pred_angles)

    logger.info(f"预测角度范围: {pred_range:.6f}")
    for i, (ta, pa) in enumerate(predictions):
        logger.info(f"  样本{i}: 真实={ta:.4f}, 预测={pa:.4f}")

    # 判断模型是否有效
    is_valid = pred_range > 0.05
    details = {
        "pred_range": pred_range,
        "predictions": predictions,
        "is_valid": is_valid,
    }

    # 计算相关系数
    if len(predictions) > 1 and np.std(true_angles) > 0:
        try:
            corr = float(np.corrcoef(true_angles, pred_angles)[0, 1])
            details["correlation"] = corr
            logger.info(f"相关系数: {corr:.4f}")
            if corr > 0.5:
                logger.info("预测方向正确")
            elif corr < -0.5:
                logger.warning("预测方向相反")
            else:
                logger.warning("预测与真实无相关性")
        except Exception:
            pass

    if is_valid:
        logger.info("模型验证通过: 输出随输入变化")
    else:
        logger.error("模型验证失败: 输出几乎恒定（小车会直行）")

    return is_valid, details


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='统一模型训练脚本')
    parser.add_argument('--model', required=True,
                        help='模型保存路径')
    parser.add_argument('--tubs', required=True,
                        help='tub 路径列表，逗号分隔')
    parser.add_argument('--transfer', default=None,
                        help='增量训练时加载的初始模型路径')
    parser.add_argument('--type', default='linear',
                        help='模型类型 (默认 linear)')
    parser.add_argument('--balance', default=None,
                        choices=['min', 'mean', 'angle'],
                        help='平衡采样策略 '
                             '(None=标准合并, '
                             'min/mean=按场景平衡, '
                             'angle=按角度分箱平衡 ★推荐解决急转弯不足)')
    parser.add_argument('--lr', type=float, default=None,
                        help='学习率 (覆盖 myconfig)')
    parser.add_argument('--epochs', type=int, default=None,
                        help='训练 epochs (覆盖 myconfig)')
    parser.add_argument('--batch-size', type=int, default=None,
                        help='batch size (覆盖 myconfig)')
    parser.add_argument('--crop-top', type=int, default=None,
                        help='CROP 上部裁剪行数')
    parser.add_argument('--no-crop', action='store_true',
                        help='禁用 CROP 变换')
    parser.add_argument('--augmentations', default=None,
                        help='数据增强列表，如 "BRIGHTNESS,BLUR"'
                             ' (空字符串=禁用)')
    parser.add_argument('--seed', type=int, default=42,
                        help='随机种子')
    parser.add_argument('--no-verify', action='store_true',
                        help='跳过训练后验证')
    parser.add_argument('--no-tflite', action='store_true',
                        help='不生成 TFLite')
    args = parser.parse_args()

    # 加载基础配置
    cfg = dk.load_config()

    # 临时覆盖配置（不修改 myconfig.py 文件）
    override = ConfigOverride(cfg)

    if args.lr is not None:
        override.set('LEARNING_RATE', args.lr)
    if args.epochs is not None:
        override.set('MAX_EPOCHS', args.epochs)
    if args.batch_size is not None:
        override.set('BATCH_SIZE', args.batch_size)

    # CROP 配置
    if args.no_crop:
        override.set('TRANSFORMATIONS', [])
    elif args.crop_top is not None:
        override.set('TRANSFORMATIONS', ['CROP'])
        override.set('ROI_CROP_TOP', args.crop_top)

    # 数据增强
    if args.augmentations is not None:
        if args.augmentations.strip() == '':
            override.set('AUGMENTATIONS', [])
        else:
            augs = [a.strip() for a in args.augmentations.split(',')
                    if a.strip()]
            override.set('AUGMENTATIONS', augs)

    logger.info("=== 训练配置 ===")
    logger.info(f"  LEARNING_RATE: {cfg.LEARNING_RATE}")
    logger.info(f"  MAX_EPOCHS: {cfg.MAX_EPOCHS}")
    logger.info(f"  BATCH_SIZE: {cfg.BATCH_SIZE}")
    logger.info(f"  TRANSFORMATIONS: {cfg.TRANSFORMATIONS}")
    logger.info(f"  AUGMENTATIONS: {cfg.AUGMENTATIONS}")
    logger.info(f"  ROI_CROP_TOP: {getattr(cfg, 'ROI_CROP_TOP', 0)}")

    # 解析 tub 路径
    tub_paths = [t.strip() for t in args.tubs.split(',') if t.strip()]
    logger.info(f"\n=== 训练数据 ({len(tub_paths)} 个场景) ===")
    for tp in tub_paths:
        logger.info(f"  {tp}")

    # 训练
    try:
        kl, history = train_model(
            cfg=cfg,
            model_path=args.model,
            tub_paths=tub_paths,
            model_type=args.type,
            transfer=args.transfer,
            balance=args.balance,
            epochs=cfg.MAX_EPOCHS,
            verbose=getattr(cfg, 'VERBOSE_TRAIN', True))
    except Exception as e:
        logger.error(f"训练失败: {e}")
        raise

    # TFLite 转换
    if not args.no_tflite and getattr(cfg, 'CREATE_TF_LITE', True):
        base_path, _ = os.path.splitext(args.model)
        tflite_path = f'{base_path}.tflite'
        try:
            keras_model_to_tflite(args.model, tflite_path)
            logger.info(f"TFLite 转换完成: {tflite_path}")
        except Exception as e:
            logger.warning(f"TFLite 转换失败: {e}")

    # 验证模型
    if not args.no_verify:
        logger.info("")
        is_valid, details = verify_model(args.model, tub_paths, cfg)
        if not is_valid:
            logger.error("=" * 60)
            logger.error("模型验证失败！模型输出几乎恒定。")
            logger.error("可能原因：")
            logger.error("  1. 学习率过高（尝试降低 LEARNING_RATE）")
            logger.error("  2. 训练数据不足或标签分布不均")
            logger.error("  3. 训练未收敛（增加 epochs）")
            logger.error("  4. CROP 配置错误（检查 ROI_CROP_TOP）")
            logger.error("=" * 60)
            sys.exit(1)
        else:
            logger.info("模型验证通过")

    # 保存训练配置（供推理时还原）
    train_config = {
        "MODEL_TYPE": args.type,
        "TRANSFORMATIONS": getattr(cfg, 'TRANSFORMATIONS', []),
        "POST_TRANSFORMATIONS": getattr(cfg, 'POST_TRANSFORMATIONS', []),
        "ROI_CROP_TOP": getattr(cfg, 'ROI_CROP_TOP', 0),
        "ROI_CROP_BOTTOM": getattr(cfg, 'ROI_CROP_BOTTOM', 0),
        "ROI_CROP_LEFT": getattr(cfg, 'ROI_CROP_LEFT', 0),
        "ROI_CROP_RIGHT": getattr(cfg, 'ROI_CROP_RIGHT', 0),
        "LEARNING_RATE": cfg.LEARNING_RATE,
        "MAX_EPOCHS": cfg.MAX_EPOCHS,
        "BALANCE": args.balance,
    }
    config_path = os.path.join(os.path.dirname(args.model),
                               os.path.splitext(
                                   os.path.basename(args.model))[0] +
                               '.train_config.json')
    with open(config_path, 'w') as f:
        json.dump(train_config, f, indent=2, default=str)
    logger.info(f"训练配置已保存: {config_path}")

    logger.info("\n=== 训练完成 ===")
    logger.info(f"模型: {args.model}")


if __name__ == '__main__':
    main()
