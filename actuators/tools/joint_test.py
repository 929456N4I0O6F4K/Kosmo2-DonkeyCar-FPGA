"""60 Hz 本地联合台架测试：先确认转向，再逐级短时前进。"""
import argparse
import datetime as dt
import json
from pathlib import Path

from pca_bench import ROOT, Debugger, PcaBench, JOINT_STEERING, joint_steering_value

# Selected in the 20261005_204600 session; user confirmed normal tests and
# deliberate inward margins from the outer trials at 1470/2040 us.
# A new session still requires all physical confirmations before driving.
STARTUP_STEERING = {'center': 1745, 'right': 1490, 'left': 2020}

HELP = """
固定通道：电调 0、舵机 3；60 Hz。电调中位 1550，前进 1655 微秒。
转向启动位置：center={center}、right={right}、left={left} 微秒。
v8 中位可在 1650..1750 微秒微调，每次最多 10；增大向左、减小向右。
v9 左右范围 1450..2040 微秒，保持在中位的对应侧；v8 仍限 1490..1990。
超出右 1490 或左 1990 向外试探，每步最多 20 微秒；范围内每步最多 50。
启动仅初始化并关闭输出。驱动轮架空，关闭其他 JTAG 窗口。

  neutral             舵机关闭，仅发送 1550 中位 5 秒
  ok                  确认刚完成测试的现场现象，不发送动作
  fail 原因           本次现场不通过，保存原因并撤销本轮确认
  steer center        电调保持中位，转向中位测试
  steer right / left  电调保持中位，右/左转 2 秒后回中保持 1 秒
  set center 1750     仅修改本轮中位，不发动作；随后 steer center 测试
  set right 1470      仅修改本轮右转目标，不发动作；随后 steer right 测试
  set left 2010       仅修改本轮左转目标，不发动作；随后 steer left 测试
  drive center 0.5    固定 1655 油门，直行半秒后回中、关闭
  drive right 0.5     固定 1655 油门，当前右转位置半秒后回中、关闭
  drive left 0.5      固定 1655 油门，当前左转位置半秒后回中、关闭
  drive 位置 1 / 2    每个位置分别从 0.5 → 1 → 2 秒，逐级人工确认
  compare solo        对照：仅电调，1655 微秒半秒，舵机关闭
  compare center      对照：同一油门/时长，加上当前中位舵机
  observed moving     对照的给油阶段，驱动轮正常转动
  observed no-motion  对照的给油阶段，驱动轮没有转动
  observed abnormal   对照出现抖动/不停等异常，撤销本轮确认
  note 观察内容       记录方向、是否平稳、回中停止及转向对电机的影响
  results / status   查看本轮确认结果 / 板端状态
  off / init         关闭 / 重新初始化；清除本轮确认，须重新开始
  q                  关闭并保存退出

首次上电：电调开关先关闭，逻辑供电保持；输入 neutral，看到中位保持后
第一秒内开启电调。测试结束且确认解锁正常、车轮静止，再输入 ok。
然后 steer center、steer right、steer left，每次确认方向/回中正确、
无顶死或抖动且电机始终静止，才输入 ok。若中位或左右不符，用 fail 原因 记录。
扩大某侧角度前，必须先 steer 该侧并 ok 确认当前值；set 后该侧需重新测试确认。
每次 set 会清除全部前进时长进度；新角度下前进仍从半秒开始。
修改中位会清除全部转向确认；测试前和回中时均使用新中位，电调中位仍为 1550。
退出重开或 init 后恢复默认值；off 保留本轮位置设置，但清除现场确认。
三项转向均确认后才开放 drive；先确认 drive center 0.5，再做带转向前进。
每次 drive 后先观察前进平稳、转向正确、回中能停住，再输入 ok。
ok 表示现场通过，不表示“读到提示/继续”；没转动、回正不足时用 fail 原因。
对照仅需 neutral/ok 和 steer center/ok，按 solo → center → solo 逐条进行。
对照后用 observed 记录给油阶段的驱动轮表现，不用 ok，不增加 drive 的通过进度。
各次联合测试：双通道中位 5 秒 → 目标组合 → 双通道回中 → 全部关闭。
回中保持 1 秒。当前工作范围已留余量；下一步先确认静态位置，再测试半秒联合前进。
请逐条输入，不要粘贴整段命令。Ctrl+C 可中断并请求关闭；q/off 仅在提示符接收。
这是有界台架测试，PA 自动到期回中关闭；不是持续驾驶或网络失联急停。
"""
PHASES = {'neutral-before': '中位保持', 'throttle': '目标组合保持',
          'neutral-after': '电调回中、转向回中', 'off/idle': '关闭输出'}


