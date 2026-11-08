"""Bounded network bench test: neutral, steering, optional historical low PWM drive.

Use only after wheels-off-ground and power have been confirmed. Never records
training data. Any request error aborts the profile and attempts a disabled stop.
"""
import argparse
import datetime
import http.client
import json
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'tools'))
from board_connection import board_host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory-password', action='store_true')
    parser.add_argument('--include-low-drive', action='store_true')
    parser.add_argument('--restart-check', action='store_true', help='Add normal stop and small steering restart; no extra forward drive')
    parser.add_argument('--simulate', action='store_true', help='Use localhost:18080 simulator')
    parser.add_argument('--host', type=board_host)
    args = parser.parse_args()
    host, port = ('127.0.0.1', 18080) if args.simulate else (board_host(args.host), 8080)
    folder = ROOT / 'runs' / (time.strftime('%Y%m%d-%H%M%S') + '-bounded-drive')
    folder.mkdir(parents=True)
    client = 'bounded-bench-' + secrets.token_hex(8)
    # A new NAT TCP connection can take longer than a control heartbeat.
    # Establish it read-only, then enforce the short timeout while driving.
    connection = http.client.HTTPConnection(host, port, timeout=5)
    sequence = 0
    samples = []
    summary = {'simulation': args.simulate, 'low_drive_requested': args.include_low_drive,
               'profile_completed': False, 'stop_confirmed': False, 'physical_observation': 'pending'}

    def api(path, payload=None):
        connection.request('GET' if payload is None else 'POST', path,
                           body=None if payload is None else json.dumps(payload),
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f'HTTP {response.status}: {body.decode(errors="replace")}')
        return json.loads(body)

    def command(enabled, angle=0, throttle=0):
        nonlocal sequence
        sequence += 1
        return api('/api/drive', dict(client=client, sequence=sequence, gesture=1,
                                     enable=enabled, angle=angle, throttle=throttle))

    def observe(stage):
        status = api('/api/status')
        sample = {'time': datetime.datetime.now().astimezone().isoformat(), 'stage': stage, 'status': status}
        samples.append(sample)
        if status['fault']:
            raise RuntimeError(status['fault'])
        return status

    attempted_enable = False
    error = None
    try:
        initial = observe('preflight')
        connection.timeout = .25
        connection.sock.settimeout(.25)
        expected = 'simulation' if args.simulate else 'pa-uio-ktr1'
        if initial['backend'] != expected or initial['enabled'] or initial['record_open']:
            raise RuntimeError('Wrong backend or active driving/recording session')
        health = initial.get('controller', {})
        if health and (not health['ready'] or not health['armed'] or health['shutdown_unconfirmed'] or health['fault']):
            raise RuntimeError('Controller must be healthy and in neutral standby')
        if not 0 <= initial['frame_age_ms'] < 500:
            raise RuntimeError('Fresh video required')
        stages = [('neutral', .25, 0, 0), ('left', 1.0, -.5, 0),
                  ('right', 1.0, .5, 0), ('center', .5, 0, 0)]
        if args.include_low_drive:
            # v5 maps 0.43 to the previous 406-tick low endpoint. Full-scale
            # now reaches 441 ticks and must not silently replace this test.
            stages.append(('historical-low-pwm', .5, 0, .43))
        if args.restart_check:
            stages.extend([('normal-stop', .3, 0, 0), ('fine-restart-left', .5, -.05, 0),
                           ('normal-stop-2', .3, 0, 0), ('fine-restart-right', .5, .05, 0)])
        print(f'Bounded profile starting. Evidence: {folder}', flush=True)
        for stage, duration, angle, throttle in stages:
            if stage != 'neutral' and not args.simulate:
                if not observe('before-' + stage).get('controller', {}).get('armed'):
                    raise RuntimeError('Controller did not remain armed')
            print(f'{stage}: {duration}s angle={angle} throttle={throttle}', flush=True)
            end = time.monotonic() + duration
            while time.monotonic() < end:
                tick = time.monotonic()
                attempted_enable = True
                command(not stage.startswith('normal-stop'), angle, throttle)
                observe(stage)
                time.sleep(max(0, .05 - (time.monotonic() - tick)))
        summary['profile_completed'] = True
    except Exception as exc:
        error = exc
        summary['error'] = str(exc)
    finally:
        # Stop first, including after an ambiguous request failure. Never retry
        # enabled commands after a timeout or silently resume an interrupted stage.
        if error is not None:
            connection.close()
            connection = http.client.HTTPConnection(host, port, timeout=2)
        if attempted_enable:
            try:
                command(False)
            except Exception as exc:
                summary['stop_request_error'] = str(exc)
                connection.close()
                connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            end = time.monotonic() + 4
            while time.monotonic() < end:
                state = observe('stopping')
                health = state.get('controller', {})
                if (not state['enabled'] and not health.get('shutdown_unconfirmed')
                        and state['frame']['flags'] == 0 and state['frame']['user/throttle'] == 0):
                    summary['stop_confirmed'] = True
                    break
                time.sleep(.1)
        except Exception as exc:
            summary['stop_observation_error'] = str(exc)
        connection.close()
        with (folder / 'samples.jsonl').open('w', encoding='utf-8') as out:
            for sample in samples:
                out.write(json.dumps(sample, ensure_ascii=False) + '\n')
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary, indent=2), flush=True)
    if error is not None:
        raise error
    if not summary['stop_confirmed']:
        raise RuntimeError('Stopped state was not confirmed')


if __name__ == '__main__':
    main()
