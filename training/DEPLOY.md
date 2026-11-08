# 一键部署小车系统

**录制卡顿修复：**已初始化的 ABI 2/3 板卡在健康中位、已结束录制时，可用 `deploy_car.cmd -SoftwareOnly` 仅通过 SSH 更新采集程序，不需要 JTAG。它不会初始化或恢复故障硬件；曝光功能仍要求完整升级到 ABI 3。详见[录制存储说明](RECORDING_IO.md)。

**2026-10-25：**当前部署包升级为 **v8 / ABI 3**，新增[自动／手动曝光](EXPOSURE.md)。默认网络地址已改为 `192.168.161.198`，使用 iQOO Neo8 Pro 热点。首次升级运行完整流程，不能使用 `-NoProgram`；后者现在只接受 ABI 3。部署保留板端 `exposure.json`，服务启动时恢复配置。当前验证状态见[验证清单](integration_validation.json)。以下 v7 地址及运行结果保留为历史记录，实际地址以脚本显示和 `board_connection.json` 为准。

本日实板已成功加载 v8、启动服务并完成板内曝光与录制验证；电脑侧连续视频验收因链路停顿中断，脚本正确保留失败结果，未显示 READY。虚拟机当前实际使用 NAT。服务仍在运行，切换到宿主机直连检查时无需再次加载固件；复测依据见[记录](runs/20261025-v8-board-validation/README.md)。

随后完成曝光配置的服务重启恢复测试，并单独通过 100 帧、约 7.22 fps 的无线复验。原一键运行日志仍保留当时的失败状态；后续复验单独记录，见[最终无线检查](runs/20261025-v8-final-wireless-check/verification.json)。

15:05 的最新页面修复包使用 `-SoftwareOnly` 一键更新成功，完整执行该模式的检查、停止、上传、启动及 100 帧验证并显示 READY，约 7.69 fps、采集端丢帧 0。该次未重置或重新加载 FPGA，见[最新部署记录](runs/20261025-150555-452217-deployment/summary.json)。

在项目根目录双击 **[deploy_car.cmd](../deploy_car.cmd)**。原来的 [start_board.cmd](start_board.cmd) 也调用同一套流程。

2026-10-14：默认改为直接通过板子的无线地址 **`192.168.43.124`** 部署，当前无线 SSH 已验证可用。SSH 上传、重启等待、控制检查和视频验证均使用同一个地址；不再依赖 Ubuntu 编译虚拟机或 PU 串口。JTAG USB 仍用于加载易失 FPGA 配置。

2026-10-14 当时部署集成 **v7**：修复转接板接线下的相机时钟驱动，见[相机恢复记录](../camera/docs/recovery_20261014.md)。用户更换排线后，19:51 的真实 CMD 首次运行因 JTAG 缺失停止；接回后，19:52 再次运行通过 **100 帧、约 7.52 fps** 无线视频复验，帧号连续、采集端丢帧计数保持 0，恢复 READY。当时服务保留零油门待机、驾驶禁用且未录制。详情及此前失败证据见[本次复测记录](runs/20261014-startup-retest.md)。驾驶控制沿用 v6 的[左右转向幅度设置](STEERING.md)，前进上限约 1800 µs。v5 的历史部署复验见 [记录](runs/20261010-throttle-v5-review.json)。

旧 H1→摄像头约 30 cm 排线条件下的 17:48 测试为 3.37 fps、采集端新增丢弃 122 帧。新排线长度、型号未知，不能记为相机直插 H1。更换后改善支持问题与原排线或连接有关，尚未单独确定线长、接触或电气根因，也不代表长期稳定性已验证。

## 运行前

- Kosmo 已上电，WD-1513B 插在 USB-A，已配置的热点（当前 iQOO Neo8 Pro）已开启；运行脚本的电脑可以访问板子的无线地址。
- JTAG USB 接入运行脚本的 Windows；若这个 Windows 在 VMware 内，将下载线分配给它。
- C20 复位拨码保持之前确认的运行侧，相机和 PCA 接线保持正常。
- 停止网页驾驶、结束录制；脚本发现正在驾驶或录制时会退出。

使用本机现有 Python、SSH 依赖及 `C:/pango/PDS_2025.2-ads`。脚本校验验证清单中的 ARM64 程序与当前集成位流的 SHA256；不在启动过程中自动重新编译或下载依赖。前进上限沿用 v5 的约 1800 µs，参数见 [CONTROLS](CONTROLS.md)。SSH 沿用经串口核验过的板端主机指纹，即使 IP 改变也不跳过核验；默认使用厂商密码，也支持已有的 `KOSMO_SSH_PASSWORD` 环境变量。

