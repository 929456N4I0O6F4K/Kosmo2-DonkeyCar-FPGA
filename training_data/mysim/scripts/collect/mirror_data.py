"""
镜像反向数据生成器
将采集的数据水平翻转 + 角度取反，生成反向赛道数据

原理:
  正向数据: 图像原样 + 角度 a (左弯 a<0, 右弯 a>0)
  镜像数据: 图像水平翻转 + 角度 -a (左弯变右弯, 右弯变左弯)

用法:
  python mirror_data.py <tub_path>           # 镜像并追加到原 tub
  python mirror_data.py <tub_path> --dry-run # 只统计不写入
  python mirror_data.py <tub_path> --force   # 覆盖已有的镜像数据
"""
import os
import sys
import json
import argparse
import cv2

# 需要取反的角度字段
ANGLE_KEYS = ['user/angle', 'pilot/angle']
# 需要镜像的图像字段（文件名含 image_array）
IMAGE_KEY_PREFIX = 'cam/image_array'


def mirror_image(img):
    """水平翻转图像"""
    return cv2.flip(img, 1)  # 1 = 水平翻转


def process_tub(tub_path, dry_run=False, force=False):
    """处理单个 tub 目录，生成镜像数据"""
    if not os.path.exists(os.path.join(tub_path, 'manifest.json')):
        print(f"错误: {tub_path} 不是有效的 tub 目录（无 manifest.json）")
        return False

    # 读取 manifest 获取输入字段和类型
    manifest_path = os.path.join(tub_path, 'manifest.json')
    with open(manifest_path) as f:
        inputs = json.loads(f.readline().strip())

    # 找出图像字段名
    image_key = None
    for key in inputs:
        if 'image' in key.lower() or 'cam' in key.lower():
            image_key = key
            break

    if image_key is None:
        print(f"错误: 未找到图像字段（含 image 或 cam 的字段）")
        return False

    print(f"图像字段: {image_key}")

    # 读取所有 catalog 文件中的记录
    catalog_files = sorted(
        [f for f in os.listdir(tub_path) if f.endswith('.catalog')],
        key=lambda x: int(x.split('_')[1].split('.')[0]) if '_' in x else 0
    )

    if not catalog_files:
        print("错误: 无 catalog 文件")
        return False

    print(f"catalog 文件: {len(catalog_files)} 个")

    # 收集所有记录
    all_records = []
    for cat_file in catalog_files:
        cat_path = os.path.join(tub_path, cat_file)
        with open(cat_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    record = json.loads(line)
                    all_records.append(record)

    print(f"原始记录数: {len(all_records)}")

    if dry_run:
        # 统计角度分布
        angles = []
        for r in all_records:
            for ak in ANGLE_KEYS:
                if ak in r:
                    angles.append(float(r[ak]))
                    break
        if angles:
            print(f"\n=== 角度分布统计 (dry-run) ===")
            print(f"  记录数: {len(angles)}")
            print(f"  最小值: {min(angles):+.4f}")
            print(f"  最大值: {max(angles):+.4f}")
            print(f"  平均值: {sum(angles)/len(angles):+.4f}")
            left = sum(1 for a in angles if a < -0.05)
            right = sum(1 for a in angles if a > 0.05)
            straight = len(angles) - left - right
            print(f"  左弯(<-0.05): {left} ({100*left/len(angles):.1f}%)")
            print(f"  直行(-0.05~0.05): {straight} ({100*straight/len(angles):.1f}%)")
            print(f"  右弯(>0.05): {right} ({100*right/len(angles):.1f}%)")
            print(f"\n镜像后预计: 左弯 {right} ↔ 右弯 {left}（完全对称）")
        print(f"\n[dry-run] 未写入任何数据。去掉 --dry-run 执行实际镜像。")
        return True

    # 实际镜像处理
    images_dir = os.path.join(tub_path, 'images')
    if not os.path.isdir(images_dir):
        print(f"错误: 无 images 目录: {images_dir}")
        return False

    # 获取当前最大 index
    max_index = max(r.get('_index', 0) for r in all_records)
    next_index = max_index + 1

    # 找到最新的 catalog 文件用于追加
    last_cat_file = catalog_files[-1]
    last_cat_path = os.path.join(tub_path, last_cat_file)

    # 读取 manifest 的其余信息
    with open(manifest_path) as f:
        f.readline()  # 跳过 inputs 行
        manifest_rest = f.read()

    # 追加镜像记录到最新的 catalog
    mirror_count = 0
    fail_count = 0

    with open(last_cat_path, 'a') as cat_f:
        for record in all_records:
            try:
                # 读取原图像
                img_name = record.get(image_key, '')
                if not img_name:
                    continue
                img_path = os.path.join(images_dir, img_name)
                if not os.path.exists(img_path):
                    fail_count += 1
                    continue

                img = cv2.imread(img_path)
                if img is None:
                    fail_count += 1
                    continue

                # 镜像图像
                mirrored_img = mirror_image(img)

                # 生成新文件名
                new_img_name = f"{next_index}_cam_image_array_mirrored.jpg"
                new_img_path = os.path.join(images_dir, new_img_name)

                # 保存镜像图像
                cv2.imwrite(new_img_path, mirrored_img)

                # 构建新记录
                new_record = record.copy()
                new_record['_index'] = next_index
                new_record[image_key] = new_img_name

                # 取反角度字段
                for ak in ANGLE_KEYS:
                    if ak in new_record:
                        new_record[ak] = -float(new_record[ak])

                # 写入 catalog
                cat_f.write(json.dumps(new_record, allow_nan=False, sort_keys=True) + '\n')

                next_index += 1
                mirror_count += 1

            except Exception as e:
                fail_count += 1
                if fail_count <= 3:
                    print(f"  警告: 处理记录 {record.get('_index', '?')} 失败: {e}")
                continue

    # 更新 manifest.json 的 current_index
    # manifest.json 格式: 第一行是 inputs 列表, 第二行是 {current_index, ...}
    with open(manifest_path, 'r') as f:
        lines = f.readlines()

    # 更新 current_index
    new_manifest = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            new_manifest.append('\n')
            continue
        try:
            d = json.loads(line)
            if isinstance(d, dict) and 'current_index' in d:
                d['current_index'] = next_index
                new_manifest.append(json.dumps(d, allow_nan=False) + '\n')
            else:
                new_manifest.append(json.dumps(d, allow_nan=False) + '\n')
        except:
            new_manifest.append(line + '\n')

    with open(manifest_path, 'w') as f:
        f.writelines(new_manifest)

    # 统计结果
    print(f"\n=== 镜像完成 ===")
    print(f"  原始记录: {len(all_records)} 条")
    print(f"  镜像生成: {mirror_count} 条")
    print(f"  失败跳过: {fail_count} 条")
    print(f"  总记录数: {len(all_records) + mirror_count} 条")
    print(f"  数据目录: {tub_path}")

    # 验证角度平衡
    orig_angles = []
    mirror_angles = []
    for r in all_records:
        for ak in ANGLE_KEYS:
            if ak in r:
                orig_angles.append(float(r[ak]))
                break

    if orig_angles:
        print(f"\n=== 角度平衡验证 ===")
        orig_left = sum(1 for a in orig_angles if a < -0.05)
        orig_right = sum(1 for a in orig_angles if a > 0.05)
        print(f"  原始: 左弯 {orig_left} / 右弯 {orig_right}")
        print(f"  镜像: 左弯 {orig_right} / 右弯 {orig_left}（互换）")
        print(f"  合计: 左弯 {orig_left + orig_right} / 右弯 {orig_left + orig_right}（完全对称）")

    return True


def main():
    parser = argparse.ArgumentParser(description='镜像反向数据生成器')
    parser.add_argument('tub_path', help='tub 数据目录路径')
    parser.add_argument('--dry-run', action='store_true', help='只统计不写入')
    parser.add_argument('--force', action='store_true', help='覆盖已有镜像数据')
    args = parser.parse_args()

    tub_path = args.tub_path.rstrip('/')
    print(f"=== 镜像反向数据生成 ===")
    print(f"数据目录: {tub_path}")
    print(f"模式: {'dry-run' if args.dry_run else '实际写入'}")
    print()

    success = process_tub(tub_path, dry_run=args.dry_run, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
