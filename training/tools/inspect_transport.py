"""Read-only SSH snapshot of the fixed KTR1 DDR mailbox and collector log."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'tools'))
from pu_ssh import connect
from board_link import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory-password', action='store_true')
    args = parser.parse_args()
    password = os.environ.get('KOSMO_SSH_PASSWORD') or (
        'root' if args.factory_password else getpass.getpass('PU SSH password: '))
    folder = ROOT / 'runs' / time.strftime('%Y%m%d-%H%M%S-transport-inspection')
    folder.mkdir(parents=True, exist_ok=True)
    with connect(password) as client:
        name = run(client, 'cat /sys/class/uio/uio0/name').strip()
        address = int(run(client, 'cat /sys/class/uio/uio0/maps/map0/addr').strip(), 0)
        if name != 'pu-pa-ddr' or address != 0x00300000:
            raise RuntimeError('Unexpected board UIO layout')
        offsets = {'magic': 0, 'abi': 4, 'command': 0x10, 'flags': 0x14,
                   'angle': 0x18, 'throttle': 0x1c, 'ttl': 0x20, 'ack': 0x24,
                   'ack_status': 0x28, 'consumed': 0x2c, 'published': 0x30,
                  'health': 0x34, 'steering': 0x38, 'frame_sequence': 0x40,
                  'exposure_request': 0x80, 'exposure_setting': 0x84,
                  'exposure_ack': 0x88, 'exposure_status': 0x8c, 'exposure_applied': 0x90}
        commands = ['cat /proc/uptime', 'devmem 0xe5006198 32']
        commands += [f'devmem {address + off:#010x} 32' for off in offsets.values()]
        values = run(client, '\n'.join(commands)).strip().splitlines()
        if len(values) != len(commands):
            raise RuntimeError('Incomplete register snapshot')
        result = {'uptime': values[0], 'isolation': values[1],
                  'registers': dict(zip(offsets, values[2:])),
                  'collector_log': run(client, 'if [ -f /root/kosmo-training/collector.log ]; then tail -n 12 /root/kosmo-training/collector.log; fi'),
                  'readonly': True, 'snapshot_atomic': False}
    (folder / 'status.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    print(f'Evidence: {folder}')


if __name__ == '__main__':
    main()
