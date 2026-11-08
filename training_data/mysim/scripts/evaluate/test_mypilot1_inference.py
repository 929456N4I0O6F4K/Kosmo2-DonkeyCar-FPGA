"""手动测试 mypilot1 模型推理
从训练数据中读取图像，应用与训练时一致的 CROP 变换，运行推理，
检查模型输出是否随输入变化（非恒定直行）。
"""
import sys
import os
import json
import numpy as np
from PIL import Image
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

# 路径配置
MODEL_DIR = os.path.join(MYSIM_DIR, "models/mypilot1")
MODEL_FILE = os.path.join(MODEL_DIR, "mypilot.keras")
TRAIN_CONFIG = os.path.join(MODEL_DIR, "mypilot1.train_config.json")

# 训练数据场景目录（取有 images 子目录的 warehouse 场景）
DATA_DIR = os.path.join(MYSIM_DIR, "datasets/sim/mypilot1/3_warehouse")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
CATALOG_FILE = os.path.join(DATA_DIR, "catalog_0.catalog")
MANIFEST_FILE = os.path.join(DATA_DIR, "manifest.json")


def load_train_config():
    """读取训练配置（CROP 参数）"""
    with open(TRAIN_CONFIG) as f:
        cfg = json.load(f)
    print(f"训练配置: {cfg}")
    return cfg


def apply_crop(image, top=0, bottom=0, left=0, right=0):
    """应用 CROP 遮罩（与 ImgCropMask 一致：乘以 bool mask，不改变尺寸）"""
    h, w, d = image.shape
    mask = np.zeros(image.shape, dtype=bool)
    x1 = left
    x2 = w - right
    y1 = top
    y2 = h - bottom
    mask[y1:y2, x1:x2, :] = True
    return np.multiply(image, mask)


