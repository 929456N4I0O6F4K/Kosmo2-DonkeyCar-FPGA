"""Idle-only steering persistence check; never enables driving or records data.

Run prepare, restart the collector, then verify-restore with the same output dir.
Original settings are saved before the test write and restored after validation.
"""
import argparse
import json
from pathlib import Path
import urllib.request

from deploy_board import check_ready
from board_connection import board_host, board_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'verify-restore'])
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--host', type=board_host)
    args = parser.parse_args()
    url = board_url(board_host(args.host))
    folder = args.output_dir
    folder.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, body=None):
        request = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=5) as response:
            result = json.load(response)
        if not check_ready(result):
            raise RuntimeError('Healthy neutral standby required for settings verification')
        return result

    def settings(status):
        return {k: status['steering'][k] for k in ['left_percent', 'right_percent']}

    if args.phase == 'prepare':
        before = api('api/status')
        if (folder / 'before.json').exists():
            raise RuntimeError('Previous original settings exist; use a new directory or finish restoration')
        original = settings(before)
        target = {'left_percent': 125, 'right_percent': 90}
        if target == original:
            target = {'left_percent': 115, 'right_percent': 120}
        (folder / 'before.json').write_text(json.dumps({'original': original, 'target': target, 'status': before}, indent=2))
        after = api('api/steering', target)
        if settings(after) != target:
            raise RuntimeError('Settings were not applied')
        (folder / 'prepared.json').write_text(json.dumps(after, indent=2))
        print('Saved independent endpoints in neutral. Restart collector, then run verify-restore.')
    else:
        saved = json.loads((folder / 'before.json').read_text())
        current = api('api/status')
        if settings(current) != saved['target']:
            raise RuntimeError('Saved settings changed or did not survive restart; refusing to overwrite')
        restored = api('api/steering', saved['original'])
        if settings(restored) != saved['original']:
            raise RuntimeError('Original steering settings not restored')
        result = {'success': True, 'after_restart': current, 'restored': restored, 'nonzero_drive_commands_sent': False}
        (folder / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
        print('Persistence verified; original steering settings restored. Evidence:', folder)


if __name__ == '__main__':
    main()
