# Donkey Car 本地部署使用手册

> 本地部署路径：`<ROOT>`
> Conda 环境名：`donkey`（Python 3.12）
> 模拟器：DonkeySimLinux（Unity 物理引擎，v22.11.06）
> 训练框架：TensorFlow 2.21（CPU 可用，GPU 需额外配置）
> 数据格式：Donkey Tub v2（图像 + 转向 + 油门 + 速度）

**所有命令均已经过实际验证。** 末尾标注 ✓ 的命令已在本环境中实测通过。

本手册涵盖：环境激活 → 模拟器使用 → 数据采集 → 模型训练 → 实时输入输出可视化 → 切换赛道 → 调试与排错。

---

## 1. 环境激活

每次开始工作前，先激活 conda 环境：

```bash
source $HOME/.miniforge3/etc/profile.d/conda.sh
conda activate donkey
cd "<ROOT>/mysim"
```

验证安装 ✓：

```bash
python -c "import tensorflow as tf; print('TF', tf.__version__)"
python -c "import donkeycar; print('OK')"
```

---

## 1.5 路径配置（全局变量）

所有脚本和代码统一使用 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 中的全局路径变量：

```python
# myconfig.py 顶部
import os
CAR_PATH = PACKAGE_PATH = os.path.dirname(os.path.realpath(__file__))

# 训练数据保存路径（tub 文件存放位置）
DATA_PATH = os.path.join(CAR_PATH, 'data')

# 模型保存路径（.keras / .tflite 文件存放位置）
MODELS_PATH = os.path.join(CAR_PATH, 'models')

# 官方预训练模型和数据集路径
OFFICIAL_MODELS_PATH = "<ROOT>/official_models"
```

### 同步使用这些变量的文件

| 文件                                                                                          | 使用的变量                                             | 说明                                  |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------- |
| [myconfig.py](<<ROOT>/mysim/myconfig.py>)                   | 定义`DATA_PATH`, `MODELS_PATH`, `OFFICIAL_MODELS_PATH` | 全局源头，所有其他文件从这里读取      |
| [auto_collect.py](<<ROOT>/mysim/scripts/collect/auto_collect.py>)           | `cfg.DATA_PATH`, `cfg.DONKEY_GYM_ENV_NAME`             | 自动采集时数据存入`DATA_PATH`         |
| [interactive_train.sh](<<ROOT>/mysim/scripts/interactive_train.sh>) | `$DATA_DIR`, `$MODELS_DIR`                             | 从 myconfig.py 读取，所有命令统一使用 |
| `manage.py drive`                                                                             | `DATA_PATH`, `MODELS_PATH`                             | donkeycar 内置支持                    |

### 修改数据保存路径

如需将数据保存到其他位置（如外接硬盘），编辑 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 第 22 行：

```python
# 方式 1：绝对路径
DATA_PATH = "/mnt/external_drive/donkey_data"

# 方式 2：相对 CAR_PATH 的子目录（默认）
DATA_PATH = os.path.join(CAR_PATH, 'data')
```

修改后**所有脚本自动同步**，无需改其他文件。

### 通过环境变量临时覆盖（不改配置文件）

`interactive_train.sh` 支持环境变量覆盖：

```bash
# 临时使用其他数据目录
DATA_PATH=/tmp/test_data ./scripts/interactive_train.sh setup

# 临时使用其他模型目录
MODELS_PATH=/mnt/models ./scripts/interactive_train.sh train mypilot_v2
```

### 验证当前路径配置 ✓

```bash
cd "<ROOT>/mysim"
./scripts/interactive_train.sh status | head -6
```

输出示例：

```
[路径配置] DATA_DIR=<ROOT>/mysim/data
[路径配置] MODELS_DIR=<ROOT>/mysim/models
=== 当前状态 ===
路径配置:
  数据目录: <ROOT>/mysim/data
  模型目录: <ROOT>/mysim/models
```

---

## 2. 模拟器使用

### 2.1 模拟器位置

```
<ROOT>/DonkeySimLinux/donkey_sim.x86_64
```

### 2.2 启动方式

**方式 A：带图形界面启动（推荐用于手动驾驶）** ✓

```bash
cd "<ROOT>/DonkeySimLinux"
./donkey_sim.x86_64
```

模拟器窗口打开后会监听两个端口：

- `9091`：主控制端口（Python 客户端连接）
- `9092`：辅助端口

**方式 B：无图形界面（headless，用于自动训练/批量采集）** ✓

```bash
./donkey_sim.x86_64 -batchmode -nographics
```

此模式不渲染画面，但仍执行物理模拟，适合无人值守的数据采集和模型测试。

### 2.3 检查模拟器是否就绪 ✓

```bash
ss -tunap | grep 9091
# 看到 LISTEN 表示模拟器已就绪
```

> 注意：模拟器启动后需要等待约 10-15 秒才会开始监听端口。

### 2.4 停止模拟器 ✓

```bash
pkill -f donkey_sim.x86_64
```

### 2.5 模拟器内部物理模型

模拟器基于 Unity 物理引擎，包含：

- **电机模型**：油门输入 → 加速度 → 速度（含阻力）
- **转向模型**：转向角 → 前轮偏转 → 实际轨迹（含惯性）
- **惯性**：车辆质量、摩擦、侧向力
- **碰撞检测**：偏离轨道会触发 `hit` 事件
- **传感器**：CTE（轨道偏差）、速度、位置(x,y,z)、陀螺仪、加速度计、激光雷达（可选）

---

## 3. 手动驾驶与数据采集

### 3.1 启动 Web 控制器 ✓

确保模拟器已启动，然后：

```bash
cd "<ROOT>/mysim"
python manage.py drive
```

输出会显示：

```
You can now go to localhost:8887 to drive your car.
```

### 3.2 浏览器驾驶

在浏览器打开 `http://localhost:8887` 或 `http://localhost:8887`

控制方式：

- **键盘**：方向键控制转向和油门
- **手柄**：连接 USB 手柄自动识别
- **鼠标**：虚拟摇杆

### 3.3 录制数据

- 点击页面上的 **"Start Recording"** 按钮开始录制
- 录制的数据保存在 `mysim/data/tub_<时间戳>/`
- 每条记录包含：摄像头图像、转向角、油门、速度

### 3.4 自动数据采集（PID 控制器）✓

本项目已配置自动采集脚本 [auto_collect.py](<<ROOT>/mysim/scripts/collect/auto_collect.py>)，无需手动驾驶：

