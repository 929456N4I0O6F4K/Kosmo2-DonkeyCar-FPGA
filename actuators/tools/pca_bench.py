"""PCA9685 bench via PA JTAG: status, probe, off, or a single bounded pulse."""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent/'camera/tools'))
from jtag_shell import Debugger
from jtag_test import dvio_json, port_value

ERRORS = {0: 'none', 1: 'I2C NACK', 2: 'I2C timeout', 3: 'invalid command or retrigger',
          4: 'initialization required', 5: 'register readback mismatch'}
JOINT_STEERING = {'center': 1695, 'right': 1595, 'left': 1795}
JOINT_CENTER_LIMITS = (1650, 1750)


def joint_steering_value(position, microseconds=None, center_us=1695):
    if position not in JOINT_STEERING:
        raise ValueError('Joint position must be center, right or left')
    if type(center_us) is not int or not JOINT_CENTER_LIMITS[0] <= center_us <= JOINT_CENTER_LIMITS[1]:
        raise ValueError('Joint center must be an integer in 1650..1750 microseconds')
    default = center_us if position == 'center' else JOINT_STEERING[position]
    value = default if microseconds is None else microseconds
    lower, upper = {'center': (center_us, center_us), 'right': (1450, center_us-5),
                    'left': (center_us+5, 2040)}[position]
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'{position} steering must be an integer in {lower}..{upper} microseconds')
    return value


def pwm_timing(prescale):
    if prescale not in (121, 101):
        raise ValueError(f'Unsupported PWM prescale {prescale}; initialize 50 or 60 Hz first')
    return dict(prescale=prescale, tick_us=(prescale+1)/25,
                nominal_frequency_hz=25_000_000/((prescale+1)*4096))


def decode(status, diagnostic):
    version = status >> 40 & 255
    if status >> 48 != 0x5043 or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        raise ValueError(f'Load pca_bench_top.sbit first; unexpected signature {status:016x}')
    code = status >> 24 & 15
    phase = (status >> 16 & 3) if version >= 3 and ((status >> 28) & 15) in (5, 6, 7, 8, 9) else 0
    return dict(raw=f'{status:016x}', firmware_version=version, token=status >> 32 & 255,
                esc_phase=phase, esc_phase_name={0: 'off/idle', 1: 'neutral-before', 2: 'throttle', 3: 'neutral-after'}[phase],
                operation=status >> 28 & 15, error_code=code, error=ERRORS.get(code, 'unknown'),
                read_data=status >> 16 & 255, register=status >> 8 & 255,
                ready=bool(status & 1), active_or_shutdown_unconfirmed=bool(status & 2),
                busy=bool(status & 4), shutdown_pending=bool(status & 8),
                expired=bool(status & 16), scl=(status >> 5) & 1, sda=(status >> 6) & 1,
                pulse_elapsed_seconds=(diagnostic >> 32)/50_000_000,
                bus_live=f'{diagnostic & 65535:04x}', bus_failure=f'{diagnostic >> 16 & 65535:04x}')