def now():
    return dt.datetime.now().astimezone().isoformat()


def run_console(bench, report, save, read_line=input, write=print, initial_steering=None):
    report['tool_revision'] = 5
    report.setdefault('commands', [])
    report.setdefault('confirmations', [])
    report.setdefault('failed_observations', [])
    report.setdefault('comparison_observations', [])
    report.setdefault('settings_history', [])
    initial_steering = dict(STARTUP_STEERING if initial_steering is None else initial_steering)
    steering = dict(initial_steering)
    report['startup_steering_us'] = dict(initial_steering)
    report['steering_us'] = dict(steering)
    pending = None

    def reset_confirmations():
        nonlocal pending
        pending = None
        report['neutral_confirmed'] = False
        report['steering_confirmed'] = []
        report['drive_confirmed_seconds'] = {p: 0 for p in JOINT_STEERING}

    reset_confirmations()
    try:
        for position, value in initial_steering.items():
            joint_steering_value(position, value, initial_steering['center'])
        firmware_version = bench.sample()['firmware_version']
        if firmware_version < 7:
            raise RuntimeError('联合测试需要 v7 固件。')
        if firmware_version < 8 and initial_steering != JOINT_STEERING:
            raise RuntimeError('当前启动转向参数需要 v8 或更新固件。')
        if firmware_version < 9 and any(not 1490 <= v <= 1990 for v in initial_steering.values()):
            raise RuntimeError('扩大后的启动转向参数需要 v9 固件。')
        state = bench.initialize(60)
        if not state['ready'] or state['error_code']:
            raise RuntimeError(f'初始化失败：{state}')
        report['pwm_timing'] = {k: state[k] for k in ('prescale', 'tick_us', 'nominal_frequency_hz')}
        report['initialized_at'] = now()
        if initial_steering['center'] != 1695:
            report['startup_center_configuration'] = bench.configure_joint_center(initial_steering['center'])
        write('60 Hz 初始化通过，全部输出关闭。')
        write(HELP.format(**initial_steering))
        save()
        while True:
            text = read_line('联合测试 > ').strip()
            parts = text.lower().split()
            if not parts:
                continue
            if parts in (['q'], ['quit'], ['exit']):
                break
            if parts in (['help'], ['h'], ['?']):
                write(HELP.format(**initial_steering))
                continue
            entry = dict(time=now(), input=text, success=False)
            report['commands'].append(entry)
            try:
                if parts == ['neutral']:
                    reset_confirmations()
                    write('通道 0 中位 1550 微秒保持 5 秒，通道 3 关闭。', flush=True)
                    result = bench.esc_sequence(1550, neutral_only=True,
                        progress=lambda phase: write(PHASES[phase], flush=True))
                    pending = dict(kind='neutral', result=result)
                    entry['result'] = result
                    write('输出已关闭。确认解锁正常、保持期间车轮静止，才输入 ok。')
                elif parts == ['ok']:
                    if pending is None:
                        raise ValueError('没有待确认的成功测试；请先运行 neutral、steer 或 drive。')
                    if pending['kind'] == 'compare':
                        raise ValueError('对照结果用 observed moving/no-motion/abnormal 记录，不用 ok。')
                    confirmation = dict(time=now(), source='User entered ok after physical observation', **pending)
                    if pending['kind'] == 'neutral':
                        report['neutral_confirmed'] = True
                    elif pending['kind'] == 'steer':
                        report['steering_confirmed'].append(pending['result']['position'])
                    else:
                        r = pending['result']
                        report['drive_confirmed_seconds'][r['position']] = max(
                            report['drive_confirmed_seconds'][r['position']], r['target_seconds'])
                    report['confirmations'].append(confirmation)
                    entry['result'] = confirmation
                    pending = None
                    write('现场观察已确认并保存。')
                elif parts[0] == 'fail' and len(parts) > 1:
                    if pending is None:
                        raise ValueError('没有待确认的测试；可用 note 保存额外现象。')
                    observation = dict(time=now(), passed=False,
                        reason=text.split(maxsplit=1)[1], **pending)
                    report['failed_observations'].append(observation)
                    entry['result'] = observation
                    reset_confirmations()
                    write('已记录现场不通过，清除本轮确认。用 note 补充现象；重新测试需从 neutral 开始。')
                elif parts[0] == 'compare':
                    if len(parts) != 2 or parts[1] not in ('solo', 'center'):
                        raise ValueError('用法：compare solo 或 compare center；固定 1655 微秒、半秒。')
                    if not report['neutral_confirmed'] or 'center' not in report['steering_confirmed']:
                        raise ValueError('对照前需 neutral/ok 和 steer center/ok；无需确认左右转向。')
                    if pending is not None:
                        raise ValueError('请先记录或确认上一项现场观察，再开始对照。')
                    mode = parts[1]
                    report['drive_confirmed_seconds'] = {p: 0 for p in JOINT_STEERING}
                    write(f'对照 {mode}：电调 1550 中位 5 秒 → 1655 油门半秒 → 1550 回中 1 秒 → 全关闭。', flush=True)
                    result = (bench.esc_sequence(1655, duration_seconds=.5,
                        progress=lambda phase: write(PHASES[phase], flush=True)) if mode == 'solo' else
                        bench.joint_sequence('center', moving=True, duration_seconds=.5,
                        center_us=steering['center'],
                        progress=lambda phase: write(PHASES[phase], flush=True)))
                    result = dict(result, comparison_mode=mode, neutral_us=1550,
                                  comparison_throttle_us=1655, comparison_target_seconds=.5,
                                  servo_enabled=(mode == 'center'))
                    entry['result'] = result
                    pending = dict(kind='compare', result=result)
                    write('已回中并关闭。请记录给油阶段驱动轮表现：observed moving / observed no-motion / observed abnormal。')
                elif parts[0] == 'observed':
                    if len(parts) != 2 or parts[1] not in ('moving', 'no-motion', 'abnormal'):
                        raise ValueError('用法：observed moving、observed no-motion、observed abnormal。')
                    if pending is None or pending['kind'] != 'compare':
                        raise ValueError('请先完成一次 compare 对照。')
                    observation = dict(time=now(), outcome=parts[1],
                        source='User observation of drive wheels during the half-second target phase', **pending)
                    report['comparison_observations'].append(observation)
                    entry['result'] = observation
                    pending = None
                    if parts[1] == 'abnormal':
                        reset_confirmations()
                    write('对照观察已保存；没有记作 drive 通过。用 note 补充电调声响、回中停止等现象。')
                elif parts[0] == 'set':
                    if len(parts) != 3 or parts[1] not in JOINT_STEERING:
                        raise ValueError('用法：set center/right/left 微秒；中位每次最多改变 10 微秒。')
                    if firmware_version < 8:
                        raise ValueError('可调整联合转向需要 v8 固件。')
                    if pending is not None:
                        raise ValueError('先用 ok 或 fail 记录上一项现场结果，再修改目标。')
                    position = parts[1]
                    requested = int(parts[2])
                    value = joint_steering_value(position, requested,
                        requested if position == 'center' else steering['center'])
                    if firmware_version < 9 and not 1490 <= value <= 1990:
                        raise ValueError('超出 1490..1990 微秒的试探需要 v9 固件。')
                    previous = steering[position]
                    outward = position != 'center' and abs(value-steering['center']) > abs(previous-steering['center'])
                    outer_trial = outward and (value < 1490 or value > 1990)
                    limit = 10 if position == 'center' else 20 if outer_trial else 50
                    if abs(value-previous) > limit:
                        raise ValueError(f'{position} 当前 {previous} 微秒，每次最多改变 {limit} 微秒。')
                    if outward and position not in report['steering_confirmed']:
                        raise ValueError(f'扩大角度前先 steer {position} 并 ok 确认当前 {previous} 微秒。')
                    change = dict(time=now(), position=position, previous_us=previous,
                                  requested_us=value, changed=value != previous, output_sent=False)
                    if position == 'center':
                        joint_steering_value('right', steering['right'], value)
                        joint_steering_value('left', steering['left'], value)
                        change['configuration'] = bench.configure_joint_center(value)
                    entry['result'] = change
                    report['settings_history'].append(change)
                    if value != previous:
                        steering[position] = value
                        report['steering_us'] = dict(steering)
                        report['steering_confirmed'] = ([] if position == 'center' else
                            [p for p in report['steering_confirmed'] if p != position])
                        report['drive_confirmed_seconds'] = {p: 0 for p in JOINT_STEERING}
                    write(f'本轮 {position} 目标为 {value} 微秒，尚未发出动作。输入 steer {position} 测试，正常才 ok。')
                elif parts[0] in ('steer', 'drive'):
                    moving = parts[0] == 'drive'
                    if len(parts) != (3 if moving else 2) or parts[1] not in JOINT_STEERING:
                        raise ValueError('用法：steer center/right/left，或 drive center/right/left 0.5/1/2。')
                    if moving and parts[2] not in ('0.5', '1', '2'):
                        raise ValueError('前进时长只接受 0.5、1、2 秒。')
                    if not report['neutral_confirmed']:
                        raise ValueError('先完成 neutral 并现场确认后输入 ok。')
                    position = parts[1]
                    duration = float(parts[2]) if moving else 2
                    if moving:
                        if set(report['steering_confirmed']) != set(JOINT_STEERING):
                            raise ValueError('先分别完成并 ok 确认 steer center、steer right、steer left。')
                        completed = report['drive_confirmed_seconds']
                        if position != 'center' and completed['center'] < .5:
                            raise ValueError('先完成 drive center 0.5，并确认现场正常后输入 ok。')
                        required = {.5: 0, 1: .5, 2: 1}[duration]
                        if completed[position] < required:
                            raise ValueError(f'先完成 drive {position} {required:g}，现场观察通过后输入 ok。')
                    else:
                        if position != 'center' and 'center' not in report['steering_confirmed']:
                            raise ValueError('先完成 steer center 并确认中位后输入 ok。')
                        report['steering_confirmed'] = [p for p in report['steering_confirmed'] if p != position]
                        report['drive_confirmed_seconds'] = {p: 0 for p in JOINT_STEERING}
                    pending = None
                    write(f'舵机中位 {steering["center"]} 微秒保持 5 秒 → {position} {steering[position]} 微秒、'
                          f'电调 {1655 if moving else 1550} 微秒保持 {duration:g} 秒 → 舵机回中 {steering["center"]} 微秒 1 秒 → 关闭。', flush=True)
                    result = bench.joint_sequence(position, moving=moving, duration_seconds=duration,
                        steering_us=steering[position], center_us=steering['center'],
                        progress=lambda phase: write(PHASES[phase], flush=True))
                    entry['result'] = result
                    pending = dict(kind=parts[0], result=result)
                    if moving:
                        write('已回中并关闭。前进平稳、方向正确、回中停住才输入 ok；没转动或有异常请输入 fail 原因。')
                    else:
                        write('已回中并关闭。位置/回中正确、无抖动且电机全程静止才输入 ok；回正不足等情况请输入 fail 原因。')
                elif parts[0] == 'note' and len(parts) > 1:
                    entry['note'] = text.split(maxsplit=1)[1]
                    write('观察已保存。')
                elif parts == ['results']:
                    entry['result'] = dict(neutral_confirmed=report['neutral_confirmed'],
                        steering_us=dict(steering),
                        steering_confirmed=list(report['steering_confirmed']),
                        drive_confirmed_seconds=dict(report['drive_confirmed_seconds']))
                    write(json.dumps(entry['result'], ensure_ascii=False, indent=2))
                elif parts in (['status'], ['off'], ['init']):
                    if parts != ['status']:
                        reset_confirmations()
                    state = (bench.sample() if parts == ['status'] else
                             bench.initialize(60) if parts == ['init'] else bench.command(1))
                    if parts == ['init']:
                        if initial_steering['center'] != 1695:
                            entry['center_configuration'] = bench.configure_joint_center(initial_steering['center'])
                        steering = dict(initial_steering)
                        report['steering_us'] = dict(steering)
                        write(f'已恢复启动位置：{steering}。')
                    entry['result'] = state
                    if state['error_code'] or not state['ready'] or state['active_or_shutdown_unconfirmed']:
                        raise RuntimeError(f'板端状态异常：{state}')
                    write(json.dumps(state, ensure_ascii=False, indent=2))
                else:
                    raise ValueError('未知命令，输入 help 查看用法。')
                entry['success'] = True
            except ValueError as exc:
                entry['error'] = str(exc)
                write(f'未执行：{exc}')
            except Exception as exc:
                entry['error'] = str(exc)
                reset_confirmations()
                write(f'操作失败：{exc}\n已清除本轮确认。先关闭动力并排查通信，再 init、neutral 和 ok。')
            finally:
                report['pending_confirmation'] = pending
                save()
    except (KeyboardInterrupt, EOFError):
        report['interrupted'] = True
        write('中断测试，正在关闭输出并保存。')
    finally:
        try:
            state = bench.command(1)
            report['final_status'] = state
            report['shutdown_confirmed'] = not any(state[k] for k in (
                'busy', 'shutdown_pending', 'active_or_shutdown_unconfirmed'))
        except Exception as exc:
            report['shutdown_confirmed'] = False
            report['shutdown_error'] = str(exc)
        if not report['shutdown_confirmed']:
            write('关闭未能确认，请关闭电调动力。')
        report['ended_at'] = now()
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pds', type=Path, default=Path('C:/pango/PDS_2025.2-ads'))
    args = parser.parse_args()
    folder = ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_joint_manual')
    folder.mkdir(parents=True)
    target = folder/'joint_test.json'
    report = dict(started_at=now(), requested_pwm_hz=60, throttle_channel=0, steering_channel=3,
                  neutral_us=1550, forward_us=1655, steering_us=dict(STARTUP_STEERING),
                  events=[], commands=[], shutdown_confirmed=False)

    def save():
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(target)

    shell = None
    code = 0
    save()
    try:
        print(f'结果文件：{target}\n正在连接 JTAG，可能需要几十秒。', flush=True)
        shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe', folder)
        run_console(PcaBench(shell, report['events']), report, save)
        code = 0 if report['shutdown_confirmed'] else 1
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or 'KeyboardInterrupt'
        print(f'运行失败：{report["error"]}')
        code = 1
    finally:
        if shell:
            shell.close()
        save()
    print(f'结果已保存：{target}')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
