"""
自动数据采集脚本 v2
- 启动 Donkey Simulator
- 使用 PID 控制器根据 cte(轨道偏差) 自动驾车
- 动态油门：直道加速、弯道减速
- 双向采集：正向 + 反向，平衡左右转向数据分布
- 将图像+转向+油门保存为 donkey tub 格式
- 可直接用 donkey train 训练
"""
import os
import sys
import time
import random
import numpy as np
import gym_donkeycar
import gymnasium as gym

# Donkey Car 的 tub 写入器
from donkeycar.parts.tub_v2 import TubWriter
from donkeycar.config import Config

# 从 myconfig.py 读取全局路径变量（与 manage.py / interactive_train.sh 保持一致）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
import myconfig as cfg
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

# ---- 配置 ----
SIM_PATH = f"{CAR_DIR}/DonkeySimLinux/donkey_sim.x86_64"
ENV_NAME = getattr(cfg, 'DONKEY_GYM_ENV_NAME', "donkey-generated-track-v0")
PORT = 9091
# 使用 myconfig.py 中的 DATA_PATH 全局变量
DATA_DIR = cfg.DATA_PATH
TUB_NAME = "tub_auto"
EPISODES = 10         # 跑 10 圈（5 正向 + 5 反向）
MAX_STEPS = 2000      # 每圈最大步数
TARGET_SPEED = 2.0    # 目标速度 (m/s)

# PID 参数（温和转向，避免撞墙）
STEERING_KP = -0.3    # 比例增益（温和，避免过度纠正）
STEERING_KI = -0.001  # 积分增益
STEERING_KD = -0.08   # 微分增益（阻尼，防止震荡）

# 动态油门参数
THROTTLE_BASE = 0.25      # 基础油门
THROTTLE_MAX = 0.35       # 直道最大油门（降低速度，减少撞车）
THROTTLE_MIN = 0.15       # 弯道最小油门
CTE_THROTTLE_THRESHOLD = 0.5  # CTE 超过此值开始减速


def make_env():
    conf = {
        "exe_path": SIM_PATH,
        "port": PORT,
        "body_style": "donkey",
        "body_rgb": (128, 128, 128),
        "car_name": "auto_collector",
        "font_size": 100,
    }
    env = gym.make(ENV_NAME, conf=conf)
    return env


def pid_steering(cte, last_cte, integral, dt=0.05, direction=1):
    """PID 转向控制器: 让车保持在轨道中心
    direction=1: 正向；direction=-1: 反向（反转转向输出以平衡数据）
    """
    integral += cte * dt
    integral = np.clip(integral, -10, 10)  # 防止积分饱和
    derivative = (cte - last_cte) / dt if dt > 0 else 0.0
    steer = (STEERING_KP * cte + STEERING_KI * integral + STEERING_KD * derivative)
    if direction == -1:
        steer = -steer
    steer = float(np.clip(steer, -1.0, 1.0))
    return steer, last_cte, integral


