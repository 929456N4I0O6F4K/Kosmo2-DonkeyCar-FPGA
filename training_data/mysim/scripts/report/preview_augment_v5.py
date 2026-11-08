#!/usr/bin/env python3
"""v5 增强效果预览: 逐项强制触发 23 项增强 + 成对镜像, 生成 HTML 对比报告

直接导入 opt5 训练脚本的 augment_image_enhanced 函数, 保证预览 = 训练实际效果
参数取偏显著值 (uniform 返回 75% 分位), 便于观察每项增强的视觉影响
"""
import os
import sys
import json
import io
import base64
import numpy as np
from PIL import Image
import cv2
from pathlib import Path

MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, os.path.join(MYSIM_DIR, 'scripts'))
# 导入 opt5 (会加载 TF, 约需 10-30s, 但只一次, 保证预览=训练效果)
from train import train_s2_physical2_opt5 as opt5

# 各增强项的 if 概率, 按代码中 rng.random() 调用顺序排列
ITEM_PROBS = [
    0.5,  0.7,  0.5,  0.5,  0.5,  0.3,   # 1-6  基础
    0.6,  0.5,  0.4,  0.3,  0.2,  0.3,   # 7-12 光线鲁棒
    0.25, 0.15, 0.3,  0.25,             # 13-16
    0.20, 0.25, 0.20, 0.15, 0.18,        # 17-21 帆布特异
    0.25, 0.30,                           # 22-23 场景干扰 (v5 新增)
]
ITEM_NAMES = [
    "1. 水平翻转", "2. 亮度扰动 ±50", "3. 对比度 0.7~1.3", "4. 旋转 ±10°",
    "5. 水平平移 ±15", "6. 垂直平移 ±5", "7. HSV 扰动", "8. Gamma 校正",
    "9. 高斯噪声", "10. 阴影模拟", "11. 运动模糊", "12. Cutout 遮挡",
    "13. 车身抖动", "14. 多方向运动模糊", "15. 色温偏移", "16. 过曝/欠曝",
    "17. 局部高光白斑", "18. 饱和度褪色", "19. 波浪形变", "20. 梯形畸变",
    "21. 灯光带状反射", "22. 合成干扰线 (v5, 仅急转)", "23. 淡线/断线 (v5)",
]
GROUPS = [
    ("基础增强",      list(range(0, 6))),
    ("光线鲁棒性",    list(range(6, 16))),
    ("帆布场地特异",  list(range(16, 21))),
    ("场景干扰 (v5)", list(range(21, 23))),
]


class ItemRNG:
    """可控 RNG: 只触发指定增强项, 其余项不触发

    random() 按 if 判断顺序返回: 目标项→0.0(触发), 其余→1.0(不触发)
    uniform/randint/choice 用独立 seeded RNG, 保证每次调用返回不同值
    (否则坐标会全部重叠, 线段退化成点, 阴影退化成空)
    target=-1 表示所有项都不触发 (用于纯镜像展示)
    """

    def __init__(self, target, seed=42):
        self.target = target
        self.idx = 0
        import random as _r
        self._rng = _r.Random(seed)

    def random(self):
        idx = self.idx
        self.idx += 1
        return 0.0 if idx == self.target else 1.0

    def uniform(self, a, b):
        return self._rng.uniform(a, b)

    def randint(self, a, b):
        return self._rng.randint(a, b)

    def choice(self, seq):
        return self._rng.choice(seq)

    def normal(self, loc=0.0, scale=1.0):
        return self._rng.gauss(loc, scale)