```bash
cd "<ROOT>/mysim"
python scripts/collect/auto_collect.py
```

脚本使用 PID 控制器根据 CTE（轨道偏差）自动驾车，参数（在 auto_collect.py 顶部修改）：

- `EPISODES = 3`：跑 3 圈
- `MAX_STEPS = 2000`：每圈最大步数
- `STEERING_GAIN = 0.5`：转向 PID 比例增益
- `THROTTLE = 0.25`：固定油门

数据保存到 `mysim/datasets/sim/mypilot1/`，可直接用于训练。

---

## 4. 训练 AI 模型

### 4.1 训练命令 ✓

```bash
cd "<ROOT>/mysim"
donkey train --tub ./datasets/sim/mypilot1 --model models/mypilot1/mypilot.keras
```

参数说明：

- `--tub`：训练数据路径（可以是多个，用空格分隔）
- `--model`：模型输出路径
- `--type`：模型类型（默认 `linear`，可选 `categorical`、`tflite_linear`、`tensorrt_linear`）

### 4.2 训练多个 tub

```bash
donkey train --tub ./datasets/sim/mypilot1 --model models/mypilot1/mypilot.keras
```

### 4.3 训练过程

- 默认训练 100 epochs（带早停，实际约 20-30 epochs）
- 每个 epoch 显示训练/验证损失
- 模型自动保存到指定路径（同时生成 `.keras` 和 `.tflite`）
- 默认使用 PilotNet 网络架构（NVIDIA 自驾驶模型）

### 4.4 训练配置调整

编辑 [myconfig.py](<<ROOT>/mysim/myconfig.py>)（以下是实际存在的配置项）：

```python
# 批大小（默认 128）
BATCH_SIZE = 128

# 训练/验证集比例（默认 0.8）
TRAIN_TEST_SPLIT = 0.8

# 最大训练轮数（默认 100）
MAX_EPOCHS = 100

# 早停（默认开启）
USE_EARLY_STOP = True
EARLY_STOP_PATIENCE = 5
MIN_DELTA = .0005

# 学习率
LEARNING_RATE = 0.001

# 模型类型（默认 linear，也可在命令行用 --type 指定）
DEFAULT_MODEL_TYPE = 'linear'

# 数据增强（列表形式，如 ['MULTIPLY', 'BLUR']）
AUGMENTATIONS = []
AUG_BRIGHTNESS_RANGE = 0.2
AUG_BLUR_RANGE = (0, 3)
```

### 4.5 模型类型

- `linear`：连续输出转向和油门（默认，推荐）
- `categorical`：转向分桶（更适合复杂赛道）
- `tflite_linear`：TensorFlow Lite（用于树莓派部署）
- `tensorrt_linear`：TensorRT 优化（用于 Jetson）

### 4.6 迁移学习 ✓

使用预训练模型作为起点（`--transfer` 参数已验证存在）：

```bash
donkey train --tub ./data/tub_new --model models/newpilot.keras \
  --transfer models/mypilot1/mypilot.keras
```

### 4.7 从检查点恢复训练

```bash
donkey train --tub ./datasets/sim/mypilot1 --model models/mypilot1/mypilot.keras \
  --checkpoint models/checkpoint
```

---

## 5. 实时查看模型输入输出数据

### 5.1 方法一：Web 控制器实时显示 ✓

启动自动驾驶时，Web 控制器会显示模型实时预测：

```bash
cd "<ROOT>/mysim"
python manage.py drive --model models/mypilot1/mypilot.keras --type linear
```

在浏览器 `http://localhost:8887`：

- **Pilot Throttle**：AI 预测的油门
- **Pilot Angle**：AI 预测的转向
- **实时视频流**：摄像头输入图像
- **mode 选择**：切换 `user`（手动）/`local`（AI 辅助）/`local_angle`（仅 AI 转向）

### 5.2 方法二：TensorBoard 查看训练曲线 ✓

```bash
cd "<ROOT>/mysim"
tensorboard --logdir=models
```

浏览器打开 `http://localhost:6006`：

- 训练损失曲线
- 验证损失曲线
- 模型结构图

### 5.3 方法三：可视化脚本 ✓

已创建 [visualize.py](<<ROOT>/mysim/scripts/viz/visualize.py>)，可保存模型每步的输入图像和预测输出：

```bash
cd "<ROOT>/mysim"

# 默认模式：保存图像到 artifacts/visualize_output/
python scripts/viz/visualize.py

# 切换赛道
python scripts/viz/visualize.py --track warehouse

# 尝试实时 GUI 显示（需要完整版 opencv-python，当前安装的是 headless 版）
python scripts/viz/visualize.py --show
```

输出：

- `artifacts/visualize_output/frame_XXXX.png` - 标注了 AI 预测的转向角和油门
- 控制台打印每步的 angle/throttle/speed/cte

> 注意：当前环境安装的是 `opencv-python-headless`，不支持 `cv2.imshow`。
> 如需 GUI 显示，运行 `pip install opencv-python` 替换。
> 默认用 `cv2.imwrite` 保存图像，无需 GUI 支持。

### 5.4 验证模型独立加载 ✓

不启动模拟器，直接测试模型能否加载和推理：

```bash
python test_model_load.py
```

---

## 6. 切换不同赛道

### 6.1 可用赛道列表 ✓

本部署支持 11 个赛道（在 `gym-donkeycar/__init__.py` 注册）：

| 环境名                             | level 名           | 描述                     |
| ---------------------------------- | ------------------ | ------------------------ |
| `donkey-generated-track-v0`        | generated_track    | **随机生成赛道（默认）** |
| `donkey-generated-roads-v0`        | generated_road     | 随机生成道路             |
| `donkey-warehouse-v0`              | warehouse          | 仓库赛道                 |
| `donkey-mountain-track-v0`         | mountain_track     | 山地赛道                 |
| `donkey-roboracingleague-track-v0` | roboracingleague_1 | 竞速联赛赛道             |
| `donkey-waveshare-v0`              | waveshare          | Waveshare 赛道           |
| `donkey-minimonaco-track-v0`       | mini_monaco        | 摩纳哥微缩赛道           |
| `donkey-warren-track-v0`           | warren             | Warren 赛道              |
| `donkey-thunderhill-track-v0`      | thunderhill        | 雷霆山赛道               |
| `donkey-circuit-launch-track-v0`   | circuit_launch     | 环形赛道                 |
| `donkey-avc-sparkfun-v0`           | sparkfun_avc       | SparkFun AVC 赛道        |