class PcaBench:
    def __init__(self, shell, events):
        self.shell = shell
        self.events = events
        shell.command('dbg_connect -ip 127.0.0.1 -port 65420', timeout=100)
        shell.command('dbg_scan_chain', timeout=40)
        obj = dvio_json(shell.command('dbg_dvio_refresh -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0'))
        self.control = port_value(obj['probe_outs'][0])
        self._decode(obj)

    def _decode(self, obj):
        if len(obj['probe_ins']) != 2:
            raise ValueError('Expected two PCA bench probes; load the correct bitstream')
        value = decode(*(port_value(port) for port in obj['probe_ins']))
        self.events.append(dict(time=dt.datetime.now().astimezone().isoformat(), **value))
        return value

    def sample(self):
        return self._decode(dvio_json(self.shell.command(
            'dbg_dvio_refresh_input -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0')))

    def idle(self, timeout=5):
        deadline = time.monotonic()+timeout
        last = None
        while time.monotonic() < deadline:
            last = self.sample()
            if not last['busy'] and not last['shutdown_pending']:
                return last
            time.sleep(.05)
        raise TimeoutError(f'Controller did not become idle; check wiring/3.3 V pullups: {last}')

    def command(self, operation, channel=0, data=0):
        state = self.idle()
        token = (state['token']+1) & 255
        value = token << 24 | operation << 20 | channel << 16 | data
        commands = [f'dbg_dvio_set_output -device 1 -dvio 0 -channel {{ProbeOut0[{bit}]}} -value {(value >> bit) & 1}'
                    # Ctrl+C may interrupt a commit before the cached word updates.
                    # An OFF request must overwrite the entire control word.
                    for bit in range(32) if operation == 1 or (self.control ^ value) & (1 << bit)]
        commands.append('dbg_dvio_commit_output -device 1 -dvio 0')
        self.shell.command('\n'.join(commands))
        self.control = value
        deadline = time.monotonic()+5
        last = None
        while time.monotonic() < deadline:
            last = self.sample()
            if last['token'] == token and not last['busy'] and not last['shutdown_pending']:
                if operation != 1 and last['error_code']:
                    raise RuntimeError(f'PCA command failed: {last}')
                return last
            time.sleep(.05)
        raise TimeoutError(f'PCA command not completed: {last}')

    def read(self, register):
        return self.command(3, data=register)['read_data']

    def initialize(self, frequency=50):
        if frequency not in (50, 60):
            raise ValueError('PWM frequency must be 50 or 60 Hz')
        if frequency == 60 and self.sample()['firmware_version'] < 5:
            raise ValueError('60 Hz selection requires firmware v5')
        state = self.command(2, data=60 if frequency == 60 else 0)
        if not state['ready']:
            raise RuntimeError('Initialization did not establish ready state')
        actual = self.read(254)
        expected = 101 if frequency == 60 else 121
        if actual != expected:
            raise RuntimeError(f'PWM prescale mismatch: requested {expected}, read {actual}')
        return dict(state, **pwm_timing(actual))

    def probe(self, frequency=50):
        self.initialize(frequency)
        registers = {f'0x{reg:02x}': self.read(reg) for reg in [0, 1, 254, *range(9, 70, 4)]}
        if (registers['0x00'] & 127 or registers['0x01'] & 31 != 4 or
                registers['0xfe'] != (101 if frequency == 60 else 121)):
            raise RuntimeError(f'Configuration readback mismatch: {registers}')
        if not all(registers[f'0x{reg:02x}'] & 16 for reg in range(9, 70, 4)):
            raise RuntimeError(f'Not all sixteen outputs are disabled: {registers}')
        return dict(address='0x40', registers=registers, all_sixteen_outputs_off=True,
                    **pwm_timing(registers['0xfe']),
                    note='Register verification; actual output waveform and actuator calibration not measured')

    def pulse(self, channel, microseconds):
        state = self.idle()
        if not state['ready'] or state['error_code']:
            raise RuntimeError('Run --action probe successfully before requesting a pulse')
        if not 0 <= channel <= 15:
            raise ValueError('PCA channel must be 0..15')
        if channel == 0 and state['firmware_version'] >= 3:
            raise ValueError('Channel 0 requires the ESC neutral/trial sequence; use esc_calibrate.cmd')
        timing = pwm_timing(self.read(254))
        ticks = round(microseconds/timing['tick_us'])
        lower = round(1200/timing['tick_us'])
        upper = round((2586 if channel == 3 and state['firmware_version'] >= 2 else 1800)/timing['tick_us'])
        if not lower <= ticks <= upper:
            raise ValueError(f'Firmware/channel pulse limit: {lower}..{upper} ticks; requested {ticks}')
        try:
            state = self.command(4, channel, ticks)
            deadline = time.monotonic()+5
            while state['active_or_shutdown_unconfirmed'] or state['busy'] or state['shutdown_pending']:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'Pulse shutdown not confirmed: {state}')
                time.sleep(.1)
                state = self.sample()
            if state['error_code'] or not state['expired']:
                raise RuntimeError(f'Pulse did not complete normally: {state}')
            return dict(channel=channel, requested_us=microseconds, ticks=ticks,
                        nominal_actual_us=ticks*timing['tick_us'], **timing, hardware_limit_seconds=2,
                        expiry_and_all_off_verified=True)
        finally:
            # Also request off on Ctrl-C; FPGA expiry runs without this process.
            self.command(1)

    def esc_sequence(self, microseconds=1500, neutral_only=False, progress=None, duration_seconds=.5):
        """FPGA-owned timing: neutral 5 s, bounded target and neutral 1 s, then off."""
        if duration_seconds not in (.5, 1, 2, 5) or (neutral_only and duration_seconds != .5):
            raise ValueError('Throttle duration must be 0.5, 1, 2 or 5 seconds; neutral uses its fixed dwell')
        state = self.idle()
        if state['firmware_version'] < 3 or not state['ready'] or state['error_code']:
            raise RuntimeError('ESC sequence requires initialized firmware v3 with no error')
        minimum, maximum = (1400, 1600) if neutral_only else (1250, 1800)
        if not minimum <= microseconds <= maximum:
            raise ValueError(f'ESC pulse must be {minimum}..{maximum} microseconds')
        timing = pwm_timing(self.read(254))
        ticks = round(microseconds/timing['tick_us'])
        operation, data = (5 if neutral_only else 6), ticks
        if duration_seconds != .5:
            if state['firmware_version'] < 6:
                raise ValueError('Extended ESC hold requires firmware v6')
            if microseconds != 1655 or timing['prescale'] != 101:
                raise ValueError('Extended ESC hold requires 60 Hz and exactly 1655 microseconds')
            operation, data = 7, (int(duration_seconds) << 12) | ticks
        try:
            state = self.command(operation, 0, data)
            deadline = time.monotonic()+max(10, 5+duration_seconds+1+4)
            previous_phase = None
            while True:
                if progress and state['esc_phase'] != previous_phase:
                    progress(state['esc_phase_name'])
                    previous_phase = state['esc_phase']
                if not any(state[key] for key in ('active_or_shutdown_unconfirmed', 'busy', 'shutdown_pending')):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'ESC sequence shutdown unconfirmed: {state}')
                time.sleep(.05)
                state = self.sample()
            if state['error_code'] or not state['expired']:
                raise RuntimeError(f'ESC sequence did not complete normally: {state}')
            return dict(channel=0, requested_us=microseconds, ticks=ticks,
                        nominal_actual_us=ticks*timing['tick_us'], **timing, neutral_only=neutral_only,
                        neutral_before_seconds=5, throttle_seconds=0 if neutral_only else duration_seconds,
                        neutral_after_seconds=0 if neutral_only else 1,
                        expiry_and_all_off_verified=True)
        finally:
            self.command(1)

    def configure_joint_center(self, microseconds):
        """Configure the PA's initial/return servo center without enabling PWM."""
        joint_steering_value('center', microseconds, center_us=microseconds)
        state = self.idle()
        if state['firmware_version'] < 8 or not state['ready'] or state['error_code']:
            raise RuntimeError('Joint center configuration requires initialized firmware v8')
        if state['active_or_shutdown_unconfirmed']:
            raise RuntimeError('Stop outputs before changing the joint center')
        timing = pwm_timing(self.read(254))
        if timing['prescale'] != 101:
            raise ValueError('Joint center configuration requires 60 Hz')
        ticks = round(microseconds/timing['tick_us'])
        state = self.command(11, 3, ticks)
        if state['operation'] != 11 or state['read_data'] != (ticks & 255):
            raise RuntimeError(f'Joint center acknowledgment mismatch: {state}')
        return dict(requested_us=microseconds, ticks=ticks,
                    nominal_actual_us=ticks*timing['tick_us'], output_sent=False)

    def joint_sequence(self, position, moving=False, duration_seconds=2, progress=None,
                       steering_us=None, center_us=1695):
        """Fixed channel-0/channel-3 bench sequence, timed and stopped by PA."""
        steering_us = joint_steering_value(position, steering_us, center_us)
        if duration_seconds not in (.5, 1, 2) or (not moving and duration_seconds != 2):
            raise ValueError('Steering check is 2 seconds; moving test is 0.5, 1 or 2 seconds')
        state = self.idle()
        if state['firmware_version'] < 7 or not state['ready'] or state['error_code']:
            raise RuntimeError('Joint sequence requires initialized firmware v7 with no error')
        if state['firmware_version'] < 8 and (steering_us != JOINT_STEERING[position] or center_us != 1695):
            raise ValueError('Adjustable joint steering requires firmware v8')
        if state['firmware_version'] < 9 and not 1490 <= steering_us <= 1990:
            raise ValueError('Steering outside 1490..1990 microseconds requires firmware v9')
        timing = pwm_timing(self.read(254))
        if timing['prescale'] != 101:
            raise ValueError('Joint sequence requires 60 Hz')
        steering_ticks = round(steering_us/timing['tick_us'])
        duration_code = 0 if duration_seconds == .5 else int(duration_seconds)
        return_seconds = 1
        try:
            if state['firmware_version'] >= 8:
                self.configure_joint_center(center_us)
            state = self.command(9 if moving else 8, 0, duration_code << 12 | steering_ticks)
            deadline = time.monotonic()+5+duration_seconds+return_seconds+4
            previous_phase = None
            while True:
                if progress and state['esc_phase'] != previous_phase:
                    progress(state['esc_phase_name'])
                    previous_phase = state['esc_phase']
                if not any(state[key] for key in ('active_or_shutdown_unconfirmed', 'busy', 'shutdown_pending')):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'Joint sequence shutdown unconfirmed: {state}')
                time.sleep(.05)
                state = self.sample()
            if state['error_code'] or not state['expired']:
                raise RuntimeError(f'Joint sequence did not complete normally: {state}')
            return dict(position=position, moving=moving, steering_channel=3, throttle_channel=0,
                        steering_us=steering_us, steering_ticks=steering_ticks,
                        steering_nominal_actual_us=steering_ticks*timing['tick_us'],
                        steering_return_us=center_us, steering_return_ticks=round(center_us/timing['tick_us']),
                        throttle_us=1655 if moving else 1550, throttle_ticks=406 if moving else 380,
                        neutral_us=1550, neutral_ticks=380, neutral_before_seconds=5,
                        target_seconds=duration_seconds, neutral_after_seconds=return_seconds,
                        expiry_and_all_off_verified=True, **timing)
        finally:
            self.command(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pds', type=Path, default=Path('C:/pango/PDS_2025.2-ads'))
    parser.add_argument('--action', choices=['status', 'probe', 'off', 'read', 'pulse'], default='status')
    parser.add_argument('--frequency', type=int, choices=[50, 60], default=50,
                        help='PWM frequency selected by probe; pulse uses the actual prescale readback')
    parser.add_argument('--register', type=lambda value: int(value, 0))
    parser.add_argument('--channel', type=int, choices=range(16))
    parser.add_argument('--us', type=int, choices=range(1200, 2587), metavar='1200..2586')
    args = parser.parse_args()
    if args.action == 'pulse' and (args.channel is None or args.us is None):
        parser.error('pulse requires explicit --channel and --us')
    if args.action == 'read' and (args.register is None or args.register not in [*range(70), 254]):
        parser.error('read requires --register 0..0x45 or 0xfe')
    folder = ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_bench')
    folder.mkdir(parents=True)
    report = dict(action=args.action, channel=args.channel, microseconds=args.us,
                  started_at=dt.datetime.now().astimezone().isoformat(), events=[], success=False)
    shell = None
    try:
        shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe', folder)
        bench = PcaBench(shell, report['events'])
        if args.action == 'status':
            result = bench.sample()
        elif args.action == 'probe':
            result = bench.probe(args.frequency)
        elif args.action == 'off':
            result = bench.command(1)
        elif args.action == 'read':
            result = dict(register=args.register, value=bench.read(args.register))
        else:
            result = bench.pulse(args.channel, args.us)
        report['result'] = result
        report['success'] = True
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or 'KeyboardInterrupt'
        print(f'FAILED: {report["error"]}', file=sys.stderr)
    finally:
        if shell:
            shell.close()
        report['ended_at'] = dt.datetime.now().astimezone().isoformat()
        (folder/'session.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(f'Log: {folder/"session.json"}')
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
