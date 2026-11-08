"""Bounded hardware acceptance for the standalone PA camera project over JTAG."""
import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

from camera_host import rgb565_to_rgb888, save_frame
from inspect_frame import colorbar_check, png_bytes
from jtag_shell import Debugger
from jtag_test import CameraJtag, monitor_delta

ROOT = Path(__file__).resolve().parents[1]


class RecordingCamera(CameraJtag):
    def __init__(self, shell, folder):
        self.phase = 'connect'
        self.monitor_samples = []
        self.monitor_file = (folder/'monitor.jsonl').open('w', encoding='utf-8')
        self.previous_monitor = None
        self.previous_host_time = None
        self.previous_key = None
        self.epoch = 0
        super().__init__(shell)
        if self.page_bytes != 256:
            raise RuntimeError('Load current CA02 camera_jtag_top bitstream for acceptance')

    def sample(self):
        result = super().sample()
        mon = self.last_monitor
        if not mon or mon['sample_sequence'] == 0:
            if self.previous_monitor is not None:
                self.epoch += 1
            self.previous_monitor = None
            self.previous_key = None
            return result
        key = (mon['sample_sequence'], mon['sysclk_ticks'])
        if key == self.previous_key:
            return result
        now = time.monotonic()
        row = dict(time=dt.datetime.now().astimezone().isoformat(), phase=self.phase,
                   monitor=mon.copy())
        old = self.previous_monitor
        # Configuration reset starts another counter epoch. Software polls at
        # least every five seconds, well inside the 85.9-second tick wrap.
        if old and (mon['total_frames'] < old['total_frames'] or
                    mon['sample_sequence'] < old['sample_sequence']):
            self.epoch += 1
            old = None
        if old and now-self.previous_host_time < 60:
            row['delta'] = monitor_delta(old, mon)
        row['epoch'] = self.epoch
        self.monitor_samples.append(row)
        self.monitor_file.write(json.dumps(row)+'\n')
        self.monitor_file.flush()
        self.previous_monitor = mon.copy()
        self.previous_host_time = now
        self.previous_key = key
        return result


