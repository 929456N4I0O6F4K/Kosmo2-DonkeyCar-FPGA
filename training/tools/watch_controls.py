"""Read-only HTTP observation of user-operated controls; never sends a command."""
import argparse
import datetime
import http.client
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'tools'))
from board_connection import board_host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--factory-password', action='store_true')
    parser.add_argument('--host', type=board_host)
    args = parser.parse_args()
    host = board_host(args.host)
    if not 1 <= args.seconds <= 120:
        parser.error('seconds must be 1..120')
    folder = ROOT / 'runs' / (time.strftime('%Y%m%d-%H%M%S') + '-control-observation')
    folder.mkdir(parents=True)
    print(f'Read-only observation started: {args.seconds}s. Evidence: {folder}', flush=True)
    connection = http.client.HTTPConnection(host, 8080, timeout=2)
    deadline = time.monotonic() + args.seconds
    previous = None
    try:
        with (folder / 'samples.jsonl').open('w', encoding='utf-8') as out:
            while time.monotonic() < deadline:
                sample = {'time': datetime.datetime.now().astimezone().isoformat()}
                try:
                    connection.request('GET', '/api/status')
                    response = connection.getresponse()
                    payload = response.read()
                    if response.status != 200:
                        raise RuntimeError(f'HTTP {response.status}')
                    sample['status'] = json.loads(payload)
                    status = sample['status']
                    changed = (status['enabled'], status.get('controller'), status['fault'])
                    if changed != previous:
                        print(json.dumps(sample, ensure_ascii=False), flush=True)
                        previous = changed
                except (OSError, http.client.HTTPException, ValueError, RuntimeError) as error:
                    sample['error'] = str(error)
                    print('Observation connection error: ' + str(error), flush=True)
                    connection.close()
                    connection = http.client.HTTPConnection(host, 8080, timeout=2)
                out.write(json.dumps(sample, ensure_ascii=False) + '\n')
                out.flush()
                time.sleep(.1)
    finally:
        connection.close()
    print('Observation complete; no drive commands were sent.', flush=True)


if __name__ == '__main__':
    main()
