"""Run build scripts and transfer artifacts on the authorized Kosmo build VM.

Use the project Python 3.14 and .host-deps. Credentials are read from the
KOSMO_VM_PASSWORD environment variable or stdin, never saved in this script.
This helper does not connect to the car's SSH server.
"""
import argparse
import os
from pathlib import Path, PurePosixPath
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / ".host-deps"))
import paramiko

WORKSPACE = "/home/pango/work/kosmo-wifi"


def remote_path(value):
    path = PurePosixPath(value)
    if ".." in path.parts or not str(path).startswith(WORKSPACE + "/"):
        raise ValueError("Artifact paths must stay in " + WORKSPACE)
    return str(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--password-stdin", action="store_true")
    sub = p.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run")
    group = run.add_mutually_exclusive_group(required=True)
    group.add_argument("--script", type=Path)
    group.add_argument("--command")
    run.add_argument("--log", type=Path)
    run.add_argument("--timeout", type=int, default=1800)
    run.add_argument("--sudo", action="store_true", help="Run on the VM with sudo; password stays in stdin")
    for name in ("put", "get"):
        transfer = sub.add_parser(name)
        transfer.add_argument("local", type=Path)
        transfer.add_argument("remote", type=remote_path)
    args = p.parse_args()
    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else os.environ.get("KOSMO_VM_PASSWORD")
    if not password:
        p.error("Provide KOSMO_VM_PASSWORD or --password-stdin")
    sys.stdout.reconfigure(encoding="utf-8")
    client = paramiko.SSHClient()
    client.load_host_keys(str(ROOT / "build/vm_known_hosts"))
    client.connect("192.168.170.136", username="pango", password=password,
                   look_for_keys=False, allow_agent=False,
                   timeout=10, auth_timeout=15, banner_timeout=15)
    with client:
        if args.action in ("put", "get"):
            with client.open_sftp() as sftp:
                if args.action == "put":
                    temp = args.remote + ".upload-" + uuid.uuid4().hex
                    sftp.put(str(args.local), temp)
                    sftp.posix_rename(temp, args.remote)
                    print("Uploaded", args.local.name, "to", args.remote)
                else:
                    args.local.parent.mkdir(parents=True, exist_ok=True)
                    temp = args.local.with_name(args.local.name + ".download")
                    sftp.get(args.remote, str(temp))
                    temp.replace(args.local)
                    print("Downloaded", args.remote, "to", args.local)
            return
        command = args.command or "bash -s"
        if args.sudo:
            import shlex
            sentinel = "KOSMO_STDIN_" + uuid.uuid4().hex
            # Consume a delimiter before the script, whether sudo reads the
            # password or uses an existing authentication ticket.
            wrapped = "while IFS= read -r line; do [ \"$line\" = " + shlex.quote(sentinel) + " ] && break; done; "
            wrapped += "exec bash -c " + shlex.quote(args.command) if args.command else "exec bash -s"
            command = "sudo -S -p '' -- bash -c " + shlex.quote(wrapped)
        stdin, stdout, _ = client.exec_command(command)
        channel = stdout.channel
        channel.set_combine_stderr(True)
        if args.sudo:
            stdin.write(password + "\n" + sentinel + "\n")
            stdin.flush()
        del password
        if args.script:
            stdin.write(args.script.read_text(encoding="utf-8"))
        stdin.channel.shutdown_write()
        deadline = time.monotonic() + args.timeout
        logfile = None
        if args.log:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            logfile = args.log.open("wb")
        try:
            while True:
                if channel.recv_ready():
                    data = channel.recv(65536)
                    if logfile:
                        logfile.write(data)
                        logfile.flush()
                    print(data.decode("utf-8", errors="replace"), end="", flush=True)
                elif channel.exit_status_ready():
                    break
                elif time.monotonic() >= deadline:
                    raise TimeoutError("VM command exceeded timeout; inspect remote process state before retrying")
                else:
                    time.sleep(0.1)
            code = channel.recv_exit_status()
        finally:
            if logfile:
                logfile.close()
        if code:
            raise SystemExit(code)


if __name__ == "__main__":
    main()