class Acceptance:
    def __init__(self, camera, folder, settings):
        self.camera, self.folder = camera, folder
        self.previous_sequence = None
        self.report = dict(started_at=dt.datetime.now().astimezone().isoformat(),
                           settings=settings, passed=False, events=[], frames=[], checks={})
        bit = ROOT/'build/pds_jtag/prj_tasks/pnr_1/generate_bitstream/camera_jtag_top.sbit'
        implementation = json.loads((ROOT/'build/implementation_jtag_validation.json').read_text(encoding='utf-8'))
        self.report['local_bitstream_sha256'] = hashlib.sha256(bit.read_bytes()).hexdigest()
        if implementation['bitstream_sha256'] != self.report['local_bitstream_sha256']:
            raise RuntimeError('Implementation report does not match local bitstream')
        self.report['implementation'] = implementation
        self.save()

    def save(self):
        (self.folder/'acceptance.json').write_text(json.dumps(self.report, indent=2)+'\n', encoding='utf-8')

    def transact(self, command):
        issued = dt.datetime.now().astimezone().isoformat()
        started = time.monotonic()
        info, raw, packet = self.camera.transact(command)
        filename = f'{len(self.report["events"]):03d}_{command}.bin'
        (self.folder/filename).write_bytes(packet)
        event = dict(command=command, phase=self.camera.phase, command_issued_at=issued,
                     received_at=dt.datetime.now().astimezone().isoformat(),
                     seconds=time.monotonic()-started, packet=filename,
                     crc32_verified=True, info=info, monitor=self.camera.last_monitor,
                     diagnostics=self.camera.last_diagnostics)
        self.report['events'].append(event)
        self.save()
        print(f'{self.camera.phase}: {command} error={info["error"]}, seq={info["sequence"]}, '
              f'bytes={info["captured_bytes"]}, elapsed={event["seconds"]:.2f}s', flush=True)
        return info, raw, packet

    def ready(self):
        deadline = time.monotonic()+10
        while True:
            info, _, _ = self.transact('S')
            if info['flags'] & 2:
                raise RuntimeError(info['error_text'])
            if info['flags'] & 1:
                if (info['pid'], info['ver']) not in ((0x26, 0x42), (0x26, 0x41)) or info['config_index'] != 223:
                    raise RuntimeError('Sensor ID/configuration mismatch')
                return info
            if time.monotonic() > deadline:
                raise TimeoutError('Initialization did not complete')
            time.sleep(.1)

    def check_monitor(self):
        deadline = time.monotonic()+5
        while True:
            self.camera.sample()
            mon = self.camera.last_monitor
            if mon and mon['sample_sequence'] and mon['total_frames']:
                if time.monotonic()-self.camera.previous_host_time > 3:
                    raise TimeoutError('DVP monitor snapshot is stale; check PCLK')
                latest = self.camera.monitor_samples[-1].get('delta')
                if latest and latest['seconds'] >= .5 and latest['frames'] == 0:
                    raise TimeoutError('PCLK is running but no complete DVP frame arrived')
                if (mon['bad_frames'] or mon['last_bytes'] != 38400 or
                        mon['last_lines'] != 120 or mon['last_line_bytes'] != 320):
                    raise RuntimeError(f'DVP monitor reports malformed frames: {mon}')
                return mon.copy()
            if time.monotonic() > deadline:
                raise TimeoutError('DVP monitor did not produce a live snapshot')
            time.sleep(.2)

    def configure(self, command, phase):
        self.camera.phase = phase
        self.transact(command)
        self.ready()
        time.sleep(2)
        return self.check_monitor()

    def capture(self, name, colorbar=False):
        info, raw, packet = self.transact('F')
        if info['kind'] != 2 or info['bad_count'] or bool(info['flags'] & 128) != colorbar:
            raise RuntimeError(f'Capture/mode validation failed: {info}')
        if self.previous_sequence is not None and info['sequence'] != (self.previous_sequence+1)&65535:
            raise RuntimeError('Fresh-frame sequence did not advance exactly once')
        self.previous_sequence = info['sequence']
        dest = self.folder/name
        metadata = save_frame(info, raw, packet, dest)
        rgb = rgb565_to_rgb888(raw)
        (dest/'frame.png').write_bytes(png_bytes(info['width'], info['height'], rgb))
        event = self.report['events'][-1]
        metadata.update(host_path='PA JTAG CA02; standalone camera acceptance',
                        command_issued_at=event['command_issued_at'], received_at=event['received_at'],
                        transfer_seconds=event['seconds'],
                        captured_at_semantics='Host save time; sensor exposure timestamp is not measured')
        (dest/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
        record = dict(folder=name, raw_sha256=metadata['raw_sha256'],
                      unique_pixel_values=metadata['unique_pixel_values'], seconds=event['seconds'])
        if colorbar:
            record['colorbar'] = colorbar_check(info['width'], info['height'], rgb)
        self.report['frames'].append(record)
        self.save()
        if colorbar and not record['colorbar']['passed']:
            raise RuntimeError('Sensor color-bar channel order failed')
        self.check_monitor()
        return record


def monitor_summary(rows):
    deltas = [row['delta'] for row in rows if 'delta' in row]
    seconds = sum(d['seconds'] for d in deltas)
    frames = sum(d['frames'] for d in deltas)
    bad = sum(d['bad_frames'] for d in deltas)
    edges = sum(d['seconds']*d['pclk_edges_per_second'] for d in deltas)
    return dict(seconds=seconds, frames=frames, bad_frames=bad,
                fps=frames/seconds if seconds else None,
                pclk_edges_per_second=edges/seconds if seconds else None,
                note='Counters derived from nominal 50 MHz board clock; edge rate is not an oscilloscope measurement')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pds', type=Path, default=Path('C:/pango/PDS_2025.2-ads'))
    parser.add_argument('--normal-count', type=int, default=10)
    parser.add_argument('--reset-count', type=int, default=3)
    parser.add_argument('--soak-seconds', type=float, default=600)
    args = parser.parse_args()
    if args.normal_count < 2 or args.reset_count < 1 or args.soak_seconds < 5:
        parser.error('Need at least two frames, one reset, and five seconds of monitoring')
    folder = ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_acceptance')
    folder.mkdir(parents=True)
    sources = folder/'host_source'
    sources.mkdir()
    for name in ['accept_camera.py', 'jtag_test.py', 'jtag_shell.py', 'camera_host.py',
                 'inspect_frame.py', 'report_acceptance.py']:
        (sources/name).write_bytes((ROOT/'tools'/name).read_bytes())
    print(f'Acceptance: {folder}', flush=True)
    settings = dict(normal_count=args.normal_count, reset_count=args.reset_count, soak_seconds=args.soak_seconds)
    shell = camera = acceptance = None
    success = False
    try:
        shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe', folder)
        camera = RecordingCamera(shell, folder)
        acceptance = Acceptance(camera, folder, settings)
        camera.phase = 'startup'
        acceptance.ready()
        acceptance.check_monitor()
        acceptance.capture('startup_normal')
        acceptance.report['checks']['automatic_startup_capture'] = True

        camera.phase = 'invalid_command'
        info, _, _ = acceptance.transact('X')
        if info['kind'] != 3 or info['error'] != 7:
            raise RuntimeError('Unknown command was not rejected')
        acceptance.ready()
        acceptance.report['checks']['unknown_command_recovery'] = True

        reset_results = []
        for index in range(args.reset_count):
            mon = acceptance.configure('R', f'reset_{index+1}')
            reset_results.append(mon)
        acceptance.report['checks']['camera_reset_cycles'] = reset_results

        acceptance.configure('T', 'colorbar_first')
        acceptance.capture('colorbar_first', colorbar=True)
        acceptance.configure('N', 'normal_between_modes')
        acceptance.capture('normal_between_modes')
        acceptance.configure('T', 'colorbar_second')
        acceptance.capture('colorbar_second', colorbar=True)
        acceptance.configure('N', 'normal_series')
        acceptance.report['checks']['two_colorbar_normal_cycles'] = True
        sample_start = len(camera.monitor_samples)
        steady_epoch = camera.epoch
        records = []
        for index in range(args.normal_count):
            records.append(acceptance.capture(f'normal_{index:03d}'))

        def steady_summary():
            rows = [row for row in camera.monitor_samples[sample_start:] if row['epoch'] == steady_epoch]
            return monitor_summary(rows)

        while True:
            acceptance.check_monitor()
            summary = steady_summary()
            if camera.epoch != steady_epoch:
                raise RuntimeError('Camera counters unexpectedly reset during the normal series')
            acceptance.report['steady_monitor'] = summary
            acceptance.save()
            print(f'Steady DVP: {summary["seconds"]:.1f}s, {summary["frames"]} frames, '
                  f'{summary["bad_frames"]} bad', flush=True)
            if summary['seconds'] >= args.soak_seconds:
                break
            time.sleep(min(5, args.soak_seconds-summary['seconds']+.2))
        if summary['bad_frames'] or summary['fps'] is None or not 1 <= summary['fps'] <= 120:
            raise RuntimeError(f'Steady stream check failed: {summary}')
        distinct = len({r['raw_sha256'] for r in records})
        if distinct < 2:
            raise RuntimeError('All normal frames identical; verify scene response/fresh capture')
        acceptance.report['checks']['normal_series'] = dict(count=len(records), distinct_raw_hashes=distinct,
            note='Different raw hashes and advancing sequence establish fresh buffers; noise alone can change hashes')
        acceptance.configure('R', 'reset_after_soak')
        acceptance.capture('normal_after_reset')
        acceptance.report['checks']['capture_after_final_reset'] = True
        acceptance.report['passed'] = success = True
    except Exception as exc:
        print(f'FAILED: {exc}', flush=True)
        if acceptance:
            acceptance.report['error'] = str(exc)
        else:
            (folder/'connection_error.json').write_text(json.dumps(dict(error=str(exc), settings=settings), indent=2)+'\n')
    finally:
        if camera:
            camera.monitor_file.close()
        if shell:
            shell.close()
        if acceptance:
            acceptance.report['ended_at'] = dt.datetime.now().astimezone().isoformat()
            acceptance.save()
    if success:
        try:
            from report_acceptance import review, write_gallery
            result = review(folder, '')
            write_gallery(folder, result)
            print(f'Gallery: {folder / "gallery.html"}', flush=True)
        except Exception as exc:
            success = acceptance.report['passed'] = False
            acceptance.report['error'] = f'Offline evidence review failed: {exc}'
            acceptance.save()
            print(f'FAILED: {exc}', flush=True)
    print(f'Result: {folder / "acceptance.json"}', flush=True)
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
