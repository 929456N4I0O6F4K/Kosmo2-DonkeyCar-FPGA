#!/usr/bin/env python3
"""
模拟器模型 vs 物理数据模型 同口径对比评估

模拟器侧: mypilot1_s2_bram_opt.keras @ warehouse 前 200 张 (复现 README 基准 0.0559)
物理侧:   mypilot1_s2_physical2_opt3 best.keras @ physicaldata2 全部行车帧

预处理与 FPGA 部署一致: 裁剪(25/2/2) + /255, 无 CLAHE
输出列顺序动态判断 (与真值相关性高者为 angle)
"""
import os
import json
import numpy as np
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

# ============ 配置 ============
SIM_DIR = f'{MYSIM_DIR}/datasets/sim/mypilot1/3_warehouse'
SIM_MODEL = f'{MYSIM_DIR}/models/mypilot1_s2_bram_opt/mypilot1_s2_bram_opt.keras'

PHYSIC_DIR = os.path.join(_PHYS, 'physicaldata2')
PHYSIC_MODEL = (f'{MYSIM_DIR}/models/'
                'mypilot1_s2_physical2_opt5/mypilot1_s2_physical_best.keras')

IMG_H_ORIG, IMG_W_ORIG, IMG_C = 120, 160, 3
ROI_CROP_TOP, ROI_CROP_LEFT, ROI_CROP_RIGHT = 25, 2, 2
N_SIM = 200          # README 口径: warehouse 前 200 张
SIM_THROTTLE_MIN = 0.0   # README 口径未过滤停车帧, 保持 0
STRAIGHT_TH = 0.08
SHARP_TH = 0.5
EXTREME_TH = 0.9
UNDER_RATIO = 0.8


def preprocess(img_arr):
    """裁剪 + 归一化, 与 FPGA 部署一致"""
    a = img_arr[ROI_CROP_TOP:,
                ROI_CROP_LEFT:IMG_W_ORIG - ROI_CROP_RIGHT, :]
    return a.astype(np.float32) / 255.0


def load_img(path):
    return preprocess(np.array(Image.open(path).convert('RGB'),
                              dtype=np.uint8))


def load_sim_records():
    """warehouse tub 格式: catalog_N.catalog"""
    recs = []
    for i in range(100):
        p = os.path.join(SIM_DIR, f'catalog_{i}.catalog')
        if not os.path.exists(p):
            break
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
    return recs


def load_physic_records():
    """physicaldata2: 每个 session 的 records.jsonl"""
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
    """推理并动态判断输出列 (与真值相关性高者为 angle)"""
    y = model.predict(imgs, verbose=0, batch_size=64)
    if isinstance(y, (list, tuple)):     # 多输出头: [angle(N,1), throttle(N,1)]
        y = np.stack([np.asarray(o).reshape(-1) for o in y], axis=1)
    else:
        y = np.asarray(y).reshape(len(imgs), -1)  # (N, 2) 单输出 Dense(2)
    c0 = abs(np.corrcoef(y[:, 0], y_true)[0, 1])
    c1 = abs(np.corrcoef(y[:, 1], y_true)[0, 1])
    angle_col = 0 if c0 >= c1 else 1
    throttle_col = 1 - angle_col
    return y[:, angle_col], y[:, throttle_col], angle_col, c0, c1


