"""SSH access to the surveyed Kosmo2, checking its serial-verified host key.

Install host dependencies with:
    python -m pip install --target .host-deps -r requirements-host.txt
Passwords come from KOSMO_SSH_PASSWORD or an interactive prompt, never files.
"""

import argparse
import base64
import getpass
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".host-deps"))
sys.path.insert(0, str(ROOT.parents[1] / ".host-deps"))
import paramiko
from board_connection import board_host


BOARD_HOST = board_host()
# Confirmed through COM6 using ssh-keygen on the board, 2026-10-04.
BOARD_FINGERPRINT = "SHA256:1MCH9ZRtXSjCezI2rFKpPk5ps7qG/Z2IKUfVgzOOlGs"


class VerifiedKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint

    def missing_host_key(self, client, hostname, key):
        actual = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if actual != self.fingerprint:
            raise paramiko.SSHException(f"Host key mismatch for {hostname}: {actual}")
        client.get_host_keys().add(hostname, key.get_name(), key)


def connect(password, host=BOARD_HOST, user="root", fingerprint=BOARD_FINGERPRINT):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(VerifiedKey(fingerprint))
    try:
        client.connect(hostname=host, username=user, password=password,
                       timeout=8, banner_timeout=10, auth_timeout=10,
                       look_for_keys=False, allow_agent=False,
                       disabled_algorithms={"keys": ["ssh-rsa", "rsa-sha2-256", "rsa-sha2-512",
                                                      "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"]})
    except Exception:
        client.close()
        raise
    return client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=BOARD_HOST)
    parser.add_argument("--user", default="root")
    parser.add_argument("--fingerprint", default=BOARD_FINGERPRINT)
    parser.add_argument("command", help="Shell command to run on PU Linux")
    args = parser.parse_args()
    password = os.environ.get("KOSMO_SSH_PASSWORD") or getpass.getpass("PU SSH password: ")
    with connect(password, args.host, args.user, args.fingerprint) as client:
        _, stdout, stderr = client.exec_command(args.command, timeout=30)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        print(stderr.read().decode("utf-8", errors="replace"), file=sys.stderr, end="")
        return stdout.channel.recv_exit_status()


if __name__ == "__main__":
    raise SystemExit(main())
