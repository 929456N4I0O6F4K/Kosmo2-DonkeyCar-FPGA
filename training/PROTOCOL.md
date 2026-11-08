# KTR1 PA/PU 接口 v3

这一 ABI 由集成固件提供，旧独立台架固件不兼容。PA DMA 和控制逻辑使用 50 MHz 系统时钟；PU CPU 使用自身时钟，摄像头 PCLK 独立，状态经同步器跨域。

2026-10-25 集成固件诊断版本为 8，DDR ABI 为 3，新增独立曝光配置邮箱。驾驶命令、转向标定及帧布局保持 ABI 2 格式；前进映射仍为 `380 + round(61 × throttle)`，最高 441 ticks（约 1800 µs）。新版录制修复程序兼容 ABI 2/3，旧 ABI 2 上禁用曝光设置；旧版采集程序不能运行于 ABI 3。曝光功能升级须完整部署。独立执行器台架使用另一套接口，不能按版本数字混用。运行与部署见 [INTEGRATION](INTEGRATION.md)。

## 板级连接

顶层实例化 `rtl/kosmo_training_core.v`，同时加入 `kosmo_training_camera.v`、`kosmo_training_transport.v` 和 `../camera/rtl/{camera_capture,camera_config,camera_sccb,camera_exposure,ov2640_init_rom}.v`。保留现有 160×120 RGB565 初始化及相机针脚约束。SCCB 默认沿用实测的 10 kHz。

`m_*` 是独立读写地址/数据握手的 **32 位 AXI 单拍主机**。板级 `axi32_sps64` 把它转换成 SPS2 原生 64 位传输：AWLEN/ARLEN=0，AWSIZE/ARSIZE=3，AWBURST/ARBURST=INCR，WLAST=1，ID=0。SPS2 地址向下对齐 8 字节，原地址 bit2 选择读取字及四个写入字节使能；另一半字不会被改写。写地址握手后才允许数据握手，每次仅一个未完成事务。硬核连接使用供应商 `system_process_unit` 的 SPS2 端口。DDR_BASE 为 `0x00300000`，匹配 PU 的预留 UIO 区域。

`control_valid` 一直保持至 `control_ack`。序号、flags、angle、throttle、steering 端点在此期间稳定；ACK 表示完整命令已被控制核心接受。ACK 后该命令才能返回 PU 成功状态。未应答超过 50 ms 返回拒绝，PU 会锁定故障。`applied_*` 返回最后实际接受的有效设定值，由相机适配器在帧开始事件到达系统时钟域时锁存；不能把待发送的命令直接回接成已接受结果。

控制单位为有符号百万分之一：angle `-1000000..1000000`，throttle `0..1000000`；flags bit0=控制启用、bit1=录制。禁止 bit1 单独置位及其他位。未启用时控制核心须回中/停止；数值到 PWM 的非对称映射由最终标定后的控制核心负责。`control_stop` 必须优先于普通命令，处理看门狗、DDR 失败、相机配置失败和采集超时。核心应在 stop 时更新有效 flags，录制端也会屏蔽 stop 期间的录制标志。

## DDR 布局

UIO map0 基址 `0x00300000`，现有预留大小 64 MiB。当前应用只映射前 64 KiB。全部元数据是对齐的 32 位小端字。RGB565 的**单个像素高字节在先**；四个传感器字节依次放入 AXI 数据的 bit7:0、15:8、23:16、31:24。

| 偏移 | 写入方 | 字段 |
| --- | --- | --- |
| 0x00 | PA | magic=`0x3152544b`，内存字节 KTR1 |
| 0x04 | PA | ABI 版本=3 |
| 0x10 | PU | 命令发布序号；0 表示更新中，正常从 1 开始 |
| 0x14 | PU | flags |
| 0x18 | PU | int32 转向 |
| 0x1c | PU | int32 油门 |
| 0x20 | PU | watchdog_ms，固定 300 |
| 0x24 | PA | 命令完成序号 |
| 0x28 | PA | 完成状态：1 已接受，2 拒绝；其余未就绪 |
| 0x2c | PU | 已复制完成的帧序号 |
| 0x30 | PA | 已发布的完整帧序号 |
| 0x34 | PA | 控制状态：bit0 ready、bit1 fault、bit2 active、bit3 armed、bit4 shutdown_unconfirmed、bit5 stop |
| 0x38 | PU | bit11:0 左端点 462～529；bit27:16 右端点 333～396；其他位必须为 0 |
| 0x40 | PA | 槽内帧序号，必须等于 0x30 |
| 0x44 | PA | 图像长度，固定 38400 |
| 0x48/0x4c | PA | 帧开始系统计时，uint64 的低/高 32 位，50 MHz ticks |
| 0x50 | PA | 帧对应的已接受控制序号 |
| 0x54/0x58 | PA | 帧对应的 int32 转向/油门 |
| 0x5c | PA | 帧对应的有效 flags |
| 0x60 | PA | 被采集器判坏并丢弃的帧数；不包含未请求的传感器帧 |
| 0x80 | PU | 曝光请求序号，0 表示更新中 |
| 0x84 | PU | bit31 自动模式，bit10:0 曝光参数 0～1200，其他位为 0 |
| 0x88 | PA | 曝光完成序号 |
| 0x8c | PA | 曝光状态：0 未确认，1 写入及回读通过，2 参数错误或不允许，3 SCCB 失败 |
| 0x90 | PA | 最后成功曝光配置，格式同 0x84；初始化为 0，须结合成功回执判断 |
| 0x1000 | PA | 38400 字节 RGB565，逐行 160×120 |