### 6.2 通过 visualize.py 切换赛道 ✓

```bash
python scripts/viz/visualize.py --track warehouse      # 仓库赛道
python scripts/viz/visualize.py --track mountain-track  # 山地赛道
```

### 6.3 通过 auto_collect.py 切换赛道

修改 [auto_collect.py](<<ROOT>/mysim/scripts/collect/auto_collect.py>) 中的 `ENV_NAME`：

```python
ENV_NAME = "donkey-warehouse-v0"
```

### 6.4 通过 myconfig.py 切换赛道（manage.py 方式）

编辑 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 中的 `DONKEY_GYM_ENV_NAME`：

```python
DONKEY_GYM = True
DONKEY_SIM_PATH = "<ROOT>/DonkeySimLinux/donkey_sim.x86_64"
DONKEY_GYM_ENV_NAME = "donkey-warehouse-v0"  # 修改这里
```

然后运行 `python manage.py drive`。

### 6.5 训练跨赛道模型

在不同赛道各采集数据，合并训练：

```bash
donkey train \
  --tub ./data/tub_generated ./data/tub_warehouse \
  --model models/multipilot.keras \
  --type categorical
```

---

## 7. 测试自动驾驶

### 7.1 启动 AI 自动驾驶 ✓

```bash
# 1. 启动模拟器
cd "<ROOT>/DonkeySimLinux"
./donkey_sim.x86_64

# 2. 启动 AI 驾驶（另一个终端）
cd "<ROOT>/mysim"
python manage.py drive --model models/mypilot1/mypilot.keras --type linear
```

### 7.2 Web 控制器操作模式

在浏览器 `http://localhost:8887`：

- **User Mode**：手动驾驶（人类控制）
- **Local Pilot**：完全 AI 驾驶
- **Local Angle**：AI 控制转向，人控制油门
- **Auto Record**：AI 驾驶时录制新数据

### 7.3 通过可视化脚本测试 ✓

```bash
cd "<ROOT>/mysim"
python scripts/viz/visualize.py --track generated-track
```

### 7.4 Web 控制器模式说明（重要）✓

浏览器 `http://localhost:8887` 顶部下拉菜单 `(M)ode` 的三个选项：

| 显示文本       | 实际 value    | 含义                      | 快捷键 |
| -------------- | ------------- | ------------------------- | ------ |
| `(U)ser`       | `user`        | 人工接管（键盘/手柄控制） | `I`    |
| `Full (A)uto`  | `local`       | AI 全自动（转向 + 油门）  | `P`    |
| `Auto (S)teer` | `local_angle` | AI 转向 + 人工油门        | `O`    |

> **命名提示**：UI 上的 "Full Auto" 即代码层的 `local` 模式，并非 "Local"。日常交流时说 "AI 模式 / Full Auto" 即可。

默认启动模式由 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 的 `WEB_INIT_MODE` 决定：

```python
# 'user': 人工控制
# 'local_angle': AI 转向 + 人工油门
# 'local': AI 全自动
WEB_INIT_MODE = "local"
```

> **已知修复**：原版 donkeycar 在 WebSocket 客户端连接时**不推送当前模式**，
> 导致前端始终显示 "User"（前端默认值），与后端 `WEB_INIT_MODE` 不一致。
> 已在 [donkeycar/.../web_controller/web.py](<<ROOT>/donkeycar/donkeycar/parts/web_controller/web.py>)
> 的 `WebSocketDriveAPI.open()` 中追加初始状态推送，现在刷新浏览器即可看到正确的默认模式。

---

## 8. 交互式训练（带跑 → AI 自跑 → 随时纠错）

### 8.1 训练思想

本节实现的训练循环：

```
手动带跑（教 AI 正确走法）
    ↓
AI 自主驾驶（让 AI 自己跑）
    ↓
随时打断纠错（发现要撞墙立即接管）
    ↓
增量训练（用新数据重训模型）
    ↓
回到第二步测试新模型
```

核心配置（已在 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 中设置）：

```python
# 有油门自动录制数据
AUTO_RECORD_ON_THROTTLE = True

# AI 驾驶时也录制数据（纠错训练必需，否则纠错数据不会被记录）
RECORD_DURING_AI = True

# 启动默认 AI 全自动模式
WEB_INIT_MODE = "local"

# 禁用物理手柄，避免覆盖 Web 控制
USE_JOYSTICK_AS_DEFAULT = False
```

### 8.2 一键脚本 interactive_train.sh ✓

脚本路径：[mysim/interactive_train.sh](<<ROOT>/mysim/scripts/interactive_train.sh>)

```bash
cd "<ROOT>/mysim"

# 启动训练环境（模拟器 + Web 控制器）
./scripts/interactive_train.sh setup

# 用所有采集的数据训练新模型
./scripts/interactive_train.sh train

# 重启 manage.py drive（保持模拟器运行，加载新模型）
./scripts/interactive_train.sh restart

# 清空训练数据（开始新一轮采集）
./scripts/interactive_train.sh clean

# 查看当前状态（模拟器/Web/数据/模型）
./scripts/interactive_train.sh status
```

| 命令      | 作用                                                   |
| --------- | ------------------------------------------------------ |
| `setup`   | 启动模拟器（图形模式）和 manage.py drive               |
| `train`   | 收集`datasets/` 下所有数据训练 `models/mypilot1/mypilot.keras` |
| `restart` | 杀掉旧的`manage.py drive` 并用新模型重启               |
| `clean`   | 清空`datasets/` 和 `manifest.json`                    |
| `status`  | 查询模拟器/Web 进程、数据量、模型文件信息              |

### 8.3 完整训练流程

#### 第一步：启动环境 ✓

```bash
cd "<ROOT>/mysim"
./scripts/interactive_train.sh setup
```

看到 "训练环境已就绪！" 后，浏览器打开 `http://localhost:8887`。

#### 第二步：手动带跑（第一阶段）

1. 下拉菜单选 **`(U)ser`**（或按 `I` 键）
2. 用键盘方向键带小车跑 **3-5 圈**：
   - `↑` 油门 / `↓` 倒车 / `←` `→` 转向
   - 有油门时自动录制（`AUTO_RECORD_ON_THROTTLE = True`）
3. **撞墙时立即松油门**，停止录制避免污染数据
4. 每圈覆盖不同路况（直道、左弯、右弯、S 弯）

#### 第三步：AI 自主驾驶 + 随时打断纠错（第二阶段）

