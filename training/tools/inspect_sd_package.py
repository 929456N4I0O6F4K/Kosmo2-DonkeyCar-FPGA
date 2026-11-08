"""Read SD preparation archives and embedded kernel config, without restoring a disk."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import zlib


def inspect_archive(path):
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        inventory = [{'name': m.name, 'size': m.size, 'regular_file': m.isfile()}
                     for m in members]
    return inventory


def kernel_config(image):
    for match in re.finditer(b'IKCFG_ST', image):
        stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            config = stream.decompress(image[match.end():])
        except zlib.error:
            continue
        if stream.eof and stream.unused_data.startswith(b'IKCFG_ED'):
            return config
    raise ValueError('No valid embedded IKCONFIG gzip stream found')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package_dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = args.output_dir or project / 'runs' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-sd-package')
    output.mkdir(parents=True, exist_ok=True)
    package = args.package_dir.resolve()
    report = {'package_dir': str(package), 'archives': {}}
    inventories = {}
    for name, path in {
        'sd_sh': package / 'sd_sh.tar.gz',
        'boot': package / 'extracted' / 'boot_backup.tar.gz',
        'rootfs': package / 'extracted' / 'rootfs_backup.tar.gz',
    }.items():
        inventory = inspect_archive(path)
        inventories[name] = inventory
        (output / (name + '-inventory.json')).write_text(
            json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        report['archives'][name] = {
            'path': str(path), 'bytes': path.stat().st_size, 'member_count': len(inventory),
            'sha256': digest,
        }
    names = [m['name'].removeprefix('./') for m in inventories['rootfs']]
    tools = {'wpa_supplicant', 'wpa_passphrase', 'iw', 'iwconfig', 'usb_modeswitch', 'gcc', 'make'}
    report['rootfs'] = {
        'kernel_modules': [n for n in names if re.search(r'\.ko(?:\.(?:xz|gz|zst))?$', n)],
        'wifi_tools': [n for n in names if PurePosixPath(n).name in tools],
        'kernel_build_files': [n for n in names if PurePosixPath(n).name in
                               {'Module.symvers', 'Kconfig', 'utsrelease.h', 'autoconf.h'}],
        'source_directories': [n for n in names if re.search(r'(^|/)(pango_kernel|pango_rootfs|pango_config|src)(/|$)', n)],
        'firmware_files': [n for n in names if n.startswith('lib/firmware/')],
    }
    boot_archive = package / 'extracted' / 'boot_backup.tar.gz'
    with tarfile.open(boot_archive, 'r:gz') as archive:
        kernel = archive.extractfile('./Image').read()
    config = kernel_config(kernel)
    (output / 'kernel.config').write_bytes(config)
    selected = [line for line in config.decode().splitlines()
                if re.match(r'(?:# )?CONFIG_(?:CFG80211|MAC80211|USB_DWC2|USB_ULPI|RTL8|RTW8|MODULES)(?:_|=| )', line)]
    version = re.search(rb'Linux version [\x20-\x7e]+', kernel)
    report['kernel'] = {
        'version': version[0].decode() if version else None,
        'image_sha256': hashlib.sha256(kernel).hexdigest(),
        'config_sha256': hashlib.sha256(config).hexdigest(),
        'relevant_config': selected,
    }
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Evidence:', output)
    print(json.dumps({'rootfs': report['rootfs'], 'kernel': report['kernel']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
