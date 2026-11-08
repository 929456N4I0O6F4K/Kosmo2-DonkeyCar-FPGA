"""Select a persistent multimeter test state via PA JTAG and read digital levels."""
import argparse
import datetime as dt
import json
import time
from pathlib import Path
from jtag_shell import Debugger
from jtag_test import dvio_json, port_value

ROOT = Path(__file__).resolve().parents[1]
MODES = {'idle':0, 'reset':1, 'scl-low':2, 'sda-low':3, 'both-low':4}


def decode(value):
    if value >> 48 != 0x4d54 or value >> 40 & 255 != 1:
        raise ValueError('Load camera_meter_top.sbit first; unexpected meter firmware signature')
    mode = value >> 32 & 255
    return dict(raw_hex=f'{value:016x}', mode=next((n for n,v in MODES.items() if v==mode),str(mode)),
                token=value >> 24 & 255, internal_pullups=bool(value & 65536), command_error=bool(value & 128),
                reset_n_output=value >> 6 & 1, sda_drive_low=bool(value & 32),
                scl_drive_low=bool(value & 16), sda_input=value >> 3 & 1,
                scl_input=value >> 2 & 1, heartbeat=value >> 1 & 1, running=bool(value & 1))


class MeterJtag:
    def __init__(self, shell):
        self.shell = shell
        shell.command('dbg_connect -ip 127.0.0.1 -port 65420',timeout=100)
        shell.command('dbg_scan_chain',timeout=40)
        obj = dvio_json(shell.command('dbg_dvio_refresh -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0'))
        self.control = port_value(obj['probe_outs'][0])
        decode(port_value(obj['probe_ins'][0]))

    def sample(self):
        obj = dvio_json(self.shell.command('dbg_dvio_refresh_input -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0'))
        return decode(port_value(obj['probe_ins'][0]))

    def select(self, name):
        token = (self.sample()['token']+1) & 255
        value = 0x4d540000 | token << 8 | MODES[name]
        commands = [f'dbg_dvio_set_output -device 1 -dvio 0 -channel {{ProbeOut0[{bit}]}} -value {(value >> bit) & 1}'
                    for bit in range(32) if (self.control ^ value) & (1 << bit)]
        commands.append('dbg_dvio_commit_output -device 1 -dvio 0')
        self.shell.command('\n'.join(commands))
        self.control = value
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            result = self.sample()
            if result['token']==token and result['mode']==name and not result['command_error']:
                time.sleep(.25)
                return self.sample()
        raise TimeoutError(f'Meter mode {name} was not acknowledged')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pds',type=Path,default=Path('C:/pango/PDS_2025.2-ads'))
    parser.add_argument('--mode',choices=['status',*MODES],default='status')
    parser.add_argument('--self-test',action='store_true',help='Exercise all modes, then leave --mode (idle by default); not a voltage measurement')
    args = parser.parse_args()
    folder = ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_meter')
    folder.mkdir(parents=True)
    session = dict(started_at=dt.datetime.now().astimezone().isoformat(),events=[],command_ok=False)
    shell = None
    print(f'Meter session: {folder}',flush=True)
    try:
        shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe',folder)
        meter = MeterJtag(shell)
        def record(mode):
            result = meter.sample() if mode=='status' else meter.select(mode)
            session['events'].append(dict(time=dt.datetime.now().astimezone().isoformat(),**result))
            print(json.dumps(result,ensure_ascii=False),flush=True)
            return result
        if args.self_test:
            try:
                for name in ['reset','scl-low','sda-low','both-low']:
                    record(name)
            finally:
                record('idle')
                if args.mode not in ('status','idle'):
                    record(args.mode)
            session['driven_low_readback_ok'] = all(
                (not e['scl_drive_low'] or e['scl_input']==0) and
                (not e['sda_drive_low'] or e['sda_input']==0) for e in session['events'])
            session['released_lines_read_high'] = all(
                (e['scl_drive_low'] or e['scl_input']==1) and
                (e['sda_drive_low'] or e['sda_input']==1) for e in session['events'])
        else:
            if args.mode != 'status':
                record('status')
            record(args.mode)
        session['command_ok'] = True
        print('State remains selected until another command, C20 reset, or power-off. Digital levels are not voltages.',flush=True)
    except Exception as exc:
        session['error'] = str(exc)
        print(f'FAILED: {exc}',flush=True)
    finally:
        if shell:
            shell.close()
        session['ended_at'] = dt.datetime.now().astimezone().isoformat()
        (folder/'session.json').write_text(json.dumps(session,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'Result: {folder / "session.json"}',flush=True)
    return 0 if session['command_ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
