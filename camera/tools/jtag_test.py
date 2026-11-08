"""Read camera status/frames through the board JTAG cable; PU/Linux is unused."""
import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from camera_host import decode_packet, save_frame
from jtag_shell import Debugger

ROOT = Path(__file__).resolve().parents[1]


def dvio_json(text):
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char != '{':
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and 'probe_ins' in obj:
            return obj
    raise ValueError('No DVIO JSON in debugger response')


def port_value(port):
    return sum(int(net['value'], 2) << net['idx'] for net in port['nets'])


def decode_diagnostics(value):
    if value >> 48 != 0x5343:
        raise ValueError(f'Unknown SCCB diagnostic format: {value:016x}')
    states = ('IDLE START_A START_B START_C BIT_SET BIT_UP BIT_HOLD BIT_DOWN '
              'ACK_SET ACK_UP ACK_SAMPLE ACK_DOWN READ_SET READ_UP READ_SAMPLE READ_DOWN '
              'NACK_SET NACK_UP NACK_HOLD NACK_DOWN STOP_LOW STOP_UP STOP_RELEASE STOP_DONE').split()
    def bus(word):
        state = word & 31
        return dict(state=states[state] if state < len(states) else str(state),
                    sda_input=word >> 5 & 1, scl_input=word >> 6 & 1,
                    sda_drive_low=bool(word & 128), scl_drive_low=bool(word & 256),
                    busy=bool(word & 512), error=word >> 10 & 3,
                    read_phase=bool(word & 4096), byte_index=word >> 13 & 3)
    return dict(raw_hex=f'{value:016x}', live=bus(value & 65535),
                failure_snapshot=bus(value >> 16 & 65535),
                config_phase=value >> 32 & 7, reset_n_output=value >> 35 & 1,
                config_state=value >> 36 & 15, config_error=value >> 40 & 255)


def decode_monitor(value):
    if value >> 240 != 0x4456:
        raise ValueError(f'Unknown DVP monitor format: {value:064x}')
    return dict(sample_sequence=value >> 224 & 65535,
                sysclk_ticks=value >> 192 & 0xffffffff,
                pclk_edges=value >> 160 & 0xffffffff,
                total_frames=value >> 128 & 0xffffffff,
                bad_frames=value >> 96 & 0xffffffff,
                last_bytes=value >> 64 & 0xffffffff,
                last_lines=value >> 48 & 65535,
                last_line_bytes=value >> 32 & 65535,
                last_frame_pclk_edges=value & 0xffffffff)


def monitor_delta(first, second):
    ticks = (second['sysclk_ticks'] - first['sysclk_ticks']) & 0xffffffff
    if not ticks or not first['sample_sequence'] or not second['sample_sequence']:
        raise ValueError('Need two fresh monitor snapshots in the same configuration epoch')
    seconds = ticks/50_000_000
    frames = (second['total_frames']-first['total_frames']) & 0xffffffff
    bad = (second['bad_frames']-first['bad_frames']) & 0xffffffff
    edges = (second['pclk_edges']-first['pclk_edges']) & 0xffffffff
    return dict(seconds=seconds, frames=frames, bad_frames=bad,
                fps=frames/seconds, pclk_edges_per_second=edges/seconds)