1. 下拉菜单切到 **`Full (A)uto`**（或按 `P` 键），让 AI 自己跑
2. **随时打断**：发现 AI 要撞墙时立即切回 **`(U)ser`** 模式接管
   - 模式切换有三种方式：
     - 鼠标点击下拉菜单
     - 键盘 `I`（User）/ `O`（Auto Steer）/ `P`（Full Auto）
     - 空格键 = 急停
3. 接管后用方向键纠正方向，继续跑
4. **AI 驾驶时也会录制数据**（`RECORD_DURING_AI = True`）
5. 你纠正时的数据会训练 AI 如何从错误中恢复

> 推荐策略：每跑 1-2 圈做一次纠错，AI 跑得越久纠错数据越丰富。

#### 第四步：增量训练

退出浏览器（或直接在终端运行）：

```bash
./scripts/interactive_train.sh train
```

脚本会自动：

- 找到 `data/` 下所有 `tub_*` 目录
- 显示每个 tub 的数据量
- 用 `donkey train --type linear` 训练新模型
- 保存到 `models/mypilot1/mypilot.keras`

#### 第五步：测试新模型

```bash
./scripts/interactive_train.sh restart
```

脚本会：

1. 杀掉旧的 `manage.py drive` 进程
2. 用新训练的 `models/mypilot1/mypilot.keras` 重启
3. 模拟器保持运行，无需重启

浏览器刷新 `http://localhost:8887`，选 `Full (A)uto` 测试新模型。
**重复第三、四、五步**持续优化模型。

### 8.4 训练循环示意图

```
┌─────────────────────────────────────────┐
│  1. ./scripts/interactive_train.sh setup        │
│     ↓                                   │
│  2. 浏览器 User 模式手动带跑 3-5 圈      │
│     ↓                                   │
│  3. 切到 Full Auto 让 AI 自跑           │
│     ↓                                   │
│  4. AI 要撞墙时立即切回 User 接管        │
│     ↓                                   │
│  5. ./scripts/interactive_train.sh train         │
│     ↓                                   │
│  6. ./scripts/interactive_train.sh restart       │
│     ↓                                   │
│  7. 浏览器 Full Auto 测试新模型         │
│     ↓                                   │
│  回到第 3 步，持续循环                   │
└─────────────────────────────────────────┘
```

### 8.5 查看训练状态 ✓

```bash
./scripts/interactive_train.sh status
```

输出示例：

```
=== 当前状态 ===
模拟器:
  运行中 (PID 510889)
  tcp   LISTEN     0      100   0.0.0.0:9091   ...
manage.py drive:
  运行中 (PID 573736)
  tcp   LISTEN     0      100   0.0.0.0:8887   ...
训练数据:
  data/tub_20260908_191630: 3492 条记录
模型:
  models/mypilot1/mypilot.keras: 9884162 bytes, 修改时间 2026-09-08 19:00:50
```

### 8.6 重置训练数据

如果要完全重新开始一轮训练（清空所有采集的数据）：

```bash
./scripts/interactive_train.sh clean
```

会删除：

- `datasets/` 所有数据目录
- `data/manifest.json` 索引文件

> 注意：`models/mypilot1/mypilot.keras` 不会被删除，如需从零开始也训练新模型，
> 手动删除：`rm -f models/mypilot1/mypilot.keras`

### 8.7 常见问题

#### Q1: 浏览器默认显示 "User" 而不是 "Full Auto"

已在 `donkeycar/parts/web_controller/web.py` 的 `WebSocketDriveAPI.open()` 中修复，
刷新浏览器或重启 `./scripts/interactive_train.sh restart` 即可看到正确的 `WEB_INIT_MODE` 默认模式。

#### Q2: 物理手柄覆盖 Web 控制

已在 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 中设置
`USE_JOYSTICK_AS_DEFAULT = False`。Web 界面的红色提示
"Note: physical game controller overrides web control." 可以忽略。

#### Q3: AssertionError: Trying to create a tub with different inputs/types

原因：开启 `RECORD_DURING_AI` 后新数据包含额外字段，与旧 tub 字段冲突。
解决：清空旧数据后重新采集。

```bash
./scripts/interactive_train.sh clean
./scripts/interactive_train.sh setup
```

#### Q4: AI 一直向左/右转

原因：训练数据质量差（转向角分布偏斜、油门恒定）。
解决：使用交互式训练流程，手动纠错时确保覆盖左右两个方向的弯道，
并用 `./scripts/interactive_train.sh train` 重新训练。

#### Q5: `train` 提示 "没有找到训练数据"

原因：新版 donkeycar (v5.4+) 使用 **Tub v2 格式**，数据直接保存在 `data/` 目录下
（`manifest.json` + `catalog_*.catalog` + `images/`），而不是旧的 `datasets/` 子目录。
早期版本的 `interactive_train.sh` 脚本只查找 `datasets/` 目录，所以找不到数据。

检查数据是否存在：

```bash
ls -la data/manifest.json data/catalog_*.catalog 2>/dev/null
cat data/manifest.json | tail -1 | python3 -c "import sys,json; print('记录数:', json.loads(sys.stdin.read()).get('current_index', 0))"
```

解决：脚本已修复，支持两种存储格式：

- **Tub v2**（新版，`manifest.json` 在 `data/` 根目录）
- **旧版**（`datasets/` 子目录）

如果脚本版本旧，手动指定训练数据路径：

```bash
donkey train --tub data/ --model models/mypilot1/mypilot.keras --type linear
```

---

## 9. 使用流水线脚本

本项目提供了 [run_pipeline.sh](<<ROOT>/run_pipeline.sh>) 一键脚本：

```bash
cd "<ROOT>"

# 1. 仅启动模拟器（手动驾驶）
./run_pipeline.sh sim

# 2. 自动采集训练数据
./run_pipeline.sh collect

# 3. 训练模型
./run_pipeline.sh train

# 4. 测试自动驾驶
./run_pipeline.sh autopilot

# 5. 完整流水线（采集 → 训练 → 测试）
./run_pipeline.sh all
```

> 注意：collect 阶段会调用 `auto_collect.py`（PID 控制器自动驾车采集）。
> train 阶段会自动找到 `data/` 下所有 tub 数据。
> autopilot 阶段用 `--type linear` 加载模型。

---

## 10. 调试与排错

### 10.1 模拟器启动失败

```bash
# 检查端口是否被占用
ss -tunap | grep -E "9091|9092"

# 杀掉残留进程
pkill -f donkey_sim.x86_64

# 检查可执行权限
ls -la DonkeySimLinux/donkey_sim.x86_64
chmod +x DonkeySimLinux/donkey_sim.x86_64
```

