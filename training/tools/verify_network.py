"""Verify real video and zero-input control over HTTP, without board SSH.

Never sends nonzero steering/throttle or records data. Refuses active sessions.
Optional lease check enables zero input, then lets the input heartbeat expire.
"""
import argparse
import concurrent.futures
import datetime
import http.client
import json
import math
from pathlib import Path
import time
import uuid


def healthy(state):
    controller = state['controller']
    assert state['backend'] == 'pa-uio-ktr1'
    assert not state['fault'] and not state['record_open'], state
    assert controller['ready'] and controller['armed'], controller
    assert not controller['fault'] and not controller['shutdown_unconfirmed'], controller
    assert 0 <= state['frame_age_ms'] < 500, state
    assert state['frame']['user/angle'] == 0 and state['frame']['user/throttle'] == 0, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--seconds', type=int, default=60, choices=range(5, 301))
    parser.add_argument('--lease-check', action='store_true')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = dict(time=datetime.datetime.now().astimezone().isoformat(), host=args.host,
                  success=False, nonzero_input_sent=False, physical_motion_tested=False)
    conn = http.client.HTTPConnection(args.host, args.port, timeout=3)
    client = 'network-check-' + uuid.uuid4().hex
    sequence = 0
    attempted_control = False

    def api(path, body=None, expected=200):
        conn.request('GET' if body is None else 'POST', path,
                     body=None if body is None else json.dumps(body),
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        assert response.status == expected, (response.status, data)
        return json.loads(data) if expected == 200 else {'error': data.decode().strip()}

    def command(enable=False, gesture=1, expected=200):
        nonlocal sequence, attempted_control
        sequence += 1
        attempted_control = True
        return api('/api/drive', dict(client=client, sequence=sequence, gesture=gesture,
                   enable=enable, angle=0, throttle=0), expected)

    def video():
        stream = http.client.HTTPConnection(args.host, args.port, timeout=3)
        stamps, seqs, sizes = [], [], []
        try:
            stream.request('GET', '/video.mjpg')
            response = stream.getresponse()
            assert response.status == 200
            deadline = time.monotonic() + args.seconds
            last_frame = None
            while time.monotonic() < deadline:
                line = response.readline()
                if not line:
                    raise EOFError('Video stream ended')
                if line.strip() != b'--frame':
                    continue
                headers = {}
                while True:
                    line = response.readline()
                    if line == b'\r\n':
                        break
                    key, value = line.decode().split(':', 1)
                    headers[key.lower()] = value.strip()
                size = int(headers['content-length'])
                assert 0 < size < 1024 * 1024
                frame = response.read(size)
                assert len(frame) == size and frame[:2] == b'\xff\xd8' and frame[-2:] == b'\xff\xd9'
                seq = int(headers['x-frame-sequence'])
                assert not seqs or seq > seqs[-1]
                stamps.append(time.monotonic()); seqs.append(seq); sizes.append(size)
                if len(seqs) == 1:
                    (args.output_dir / 'first.jpg').write_bytes(frame)
                last_frame = frame
            assert len(seqs) >= 10
            (args.output_dir / 'last.jpg').write_bytes(last_frame)
            return dict(frames=len(seqs), fps=(len(seqs)-1)/(stamps[-1]-stamps[0]),
                        first_sequence=seqs[0], last_sequence=seqs[-1], jpeg_bytes=sum(sizes),
                        max_frame_gap_ms=max(b-a for a,b in zip(stamps,stamps[1:]))*1000)
        finally:
            stream.close()

    try:
        initial = api('/api/status')
        report['initial'] = initial
        assert not initial['enabled'], 'Finish the active driving session first'
        healthy(initial)
        latencies, samples = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(video)
            deadline = time.monotonic() + args.seconds
            tick = time.monotonic()
            while time.monotonic() < deadline:
                started = time.monotonic()
                assert command()['accepted']
                latencies.append((time.monotonic()-started)*1000)
                if len(latencies) % 5 == 0:
                    state = api('/api/status')
                    healthy(state)
                    assert not state['enabled'] and state['frame']['flags'] == 0
                    samples.append(state)
                if future.done():
                    future.result()
                tick = max(tick + .05, time.monotonic())
                time.sleep(max(0, tick-time.monotonic()))
            report['video'] = future.result()
        ordered = sorted(latencies)
        report['control'] = dict(requests=len(ordered), status_samples=len(samples),
                               median_ms=ordered[len(ordered)//2],
                               p95_ms=ordered[math.ceil(len(ordered)*.95)-1], max_ms=max(ordered))
        (args.output_dir / 'status-samples.json').write_text(json.dumps(samples, indent=2))
        if args.lease_check:
            for _ in range(12):
                assert command(True)['accepted']
                time.sleep(.05)
            enabled = api('/api/status')
            healthy(enabled)
            assert enabled['enabled'] and enabled['frame']['flags'] & 1
            # No heartbeat: only zero values have been sent. This checks the PU
            # input lease, not physical braking or the independent PA watchdog.
            time.sleep(.75)
            expired = api('/api/status')
            healthy(expired)
            assert not expired['enabled'] and expired['frame']['flags'] == 0
            stale = command(True, expected=409)
            assert 'timed out' in stale.get('error', ''), stale
            assert command(True, gesture=2)['accepted']
            assert command(False, gesture=2)['accepted']
            # Camera metadata describes capture time and can still belong to a
            # frame captured before the stop. Observe new frames, with a bound.
            stop_sent = time.monotonic()
            report['stop_samples'] = []
            while True:
                stopped = api('/api/status')
                healthy(stopped)
                report['stop_samples'].append(stopped)
                if not stopped['enabled'] and stopped['frame']['flags'] == 0:
                    break
                assert time.monotonic()-stop_sent < 1, ('Stop not confirmed', stopped)
                time.sleep(.05)
            report['lease'] = dict(enabled=enabled, expired=expired, stale_gesture_rejected=True,
                                   fresh_gesture_accepted=True, zero_input_only=True,
                                   stop_metadata_observed_ms=(time.monotonic()-stop_sent)*1000)
        final = api('/api/status')
        healthy(final)
        assert not final['enabled'] and final['frame']['flags'] == 0, final
        assert final['command_ack'] > initial['command_ack']
        report['final'] = final
        report['success'] = True
    except BaseException as exc:
        report['error'] = str(exc) or repr(exc)
        raise
    finally:
        if attempted_control:
            try:
                conn.close()
                conn = http.client.HTTPConnection(args.host, args.port, timeout=3)
                report['final_stop_accepted'] = command()['accepted']
            except Exception as exc:
                report['final_stop_error'] = str(exc)
                report['success'] = False
        conn.close()
        (args.output_dir / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('initial','final','lease')}, indent=2))
    assert report['success']


if __name__ == '__main__':
    main()
