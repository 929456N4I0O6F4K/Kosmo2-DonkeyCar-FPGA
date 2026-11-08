"""Run a reviewed JSON command list via a Linux VM's CP210x UART (Python 3.5+).

No board SSH. Saves commands and output; never pass Wi-Fi secrets in commands.
An absent Linux prompt stops the survey without interrupting the console.
"""
import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import os
import re
import select
import termios
import time


def read_quiet(fd, maximum=3, quiet=0.3):
    result = bytearray()
    deadline = time.monotonic() + maximum
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], quiet)
        if ready:
            data = os.read(fd, 65536)
            if not data:
                raise IOError("UART disconnected")
            result.extend(data)
        elif result:
            break
    return result.decode("utf-8", errors="replace")


def write_all(fd, data):
    while data:
        _, ready, _ = select.select([], [fd], [], 5)
        if not ready:
            raise TimeoutError("UART write timed out")
        data = data[os.write(fd, data):]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True)
    p.add_argument("--commands", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--private", action="store_true", help="Redact command text and UART responses for credential setup")
    args = p.parse_args()
    with open(args.commands) as source:
        commands = json.load(source)
    for name, command in commands:
        if not name or not command or "\n" in command or "\r" in command:
            raise ValueError("Expected named, single-line commands")
        command.encode("ascii")
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    report = {"port": args.port, "timestamp": datetime.datetime.now().isoformat(), "commands": []}
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = termios.tcgetattr(fd)
        settings[0] = settings[1] = settings[3] = 0
        settings[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        settings[4] = settings[5] = termios.B115200
        settings[6][termios.VMIN] = 0
        settings[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        welcome = read_quiet(fd, maximum=1)
        write_all(fd, b"\r")
        welcome += read_quiet(fd)
        if re.search(r"login:\s*$", welcome):
            write_all(fd, b"root\r")
            welcome += read_quiet(fd)
            if re.search(r"Password:\s*$", welcome, re.I):
                write_all(fd, b"root\r")
                welcome += read_quiet(fd, maximum=10, quiet=1)
        report["welcome"] = welcome
        if not re.search(r"(?:^|\n)[^\n]*[#$]\s*$", welcome):
            raise RuntimeError("No Linux shell prompt; no commands sent: " + welcome[-1200:])
        for index, (name, command) in enumerate(commands):
            marker = "KOSMO_UART_END_{:02d}".format(index)
            line = command + "; printf '\\n" + marker + ":%s\\n' \"$?\""
            write_all(fd, line.encode("ascii") + b"\r")
            output = ""
            deadline = time.monotonic() + args.timeout
            match = None
            while time.monotonic() < deadline:
                output += read_quiet(fd, maximum=1)
                match = re.search(r"^" + marker + r":(\d+)\s*$", output, re.M)
                if match:
                    break
            report["commands"].append({"name": name, "command": "[redacted]" if args.private else command,
                                       "output": "[redacted]" if args.private else output,
                                       "exit_code": int(match.group(1)) if match else None})
            if args.private:
                print("[{}] exit={}".format(name, int(match.group(1)) if match else "timeout"), flush=True)
            elif name == "fdt" and match and int(match.group(1)) == 0:
                encoded = "".join(line for line in output.splitlines()
                                  if re.fullmatch(r"[A-Za-z0-9+/]{2,}={0,2}", line))
                data = base64.b64decode(encoded, validate=True)
                checksum = re.search(r"^([0-9a-f]{64})\s+/", output, re.M)
                if not checksum or hashlib.sha256(data).hexdigest() != checksum.group(1):
                    raise ValueError("DTB checksum mismatch")
                if data[:4] != b"\xd0\x0d\xfe\xed" or int.from_bytes(data[4:8], "big") != len(data):
                    raise ValueError("Invalid DTB")
                with open(args.output + ".dtb", "wb") as artifact:
                    artifact.write(data)
                print("[fdt] saved {} bytes, SHA256 {}".format(len(data), checksum.group(1)), flush=True)
            else:
                print("[{}]\n{}".format(name, output), flush=True)
            if not match:
                raise TimeoutError("No completion marker; console left uninterrupted")
            if int(match.group(1)):
                raise RuntimeError("Command failed: " + name)
    finally:
        os.close(fd)
        with open(args.output, "w") as result:
            json.dump(report, result, ensure_ascii=False, indent=2)
            result.write("\n")


if __name__ == "__main__":
    main()
