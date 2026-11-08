"""Collect read-only PU Linux facts needed for camera and DonkeyCar bring-up."""

import argparse
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


DEVICE_PATTERNS = (
    "/dev/video*",
    "/dev/media*",
    "/dev/i2c-*",
    "/dev/spidev*",
    "/dev/gpiochip*",
    "/dev/uio*",
    "/sys/class/pwm/pwmchip*",
)
PACKAGES = ("donkeycar", "cv2", "numpy", "PIL", "serial", "tensorflow", "tflite_runtime")
COMMANDS = ("v4l2-ctl", "media-ctl", "ffmpeg", "gcc")


def read_optional(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip("\0\n ")
    except (OSError, UnicodeError):
        return None


def run_optional(command):
    executable = shutil.which(command[0])
    if not executable:
        return {"available": False}
    try:
        result = subprocess.run(
            [executable, *command[1:]], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5, check=False,
        )
        return {
            "available": True,
            "exit_code": result.returncode,
            "stdout": result.stdout[:8192],
            "stderr": result.stderr[:2048],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "error": str(exc)}


def collect():
    devices = {}
    for pattern in DEVICE_PATTERNS:
        parent = Path(pattern).parent
        devices[pattern] = sorted(str(path) for path in parent.glob(Path(pattern).name))

    video_names = {}
    for device in devices["/dev/video*"]:
        name = Path(device).name
        video_names[device] = read_optional(Path("/sys/class/video4linux") / name / "name")

    packages = {}
    for package in PACKAGES:
        try:
            packages[package] = importlib.util.find_spec(package) is not None
        except (ImportError, ValueError):
            packages[package] = False

    return {
        "schema": "kosmo-board-probe-v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "system": {
            "platform": sys.platform,
            "machine": platform.machine(),
            "release": platform.release(),
            "python": sys.version.split()[0],
            "device_tree_model": read_optional(Path("/proc/device-tree/model")),
        },
        "devices": devices,
        "video_names": video_names,
        "python_packages_found": packages,
        "commands_found": {command: shutil.which(command) for command in COMMANDS},
        "v4l2_devices": run_optional(("v4l2-ctl", "--list-devices")),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()
    result = json.dumps(collect(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
        print(args.output)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