默认地址保存在 [board_connection.json](board_connection.json)。DHCP 地址改变后，修改其中的 `host`，下次双击即可使用新地址。地址优先级为命令行 `-BoardHost`、环境变量 `KOSMO_BOARD_HOST`、配置文件；只填 IPv4，不含 `http://` 或端口。

## 自动完成的步骤

1. 校验本地程序与位流，读取板端隔离状态。
2. 停止旧采集服务。若进程在运行但 HTTP 状态不可读，退出而不强行中断未知会话。已启用 PU/PA 时，通过 JTAG 确认 PWM 全部关闭，再重启 PU，等待无线重新连接、SSH 恢复和隔离确认。
3. 加载当前 PA 集成位流，开启 PU/PA 通路，复位并核验相机、PCA 和传输。
4. 上传采集程序，自动建立零油门中位待机。
5. 验证控制 ACK、连续 100 帧真实视频与最终零油门状态。

只有全部通过才显示 **`READY: http://192.168.43.124:8080/`**，指定其他地址时会相应变化。打开显示的地址即可操作，无需令牌。加载过程通常需要数分钟，JTAG 连接阶段有一段等待。

验收输出同时列出帧数、fps、`source_dropped` 增量和控制 ACK；检测到采集端丢帧时会提示 READY 仅确认现有启动与通信检查通过，不代表相机稳定性已通过。

如首次启动的零值命令 ACK 超时，会在再次确认输出关闭后自动重启、重载一次；其他故障直接给出错误与日志路径。每次部署最多执行这一次自动恢复，不发送非零转向或油门、不重放驾驶指令。已有采集数据保留；位流加载到易失配置，断电后需再次运行。

每次运行保存到 `training/runs/<时间>-deployment/`，包含各步骤 `command.log`、JTAG/网络 JSON 及最终 `summary.json`。重复双击时第二个部署进程会退出，防止同时操作板卡。

等待视频和中位待机时，脚本分别报告采集程序与硬件控制器的故障，保留原始原因。例如 `Collector reports a fault: camera: context deadline exceeded` 表示取帧超时，不等于 PCA 故障。失败时另存 `wait-ready-failure-status.json`，包含最后一次 HTTP 状态；若从未读到状态则为 `null`。

停止旧服务时核对 `/proc` 中的实际程序路径，不直接相信上次留下的 PID 文件；板卡重启后 PID 被其他进程复用，也不会因此误停其他程序或阻塞部署。

## 命令行选项

在 `training` 目录执行：

```powershell
./start_board.ps1                 # 默认：自动完整部署，验证 100 帧
./start_board.ps1 -NoProgram      # 停止、确认关闭、初始化并重新部署程序；不重启 PU 或重刷 PA
./start_board.ps1 -Frames 30      # 完整部署，验证 30 帧
./start_board.ps1 -CheckOnly      # 只检查本地文件和哈希，不访问板卡
./start_board.ps1 -SoftwareOnly   # 健康且空闲的 ABI 2/3：仅更新采集服务，无需 JTAG
./start_board.ps1 -BoardHost 192.168.43.124 # 本次指定无线 IP
./start_board.ps1 -BoardHost 192.168.137.10 # 有线接通时仍可指定原有线 IP
```

项目根目录也可运行 `deploy_car.cmd -BoardHost 192.168.43.124`。一次性参数不会改写配置文件。无线启动等待沿用所选地址；若热点在板子重启后分配了不同地址，脚本会超时退出，需要更新地址后重试，不会跳到另一块设备。

`-NoProgram` 要求已启用 KTR1 ABI 3 固件；旧 ABI 1/2 会明确要求完整升级。它也会核验输出已关闭并初始化，不能跳过 PCA 故障。改变固件需要完整部署，网页转向和曝光设置则直接保存生效，无需再次烧录。部署保留板端 `steering.json` 和 `exposure.json`。默认完整流程可用于首次上电和重复部署，无须手动区分是否应重启 PU。

## 常见中断

