"""本地标定 WP-1625：中位确认、短时油门、FPGA 自动回中和关闭。"""
import argparse
import datetime as dt
import json
from pathlib import Path

from pca_bench import ROOT, Debugger, PcaBench

HELP = """
本脚本固定控制电调通道 0，舵机通道 3 保持关闭。输入单位：微秒。
保持驱动轮架空。首次上电对照：Kosmo2/PCA9685 逻辑侧保持供电，仅关闭电调开关。
输入 neutral（使用提示符显示的中位值），看到“中位保持”后立即开启电调，尽量在第一秒内完成。
本次中位共 5 秒；手册要求电调开启后保持中位约 3 秒，开启太晚时不能据此判断解锁。

  neutral          测试当前中位值（见提示符），保持 5 秒后关闭
  neutral 1490     更换中位候选值并测试，允许 1400–1600 微秒
  ok               仅在刚才已解锁且电机静止时输入，确认中位观察结果
  +5 / -5 / 1510   小步测试油门：中位 5 秒 → 油门 0.5 秒 → 回中 1 秒 → 关闭
  hold 0.5        固定 60 Hz、中位 1550、油门 1655，先做半秒复核（需要 v6）
  hold 1 / 2 / 5  同一 1655 油门分别保持 1、2、5 秒；逐级测试，每次都回中并关闭
  start            记录上次测试值为起转点
  slow             记录上次测试值为可用低速点
  note 前进/未动    保存观察，包括实际旋转方向、过快、提示音等
  results          显示中位及已记录结果
  status / init    查看状态 / 故障排除后重新初始化（需要重新确认中位）
  off              关闭输出并撤销本次中位确认
  q                关闭输出、保存并退出；Ctrl+C 也可中断

首次上电观察：电调完成自检有一声长音，中位时红灯熄灭且电机静止，再输入 ok。
手册中的开机短音表示电池类型，不能单凭“有声音”确认解锁。
同一次上电已确认解锁后，恢复中位信号不要求每次重新长鸣；仍需确认电机静止。
ok 只记录观察，不发送解锁信号。若本次上电尚未确认解锁，先记录现象，不加油门。
五秒结束会主动断开 PWM；请观察中位保持期间的灯/声音，结束后状态可能改变。
没确认中位时，数字和 +/- 油门输入会被拒绝；启动本身不发送中位或油门。
旧笔记的 422/424/427 是未知频率下的计数，不能当成微秒直接输入。
先找起转点和低速点；发现转速过快就停止向该方向增加。
持续测试按 hold 0.5 → hold 1 → hold 2 → hold 5 手动逐级开始。
每级先观察平稳、回中能停住，再输入下一级；不会自动连续执行。
hold 固定使用已复现的 1655 微秒，不受上次数字参考值影响，不支持其他脉宽。
中位改变、init、off、普通数字油门测试或通信错误后，需从 hold 0.5 重新开始。
测试过程中按 Ctrl+C 中断并请求关闭；q/off 只在返回输入提示符后接收。
"""

PHASES = {'neutral-before': '中位保持', 'throttle': '短时油门',
          'neutral-after': '回中保持', 'off/idle': '关闭输出'}


def now():
    return dt.datetime.now().astimezone().isoformat()


def parse_target(text, reference, minimum, maximum, max_step):
    value = reference+int(text) if text.startswith(('+', '-')) else int(text)
    if not minimum <= value <= maximum:
        raise ValueError(f'油门只接受 {minimum}–{maximum} 微秒；旧计数 422 不是 422 微秒。')
    if abs(value-reference) > max_step:
        raise ValueError(f'当前参考 {reference} 微秒，单次变化最多 {max_step} 微秒。')
    return value


