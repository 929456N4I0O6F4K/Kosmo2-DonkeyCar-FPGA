# Kosmo2 DonkeyCar — FPGA 加速的自动驾驶小车 + 硬件指纹模型保护

在 **Kosmo2 / PG2K100** 开发板上，用 FPGA 打通
**OV2640 摄像头 → 硬件 CNN 推理 → PCA9685 舵机/电调** 的完整链路，
并用 **PUF（物理不可克隆函数）** 把量化后的模型权重绑定到具体芯片上，
让模型"离开这块板子就跑不起来"。

浏览器直接当驾驶界面：视频预览、比例摇杆 / 键盘驾驶、参数保存、数据录制与下载，
全部由板上 ARM64 侧的一个 Go 程序通过网络提供。

本仓库是**最终交付版本**：加速器为 `cnn_deploy_opt5_puf_masked/`（固件 v11），
模型为 `mypilot1_s2_physical2_opt5/` 中的 INT8 量化模型及其导出源。

---

## 一、这是什么

| 组成 | 路径 | 说明 |
| --- | --- | --- |
| 加速器 | `cnn_deploy_opt5_puf_masked/` | release `camera-cnn-drive-opt5-puf-masked-v11`，`firmware_version: 11`，单次推理 |
| 权重 ROM | `cnn_deploy_opt5_puf_masked/rtl/generated/stage*_weights.mem` | 16 个 `.mem`，RTL 用 `$readmemh` 直接读，**综合只依赖这些文件** |
| INT8 模型 | `mypilot1_s2_physical2_opt5/mypilot1_s2_physical_int8.tflite` | 231 KB，量化后的推理模型 |
| 浮点模型 | `mypilot1_s2_physical2_opt5/mypilot1_s2_physical.tflite` | 数值对照用 |
| Keras 源模型 | `mypilot1_s2_physical2_opt5/mypilot1_s2_physical_best.keras` | 权重导出的来源 |
| 量化参数 | `mypilot1_s2_physical2_opt5/quantization_params.json` | 输入/输出 scale 与 zero point |
| 训练超参 | `mypilot1_s2_physical2_opt5/train_config.json` | 两轮 trial 选优，选中 trial 2 |

网络结构：Conv 24/32/64/64/16 + Dense 100/50 + Dense2 线性输出（转向 Q16.16、油门）。
输入为 160×120 RGB565 冻结帧裁到 `RGB[25:120, 2:158, :]`、按位复制扩展到 RGB888、
逐通道 `q = pixel - 128` 得到的 95×156×3 INT8 张量。

> **模型文件里没有 PUF 编码，这是正常的。**
> `cnn_deploy_opt5_puf_masked/model_manifest.json` 中的 `"puf": false` 表示
> `mypilot1_s2_physical_int8.tflite` 这个模型文件本身未掺入 PUF 编码，**并不表示本项目未接 PUF**。
> PUF 作用于 dense1 / dense2 的权重 ROM：`encode_puf_dense_weights.py` 按板 A 的 enrollment
> 响应与稳定位掩码对 `stage5_weights.mem` / `stage6_weights.mem` 做符号取反，生成 `puf_key.mem`
> 后由 `puf_key_store.v` 在运行时读出。编码记录写在 `build/board/puf_obfuscation_manifest.json`，
> 该目录被 `.gitignore` 排除，因此未随包提供。

---

## 二、怎么构建

工具链：**Pango PDS 2025.2** + **Go 1.23** + **Python 3**（`pyserial==3.5`、`paramiko==5.0.0`，见 [requirements-host.txt](requirements-host.txt)）。

### 1. 先出比特流（仓库不含）

`.gitignore` 排除了 `*.sbit`，仓库中没有任何比特流，**第一次使用必须自己综合**：

```powershell
# 方式一：PDS GUI —— 打开工程，执行 Generate Bitstream
#   training\build_board.pds
# 方式二：命令行 —— 在工程目录下执行
#   training\impl.tcl      （流程结尾含 gen_bit_stream）
```

产物：`training/build/board/prj_tasks/pnr_1/generate_bitstream/kosmo_training_top.sbit`

> 工程通过相对路径引用 PDS 安装目录下的 DVIO IP（`.../pango/PDS_2025.2-ads/ip/...`），
> 换机器后需在 PDS 中确认 IP 路径有效。

### 2. 再编板端 Go 程序

```powershell
.\training\build.ps1
```

执行 `go test` / `go vet`，产物为 `training/bin/kosmo-collect.exe`（Windows）与 linux/arm64 版本。

### 3. 最后部署到车

```powershell
.\deploy_car.cmd        # 状态检查 → 固件加载 → 采集服务 → 100 帧视频验证
```

服务起来后浏览器打开 `http://192.168.43.124:8080/`，无需令牌。
只重启已有固件上的采集服务：`.\training\start_board.ps1 -NoProgram`。

### 4. CNN 模型驾驶

```powershell
cd cnn_deploy_opt5_puf_masked
.\start_cnn.ps1 -CheckOnly -NoBrowser   # 本地发布文件自检
.\start_cnn.ps1                          # 固件 → 相机 → CNN → 控制器
```

