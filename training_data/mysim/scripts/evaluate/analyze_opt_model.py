#!/usr/bin/env python3
"""分析 opt 模型的两个核心指标:
1. 直行帧 (|true|<0.08): 预测幅值分布 (是否有大转弯输出)
2. 大转弯帧 (|true|>0.5): 是否转向到位 (欠转分析)
"""
import os
import sys
import json
import random
import numpy as np
from PIL import Image
import cv2

from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, MYSIM_DIR)

import tensorflow as tf
# 实车采集数据不在项目内; 可用环境变量 CAR_PHYSICAL_DATA 覆盖
_PHYS = os.environ.get('CAR_PHYSICAL_DATA') or next(
    p for p in (os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', '.discarded', 'physical'),
                os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', 'physical'),
                os.path.join(CAR_DIR, '.discarded', 'physical')) if os.path.isdir(p))

PHYSIC_DATA_DIR = os.path.join(_PHYS, 'physicaldata2')
PHYSIC_DATA_DIR_PREV = os.path.join(_PHYS, 'physicdata')
STRAIGHT_THRESH = 0.08
INT8_PATH = f'{MYSIM_DIR}/models/mypilot1_s2_physical2_opt2/mypilot1_s2_physical_int8.tflite'

IMG_H_ORIG, IMG_W_ORIG, IMG_C = 120, 160, 3
ROI_CROP_TOP, ROI_CROP_LEFT, ROI_CROP_RIGHT = 25, 2, 2
IMG_H, IMG_W = 95, 156
CLAHE_CLIP = 2.0
CLAHE_TILE = (8, 8)
VALIDATION_SPLIT = 0.15
SEED = 42


def apply_clahe(img_uint8):
    lab = cv2.cvtColor(img_uint8, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_TILE)
    l = clahe.apply(l)
    lab = cv2.merge((l, a, b))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def preprocess(img_arr):
    arr = img_arr.copy()
    arr = arr[ROI_CROP_TOP:, :, :]
    arr = arr[:, ROI_CROP_LEFT:IMG_W_ORIG - ROI_CROP_RIGHT, :]
    arr = apply_clahe(arr)
    return arr.astype(np.float32) / 255.0


def load_all():
    all_records = []
    for d in sorted(os.listdir(PHYSIC_DATA_DIR)):
        path = os.path.join(PHYSIC_DATA_DIR, d)
        rec = os.path.join(path, 'records.jsonl')
        if not os.path.exists(rec):
            continue
        with open(rec) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if r.get('user/throttle', 0) < 0.05:
                        continue
                    img = r.get('cam/image_array', '')
                    ip = os.path.join(path, img)
                    if not img or not os.path.exists(ip):
                        continue
                    r['_img_path'] = ip
                    all_records.append(r)
    n_p2 = len(all_records)
    # physicdata 直行补充
    for d in sorted(os.listdir(PHYSIC_DATA_DIR_PREV)):
        path = os.path.join(PHYSIC_DATA_DIR_PREV, d)
        rec = os.path.join(path, 'records.jsonl')
        if not os.path.exists(rec):
            continue
        with open(rec) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if r.get('user/throttle', 0) < 0.05:
                        continue
                    img = r.get('cam/image_array', '')
                    ip = os.path.join(path, img)
                    if not img or not os.path.exists(ip):
                        continue
                    if abs(r.get('user/angle', 0)) >= STRAIGHT_THRESH:
                        continue
                    r['_img_path'] = ip
                    all_records.append(r)
    print(f'physicaldata2: {n_p2}, 合计: {len(all_records)}')
    # 相同划分
    rng = random.Random(SEED)
    shuffled = all_records.copy()
    rng.shuffle(shuffled)
    split = int(len(shuffled) * (1 - VALIDATION_SPLIT))
    val = shuffled[split:]
    print(f'验证集: {len(val)}')
    return val