def run_console(bench, report, save, neutral_us=1500, minimum=1250, maximum=1800, max_step=10,
                read_line=input, write=print, frequency=50):
    reference = neutral_us
    confirmed = False
    pending_neutral = None
    last_trial = None
    hold_completed = 0
    report.setdefault('commands', [])
    report.setdefault('marks', {})
    report.setdefault('mark_history', [])
    report['neutral_confirmed'] = False
    report['neutral_candidate_us'] = neutral_us
    report['hold_completed_seconds'] = 0
    try:
        state = bench.sample()
        firmware_version = state['firmware_version']
        if state['firmware_version'] < 3:
            raise RuntimeError('电调标定需要 pca_bench 固件 v3；请下载当前位流。')
        state = bench.initialize(frequency)
        if not state['ready'] or state['error_code']:
            raise RuntimeError(f'初始化失败：{state}')
        write('初始化通过，全部输出关闭。')
        report['requested_pwm_hz'] = frequency
        report['pwm_timing'] = {key: state[key] for key in ('prescale', 'tick_us', 'nominal_frequency_hz')}
        report['nominal_pwm_hz'] = state['nominal_frequency_hz']
        write(f'PWM 设置 {frequency} Hz，寄存器读回 PRE_SCALE={state["prescale"]}；'
              f'标称频率 {state["nominal_frequency_hz"]:.4f} Hz。输入单位仍为微秒。')
        write(HELP)
        write(f'油门范围 {minimum}–{maximum} 微秒，单次变化最多 {max_step} 微秒。')
        report['initialized_at'] = now()
        save()
        while True:
            text = read_line(f'电调[中位 {neutral_us}; 参考 {reference}; {"已确认" if confirmed else "未确认"}] > ').strip()
            if not text:
                continue
            command = text.lower()
            if command in ('q', 'quit', 'exit'):
                break
            if command in ('h', 'help', '?'):
                write(HELP)
                continue
            entry = dict(time=now(), input=text, success=False)
            report['commands'].append(entry)
            try:
                if command == 'neutral' or command.startswith('neutral '):
                    parts = command.split()
                    if len(parts) not in (1, 2):
                        raise ValueError('用法：neutral 或 neutral 1500。')
                    candidate = neutral_us if len(parts) == 1 else int(parts[1])
                    if not 1400 <= candidate <= 1600 or not minimum <= candidate <= maximum:
                        raise ValueError('中位候选必须为 1400–1600 微秒，且在当前油门范围内。')
                    confirmed = False
                    report['neutral_confirmed'] = False
                    pending_neutral = last_trial = None
                    hold_completed = 0
                    report['hold_completed_seconds'] = 0
                    if candidate != neutral_us:
                        report['marks'] = {}
                    neutral_us = reference = candidate
                    report['neutral_candidate_us'] = candidate
                    write(f'通道 0：中位候选 {candidate} 微秒，保持 5 秒。观察解锁提示及电机是否静止。', flush=True)
                    result = bench.esc_sequence(candidate, neutral_only=True,
                                                progress=lambda phase: write(PHASES[phase], flush=True))
                    pending_neutral = dict(result)
                    entry['result'] = result
                    write('中位输出已关闭。本次电调上电已确认正常解锁，且保持期间电机静止、红灯熄灭，才输入 ok；否则用 note 记录现象。')
                elif command == 'ok':
                    if pending_neutral is None:
                        raise ValueError('请先成功运行 neutral，再根据现场观察确认。')
                    confirmed = True
                    report['neutral_confirmed'] = True
                    report['neutral_confirmation'] = dict(time=now(), requested_us=neutral_us,
                        ticks=pending_neutral['ticks'], nominal_actual_us=pending_neutral['nominal_actual_us'],
                        source='User entered ok after observing successful unlock and stationary motor')
                    entry['result'] = dict(report['neutral_confirmation'])
                    pending_neutral = None
                    reference = neutral_us
                    write('中位观察已记录。可用 +5 开始寻找起转点，并记录实际方向。')
                elif command == 'hold' or command.startswith('hold '):
                    parts = command.split()
                    if len(parts) != 2 or parts[1] not in ('0.5', '1', '2', '5'):
                        raise ValueError('用法：hold 0.5、hold 1、hold 2、hold 5。')
                    duration = float(parts[1])
                    if firmware_version < 6:
                        raise ValueError('持续测试需要 v6 固件。')
                    if not confirmed:
                        raise ValueError('先完成 neutral 和现场观察，再输入 ok。')
                    if frequency != 60 or neutral_us != 1550:
                        raise ValueError('hold 固定使用 60 Hz、中位 1550 微秒；更换条件后需重新初始化和确认。')
                    if not minimum <= 1655 <= maximum:
                        raise ValueError('当前命令行油门范围不包含 1655 微秒，hold 不会绕过此限制。')
                    required = {.5: 0, 1: .5, 2: 1, 5: 2}[duration]
                    if hold_completed < required:
                        raise ValueError(f'请先完成 hold {required:g}，观察平稳并回中停住后再延长。')
                    last_trial = None
                    write(f'通道 0：中位 1550 保持 5 秒 → 固定 1655 油门 {duration:g} 秒 → 回中 1550 保持 1 秒 → 关闭。', flush=True)
                    result = bench.esc_sequence(1655, duration_seconds=duration,
                        progress=lambda phase: write(PHASES[phase], flush=True))
                    result.update(neutral_us=1550, neutral_ticks=round(1550/result['tick_us']),
                                  neutral_nominal_actual_us=round(1550/result['tick_us'])*result['tick_us'])
                    last_trial = result
                    reference = 1655
                    hold_completed = max(hold_completed, duration)
                    report['hold_completed_seconds'] = hold_completed
                    entry['result'] = result
                    write('本级已到期回中并关闭。请用 note 记录转动是否平稳、回中多久停住；观察通过后再手动开始下一级。')
                elif command in ('start', 'slow'):
                    if last_trial is None or not confirmed:
                        raise ValueError('请先成功测试一个油门值，再记录起转点/低速点。')
                    if last_trial['ticks'] == last_trial['neutral_ticks']:
                        raise ValueError('上次输出等于中位，不能记录为起转点或低速点。')
                    mark = dict(last_trial)
                    mark.update(time=now(), neutral_us=neutral_us)
                    report['marks'][command] = mark
                    report['mark_history'].append(dict(label=command, **mark))
                    entry['result'] = dict(mark)
                    write(f'已记录 {command} = {mark["requested_us"]} 微秒；请用 note 补充前进/后退方向。')
                elif command.startswith('note '):
                    entry['note'] = text[5:].strip()
                    write('观察已保存。')
                elif command == 'results':
                    entry['result'] = dict(neutral_confirmed=confirmed,
                        neutral_confirmation=report.get('neutral_confirmation'), marks=dict(report['marks']))
                    write(json.dumps(entry['result'], indent=2, ensure_ascii=False))
                elif command in ('status', 'off', 'init'):
                    if command != 'status':
                        confirmed = False
                        report['neutral_confirmed'] = False
                        pending_neutral = last_trial = None
                        hold_completed = 0
                        report['hold_completed_seconds'] = 0
                        reference = neutral_us
                    state = (bench.sample() if command == 'status' else
                             bench.initialize(frequency) if command == 'init' else bench.command(1))
                    entry['result'] = state
                    write(json.dumps(state, indent=2, ensure_ascii=False))
                else:
                    if not confirmed:
                        raise ValueError('先执行 neutral，并在解锁正常且电机静止后输入 ok。')
                    target = parse_target(command, reference, minimum, maximum, max_step)
                    last_trial = None
                    hold_completed = 0
                    report['hold_completed_seconds'] = 0
                    write(f'通道 0：中位 5 秒 → {target} 微秒油门 0.5 秒 → 回中 1 秒 → 关闭。', flush=True)
                    result = bench.esc_sequence(target, progress=lambda phase: write(PHASES[phase], flush=True))
                    result['neutral_us'] = neutral_us
                    result['neutral_ticks'] = round(neutral_us/result['tick_us'])
                    result['neutral_nominal_actual_us'] = result['neutral_ticks']*result['tick_us']
                    last_trial = result
                    reference = target
                    entry['result'] = result
                    write('本次流程完成，已关闭输出。记录是否起转、方向及速度。')
                entry['success'] = True
            except ValueError as exc:
                entry['error'] = str(exc)
                write(f'未执行：{exc}')
            except Exception as exc:
                entry['error'] = str(exc)
                confirmed = False
                report['neutral_confirmed'] = False
                pending_neutral = last_trial = None
                hold_completed = 0
                report['hold_completed_seconds'] = 0
                write(f'操作失败：{exc}\n控制链路出错，已撤销中位确认；这不是电调解锁反馈。'
                      '\n先关闭动力。若有 I2C timeout、SDA=0 或关闭未确认，不要反复输入油门。'
                      '\n修复通信并确认全部关闭后，才重新接动力、neutral 和 ok。')
            finally:
                save()
    except (KeyboardInterrupt, EOFError):
        report['interrupted'] = True
        write('\n中断测试，正在关闭输出并保存。')
    finally:
        try:
            state = bench.command(1)
            report['final_status'] = state
            report['shutdown_confirmed'] = not any(state[key] for key in (
                'busy', 'shutdown_pending', 'active_or_shutdown_unconfirmed'))
            if not report['shutdown_confirmed']:
                write('关闭状态未确认，请关闭动力电源。')
        except Exception as exc:
            report['shutdown_confirmed'] = False
            report['shutdown_error'] = str(exc)
            write(f'无法确认关闭：{exc}\n请关闭动力电源。')
        report['ended_at'] = now()
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pds', type=Path, default=Path('C:/pango/PDS_2025.2-ads'))
    parser.add_argument('--frequency', type=int, choices=[50, 60], default=50)
    parser.add_argument('--neutral-us', type=int, default=1500)
    parser.add_argument('--min-us', type=int, default=1250)
    parser.add_argument('--max-us', type=int, default=1800)
    parser.add_argument('--max-step-us', type=int, default=10)
    args = parser.parse_args()
    if not 1250 <= args.min_us <= args.neutral_us <= args.max_us <= 1800:
        parser.error('油门范围必须包含中位，且位于 1250..1800 微秒。')
    if not 1400 <= args.neutral_us <= 1600 or not 1 <= args.max_step_us <= 20:
        parser.error('中位范围 1400..1600；单次变化上限 1..20 微秒。')
    folder = ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_esc_manual')
    folder.mkdir(parents=True)
    target = folder/'esc_calibration.json'
    report = dict(started_at=now(), throttle_channel=0, steering_channel=3,
        requested_pwm_hz=args.frequency, nominal_pwm_hz=None, minimum_us=args.min_us, maximum_us=args.max_us,
        maximum_step_us=args.max_step_us, events=[], commands=[], marks={}, shutdown_confirmed=False)

    def save():
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        temporary.replace(target)

    save()
    shell = None
    code = 0
    try:
        print(f'结果文件：{target}', flush=True)
        print('正在连接 JTAG，首次连接可能需要几十秒。', flush=True)
        shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe', folder)
        bench = PcaBench(shell, report['events'])
        run_console(bench, report, save, args.neutral_us, args.min_us, args.max_us, args.max_step_us,
                    frequency=args.frequency)
        code = 0 if report['shutdown_confirmed'] else 1
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or 'KeyboardInterrupt'
        print(f'运行失败：{report["error"]}')
        code = 1
    finally:
        if shell:
            shell.close()
        save()
    print(json.dumps(dict(neutral=report.get('neutral_confirmation'), marks=report['marks']),
                     indent=2, ensure_ascii=False))
    print(f'请把中位、起转点、低速点、实际方向告诉我，或提供此文件路径：{target}')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
