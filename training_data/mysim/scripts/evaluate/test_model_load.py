"""测试模型能否独立加载和推理（不启动模拟器）"""
import numpy as np
import sys
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

# 尝试用手册中的方式加载模型
print("== 尝试 1: 用 KerasLinear 加载 ==")
try:
    from donkeycar.parts.keras import KerasLinear
    model = KerasLinear()
    model.load(f"{MYSIM_DIR}/models/mypilot/mypilot.keras")
    print("加载成功")
    # 造一张假图像测试推理
    fake_img = np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)
    result = model.run(fake_img)
    print("推理成功, 输出:", result)
except Exception as e:
    print(f"失败: {type(e).__name__}: {e}")

print()
print("== 尝试 2: 直接用 keras 加载 ==")
try:
    import tensorflow as tf
    m = tf.keras.models.load_model(f"{MYSIM_DIR}/models/mypilot/mypilot.keras")
    print("加载成功, 输入:", [i.name for i in m.inputs])
    print("输出:", [o.name for o in m.outputs])
    fake_img = (np.random.rand(1, 120, 160, 3).astype(np.float32))
    out = m.predict(fake_img, verbose=0)
    print("推理成功, 输出:", out)
except Exception as e:
    print(f"失败: {type(e).__name__}: {e}")
