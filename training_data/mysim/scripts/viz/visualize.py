"""
实时显示模型输入（摄像头图像）和输出（转向角、油门）

使用方式:
  python visualize.py                      # 默认保存图像到 visualize_output/
  python visualize.py --show               # 尝试用 cv2.imshow 实时显示（需完整版 opencv）
  python visualize.py --track warehouse     # 切换赛道

输出:
  - visualize_output/frame_XXXX.png  标注了 AI 预测的转向角和油门
  - 控制台打印每步的 angle/throttle/speed/cte
"""
import os
import sys
import numpy as np
import gym_donkeycar
import gymnasium as gym
import cv2
from pathlib import Path

MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

SIM_PATH = f"{CAR_DIR}/DonkeySimLinux/donkey_sim.x86_64"
MODEL_PATH = f"{MYSIM_DIR}/models/mypilot1/mypilot.keras"
OUTPUT_DIR = f"{MYSIM_DIR}/artifacts/visualize_output"

# 默认赛道，可通过命令行参数修改
TRACK = sys.argv[sys.argv.index("--track") + 1] if "--track" in sys.argv else "generated-track"
ENV_NAME = f"donkey-{TRACK}-v0"
SHOW_GUI = "--show" in sys.argv

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 加载模型
from donkeycar.parts.keras import KerasLinear
model = KerasLinear()
model.load(MODEL_PATH)

conf = {"exe_path": SIM_PATH, "port": 9091}
env = gym.make(ENV_NAME, conf=conf)
obs, info = env.reset()
print(f"赛道: {ENV_NAME}")
print(f"obs shape={obs.shape}, dtype={obs.dtype}")

# 测试 cv2.imshow 是否可用
use_gui = False
if SHOW_GUI:
    try:
        cv2.imshow("test", np.zeros((10, 10, 3), dtype=np.uint8))
        cv2.waitKey(1)
        cv2.destroyAllWindows()
        use_gui = True
        print("使用 cv2.imshow 实时显示（按 q 退出）")
    except Exception:
        print("cv2.imshow 不可用（安装的是 headless 版 opencv），改用 imwrite 保存图像")
else:
    print("使用 imwrite 保存图像到 visualize_output/")

print("AI 自动驾驶开始...")
for step in range(100):
    angle, throttle = model.run(obs)

    # 在图像上标注预测输出
    display = obs.copy()
    cv2.putText(display, f"Angle: {angle:+.3f}", (5, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(display, f"Throttle: {throttle:+.3f}", (5, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(display, f"Step: {step}", (5, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    if use_gui:
        cv2.imshow("Model I/O", display)
        if cv2.waitKey(1) == ord('q'):
            break
    else:
        # 保存前 10 帧和每隔 10 帧保存一帧
        if step < 10 or step % 10 == 0:
            cv2.imwrite(os.path.join(OUTPUT_DIR, f"frame_{step:04d}.png"), display)

    action = np.array([float(angle), float(throttle)], dtype=np.float32)
    obs, reward, terminated, truncated, info = env.step(action)
    speed = info.get("speed", 0)
    cte = info.get("cte", 0)
    if step % 10 == 0:
        print(f"step={step:4d}  angle={angle:+.3f}  throttle={throttle:+.3f}  speed={speed:.2f}  cte={cte:+.3f}")
    if terminated:
        print(f"撞车于 step {step}")
        break

print(f"完成 {step} 步")
env.close()
if use_gui:
    cv2.destroyAllWindows()
print(f"输出图像保存在: {OUTPUT_DIR}")