模型驾驶需要按住按键，松开即停。内部调用 `training/tools/deploy_board.py`。

### 5. 资源与时序评估（可选，不产比特流）

```powershell
# cnn_deploy_opt5_puf_masked\synthesis\build.tcl
# 只跑到 report_timing，用于看 LUT/BRAM/时序，不生成 .sbit
```

### 6. PUF 响应采集与权重编码

```powershell
# 板上采集：先烧入采集映像，再用脚本读回响应
python ro_puf\tools\capture.py --board A --session <会话名>

# 响应 → 生产用 key ROM（符号取反写入 dense1/dense2 的权重复本）
python cnn_deploy_opt5_puf_masked\tools\encode_puf_dense_weights.py `
       --capture <板A采集.json> --enrollment-key <puf_key.mem> --enrollment-key-json <key_meta.json> `
       --output-key <输出 puf_key.mem>
```

RO 阵列原语在 `ro_puf/rtl/`（`ro_cell` / `ro_bank` / `ro_counter`），
其位置约束 `ro_locations.fdc` 在 `ro_puf/constraints/`，集成构建时会拷入
`integration/training/board/`。

### 7. CNN + PUF 集成映像（报告的主映像）

板级 `training/` 只含相机 + 车控；把 CNN 与 PUF 接进同一映像的顶层在
`cnn_deploy_opt5_puf_masked/integration/` 下（`training/board/kosmo_training_top.v`、
`training/rtl/kosmo_cnn_bridge.v`，以及 RO 布局约束）。构建分三步：

```powershell
# ① 用板 A 的采集结果写出生产用 key ROM（模式字 1d0e0）
python cnn_deploy_opt5_puf_masked\tools\configure_puf_reference.py `
       --capture-json <板A采集.json>

# ② 调 PDS 综合（脚本内部用 pds_shell，要求 PDS 装在 C:/pango/PDS_2025.2-ads）
python cnn_deploy_opt5_puf_masked\tools\build_integration.py

# ③ 三条判据核验：路由网表、SDF、BRAM 初值
python cnn_deploy_opt5_puf_masked\tools\compare_implementations.py <capture映像> <production映像> --output <结果.json>
```

`build_integration.py` 会对 `rtl/`、`integration/{training/rtl,training/board,training/scripts,camera/rtl,actuators/rtl}`
做哈希校验，构建后若源文件被改动会直接报错。

### 8. PC 端训练与量化（可选）

```powershell
pip install -r training/requirements-train.txt
pip install donkeycar gym-donkeycar        # 训练流程的第三方依赖
cd training_data/mysim
python manage.py --help
```

`training_data/mysim/scripts/` 保留采集、训练、量化、评估脚本；训练报告见
[training_data/mysim/training_reports/final_report.md](training_data/mysim/training_reports/final_report.md)。

---

## 三、目录索引

| 目录 / 文件 | 是什么 | 入口 |
| --- | --- | --- |
| `training/` | 板端主工程：Go 服务 + RTL + 板级约束 + 驾驶网页 | `build.ps1`、`start_board.ps1`、`build_board.pds` |
| `camera/` | OV2640 工程：SCCB、初始化 ROM、曝光、JTAG 桥 | `camera.pds` + `constraints/camera.fdc` |
| `actuators/` | PCA9685 舵机/电调台架 | `pca_bench.pds` + `constraints/pca_bench.fdc` |
| `cnn_deploy_opt5_puf_masked/` | 最终 CNN 加速器（v11，opt5 + PUF 掩码），`integration/` 为 CNN+PUF 集成映像的顶层与 RO 布局约束 | `start_cnn.ps1`、`synthesis/build.tcl`、`integration/scripts/build_board.tcl` |
| `mypilot1_s2_physical2_opt5/` | 最终模型：INT8 / 浮点 / Keras 源 + 量化与训练配置 | — |
| `ro_puf/` | RO-PUF 阵列本体：`ro_bank.v`、`ro_cell.v`、`ro_counter.v` 与 `ro_locations.fdc` 位置约束（**opt5 综合的编译依赖**） | `constraints/ro_locations.fdc` |
| `training_data/` | PC 训练脚本与训练报告（第三方依赖、历代模型、厂商开发包未随包） | `mysim/scripts/` |
| `tools/` | 板卡连接、SSH、串口工具 | — |
| `docs/` `引脚信息.md` | 接线 | — |
| `deploy_car.cmd` | 一键部署入口 | ✅ |

文档：[training/PROTOCOL.md](training/PROTOCOL.md)（PA/PU DDR 与 HTTP 接口）、
[training/DEPLOY.md](training/DEPLOY.md)（编译、烧录、启动、恢复）、
[docs/camera_wiring.md](docs/camera_wiring.md) 与 [引脚信息.md](引脚信息.md)（接线）。

---

## 许可证

本项目自身代码采用 **MIT License**，见 [LICENSE](LICENSE)。
`camera/vendor/` 下的第三方 OV2640 代码（esp32-camera Apache-2.0、OpenMV MIT）
保留原许可证，见 [camera/vendor/NOTICE.md](camera/vendor/NOTICE.md)。
