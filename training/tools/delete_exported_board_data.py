"""Delete only unchanged, verified board sessions from a completed local export.

Requires an explicit user request to remove board data. Local copies are kept.
The collector must be stopped, and the full remote inventory and hashes must
match the export before any source file is removed.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import zipfile

from board_link import REMOTE, collector_process_script, connect, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export_dir', type=Path)
    parser.add_argument('--factory-password', action='store_true')
    args = parser.parse_args()
    folder = args.export_dir.resolve()
    manifest = json.loads((folder / 'export.json').read_text(encoding='utf-8'))
    if not manifest['success'] or not manifest['remote_sha256_verified']:
        raise RuntimeError('A verified successful export is required')
    session_ids = [s['directory'] for s in manifest['sessions']]
    if not session_ids or any(not re.fullmatch(r'\d{8}T\d{6}\.\d+Z_[a-f0-9]+', s) for s in session_ids):
        raise ValueError('Unexpected session IDs')
    if manifest['archive'] != 'kosmo-recordings.zip':
        raise ValueError('Unexpected archive name')
    archive = folder / manifest['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['archive_sha256']:
        raise RuntimeError('Local archive hash mismatch')
    expected = manifest['files']
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise RuntimeError('Local archive is damaged')
        for rel, item in expected.items():
            parts = rel.split('/')
            if (parts[0] not in session_ids or any(p in ('', '.', '..') for p in parts)
                    or any(c in rel for c in '\\:\r\n')):
                raise ValueError('Unsafe path in export manifest')
            local = (folder / 'sessions' / rel).resolve()
            if not local.is_relative_to(folder / 'sessions'):
                raise ValueError('Local path escapes export')
            if (hashlib.sha256(local.read_bytes()).hexdigest() != item['sha256']
                    or hashlib.sha256(zipped.read(rel)).hexdigest() != item['sha256']):
                raise RuntimeError('Local data/ZIP mismatch: ' + rel)
    password = os.environ.get('KOSMO_SSH_PASSWORD') or (
        'root' if args.factory_password else getpass.getpass('PU SSH password: '))
    base = REMOTE + '/data'
    actual, directories = set(), []
    with connect(password) as client, client.open_sftp() as sftp:
        run(client, collector_process_script(stop=False))
        if sftp.normalize(base) != base:
            raise RuntimeError('Unexpected remote data directory')

        def scan(relative):
            path = base + '/' + relative
            entry = sftp.lstat(path)
            if stat.S_ISDIR(entry.st_mode):
                directories.append(relative)
                for child in sftp.listdir(path):
                    if child in ('.', '..') or '/' in child or '\\' in child:
                        raise ValueError('Unsafe remote entry')
                    scan(relative + '/' + child)
            elif stat.S_ISREG(entry.st_mode):
                actual.add(relative)
            else:
                raise RuntimeError('Refusing non-regular source: ' + relative)

        for session_id in session_ids:
            scan(session_id)
        if actual != set(expected):
            raise RuntimeError('Remote session inventory changed; export it again before deleting')
        names = sorted(actual)
        for offset in range(0, len(names), 100):
            batch = names[offset:offset + 100]
            command = 'cd ' + shlex.quote(base) + ' && sha256sum ' + ' '.join(shlex.quote('./' + x) for x in batch)
            lines = run(client, command).splitlines()
            if len(lines) != len(batch):
                raise RuntimeError('Incomplete source hash verification')
            for rel, line in zip(batch, lines):
                digest, name = line.split(None, 1)
                if name != './' + rel or digest != expected[rel]['sha256']:
                    raise RuntimeError('Remote source changed: ' + rel)
        # No recursive delete and no wildcard: remove the verified files only.
        run(client, collector_process_script(stop=False))
        print(f'Both local copies and {len(names)} board files verified; deleting {len(session_ids)} exported session.', flush=True)
        for rel in names:
            sftp.remove(base + '/' + rel)
        for rel in sorted(directories, key=lambda p: p.count('/'), reverse=True):
            sftp.rmdir(base + '/' + rel)
        remaining = sftp.listdir(base)
        if set(session_ids) & set(remaining):
            raise RuntimeError('Source session still present')
    result = {'success': True, 'deleted_at': datetime.datetime.now().astimezone().isoformat(),
              'deleted_sessions': session_ids, 'deleted_files': len(names),
              'remaining_board_entries': remaining, 'local_copies_verified_and_retained': True,
              'archive_sha256': manifest['archive_sha256'], 'training_started': False}
    (folder / 'board-deletion.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    manifest['source_deleted'] = True
    manifest['source_deletion_evidence'] = 'board-deletion.json'
    (folder / 'export.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
