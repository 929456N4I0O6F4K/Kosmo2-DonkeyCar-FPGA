#!/usr/bin/env python3
"""
测试模拟器 lidar 数据可用性 - 动态行驶版

让车以较高油门在赛道上跑一段时间,记录整个过程中的 lidar 数据
统计 2m 量程内是否能检测到障碍物

用法:
    # 先启动模拟器
    cd <car>/DonkeySimLinux
    ./donkey_sim.x86_64

    # 运行测试
    python test_lidar_sim.py
"""
import sys
import time
import numpy as np
from pathlib import Path

MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

sys.path.insert(0, MYSIM_DIR)

import donkeycar as dk
from donkeycar.parts.dgym import DonkeyGymEnv


def test_lidar_dynamic(scene_name="donkey-warehouse-v0",
                       max_range=2.0,
                       duration=30,
                       throttle=0.5):
    """
    让车在场景中动态行驶,持续记录 lidar 数据

    参数:
        scene_name: 场景名
        max_range: lidar 量程(m)
        duration: 测试持续时间(秒)
        throttle: 油门(0-1)
    """
    cfg = dk.load_config(f'{MYSIM_DIR}/myconfig.py')

    cfg.GYM_CONF = {
        "body_style": "donkey",
        "body_rgb": (128, 128, 128),
        "car_name": "lidar_test",
        "font_size": 100,
        "lidar_config": {
            "deg_per_sweep_inc": 2.0,
            "deg_ang_down": 0.0,
            "deg_ang_delta": -1.0,
            "num_sweeps_levels": 1,
            "max_range": max_range,
            "noise": 0.4,
            "offset_x": 0.0,
            "offset_y": 0.5,
            "offset_z": 0.5,
            "rot_x": 0.0,
        }
    }
    cfg.DONKEY_GYM = True
    cfg.SIM_RECORD_LIDAR = True
    cfg.SIM_HOST = "127.0.0.1"

    print(f"\n{'='*60}")
    print(f"场景: {scene_name}")
    print(f"量程: {max_range}m, 油门: {throttle}, 时长: {duration}s")
    print(f"{'='*60}")

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host=cfg.SIM_HOST,
        env_name=scene_name,
        conf=cfg.GYM_CONF,
        record_location=False,
        record_gyroaccel=False,
        record_velocity=False,
        record_lidar=True,
        delay=0,
    )

    import threading
    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    # 等待连接建立
    time.sleep(3)

    # 动态行驶,持续记录
    all_samples = []
    all_radar_13 = []  # 13点抽样
    detect_count = 0   # 有有效检测的样本数

    angles_13 = list(range(-60, 61, 10))  # -60 到 +60, 每10度
    deg_per_sweep_inc = 2.0

    print(f"开始行驶(油门={throttle})...")
    start_time = time.time()
    sample_interval = 0.3  # 每0.3秒采样一次
    last_sample_time = 0

    while time.time() - start_time < duration:
        elapsed = time.time() - start_time

        # 给油门让车跑,加小幅转向避免直线撞墙
        steer = 0.0
        if int(elapsed / 3) % 2 == 0:
            steer = 0.1  # 微右转
        else:
            steer = -0.1  # 微左转

        outputs = gym_env.run_threaded(steer, throttle)

        # 按间隔采样 lidar
        if elapsed - last_sample_time >= sample_interval:
            last_sample_time = elapsed

            if isinstance(outputs, list) and len(outputs) >= 2:
                lidar_data = outputs[-1]
                if isinstance(lidar_data, np.ndarray):
                    lidar_data = lidar_data.tolist()

                if isinstance(lidar_data, list) and len(lidar_data) > 0:
                    all_samples.append(lidar_data)

                    # 13点抽样
                    radar_13 = []
                    for angle in angles_13:
                        idx = int((angle % 360) / deg_per_sweep_inc)
                        if idx < len(lidar_data):
                            d = lidar_data[idx]
                            radar_13.append(d if d > 0 else 0)
                        else:
                            radar_13.append(0)

                    all_radar_13.append(radar_13)

                    valid_count = sum(1 for d in radar_13 if d > 0)
                    if valid_count > 0:
                        detect_count += 1
                        # 打印检测到的点
                        detected = [(a, d) for a, d in zip(angles_13, radar_13) if d > 0]
                        det_str = ", ".join(f"{a:+d}°:{d:.2f}m" for a, d in detected)
                        print(f"  [{elapsed:5.1f}s] 检测到 {valid_count} 点: {det_str}")
                    else:
                        # 每5秒打印一次状态
                        if int(elapsed) % 5 == 0 and abs(elapsed - int(elapsed)) < sample_interval:
                            print(f"  [{elapsed:5.1f}s] 无检测")

    # 统计结果
    total_samples = len(all_radar_13)
    print(f"\n--- {scene_name} 结果 ---")
    print(f"总采样数: {total_samples}")
    print(f"有检测的样本数: {detect_count}")
    print(f"检测率: {detect_count/total_samples*100:.1f}%" if total_samples > 0 else "N/A")

    if detect_count > 0:
        # 统计每个角度的检测情况
        print(f"\n各角度检测统计:")
        for i, angle in enumerate(angles_13):
            detections = [r[i] for r in all_radar_13 if r[i] > 0]
            if detections:
                print(f"  {angle:+3d}°: 检测 {len(detections)} 次, "
                      f"距离 min={min(detections):.2f}m max={max(detections):.2f}m "
                      f"avg={sum(detections)/len(detections):.2f}m")
            else:
                print(f"  {angle:+3d}°: 无检测")

        # 找到最近的检测
        all_detections = [d for r in all_radar_13 for d in r if d > 0]
        if all_detections:
            print(f"\n最近障碍物: {min(all_detections):.2f}m")
            print(f"最远障碍物: {max(all_detections):.2f}m")
            print(f"平均距离: {sum(all_detections)/len(all_detections):.2f}m")

    gym_env.shutdown()
    time.sleep(2)
    return detect_count, total_samples, all_radar_13


if __name__ == '__main__':
    # 测试 warehouse 场景(室内,最可能有近距离障碍物)
    tests = [
        ("donkey-warehouse-v0", 2.0, 30, 0.5),
        ("donkey-warehouse-v0", 5.0, 30, 0.5),
        ("donkey-generated-track-v0", 5.0, 30, 0.5),
    ]

    print("=" * 60)
    print("lidar 动态行驶测试 — 让车真正跑起来")
    print("=" * 60)

    results = []
    for scene, max_range, dur, thr in tests:
        detect, total, _ = test_lidar_dynamic(scene, max_range, dur, thr)
        results.append((scene, max_range, detect, total))

    # 汇总
    print("\n" + "=" * 60)
    print("=== 动态测试汇总 ===")
    print("=" * 60)
    for scene, max_range, detect, total in results:
        rate = detect/total*100 if total > 0 else 0
        status = "有数据" if detect > 0 else "无数据"
        print(f"{scene} ({max_range}m): {detect}/{total} 样本有检测 ({rate:.1f}%) [{status}]")