class CameraJtag:
    def __init__(self, shell):
        self.shell = shell
        shell.command('dbg_connect -ip 127.0.0.1 -port 65420', timeout=100)
        shell.command('dbg_scan_chain', timeout=40)
        obj = dvio_json(shell.command('dbg_dvio_refresh -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0'))
        self.control = port_value(obj['probe_outs'][0])
        self.token = port_value(obj['probe_ins'][0]) & 255
        self.sample()

    def sample(self):
        obj = dvio_json(self.shell.command(
            'dbg_dvio_refresh_input -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0'))
        status = port_value(obj['probe_ins'][0])
        signature = status >> 48
        if signature not in (0xca01, 0xca02):
            raise ValueError(f'Wrong JTAG firmware or unstable read: {status:016x}')
        self.last_diagnostics = (decode_diagnostics(port_value(obj['probe_ins'][2]))
                                 if len(obj['probe_ins']) > 2 else None)
        self.last_monitor = None
        if signature == 0xca02:
            if len(obj['probe_ins']) != 11:
                raise ValueError('CA02 firmware requires eight data probes and a DVP monitor')
            self.page_bytes = 256
            self.last_monitor = decode_monitor(port_value(obj['probe_ins'][10]))
            data = b''.join(port_value(obj['probe_ins'][i]).to_bytes(32, 'little')
                            for i in [1, 3, 4, 5, 6, 7, 8, 9])
        else:
            self.page_bytes = 32
            data = port_value(obj['probe_ins'][1]).to_bytes(32, 'little')
        return status, data

    def set_control(self, value):
        commands = []
        for bit in range(32):
            if (self.control ^ value) & (1 << bit):
                commands.append(f'dbg_dvio_set_output -device 1 -dvio 0 -channel {{ProbeOut0[{bit}]}} -value {(value >> bit) & 1}')
        commands.append('dbg_dvio_commit_output -device 1 -dvio 0')
        self.shell.command('\n'.join(commands))
        self.control = value

    def transact(self, command):
        before, _ = self.sample()
        if not before & 0x100 or before & 0x200:
            raise RuntimeError('Camera busy; wait for the current command to finish')
        self.token = ((before & 255) + 1) & 255
        base = self.token << 8 | ord(command)
        self.set_control(base)
        deadline = time.monotonic() + 15
        while True:
            status, _ = self.sample()
            if status & 255 == self.token and status & 0x400:
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f'Camera command {command} did not complete; status={status:016x}')
            time.sleep(.05)
        if status & 0x800:
            raise ValueError('JTAG packet buffer overflow')
        size = status >> 16 & 65535
        if not 44 <= size <= 38444:
            raise ValueError(f'Invalid JTAG packet length {size}')
        packet = bytearray()
        for page in range((size+self.page_bytes-1)//self.page_bytes):
            self.set_control(base | page << 16)
            end = time.monotonic()+3
            while True:
                current, data = self.sample()
                if (current & 255 != self.token or current >> 16 & 65535 != size or
                        not current & 0x400 or current & 0x800):
                    raise ValueError('JTAG packet changed during read')
                if current & 0x1000 and (current >> 32 & 65535) == page:
                    break
                if time.monotonic() > end:
                    raise TimeoutError('JTAG page acknowledgement timeout')
            packet.extend(data)
            if size > 1000 and page % max(1, 6400//self.page_bytes) == 0:
                print(f'JTAG {command}: {min(len(packet),size)}/{size} bytes', flush=True)
        packet = bytes(packet[:size])
        info, raw = decode_packet(packet)
        return info, raw, packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pds', type=Path, default=Path('C:/pango/PDS_2025.2-ads'))
    parser.add_argument('--mode', choices=['status', 'reset', 'colorbar', 'normal', 'all'], default='status')
    parser.add_argument('--count', type=int, default=1)
    args = parser.parse_args()
    if args.count < 1:
        parser.error('count must be positive')
    folder = ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_jtag')
    folder.mkdir(parents=True)
    session = dict(started_at=dt.datetime.now().astimezone().isoformat(),
                   transport='PDS DVIO / PA JTAG', mode=args.mode, events=[], frames=[], passed=False)
    bit = ROOT/'build/pds_jtag/prj_tasks/pnr_1/generate_bitstream/camera_jtag_top.sbit'
    if bit.exists():
        session['bitstream_sha256'] = hashlib.sha256(bit.read_bytes()).hexdigest()
        report = ROOT/'build/implementation_jtag_validation.json'
        if report.exists():
            implementation = json.loads(report.read_text(encoding='utf-8'))
            if implementation.get('bitstream_sha256') == session['bitstream_sha256']:
                session['local_bitstream_sccb_profile'] = implementation.get('sccb_profile')
    shell = None
    def save():
        (folder/'session.json').write_text(json.dumps(session, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    try:
        print(f'JTAG session: {folder}', flush=True)
        save()
        shell = Debugger(args.pds/'bin/cdt_dbg_shell.exe', folder)
        camera = CameraJtag(shell)
        def transact(command):
            info, raw, packet = camera.transact(command)
            name = f'{len(session["events"]):03d}_{command}.bin'
            (folder/name).write_bytes(packet)
            session['events'].append(dict(command=command, time=dt.datetime.now().astimezone().isoformat(),
                                         packet=name, crc32_verified=True, info=info,
                                         diagnostics=camera.last_diagnostics,
                                         monitor=camera.last_monitor))
            save()
            print(json.dumps(info, ensure_ascii=False), flush=True)
            if camera.last_diagnostics:
                print('SCCB diagnostics: '+json.dumps(camera.last_diagnostics), flush=True)
            return info, raw, packet
        def ready():
            deadline = time.monotonic()+8
            while True:
                info, _, _ = transact('S')
                if info['flags'] & 2:
                    raise RuntimeError(info['error_text'])
                if info['flags'] & 1:
                    return info
                if time.monotonic() > deadline:
                    raise TimeoutError('Camera initialization timeout')
                time.sleep(.1)
        if args.mode == 'reset':
            transact('R')
        first = ready()
        started = time.monotonic()
        time.sleep(1)
        second = ready()
        session['vsync_hz_estimate'] = ((second['vsync_count']-first['vsync_count']) & 0xffffffff)/(time.monotonic()-started)
        modes = ['colorbar','normal'] if args.mode == 'all' else ([args.mode] if args.mode in ('colorbar','normal') else [])
        for mode in modes:
            transact('T' if mode == 'colorbar' else 'N')
            ready()
            time.sleep(2)
            for index in range(args.count):
                info, raw, packet = transact('F')
                if info['kind'] != 2:
                    raise RuntimeError(info['error_text'])
                dest = folder/f'{mode}_{index:03d}'
                metadata = save_frame(info, raw, packet, dest)
                metadata['host_path'] = 'PA JTAG DVIO bench capture; not PU/PA streaming'
                (dest/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
                session['frames'].append(str(dest.relative_to(folder)))
                save()
        session['passed'] = True
    except Exception as exc:
        session['error'] = str(exc)
        print(f'FAILED: {exc}', flush=True)
    finally:
        if shell:
            shell.close()
        session['ended_at'] = dt.datetime.now().astimezone().isoformat()
        save()
    print(f'Result: {folder / "session.json"}', flush=True)
    return 0 if session['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
