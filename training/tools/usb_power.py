"""Deploy and control Kosmo2 USB-A power over UART (no SSH required)."""
import argparse
import base64
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import sys
import re
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'tools'))
import pu_serial_probe as probe
import serial
from serial.tools import list_ports

REMOTE = '/usr/local/sbin/kosmo-usb-power'
INIT = '/etc/init.d/S41kosmo-usb-power'
FLAG = '/etc/kosmo-usb-power.enabled'


def upload_commands(source, destination, staging):
    content = source.read_text(encoding='utf-8').replace('\r\n', '\n').encode('ascii')
    digest = hashlib.sha256(content).hexdigest()
    encoded = base64.b64encode(content).decode('ascii')
    q = shlex.quote
    commands = [('upload_prepare', f'umask 077 && : > {q(staging + ".b64")}')]
    for offset in range(0, len(encoded), 512):
        commands.append((f'upload_{offset // 512}',
                         f'printf %s {q(encoded[offset:offset + 512])} >> {q(staging + ".b64")}'))
    # Verify content and shell syntax before touching an installed copy.
    commands.append(('upload_verify',
        f'base64 -d {q(staging + ".b64")} > {q(staging)} && '
        f'echo {q(digest + "  " + staging)} | sha256sum -c - && sh -n {q(staging)}'))
    # SysV rcS executes S??*; backups must never live inside /etc/init.d.
    backup = '/var/lib/kosmo-usb-power/backups/' + PurePosixPath(destination).name + '.before'
    commands.append(('upload_install',
        f'mkdir -p {q(str(PurePosixPath(destination).parent))} {q(str(PurePosixPath(backup).parent))} && '
        f'if test -e {q(destination)} && ! test -e {q(backup)}; then cp -p {q(destination)} {q(backup)}; fi && '
        f'cp {q(staging)} {q(destination + ".new")} && chmod 755 {q(destination + ".new")} && '
        f'mv {q(destination + ".new")} {q(destination)} && '
        f'rm -f {q(staging)} {q(staging + ".b64")}'))
    return commands


def action_commands(action, tag):
    if action == 'inspect':
        return list(snapshot_commands().items())
    if action in ('install', 'deploy'):
        result = [('preflight', "test \"$(id -u)\" = 0 && tr '\\000' '\\n' < /proc/device-tree/compatible | grep -qx pango,kosmo2-pg2k100-400")]
        for source, destination in [('kosmo-usb-power', REMOTE), ('S41kosmo-usb-power', INIT)]:
            result += upload_commands(ROOT / 'usb_power' / source, destination, f'/tmp/kosmo-usb-{tag}-{source}')
        if action == 'deploy':
            result += [('start', f'{REMOTE} start'), ('enable_boot', f'{REMOTE} status && touch {FLAG} && sync')]
        return result
    if action == 'enable-boot':
        return [('enable_boot', f'{REMOTE} status && touch {FLAG} && sync')]
    if action == 'disable-boot':
        return [('disable_boot', f'rm -f {FLAG} && sync')]
    return [(action, f'{REMOTE} {action}')]


def boot_check(port, folder):
    """Reboot over UART, require a fresh boot log, then verify auto-start."""
    before=folder/'before'
    before.mkdir()
    probe.COMMANDS=[('preflight',f'test -e {FLAG} && {REMOTE} status')]
    probe.survey(port,before,stop_on_error=True)
    print('Rebooting PU over UART; USB load must remain disconnected for this check.',flush=True)
    port.write(b'sync && reboot\r')
    output=''
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        output+=probe.read_until_quiet(port,maximum=2,quiet=.2)
        (folder/'boot-console.log').write_text(output,encoding='utf-8')
        if 'Booting Linux' in output and re.search(r'login:\s*$',output):
            break
    else:
        raise TimeoutError('Fresh Linux login not seen; inspect boot-console.log. No further commands sent.')
    after=folder/'after'
    after.mkdir()
    probe.COMMANDS=[('boot_uptime','cat /proc/uptime'),('boot_power',f'test -e {FLAG} && {REMOTE} status')]
    probe.survey(port,after,stop_on_error=True)
    print('Fresh boot detected and automatic USB power startup verified.',flush=True)


def snapshot_commands():
    commands = {
        'system': 'uname -a; cat /proc/uptime',
        'usb_log': "dmesg | grep -i -E 'usb|dwc|ulpi|phy' | tail -n 65",
        'drivers': 'ls -l /sys/bus/platform/devices/f0040000*/driver /sys/bus/platform/drivers/*dwc* /sys/bus/platform/drivers/*ulpi* 2>/dev/null; true',
        'gpio': 'cat /sys/kernel/debug/gpio 2>/dev/null; for p in /sys/class/gpio/gpiochip*; do echo "$p"; cat "$p/base" "$p/ngpio" "$p/label"; done',
        'usb_sysfs': 'ls -l /sys/bus/usb/devices; ls /sys/kernel/debug/usb 2>/dev/null; true',
        'registers': '; '.join(f'printf "{name} "; devmem {address:#010x} 32' for name, address in {
            'GOTGCTL':0xf0040000, 'GAHBCFG':0xf0040008, 'GUSBCFG':0xf004000c,
            'GRSTCTL':0xf0040010, 'GINTSTS':0xf0040014, 'GINTMSK':0xf0040018,
            'GULPI':0xf0040034, 'GSNPSID':0xf0040040, 'GHWCFG2':0xf0040048,
            'HPRT':0xf0040440, 'PCGCTL':0xf0040e00,
            'GPIO_B_DATA':0xe500a00c, 'GPIO_B_DIR':0xe500a010,
        }.items()),
        'pinmux': "ls /sys/kernel/debug/pinctrl; cat /sys/kernel/debug/pinctrl/*/pinmux-pins 2>/dev/null | head -n 75; true",
    }
    return commands


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect','install','deploy','start','stop','status','enable-boot','disable-boot','boot-check'])
    parser.add_argument('--port', help='PU console; autodetects a single CP210x if omitted')
    args=parser.parse_args()
    if not args.port:
        matches=[p.device for p in list_ports.comports() if (p.vid,p.pid)==(0x10c4,0xea60)]
        if len(matches)!=1:
            parser.error('Specify --port: expected exactly one CP210x serial device')
        args.port=matches[0]
    tag=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder=ROOT/'runs'/(tag+'-usb-power-'+args.action)
    folder.mkdir(parents=True)
    probe.COMMANDS=action_commands(args.action,tag)
    (folder/'commands.json').write_text(json.dumps(probe.COMMANDS,indent=2)+'\n',encoding='utf-8')
    print('UART:',args.port,'Action:',args.action,'Evidence:',folder,flush=True)
    port=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=3)
    port.dtr=port.rts=False
    port.port=args.port
    with port:
        if args.action=='boot-check':
            boot_check(port,folder)
            return
        results=probe.survey(port,folder,stop_on_error=True,quiet=args.action in ('install','deploy'))
    if args.action in ('install','deploy'):
        for result in results:
            if not result['name'].startswith('upload_'):
                print(result['output'])
        print('Files verified and installed via UART.')


if __name__=='__main__':
    main()
