"""Configure WPA2 Wi-Fi through the build VM's UART without logging credentials.

Interactive by default. --passwords-stdin reads VM password then Wi-Fi password.
Stores only the derived WPA PSK on the board, not the plaintext Wi-Fi password.
"""
import argparse
import base64
import getpass
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / ".host-deps"))
import paramiko


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ssid", required=True)
    p.add_argument("--passwords-stdin", action="store_true")
    args = p.parse_args()
    if args.passwords_stdin:
        vm_password = sys.stdin.readline().rstrip("\r\n")
        wifi_password = sys.stdin.readline().rstrip("\r\n")
    else:
        vm_password = getpass.getpass("Build VM password: ")
        wifi_password = getpass.getpass("Wi-Fi password: ")
    ssid = args.ssid.encode("utf-8")
    password = wifi_password.encode("utf-8")
    if not 1 <= len(ssid) <= 32 or not 8 <= len(password) <= 63:
        p.error("SSID must be 1-32 bytes; WPA2 passphrase must be 8-63 bytes")
    psk = hashlib.pbkdf2_hmac("sha1", password, ssid, 4096, 32).hex()
    config = ("ctrl_interface=/run/kosmo-wifi/control\nnetwork={\n"
              "    ssid=" + ssid.hex() + "\n    psk=" + psk + "\n    key_mgmt=WPA-PSK\n    proto=RSN\n}\n").encode()
    del wifi_password, password, psk
    encoded = base64.b64encode(config).decode()
    checksum = hashlib.sha256(config).hexdigest()
    commands = [
        ["prepare", "umask 077; mkdir -p /etc/kosmo-wifi; chmod 700 /etc/kosmo-wifi; stty -echo"],
        ["write_config", "printf '%s' '" + encoded + "' | base64 -d > /etc/kosmo-wifi/wpa_supplicant.conf.new"],
        ["verify_config", "echo '" + checksum + "  /etc/kosmo-wifi/wpa_supplicant.conf.new' | sha256sum -c - >/dev/null && chmod 600 /etc/kosmo-wifi/wpa_supplicant.conf.new && mv /etc/kosmo-wifi/wpa_supplicant.conf.new /etc/kosmo-wifi/wpa_supplicant.conf"],
        ["restore_console", "stty echo"],
    ]
    task_root = "/home/pango/work/kosmo-wifi"
    remote = task_root + "/private/config-" + uuid.uuid4().hex + ".json"
    client = paramiko.SSHClient()
    client.load_host_keys(str(ROOT / "build/vm_known_hosts"))
    client.connect("192.168.170.136", username="pango", password=vm_password,
                   allow_agent=False, look_for_keys=False, timeout=10)
    with client, client.open_sftp() as sftp:
        try:
            try:
                sftp.mkdir(task_root + "/private", mode=0o700)
            except OSError:
                pass
            sftp.chmod(task_root + "/private", 0o700)
            with sftp.open(remote, "w") as target:
                target.write(json.dumps(commands))
            sftp.chmod(remote, 0o600)
            command = ("sudo -S -p '' -- python3 " + task_root + "/vm_uart.py --port /dev/ttyUSB0"
                       " --commands " + remote + " --output " + task_root + "/logs/configure-wifi.json --private")
            stdin, stdout, stderr = client.exec_command(command, timeout=90)
            stdin.write(vm_password + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()
            del vm_password
            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()
            print(output, end="")
            if error:
                print(error, file=sys.stderr, end="")
            if code:
                raise SystemExit(code)
            print("WPA2 configuration saved and checksum verified via UART.")
        finally:
            try:
                sftp.remove(remote)
            except OSError:
                pass


if __name__ == "__main__":
    main()
