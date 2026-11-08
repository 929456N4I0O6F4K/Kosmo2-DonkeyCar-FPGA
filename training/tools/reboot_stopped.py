"""Reboot PU for PA reconfiguration, only after the collector and PWM are off."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'tools'))
from pu_ssh import connect, BOARD_HOST
from board_connection import board_host
from board_link import run, collector_process_script


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory-password', action='store_true')
    parser.add_argument('--host', type=board_host, default=BOARD_HOST)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    password = os.environ.get('KOSMO_SSH_PASSWORD') or ('root' if args.factory_password else getpass.getpass('PU SSH password: '))
    folder = args.output_dir or ROOT / 'runs' / (time.strftime('%Y%m%d-%H%M%S') + '-stopped-reboot')
    folder.mkdir(parents=True)
    with connect(password, host=args.host) as client:
        run(client, collector_process_script())
        name = run(client, 'cat /sys/class/uio/uio0/name').strip()
        magic = int(run(client, 'devmem 0x00300000 32').strip(), 0)
        health = int(run(client, 'devmem 0x00300034 32').strip(), 0)
        if name != 'pu-pa-ddr' or magic != 0x3152544b or health & (4 | 16):
            raise RuntimeError(f'Refusing reboot: unexpected board or PWM not confirmed off ({health:#x})')
        boot_id = run(client, 'cat /proc/sys/kernel/random/boot_id').strip()
        evidence = {'previous_boot_id': boot_id, 'controller_health': health,
                    'collector_stopped': True, 'outputs_confirmed_off': True}
        (folder / 'before.json').write_text(json.dumps(evidence, indent=2) + '\n')
        run(client, 'sync')
        client.exec_command('/sbin/reboot', timeout=5)
        print(f'Reboot requested from a confirmed stopped state. Evidence: {folder}', flush=True)


if __name__ == '__main__':
    main()
