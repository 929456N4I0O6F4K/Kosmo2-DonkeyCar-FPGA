# training_data — PC 端训练工作区

这个目录是原项目 `car.zip` 解压整理后的**训练部分**，原样保留了 DonkeyCar 生态的代码、
配置、脚本和选定的模型权重，但**去掉了数据集、Unity 仿真器和中间产物**（体积原因，见下）。

`USAGE_GUIDE.md` 是这个工作区的完整使用手册（环境激活、模拟器、采集、训练、切换赛道、排错）。
手册里用 `<ROOT>` 表示本目录，替换成实际路径即可。

## 目录

```
training_data/
├── USAGE_GUIDE.md          # 完整使用手册（先看这个）
├── donkeycar/              # DonkeyCar 框架（含本地修改，MIT）
├── gym-donkeycar/          # DonkeyCar 的 Gym 环境封装（MIT）
├── mysim/                  # 本项目自己的驾驶/训练工程
│   ├── manage.py           # 驾驶入口（浏览器驾驶 + 录制）
│   ├── config.py           # DonkeyCar 基础配置
│   ├── myconfig.py         # 用户配置：DATA_PATH / MODELS_PATH / 赛道 / 增强 / 裁剪
│   ├── custom_crop.py      # 自定义 ROI 裁剪
│   ├── paths.py            # 路径解析
│   ├── scripts/            # 采集、训练、量化、评估、报告、可视化脚本
│   ├── models/             # 选定模型（见下）
│   └── reports/            # 角度/镜像对比的评估报告（HTML + CSV）
├── fpga_dev_kit/           # FPGA 部署开发包：模型、逐层权重 npy、样例图、样例推理、架构
└── official_models/        # DonkeyCar 官方预训练模型（迁移学习起点）
```

### 保留的模型

只保留了和板端部署链路相关的版本，避免仓库塞满实验过程产物：

| 目录 | 说明 |
| --- | --- |
| `mysim/models/mypilot1/` | 基础 PilotNet 系列（`.keras` / `.tflite`） |
| `mysim/models/mypilot1_s2_physical2/` | 对应板端 v10 |
| `mysim/models/mypilot1_s2_physical2_opt4/` | 对应板端 v11 |
| `mysim/models/mypilot1_s2_physical2_opt5/` | opt5 + PUF 掩码候选的源模型 |
| `official_models/2_circuit_launch_pilots/` | 官方预训练模型（迁移学习用） |
| `fpga_dev_kit/1_model_files/` | 最早用于 FPGA 的 mypilot 模型 |

根目录下的 `model/` 和 `mypilot1_s2_physical2_opt4|opt5/` 是同一批模型在**板端工程侧**的副本，
因为 `cnn_deploy*` 的脚本会按相对路径 `../model/...` 取模型。

## 被移除的内容

| 内容 | 原体积 | 为什么移除 | 怎么恢复 |
| --- | --- | --- | --- |
| `mysim/datasets/sim/` | 284 MB | 训练数据集，属于采集产物 | 用 `mysim/scripts/collect/` 重新采集，或从 [autorope/donkey_datasets](https://github.com/autorope/donkey_datasets) 下载 |
| `DonkeySimLinux/` | 667 MB | Unity 仿真器二进制 | 从 DonkeyCar 官方 Simulator 页面下载对应版本（v22.11.06） |
| `mysim/artifacts/hls4ml_out/` | 59 MB | HLS4ML 生成的 RTL，可由脚本重新生成 | `mysim/scripts/quantize/hls4ml_scan.py` |
| `mysim/models/logs/` | 5 MB | TensorBoard 训练曲线 | 重新训练即可生成 |
| `__pycache__/`、`*.pyc` | — | 字节码 | — |

## 环境

手册记录的原环境：

- Python 3.12（conda 环境名 `donkey`）
- TensorFlow 2.21（CPU 可训练；GPU 需额外配置 cuDNN）
- 数据格式：Donkey Tub v2（图像 + 转向 + 油门 + 速度）
- `donkeycar` 使用仓库内的本地副本（`mysim/` 的配置会 import 它）

```bash
source $HOME/.miniforge3/etc/profile.d/conda.sh
conda activate donkey
cd training_data/mysim
python -c "import tensorflow as tf, donkeycar; print(tf.__version__, 'ok')"
```

## 训练链路（对应板端部署）

```
采集（模拟器 / 实车）
    → donkey train（PilotNet，CROP + AUG）
    → mypilot_*.keras
    → scripts/train/train_s2_physical*.py（结构改造）
    → scripts/quantize/quantize_s2_int8.py（INT8 量化）
    → *_int8.tflite
    → cnn_deploy*/（导出逐层权重 .mem → RTL 仿真 → 板上数值对照）
```

量化后的 INT8 模型用 `fpga_dev_kit/` 里的逐层权重与样例推理做逐层核对：

| 文件 | 用途 |
| --- | --- |
| `fpga_dev_kit/2_weights_npy/` | 每层 weight/bias，`layerNN_*.npy` |
| `fpga_dev_kit/3_sample_images/` | 21 张真实采集样例（标注好帧号） |
| `fpga_dev_kit/4_sample_inference/` | `sample_inputs.npy` / `sample_outputs.npy` / 期望结果 |
| `fpga_dev_kit/5_architecture/` | 网络结构 JSON 与 summary |
| `fpga_dev_kit/6_config/config.json` | 量化 scale / zero point 等部署参数 |

## 说明

- `donkeycar/` 和 `gym-donkeycar/` 是上游仓库的本地副本，为减小体积**去掉了 `.git` 目录**。
  对应上游分别是 [autorope/donkeycar](https://github.com/autorope/donkeycar) 和
  [tawnkramer/gym-donkeycar](https://github.com/tawnkramer/gym-donkeycar)，各自保留原 MIT 许可证。
- 本目录的脚本与配置里仍有部分绝对路径/占位符（`<ROOT>`、`/home/...`），
  迁移到新机器时需要按 `myconfig.py` 的 `DATA_PATH`、`MODELS_PATH`、`OFFICIAL_MODELS_PATH` 改一遍。
- `mysim/` 是模拟器训练链路；实车链路是根目录 `training/`（板端）与 `training/exports/`（真实采集样例）。
