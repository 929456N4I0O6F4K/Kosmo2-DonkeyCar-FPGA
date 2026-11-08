"""Capture a controlled UART reboot or one-off U-Boot command (Python 3.5+)."""
import argparse
import fcntl
import os
import re
import termios
import time
from vm_uart import read_quiet, write_all


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True)
    p.add_argument("--output", required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--reboot-to-uboot", action="store_true")
    mode.add_argument("--reboot-linux", action="store_true")
    mode.add_argument("--uboot-command")
    p.add_argument("--wait-linux", action="store_true")
    args = p.parse_args()
    wait_linux = args.wait_linux or args.reboot_linux
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    uboot = r"(?:^|\n)(?:=>|[A-Za-z0-9_@().: /-]{1,60}>)\s*$"
    log = ""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = termios.tcgetattr(fd)
        settings[0] = settings[1] = settings[3] = 0
        settings[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        settings[4] = settings[5] = termios.B115200
        settings[6][termios.VMIN] = settings[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        log += read_quiet(fd, maximum=0.3)
        write_all(fd, b"\r")
        log += read_quiet(fd, maximum=1)
        if args.reboot_to_uboot or args.reboot_linux:
            if not re.search(r"(?:^|\n)[^\n]*#\s*$", log):
                raise RuntimeError("No Linux root prompt")
            write_all(fd, b"sync && reboot\r")
        else:
            if not re.search(uboot, log):
                raise RuntimeError("No U-Boot prompt")
            if "\n" in args.uboot_command or "\r" in args.uboot_command:
                raise ValueError("Single-line U-Boot command required")
            write_all(fd, args.uboot_command.encode("ascii") + b"\r")
        captured = ""
        stopped = False
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            data = read_quiet(fd, maximum=0.2, quiet=0.05)
            captured += data
            log += data
            with open(args.output, "w") as output:
                output.write(log)
            if args.reboot_to_uboot and not stopped and "Hit any key to stop autoboot:" in captured:
                write_all(fd, b"\r")
                stopped = True
            if re.search(uboot, captured):
                print(captured, flush=True)
                if wait_linux:
                    raise RuntimeError("Returned to U-Boot instead of starting Linux")
                return
            if wait_linux and "Starting kernel" in captured and re.search(r"(?:login:|[^\n]*#)\s*$", captured):
                print(captured, flush=True)
                return
        print(captured, flush=True)
        raise TimeoutError("Boot observation timed out; no extra input sent")
    finally:
        os.close(fd)
        with open(args.output, "w") as output:
            output.write(log)


if __name__ == "__main__":
    main()