PA 初始化先清除头部，最后写 magic；PU 在 magic/version 验证通过前不发布命令。PA 重新配置/重启时应停止 PU 采集程序，复核接口后重新运行。PA 停钟/复位后的独立执行器停机机制由控制系统负责。

## 命令原子性与失联

ABI 3 曝光请求使用独立邮箱：PU 先将 0x80 置零，再写 0x84，最后发布新序号；PA 两次读取序号一致才接受。完成时先写状态及实际配置，再写完成序号。PU 同时核对序号、成功状态及应用值，旧成功回执不能确认新请求。

仅在相机就绪、无故障、已应用 flags=0 且驾驶命令禁用时接受曝光请求。SCCB 事务异步执行，传输器继续处理零值心跳和视频；待完成期间拒绝使能驾驶的命令。应用层要求停车、未录制且视频正常，并在回执后等待三帧再恢复驾驶或录制。相机整体事务限时约 333 ms，单次 SCCB 保留原有超时保护。失败不更新最后成功值，并触发相机故障停机。单位、增益行为及持久化见 [EXPOSURE](EXPOSURE.md)。

PU 单线程发布命令：先把 0x10 置 0，使旧命令失效，再写 flags/angle/throttle/TTL/steering，最后写新的非零序号。PA 先读序号，读取 payload，再次读序号；两次一致且非零才接受。这样在 ACK 超时后重发停止也不会拼接新旧字段。一个 PU 进程独占 UIO；ACK 顺序为先状态、再序号。

浏览器带递增序号，同一当前输入来源的乱序/重复请求被拒绝；不再限制页面驾驶权，最新有效输入（包括其他页面发来的停止）生效。PU 每 50 ms 发送一次有效控制或中位待机命令。浏览器输入超时 300 ms、相机帧龄超过 500 ms 时停止；PA 在最后一次成功控制 ACK 后计时，300 ms 无新接受命令则 `control_stop=1`。单拍 AXI 超时或错误响应也锁定 stop，避免等待总线时丢掉停止计时。

浏览器每次从停止状态开始新的实际操作时增加 `gesture`，随后保持的键盘设定值或同一次摇杆操作共用该值。超时后的旧 gesture 不能再次启用；须重新操作，持续按住的键盘重复事件不会恢复旧油门。`sequence` 仍逐条递增。

空闲页面不周期发送控制请求。普通禁用命令建立或维持中位 PWM，完成首次初始化后保留 `armed`，普通启停不重复等待。`active=true` 表示 PWM 仍输出，允许与 `enabled=false`/帧 flags=0 同时出现。独立 `control_stop` 仍回中后关闭输出；只有关闭读回确认后才清除 `active`/`shutdown_unconfirmed`。操作约定见 [CONTROLS.md](CONTROLS.md)。

从诊断版本 4 起，健康中位待机须读回 MODE1、MODE2、PRE_SCALE 以及 ESC/舵机 ON/OFF 寄存器后才确认心跳；驾驶更新也读回模式和频率，v6 保留该行为。PCA 地址无应答或读回不符会锁定 fault，取消 armed 并重试全关闭，此异常路径不能保证先完成回中。`armed` 不表示电调回传了解锁状态。

## 帧所有权与标签

PA 只在 `published == consumed` 时写槽。先写全部图像，再写描述符，等待所有 AXI 写应答后才写 published。槽未释放时可以继续处理命令，但不覆盖图像。PU 通过 acquire 读取 published、描述符和像素，确认发布序号未改变后 release 写 consumed。UIO 必须是设备/不可缓存映射；软件原子操作不能代替实际硬核与缓存属性的实板验证。

相机 RAM 从完成捕获到 DMA 发布后保持冻结；`frame_release` 后才重新请求。帧开始由 `camera_capture.capture_active` 上升沿表示，通过三拍同步进入系统域后，同时锁存时间与 `applied_*`，存在几拍系统时钟的同步延迟。后续驾驶指令变化不会改写该帧标签。

不以网络包到达顺序匹配标签，不重复录制上一帧，不向模型输入 JPEG 预览数据。捕获超时为 1 秒；坏尺寸帧丢弃并计数。单槽方案会跳过无法请求的传感器帧，需以实际保存帧率和帧间隔评估采集质量。

## HTTP 接口

网页与 API 由同一端口直接提供，无令牌、登录接口或 Cookie 认证；改变状态的跨源请求仍被拒绝。正文上限 4096 字节。

| 请求 | 行为 |
| --- | --- |
| GET `/api/status` | 模式、帧元数据、帧龄、ACK、录制计数、左右转向设置与故障 |
| GET `/video.mjpg` | MJPEG；每帧含 Content-Length 和 X-Frame-Sequence |
| POST `/api/drive` | `{"client":"浏览器唯一ID","sequence":1,"gesture":1,"enable":true,"angle":0,"throttle":0.1}` |
| POST `/api/record` | `{"recording":true}` 新建会话；false 关闭会话 |
| POST `/api/steering` | `{"left_percent":110,"right_percent":110}`；各为 50～150 的整数，仅停车且未录制时保存 |
| GET `/api/download` | 最近一个已结束会话的 ZIP，正在录制时拒绝 |

视频、命令及 SD 录制使用独立执行路径；慢视频客户端有写超时，不能让预览积压成为控制队列。HTTP 发送成功不代表执行器成功，真实接受状态要看控制 ACK 及帧内对应序号。

新会话的 `session.json.steering` 保存录制时的左右幅度、端点及中位 ticks；录制期间禁止改变幅度。同一归一化标签在不同幅度下对应不同 PWM，后续使用数据时应保留并核对会话参数。
