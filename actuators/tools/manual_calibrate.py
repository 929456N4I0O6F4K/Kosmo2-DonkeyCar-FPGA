"""本地交互式舵机标定：通道 3、微秒输入、每次两秒、自动记录。"""
import argparse
import datetime as dt
import json
from pathlib import Path

from pca_bench import ROOT, Debugger, PcaBench

MIN_US = 1200
MAX_US = 2586
MAX_STEP_US = 500

HELP = """
输入示例：
  1700          测试 1700 微秒，持续两秒后自动关闭
  +10 / -10     相对上次成功设置增加/减少 10 微秒
  center        把上次成功测试值记为直行中位
  left / right  把上次成功测试值记为安全左/右转向端点
  note 说明     记录观察结果
  results       显示已记录的中位和端点
  status        查看当前状态
  init          总线错误恢复后重新初始化（全部输出关闭）
  off           关闭全部输出
  q             关闭输出并退出；Ctrl+C 也可退出

只控制舵机通道 3；电调通道 0 保持关闭。
输入单位是微秒，不是旧笔记中的 PCA9685 计数。400 会被拒绝。
从 1600 微秒附近开始，可用 +10/-10 或 +100/-100 调整。
到机械限位就停止向该方向调整，记录端点时留一点余量。
"""


def now():
    return dt.datetime.now().astimezone().isoformat()


def parse_pulse(text, reference, minimum, maximum, max_step=MAX_STEP_US):
    if text.startswith(('+', '-')):
        value = reference + int(text)
    else:
        value = int(text)
    if not minimum <= value <= maximum:
        raise ValueError(f'只接受 {minimum}–{maximum} 微秒；旧计数 400 不是 400 微秒。')
    if abs(value-reference) > max_step:
        raise ValueError(f'当前参考值 {reference} 微秒，单次最多变化 {max_step}；请分步调整。')
    return value


def summarize_marks(report):
    marks = report['marks']
    complete = all(key in marks for key in ('left', 'center', 'right'))
    consistent = complete and (
        min(marks['left']['ticks'], marks['right']['ticks']) < marks['center']['ticks']
        < max(marks['left']['ticks'], marks['right']['ticks']))
    report['three_points_consistent'] = bool(consistent)
    return {'channel': 3, 'unit': 'microseconds', 'marks': marks,
            'three_points_consistent': bool(consistent),
            'note': '现场目测标记；未自动应用到驾驶程序。'}


def run_console(bench, report, save, minimum=MIN_US, maximum=MAX_US,
                read_line=input, write=print, max_step=MAX_STEP_US):
    reference = 1600
    last_pulse = None
    report.setdefault('commands', [])
    report.setdefault('marks', {})
    try:
        state = bench.sample()
        if state['firmware_version'] < 2:
            raise RuntimeError('需要 pca_bench 固件 v2；请按 README 下载当前位流。')
        state = bench.command(2)
        if not state['ready'] or state['error_code']:
            raise RuntimeError(f'初始化失败：{state}')
        write('初始化通过，全部输出关闭。舵机通道 3；电调通道 0。')
        write(HELP)
        write(f'本次允许范围：{minimum}–{maximum} 微秒，单次最多变化 {max_step} 微秒。')
        write('1600 只是输入参考值，不会自动输出。')
        report['initialized_at'] = now()
        save()
        while True:
            text = read_line(f'舵机[参考 {reference} us] > ').strip()
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
                if command in ('center', 'left', 'right'):
                    if last_pulse is None:
                        raise ValueError('请先成功测试一个脉宽，再记录它的位置。')
                    report['marks'][command] = dict(time=now(), **last_pulse)
                    entry['result'] = summarize_marks(report)
                    write(f'已记录 {command} = {last_pulse["requested_us"]} 微秒（{last_pulse["ticks"]} tick）。')
                    if len(report['marks']) == 3 and not report['three_points_consistent']:
                        write('三个标记尚不一致：center 应位于 left/right 之间，不能把同一个值标成不同端点。')
                elif command == 'results':
                    entry['result'] = summarize_marks(report)
                    write(json.dumps(entry['result'], indent=2, ensure_ascii=False))
                elif command.startswith('note '):
                    entry['note'] = text[5:].strip()
                    write('观察记录已保存。')
                elif command in ('status', 'off', 'init'):
                    state = bench.sample() if command == 'status' else bench.command(1 if command == 'off' else 2)
                    entry['result'] = state
                    write(json.dumps(state, indent=2, ensure_ascii=False))
                else:
                    value = parse_pulse(command, reference, minimum, maximum, max_step)
                    write(f'测试通道 3：{value} 微秒，持续两秒。', flush=True)
                    # Clear the mark source before a command that might fail.
                    last_pulse = None
                    result = bench.pulse(3, value)
                    last_pulse = result
                    reference = value
                    entry['result'] = result
                    write(f'已自动关闭。标称实际脉宽 {result["nominal_actual_us"]:.2f} 微秒；请观察并记录。')
                entry['success'] = True
            except ValueError as exc:
                entry['error'] = str(exc)
                write(f'未执行：{exc}')
            except Exception as exc:
                entry['error'] = str(exc)
                last_pulse = None
                write(f'操作失败：{exc}\n请检查状态/接线；错误恢复后可输入 init。')
            finally:
                save()
    except (KeyboardInterrupt, EOFError):
        write('\n正在关闭输出并保存结果……')
        report['interrupted'] = True
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
        summarize_marks(report)
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pds', type=Path, default=Path('C:/pango/PDS_2025.2-ads'))
    parser.add_argument('--min-us', type=int, default=MIN_US)
    parser.add_argument('--max-us', type=int, default=MAX_US)
    parser.add_argument('--max-step-us', type=int, default=MAX_STEP_US,
                        help='单次脉宽变化上限，默认 500 微秒')
    args = parser.parse_args()
    if not 1200 <= args.min_us <= 1600 <= args.max_us <= 2586:
        parser.error('范围必须包含起点 1600，且位于固件允许的 1200..2586 微秒内。')
    if not 1 <= args.max_step_us <= MAX_US-MIN_US:
        parser.error(f'--max-step-us 必须在 1..{MAX_US-MIN_US} 微秒内。')
    folder = ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_manual')
    folder.mkdir(parents=True)
    target = folder/'calibration.json'
    report = dict(started_at=now(), steering_channel=3, throttle_channel=0,
                  nominal_pwm_hz=25_000_000/(122*4096), minimum_us=args.min_us,
                  maximum_us=args.max_us, maximum_step_us=args.max_step_us,
                  events=[], commands=[], marks={}, shutdown_confirmed=False)

    def save():
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        temporary.replace(target)

    save()
    shell = None
    result = 0
    try:
        print(f'结果文件：{target}', flush=True)
        print('正在连接板载 JTAG，首次连接可能需要几十秒。', flush=True)
        shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe', folder)
        bench = PcaBench(shell, report['events'])
        run_console(bench, report, save, args.min_us, args.max_us, max_step=args.max_step_us)
        result = 0 if report['shutdown_confirmed'] else 1
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or 'KeyboardInterrupt'
        print(f'运行失败：{report["error"]}')
        result = 1
    finally:
        if shell:
            shell.close()
        save()
    print(json.dumps(summarize_marks(report), indent=2, ensure_ascii=False))
    print(f'请把结果告诉我，或提供此文件路径：{target}')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
