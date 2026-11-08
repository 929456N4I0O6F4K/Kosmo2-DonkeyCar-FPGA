"""Deploy the reviewed car system, including stopped reboot and video verification.

Uses checked SSH/JTAG tools over the configured Wi-Fi or Ethernet address.
Never sends an enabled drive command.
"""
import argparse
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'tools'))
from board_connection import board_host, board_url
BINARY = 'bin/kosmo-collect-linux-arm64'
BITSTREAM = 'build/board/prj_tasks/pnr_1/generate_bitstream/kosmo_training_top.sbit'
PDS = Path('C:/pango/PDS_2025.2-ads/bin')


class StepError(RuntimeError):
    def __init__(self, name, output):
        super().__init__(f'{name} failed; see its log.\n{output[-1800:]}')
        self.output = output


def check_board(state, no_program=False):
    if state['isolation'] not in (0, 11, 15):
        raise RuntimeError('Unexpected PU/PA isolation register; refusing deployment.')
    if no_program and state['isolation'] != 15:
        raise RuntimeError('No initialized PU/PA link. Run the full deployment without -NoProgram.')
    if state['isolation'] == 15 and (state['magic'] != 0x3152544b or state['abi'] not in (1, 2, 3)):
        raise RuntimeError('Link is enabled with unknown firmware. Power-cycle the board before deployment.')
    if no_program and state['abi'] != 3:
        raise RuntimeError('Exposure settings require ABI 3. Run full deployment without -NoProgram.')


def check_idle(status):
    if status and (status.get('enabled') or status.get('record_open')):
        raise RuntimeError('Driving or recording is active. Stop driving and finish recording first.')


def check_stopped(status):
    if status.get('firmware_version', 0) < 2:
        raise RuntimeError('Cannot confirm actuator state with this firmware.')
    if status['drive_active'] or status['shutdown_unconfirmed']:
        raise RuntimeError('PWM shutdown is not confirmed. Check PCA power/wiring before retrying.')


def check_ready(status):
    check_idle(status)
    health = status.get('controller', {})
    return (status.get('backend') == 'pa-uio-ktr1' and not status.get('fault')
            and health.get('ready') and health.get('armed')
            and not health.get('fault') and not health.get('shutdown_unconfirmed')
            and not health.get('stop') and 0 <= status.get('frame_age_ms', -1) < 500
            and status.get('frame', {}).get('flags') == 0
            and status['frame']['user/angle'] == 0 and status['frame']['user/throttle'] == 0)


def deploy(ops, no_program=False):
    """State transitions are separate from I/O so failure paths can be tested."""
    ops.preflight(no_program)
    state = ops.inspect()
    check_board(state, no_program)
    status = ops.status(optional=True)
    check_idle(status)
    if status is None and state.get('collector_running'):
        raise RuntimeError('Collector is running but HTTP status is unreachable; refusing to interrupt an unknown session.')
    ops.stop()
    if state['isolation'] == 15:
        check_stopped(ops.diagnostics(reset=False))
        if not no_program:
            ops.reboot_and_wait(state['boot_id'])
    if no_program:
        ops.diagnostics(reset=True)
    else:
        ops.load()
    try:
        ops.start()
    except StepError as error:
        # Only the initial disabled ACK failure has a bounded reboot recovery.
        # A service that already opened HTTP, or a hardware fault, is not retried.
        if (no_program or 'context deadline exceeded' not in error.output
                or 'backend=pa-uio-ktr1;' in error.output or 'initial exposure configuration:' in error.output):
            raise
        ops.note('Initial zero-command ACK timed out; attempting one stopped reboot recovery.')
        ops.stop()
        check_stopped(ops.diagnostics(reset=False))
        state = ops.inspect()
        check_board(state)
        ops.reboot_and_wait(state['boot_id'])
        ops.load()
        ops.start()
    ops.wait_ready()
    return ops.verify()


def deploy_software(ops):
    """Update the collector on a healthy initialized link; never resets FPGA/PU."""
    ops.preflight(no_program=True, software_only=True)
    state = ops.inspect()
    check_board(state)
    if state['isolation'] != 15 or state['abi'] not in (2, 3):
        raise RuntimeError('Software update needs an initialized ABI 2/3 link. Run full deployment.')
    status = ops.status()
    check_idle(status)
    if not check_ready(status):
        raise RuntimeError('Software update requires healthy video and confirmed neutral standby. Run full deployment to recover hardware faults.')
    ops.stop()
    ops.start()
    ops.wait_ready()
    return ops.verify()


