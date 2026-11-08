"""Read a Kosmo BSP archive and save an inventory plus selected source files.

This does not execute archive contents or unpack toolchains/symlinks on Windows.
"""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import time


def selected(name):
    parts = PurePosixPath(name).parts
    if not parts or parts[0] != "kosmo2":
        return False
    leaf = parts[-1]
    lower = name.lower()
    if len(parts) <= 3 and (
        leaf.lower().startswith(("readme", "release", "version"))
        or leaf in {"Makefile", ".config", "settings.sh", "AGENTS.md"}
    ):
        return True
    if name.startswith("kosmo2/pango_kernel/"):
        return (
            name.endswith(("include/generated/utsrelease.h", "include/generated/compile.h"))
            or "/drivers/usb/dwc2/" in name
            or name.endswith(("drivers/usb/phy/Makefile", "drivers/usb/phy/Kconfig"))
            or ("ulpi" in lower and name.endswith((".c", ".h", ".yaml", ".txt")))
            or ("pango" in "/".join(parts[2:]) and name.endswith((".c", ".h", ".dts", ".dtsi", "Kconfig", "Makefile")))
            or "/arch/arm64/configs/" in name
        )
    if name.startswith("kosmo2/pango_config/"):
        return (
            name.endswith((".dts", ".dtsi", ".config", "defconfig"))
            or (len(parts) <= 4 and name.endswith((".sh", ".txt", ".md")))
        )
    if name.startswith("kosmo2/pango_rootfs/"):
        return (
            "/configs/" in name and ("pango" in leaf or "kosmo" in leaf)
            or "/package/wpa_supplicant/" in name
            or "/package/iw/" in name
            or "/package/rtl8188" in lower
            or "/package/usb_modeswitch/" in name
        )
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    out = args.output or Path(__file__).resolve().parents[1] / "runs" / (
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-bsp-inspection"
    )
    out.mkdir(parents=True, exist_ok=False)
    counts, sizes = Counter(), Counter()
    captured, candidates, skipped = [], [], []
    started = last_progress = time.monotonic()
    member_count = 0
    with (out / "inventory.jsonl").open("w", encoding="utf-8") as inventory:
        with tarfile.open(args.archive, "r|gz") as archive:
            for member in archive:
                name = member.name.removeprefix("./")
                parts = PurePosixPath(name).parts
                member_count += 1
                group = "/".join(parts[:2])
                counts[group] += 1
                sizes[group] += member.size
                inventory.write(json.dumps({
                    "name": name, "size": member.size,
                    "type": member.type.decode("ascii", errors="replace"),
                    "link": member.linkname or None,
                }, ensure_ascii=False) + "\n")
                lower = name.lower()
                if any(x in lower for x in ("8188gu", "toolchain", "linaro", "module.symvers", "release_note")):
                    if member.isfile() and (len(parts) < 6 or "8188gu" in lower or "module.symvers" in lower):
                        candidates.append({"name": name, "size": member.size})
                if member.isfile() and selected(name):
                    unsafe = (
                        not parts or PurePosixPath(name).is_absolute()
                        or any(p in {"..", "."} or any(c in p for c in ':\\<>|?*') for p in parts)
                    )
                    if unsafe or member.size > 2_000_000:
                        skipped.append({"name": name, "size": member.size})
                    else:
                        dest = out / "selected" / Path(*parts)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source:
                            content = source.read()
                        dest.write_bytes(content)
                        captured.append(name)
                if time.monotonic() - last_progress >= 15:
                    print(f"Scanned {member_count} entries; now {group}", flush=True)
                    last_progress = time.monotonic()
    digest = hashlib.sha256()
    with args.archive.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    report = {
        "archive": str(args.archive.resolve()),
        "archive_bytes": args.archive.stat().st_size,
        "sha256": digest.hexdigest(),
        "members": member_count,
        "groups": {g: {"members": n, "file_bytes": sizes[g]} for g, n in sorted(counts.items())},
        "selected_count": len(captured),
        "selected": captured,
        "candidates": candidates,
        "skipped": skipped,
        "seconds": round(time.monotonic() - started, 1),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"selected", "candidates"}}, indent=2), flush=True)
    print(f"Report: {out}", flush=True)


if __name__ == "__main__":
    main()
