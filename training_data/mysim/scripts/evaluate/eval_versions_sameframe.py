#!/usr/bin/env python3
"""
版本演化同帧评估: 基线 / v1(opt) / v2(opt2) @ physicaldata2 全量 4717 行车帧

v3/v4/v5 已有同口径结果 (sim_vs_physic_eval*.json), 本脚本补齐前三个版本:
  - 基线: 裁剪(25/2/2) + /255 (无 CLAHE, 与 train_config 一致)
  - v1/v2: 裁剪 → CLAHE(LAB-L, clipLimit=2.0, tile 8x8) → /255
口径与 evaluate_sim_vs_physic.py 完全一致:
  STRAIGHT_TH=0.08, SHARP_TH=0.5, EXTREME_TH=0.9, UNDER_RATIO=0.8
  输出列动态判断 (与真值相关性高者为 angle)
额外输出 7 分箱 MAE (ANGLE_BINS 口径) 用于版本演化图
"""
import os
import json
import numpy as np
import cv2
from PIL import Image

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)
# 实车采集数据不在项目内; 可用环境变量 CAR_PHYSICAL_DATA 覆盖
_PHYS = os.environ.get('CAR_PHYSICAL_DATA') or next(
    p for p in (os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', '.discarded', 'physical'),
                os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', 'physical'),
                os.path.join(CAR_DIR, '.discarded', 'physical')) if os.path.isdir(p))

BASE = f'{MYSIM_DIR}/models'
PHYSIC_DIR = os.path.join(_PHYS, 'physicaldata2')
OUT_PATH = f'{MYSIM_DIR}/reports/version_eval_sameframe.json'

IMG_H_ORIG, IMG_W_ORIG, IMG_C = 120, 160, 3
ROI_CROP_TOP, ROI_CROP_LEFT, ROI_CROP_RIGHT = 25, 2, 2
STRAIGHT_TH = 0.08
SHARP_TH = 0.5
EXTREME_TH = 0.9
UNDER_RATIO = 0.8
ANGLE_BINS = [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
BIN_LABELS = ['急左', '中左', '小左', '直行', '小右', '中右', '急右']

VERSIONS = [
    ('baseline', '基线(无CLAHE)', f'{BASE}/mypilot1_s2_physical2/mypilot1_s2_physical_best.keras', False),
    ('v1', 'v1(opt,CLAHE)', f'{BASE}/mypilot1_s2_physical2_opt/mypilot1_s2_physical_best.keras', True),
    ('v2', 'v2(opt2,CLAHE)', f'{BASE}/mypilot1_s2_physical2_opt2/mypilot1_s2_physical_best.keras', True),
]

_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def preprocess(img_arr, use_clahe):
    a = img_arr[ROI_CROP_TOP:,
                ROI_CROP_LEFT:IMG_W_ORIG - ROI_CROP_RIGHT, :]
    if use_clahe:
        lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = _clahe.apply(lab[:, :, 0])
        a = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return a.astype(np.float32) / 255.0


def load_physic_records():
    recs = []
    for d in sorted(os.listdir(PHYSIC_DIR)):
        rp = os.path.join(PHYSIC_DIR, d, 'records.jsonl')
        if not os.path.exists(rp):
            continue
        with open(rp) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if r.get('user/throttle', 0) < 0.05:
                        continue
                    img = os.path.join(PHYSIC_DIR, d, r.get('cam/image_array', ''))
                    if os.path.exists(img):
                        r['_img'] = img
                        recs.append(r)
    return recs


def predict_angle(model, imgs, y_true):
    y = model.predict(imgs, verbose=0, batch_size=64)
    if isinstance(y, (list, tuple)):
        y = np.stack([np.asarray(o).reshape(-1) for o in y], axis=1)
    else:
        y = np.asarray(y).reshape(len(imgs), -1)
    c0 = abs(np.corrcoef(y[:, 0], y_true)[0, 1])
    c1 = abs(np.corrcoef(y[:, 1], y_true)[0, 1])
    angle_col = 0 if c0 >= c1 else 1
    return y[:, angle_col], angle_col, c0, c1


def bin_mae(y_pred, y_true):
    out = {}
    for i in range(7):
        m = (y_true >= ANGLE_BINS[i]) & (y_true < ANGLE_BINS[i + 1])
        out[BIN_LABELS[i]] = {
            'n': int(m.sum()),
            'mae': float(np.mean(np.abs(y_pred[m] - y_true[m]))) if m.any() else None,
        }
    return out


def evaluate(y_pred, y_true):
    err = y_pred - y_true
    straight = np.abs(y_true) < STRAIGHT_TH
    sharp = np.abs(y_true) >= SHARP_TH
    extreme = np.abs(y_true) >= EXTREME_TH
    under = sharp & (np.abs(y_pred) < UNDER_RATIO * np.abs(y_true))
    res = {
        'n': int(len(y_true)),
        'angle_mae': float(np.mean(np.abs(err))),
        'angle_corr': float(np.corrcoef(y_pred, y_true)[0, 1]),
        'pred_range': [float(y_pred.min()), float(y_pred.max())],
        'straight_n': int(straight.sum()),
        'straight_mae': float(np.mean(np.abs(err[straight]))) if straight.any() else None,
        'straight_pred_range': [float(y_pred[straight].min()),
                                float(y_pred[straight].max())] if straight.any() else None,
        'straight_over02_pct': float((np.abs(y_pred[straight]) > 0.2).mean() * 100) if straight.any() else None,
        'sharp_n': int(sharp.sum()),
        'sharp_mae': float(np.mean(np.abs(err[sharp]))) if sharp.any() else None,
        'sharp_under_pct': float(under.sum() / sharp.sum() * 100) if sharp.any() else None,
        'extreme_n': int(extreme.sum()),
        'extreme_mae': float(np.mean(np.abs(err[extreme]))) if extreme.any() else None,
        'bin_mae': bin_mae(y_pred, y_true),
    }
    return res


def main():
    recs = load_physic_records()
    y_true = np.array([r.get('user/angle', 0.0) for r in recs])
    paths = [r['_img'] for r in recs]
    print(f'physicaldata2 行车帧: {len(recs)}')

    results = {}
    for key, label, model_path, use_clahe in VERSIONS:
        print(f'\n{"=" * 64}\n[{label}] 预处理: '
              f'{"裁剪+CLAHE+/255" if use_clahe else "裁剪+/255"}')
        model = tf.keras.models.load_model(model_path, compile=False)
        imgs = np.array([preprocess(np.array(Image.open(p).convert('RGB'),
                                             dtype=np.uint8), use_clahe)
                         for p in paths])
        y_pred, col, c0, c1 = predict_angle(model, imgs, y_true)
        print(f'输出列映射: [{col}]=angle (corr {c0:.3f}/{c1:.3f})')
        res = evaluate(y_pred, y_true)
        print(f'  MAE {res["angle_mae"]:.4f}  corr {res["angle_corr"]:.4f}  '
              f'直行|p|>0.2 {res["straight_over02_pct"]:.1f}%  '
              f'急弯欠转 {res["sharp_under_pct"]:.1f}%  '
              f'极限MAE {res["extreme_mae"]:.4f}')
        results[key] = res
        del imgs
        import gc; gc.collect()

    with open(OUT_PATH, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f'\n结果已保存: {OUT_PATH}')


if __name__ == '__main__':
    main()
