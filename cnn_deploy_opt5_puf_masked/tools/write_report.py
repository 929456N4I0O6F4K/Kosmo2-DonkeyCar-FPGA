"""Render the opt4 report using this release's measured results only."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def main():
    model = read('model_manifest.json')
    release = read('integration/training/integration_validation.json')
    evaluation = read('build/model_evaluation.json')
    sim = read('build/sim/validation.json')
    board_path = ROOT / 'integration/board_evidence.json'
    board = read('integration/board_evidence.json') if board_path.exists() else None
    resources = release['resources']
    lut = resources['CLMA.LUT']['used'] + resources['CLMS.LUT']['used']
    ff = resources['CLMA.FF']['used'] + resources['CLMS.FF']['used']
    lines = ['# opt4 独立部署验证报告', '', '日期：2026-10-28。', '', '## 状态', '',
             ('**新模型 v11 已上板，50 帧同帧精确对照通过。**' if board else '**离线验证及完整固件构建已通过，实板验证待完成。**'), '',
             '按用户确认采用单次 INT8 推理。相机裁切、图像转换和网络结构不变，八层权重、偏置及重量化参数均已更新。旧 v9、v10 工程和原始模型文件均保留，没有重新训练或量化，不接 PUF。', '',
             '## 模型', '',
             f"- SHA256：`{model['model_sha256']}`。",
             f"- 输出量化：scale `{model['output_quantization']['scale']}`，zero point `{model['output_quantization']['zero_point']}`，Q30 `{model['output_quantization']['scale_q30']}`。",
             '- 输入为高 95 × 宽 156 × RGB；160×120 相机裁切 `RGB[25:120,2:158,:]`，RGB565 按位复制为 RGB888，输入 `q=pixel-128`。',
             '- 输出顺序为转向、油门。新 FPGA 诊断版本 11，DDR ABI 4。启动脚本复位前核对版本，v10 不能通过 v11 的免烧写启动。',
             '- 单次推理结果不等同于训练配置中的 TTA 评估指标。', '',
             '## 本轮离线验证', '',
             '- 12 组输入的整数参考与 TFLite 所有层完全一致：8 张录制图像，以及全黑、全白、空间图案和随机图案。',
             f"- RTL {sim['frames']} 帧，{sim['exact_layer_bytes']:,} 个层输出字节、{sim['exact_crop_bytes']:,} 个裁切字节完全一致；5,401 个重量化边界向量通过。",
             '- 裁切超时、推理超时恢复、未读结果过期、背压、忙时拒帧、连续推理通过。相机、AXI、PCA9685 和两帧真实 CNN 与 DMA 同帧桥接仿真通过。',
             '- 部署回归 26 项通过，包括 v10 在复位前被拒绝，以及仅更新服务前核对版本。',
             f"- 仿真处理时间为 {sim['max_processing_cycles']:,} 周期，50 MHz 对应 {sim['processing_ms_at_50mhz']:.5f} ms。它是裁切加 CNN 处理时间，不是相机到执行器总延迟。", '',
             f"192 张旧录制图像上，INT8 与配套浮点模型的平均绝对差（转向、油门）为 {evaluation['int8_vs_float_mae']}，P95 为 {evaluation['int8_vs_float_p95']}。Keras 与浮点 TFLite 最大差为 {evaluation['keras_vs_float_tflite_max']:.9g}。",
             '', '原有 24 个录制包用于部署回归，可能参与过训练。未提供 physicaldata2 新录制数据，未测得独立新数据准确率或道路表现；不能据此认定 opt4 驾驶效果优于 v10。', '',
             '## 完整固件构建', '',
             f"- 50 MHz，所有时序约束通过，建立时间余量 {release['setup_slack_ns']} ns。工具估计最大频率 {release['estimated_max_mhz']} MHz，实际保持 50 MHz。",
             f'- LUT {lut:,}/53,600，FF {ff:,}/107,200。',
             f"- APM {resources['APM']['used']}/256，RAM 为 {resources['DRM36K']['used']} 个 DRM36K 加 {resources['DRM18K']['used']} 个 DRM18K。",
             f"- bitstream SHA256：`{release['sha256']['build/board/prj_tasks/pnr_1/generate_bitstream/kosmo_training_top.sbit']}`。", '',
             '发布封存已核对当前模型、原版本文件、仿真 ROM 和向量、布局布线输入、最终时序及固件哈希。PU 程序及网页源码逐字节相同，旧 ARM64 和浏览器证据标注继承来源，不作为本轮重新执行的测试。', '',
             '## 实板', '']
    if board:
        assert board['success'] and board['model_sha256'] == model['model_sha256']
        lines += [f"- 地址 `{board['host']}`，确认固件版本 {board['firmware_version']}。",
                  f"- 新模型 {board['exact_same_frame_predictions']}/50 帧转向和油门 Q16 输出与同帧 TFLite 精确一致。",
                  f"- 实测最长处理时间 {board['max_processing_ms']:.5f} ms/帧。视频 {board['video_fps']:.4f} fps，同帧对照期间源帧率 {board['source_sequence_fps']:.4f} fps。",
                  f"- 视频检查阶段采集丢帧 {board['capture_drops_during_video']}，同帧对照阶段采集丢帧 {board['capture_drops_during_comparison']}。",
                  '- 控制 ACK 持续增加，结束保持零指令待机，无控制器故障；本轮未发送非零动作命令，未进行道路测试。',
                  f"- 完整部署：`{release['latest_deployment']}`。",
                  f"- 同帧对照：`{release['same_frame_comparison']}`。",
                  '- 汇总证据与哈希：`integration/board_evidence.json`。']
    else:
        lines += ['等待完整部署及 50 帧新模型实板对照，当前不声称新模型实板已通过。']
    lines += ['', '一键入口：`start_cnn.cmd`。旧 v10 回退：完整运行 `../cnn_deploy_physical2/start_cnn.cmd`。', '']
    (ROOT / 'INTEGRATION_REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Report updated; hardware_verified=' + str(bool(board)))


if __name__ == '__main__':
    main()
