"""Read integration diagnostics over JTAG; reset only with --reset-stopped."""
import json
from pathlib import Path
import sys
import time
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reset-stopped',action='store_true',help='Reset only when actuator all-off is confirmed')
parser.add_argument('--output-dir', type=Path, help='Save diagnostics in this directory')
args=parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'camera/tools'))
from jtag_shell import Debugger
from jtag_test import dvio_json, port_value
out = args.output_dir or ROOT / 'runs' / time.strftime('%Y%m%d-%H%M%S-jtag')
out.mkdir(parents=True, exist_ok=True)
shell = Debugger('C:/pango/PDS_2025.2-ads/bin/cdt_dbg_shell.exe', out)
try:
    shell.command('dbg_connect -ip 127.0.0.1 -port 65420', timeout=60)
    shell.command('dbg_scan_chain', timeout=40)
    raw = dvio_json(shell.command('dbg_dvio_refresh -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0'))
    value = port_value(raw['probe_ins'][0])
    assert value >> 48 == 0x4b54, f'Wrong firmware: {value:016x}'
    if args.reset_stopped:
        if value >> 40 & 255 < 2 or value & ((1<<4)|(1<<6)):
            rejected = dict(raw=f'{value:016x}', firmware_version=value >> 40 & 255,
                drive_active=bool(value & (1<<4)), shutdown_unconfirmed=bool(value & (1<<6)),
                drive_diagnostics=f"{port_value(raw['probe_ins'][1]):016x}", reset_performed=False)
            (out / 'rejected-reset.json').write_text(json.dumps(rejected, indent=2) + '\n')
            raise RuntimeError('Reset requires v2 diagnostic firmware and confirmed inactive outputs')
        shell.command('dbg_dvio_set_output -device 1 -dvio 0 -channel {ProbeOut0[0]} -value 1\ndbg_dvio_commit_output -device 1 -dvio 0')
        time.sleep(.1)
        shell.command('dbg_dvio_set_output -device 1 -dvio 0 -channel {ProbeOut0[0]} -value 0\ndbg_dvio_commit_output -device 1 -dvio 0')
        time.sleep(2)
        raw=dvio_json(shell.command('dbg_dvio_refresh_input -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0'))
        value=port_value(raw['probe_ins'][0])
    fields = 'command_valid control_stop drive_ready drive_fault drive_active drive_armed shutdown_unconfirmed camera_ready camera_failed capture_fault transport_fault s_rvalid s_bvalid s_arready s_wready s_awready'.split()
    result = {name: bool(value >> n & 1) for n, name in enumerate(fields)}
    result.update(raw=f'{value:016x}', firmware_version=value >> 40 & 255,
                  pu_resetn=bool(value >> 32 & 1), bus_state=value >> 29 & 7, transport_state=value >> 23 & 63,
                  drive_diagnostics=f"{port_value(raw['probe_ins'][1]):016x}")
    drive = port_value(raw['probe_ins'][1])
    result.update(first_i2c_failure=f'{drive >> 48:04x}', live_i2c=f'{(drive >> 32) & 65535:04x}',
                  esc_ticks=(drive >> 20) & 4095, steering_ticks=(drive >> 8) & 4095)
    if len(raw['probe_ins'])>2:
        bus=port_value(raw['probe_ins'][2])
        result.update(awaddr=f'{bus>>32:08x}',araddr=f'{bus&0xffffffff:08x}',bresp=value>>21&3,rresp=value>>19&3)
    (out / 'status.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f'Evidence: {out}', flush=True)
    if args.reset_stopped and (not result['drive_ready'] or not result['camera_ready'] or
            any(result[k] for k in ('drive_fault','shutdown_unconfirmed','camera_failed','capture_fault','transport_fault'))):
        raise RuntimeError('Board initialization still faulted; see status.json and debugger.log')
finally:
    shell.close()
