"""Export existing board sessions over verified SSH; never drives or trains.

Raw PNG images, JSONL labels and session metadata are preserved byte for byte.
--finish-recording closes an open recorder only when the car is already stopped.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import urllib.request
import zipfile

from board_link import BOARD_HOST, REMOTE, ROOT, connect, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory-password', action='store_true')
    parser.add_argument('--finish-recording', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, payload=None):
        req = urllib.request.Request(f'http://{BOARD_HOST}:8080/api/{path}',
                                     data=None if payload is None else json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        with opener.open(req, timeout=10) as response:
            return json.load(response)

    before = api('status')
    if before['enabled'] or before['frame']['flags'] & 1:
        raise RuntimeError('Stop driving before exporting data')
    if before['record_open']:
        if not args.finish_recording:
            raise RuntimeError('Finish recording first, or use --finish-recording while stopped')
        api('record', {'recording': False})
    stopped = api('status')
    if stopped['record_open'] or stopped['enabled']:
        raise RuntimeError('Collector must be stopped and recording closed')

    folder = args.output_dir or ROOT / 'exports' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-board-data')
    folder.mkdir(parents=True, exist_ok=False)
    data = folder / 'sessions'
    data.mkdir()
    (folder / 'status-before.json').write_text(json.dumps(before, indent=2) + '\n')
    (folder / 'status-after-recording.json').write_text(json.dumps(stopped, indent=2) + '\n')
    password = os.environ.get('KOSMO_SSH_PASSWORD') or (
        'root' if args.factory_password else getpass.getpass('PU SSH password: '))
    files, directories = {}, []
    remote_root = REMOTE + '/data'
    with connect(password) as client, client.open_sftp() as sftp:
        def scan(relative=''):
            for entry in sorted(sftp.listdir_attr(remote_root + '/' + relative), key=lambda x: x.filename):
                name = entry.filename
                if (name in ('.', '..') or any(c in name for c in '<>:"/\\|?*\r\n')
                        or name.endswith((' ', '.'))):
                    raise ValueError('Unsafe filename in board data')
                rel = str(PurePosixPath(relative) / name)
                if stat.S_ISDIR(entry.st_mode):
                    directories.append(rel)
                    (data / rel).mkdir()
                    scan(rel)
                elif stat.S_ISREG(entry.st_mode):
                    files[rel] = {'bytes': entry.st_size, 'mtime': entry.st_mtime}
                else:
                    raise ValueError('Non-regular file in board data: ' + rel)
        scan()
        print(f'Found {len(files)} files; copying to {folder}', flush=True)
        for index, (rel, metadata) in enumerate(files.items(), 1):
            target = data / rel
            sftp.get(remote_root + '/' + rel, str(target))
            if target.stat().st_size != metadata['bytes']:
                raise RuntimeError('Download size mismatch: ' + rel)
            metadata['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            if index % 50 == 0:
                print(f'Copied {index}/{len(files)} files', flush=True)
        # Compare against board hashes after copying; an incomplete/changing
        # recording cannot silently become a successful export.
        names = list(files)
        for offset in range(0, len(names), 100):
            batch = names[offset:offset + 100]
            command = 'cd ' + shlex.quote(remote_root) + ' && sha256sum ' + ' '.join(shlex.quote('./' + x) for x in batch)
            lines = run(client, command).splitlines()
            if len(lines) != len(batch):
                raise RuntimeError('Incomplete remote checksum list')
            for rel, line in zip(batch, lines):
                digest, remote_name = line.split(None, 1)
                if remote_name != './' + rel or digest != files[rel]['sha256']:
                    raise RuntimeError('Board/download checksum mismatch: ' + rel)
                after = sftp.stat(remote_root + '/' + rel)
                if after.st_size != files[rel]['bytes'] or after.st_mtime != files[rel]['mtime']:
                    raise RuntimeError('Source changed during export: ' + rel)

    sessions = []
    for meta_path in sorted(data.glob('*/session.json')):
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        records = [json.loads(line) for line in (meta_path.parent / 'records.jsonl').read_text(encoding='utf-8').splitlines()]
        sessions.append({'directory': meta_path.parent.name, 'metadata': meta, 'records': len(records),
                         'angle_range': [min(r['user/angle'] for r in records), max(r['user/angle'] for r in records)] if records else None,
                         'throttle_range': [min(r['user/throttle'] for r in records), max(r['user/throttle'] for r in records)] if records else None})
    archive = folder / 'kosmo-recordings.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        for rel in directories:
            zipped.write(data / rel, rel + '/')
        for rel in files:
            zipped.write(data / rel, rel)
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise RuntimeError('ZIP integrity verification failed')
    report = {'success': True, 'source': remote_root, 'exported_at': datetime.datetime.now().astimezone().isoformat(),
              'sessions': sessions, 'session_count': len(sessions), 'record_count': sum(s['records'] for s in sessions),
              'file_count': len(files), 'bytes': sum(f['bytes'] for f in files.values()), 'files': files,
              'archive': archive.name, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'remote_sha256_verified': True, 'source_deleted': False, 'training_started': False}
    (folder / 'export.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"Exported {report['session_count']} sessions, {report['record_count']} records. ZIP: {archive}", flush=True)


if __name__ == '__main__':
    main()