@contextmanager
def deployment_lock(path):
    # Prevent two double-clicks from programming the same board concurrently.
    import msvcrt
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('Another one-click deployment is already running.') from error
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class Operations:
    def __init__(self, folder, frames, host=None):
        self.folder, self.frames, self.step = folder, frames, 0
        self.host = board_host(host)
        self.url = board_url(self.host)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def note(self, text):
        print(text, flush=True)

    def preflight(self, no_program, software_only=False):
        manifest = json.loads((ROOT / 'integration_validation.json').read_text(encoding='utf-8'))
        if software_only and not {2, 3}.issubset(manifest.get('supported_transport_abis', [])):
            raise RuntimeError('This collector release is not validated for ABI 2/3 software updates.')
        artifacts = [BINARY] + ([] if no_program else [BITSTREAM])
        hashes = {}
        for name in artifacts:
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            if hashes[name] != manifest['sha256'][name]:
                raise RuntimeError(f'Artifact differs from the validated release: {name}')
        for name in ([] if software_only else ['cdt_dbg_shell.exe']) + ([] if no_program else ['cdt_cfg_shell.exe']):
            if not (PDS / name).is_file():
                raise RuntimeError(f'Missing PDS tool: {PDS / name}')
        (self.folder / 'artifacts.json').write_text(json.dumps(hashes, indent=2) + '\n')
        self.note('Artifacts verified. Software update uses SSH only.' if software_only else
                  'Artifacts verified. Keep C20 in the running position.')

    def inspect(self):
        sys.path.insert(0, str(ROOT.parent / 'tools'))
        from pu_ssh import connect
        from board_link import run
        password = os.environ.get('KOSMO_SSH_PASSWORD') or 'root'
        for attempt in range(3):
            try:
                client = connect(password, host=self.host)
                break
            except (TimeoutError, ConnectionError, OSError):
                if attempt == 2:
                    raise
                self.note(f'Waiting for board SSH at {self.host}...')
                time.sleep(2)
        with client:
            name = run(client, 'cat /sys/class/uio/uio0/name').strip()
            address = int(run(client, 'cat /sys/class/uio/uio0/maps/map0/addr').strip(), 0)
            if name != 'pu-pa-ddr' or address != 0x00300000:
                raise RuntimeError('Unexpected UIO layout; refusing deployment.')
            isolation = int(run(client, 'devmem 0xe5006198 32').strip(), 0)
            state = {'isolation': isolation, 'boot_id': run(client, 'cat /proc/sys/kernel/random/boot_id').strip(),
                     'host': self.host, 'kernel': run(client, 'uname -r').strip()}
            # Read actual process paths: a PID file can survive a reboot.
            processes = run(client, 'for p in /proc/[0-9]*/exe; do readlink "$p" 2>/dev/null; done; true')
            state['collector_running'] = any(line in ('/root/kosmo-training/kosmo-collect',
                '/root/kosmo-training/kosmo-collect (deleted)') for line in processes.splitlines())
            state['network'] = run(client, 'ip -4 addr; ip route').strip()
            if isolation == 15:
                state.update(magic=int(run(client, 'devmem 0x00300000 32').strip(), 0),
                             abi=int(run(client, 'devmem 0x00300004 32').strip(), 0))
        (self.folder / 'latest-board-state.json').write_text(json.dumps(state, indent=2) + '\n')
        return state

    def status(self, optional=False):
        try:
            with self.opener.open(self.url + 'api/status', timeout=4) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError):
            if optional:
                return None
            raise

    def command(self, name, argv, timeout=180):
        self.step += 1
        folder = self.folder / f'{self.step:02d}-{name}'
        folder.mkdir()
        self.note(f'[{self.step:02d}] {name} ...')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        try:
            result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                                    encoding='utf-8', errors='replace', timeout=timeout,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as error:
            output = str(error)
            (folder / 'command.log').write_text(output, encoding='utf-8')
            raise StepError(name, output) from error
        output = result.stdout + result.stderr
        (folder / 'command.log').write_text(output, encoding='utf-8')
        if result.returncode:
            if '"camera_failed": true' in output:
                self.note('Camera initialization failed. Check OV2640 power and SCCB wiring; service was not started.')
            if 'Select dvio is not valid' in output:
                self.note('Check C20 reset switch: it must remain in the running position.')
            if 'No cable was found' in output:
                self.note('Connect the board JTAG USB to this Windows / VMware guest.')
            raise StepError(name, output)
        return output

    def link(self, action, **options):
        out = self.folder / f'network-{self.step + 1:02d}-{action}'
        argv = [sys.executable, 'tools/board_link.py', action, '--host', self.host,
                '--factory-password', '--output-dir', str(out)]
        for key, value in options.items():
            argv.extend(['--' + key, str(value)])
        self.command(action, argv)
        return out

    def stop(self):
        self.link('stop')

    def diagnostics(self, reset):
        out = self.folder / f'jtag-{self.step + 1:02d}'
        argv = [sys.executable, 'tools/board_status.py', '--output-dir', str(out)]
        if reset:
            argv.append('--reset-stopped')
        self.command('initialize' if reset else 'confirm-pwm-off', argv)
        return json.loads((out / 'status.json').read_text())

    def reboot_and_wait(self, previous_boot):
        self.command('stopped-reboot', [sys.executable, 'tools/reboot_stopped.py', '--host', self.host,
                     '--factory-password', '--output-dir', str(self.folder / 'reboot')])
        self.note(f'Waiting for PU to reboot, reconnect Wi-Fi/Ethernet and restore SSH at {self.host} (up to 120 seconds)...')
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            time.sleep(3)
            try:
                state = self.inspect()
            except (TimeoutError, ConnectionError, OSError):
                continue
            if state['boot_id'] != previous_boot and state['isolation'] in (0, 11):
                return
        raise RuntimeError(f'PU reboot/isolation not confirmed at {self.host}. Check power, hotspot/network and the board IP.')

    def load(self):
        self.link('check-isolated')
        output = self.command('program-pa', [str(PDS / 'cdt_cfg_shell.exe'), '-file', str(ROOT / 'scripts/program_board.tcl')])
        if 'Finish program' not in output:
            raise StepError('program-pa', output)
        self.link('prepare-link')
        self.diagnostics(reset=True)

    def start(self):
        self.link('deploy')

    def wait_ready(self):
        self.note('Waiting for fresh video and neutral standby...')
        deadline = time.monotonic() + 25
        last_status = None
        try:
            while time.monotonic() < deadline:
                try:
                    status = self.status()
                except (urllib.error.URLError, TimeoutError, OSError):
                    time.sleep(1)
                    continue
                last_status = status
                check_idle(status)
                controller = status.get('controller', {})
                if status.get('fault'):
                    raise RuntimeError(f'Collector reports a fault: {status["fault"]}. '
                                       f'Controller fault={bool(controller.get("fault"))}; '
                                       'inspect collector.log and the saved HTTP status.')
                if controller.get('fault'):
                    raise RuntimeError('Hardware controller reports a fault; '
                                       'inspect controller health and JTAG diagnostics.')
                if check_ready(status):
                    return
                time.sleep(.5)
            raise RuntimeError('Video/neutral standby did not become ready; inspect board status.')
        except Exception:
            evidence = self.folder / 'wait-ready-failure-status.json'
            try:
                # null means no HTTP status was received, not a healthy device.
                evidence.write_text(json.dumps(last_status, indent=2) + '\n', encoding='utf-8')
                self.note(f'Last HTTP status saved: {evidence}')
            except OSError as error:
                self.note(f'Could not save last HTTP status: {error}')
            raise

    def verify(self):
        folder = self.link('verify', frames=self.frames)
        result = json.loads((folder / 'verification.json').read_text())
        if not check_ready(result['status_after']):
            raise RuntimeError('Final controller state is not healthy neutral standby.')
        before, after = result['status_before'], result['status_after']
        drops = after['frame']['source_dropped'] - before['frame']['source_dropped']
        self.note(f'Video: {result["frames"]} frames, {result["fps"]:.2f} fps; '
                  f'camera capture drops {drops:+d}; '
                  f'control ACK {before["command_ack"]} -> {after["command_ack"]}.')
        if drops > 0:
            self.note('Camera capture drops detected. Check camera connection and frame diagnostics; '
                      'READY confirms startup, not stable capture.')
        result['evidence'] = str(folder.relative_to(ROOT))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--no-program', action='store_true', help='Stop, initialize and redeploy service without PA programming or PU reboot')
    mode.add_argument('--software-only', action='store_true', help='SSH collector update on healthy idle ABI 2/3 firmware, no JTAG or resets')
    parser.add_argument('--frames', type=int, default=100, choices=range(2, 1001), metavar='2..1000')
    parser.add_argument('--check-only', action='store_true', help='Check local release artifacts only; no board access')
    parser.add_argument('--host', type=board_host, help='Board IPv4; default KOSMO_BOARD_HOST or board_connection.json')
    args = parser.parse_args()
    folder = ROOT / 'runs' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f-deployment')
    folder.mkdir(parents=True)
    host = board_host(args.host)
    url = board_url(host)
    report = {'success': False, 'host': host, 'url': url, 'no_program': args.no_program, 'software_only': args.software_only, 'check_only': args.check_only}
    print(f'Kosmo car deployment. Log: {folder}', flush=True)
    print(f'Board: {host}; SSH host fingerprint will be checked. '+
          ('Software-only update; no JTAG required.' if args.software_only else 'JTAG USB must be connected to this Windows.'), flush=True)
    try:
        with deployment_lock(ROOT / 'runs/deploy.lock'):
            ops = Operations(folder, args.frames, host=host)
            if args.check_only:
                ops.preflight(args.no_program or args.software_only, software_only=args.software_only)
            elif args.software_only:
                report['verification'] = deploy_software(ops)
            else:
                report['verification'] = deploy(ops, args.no_program)
            report['success'] = True
            print('Local checks passed.' if args.check_only else f'READY: {url} (neutral standby)', flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        report['error'] = str(error) or 'Interrupted by user'
        print(f'DEPLOYMENT STOPPED: {report["error"]}\nLogs: {folder}', file=sys.stderr, flush=True)
        return 1
    finally:
        (folder / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
