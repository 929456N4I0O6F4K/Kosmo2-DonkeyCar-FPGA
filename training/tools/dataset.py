"""Read lossless Kosmo sessions and export through the installed DonkeyCar Tub API."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


def load_sessions(paths, allow_synthetic=False):
    records, sessions = [], []
    for directory in paths:
        root = Path(directory).resolve()
        meta = json.loads((root / "session.json").read_text(encoding="utf-8"))
        if meta.get("schema") != "kosmo-training-v1":
            raise ValueError(f"Unsupported session: {root}")
        if meta["synthetic"] and not allow_synthetic:
            raise ValueError(f"Synthetic session excluded: {root}; use --allow-synthetic only for smoke tests")
        if meta["session_id"] in sessions:
            raise ValueError("Duplicate session ID")
        sessions.append(meta["session_id"])
        previous_us, previous_seq = -1, None
        with (root / "records.jsonl").open(encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                try:
                    r = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Truncated/bad record {root}:{line_no}; inspect before training") from exc
                if r["session_id"] != meta["session_id"] or r["user/mode"] != "user":
                    raise ValueError(f"Wrong session or label mode: {root}:{line_no}")
                angle, throttle = r["user/angle"], r["user/throttle"]
                if (not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (angle, throttle))
                        or not -1 <= angle <= 1 or not 0 <= throttle <= 1):
                    raise ValueError(f"Invalid labels: {root}:{line_no}")
                if r["capture_us"] <= previous_us or r["frame_sequence"] == previous_seq:
                    raise ValueError(f"Duplicate/out-of-order frame: {root}:{line_no}")
                previous_us, previous_seq = r["capture_us"], r["frame_sequence"]
                path = (root / r["cam/image_array"]).resolve()
                if not path.is_relative_to(root / "images"):
                    raise ValueError("Image path escapes the session")
                with Image.open(path) as image:
                    if image.size != (160, 120) or image.mode != "RGB":
                        raise ValueError(f"Expected 160x120 RGB: {path}")
                    image.verify()
                records.append(dict(r, image_path=str(path)))
    if not records:
        raise ValueError("No recorded driving frames; enable recording and hold drive first")
    return records, sessions


def image_array(record, crop=True):
    with Image.open(record["image_path"]) as image:
        rgb = np.array(image)
    return rgb[25:120, 2:158] if crop else rgb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions", nargs="+", type=Path)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--tub", type=Path, help="new output directory; uses official installed Tub v2 writer")
    args = parser.parse_args()
    records, ids = load_sessions(args.sessions, args.allow_synthetic)
    report = {"sessions": ids, "records": len(records),
              "steering_range": [min(r["user/angle"] for r in records), max(r["user/angle"] for r in records)],
              "throttle_range": [min(r["user/throttle"] for r in records), max(r["user/throttle"] for r in records)]}
    if args.tub:
        if args.tub.exists():
            raise ValueError("Output Tub already exists; choose a new path")
        from donkeycar.parts.tub_v2 import Tub
        keys = ["cam/image_array", "user/angle", "user/throttle", "user/mode",
                "kosmo/session_id", "kosmo/capture_us", "kosmo/frame_sequence", "kosmo/command_sequence"]
        types = ["image_array", "float", "float", "str", "str", "int", "int", "int"]
        tub = Tub(str(args.tub), inputs=keys, types=types, metadata=["source:kosmo-training-v1"])
        try:
            for r in records:
                tub.write_record(dict(zip(keys, [image_array(r, False), r["user/angle"], r["user/throttle"], "user",
                    r["session_id"], r["capture_us"], r["frame_sequence"], r["command_sequence"]])))
        finally:
            tub.close()
        # Tub's private timestamp is export time. The original capture clock and
        # session IDs above remain explicit public fields; retain raw sessions.
        (args.tub / "kosmo_export.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