def load_records_from_catalog():
    """从 catalog 文件读取记录（JSON Lines 格式，每行一个 JSON 对象）"""
    records = []
    with open(CATALOG_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except json.JSONDecodeError as e:
                print(f"警告: 跳过无法解析的行: {e}")
    return records


def main():
    print("=" * 60)
    print("手动测试 mypilot1 模型推理")
    print("=" * 60)

    # 1. 加载训练配置
    train_cfg = load_train_config()
    crop_top = train_cfg.get("ROI_CROP_TOP", 0)
    crop_bottom = train_cfg.get("ROI_CROP_BOTTOM", 0)
    crop_left = train_cfg.get("ROI_CROP_LEFT", 0)
    crop_right = train_cfg.get("ROI_CROP_RIGHT", 0)
    has_crop = "CROP" in train_cfg.get("TRANSFORMATIONS", [])
    print(f"训练时 CROP: {has_crop}, top={crop_top}, bottom={crop_bottom}")

    # 2. 加载模型
    print("\n--- 加载模型 ---")
    import tensorflow as tf
    model = tf.keras.models.load_model(MODEL_FILE)
    print(f"模型加载成功: {MODEL_FILE}")
    print(f"  输入形状: {model.input_shape}")
    print(f"  输出: {model.outputs}")

    # 3. 读取训练数据
    print("\n--- 读取训练数据 ---")
    records = load_records_from_catalog()
    print(f"从 catalog_0 读取 {len(records)} 条记录")

    if len(records) == 0:
        print("错误: 未读取到记录")
        return

    # 4. 筛选有代表性的样本：大左弯、大右弯、直行
    # 记录格式: {'cam/image_array': image_path, 'user/angle': float, ...}
    samples = {"hard_left": None, "hard_right": None, "straight": None,
               "medium_left": None, "medium_right": None}
    for rec in records:
        # 记录可能是 dict 或 list
        if isinstance(rec, dict):
            angle = rec.get("user/angle", 0)
            img_name = rec.get("cam/image_array", "")
        elif isinstance(rec, (list, tuple)) and len(rec) >= 2:
            img_name = rec[0]
            angle = rec[1]
        else:
            continue

        if abs(angle) > 0.5 and angle < 0 and samples["hard_left"] is None:
            samples["hard_left"] = (img_name, angle)
        elif abs(angle) > 0.5 and angle > 0 and samples["hard_right"] is None:
            samples["hard_right"] = (img_name, angle)
        elif abs(angle) < 0.05 and samples["straight"] is None:
            samples["straight"] = (img_name, angle)
        elif 0.2 > angle > 0.1 and samples["medium_right"] is None:
            samples["medium_right"] = (img_name, angle)
        elif -0.2 < angle < -0.1 and samples["medium_left"] is None:
            samples["medium_left"] = (img_name, angle)

    print("\n选取的样本:")
    for k, v in samples.items():
        if v:
            print(f"  {k}: 图像={v[0]}, 真实角度={v[1]:.4f}")
        else:
            print(f"  {k}: 未找到")

    # 5. 对每个样本进行推理
    print("\n--- 推理测试 ---")
    print(f"{'样本':<15} {'真实角度':>10} {'预测角度':>10} {'预测油门':>10} {'是否CROP':>10}")
    print("-" * 60)

    predictions = []
    for name, sample in samples.items():
        if sample is None:
            continue
        img_name, true_angle = sample
        img_path = os.path.join(IMAGES_DIR, img_name) if not os.path.isabs(img_name) else img_name
        if not os.path.exists(img_path):
            # 尝试在 DATA_DIR 下找
            img_path = os.path.join(DATA_DIR, img_name)
        if not os.path.exists(img_path):
            print(f"  {name}: 图像不存在 {img_path}")
            continue

        # 读取图像
        img = np.array(Image.open(img_path).convert("RGB"))
        # 应用 CROP 遮罩（与训练时一致）
        if has_crop:
            img = apply_crop(img, crop_top, crop_bottom, crop_left, crop_right)

        # 归一化（与 normalize_image 一致：/255.0）
        img_norm = img.astype(np.float32) / 255.0
        # 扩展 batch 维度
        img_batch = np.expand_dims(img_norm, axis=0)

        # 推理
        pred = model.predict(img_batch, verbose=0)
        # KerasLinear 有两个输出（angle, throttle），可能是 list 或 array
        if isinstance(pred, (list, tuple)):
            # 输出是 [angle_array, throttle_array]
            pred_angle = float(np.asarray(pred[0]).flatten()[0])
            pred_throttle = float(np.asarray(pred[1]).flatten()[0])
        else:
            arr = np.asarray(pred)
            if arr.ndim >= 2 and arr.shape[-1] >= 2:
                pred_angle = float(arr[0, 0])
                pred_throttle = float(arr[0, 1])
            else:
                pred_angle = float(arr.flatten()[0])
                pred_throttle = float(arr.flatten()[1] if arr.size > 1 else 0.0)

        predictions.append((name, true_angle, pred_angle, pred_throttle))
        print(f"{name:<15} {true_angle:>10.4f} {pred_angle:>10.4f} {pred_throttle:>10.4f} {'是' if has_crop else '否':>10}")

    # 6. 结论
    print("\n--- 结论 ---")
    if len(predictions) < 2:
        print("样本不足，无法判断")
        return

    angles = [p[2] for p in predictions]
    angle_range = max(angles) - min(angles)
    print(f"预测角度范围: [{min(angles):.4f}, {max(angles):.4f}]")
    print(f"预测角度变化幅度: {angle_range:.4f}")

    if angle_range < 0.05:
        print("⚠ 模型输出几乎恒定 → 小车会直行（问题未修复）")
    elif angle_range < 0.2:
        print("⚠ 模型输出变化较小 → 转向可能不够（部分修复）")
    else:
        print("✓ 模型输出随输入变化 → 转向正常（已修复）")

    # 检查与真实标签的相关性
    true_angles = [p[1] for p in predictions]
    if len(true_angles) > 1:
        try:
            correlation = float(np.corrcoef(true_angles, angles)[0, 1])
            print(f"预测与真实角度相关系数: {correlation:.4f}")
            if correlation > 0.5:
                print("✓ 预测方向正确")
            elif correlation < -0.5:
                print("✗ 预测方向相反（需翻转）")
            else:
                print("⚠ 预测与真实无相关性")
        except Exception as e:
            print(f"无法计算相关系数: {e}")


if __name__ == "__main__":
    main()