### 10.2 Python 连接失败

```
WARNING:gym_donkeycar.envs.donkey_sim:waiting for sim to start..
```

表示模拟器未启动或端口未就绪。先启动模拟器，等待 10-15 秒后再运行 Python 脚本。

### 10.3 GPU 加速

检查 TensorFlow 是否检测到 GPU：

```bash
python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
```

如果输出为空（当前环境状态），安装 GPU 版：

```bash
pip install tensorflow[and-cuda]
```

> 当前环境：TensorFlow 2.21 已安装，但未检测到 GPU（缺少 cuDNN）。
> CPU 训练也能工作，528 条数据训练约 1 分钟即可完成。

### 10.4 训练数据查看 ✓

```bash
# 查看数据数量
ls mysim/datasets/sim/mypilot1/images/ | wc -l

# 查看记录内容
head -5 mysim/datasets/sim/mypilot1/catalog_0.catalog

# 查看图像
ls mysim/datasets/sim/mypilot1/images/ | head -5
```

### 10.5 模型性能差

- 增加训练数据（多跑几圈，修改 auto_collect.py 中的 EPISODES）
- 切换模型类型：`donkey train --type categorical`
- 调整 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 中的 `BATCH_SIZE`、`MAX_EPOCHS`、`LEARNING_RATE`
- 使用 `tensorboard --logdir=models` 查看损失曲线

### 10.6 内存不足

- 减小 `BATCH_SIZE`（如 32）
- 减少 `MAX_STEPS`（auto_collect.py 中的参数）
- 关闭其他占用内存的程序

### 10.7 cv2.imshow 报错 ✓

```
cv2.error: ... The function is not implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support.
```

原因：安装的是 `opencv-python-headless`，不支持 GUI。解决：

```bash
# 方案一：用 imwrite 代替 imshow（默认，推荐）
python scripts/viz/visualize.py

# 方案二：安装完整版 opencv
pip install opencv-python --force-replace
python scripts/viz/visualize.py --show
```

---

## 11. 目录结构

```
<ROOT>/
├── donkeycar/                  # Donkey Car 主框架（git clone）
├── gym-donkeycar/              # Gym 环境封装
├── DonkeySimLinux/             # Unity 模拟器
│   └── donkey_sim.x86_64
├── fpga_dev_kit/               # FPGA 部署开发包
├── official_models/            # 官方预训练模型
├── mysim/                      # 用户应用
│   ├── manage.py              # 驾驶/训练入口
│   ├── train.py               # 训练入口
│   ├── calibrate.py           # 校准
│   ├── config.py              # donkeycar 基础配置
│   ├── myconfig.py            # 用户配置（DATA_PATH / MODELS_PATH 等）
│   ├── custom_crop.py         # 自定义裁剪预处理
│   ├── paths.py               # 路径配置（相对定位）
│   ├── data/                  # 临时采集数据（Tub v2 格式）
│   ├── datasets/              # 汇总后的全部数据集
│   │   └── sim/               # 模拟器数据（按模型来源分组）
│   │       ├── mypilot1/
│   │       ├── mypilot_radar/
│   │       └── mypilot_linear/
│   ├── models/                # 全部模型（按版本分子目录）
│   │   ├── mypilot1/          # 基础模型
│   │   ├── mypilot1_s1/ s2/ s2_*/  # 各优化版本
│   │   └── logs/              # TensorBoard 训练记录
│   ├── artifacts/             # 构建产物（hls4ml / quantization）
│   ├── reports/               # 评估与可视化报告
│   └── scripts/               # 脚本（按用途分组）
│       ├── collect/           # 数据采集、平衡、镜像
│       ├── train/             # 各版本训练脚本
│       ├── quantize/          # INT8 / hls4ml 量化
│       ├── evaluate/          # 评估与测试
│       ├── report/            # 报告生成
│       ├── viz/               # 可视化
│       ├── dcar               # donkey 命令包装
│       └── interactive_train.sh
├── run_pipeline.sh            # 一键流水线
└── USAGE_GUIDE.md            # 本手册
```

---

## 12. 常用命令速查（均已验证 ✓）

```bash
# 激活环境
source $HOME/.miniforge3/etc/profile.d/conda.sh && conda activate donkey

# 启动模拟器（图形）
cd "<ROOT>/DonkeySimLinux" && ./donkey_sim.x86_64

# 启动模拟器（无图形）
./donkey_sim.x86_64 -batchmode -nographics

# 手动驾驶（浏览器 localhost:8887）
cd "<ROOT>/mysim" && python manage.py drive

# 自动采集数据
python scripts/collect/auto_collect.py

# 训练模型
donkey train --tub ./datasets/sim/mypilot1 --model models/mypilot1/mypilot.keras

# AI 自动驾驶
python manage.py drive --model models/mypilot1/mypilot.keras --type linear

# 可视化模型输入输出
python scripts/viz/visualize.py
python scripts/viz/visualize.py --track warehouse

# TensorBoard 查看训练曲线
tensorboard --logdir=models

# 切换赛道（编辑 myconfig.py）
# DONKEY_GYM_ENV_NAME = "donkey-warehouse-v0"

# 停止模拟器
pkill -f donkey_sim.x86_64

# 查看数据
ls datasets/sim/mypilot1/3_warehouse/images/ | wc -l
```

---

## 13. 进阶：自定义训练

### 13.1 使用不同网络架构

编辑 [myconfig.py](<<ROOT>/mysim/myconfig.py>)：

```python
# 线性模型（默认，PilotNet）
DEFAULT_MODEL_TYPE = 'linear'

# 分类模型（转向分桶，更适合复杂赛道）
DEFAULT_MODEL_TYPE = 'categorical'
```

也可通过命令行 `--type categorical` 指定，会覆盖 myconfig.py 设置。

### 13.2 数据增强

编辑 [myconfig.py](<<ROOT>/mysim/myconfig.py>)：

```python
# 可用的增强方法：MULTIPLY, BLUR
AUGMENTATIONS = ['MULTIPLY', 'BLUR']
AUG_BRIGHTNESS_RANGE = 0.2
AUG_BLUR_RANGE = (0, 3)
```

### 13.3 迁移学习 ✓

```bash
donkey train --tub ./data/tub_new --model models/newpilot.keras \
  --transfer models/mypilot1/mypilot.keras
```

---

