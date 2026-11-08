"""Deploy/read the real UIO collector. Never sends an enabled drive command.

Uses the previously verified SSH host key. Password: KOSMO_SSH_PASSWORD or
interactive prompt. --factory-password explicitly selects the documented
vendor root password. Files are confined to /root/kosmo-training.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'tools'))
from pu_ssh import connect, BOARD_HOST

REMOTE = '/root/kosmo-training'

def run(client, command):
    _, out, err = client.exec_command(command, timeout=20)
    result = out.read().decode()
    errors = err.read().decode()
    code = out.channel.recv_exit_status()
    if code:
        raise RuntimeError(f'Remote command exited {code}: ' + result + errors)
    return result


def wait_collector_log(client, timeout=15):
    # SSH can return before the background process is scheduled. An empty log
    # after a fixed sleep is not evidence that startup failed. The collector's
    # first log line reports either HTTP startup or its actual startup error.
    deadline = time.monotonic() + timeout
    while True:
        log = run(client, f'cat {REMOTE}/collector.log')
        if log.strip() or time.monotonic() >= deadline:
            return log
        time.sleep(.25)


def collector_process_script(stop=False):
    # A persisted PID can belong to an unrelated process after a board reboot.
    # Enumerate actual executable links; never signal from the PID-file alone.
    action = '''kill -TERM "$collector_pid" || exit 5
for n in 1 2 3 4 5; do
current_exe=$(readlink "$collector_proc/exe" 2>/dev/null)
[ "$current_exe" != "$collector_exe" ] && break
sleep 1
done
current_exe=$(readlink "$collector_proc/exe" 2>/dev/null)
[ "$current_exe" != "$collector_exe" ] || exit 6''' if stop else '''echo "Collector is still running: $collector_pid" >&2
exit 4'''
    return f'''for collector_proc in /proc/[0-9]*; do
collector_exe=$(readlink "$collector_proc/exe" 2>/dev/null) || continue
case "$collector_exe" in
"{REMOTE}/kosmo-collect"|"{REMOTE}/kosmo-collect (deleted)")
collector_pid=${{collector_proc##*/}}
{action}
;;
esac
done'''

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['check-isolated', 'prepare-link', 'deploy', 'status', 'stop', 'verify'])
    p.add_argument('--host', default=BOARD_HOST)
    p.add_argument('--factory-password', action='store_true')
    p.add_argument('--frames', type=int, default=100)
    p.add_argument('--output-dir', type=Path, help='Save deployment/verification evidence here')
    args = p.parse_args()
    print(f'Connecting to {args.host} for {args.action}', flush=True)
    password = os.environ.get('KOSMO_SSH_PASSWORD') or ('root' if args.factory_password else getpass.getpass('PU SSH password: '))
    out = args.output_dir or ROOT / 'runs' / time.strftime('%Y%m%d-%H%M%S-network')
    out.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            client = connect(password, host=args.host)
            break
        except TimeoutError:
            if attempt == 2: raise
            print('SSH connection timed out; retrying...', flush=True)
    with client:
        if args.action in ('check-isolated', 'prepare-link'):
            # PG2K100 BSP pg_clk.c pg_level_shifter_set and pg_fsbl_hw.h:
            # PG_ISO_CTRL=0xe5006198: FSBL uses 0xb while configuring PA,
            # then 0xf AFTER configuration. This Linux image cold-boots with 0.
            # Keep existing isolation; do not cut an active AXI transaction.
            # Runtime only; does not reset Linux, DDR, clocks or boot storage.
            name = run(client, 'cat /sys/class/uio/uio0/name').strip()
            address = int(run(client, 'cat /sys/class/uio/uio0/maps/map0/addr').strip(), 0)
            if name != 'pu-pa-ddr' or address != 0x00300000:
                raise RuntimeError('Unexpected board UIO layout')
            before = int(run(client, 'devmem 0xe5006198 32').strip(), 0)
            if before not in (0, 11, 15):
                raise RuntimeError(f'Unexpected isolation register: {before:#x}')
            if args.action == 'check-isolated' and before == 15:
                # The current transport polls continuously. Live reconfiguration
                # needs a future bus-quiesce handshake, not just daemon shutdown.
                raise RuntimeError('PU/PA link is already enabled. Use start_board.ps1 for a stopped '
                                   'reboot and full deployment, or -NoProgram to restart without programming.')
            target = before if args.action == 'check-isolated' else 15
            if before != target:
                run(client, f'devmem 0xe5006198 32 {target:#010x}')
            after = int(run(client, 'devmem 0xe5006198 32').strip(), 0)
            evidence = dict(action=args.action, register='0xe5006198', before=before, after=after)
            (out / 'link-setup.json').write_text(json.dumps(evidence, indent=2))
            if after != target:
                raise RuntimeError('PU/PA isolation register readback mismatch')
            print('PA-to-PU isolation confirmed; load the bitstream next.' if args.action == 'check-isolated' else
                  'PU/PA link enabled after configuration; initialize the stopped core next.')
            return
        if args.action in ('deploy', 'stop'):
            print(run(client, collector_process_script(stop=True)))
            run(client, f'if [ -f {REMOTE}/collector.pid ]; then rm -f {REMOTE}/collector.pid; fi')
        if args.action == 'deploy':
            binary = ROOT / 'bin/kosmo-collect-linux-arm64'
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            run(client, f'mkdir -p {REMOTE}/data; chmod 700 {REMOTE}')
            # This image has no persistent RTC; retain meaningful session dates.
            clock_before = run(client, 'date -u').strip()
            utc = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            clock_after = run(client, 'date -u -s ' + shlex.quote(utc)).strip()
            (out / 'clock.json').write_text(json.dumps(dict(before=clock_before, after=clock_after), indent=2))
            with client.open_sftp() as sftp:
                sftp.put(str(binary), REMOTE + '/kosmo-collect.new')
            actual = run(client, f'sha256sum {REMOTE}/kosmo-collect.new').split()[0]
            if actual != digest:
                raise RuntimeError('Uploaded binary hash mismatch')
            # This only starts disabled. Driving requires fresh browser input.
            run(client, f'''chmod 700 {REMOTE}/kosmo-collect.new
mv {REMOTE}/kosmo-collect.new {REMOTE}/kosmo-collect
cd {REMOTE}
nohup ./kosmo-collect -backend uio -listen 0.0.0.0:8080 -data {REMOTE}/data -max-throttle 1 > collector.log 2>&1 < /dev/null &
echo $! > collector.pid''')
            log = wait_collector_log(client)
            print(log)
            (out / 'collector.log').write_text(log)
            if 'backend=pa-uio-ktr1;' not in log:
                raise RuntimeError('Real collector did not start; see collector.log')
            (out / 'binary.sha256').write_text(digest + '\n')
        elif args.action == 'stop':
            print('Collector stopped; hardware watchdog remains independent.')
            return
        base = f'http://{args.host}:8080'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            return opener.open(urllib.request.Request(base + path, data=data,
                headers={'Content-Type': 'application/json'}), timeout=4)
        with request('/api/status') as response:
            before = json.load(response)
        print(json.dumps(before, ensure_ascii=False, indent=2))
        (out / 'status.json').write_text(json.dumps(before, indent=2))
        if args.action == 'verify':
            if not 2 <= args.frames <= 1000:
                raise ValueError('frames must be 2..1000')
            # Refuse to interfere with an active driving/recording session.
            if before['enabled'] or before['record_open']:
                raise RuntimeError('Active session; finish driving/recording first')
            started = time.monotonic()
            with request('/api/drive', dict(client='network-verification', sequence=time.time_ns(), enable=False, angle=0, throttle=0)) as response:
                assert json.load(response)['accepted']
            request_ms = (time.monotonic() - started) * 1000
            with request('/video.mjpg') as response:
                times, sequences = [], []
                while len(sequences) < args.frames:
                    line = response.readline()
                    if not line:
                        raise EOFError('Video stream ended')
                    if line.strip() != b'--frame':
                        continue
                    headers = {}
                    while True:
                        line = response.readline()
                        if line == b'\r\n': break
                        k, v = line.decode().split(':', 1)
                        headers[k.lower()] = v.strip()
                    frame = response.read(int(headers['content-length']))
                    assert frame[:2] == b'\xff\xd8' and frame[-2:] == b'\xff\xd9'
                    seq = int(headers['x-frame-sequence'])
                    assert not sequences or seq > sequences[-1]
                    sequences.append(seq); times.append(time.monotonic())
                    if len(sequences) in (1, args.frames):
                        (out / f'frame-{seq}.jpg').write_bytes(frame)
            with request('/api/status') as response:
                after = json.load(response)
            assert after['command_ack'] > before['command_ack']
            assert not after['fault'] and not after['enabled']
            assert after['frame']['flags'] == 0
            evidence = dict(frames=len(sequences), fps=(len(times)-1)/(times[-1]-times[0]),
                first_sequence=sequences[0], last_sequence=sequences[-1], disabled_http_request_ms=request_ms,
                status_before=before, status_after=after, physical_actuation_tested=False)
            (out / 'verification.json').write_text(json.dumps(evidence, indent=2))
            print(json.dumps(evidence, indent=2))
        print(f'Open {base}/')
        print(f'Evidence: {out}')

if __name__ == '__main__':
    main()
