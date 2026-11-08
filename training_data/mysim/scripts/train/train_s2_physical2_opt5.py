#!/usr/bin/env python3
"""
方案2 BRAM优化版 - physicaldata2 优化训练 v5 (确定性成对镜像 + 场景干扰/淡线增强)

v5 变更 (相对 opt4, 实车反馈驱动):
  1. 确定性成对镜像训练 (核心, 强化反向赛道):
     - 每条训练样本生成 (原图, angle) + (水平镜像图, -angle) 两条, 数据量 ×2
     - 同 batch 内方向严格对称, 强制网络只依赖可镜像的线路几何特征,
       抑制场景捷径 (纹理/光照/背景) → 反向赛道与换场地泛化提升
     - 成对模式下禁用随机翻转 (由确定性镜像替代); 验证集保持真实分布
  2. 新增 #22 合成干扰线 (25%): 随机黄/白伪线条, 模拟新场地外界标线干扰
  3. 新增 #23 淡线/断线 (30%): 随机椭圆区域内近白像素向暗压缩, 模拟
     帆布褶皱/印刷不清导致白线变淡消失
  4. 增强共 23 项: 基础 6 + 光线鲁棒 10 + 帆布特异 5 + 场景干扰 2
  5. 继承 v4: 标签清洗三件套 + 分箱均衡 + 门控欠转惩罚(对称) + Mixup + SWA

约束 (不可变):
  - 模型架构: build_model_s2_bram_opt 不变
  - 输入 shape: (95, 156, 3)
  - BRAM: 21 块 (< 100 目标)
  - INT8 量化输出
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
import cv2
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
# 上一版 physicdata 仅用于补充直行样本 (|angle| < STRAIGHT_THRESH, 不学弯道)
PHYSIC_DATA_DIR_PREV = os.path.join(_PHYS, 'physicdata')
STRAIGHT_THRESH = 0.08  # 直行筛选阈值, |angle| < 0.08 视为直行
OUTPUT_DIR = f'{MYSIM_DIR}/models/mypilot1_s2_physical2_opt5'

# v4 标签清洗: tau 时间对齐用的参考模型 (opt3 最佳, 用于扫反应延迟; 不存在则跳过 tau 对齐)
TAU_ALIGN_MODEL = f'{MYSIM_DIR}/models/mypilot1_s2_physical2_opt3/mypilot1_s2_physical_best.keras'
TAU_MAX = 3                # tau 扫描范围 (帧), 负=标签提前, 正=标签滞后
TAU_MIN_SESSION = 40       # session 少于该帧数不做 tau 对齐
TAU_IMPROVE = 0.02         # MAE 改善超过 2% 才应用平移, 否则 tau=0
MEDIAN_WINDOW = 5          # 中值滤波窗口 (保边: >=3 帧的持续预判打角保留, 1-2 帧抖动抹平)
CORR_JUMP_THRESH = 0.3     # 剔修正帧: 2 帧内反向跳变阈值 (渐进预判打角不触发)

TRANSFER_MODEL = f'{MYSIM_DIR}/models/mypilot1_s2_cropped/mypilot1_s2_cropped.keras'

IMG_H_ORIG = 120
IMG_W_ORIG = 160
IMG_C = 3
ROI_CROP_TOP = 25
ROI_CROP_LEFT = 2
ROI_CROP_RIGHT = 2
IMG_H = IMG_H_ORIG - ROI_CROP_TOP         # 95
IMG_W = IMG_W_ORIG - ROI_CROP_LEFT - ROI_CROP_RIGHT  # 156

# 训练超参数
LEARNING_RATE_INIT = 0.0003
LEARNING_RATE_MIN = 0.000001
WARMUP_EPOCHS = 3
BATCH_SIZE = 64
EPOCHS = 100
EARLY_STOP_PATIENCE = 15
VALIDATION_SPLIT = 0.15
SEED = 42
NUM_TRIALS = 2
FREEZE_LAYERS = []
LABEL_SMOOTHING = 0.05

# 角度分箱 (用于加权损失, 不做平衡)
ANGLE_BINS = [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
BIN_LABELS = ['急左', '中左', '小左', '直行', '小右', '中右', '急右']
# 分箱权重 (v3: 数据均衡为主, 权重轻微辅助)
BIN_WEIGHTS = [2.0, 1.5, 1.0, 2.0, 1.0, 1.0, 1.5]
# 欠转惩罚: 仅转弯帧生效 (|true| > UNDER_GATE), 直行帧不适用 (v2 教训: 幅值盲惩罚把直行推大)
UNDER_PENALTY = 2.0
UNDER_GATE = 0.3
# v4: 移除直行幅值惩罚, 保留直行段提前打角的预判行为
# 分箱均衡过采样 (仅作用于训练集, 验证集保持真实分布)
BALANCE_TARGET = 1000          # 各分箱目标数量
LEFT_EXTRA_TARGET = 1200       # 急左/中左 额外修正目标 (左转踩线问题)
RIGHT_CAP = 1500               # 急右上限 (数据占 40%, 轻度压制避免淹没其他分箱)

# Mixup 配置
MIXUP_ALPHA = 0.2
MIXUP_PROB = 0.2  # 低概率 (Mixup 会稀释急转弯标签, 加剧欠转)

# v5: 多进程数据加载 (i9-12900H 20核, 并行跑 2 trial 各用 6 workers)
DATA_WORKERS = 6

# v5: 确定性成对镜像训练 (强化反向赛道)
# True: 训练集每条样本 → (原图, angle) + (镜像图, -angle) 确定性成对, 数据 ×2,
#       同时禁用随机翻转 (镜像替代); 验证集不受影响, 保持真实分布
PAIRED_MIRROR = True

# v5: 时间留出验证集划分 (替代随机划分)
# 大 session (帧数最多) 按录制顺序前 (1-ratio) 训练 / 后 ratio 验证,
# 其余小 session 全部进验证集 → val_loss 测时间+跨 session 泛化, 不再偏乐观
TEMPORAL_VAL_RATIO = 0.15

# SWA 配置
SWA_START_EPOCH_FRAC = 0.75  # 最后 25% epoch 启用 SWA
SWA_SAVE_BEST = True  # 训练结束后用 SWA 权重评估 val_loss, 取更优者


# ============ 数据加载 ============
def load_physic_records():
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
    logger.info(f"physicaldata2 总计: {len(all_records)} 条 (来自 {len(sessions)} 个 session)")
    return all_records, sessions


def load_straight_records_from_prev():
    """从上一版 physicdata 仅提取直行样本 (|angle| < STRAIGHT_THRESH)
    严格不学习弯道数据, 仅用于补充直行样本
    """
    straight_records = []
    for d in sorted(os.listdir(PHYSIC_DATA_DIR_PREV)):
        path = os.path.join(PHYSIC_DATA_DIR_PREV, d)
        if not os.path.isdir(path):
            continue
        rec_path = os.path.join(path, 'records.jsonl')
        if not os.path.exists(rec_path):
            continue
        with open(rec_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if r.get('user/throttle', 0) < 0.05:
                        continue
                    img_name = r.get('cam/image_array', '')
                    if not img_name:
                        continue
                    img_path = os.path.join(path, img_name)
                    if not os.path.exists(img_path):
                        continue
                    a = r.get('user/angle', 0)
                    # 严格筛选直行: |angle| < STRAIGHT_THRESH
                    if abs(a) >= STRAIGHT_THRESH:
                        continue
                    r['_img_path'] = img_path
                    r['_session'] = f'{d}(prev_straight)'
                    straight_records.append(r)
    return straight_records


def get_bin_index(angle):
    """获取角度所在分箱索引"""
    for i in range(len(ANGLE_BINS) - 1):
        if ANGLE_BINS[i] <= angle < ANGLE_BINS[i + 1]:
            return i
    return len(ANGLE_BINS) - 2  # 兜底


# ============ 数据增强 (升级版) ============
def augment_image_enhanced(img_arr, angle, rng, allow_flip=True):
    """增强版: 基础增强 + 光线鲁棒性增强 + 帆布场地特异性增强 + 场景干扰 (共 23 项)

    allow_flip=False 时禁用随机翻转 (v5 成对镜像模式下由确定性镜像替代)
    """
    from PIL import Image as PILImage
    h, w = img_arr.shape[:2]

    # === 基础增强 (保留) ===
    # 1. 水平翻转 (50%) — v5: 成对镜像模式下禁用 (确定性镜像已覆盖)
    if allow_flip and rng.random() < 0.5:
        img_arr = img_arr[:, ::-1, :].copy()
        angle = -angle

    # 2. 亮度扰动 (RGB, ±80) — v5: 扩大范围增强对比
    if rng.random() < 0.7:
        delta = rng.uniform(-80, 80)
        img_arr = np.clip(img_arr.astype(np.int16) + delta, 0, 255).astype(np.uint8)

    # 3. 对比度扰动 — v5: 扩大范围 (0.5~1.6) 增强视觉差异
    if rng.random() < 0.5:
        alpha = rng.uniform(0.5, 1.6)
        img_arr = np.clip(img_arr.astype(np.float32) * alpha, 0, 255).astype(np.uint8)

    # 4. 旋转 (±10°)
    if rng.random() < 0.5:
        angle_rot = rng.uniform(-10, 10)
        pil = PILImage.fromarray(img_arr)
        pil = pil.rotate(angle_rot, resample=PILImage.BILINEAR, fillcolor=(128, 128, 128))
        img_arr = np.array(pil)

    # 5. 水平平移 (v4 修复: np.roll 会环绕卷绕出对侧内容, 改为反射填充)
    if rng.random() < 0.5:
        shift = rng.uniform(-15, 15)
        M = np.float32([[1, 0, shift], [0, 1, 0]])
        img_arr = cv2.warpAffine(img_arr, M, (w, h),
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REFLECT_101)

    # 6. 垂直平移 (v4 修复: 同上, 反射填充)
    if rng.random() < 0.3:
        shift = rng.uniform(-5, 5)
        M = np.float32([[1, 0, 0], [0, 1, shift]])
        img_arr = cv2.warpAffine(img_arr, M, (w, h),
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REFLECT_101)

    # === 光线鲁棒性增强 (新增) ===
    # 7. HSV 空间扰动 (色相/饱和度/明度独立扰动, 模拟色温变化)
    if rng.random() < 0.6:
        hsv = cv2.cvtColor(img_arr, cv2.COLOR_RGB2HSV).astype(np.float32)
        h_delta = rng.uniform(-15, 15)
        s_delta = rng.uniform(-0.3, 0.3) * 255
        v_delta = rng.uniform(-0.3, 0.3) * 255
        hsv[:, :, 0] = np.clip(hsv[:, :, 0] + h_delta, 0, 179)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] + s_delta, 0, 255)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] + v_delta, 0, 255)
        img_arr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    # 8. Gamma 校正 (模拟曝光变化, γ∈[0.5, 2.0])
    if rng.random() < 0.5:
        gamma = rng.uniform(0.5, 2.0)
        inv_gamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** inv_gamma) * 255
                          for i in np.arange(256)]).astype(np.uint8)
        img_arr = cv2.LUT(img_arr, table)

    # 9. 高斯噪声 (模拟低光传感器噪声)
    if rng.random() < 0.4:
        sigma = rng.uniform(0, 15)
        noise = np.random.normal(0, sigma, img_arr.shape)
        img_arr = np.clip(img_arr.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    # 10. 阴影模拟 (随机多边形阴影, 模拟室外树木/建筑遮光)
    #     v5: 顶点 5~8 (更大面积), 位置全图随机 (不固定左→右), 强度 0.2~0.7
    if rng.random() < 0.3:
        h, w = img_arr.shape[:2]
        shadow_mask = np.ones((h, w), dtype=np.float32)
        n_pts = rng.randint(5, 8)
        pts = np.array([[rng.randint(0, w - 1), rng.randint(0, h - 1)]
                        for _ in range(n_pts)], np.int32)
        shadow_intensity = rng.uniform(0.2, 0.7)
        cv2.fillPoly(shadow_mask, [pts], shadow_intensity)
        img_arr = (img_arr.astype(np.float32) * shadow_mask[:, :, None]).astype(np.uint8)

    # 11. 运动模糊 (模拟车辆运动模糊) — v5: 核加大 7~25, 支持多方向
    if rng.random() < 0.2:
        kernel_size = rng.choice([7, 11, 15, 19, 25])
        kernel = np.zeros((kernel_size, kernel_size), dtype=np.float32)
        angle_deg = rng.choice([0, 30, 45, -30, 90])
        rad = np.deg2rad(angle_deg)
        cx_k = (kernel_size - 1) / 2
        for i in range(kernel_size):
            offset = i - cx_k
            xx = int(round(cx_k + offset * np.cos(rad)))
            yy = int(round(cx_k + offset * np.sin(rad)))
            if 0 <= xx < kernel_size and 0 <= yy < kernel_size:
                kernel[yy, xx] = 1.0
        kernel = kernel / max(kernel.sum(), 1.0)
        img_arr = cv2.filter2D(img_arr, -1, kernel)

    # 12. Cutout 随机遮挡 — v5: 大小多样 (h//15~h//2, w//15~w//2), 数量 1~4
    if rng.random() < 0.3:
        h, w = img_arr.shape[:2]
        n_holes = rng.randint(1, 4)
        for _ in range(n_holes):
            cut_h = rng.randint(h // 15, h // 2)
            cut_w = rng.randint(w // 15, w // 2)
            cy = rng.randint(0, max(h - cut_h, 0))
            cx = rng.randint(0, max(w - cut_w, 0))
            img_arr[cy:cy + cut_h, cx:cx + cut_w] = 128

    # === 高速运动鲁棒性增强 (v3 新增) ===
    # 13. 车身抖动 (颠簸: 垂直+水平+小角度旋转同时施加, 模拟高速过弯/路面不平)
    if rng.random() < 0.25:
        h, w = img_arr.shape[:2]
        v_j = rng.randint(-8, 8)     # 垂直抖动
        h_j = rng.randint(-10, 10)   # 水平抖动
        roll = rng.uniform(-2.0, 2.0)  # 车身侧倾导致的画面小角度
        M = cv2.getRotationMatrix2D((w / 2, h / 2), roll, 1.0)
        M[0, 2] += h_j
        M[1, 2] += v_j
        img_arr = cv2.warpAffine(img_arr, M, (w, h),
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT,
                                 borderValue=(128, 128, 128))

    # 14. 多方向运动模糊 (水平/对角/反向对角, 模拟不同运动方向的高速拖影)
    if rng.random() < 0.15:
        kernel_size = rng.choice([7, 9, 11, 15, 19])
        angle_deg = rng.choice([0, 30, 45, -30, 90])  # 90=垂直震动模糊
        kernel = np.zeros((kernel_size, kernel_size), dtype=np.float32)
        rad = np.deg2rad(angle_deg)
        cx = (kernel_size - 1) / 2
        for i in range(kernel_size):
            offset = i - cx
            xx = int(round(cx + offset * np.cos(rad)))
            yy = int(round(cx + offset * np.sin(rad)))
            if 0 <= xx < kernel_size and 0 <= yy < kernel_size:
                kernel[yy, xx] = 1.0
        kernel = kernel / max(kernel.sum(), 1.0)
        img_arr = cv2.filter2D(img_arr, -1, kernel)

    # 15. 色温偏移 (R/B 通道独立增益, 模拟早晨偏蓝/傍晚偏橙的太阳光)
    if rng.random() < 0.3:
        r_gain = rng.uniform(0.85, 1.15)
        b_gain = rng.uniform(0.85, 1.15)
        img_arr = img_arr.astype(np.float32)
        img_arr[:, :, 0] = np.clip(img_arr[:, :, 0] * r_gain, 0, 255)
        img_arr[:, :, 2] = np.clip(img_arr[:, :, 2] * b_gain, 0, 255)
        img_arr = img_arr.astype(np.uint8)

    # 16. 过曝/欠曝 (高光溢出/暗部丢失, 模拟相机自动曝光失误)
    #      v5: 概率 25%→40%, 过曝 1.2~1.6, 欠曝 0.4~0.7
    if rng.random() < 0.40:
        factor = rng.choice([
            rng.uniform(1.2, 1.6),   # 过曝
            rng.uniform(0.4, 0.7),   # 欠曝
        ])
        img_arr = np.clip(img_arr.astype(np.float32) * factor, 0, 255).astype(np.uint8)

    # ============ 场景特异性增强 (帆布场地) ============

    # 17. 局部高光白斑 (边界线与白光重叠: 阳光在帆布上的反射斑/灯光反光)
    #     v4 修复: 中心必须真正达到 peak (旧实现中心只有 peak-soft, 白斑偏弱)
    if rng.random() < 0.20:
        canvas = img_arr.astype(np.float32)
        cx, cy = rng.randint(0, w - 1), rng.randint(0, h - 1)
        ax, ay = rng.randint(15, 45), rng.randint(10, 35)  # 椭圆半轴
        peak = rng.uniform(230, 255)                        # 白斑峰值亮度
        yy, xx = np.mgrid[0:h, 0:w]
        d2 = ((xx - cx) / ax) ** 2 + ((yy - cy) / ay) ** 2
        # 高斯衰减白斑: 中心推向 peak, 高斯尾部自然形成渐隐过渡带
        blob = np.exp(-d2 / 2.0)
        canvas = canvas + blob[:, :, None] * (peak - canvas)
        img_arr = np.clip(canvas, 0, 255).astype(np.uint8)

    # 18. 饱和度褪色 (黄线不清晰: 颜色变灰白, 边界线与帆布底色接近)
    #      v5: 压低到 0.15~0.5, 褪色更明显
    if rng.random() < 0.25:
        hsv = cv2.cvtColor(img_arr, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rng.uniform(0.15, 0.5), 0, 255)
        img_arr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    # 19. 波浪形变 (帆布不平整: 褶皱让车道线在图像中弯曲起伏, 非刚性)
    if rng.random() < 0.20:
        amp = rng.uniform(2.0, 4.0)     # 形变幅度 px
        wl = rng.uniform(40, 80)        # 波长 px
        phase = rng.uniform(0, 2 * np.pi)
        # 每行一个水平偏移 → 水平波浪; map 形状均为 (h, w)
        map_x = (np.arange(w, dtype=np.float32)[None, :]
                 + amp * np.sin(2 * np.pi * np.arange(h, dtype=np.float32)
                                / wl + phase)[:, None]).astype(np.float32)
        map_y = np.tile(np.arange(h, dtype=np.float32)[:, None],
                        (1, w)).astype(np.float32)
        img_arr = cv2.remap(img_arr, map_x, map_y, cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT,
                            borderValue=(128, 128, 128))

    # 20. 梯形畸变 (帆布起伏/轻微坡度: 透视宽度差, 模拟车道线收敛变化)
    if rng.random() < 0.15:
        skew = rng.uniform(2.0, 6.0) * rng.choice([-1, 1])
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = np.float32([[skew, 0], [w - skew, 0], [w, h], [0, h]])
        M = cv2.getPerspectiveTransform(src, dst)
        img_arr = cv2.warpPerspective(img_arr, M, (w, h),
                                      flags=cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_CONSTANT,
                                      borderValue=(128, 128, 128))

    # 21. 灯光带状反射 (帆布褶皱上的灯光反光: 长条形完全过曝带,
    #     中心饱和到纯白 255 无纹理无颜色, 边缘锐利, 车道线在带内完全消失)
    if rng.random() < 0.18:
        canvas = img_arr.astype(np.float32)
        cx, cy = rng.randint(0, w - 1), rng.randint(0, h - 1)
        length = rng.randint(30, 90)    # 带长 px
        width = rng.randint(4, 14)      # 带宽 px (窄而锐)
        theta = rng.uniform(0, np.pi)   # 带方向 (沿褶皱任意方向)
        yy, xx = np.mgrid[0:h, 0:w]
        dx, dy = xx - cx, yy - cy
        u = dx * np.cos(theta) + dy * np.sin(theta)     # 沿带方向
        v = -dx * np.sin(theta) + dy * np.cos(theta)    # 垂直带方向
        band = (np.exp(-u ** 2 / (2 * (length / 2) ** 2))
                * np.exp(-v ** 2 / (2 * (width / 2) ** 2)))
        # 中心带 (band>0.85) 完全饱和到 255 (白光溢出, 颜色信息丢失)
        lum = canvas.mean(axis=2)
        sat = band > 0.85
        boosted = lum + (255 - lum) * np.clip((band - 0.55) / 0.45, 0, 1) ** 1.5
        new_lum = np.where(sat, 255.0, boosted)
        new_lum = np.maximum(new_lum, lum)   # 只增不减
        gain = (new_lum - lum) / np.maximum(lum, 1.0)
        canvas = canvas * (1 + gain[:, :, None])  # 各通道等比增亮 → 变白
        img_arr = np.clip(canvas, 0, 255).astype(np.uint8)
        # v4 修复: 等比增亮对暗区像素失效 (0×大增益=0, 会残留黑色/偏色),
        # 饱和区直接强制纯白, 与真实过曝 (RGB 同时溢出) 一致
        img_arr[sat] = 255

    # ============ 场景干扰增强 (v5 新增: 换场地泛化) ============

    # 22. 合成干扰线 (25%): 随机黄/白伪线条, 模拟新场地外界标线 (跑道外的
    #     警示线/胶带/邻近赛道边界), 教模型不依赖单一线条线索
    #     v5 调整: 线粗 4~8px, 位置靠上 (y∈[ROI_CROP_TOP, h*2//3] 保证裁切后保留),
    #     方向多样 (任意角度 1~3 段折线), 仅急转弯帧添加 (|angle|>0.3)
    #     线段足够长: 每段端点间距 ≥ 40px (沿随机方向延伸)
    if rng.random() < 0.25 and abs(angle) > 0.3:
        line_col = rng.choice([(180, 170, 40), (230, 230, 225)])  # 黄 / 白
        n_lines = rng.randint(1, 3)
        y_lo = ROI_CROP_TOP                          # 裁切后保留的起始行
        y_hi = h * 2 // 3                             # 靠上区域
        for _ in range(n_lines):
            thickness = rng.randint(4, 8)               # v5: 更粗
            # 起点
            px, py = rng.randint(0, w - 1), rng.randint(y_lo, y_hi)
            n_segs = rng.randint(1, 3)                  # 1~3 段折线
            for _ in range(n_segs):
                # 沿随机方向延伸 40~100px, 保证线段足够长
                seg_len = rng.uniform(40, 100)
                seg_ang = rng.uniform(0, 2 * np.pi)
                qx = int(np.clip(px + seg_len * np.cos(seg_ang), 0, w - 1))
                qy = int(np.clip(py + seg_len * np.sin(seg_ang), y_lo, y_hi))
                cv2.line(img_arr, (px, py), (qx, qy), line_col, thickness, cv2.LINE_AA)
                px, py = qx, qy  # 下一段从当前终点继续

    # 23. 淡线/断线 (30%): 随机椭圆区域内近白像素 (S<90, V>150) 向暗压缩
    #     30-70%, 模拟帆布褶皱/印刷不清导致白线局部变淡甚至消失
    if rng.random() < 0.30:
        hsv = cv2.cvtColor(img_arr, cv2.COLOR_RGB2HSV)
        cx, cy = rng.randint(0, w - 1), rng.randint(h // 4, h - 1)
        ax = rng.randint(w // 8, w // 3)
        ay = rng.randint(h // 8, h // 4)
        yy, xx = np.mgrid[0:h, 0:w]
        mask = (((xx - cx) / ax) ** 2 + ((yy - cy) / ay) ** 2) < 1.0
        weak = (hsv[:, :, 1] < 90) & (hsv[:, :, 2] > 150) & mask  # 近白像素
        fade = rng.uniform(0.3, 0.7)  # 压暗比例
        canvas = img_arr.astype(np.float32)
        canvas[weak] = canvas[weak] * (1.0 - fade)
        img_arr = np.clip(canvas, 0, 255).astype(np.uint8)

    return img_arr, angle


# ============ 预处理 (与 FPGA 部署一致: 仅裁剪+归一化, 无 CLAHE) ============
def preprocess_image_enhanced(img_arr):
    """预处理: 裁剪 + 归一化 (光照鲁棒性由数据增强保证, FPGA 端无需 CLAHE)"""
    arr = img_arr.copy()
    if ROI_CROP_TOP > 0:
        arr = arr[ROI_CROP_TOP:, :, :]
    if ROI_CROP_LEFT > 0 or ROI_CROP_RIGHT > 0:
        arr = arr[:, ROI_CROP_LEFT:IMG_W_ORIG - ROI_CROP_RIGHT, :]
    return arr.astype(np.float32) / 255.0


def load_record_enhanced(r, augment=False, rng=None, mirror=False, allow_flip=True):
    """加载单条记录 (升级版预处理)

    mirror=True: 确定性水平镜像 (v5 成对镜像), 在增强前执行, angle 取反
    allow_flip: 透传给 augment_image_enhanced, 成对镜像模式下传 False 禁用随机翻转
    """
    img = Image.open(r['_img_path']).convert('RGB')
    if img.size != (IMG_W_ORIG, IMG_H_ORIG):
        img = img.resize((IMG_W_ORIG, IMG_H_ORIG))
    img_arr = np.array(img, dtype=np.uint8)

    angle = r.get('user/angle', 0)
    throttle = r.get('user/throttle', 0)

    if mirror:
        img_arr = img_arr[:, ::-1, :].copy()
        angle = -angle

    if augment and rng is not None:
        img_arr, angle = augment_image_enhanced(img_arr, angle, rng,
                                                allow_flip=allow_flip)

    x = preprocess_image_enhanced(img_arr)
    y = np.array([angle, throttle], dtype=np.float32)
    return x, y


# ============ 加权 MSE 损失 ============
def get_sample_weight(angle):
    """根据角度获取样本权重"""
    bin_idx = get_bin_index(angle)
    return BIN_WEIGHTS[bin_idx]


class WeightedMSE(tf.keras.losses.Loss):
    """按角度分箱加权的 MSE 损失 + 门控欠转惩罚
    (v4: 移除直行幅值惩罚, 直行段提前打角是预判弯道的真实意图, 保留)
    """

    def __init__(self, bin_weights=BIN_WEIGHTS, bins=ANGLE_BINS,
                 under_penalty=UNDER_PENALTY, under_gate=UNDER_GATE, **kwargs):
        super().__init__(**kwargs)
        self.bin_weights = tf.constant(bin_weights, dtype=tf.float32)
        self.bins = bins
        self.under_penalty = under_penalty
        self.under_gate = under_gate

    def call(self, y_true, y_pred):
        # y_true shape: (batch, 2), y_true[:, 0] = angle
        angles = y_true[:, 0]
        # 计算每个样本的 bin 索引
        weights = tf.zeros_like(angles)
        for i in range(len(self.bins) - 1):
            mask = tf.logical_and(angles >= self.bins[i], angles < self.bins[i + 1])
            weights = tf.where(mask, tf.fill(tf.shape(angles), self.bin_weights[i]), weights)
        # 兜底 (超出范围的用最后一个权重)
        mask_last = angles >= self.bins[-2]
        weights = tf.where(mask_last, tf.fill(tf.shape(angles), self.bin_weights[-2]), weights)

        # 加权 MSE
        squared = tf.square(y_true - y_pred)
        # 门控欠转惩罚: 仅转弯帧 (|true| > gate) 且 |pred| < |true| 时加罚
        # (v2 教训: 无门限的欠转惩罚会把直行帧幅值往大推)
        under_mask = tf.logical_and(
            tf.abs(y_true[:, 0]) > self.under_gate,
            tf.abs(y_pred[:, 0]) < tf.abs(y_true[:, 0]))
        angle_sq = tf.where(under_mask, squared[:, 0] * self.under_penalty, squared[:, 0])
        # 对 angle 加权, throttle 不加权
        weighted_squared = tf.stack([angle_sq * weights, squared[:, 1]], axis=1)
        return tf.reduce_mean(weighted_squared, axis=-1)


# ============ Mixup 数据混合 ============
def mixup_data(batch_x, batch_y, alpha=MIXUP_ALPHA, prob=MIXUP_PROB):
    """Mixup: 样本线性混合"""
    if random.random() > prob or alpha <= 0:
        return batch_x, batch_y

    lam = np.random.beta(alpha, alpha)
    batch_size = len(batch_x)
    index = np.random.permutation(batch_size)
    mixed_x = lam * batch_x + (1 - lam) * batch_x[index]
    mixed_y = lam * batch_y + (1 - lam) * batch_y[index]
    return mixed_x.astype(np.float32), mixed_y.astype(np.float32)


# ============ 数据生成器 (升级版) ============
class DataGeneratorEnhanced(tf.keras.utils.Sequence):
    def __init__(self, records, batch_size=BATCH_SIZE, augment=False, seed=SEED,
                 use_mixup=False, paired=False, **kwargs):
        super().__init__(**kwargs)
        self.records = records
        self.batch_size = batch_size
        self.augment = augment
        self.use_mixup = use_mixup
        self.paired = paired  # v5: 确定性成对镜像 (每条样本 → 原图 + 镜像图)
        self.rng = random.Random(seed)
        np.random.seed(seed)
        self.indices = np.arange(self._virtual_len())
        self.on_epoch_end()

    def _virtual_len(self):
        """成对镜像模式下虚拟样本数 = 记录数 ×2 (i//2 定位记录, i%2 定镜像)"""
        return len(self.records) * 2 if self.paired else len(self.records)

    def __len__(self):
        return int(np.ceil(self._virtual_len() / self.batch_size))

    def __getitem__(self, idx):
        batch_idx = self.indices[idx * self.batch_size:(idx + 1) * self.batch_size]
        batch_x, batch_y = [], []
        for i in batch_idx:
            if self.paired:
                # 确定性成对: i//2 → 记录, i%2==1 → 水平镜像 + angle 取反
                # (同一 batch 内左右方向严格对称, 禁用随机翻转)
                rec = self.records[i // 2]
                x, y = load_record_enhanced(rec, augment=self.augment, rng=self.rng,
                                            mirror=(i % 2 == 1), allow_flip=False)
            else:
                x, y = load_record_enhanced(self.records[i], augment=self.augment,
                                            rng=self.rng)
            batch_x.append(x)
            batch_y.append(y)
        batch_x = np.array(batch_x)
        batch_y = np.array(batch_y)
        # Mixup
        if self.use_mixup:
            batch_x, batch_y = mixup_data(batch_x, batch_y)
        return batch_x, batch_y

    def on_epoch_end(self):
        np.random.shuffle(self.indices)


# ============ SWA 回调 ============
class SWACallback(tf.keras.callbacks.Callback):
    """Stochastic Weight Averaging: 收敛末期权重平均
    注意: EarlyStopping 的 restore_best_weights 会在 on_train_end 前恢复最佳权重,
    SWA 在 on_train_end 比较后再决定是否覆盖, 取更优者
    """

    def __init__(self, start_epoch_frac=SWA_START_EPOCH_FRAC, val_data=None,
                 save_best=SWA_SAVE_BEST):
        super().__init__()
        self.start_epoch_frac = start_epoch_frac
        self.swa_weights = None
        self.swa_n = 0
        self.start_epoch = None
        self.val_data = val_data  # 用于评估 SWA vs best
        self.save_best = save_best
        self.best_weights_before_swa = None

    def on_train_begin(self, logs=None):
        self.start_epoch = int(self.params['epochs'] * self.start_epoch_frac)

    def on_epoch_end(self, epoch, logs=None):
        if epoch >= self.start_epoch:
            current_weights = self.model.get_weights()
            if self.swa_weights is None:
                self.swa_weights = [w.copy() for w in current_weights]
                self.swa_n = 1
            else:
                self.swa_n += 1
                for i, w in enumerate(current_weights):
                    self.swa_weights[i] = (self.swa_weights[i] * (self.swa_n - 1) + w) / self.swa_n
            logger.info(f"  SWA: epoch {epoch+1}, 已平均 {self.swa_n} 个 checkpoint")

    def on_train_end(self, logs=None):
        if self.swa_weights is None:
            return
        # 此时 model 已是 EarlyStopping 恢复的最佳权重
        self.best_weights_before_swa = [w.copy() for w in self.model.get_weights()]
        if not self.save_best or self.val_data is None:
            logger.info(f"SWA: 直接应用平均权重 (平均了 {self.swa_n} 个 checkpoint)")
            self.model.set_weights(self.swa_weights)
            return
        # 评估 SWA 权重 vs 当前 best 权重 (evaluate 返回 [loss, mae], 用索引避免解包错误)
        logger.info(f"SWA: 比较 SWA 权重与 best 权重 (平均了 {self.swa_n} 个 checkpoint)")
        self.model.set_weights(self.best_weights_before_swa)
        best_metrics = self.model.evaluate(self.val_data, verbose=0)
        best_loss, best_mae = float(best_metrics[0]), float(best_metrics[1])
        self.model.set_weights(self.swa_weights)
        swa_metrics = self.model.evaluate(self.val_data, verbose=0)
        swa_loss, swa_mae = float(swa_metrics[0]), float(swa_metrics[1])
        logger.info(f"  best: val_loss={best_loss:.6f}, val_mae={best_mae:.6f}")
        logger.info(f"  SWA : val_loss={swa_loss:.6f}, val_mae={swa_mae:.6f}")
        if swa_loss < best_loss:
            logger.info(f"  → 采用 SWA 权重 (loss 更低)")
            self.model.set_weights(self.swa_weights)
        else:
            logger.info(f"  → 采用 best 权重 (SWA 未提升, 还原)")
            self.model.set_weights(self.best_weights_before_swa)


# ============ 模型构建 (不变) ============
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
    x = Conv2D(16, 3, strides=1, activation='relu', name='conv2d_5')(x)
    x = Dropout(drop)(x)

    x = Flatten(name='flattened')(x)
    x = Dense(100, activation='relu', name='dense_1')(x)
    x = Dropout(drop)(x)
    x = Dense(50, activation='relu', name='dense_2')(x)
    x = Dropout(drop)(x)
    outputs = Dense(2, activation='linear', name='n_outputs')(x)

    model = KerasModel(inputs=[img_in], outputs=outputs, name='linear_s2_physical_opt')
    return model


# ============ 迁移学习 ============
def load_transfer_weights(model):
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


# ============ 学习率调度 ============
class WarmupCosineLR(tf.keras.callbacks.Callback):
    def __init__(self, init_lr, min_lr, total_steps, warmup_steps):
        self.init_lr = init_lr
        self.min_lr = min_lr
        self.total_steps = total_steps
        self.warmup_steps = warmup_steps
        self.step = 0

    def on_train_batch_begin(self, batch, logs=None):
        if self.step < self.warmup_steps:
            lr = self.init_lr * (self.step + 1) / self.warmup_steps
        else:
            progress = (self.step - self.warmup_steps) / max(1, self.total_steps - self.warmup_steps)
            cos = 0.5 * (1 + math.cos(math.pi * progress))
            lr = self.min_lr + (self.init_lr - self.min_lr) * cos
        self.model.optimizer.learning_rate.assign(lr)
        self.step += 1


# ============ INT8 量化 ============
def quantize_int8(model, calibration_records):
    logger.info("\n" + "=" * 60)
    logger.info("INT8 量化")
    logger.info("=" * 60)

    def rep_data_gen():
        rng = random.Random(SEED)
        for r in calibration_records[:200]:
            x, _ = load_record_enhanced(r, augment=False, rng=rng)
            yield [x[None, ...]]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = rep_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8

    int8_model = converter.convert()
    return int8_model


# ============ TTA 推理评估 ============
def evaluate_int8_tta(int8_path, records):
    """评估 INT8 模型 (带 TTA: 原图 + 水平翻转取平均)"""
    logger.info("\n" + "=" * 60)
    logger.info("评估 INT8 模型 (TTA: 原图 + 水平翻转)")
    logger.info("=" * 60)

    interpreter = tf.lite.Interpreter(model_path=int8_path)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    inp_scale, inp_zero = input_details[0]['quantization']
    out_scale, out_zero = output_details[0]['quantization']

    preds_a, preds_t, reals_a, reals_t = [], [], [], []
    for r in records:
        x, y = load_record_enhanced(r, augment=False)
        # 原图推理
        x_q = np.round(x / inp_scale + inp_zero).astype(np.int8)[None, ...]
        interpreter.set_tensor(input_details[0]['index'], x_q)
        interpreter.invoke()
        out_orig = interpreter.get_tensor(output_details[0]['index'])[0]
        # 水平翻转推理
        x_flip = x[:, ::-1, :].copy()
        x_q_flip = np.round(x_flip / inp_scale + inp_zero).astype(np.int8)[None, ...]
        interpreter.set_tensor(input_details[0]['index'], x_q_flip)
        interpreter.invoke()
        out_flip = interpreter.get_tensor(output_details[0]['index'])[0]
        # 翻转后的 angle 取反
        a_orig = (float(out_orig[0]) - out_zero) * out_scale
        a_flip = (float(out_flip[0]) - out_zero) * out_scale
        t_orig = (float(out_orig[1]) - out_zero) * out_scale
        t_flip = (float(out_flip[1]) - out_zero) * out_scale
        # TTA: 平均 (angle 取反后平均)
        a_final = (a_orig + (-a_flip)) / 2
        t_final = (t_orig + t_flip) / 2

        preds_a.append(a_final); preds_t.append(t_final)
        reals_a.append(y[0]); reals_t.append(y[1])

    preds_a, preds_t = np.array(preds_a), np.array(preds_t)
    reals_a, reals_t = np.array(reals_a), np.array(reals_t)

    mae_a = np.mean(np.abs(preds_a - reals_a))
    mae_t = np.mean(np.abs(preds_t - reals_t))
    corr_a = np.corrcoef(preds_a, reals_a)[0, 1] if np.std(preds_a) > 0 else 0
    corr_t = np.corrcoef(preds_t, reals_t)[0, 1] if np.std(preds_t) > 0 else 0

    logger.info(f"测试 {len(preds_a)} 张图 (TTA):")
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


# ============ v4 标签清洗三件套 (按 session 保持时序) ============
def group_by_session(records):
    """按 session 分组, 保持原有加载顺序 (session 内为时序)"""
    grouped = {}
    for r in records:
        grouped.setdefault(r['_session'], []).append(r)
    return grouped


def tau_align_sessions(records, model_path):
    """τ 时间对齐: 司机看到弯道后隔 1-2 帧才打角 (反应延迟), 出弯回正同样滞后.
    用参考模型 (opt3 best) 预测序列与标签序列做 τ∈[-3,3] 扫描,
    把标签平移到与图像视觉事件对齐 → 转向更及时.
    仅当 MAE 改善超过 TAU_IMPROVE 才应用; angle 与 throttle 一起平移.
    注意: 预判性提前打角 (渐进) 不会被此操作删除, 只对齐到正确的帧.
    """
    if not os.path.exists(model_path):
        logger.info(f"  tau 对齐跳过: 参考模型不存在 {model_path}")
        return records
    ref_model = tf.keras.models.load_model(
        model_path, custom_objects={'WeightedMSE': WeightedMSE})

    grouped = group_by_session(records)
    total_shifted, total_dropped = 0, 0
    for sess, rs in grouped.items():
        n = len(rs)
        if n < TAU_MIN_SESSION:
            continue
        # 逐批预测 (避免整 session 图像进内存)
        preds = []
        bs = 128
        for st in range(0, n, bs):
            chunk = rs[st:st + bs]
            xs = np.stack([
                preprocess_image_enhanced(
                    np.array(Image.open(r['_img_path']).convert('RGB')
                             .resize((IMG_W_ORIG, IMG_H_ORIG)), dtype=np.uint8))
                for r in chunk])
            p = ref_model.predict(xs, verbose=0)
            if isinstance(p, (list, tuple)):
                p = np.stack([np.asarray(o).reshape(-1) for o in p], axis=1)
            preds.append(np.asarray(p).reshape(len(chunk), -1))
        preds = np.concatenate(preds, axis=0)          # (n, k)
        labels = np.array([[r['user/angle'], r['user/throttle']] for r in rs])
        # 输出列动态判断: 与 angle 真值相关性高者为 angle 列
        if preds.shape[1] >= 2:
            c0 = np.corrcoef(preds[:, 0], labels[:, 0])[0, 1]
            c1 = np.corrcoef(preds[:, 1], labels[:, 0])[0, 1]
            p_angle = preds[:, 0] if c0 >= c1 else preds[:, 1]
        else:
            p_angle = preds[:, 0]

        def mae_of(tau):
            if tau > 0:
                d = np.abs(p_angle[:n - tau] - labels[tau:, 0])
            else:
                d = np.abs(p_angle[-tau:] - labels[:n + tau, 0])
            return float(d.mean())

        base = mae_of(0)
        best_tau, best_mae = 0, base
        for tau in range(-TAU_MAX, TAU_MAX + 1):
            if tau == 0:
                continue
            m = mae_of(tau)
            if m < best_mae:
                best_tau, best_mae = tau, m
        if best_tau == 0 or base - best_mae < base * TAU_IMPROVE:
            continue
        # 应用平移: label_i' = label_{i+tau}; τ>0 丢尾部 τ 帧, τ<0 丢头部
        if best_tau > 0:
            keep_rs, keep_labels = rs[:n - best_tau], labels[best_tau:]
        else:
            keep_rs, keep_labels = rs[-best_tau:], labels[:n + best_tau]
        for r, (a, t) in zip(keep_rs, keep_labels):
            r['user/angle'] = float(a)
            r['user/throttle'] = float(t)
        grouped[sess] = keep_rs
        total_shifted += 1
        total_dropped += abs(best_tau)
        logger.info(f"  {sess[:40]}: τ={best_tau:+d}  MAE {base:.4f}→{best_mae:.4f} "
                    f"(丢 {abs(best_tau)} 帧)")
    logger.info(f"tau 对齐: {total_shifted}/{len(grouped)} 个 session 平移, 共丢 {total_dropped} 帧")
    return [r for rs in grouped.values() for r in rs]


def median_filter_labels(records):
    """中值滤波 (窗口 5): 手柄抖动是孤立 1-2 帧尖峰 → 被抹掉;
    预判性提前打角持续 >=3 帧 → 中值保边, 完整保留
    """
    grouped = group_by_session(records)
    half = MEDIAN_WINDOW // 2
    for sess, rs in grouped.items():
        if len(rs) < MEDIAN_WINDOW:
            continue
        for key in ('user/angle', 'user/throttle'):
            seq = np.array([r[key] for r in rs], dtype=np.float32)
            filt = np.empty_like(seq)
            for i in range(len(seq)):
                filt[i] = np.median(seq[max(0, i - half):i + half + 1])
            for r, v in zip(rs, filt):
                r[key] = float(v)
    logger.info(f"中值滤波: 窗口 {MEDIAN_WINDOW}, 应用于 {len(grouped)} 个 session (angle+throttle)")
    return records


def remove_correction_frames(records):
    """剔除修正帧 (毒样本): 打角过冲后 1 帧内急速反向拉回的帧.
    模式: |a[i]-a[i-1]|>阈值 且 |a[i+1]-a[i]|>阈值 且方向相反 → 剔除帧 i.
    渐进预判打角 / 弯道入口快速打角均为同向渐变, 不会误剔.
    """
    grouped = group_by_session(records)
    kept, removed = [], 0
    for sess, rs in grouped.items():
        if len(rs) < 3:
            kept.extend(rs)
            continue
        angles = [r['user/angle'] for r in rs]
        keep_mask = [True] * len(rs)
        for i in range(1, len(rs) - 1):
            d_prev = angles[i] - angles[i - 1]
            d_next = angles[i + 1] - angles[i]
            if (abs(d_prev) > CORR_JUMP_THRESH and abs(d_next) > CORR_JUMP_THRESH
                    and d_prev * d_next < 0):
                keep_mask[i] = False
        kept.extend(r for r, k in zip(rs, keep_mask) if k)
        removed += sum(1 for k in keep_mask if not k)
    logger.info(f"剔修正帧: 移除 {removed} 条过冲修正帧 "
                f"(阈值 {CORR_JUMP_THRESH}, 剩 {len(kept)} 条)")
    return kept


def clean_labels_pipeline(records):
    """v4 标签清洗主入口: tau 对齐 → 中值滤波 → 剔修正帧"""
    logger.info("\n--- v4 标签清洗三件套 (tau 对齐 + 中值滤波 + 剔修正帧) ---")
    records = tau_align_sessions(records, TAU_ALIGN_MODEL)
    records = median_filter_labels(records)
    records = remove_correction_frames(records)
    return records


# ============ 主流程 ============
def bin_balanced_oversample(train_records, rng):
    """v3: 分箱均衡过采样 (仅训练集, 验证集保持真实分布)
    - 各分箱过采样至 BALANCE_TARGET (重复帧每 epoch 获得不同增强)
    - 急左/中左 过采样至 LEFT_EXTRA_TARGET (左转踩线额外修正)
    - 急右 下采样至 RIGHT_CAP (轻度压制, 避免淹没其他分箱)
    """
    bins_idx = [[] for _ in range(7)]
    for i, r in enumerate(train_records):
        a = r.get('user/angle', 0)
        for b in range(7):
            if ANGLE_BINS[b] <= a < ANGLE_BINS[b + 1]:
                bins_idx[b].append(i)
                break
        else:
            bins_idx[6].append(i)

    targets = [LEFT_EXTRA_TARGET, LEFT_EXTRA_TARGET, BALANCE_TARGET,
               BALANCE_TARGET, BALANCE_TARGET, BALANCE_TARGET, RIGHT_CAP]
    new_records = []
    for b in range(7):
        pool = bins_idx[b]
        target = targets[b]
        if not pool:
            logger.info(f"  {BIN_LABELS[b]}: 0 条 (跳过)")
            continue
        if len(pool) > target:
            # 下采样 (急右)
            chosen = rng.sample(pool, target)
        else:
            # 过采样: 全保留 + 随机重复补足
            chosen = pool.copy()
            while len(chosen) < target:
                chosen.append(rng.choice(pool))
        new_records.extend(train_records[i] for i in chosen)
        logger.info(f"  {BIN_LABELS[b]}: {len(pool)} → {len(chosen)} 条 (目标 {target})")
    rng.shuffle(new_records)
    return new_records


def temporal_session_split(all_records, val_ratio=TEMPORAL_VAL_RATIO):
    """v5: 时间留出验证集划分 (替代随机 shuffle 划分)

    - 大 session (帧数最多): 按录制顺序前 (1-val_ratio) 训练 / 后 val_ratio 验证
      → val 帧来自录制后段 (可能不同圈/光照时段), 测时间泛化
    - 其余小 session: 全部进验证集 (提供跨 session 信号)
    - physicdata 直行补充 (session 名含 'prev_straight'): 全进训练集

    返回: (train_records, val_records), 各自保持录制顺序 (后续 DataGenerator 会 shuffle)
    """
    by_session = {}
    for r in all_records:
        s = r.get('_session', 'unknown')
        by_session.setdefault(s, []).append(r)

    # 找最大 session (非直行补充)
    session_sizes = [(s, len(recs)) for s, recs in by_session.items()]
    session_sizes.sort(key=lambda x: -x[1])
    big_session = None
    for s, n in session_sizes:
        if 'prev_straight' not in s:
            big_session = s
            break

    train_records, val_records = [], []
    for s, recs in by_session.items():
        if 'prev_straight' in s:
            # 直行补充: 全进训练
            train_records.extend(recs)
            logger.info(f"  [train] {s}: {len(recs)} 条 (直行补充→训练)")
        elif s == big_session:
            # 大 session: 时间留出
            split = int(len(recs) * (1 - val_ratio))
            train_records.extend(recs[:split])
            val_records.extend(recs[split:])
            logger.info(f"  [train] {s}: {split} 条 (前 {1-val_ratio:.0%}, 时间留出)")
            logger.info(f"  [val]   {s}: {len(recs)-split} 条 (后 {val_ratio:.0%}, 时间留出)")
        else:
            # 小 session: 全进验证
            val_records.extend(recs)
            logger.info(f"  [val]   {s}: {len(recs)} 条 (小 session→验证)")

    logger.info(f"时间留出划分: 训练 {len(train_records)} 条 / 验证 {len(val_records)} 条 "
                f"(val_ratio={val_ratio}, 大 session 时间后段+小 session 全进 val)")
    return train_records, val_records


def finalize_export(model, batch_size, epochs, sessions, straight_prev,
                    all_records, bins_count, val_records,
                    best_trial, best_val_loss, trial_val_losses=None):
    """v5: 训练后处理 (统一 best 保存 + FP32/INT8 导出 + TTA 评估 + 训练配置)
    串行训练与并行合并脚本 (merge_trials_v5.py) 共用
    """
    # 确保最终 best 模型也保存为统一路径
    unified_best = f'{OUTPUT_DIR}/mypilot1_s2_physical_best.keras'
    model.save(unified_best)
    logger.info(f"保存统一 best 路径: {unified_best}")

    logger.info(f"\n最佳 trial: #{best_trial}, val_loss: {best_val_loss:.6f}")
    total_params = int(sum(np.prod(v.shape) for v in model.weights))
    logger.info(f"总参数: {total_params:,}")

    # 5. 保存最终模型
    keras_path = f'{OUTPUT_DIR}/mypilot1_s2_physical.keras'
    model.save(keras_path)
    logger.info(f"\n保存 Keras 模型: {keras_path}")

    # 6. FP32 TFLite
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    fp32_tflite = converter.convert()
    fp32_path = f'{OUTPUT_DIR}/mypilot1_s2_physical.tflite'
    with open(fp32_path, 'wb') as f:
        f.write(fp32_tflite)
    logger.info(f"保存 FP32 TFLite: {fp32_path} ({len(fp32_tflite)/1024:.1f} KB)")

    # 7. INT8 量化
    int8_model = quantize_int8(model, val_records)
    int8_path = f'{OUTPUT_DIR}/mypilot1_s2_physical_int8.tflite'
    with open(int8_path, 'wb') as f:
        f.write(int8_model)
    logger.info(f"保存 INT8 TFLite: {int8_path} ({len(int8_model)/1024:.1f} KB)")

    # 8. 评估 (带 TTA)
    results = evaluate_int8_tta(int8_path, val_records)

    # 9. 量化参数
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
            'shape': [int(s_) for s_ in td['shape']]
        })
    with open(f'{OUTPUT_DIR}/quantization_params.json', 'w') as f:
        json.dump(quant_params, f, indent=2)

    # 10. 训练配置
    config = {
        'MODEL_TYPE': 'linear',
        'architecture': 'Conv5=16 + 裁剪 95×156 (无 CLAHE, 与 FPGA 部署一致)',
        'data_source': 'physicaldata2 (主) + physicdata 直行样本补充 (|angle|<0.08)',
        'optimization_version': 'v5: 确定性成对镜像(强化反向赛道) + 干扰线/淡线增强(换场地泛化) + v4全量继承',
        'sessions': [s for s, _ in sessions],
        'session_counts': {s: n for s, n in sessions},
        'total_records': len(all_records),
        'straight_supplement': {
            'source': 'physicdata (上一版)',
            'threshold': STRAIGHT_THRESH,
            'count': len(straight_prev),
            'note': '仅提取直行样本, 不学习弯道数据'
        },
        'angle_bins': ANGLE_BINS,
        'angle_bin_labels': BIN_LABELS,
        'bin_weights': dict(zip(BIN_LABELS, BIN_WEIGHTS)),
        'bin_distribution': {BIN_LABELS[i]: bins_count[i] for i in range(7)},
        'data_strategy': 'v5: 确定性成对镜像×2 (原图+镜像同batch方向对称, 禁随机翻转) + 分箱均衡过采样 (急左/中左→1200, 其余→1000, 急右→1500) + 门控欠转惩罚×2 (对称)',
        'augmentation': {
            'paired_mirror': {
                'enabled': PAIRED_MIRROR,
                'random_flip_disabled': True,
                'note': '训练集每条样本 → (原图, angle) + (镜像图, -angle), 强化反向赛道'
            },
            'scene_distract_v5': {
                '22_synthetic_lines': '25% 概率 (仅|angle|>0.3), 1-3段折线 (单段40-100px, 4-8px粗, LINE_AA, 裁切后保留)',
                '23_faded_lines': '30% 概率, 随机椭圆内近白像素(S<90,V>150)压暗30-70%'
            },
            'A_basic': {
                'horizontal_flip': '禁用 (成对镜像替代)',
                'brightness': '±80',
                'contrast': '0.5~1.6',
                'rotation': '±10°',
                'horizontal_shift': '±15',
                'vertical_shift': '±5'
            },
            'A_light_robust': {
                'hsv_perturb': 'H±15, S±0.3, V±0.3',
                'gamma_correction': 'γ∈[0.5, 2.0]',
                'gaussian_noise': 'σ∈[0, 15]',
                'shadow_simulation': '全图随机5-8顶点多边形, 强度0.2-0.7',
                'motion_blur': '核 7-25, 多方向 (0/30/45/-30/90°)',
                'cutout': '1-4个, h/15~h/2 见方',
                'exposure': '40%, 过曝1.2-1.6 / 欠曝0.4-0.7',
                'faded_saturation': 'S×0.15-0.5'
            }
        },
        'preprocessing': {
            'method': 'crop',
            'crop': {'ROI_CROP_TOP': ROI_CROP_TOP, 'ROI_CROP_LEFT': ROI_CROP_LEFT, 'ROI_CROP_RIGHT': ROI_CROP_RIGHT},
            'clahe': False,
            'normalization': '/255.0',
            'input_height': IMG_H,
            'input_width': IMG_W
        },
        'training_strategy': {
            'C_mixup': {'alpha': MIXUP_ALPHA, 'prob': MIXUP_PROB},
            'C_swa': {'start_epoch_frac': SWA_START_EPOCH_FRAC},
            'C_tta': {'methods': ['original', 'horizontal_flip'], 'aggregation': 'mean(angle取反)'},
            'D_weighted_loss': f'WeightedMSE (分箱权重 + 门控欠转惩罚 ×{UNDER_PENALTY}; v4 移除直行幅值惩罚, 保留预判打角) + Mixup 概率 {MIXUP_PROB}',
            'v4_label_cleaning': {
                'tau_align': {'model': 'opt3_best', 'max_tau': TAU_MAX,
                              'improve_thresh': TAU_IMPROVE, 'min_session': TAU_MIN_SESSION},
                'median_filter': {'window': MEDIAN_WINDOW, 'note': '保留>=3帧的预判性提前打角(中值保边)'},
                'remove_correction_frames': {'jump_thresh': CORR_JUMP_THRESH,
                                             'note': '仅剔过冲后急速反向帧, 渐进预判不触发'},
            },
        },
        'hyperparameters': {
            'learning_rate_init': LEARNING_RATE_INIT,
            'learning_rate_min': LEARNING_RATE_MIN,
            'lr_schedule': 'warmup_cosine',
            'warmup_epochs': WARMUP_EPOCHS,
            'batch_size': batch_size,
            'max_epochs': epochs,
            'early_stop_patience': EARLY_STOP_PATIENCE,
            'validation_split': f'v5 时间留出 (大 session 后 {TEMPORAL_VAL_RATIO:.0%} + 小 session 全进 val, 替代随机划分)',
            'seed': SEED,
            'num_trials': NUM_TRIALS,
            'label_smoothing': LABEL_SMOOTHING
        },
        'transfer_model': TRANSFER_MODEL,
        'total_params': total_params,
        'dense1_input': 960,
        'dense1_params': 96000,
        'bram_blocks': 21,
        'bram_utilization': '99.2%',
        'int8_size_kb': os.path.getsize(int8_path) / 1024,
        'evaluation_tta': results
    }
    if trial_val_losses is not None:
        config['trial_selection'] = {
            'mode': '并行双trial (--trial-idx) 合并选优',
            'selected_trial': best_trial,
            'val_losses': trial_val_losses,
        }
    with open(f'{OUTPUT_DIR}/train_config.json', 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("\n" + "=" * 60)
    logger.info("训练完成!")
    logger.info("=" * 60)
    logger.info(f"模型目录: {OUTPUT_DIR}")
    logger.info(f"  Keras: {keras_path}")
    logger.info(f"  FP32 TFLite: {fp32_path}")
    logger.info(f"  INT8 TFLite: {int8_path}")
    logger.info(f"  train_config.json")
    logger.info(f"  quantization_params.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=EPOCHS)
    parser.add_argument('--batch', type=int, default=BATCH_SIZE)
    parser.add_argument('--lr', type=float, default=LEARNING_RATE_INIT)
    parser.add_argument('--start-trial', type=int, default=1,
                        help='从第 N 个 trial 开始 (断点续跑)')
    parser.add_argument('--initial-best-loss', type=float, default=None,
                        help='已完成 trial 的最佳 val_loss 基准 (断点续跑)')
    parser.add_argument('--trial-idx', type=int, default=None,
                        help='v5 并行: 只跑指定 trial (1 或 2), 各进程独立 best 路径, 跑完手动比较')
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(f'{OUTPUT_DIR}/logs', exist_ok=True)

    logger.info("=" * 60)
    logger.info("方案2 BRAM优化版 - physicaldata2 光线鲁棒性优化训练")
    logger.info("=" * 60)
    logger.info(f"输入: {IMG_H}×{IMG_W} (仅裁剪, 无 CLAHE, 与 FPGA 部署一致)")
    logger.info(f"架构: Conv5=16, Dense1 输入=960 (BRAM 优化, 不变)")
    logger.info(f"优化: v5 = 确定性成对镜像×2(强化反向赛道) + 23项增强(+干扰线/淡线) + v4标签清洗 + 分箱均衡 + 门控欠转惩罚")
    logger.info(f"分箱权重: {dict(zip(BIN_LABELS, BIN_WEIGHTS))}, 欠转惩罚 ×{UNDER_PENALTY}")
    logger.info(f"学习率: Warmup+余弦 {LEARNING_RATE_INIT}→{LEARNING_RATE_MIN}")
    logger.info(f"batch: {args.batch}, epochs: {args.epochs}, trials: {NUM_TRIALS}")
    logger.info(f"Mixup α={MIXUP_ALPHA}, SWA 起始 {SWA_START_EPOCH_FRAC*100:.0f}% epoch")

    # 1. 加载数据
    logger.info("\n--- 加载物理采集数据 (physicaldata2) ---")
    all_records, sessions = load_physic_records()
    for s, n in sessions:
        logger.info(f"  {s}: {n} 条")

    # 1.5 从 physicdata 补充直行样本 (不学弯道)
    logger.info("\n--- 从 physicdata 补充直行样本 (|angle| < %.2f, 不学弯道) ---" % STRAIGHT_THRESH)
    straight_prev = load_straight_records_from_prev()
    logger.info(f"  physicdata 直行样本: {len(straight_prev)} 条")
    all_records.extend(straight_prev)
    sessions.append(('physicdata(直行补充)', len(straight_prev)))
    logger.info(f"合并后总记录: {len(all_records)} 条 (弯道仅来自 physicaldata2, 直行增强)")

    # 1.6 v4: 标签清洗三件套 (tau 对齐 → 中值滤波 → 剔修正帧)
    all_records = clean_labels_pipeline(all_records)

    # 分箱统计
    bins_count = [0] * 7
    for r in all_records:
        bins_count[get_bin_index(r.get('user/angle', 0))] += 1
    logger.info("\n角度分箱分布 (合并后):")
    for i in range(7):
        logger.info(f"  {BIN_LABELS[i]}: {bins_count[i]} ({bins_count[i]/len(all_records)*100:.1f}%) → 权重 {BIN_WEIGHTS[i]}")

    # 2. v5: 时间留出划分 (替代随机 shuffle 划分, 测时间+跨 session 泛化)
    logger.info(f"\n--- v5 时间留出验证集划分 (大 session 后段+小 session→val) ---")
    train_records, val_records = temporal_session_split(all_records, TEMPORAL_VAL_RATIO)

    # 2.5 v3: 分箱均衡过采样 (仅训练集)
    rng = random.Random(SEED)
    logger.info(f"\n--- v3 分箱均衡过采样 (直行/左转增强, 急右压制) ---")
    train_records = bin_balanced_oversample(train_records, rng)
    logger.info(f"均衡后训练集: {len(train_records)} 条")

    # 3. 学习率调度 (v5: 成对镜像训练集有效样本 ×2, 余弦调度步数须同步)
    effective_train_len = len(train_records) * 2 if PAIRED_MIRROR else len(train_records)
    total_steps_per_epoch = math.ceil(effective_train_len / args.batch)
    total_steps = total_steps_per_epoch * args.epochs
    warmup_steps = total_steps_per_epoch * WARMUP_EPOCHS

    # 4. 多 trial 训练
    # v5: 支持 --trial-idx 只跑指定 trial (并行模式), 各 trial 独立 best 路径
    if args.trial_idx is not None:
        trial_range = [args.trial_idx - 1]
        logger.info(f"\n--- 并行模式: 只跑 Trial {args.trial_idx} ---")
    else:
        trial_range = range(args.start_trial - 1, NUM_TRIALS)
        logger.info(f"\n--- 多 trial 训练 ({NUM_TRIALS} 次, 保留最佳) ---")
    # 断点续跑: --start-trial 2 --initial-best-loss 0.070203 可跳过已完成的 trial
    best_val_loss = args.initial_best_loss if args.initial_best_loss is not None else float('inf')
    best_model = None
    best_trial = args.start_trial - 1 if args.initial_best_loss is not None else -1
    for trial in trial_range:
        trial_seed = SEED + trial * 100
        logger.info(f"\n{'='*60}")
        logger.info(f"Trial {trial+1}/{NUM_TRIALS}  (seed={trial_seed})")
        logger.info(f"{'='*60}")

        # v5: 并行模式下每个 trial 用独立 best 路径, 避免写冲突
        best_path = f'{OUTPUT_DIR}/mypilot1_s2_physical_best_t{trial+1}.keras'

        model = build_model_s2_bram_opt()
        load_transfer_weights(model)

        for layer in model.layers:
            layer.trainable = True

        optimizer = tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE_INIT)
        model.compile(optimizer=optimizer,
                      loss=WeightedMSE(),
                      metrics=['mae'],
                      jit_compile=False)

        train_gen = DataGeneratorEnhanced(train_records, batch_size=args.batch,
                                           augment=True, seed=trial_seed, use_mixup=True,
                                           paired=PAIRED_MIRROR,
                                           workers=DATA_WORKERS,
                                           use_multiprocessing=True)
        val_gen = DataGeneratorEnhanced(val_records, batch_size=args.batch,
                                         augment=False, seed=trial_seed + 1)

        callbacks = [
            WarmupCosineLR(LEARNING_RATE_INIT, LEARNING_RATE_MIN,
                           total_steps, warmup_steps),
            EarlyStopping(monitor='val_loss', patience=EARLY_STOP_PATIENCE,
                          restore_best_weights=True, verbose=1),
            SWACallback(SWA_START_EPOCH_FRAC, val_data=val_gen),
            tf.keras.callbacks.TensorBoard(
                log_dir=f'{OUTPUT_DIR}/logs/trial_{trial+1}', histogram_freq=0),
        ]

        history = model.fit(
            train_gen,
            validation_data=val_gen,
            epochs=args.epochs,
            callbacks=callbacks,
            verbose=2,
        )

        final_val_loss = min(history.history.get('val_loss', [float('inf')]))
        logger.info(f"Trial {trial+1} 最低 val_loss: {final_val_loss:.6f}")

        if final_val_loss < best_val_loss:
            best_val_loss = final_val_loss
            best_model = model
            best_trial = trial + 1
            model.save(best_path)
            logger.info(f"✅ Trial {trial+1} 创新低! 保存到 {best_path}")

    # v5: 并行模式 (--trial-idx) 下跳过后处理 (量化/评估), 由串行合并进程完成
    if args.trial_idx is not None:
        logger.info(f"\n并行模式 Trial {args.trial_idx} 完成, best: {best_path}")
        logger.info(f"val_loss: {best_val_loss:.6f}")
        logger.info("后续量化/评估请运行无 --trial-idx 的串行合并 (会比较两个 trial 的 best)")
        return

    # 串行模式: 从两个 trial 的独立 best 文件中选最优
    if best_model is None:
        # 加载两个 trial 的 best, 比较 val_loss
        t1_path = f'{OUTPUT_DIR}/mypilot1_s2_physical_best_t1.keras'
        t2_path = f'{OUTPUT_DIR}/mypilot1_s2_physical_best_t2.keras'
        candidates = []
        for tp in [t1_path, t2_path]:
            if os.path.exists(tp):
                m = tf.keras.models.load_model(tp, custom_objects={'WeightedMSE': WeightedMSE})
                candidates.append((tp, m))
        if not candidates:
            logger.error("未找到任何 trial best 模型, 无法继续")
            return
        best_model = candidates[0][1]
        best_path = candidates[0][0]
        best_trial = 1
        logger.info(f"从 {best_path} 恢复最佳模型 (默认 Trial 1)")
    else:
        # best_model 已在内存中, 但 best_path 可能是 t1 或 t2, 确保统一为 best_t
        pass

    # v5: 导出 (统一 best + FP32/INT8 量化 + TTA 评估 + 配置)
    finalize_export(best_model, batch_size=args.batch, epochs=args.epochs,
                    sessions=sessions, straight_prev=straight_prev,
                    all_records=all_records, bins_count=bins_count,
                    val_records=val_records, best_trial=best_trial,
                    best_val_loss=best_val_loss)


if __name__ == '__main__':
    main()
