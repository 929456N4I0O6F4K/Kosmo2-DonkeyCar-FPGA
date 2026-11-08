"""Configure this board's eth0 for the computer's direct Ethernet subnet.

Backs up all changed board files both on the board and under local runs/.
Only saves configuration: reactivate eth0 from the serial console afterwards.
"""

import argparse
import datetime as dt
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex

from pu_ssh import BOARD_HOST, ROOT, connect


def configure(client, address, gateway):
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = ROOT / "runs" / f"{stamp}_network_config"
    folder.mkdir(parents=True, exist_ok=False)
    backup = f"/root/kosmo_donkeycar/backups/network_{stamp}"
    paths = ["/etc/network/interfaces", "/etc/init.d/S99dhclient", "/etc/init.d/rcS"]
    with client.open_sftp() as sftp:
        originals = {p: sftp.file(p, "rb").read() for p in paths}
        modes = {p: sftp.stat(p).st_mode & 0o777 for p in paths}
        rcs = originals[paths[2]].decode("utf-8")
        rcs, count = re.subn(r"^ifconfig eth0 192\.168\.1\.10 netmask 255\.255\.255\.0 up$",
                            "# eth0 is configured by S40network and /etc/network/interfaces.",
                            rcs, flags=re.M)
        if count != 1:
            raise ValueError("Expected vendor rcS address override not found; inspect before changing configuration")
        interfaces = (
            "# Kosmo2 direct Ethernet; configured by kosmo_donkeycar.\n"
            "auto lo\niface lo inet loopback\n\n"
            "auto eth0\niface eth0 inet static\n"
            f"    address {address.ip}\n    netmask {address.netmask}\n"
            f"    gateway {gateway}\n"
            f"    up printf 'nameserver {gateway}\\n' > /etc/resolv.conf\n"
        )
        dhclient = (
            "#!/bin/sh\n"
            "# S40network owns interface configuration. Do not start a second DHCP client.\n"
            "case \"$1\" in\n"
            "    start|stop) exit 0 ;;\n"
            "    restart) exec /etc/init.d/S40network restart ;;\n"
            "    *) echo \"Usage: $0 {start|stop|restart}\"; exit 1 ;;\n"
            "esac\n"
        )
        updates = dict(zip(paths, [interfaces.encode(), dhclient.encode(), rcs.encode()]))
        _, stdout, stderr = client.exec_command("mkdir -p " + shlex.quote(backup), timeout=10)
        if stdout.channel.recv_exit_status():
            raise RuntimeError(stderr.read().decode())
        changes = []
        for index, path in enumerate(paths):
            original, content = originals[path], updates[path]
            for kind, data in (("before", original), ("after", content)):
                local = folder / kind / path.lstrip("/")
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
            remote_backup = backup + "/" + Path(path).name
            with sftp.file(remote_backup, "wb") as out:
                out.write(original)
            sftp.chmod(remote_backup, modes[path])
            staged = path + ".kosmo-new"
            with sftp.file(staged, "wb") as out:
                out.write(content)
            sftp.chmod(staged, modes[path])
            changes.append(dict(path=path, backup=remote_backup,
                                before_sha256=hashlib.sha256(original).hexdigest(),
                                after_sha256=hashlib.sha256(content).hexdigest()))
        for path in paths[1:]:
            _, stdout, stderr = client.exec_command("sh -n " + shlex.quote(path + ".kosmo-new"), timeout=10)
            if stdout.channel.recv_exit_status():
                raise RuntimeError(stderr.read().decode())
        for path in paths:
            sftp.posix_rename(path + ".kosmo-new", path)
            if sftp.file(path, "rb").read() != updates[path]:
                raise RuntimeError(f"Configuration readback mismatch: {path}")
    _, stdout, stderr = client.exec_command("sync", timeout=15)
    if stdout.channel.recv_exit_status():
        raise RuntimeError(stderr.read().decode())
    report = dict(address=str(address), gateway=str(gateway), board_backup=backup,
                  files=changes, readback_verified=True, interface_reactivated=False,
                  note="Configuration saved; reactivate eth0 via serial and verify SSH afterwards")
    (folder / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Evidence: {folder}")
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=BOARD_HOST)
    parser.add_argument("--address", default="192.168.137.10/24")
    parser.add_argument("--gateway", default="192.168.137.1")
    args = parser.parse_args()
    address = ipaddress.IPv4Interface(args.address)
    gateway = ipaddress.IPv4Address(args.gateway)
    if (address.ip in (address.network.network_address, address.network.broadcast_address)
            or gateway not in address.network or gateway == address.ip):
        parser.error("Host and gateway must be distinct usable addresses in one subnet")
    password = os.environ.get("KOSMO_SSH_PASSWORD") or getpass.getpass("PU SSH password: ")
    with connect(password, host=args.host) as client:
        configure(client, address, gateway)


if __name__ == "__main__":
    main()