def img_to_b64(img_arr, quality=85):
    if img_arr.dtype != np.uint8:
        img_arr = np.clip(img_arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(img_arr)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def load_samples():
    """从 physicaldata2 选 3 张代表性图片: 直行 / 中转 / 急转"""
    records = []
    for d in sorted(os.listdir(opt5.PHYSIC_DATA_DIR)):
        path = os.path.join(opt5.PHYSIC_DATA_DIR, d)
        rec_path = os.path.join(path, 'records.jsonl')
        if not os.path.exists(rec_path):
            continue
        with open(rec_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
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

    samples = []
    for tag, target_abs in [('直行', 0.0), ('中转', 0.45), ('急转', 0.85)]:
        best, best_dist = None, 999
        for r in records:
            a = r.get('user/angle', 0)
            if a <= 0:  # 优先右转 (正角度, 便于看翻转效果)
                continue
            dist = abs(abs(a) - target_abs)
            if dist < best_dist:
                best_dist, best = dist, r
        if best:
            samples.append((tag, best))
    return samples


def main():
    samples = load_samples()
    if not samples:
        print("ERROR: 未找到样本图片")
        return

    cards = []
    for tag, rec in samples:
        angle = rec.get('user/angle', 0)
        img = Image.open(rec['_img_path']).convert('RGB')
        if img.size != (opt5.IMG_W_ORIG, opt5.IMG_H_ORIG):
            img = img.resize((opt5.IMG_W_ORIG, opt5.IMG_H_ORIG))
        orig = np.array(img, dtype=np.uint8)
        orig_b64 = img_to_b64(orig)

        # 逐项强制触发
        item_b64s = []
        for i in range(len(ITEM_PROBS)):
            rng = ItemRNG(target=i)
            aug, _ = opt5.augment_image_enhanced(
                orig.copy(), angle, rng, allow_flip=True)
            item_b64s.append(img_to_b64(aug))

        # 成对镜像 (v5 核心): 镜像图 + 禁用随机翻转 + 不触发其他增强
        mirror = orig[:, ::-1, :].copy()
        rng_clean = ItemRNG(target=-1)
        mirror_aug, _ = opt5.augment_image_enhanced(
            mirror.copy(), -angle, rng_clean, allow_flip=False)
        mirror_b64 = img_to_b64(mirror)
        mirror_aug_b64 = img_to_b64(mirror_aug)

        # 生成卡片 HTML
        group_html = []
        for gname, indices in GROUPS:
            rows = []
            for i in indices:
                v5cls = ' class="v5"' if i >= 21 else ''
                rows.append(
                    f'<div class="row"><span{v5cls}>{ITEM_NAMES[i]}</span>'
                    f'<img src="data:image/jpeg;base64,{orig_b64}">'
                    f'<img src="data:image/jpeg;base64,{item_b64s[i]}">'
                    f'</div>')
            group_html.append(f'<div class="group"><h3>{gname}</h3>{"".join(rows)}</div>')

        paired_html = (
            f'<div class="group"><h3 class="v5">成对镜像 (v5 核心)</h3>'
            f'<div class="row"><span class="v5">原图 (angle={angle:.3f})</span>'
            f'<img src="data:image/jpeg;base64,{orig_b64}">'
            f'<img src="data:image/jpeg;base64,{orig_b64}"></div>'
            f'<div class="row"><span class="v5">水平镜像 (angle={-angle:.3f})</span>'
            f'<img src="data:image/jpeg;base64,{orig_b64}">'
            f'<img src="data:image/jpeg;base64,{mirror_b64}"></div>'
            f'<div class="row"><span class="v5">镜像+增强 (allow_flip=False)</span>'
            f'<img src="data:image/jpeg;base64,{mirror_b64}">'
            f'<img src="data:image/jpeg;base64,{mirror_aug_b64}"></div>'
            f'<div class="hint">训练时: 原图+镜像图同 batch 成对出现, '
            f'方向严格对称, 禁用随机翻转</div></div>')

        # 混合增强 (训练实际效果): 用真实 RNG, 所有 23 项按各自概率同时触发
        import random as _real_rng
        mixed_b64s = []
        for k in range(8):
            real_rng = _real_rng.Random(1000 + k)
            mixed, _ = opt5.augment_image_enhanced(
                orig.copy(), angle, real_rng, allow_flip=True)
            mixed_b64s.append(img_to_b64(mixed))

        mixed_html = (
            f'<div class="group"><h3 class="v5">混合增强 (训练实际效果, 8 次随机)</h3>'
            f'<div class="hint">每次调用: 23 项各自按概率独立触发, 叠加成训练时看到的样子</div>')
        for k in range(0, 8, 4):
            mixed_html += '<div class="mixed-row">'
            for j in range(k, min(k + 4, 8)):
                mixed_html += (f'<img src="data:image/jpeg;base64,{mixed_b64s[j]}">'
                               f'<div class="cap">#{j+1}</div>')
            mixed_html += '</div>'
        mixed_html += '</div>'

        cards.append(
            f'<div class="sample"><h2>样本: {tag} '
            f'(angle={angle:.3f}, session={rec.get("_session", "")})</h2>'
            f'<div class="legend">左=原图 | 右=增强后</div>'
            f'{"".join(group_html)}{paired_html}{mixed_html}</div>')

    html = f'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>v5 增强效果预览</title>
<style>
body {{ font-family: -apple-system, "PingFang SC", sans-serif;
       background: #1a1a2e; color: #ddd; margin: 0; padding: 20px; }}
h1 {{ color: #e94560; }}
h2 {{ color: #fff; background: #16213e; padding: 10px 16px; border-radius: 6px; }}
h3 {{ color: #e94560; margin: 20px 0 8px; border-bottom: 1px solid #333; padding-bottom: 4px; }}
.sample {{ margin-bottom: 40px; }}
.group {{ margin: 12px 0; }}
.row {{ display: flex; align-items: center; gap: 10px; margin: 4px 0; }}
.row span {{ width: 180px; text-align: right; font-size: 13px; color: #aaa; flex-shrink: 0; }}
.row img {{ width: 200px; height: 150px; object-fit: cover; border-radius: 3px; border: 1px solid #333; }}
.v5 {{ color: #e94560 !important; font-weight: bold; }}
.legend {{ color: #888; font-size: 12px; margin: -8px 0 10px 180px; }}
.hint {{ color: #666; font-size: 11px; margin: 6px 0 0 190px; }}
.note {{ background: #16213e; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; line-height: 1.6; }}
.mixed-row {{ display: flex; gap: 8px; margin: 4px 0; flex-wrap: wrap; }}
.mixed-row img {{ width: 180px; height: 135px; object-fit: cover; border-radius: 3px; border: 1px solid #333; }}
.cap {{ font-size: 11px; color: #666; text-align: center; width: 180px; }}
</style></head><body>
<h1>v5 增强效果预览报告</h1>
<div class="note">
直接调用 opt5 训练脚本的 <code>augment_image_enhanced</code> 函数, 保证预览 = 训练实际效果<br>
逐项强制触发 (其余项不触发), 参数取偏显著值 (uniform 75% 分位), 便于观察每项的视觉影响<br>
共 23 项增强 + 成对镜像, 分 4 组展示 (基础 / 光线 / 帆布特异 / 场景干扰v5)
</div>
{''.join(cards)}
</body></html>'''

    out = f'{MYSIM_DIR}/reports/augment_preview.html'
    with open(out, 'w') as f:
        f.write(html)
    print(f"报告已生成: {out}")
    print(f"样本数: {len(samples)}, 增强项: 23 + 成对镜像")


if __name__ == '__main__':
    main()
