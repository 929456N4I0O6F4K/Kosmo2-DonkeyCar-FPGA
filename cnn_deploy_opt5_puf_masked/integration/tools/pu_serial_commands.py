"""Run a reviewed JSON list of named shell commands through the PU console.

Each command is logged with its completion marker. Does not use SSH.
Input: [["name", "single-line shell command"], ...].
"""
import argparse
import datetime
import json
from pathlib import Path

import serial
import pu_serial_probe as probe


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--commands',type=Path,required=True)
    parser.add_argument('--keep-going',action='store_true',help='Run remaining diagnostic commands after a nonzero exit')
    args=parser.parse_args()
    commands=json.loads(args.commands.read_text(encoding='utf-8'))
    for name,command in commands:
        if not name or not command or '\n' in command or '\r' in command:
            raise ValueError('Expected named, single-line commands')
        command.encode('ascii')
    folder=Path(__file__).resolve().parents[1]/'runs'/datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f_serial_commands')
    folder.mkdir(parents=True)
    probe.COMMANDS=commands
    port=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=3)
    port.dtr=port.rts=False
    port.port=args.port
    with port:
        probe.survey(port,folder,stop_on_error=not args.keep_going)
    report=json.loads((folder/'probe.json').read_text(encoding='utf-8'))
    print('Evidence:',folder)
    if any(c['exit_code'] for c in report['commands']):
        raise SystemExit(1)


if __name__=='__main__':
    main()