| 提示 | 处理 |
| --- | --- |
| SSH 超时 | 检查板卡电源、Longhorn 热点、USB 网卡和配置中的 IP；若使用有线则检查网线 |
| Collector is running but HTTP status is unreachable | 采集进程仍在，先恢复网络或检查服务状态，再运行；脚本不会强行打断未知会话 |
| Host key mismatch | 当前地址的 SSH 身份与已核验板子不一致，先核对 IP/设备，不要关闭指纹校验 |
| No cable was found | 将 JTAG USB 连接给当前 Windows/虚拟机 |
| Select dvio is not valid | 检查 C20 是否仍处于复位侧；保持运行侧后重试 |
| PWM shutdown is not confirmed | 检查 PCA 供电与接线，关闭未确认时脚本不会强制复位或重载 |
| Camera initialization failed | 检查 OV2640 供电、RST、SDA/SCL 接线；相机未就绪时不会启动真实采集服务，详见 [接线表](../docs/camera_wiring.md) |
| Collector reports a fault: camera: context deadline exceeded | 相机没有按时提供有效帧；检查保存的 HTTP 状态、采集日志与 JTAG，寄存器初始化通过并不保证 DVP 图像帧正常；修复后需重新启动采集服务 |
| Hardware controller reports a fault | 检查 controller 健康状态及 PCA/JTAG 诊断；与相机取帧超时分别处理 |
| Driving or recording is active | 网页停车并结束录制后再运行 |
| Artifact differs from the validated release | 文件与验证清单不一致，先完成构建审核和指纹更新 |
| Link is enabled with unknown firmware | 当前不是可确认状态的小车固件，先从板卡重启后的隔离状态开始 |

2026-10-10 实测 `-NoProgram` 重启时曾出现首条中位命令 ACK 超时；此时用默认完整部署恢复，不应反复直接启动采集进程。[失败记录](runs/20261010-204414-845946-deployment/summary.json)。该次根因尚未确定，`-NoProgram` 不作为本轮已通过的恢复路径。

完整恢复时还遇到后台服务启动较慢、固定等待 2 秒读到空日志而误报失败。已改为最多 15 秒轮询首条日志，真实启动错误仍直接报告；3 项离线测试通过。修复前那次服务随后正常启动，并独立通过 [100 帧检查](runs/20261010-v6-final-network/verification.json)，未把原失败的脚本 `summary.json` 改成成功。

详细网络、接线与诊断见 [INTEGRATION](INTEGRATION.md)；驾驶操作见 [CONTROLS](CONTROLS.md)。

## 2026-10-14 无线入口复验

19 项离线检查通过，覆盖所选 IP 在 SSH 检查、上传、重启等待和 HTTP 验证之间的一致性，以及已运行但状态不可读时拒绝中断会话。根目录 CMD → PowerShell → Python 的 `-CheckOnly -BoardHost 192.168.137.10` 参数透传通过，没有连接该有线地址；正常部署使用配置中的 `192.168.43.124`。

实板无线 SSH、主机指纹核验、FPGA 下载和停车后的无线重启/自连通过。第一次完整启动在相机初始化处停止，PCA 正常、PWM 已关闭，尚未到达 READY：[失败记录](runs/20261014-153004-563325-deployment/summary.json)。用户说明更换过相机连接线；专用相机诊断读到 ID `0x2642`，随后在配置表索引 4 出现 SCCB 地址字节 NACK，不能仅据此判断具体哪根线接错。接线核对待完成，当前不将这次运行记为完整部署成功。[脚本检查记录](runs/20261014-wireless-deploy-checks/review.json)。

## 2026-10-10 一键脚本实测（当时为 v4）

| 入口与场景 | 结果 |
| --- | --- |
| `start_board.ps1`，上电后完整部署 | 通过，连续 100 帧约 7.56 fps，ACK 123→387；[记录](runs/20261010-145206-062698-deployment/summary.json) |
| `start_board.ps1`，运行中停止服务、重启 PU、重新加载 | 通过，连续 100 帧约 7.58 fps，ACK 164→426；[记录](runs/20261010-145501-164823-deployment/summary.json) |
| 根目录 `deploy_car.cmd -CheckOnly` | CMD → PowerShell → Python 入口与退出码检查通过；[记录](runs/20261010-145902-050043-deployment/summary.json) |
| 离线部署回归 | 11 项通过，覆盖运行会话保护、关闭确认、冷/热启动、单次 ACK 恢复、文件校验与重复启动锁 |

两次实板部署结束时均无控制故障、转向/油门为零、`enabled=false`，没有开始录制。验证范围为视频、控制通信和中位待机；本次未测试非零机械动作。汇总见 [部署复验记录](runs/20261010-deployment-review.json)。