def main():
    val = load_all()
    interp = tf.lite.Interpreter(model_path=INT8_PATH)
    interp.allocate_tensors()
    ind = interp.get_input_details()
    outd = interp.get_output_details()
    iscale, izero = ind[0]['quantization']
    oscale, ozero = outd[0]['quantization']

    preds, reals = [], []
    for i, r in enumerate(val):
        img = Image.open(r['_img_path']).convert('RGB')
        if img.size != (IMG_W_ORIG, IMG_H_ORIG):
            img = img.resize((IMG_W_ORIG, IMG_H_ORIG))
        x = preprocess(np.array(img, dtype=np.uint8))
        xq = np.round(x / iscale + izero).astype(np.int8)[None, ...]
        interp.set_tensor(ind[0]['index'], xq)
        interp.invoke()
        o = interp.get_tensor(outd[0]['index'])[0]
        # TFLite 输出[0]=angle, [1]=throttle (与 evaluate_int8_tta 一致)
        a = (float(o[0]) - ozero) * oscale
        t = (float(o[1]) - ozero) * oscale
        preds.append(a)
        reals.append(r.get('user/angle', 0))

    preds = np.array(preds)
    reals = np.array(reals)

    # ===== 1. 直行帧分析 =====
    print('\n===== 直行帧 (|true|<0.08) 预测幅值 =====')
    sm = np.abs(reals) < 0.08
    sp = preds[sm]
    print(f'帧数: {sm.sum()}')
    print(f'预测 |a|: mean={np.abs(sp).mean():.4f}, P95={np.percentile(np.abs(sp),95):.4f}, '
          f'P99={np.percentile(np.abs(sp),99):.4f}, MAX={np.abs(sp).max():.4f}')
    for th in [0.2, 0.3, 0.5]:
        n = (np.abs(sp) > th).sum()
        print(f'  |pred|>{th}: {n} 帧 ({n/len(sp)*100:.2f}%)')

    # ===== 2. 大转弯到位分析 =====
    print('\n===== 大转弯 (|true|>0.5) 到位分析 =====')
    bm = np.abs(reals) > 0.5
    bp, bt = preds[bm], reals[bm]
    print(f'帧数: {bm.sum()}')
    ratio = np.abs(bp) / np.clip(np.abs(bt), 1e-6, None)
    print(f'|pred|/|true|: mean={ratio.mean():.4f}, median={np.median(ratio):.4f}')
    under = ratio < 0.8   # 欠转 >20%
    over = ratio > 1.2    # 过转 >20%
    print(f'欠转(|pred|<0.8|true|): {under.sum()} 帧 ({under.sum()/len(bp)*100:.1f}%), '
          f'平均欠转幅度 {np.mean(np.abs(bt[under])-np.abs(bp[under])) if under.sum() else 0:.4f}')
    print(f'过转(|pred|>1.2|true|): {over.sum()} 帧 ({over.sum()/len(bp)*100:.1f}%)')
    print(f'大转弯 MAE: {np.mean(np.abs(bp-bt)):.4f}')

    # ===== 3. 极限转弯 |true|>0.8 =====
    print('\n===== 极限转弯 (|true|>0.8) 到位分析 =====')
    em = np.abs(reals) > 0.8
    if em.sum() > 0:
        ep, et = preds[em], reals[em]
        er = np.abs(ep) / np.abs(et)
        print(f'帧数: {em.sum()}')
        print(f'|pred|/|true|: mean={er.mean():.4f}, median={np.median(er):.4f}')
        eu = er < 0.8
        print(f'欠转: {eu.sum()} 帧 ({eu.sum()/len(ep)*100:.1f}%)')
        print(f'极限转弯 MAE: {np.mean(np.abs(ep-et)):.4f}')

    # ===== 4. 最差的大转弯帧 (欠转最严重) =====
    print('\n===== 欠转最严重的 10 帧 (|true|>0.5) =====')
    idx = np.where(bm)[0]
    worst = sorted(idx, key=lambda i: np.abs(reals[i]) - np.abs(preds[i]), reverse=True)[:10]
    for i in worst:
        print(f'  true={reals[i]:+.3f}, pred={preds[i]:+.3f}, 欠转={abs(reals[i])-abs(preds[i]):.3f}, '
              f'session={os.path.basename(os.path.dirname(val[i]["_img_path"]))[:25]}')

    # ===== 5. 直行大转角帧来源诊断 =====
    print('\n===== 直行帧大转角输出来源 (|true|<0.08 且 |pred|>0.3) =====')
    from collections import Counter
    src = Counter()
    for i in np.where(sm)[0]:
        if abs(preds[i]) > 0.3:
            # physicaldata2 与 physicdata 补充的区分: 通过路径
            is_prev = 'physicdata' in val[i]['_img_path']
            src['physicdata补充' if is_prev else 'physicaldata2'] += 1
    for k, v in src.most_common():
        print(f'  {k}: {v} 帧')
    # 这些帧的真实角度分布
    big_pred_straight = [(reals[i], preds[i]) for i in np.where(sm)[0] if abs(preds[i]) > 0.3]
    for t, p in big_pred_straight[:12]:
        is_prev = None
        print(f'  true={t:+.3f}, pred={p:+.3f}')


if __name__ == '__main__':
    main()
