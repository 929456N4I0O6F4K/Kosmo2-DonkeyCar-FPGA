"""Read-only Linux survey through the board's PU serial console.

Uses the vendor image's documented root/root login only when a login prompt
is present. Saves received output and structured command results on the PC.
Does not change the board's network, storage, GPIO, or PA configuration.
"""

import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import re
import time
from pathlib import Path

import serial


COMMANDS = [
    ("system", "uname -a; id; cat /etc/os-release; cat /proc/cmdline; uptime"),
    ("memory_storage", "free -m; df -h; cat /proc/mounts; cat /proc/partitions"),
    ("network", "ip addr show; ip route show; cat /etc/network/interfaces; cat /proc/net/wireless"),
    ("tools", "for x in python3 python pip3 gcc cc make curl wget dropbear sshd httpd busybox dtc devmem i2cdetect; do command -v $x; done; busybox | head -n 3"),
    ("devices", "ls -l /dev/video* /dev/media* /dev/i2c-* /dev/spidev* /dev/gpiochip* /dev/uio* /dev/mem /dev/mmcblk* /sys/class/fpga_manager/* 2>/dev/null; ls /sys/bus/platform/devices"),
    ("device_tree", "tr '\\000' '\\n' < /proc/device-tree/model; tr '\\000' '\\n' < /proc/device-tree/compatible; ls /proc/device-tree; cat /proc/iomem"),
    ("drivers", "cat /proc/modules; dmesg | tail -n 100"),
    ("python", "if command -v python3 >/dev/null 2>&1; then python3 -V; python3 -c 'import importlib.util,json; print(json.dumps({n:importlib.util.find_spec(n) is not None for n in [\"donkeycar\",\"numpy\",\"PIL\",\"cv2\",\"tornado\",\"serial\"]}))'; fi"),
    ("uio", "for d in /sys/class/uio/uio*; do echo $d; cat $d/name $d/version; for m in $d/maps/map*; do echo $m; cat $m/name $m/addr $m/size $m/offset; done; done"),
    ("pa_tree", "find /proc/device-tree/amba_pa /proc/device-tree/reserved-memory -maxdepth 3 -type f; for p in /proc/device-tree/amba_pa/ranges /proc/device-tree/ddr@1e000000/reg /proc/device-tree/shared-ddr@300000/reg; do echo $p; od -An -tx1 $p; done"),
    ("runtime", "ls -l /sys/firmware/fdt /proc/config.gz /lib/ld* /lib/libc*; busybox --list | grep -E 'base64|sha256|httpd|nc|tftp|timeout|stty'; ps; ls /usr/bin /usr/sbin | head -n 100"),
    ("kernel_config", "base64 /proc/config.gz; sha256sum /proc/config.gz"),
    ("fdt", "base64 /sys/firmware/fdt; sha256sum /sys/firmware/fdt"),
]


def read_until_quiet(port, maximum=4.0, quiet=0.5):
    result = bytearray()
    start = last = time.monotonic()
    while time.monotonic() - start < maximum:
        chunk = port.read(port.in_waiting or 1)
        if chunk:
            result.extend(chunk)
            last = time.monotonic()
        elif result and time.monotonic() - last >= quiet:
            break
    return result.decode("utf-8", errors="replace").replace("\r", "")


def survey(port, folder, sections=None, *, stop_on_error=False, quiet=False):
    log = []
    port.write(b"\r")
    welcome = read_until_quiet(port)
    log.append(welcome)
    if re.search(r"login:\s*$", welcome):
        port.write(b"root\r")
        welcome = read_until_quiet(port)
        log.append(welcome)
        if re.search(r"Password:\s*$", welcome, re.I):
            port.write(b"root\r")
            welcome = read_until_quiet(port)
            log.append(welcome)
            # PAM/login may pause after an initial newline before the shell.
            deadline = time.monotonic() + 8
            while not re.search(r"(?:^|\n)[^\n]*[#$]\s*$", welcome) and time.monotonic() < deadline:
                extra = read_until_quiet(port, maximum=2)
                welcome += extra
                log.append(extra)
                if re.search(r"login:\s*$", welcome):
                    break
    if not re.search(r"(?:^|\n)[^\n]*[#$]\s*$", welcome):
        (folder / "console.log").write_text("".join(log), encoding="utf-8")
        raise RuntimeError("No Linux shell prompt; inspect console.log. No commands sent.")
    results = []
    for index, (name, command) in enumerate(COMMANDS):
        if sections and name not in sections:
            continue
        marker = f"KOSMO_PROBE_END_{index:02d}"
        line = command + "; printf '\\n" + marker + ":%s\\n' \"$?\""
        port.write(line.encode("ascii") + b"\r")
        output = ""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            output += read_until_quiet(port, maximum=2, quiet=0.2)
            match = re.search(r"^" + marker + r":(\d+)\s*$", output, re.M)
            if match:
                break
        else:
            log.append(output)
            (folder / "console.log").write_text("".join(log), encoding="utf-8")
            raise TimeoutError(f"No completion marker for {name}; stopped without interrupting shell")
        log.append(output)
        (folder / "console.log").write_text("".join(log), encoding="utf-8")
        results.append(dict(name=name, command=command, exit_code=int(match[1]), output=output))
        if name in ("kernel_config", "fdt") and int(match[1]) == 0:
            encoded = "".join(line for line in output.splitlines()
                              if re.fullmatch(r"[A-Za-z0-9+/]{2,}={0,2}", line))
            artifact = folder / ("kernel.config.gz" if name == "kernel_config" else "live.dtb")
            content = base64.b64decode(encoded, validate=True)
            checksum = re.search(r"^([0-9a-f]{64})\s+/", output, re.M)
            if not checksum or hashlib.sha256(content).hexdigest() != checksum[1]:
                raise ValueError(f"Serial file transfer checksum mismatch: {name}")
            if name == "kernel_config":
                gzip.decompress(content)
            elif content[:4] != b"\xd0\x0d\xfe\xed" or int.from_bytes(content[4:8], "big") != len(content):
                raise ValueError("Invalid flattened device tree")
            artifact.write_bytes(content)
            print(f"[{name}] saved {artifact.name} ({artifact.stat().st_size} bytes)", flush=True)
        elif not quiet:
            print(f"[{name}]\n{output}", flush=True)
        (folder / "console.log").write_text("".join(log), encoding="utf-8")
        (folder / "probe.json").write_text(json.dumps(dict(
            timestamp=dt.datetime.now().astimezone().isoformat(),
            port=port.port, baudrate=port.baudrate, commands=results,
        ), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if stop_on_error and int(match[1]):
            raise RuntimeError(f"Serial command {name} exited {match[1]}; inspect {folder / 'console.log'}")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--section", action="append", choices=[name for name, _ in COMMANDS])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = root / "runs" / dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f_pu_probe")
    folder.mkdir(parents=True)
    print(f"Evidence: {folder}", flush=True)
    port = serial.Serial(port=None, baudrate=args.baud, timeout=0.1, write_timeout=3)
    port.dtr = False
    port.rts = False
    port.port = args.port
    with port:
        survey(port, folder, args.section)


if __name__ == "__main__":
    main()