def evaluate(name, y_pred, y_true):
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    corr = float(np.corrcoef(y_pred, y_true)[0, 1])
    straight = np.abs(y_true) < STRAIGHT_TH
    sharp = np.abs(y_true) >= SHARP_TH
    extreme = np.abs(y_true) >= EXTREME_TH
    under = sharp & (np.abs(y_pred) < UNDER_RATIO * np.abs(y_true))
    res = {
        'n': int(len(y_true)),
        'angle_mae': mae,
        'angle_corr': corr,
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
    }
    print(f'\n{"=" * 64}')
    print(f'{name}')
    print('=' * 64)
    print(f'  样本数: {res["n"]}')
    print(f'  angle MAE:       {mae:.4f}')
    print(f'  angle 相关系数:  {corr:.4f}')
    print(f'  预测范围:        [{res["pred_range"][0]:.3f}, {res["pred_range"][1]:.3f}]')
    print(f'  --- 直行段 (|true|<{STRAIGHT_TH}) ---')
    print(f'  样本: {res["straight_n"]}  MAE: {res["straight_mae"]:.4f}')
    print(f'  预测范围: [{res["straight_pred_range"][0]:.3f}, {res["straight_pred_range"][1]:.3f}]')
    print(f'  |pred|>0.2 占比: {res["straight_over02_pct"]:.1f}%')
    print(f'  --- 大转弯 (|true|>={SHARP_TH}) ---')
    def fmt(v):
        return f'{v:.4f}' if isinstance(v, (int, float)) else 'N/A'
    print(f'  样本: {res["sharp_n"]}  MAE: {fmt(res["sharp_mae"])}')
    print(f'  欠转率 (|pred|<0.8|true|): {fmt(res["sharp_under_pct"])}%')
    print(f'  --- 极限转弯 (|true|>={EXTREME_TH}) ---')
    print(f'  样本: {res["extreme_n"]}  MAE: {fmt(res["extreme_mae"])}')
    return res


def main():
    # ============ 模拟器侧 ============
    print('加载模拟器模型:', os.path.basename(SIM_MODEL))
    sim_model = tf.keras.models.load_model(SIM_MODEL, compile=False)

    sim_recs = load_sim_records()[:N_SIM]
    print(f'warehouse 记录: {len(sim_recs)} 条 (README 口径)')
    sim_imgs = np.array([load_img(os.path.join(SIM_DIR, 'images',
                                               r['cam/image_array']))
                         for r in sim_recs])
    sim_true = np.array([r.get('user/angle', 0.0) for r in sim_recs])
    sim_pred, sim_thr, col, c0, c1 = predict_angle(sim_model, sim_imgs, sim_true)
    print(f'输出列映射: [{col}]=angle (corr {c0:.3f}/{c1:.3f})')
    res_sim = evaluate('模拟器模型 @ warehouse 200 张 (in-distribution)',
                       sim_pred, sim_true)

    # ============ 物理侧 ============
    print('\n加载物理模型:', os.path.basename(PHYSIC_MODEL))
    phy_model = tf.keras.models.load_model(PHYSIC_MODEL, compile=False)

    phy_recs = load_physic_records()
    print(f'physicaldata2 行车帧: {len(phy_recs)} 条')
    phy_imgs = np.array([load_img(r['_img']) for r in phy_recs])
    phy_true = np.array([r.get('user/angle', 0.0) for r in phy_recs])
    phy_pred, phy_thr, col2, c0b, c1b = predict_angle(phy_model, phy_imgs, phy_true)
    print(f'输出列映射: [{col2}]=angle (corr {c0b:.3f}/{c1b:.3f})')
    res_phy = evaluate('物理模型 v5 @ physicaldata2 全量 (in-distribution)',
                       phy_pred, phy_true)

    # ============ 对比汇总 ============
    print(f'\n{"=" * 64}')
    print('同口径对比汇总')
    print('=' * 64)
    rows = [
        ('angle MAE', 'angle_mae'),
        ('angle 相关系数', 'angle_corr'),
        ('直行段 MAE', 'straight_mae'),
        ('直行 |pred|>0.2 占比%', 'straight_over02_pct'),
        ('大转弯 MAE', 'sharp_mae'),
        ('大转弯欠转率%', 'sharp_under_pct'),
        ('极限转弯 MAE', 'extreme_mae'),
    ]
    print(f'{"指标":<26}{"模拟器(warehouse)":>20}{"物理(physicaldata2)":>22}')
    for label, key in rows:
        v1, v2 = res_sim[key], res_phy[key]
        f1 = f'{v1:.4f}' if isinstance(v1, (int, float)) else 'N/A'
        f2 = f'{v2:.4f}' if isinstance(v2, (int, float)) else 'N/A'
        print(f'{label:<28}{f1:>20}{f2:>22}')

    out = {'simulator': res_sim, 'physical': res_phy}
    out_path = f'{MYSIM_DIR}/reports/sim_vs_physic_eval_v5.json'
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f'\n结果已保存: {out_path}')


if __name__ == '__main__':
    main()
