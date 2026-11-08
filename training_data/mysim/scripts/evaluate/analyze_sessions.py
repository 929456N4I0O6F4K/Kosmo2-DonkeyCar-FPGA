#!/usr/bin/env python3
"""分析 physicaldata2 各 session 特征: 帧数/角度分布/方向倾向/直行弯道比例
用于决定 session 级 val 划分留出哪个 session
"""
import os
import json
import numpy as np
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)
# 实车采集数据不在项目内; 可用环境变量 CAR_PHYSICAL_DATA 覆盖
_PHYS = os.environ.get('CAR_PHYSICAL_DATA') or next(
    p for p in (os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', '.discarded', 'physical'),
                os.path.join(os.path.dirname(CAR_DIR), 'discarded_physical', 'physical'),
                os.path.join(CAR_DIR, '.discarded', 'physical')) if os.path.isdir(p))

DATA_DIR = os.path.join(_PHYS, 'physicaldata2')
BINS = [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
LABELS = ['急左', '中左', '小左', '直行', '小右', '中右', '急右']

def get_bin(a):
    for i in range(len(BINS) - 1):
        if BINS[i] <= a < BINS[i + 1]:
            return i
    return 6

print(f"{'Session':<12} {'帧数':>6} {'均值':>7} {'std':>6} {'min':>6} {'max':>6} "
      f"{'正角%':>6} {'急左':>5} {'中左':>5} {'小左':>5} {'直行':>5} {'小右':>5} {'中右':>5} {'急右':>5} "
      f"{'方向推断'}")
print("-" * 130)

all_sessions = []
for d in sorted(os.listdir(DATA_DIR)):
    path = os.path.join(DATA_DIR, d)
    rec_path = os.path.join(path, 'records.jsonl')
    if not os.path.exists(rec_path):
        continue
    angles = []
    for line in open(rec_path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get('user/throttle', 0) < 0.05:
            continue
        angles.append(r.get('user/angle', 0))

    if not angles:
        continue
    a = np.array(angles)
    bins = [0] * 7
    for x in a:
        bins[get_bin(x)] += 1
    pos_pct = (a > 0.05).sum() / len(a) * 100  # 右转比例
    neg_pct = (a < -0.05).sum() / len(a) * 100  # 左转比例

    # 方向推断: 正角多=顺时针(右转为主), 负角多=逆时针(左转为主)
    if pos_pct > 60:
        direction = "顺时针(右转为主)"
    elif neg_pct > 60:
        direction = "逆时针(左转为主)"
    else:
        direction = "混合/双向"

    print(f"{d:<12} {len(a):>6} {a.mean():>7.3f} {a.std():>6.3f} {a.min():>6.2f} {a.max():>6.2f} "
          f"{pos_pct:>5.1f}% {bins[0]:>5} {bins[1]:>5} {bins[2]:>5} {bins[3]:>5} {bins[4]:>5} {bins[5]:>5} {bins[6]:>5} "
          f"{direction}")
    all_sessions.append((d, len(a), a, bins, direction))

print("\n" + "=" * 80)
print("留出建议:")
print("- 留出的 session 应覆盖各种转弯场景 (有急左/急右), 不能只有直行")
print("- 留出方向最有代表性的 (顺时针或混合), 避免留出极端单向 session")
print("- 留出帧数适中, 不至于让训练数据太少")
print()

# 推荐: 帧数适中 + 角度分布最均衡 + 方向为混合或顺时针
best = None
best_score = -999
for d, n, a, bins, direction in all_sessions:
    turn_coverage = sum(bins[:3] + bins[4:])  # 非直行帧数
    balance = min(bins[0] + bins[1], bins[5] + bins[6])  # 左右弯较小值 (越均衡越好)
    score = turn_coverage + balance - abs(n - 1000) * 0.01  # 转弯覆盖+均衡-帧数偏差
    if "混合" in direction:
        score += 50  # 混合方向加分
    if score > best_score:
        best_score, best = score, d

print(f"推荐留出: {best} (综合分最高: 转弯覆盖+方向均衡+帧数适中)")