def dynamic_throttle(cte, steer, speed):
    """动态油门：直道加速，弯道减速"""
    # 根据转向角大小调整油门（转向越大越减速）
    steer_abs = abs(steer)
    if steer_abs < 0.1 and abs(cte) < CTE_THROTTLE_THRESHOLD:
        # 直道，加速
        throttle = THROTTLE_MAX
    elif steer_abs > 0.5 or abs(cte) > 1.5:
        # 大弯或偏离严重，减速
        throttle = THROTTLE_MIN
    else:
        # 中等弯道，线性插值
        ratio = steer_abs / 0.5
        throttle = THROTTLE_MAX - ratio * (THROTTLE_MAX - THROTTLE_MIN)
    # 加一点随机扰动，让数据更丰富
    throttle += random.uniform(-0.02, 0.02)
    throttle = float(np.clip(throttle, THROTTLE_MIN, THROTTLE_MAX))
    return throttle


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    tub_path = os.path.join(DATA_DIR, TUB_NAME)

    # 初始化 donkey config
    cfg = Config()
    cfg.IMAGE_W = 160
    cfg.IMAGE_H = 120
    cfg.IMAGE_DEPTH = 3
    inputs = ["cam/image_array", "user/angle", "user/throttle", "user/speed"]
    types = ["image_array", "float", "float", "float"]
    tub = TubWriter(base_path=tub_path, inputs=inputs, types=types)

    env = make_env()
    print(f"==> 环境已创建: {ENV_NAME}")
    print(f"==> 模拟器路径: {SIM_PATH}")
    print(f"==> 数据保存到: {tub_path}")
    print(f"==> 计划采集: {EPISODES} 圈 × {MAX_STEPS} 步 = 最多 {EPISODES * MAX_STEPS} 条")
    print(f"==> PID: Kp={STEERING_KP}, Ki={STEERING_KI}, Kd={STEERING_KD}")
    print(f"==> 动态油门: base={THROTTLE_BASE}, min={THROTTLE_MIN}, max={THROTTLE_MAX}")

    total_records = 0
    angle_records = []  # 用于统计转向角分布
    throttle_records = []  # 用于统计油门分布

    try:
        for ep in range(EPISODES):
            # 交替正向/反向，平衡左右转向数据
            direction = 1 if ep % 2 == 0 else -1
            direction_name = "正向" if direction == 1 else "反向"
            print(f"\n==> Episode {ep + 1}/{EPISODES} ({direction_name}) 开始")

            obs, info = env.reset()
            cte = float(info.get("cte", 0.0))
            last_cte = cte
            integral = 0.0
            ep_records = 0

            # 等待车稳定起步（前 10 步只控制不记录）
            for step in range(MAX_STEPS):
                steer, last_cte, integral = pid_steering(
                    cte, last_cte, integral, direction=direction)
                throttle = dynamic_throttle(cte, steer, float(info.get("speed", 0)))
                action = np.array([steer, throttle], dtype=np.float32)

                obs, reward, terminated, truncated, info = env.step(action)
                cte = float(info.get("cte", 0.0))
                speed = float(info.get("speed", 0.0))
                hit = info.get("hit", "none")

                # 跳过前 10 步（起步阶段不稳定）
                if step >= 10:
                    tub.run(obs, float(steer), float(throttle), float(speed))
                    ep_records += 1
                    total_records += 1
                    angle_records.append(float(steer))
                    throttle_records.append(float(throttle))

                if step % 100 == 0:
                    print(f"    step={step:4d}  cte={cte:+.3f}  steer={steer:+.3f}  "
                          f"throttle={throttle:.3f}  speed={speed:.2f}  hit={hit}")

                # 撞车或冲出轨道
                if terminated or hit != "none":
                    print(f"    Episode 结束: step={step} hit={hit} terminated={terminated}")
                    # 重置环境继续跑
                    if ep_records < 100:
                        obs, info = env.reset()
                        cte = float(info.get("cte", 0.0))
                        last_cte = cte
                        integral = 0.0
                        continue
                    break

            print(f"==> Episode {ep + 1} 完成: 记录 {ep_records} 条")

    except KeyboardInterrupt:
        print("\n==> 用户中断")
    finally:
        try:
            tub.close()
        except Exception:
            pass
        try:
            env.close()
        except Exception:
            pass

        print(f"\n{'=' * 60}")
        print(f"==> 总共采集 {total_records} 条记录")
        print(f"==> 数据保存在: {tub_path}")

        # 数据分布统计
        if angle_records:
            print(f"\n=== 数据分布统计 ===")
            print(f"转向角: min={min(angle_records):+.3f}  max={max(angle_records):+.3f}  "
                  f"mean={sum(angle_records)/len(angle_records):+.3f}")
            print(f"油门:   min={min(throttle_records):+.3f}  max={max(throttle_records):+.3f}  "
                  f"mean={sum(throttle_records)/len(throttle_records):+.3f}")

            # 转向角分布
            bins = [-1, -0.5, -0.1, -0.05, 0.05, 0.1, 0.5, 1]
            labels = ['<-0.5', '-0.5~-0.1', '-0.1~-0.05', '-0.05~0.05',
                      '0.05~0.1', '0.1~0.5', '>0.5']
            print("转向角分布:")
            for i in range(len(bins) - 1):
                c = sum(1 for a in angle_records if bins[i] <= a < bins[i + 1])
                print(f"  {labels[i]}: {c} ({100 * c / len(angle_records):.1f}%)")

        print(f"\n==> 下一步: 训练模型")
        print(f"    cd <mysim>")
        print(f"    donkey train --tub {tub_path} --model models/mypilot.keras")


if __name__ == "__main__":
    main()