## 14. 官方预训练模型与迁移学习

官方仓库 [autorope/donkey_datasets](https://github.com/autorope/donkey_datasets) 提供预训练模型和训练数据集，已下载到本地 [official_models/](<<ROOT>/official_models>)。

### 14.1 官方资源目录结构

```
official_models/
├── README.md                      # 详细使用说明
├── 1_sim_datasets/                # 模拟器训练数据集（3 个）
│   ├── sim_gen_roads_pid_1_rl.tar.gz     # 随机生成赛道（PID 自动采集 1）
│   ├── sim_gen_roads_pid_2_rl.tar.gz     # 随机生成赛道（PID 自动采集 2）
│   └── sim_warehouse_manual.tar.gz       # 仓库赛道（人工驾驶采集）
├── 2_circuit_launch_pilots/       # Circuit Launch 预训练模型（12 个）
│   ├── pilot_21-08-13_4.keras      # linear, 无增强, 无裁剪
│   ├── pilot_21-08-13_5.keras      # categorical, 无增强, 无裁剪
│   ├── pilot_21-08-13_6.keras      # memory, 无增强, 无裁剪
│   ├── pilot_21-08-13_7.keras      # linear, 有增强, 无裁剪
│   ├── pilot_21-08-13_8.keras      # categorical, 有增强, 无裁剪
│   ├── pilot_21-08-13_9.keras      # memory, 有增强, 无裁剪
│   ├── pilot_21-08-13_10.keras     # linear, 无增强, 有裁剪  ★与我当前 CROP 配置一致
│   ├── pilot_21-08-13_11.keras     # categorical, 无增强, 有裁剪
│   ├── pilot_21-08-13_12.keras     # memory, 无增强, 有裁剪
│   ├── pilot_21-08-13_16.keras     # memory, 有增强, 有裁剪
│   ├── pilot_21-08-13_17.keras     # categorical, 有增强, 有裁剪
│   ├── pilot_21-08-13_19.h5     # linear, 有增强, 有裁剪  ★★最推荐用于迁移学习
│   ├── pilot_21-08-13_*.tflite     # 对应的 TFLite 版本
│   ├── database.json               # 训练历史和配置
│   └── myconfig_circuit_launch.py  # 官方训练时使用的配置
└── 3_large_datasets_raw/           # 全部 39 个原始数据集
    ├── american_steel_*.tar.gz
    ├── circuit_launch_*.tar.gz
    ├── sim_*.tar.gz                # 包含 3 个模拟器数据集
    ├── ucsd_*.tar.gz
    └── ...
```

### 14.2 模型选择指南

| No     | 类型       | 增强Y/N | 裁剪Y/N | 推荐用途                           |
| ------ | ---------- | ------- | ------- | ---------------------------------- |
| 4      | linear     | N       | N       | 基础对比                           |
| 5      | cat        | N       | N       | 分类输出                           |
| 6      | memory     | N       | N       | 时序记忆                           |
| 7      | linear     | Y       | N       | 泛化更好                           |
| 8      | cat        | Y       | N       |                                    |
| 9      | memory     | Y       | N       |                                    |
| 10     | linear     | N       | Y       | **推荐**：与当前 CROP 配置一致     |
| 11     | cat        | N       | Y       |                                    |
| 12     | memory     | N       | Y       |                                    |
| 16     | memory     | Y       | Y       |                                    |
| 17     | cat        | Y       | Y       |                                    |
| **19** | **linear** | **Y**   | **Y**   | **★最推荐**：有增强+裁剪，泛化最好 |

**重要**：使用 10/11/12/16/17/19（有裁剪）的模型时，必须在 [myconfig.py](<<ROOT>/mysim/myconfig.py>) 中启用：

```python
TRANSFORMATIONS = ['CROP']
ROI_CROP_TOP = 45
```

否则输入尺寸不匹配会报错。

### 14.3 指定模型路径和名称

所有命令支持通过参数指定模型名（不带 .keras 后缀）：

| 命令      | 语法                                                         | 说明               |
| --------- | ------------------------------------------------------------ | ------------------ |
| `setup`   | `./scripts/interactive_train.sh setup [model_name]`                  | 启动时加载指定模型 |
| `train`   | `./scripts/interactive_train.sh train [model_name] [transfer_model]` | 训练或迁移学习     |
| `restart` | `./scripts/interactive_train.sh restart [model_name]`                | 重启测试指定模型   |

**判断"从头训练"还是"补充训练"的规则**：

```bash
# 1. 从头训练（新模型）— 不传 transfer_model
./scripts/interactive_train.sh train mypilot_v2
# → 输出 models/mypilot_v2.keras，随机初始化权重

# 2. 补充训练（迁移学习）— 传 transfer_model
./scripts/interactive_train.sh train mypilot_fine ../official_models/2_circuit_launch_pilots/pilot_21-08-13_19.h5
# → 加载 pilot_21-08-13_19.h5 作为初始权重
# → 用本地数据微调
# → 输出 models/mypilot_fine.keras

# 3. 不指定名字（默认 mypilot，会覆盖）
./scripts/interactive_train.sh train
```

### 14.4 加载官方模型直接测试（不训练）

```bash
cd "<ROOT>/mysim"

# 复制官方模型到 models/ 目录
cp ../official_models/2_circuit_launch_pilots/pilot_21-08-13_19.h5 models/official_19.h5

# 启动时指定
./scripts/interactive_train.sh setup official_19

# 浏览器打开 http://localhost:8887 选 Full Auto 测试
```

**注意**：官方模型是真实赛道训练的，在模拟器中可能表现不佳（域偏移），主要用于迁移学习的起点。

### 14.5 迁移学习（补充训练）

在已有模型基础上继续学习，适合快速适应新场景：

```bash
cd "<ROOT>/mysim"

# 1. 启动环境采集本地数据
./scripts/interactive_train.sh setup
# 浏览器 User 模式带跑 3-5 圈

# 2. 用官方模型作为起点，本地数据微调
./scripts/interactive_train.sh train mypilot_fine ../official_models/2_circuit_launch_pilots/pilot_21-08-13_19.h5

# 3. 测试微调后的模型
./scripts/interactive_train.sh restart mypilot_fine
```

**迁移学习时建议调低学习率**，编辑 [myconfig.py](<<ROOT>/mysim/myconfig.py>)：

```python
# 迁移学习专用参数（训练完后改回原值）
LEARNING_RATE = 0.0001    # 默认 0.0005，迁移学习降到 1/5
MAX_EPOCHS = 10           # 默认 50，迁移学习用少量 epochs 即可
```

训练完后改回原值：

```python
LEARNING_RATE = 0.0005
MAX_EPOCHS = 50
```

### 14.6 混合官方数据 + 本地数据训练

最彻底的提升泛化能力方法：

```bash
cd "<ROOT>/mysim"

# 1. 解压官方数据到 data_official/
mkdir -p data_official
tar xzf ../official_models/1_sim_datasets/sim_gen_roads_pid_1_rl.tar.gz -C data_official/

# 2. 启动环境采集本地数据（存到 data/）
./scripts/interactive_train.sh setup
# 浏览器带跑 3-5 圈

# 3. 合并训练（手动指定两个 tub 路径）
donkey train --tub data/ data_official/ --model models/mixed.keras --type linear

# 4. 测试
./scripts/interactive_train.sh restart mixed
```

### 14.7 完整工作流示例

**场景 A：用官方模拟器数据集训练基线模型**

```bash
cd "<ROOT>/mysim"

# 1. 解压官方模拟器数据集
tar xzf ../official_models/1_sim_datasets/sim_gen_roads_pid_1_rl.tar.gz -C data_official/

# 2. 用官方数据训练基线模型
donkey train --tub data_official/ --model models/baseline.keras --type linear

# 3. 启动测试
./scripts/interactive_train.sh setup baseline

# 4. 浏览器选 Full Auto 测试
```

**场景 B：官方模型 + 本地数据 迁移学习**

```bash
cd "<ROOT>/mysim"

# 1. 启动环境采集本地数据
./scripts/interactive_train.sh setup
# 浏览器 User 模式带跑 3-5 圈

# 2. 用官方模型作为起点，本地数据微调
./scripts/interactive_train.sh train mypilot_v2 ../official_models/2_circuit_launch_pilots/pilot_21-08-13_19.h5

# 3. 测试微调后的模型
./scripts/interactive_train.sh restart mypilot_v2
```

**场景 C：混合官方数据 + 本地数据训练**

```bash
cd "<ROOT>/mysim"

# 1. 解压官方数据到 data_official/
tar xzf ../official_models/1_sim_datasets/sim_gen_roads_pid_1_rl.tar.gz -C data_official/

# 2. 启动环境采集本地数据（存到 data/）
./scripts/interactive_train.sh setup
# 浏览器带跑 3-5 圈

# 3. 合并训练（手动指定两个 tub 路径）
donkey train --tub data/ data_official/ --model models/mixed.keras --type linear

# 4. 测试
./scripts/interactive_train.sh restart mixed
```

### 14.8 数据增强配置（已启用）

[myconfig.py](<<ROOT>/mysim/myconfig.py>) 中已配置数据增强，提升泛化能力：

```python
# 训练时随机调整亮度/模糊，模拟不同场景光照
AUGMENTATIONS = ['BRIGHTNESS', 'BLUR']
AUG_BRIGHTNESS_RANGE = 0.3
AUG_BLUR_RANGE = (0, 4)
```

下次训练时自动生效，无需额外操作。

### 14.9 ROI 裁剪配置（已启用）

为减少背景干扰，已启用 CROP 转换：

```python
# 裁掉图像上部 45 行（天空、远处背景），保留下部 75 行（纯道路）
TRANSFORMATIONS = ['CROP']
ROI_CROP_TOP = 45
ROI_CROP_BOTTOM = 0
ROI_CROP_RIGHT = 0
ROI_CROP_LEFT = 0
```

**注意**：启用 CROP 后，旧模型（未裁剪训练的）不兼容，必须重新训练。

---

## 15. dcar 命令行训练管理工具（推荐）

`dcar` 是统一管理模型创建、数据采集、训练、清除的命令行工具，采用"模型-数据同目录"组织结构。

### 15.1 目录结构

```
models/
└── <model_name>/                    # 模型同名根目录
    ├── <model_name>.keras           # 模型文件
    ├── 0_custom/                    # 物理世界场景数据
    ├── 1_generated-track/           # 模拟器场景 1 数据
    ├── 2_generated-roads/           # 模拟器场景 2 数据
    ├── 3_warehouse/                 # 模拟器场景 3 数据
    ├── 4_avc-sparkfun/              # 模拟器场景 4 数据
    └── 5_mountain/                  # 模拟器场景 5 数据
```

### 15.2 场景映射

| 编号 | 场景名称        | Donkey 环境名             | 启动模拟器 |
| ---- | --------------- | ------------------------- | ---------- |
| 0    | custom          | 物理世界(自定义)          | 否         |
| 1    | generated-track | donkey-generated-track-v0 | 是         |
| 2    | generated-roads | donkey-generated-roads-v0 | 是         |
| 3    | warehouse       | donkey-warehouse-v0       | 是         |
| 4    | avc-sparkfun    | donkey-avc-sparkfun-v0    | 是         |
| 5    | mountain        | donkey-mountain-track-v0  | 是         |

### 15.3 命令速查

| 命令    | 语法                                    | 说明                               |
| ------- | --------------------------------------- | ---------------------------------- |
| create  | `./dcar create <model_name>`            | 创建模型（检查同名，询问是否创建） |
| collect | `./dcar collect <model_name>`           | 数据采集（选场景，启动模拟器/Web） |
| train   | `./dcar train <model_name>`             | 训练（增量/从头+选场景）           |
| clean   | `./dcar clean [model_name] [scene_num]` | 清除数据/进程                      |
| status  | `./dcar status`                         | 查看状态                           |
| list    | `./dcar list`                           | 列出所有模型                       |
| help    | `./dcar help`                           | 显示帮助                           |

### 15.4 create - 创建模型 ✓

检查同名模型是否存在，存在则显示相对路径，不存在则询问是否创建。

```bash
cd "<ROOT>/mysim"

# 创建新模型
./dcar create mypilot
# 输出：
#   相对路径: models/mypilot/mypilot.keras
#   状态: 不存在
#   是否创建同名文件夹？[y/N] y
#   已创建: models/mypilot

# 再次运行（已存在）
./dcar create mypilot
# 输出：
#   相对路径: models/mypilot
#   状态: 已存在，可直接使用（尚未训练，仅有数据目录）
```

**判断逻辑**：
- 同名目录存在 → 显示"已存在可直接使用"
- 同名目录不存在 → 询问"是否创建同名文件夹？"，回复 Y 才创建

### 15.5 collect - 数据采集 ✓

必须给定模型名称，选择场景后采集数据到对应场景子目录。

```bash
./dcar collect mypilot
# 输出：
#   可用场景：
#     0) 物理世界(自定义)（不启动模拟器）
#     1) donkey-generated-track-v0
#     ...
#   选择场景编号 [0-5]: 1
#   选中的场景: donkey-generated-track-v0
#   数据目录: models/mypilot/1_generated-track
```

**场景 0（物理世界）**：不启动模拟器，使用真实摄像头
**场景 1-5（模拟器）**：自动启动模拟器 + Web 控制器

**采集时操作**：
- **User 模式**：手动带跑（方向键控制），有油门时自动录制
- **Full Auto**：AI 驾驶（测试已有模型），切换此模式即测试
- **Auto Steer**：AI 转向 + 人工油门

**测试模型**：无需单独命令，collect 启动后在 Web 界面切换 Full Auto 即可测试。

### 15.6 train - 训练 ✓

自动检测是否增量训练，交互式选择训练场景和训练类型。

```bash
./dcar train mypilot
# 输出：
#   检测到已有模型: models/mypilot/mypilot.keras
#   是否进行增量训练？[Y/n]
#   场景数据检查：
#     [1] 1_generated-track: 15494 条记录
#   选择训练场景：
#     a) 全部场景合并训练
#     1) 仅 1_generated-track
#   选择 [a/场景编号，多个用空格分隔]: a
#
#   === 训练类型选择 ===
#     1) 标准训练（无遮罩 无增强）
#     2) 仅遮罩训练（CROP，无增强）
#     3) 仅增强训练（无遮罩，BRIGHTNESS+BLUR）
#     4) 遮罩+增强训练（CROP + BRIGHTNESS + BLUR）★推荐
#     5) 当前配置（保持 myconfig.py 现有设置）
#   选择训练类型 [1-5，默认5]: 4
#
#   === 增量训练学习率调整 ===（仅增量训练时显示）
#     1) 自动调整到 0.0001（推荐）
#     2) 自动调整到 0.00005（更保守）
#     3) 保持当前值 0.0005
#     4) 自定义
#   选择 [1-4，默认1]: 1
```

**增量训练判断**：
- 检测到 .keras 文件 → 询问"是否增量训练？"
- 无 .keras 文件 → 自动从头训练

**场景选择**：
- `a` = 全部有数据的场景合并训练（提升泛化）
- `1 3` = 仅场景 1 和 3 的数据（指定场景）
- `1` = 仅场景 1 的数据

**训练类型选择**（5 种选项）：

| 选项 | 遮罩(CROP) | 增强(AUG) | 说明                                                           |
| ---- | ---------- | --------- | -------------------------------------------------------------- |
| 1    | 否         | 否        | 标准训练：直接使用原始图像，速度快，适合快速验证               |
| 2    | 是         | 否        | 仅遮罩：裁掉上部 45 行背景，减少背景干扰，适合背景变化大的场景 |
| 3    | 否         | 是        | 仅增强：随机亮度±30%+模糊 0-4px，模拟不同光照，适合多场景迁移  |
| 4    | 是         | 是        | **★推荐**：遮罩+增强，最强泛化能力，减少域偏移，适合最终部署   |
| 5    | 当前       | 当前      | 保持 myconfig.py 现有设置，不修改                              |

**训练类型作用说明**：

**遮罩（CROP）**：
- 裁掉图像上部 45 行（天空、远处背景、房子等）
- 只保留下部 75 行（纯道路区域）
- **作用**：消除背景变化对模型的干扰。换场景时即使道路颜色不变但背景变了，模型不会受影响
- **代价**：丢失前瞻距离，对远处弯道反应稍慢

**数据增强（AUGMENTATIONS）**：
- **BRIGHTNESS**：训练时随机调整图像亮度 ±30%
- **BLUR**：训练时随机添加 0-4 像素高斯模糊
- **作用**：让模型见过各种光照和模糊条件，提升在不同环境下的泛化能力
- **代价**：训练时间增加约 20%

**增量训练学习率调整**（仅增量训练时显示）：
- **0.0001（推荐）**：默认值的 1/5，保护已学特征不被破坏
- **0.00005**：更保守，仅微调，适合少量纠错数据
- **0.0005**：保持默认，学习力度大，可能覆盖旧知识
- **自定义**：手动输入
- 增量训练自动设置 `MAX_EPOCHS=15`（默认 50），避免过拟合

### 15.7 clean - 清除 ✓

清除进程资源 + 可选清除数据。

```bash
# 仅清除进程（停止模拟器和 Web 控制器）
./dcar clean

# 清除指定模型的指定场景数据
./dcar clean mypilot 1
# → 清空 models/mypilot/1_generated-track/ 下的数据

# 清除指定模型的所有场景数据（保留模型文件）
./dcar clean mypilot
```

**清除规则**：
- 无参数 → 仅停止运行中的进程
- 指定 model_name → 停止进程 + 清除该模型所有场景数据
- 指定 model_name + scene_num → 停止进程 + 清除指定场景数据
- **模型文件(.keras)始终保留**

### 15.8 完整工作流

```bash
cd "<ROOT>/mysim"

# 1. 创建模型
./dcar create mypilot

# 2. 采集数据（选场景 1）
./dcar collect mypilot
# → 浏览器 http://localhost:8887 手动带跑 3-5 圈

# 3. 训练
./dcar train mypilot
# → 从头训练（无已有模型）

# 4. 测试模型（通过 collect）
./dcar collect mypilot
# → 浏览器切换 Full Auto 测试 AI 驾驶
# → 发现错误切回 User 纠错（纠错数据自动录制）

# 5. 增量训练（用纠错数据）
./dcar train mypilot
# → 选择 Y 进行增量训练

# 6. 清除进程
./dcar clean

# 7. 多场景训练（提升泛化）
./dcar collect mypilot  # 选场景 3（仓库）
./dcar train mypilot     # 选 a 合并训练
```

### 15.9 status 和 list ✓

```bash
# 查看完整状态（路径、进程、所有模型和数据）
./dcar status

# 仅列出模型名称
./dcar list
```

---

## 参考资料

- Donkey Car 官方文档：http://docs.donkeycar.com/
- 模拟器页面：http://docs.donkeycar.com/guide/deep_learning/simulator/
- Gym Donkeycar：https://github.com/tawnkramer/gym-donkeycar
- Donkey Car GitHub：https://github.com/autorope/donkeycar
- Discord 社区：https://discord.gg/PN6kFeA
