"""Encode dense1/dense2 signs with a captured board-A response.

Run after tools/export.py. The enrollment key is read only as an input; the
generated production key has a zero binding and the transformed weights carry
the board-A reference signs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import puf_key_image

WIDTH = 144
FULL_MASK = (1 << WIDTH) - 1
LAYERS = {"stage5_weights.mem": (960, 100), "stage6_weights.mem": (100, 50)}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_capture(capture_path, key_path, key_json_path):
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    key_meta = json.loads(key_json_path.read_text(encoding="utf-8"))
    if capture.get("schema") != "kosmo-opt4-ro-capture-v2" or capture.get("board") != "A":
        raise ValueError("Expected the saved RO7 enrollment capture from board A")
    if key_meta.get("kind") != "ro7-opt4" or key_meta.get("board") != "A":
        raise ValueError("Expected the matching RO7/opt4 board-A key metadata")
    if key_meta.get("capture_sha256") != sha256(capture_path):
        raise ValueError("Enrollment key metadata does not match the capture JSON")
    if key_meta.get("key_sha256") != sha256(key_path):
        raise ValueError("Enrollment key metadata does not match the saved key image")
    captures = capture.get("captures_hex", [])
    quality = capture.get("quality_hex", [])
    if len(captures) < 8 or len(captures) != len(quality):
        raise ValueError("Capture must contain at least eight matching enrollments and quality masks")
    if capture.get("min_count_margin") != 50 or capture.get("repeats_per_comparison") != 9:
        raise ValueError("Capture does not use the frozen RO7 voting policy")
    if any(not re.fullmatch(r"[0-9a-fA-F]{36}", value) for value in captures):
        raise ValueError("Malformed 144-bit capture value")
    values = [int(value.removeprefix("0x"), 16) for value in captures]
    stable = FULL_MASK
    for value in values[1:]:
        stable &= ~(values[0] ^ value) & FULL_MASK
    for value in quality:
        if not re.fullmatch(r"[0-9a-fA-F]{36}", value):
            raise ValueError("Malformed 144-bit quality mask")
        stable &= int(value, 16)
    for group in range(16):
        if (stable >> (group * 9)) & 0xff != 0xff:
            stable &= ~(1 << (group * 9 + 8))
    if stable != int(capture.get("stable_mask_hex", "0"), 16):
        raise ValueError("Recomputed stability mask does not match capture metadata")
    key = puf_key_image.read(key_path)
    reference = values[0] & stable
    if key["mode"] != "drive" or key["sign_mask"] != stable or key["binding"] != reference:
        raise ValueError("Saved enrollment key does not match the captured reference and stable mask")
    if stable.bit_count() < 96 or key_meta.get("registered_comparisons", 0) < 96:
        raise ValueError("Enrollment is below the accepted run-through comparison threshold")
    return capture, key_meta, reference, stable


def encode_mem(path, depth, width, toggle_mask):
    lines = path.read_text(encoding="ascii").splitlines()
    if len(lines) != depth or any(not re.fullmatch(rf"[0-9a-fA-F]{{{width * 2}}}", line) for line in lines):
        raise ValueError(f"Unexpected ROM shape in {path}: expected {depth} x {width} bytes")
    encoded = []
    changed_taps = 0
    changed_weights = 0
    for tap, line in enumerate(lines):
        raw = bytes.fromhex(line)
        if (toggle_mask >> (tap % WIDTH)) & 1:
            if 0x80 in raw:
                raise ValueError(f"Cannot negate int8 -128 in {path} tap {tap}")
            original = raw
            raw = bytes(((-value if value < 128 else -(value - 256)) & 0xff) for value in raw)
            restored = bytes(((-value if value < 128 else -(value - 256)) & 0xff) for value in raw)
            if restored != original:
                raise AssertionError(f"int8 sign encoding is not reversible at {path} tap {tap}")
            changed_taps += 1
            changed_weights += width
        encoded.append(raw.hex() + "\n")
    text = "".join(encoded)
    return text, changed_taps, changed_weights


def atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(text)
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--enrollment-key", type=Path, required=True)
    parser.add_argument("--enrollment-key-json", type=Path, required=True)
    parser.add_argument("--output-key", type=Path,
                        default=ROOT / "integration/training/build/board/puf_key.mem")
    parser.add_argument("--mem-dir", type=Path, default=ROOT / "rtl/generated")
    parser.add_argument("--baseline-route", type=Path, default=ROOT.parent /
                        "cnn_deploy_opt4/integration/training/build/board/prj_tasks/pnr_1/"
                        "place_route/kosmo_training_top_route_optimize.netlist")
    args = parser.parse_args()

    capture, key_meta, reference, stable = stable_capture(
        args.capture, args.enrollment_key, args.enrollment_key_json)
    model_manifest = json.loads((ROOT / "model_manifest.json").read_text(encoding="utf-8"))
    if "opt5" not in model_manifest.get("model", ""):
        raise ValueError("The exported deployment model is not opt5")
    manifest_path = args.output_key.parent / "puf_obfuscation_manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_hashes = previous.get("source_mem_sha256", {})
        encoded_hashes = previous.get("encoded_mem_sha256", {})
        if source_hashes or encoded_hashes:
            for name in LAYERS:
                current_hash = sha256(args.mem_dir / name)
                if current_hash == encoded_hashes.get(name):
                    raise ValueError(f"{name} is already PUF-encoded; rerun tools/export.py before encoding again")
                if current_hash != source_hashes.get(name):
                    raise ValueError(f"{name} differs from both source and encoded data in the prior manifest")
    toggle_mask = reference & stable
    if not toggle_mask:
        raise ValueError("Enrollment reference has no stable one bits to encode")

    staged = {}
    stats = {}
    source_hashes = {}
    encoded_hashes = {}
    for name, (depth, width) in LAYERS.items():
        path = args.mem_dir / name
        source_hashes[name] = sha256(path)
        staged[name], taps, weights = encode_mem(path, depth, width, toggle_mask)
        encoded_hashes[name] = hashlib.sha256(staged[name].encode("ascii")).hexdigest()
        stats[name] = dict(taps_transformed=taps, weights_selected_for_negation=weights)

    output_key = puf_key_image.words("drive", binding=0, sign_mask=stable)
    key_text = "".join(f"{word:05x}\n" for word in output_key)

    args.output_key.parent.mkdir(parents=True, exist_ok=True)
    for name, text in staged.items():
        atomic_write(args.mem_dir / name, text)
    atomic_write(args.output_key, key_text)
    production_key = puf_key_image.read(args.output_key)
    if production_key != dict(mode="drive", binding=0, sign_mask=stable):
        raise AssertionError("Production key image failed its consistency check")
    result = dict(
        schema="kosmo-opt5-puf-weight-encoding-v1",
        model=model_manifest["model"],
        model_sha256=model_manifest["model_sha256"],
        enrollment_board="A",
        enrollment_capture_sha256=sha256(args.capture),
        enrollment_status=key_meta.get("status"),
        stable_symbols=stable.bit_count(),
        registered_comparisons=key_meta["registered_comparisons"],
        power_cycle_verified=bool(capture.get("power_cycle_verified")),
        cross_build_reuse_qualified=bool(capture.get("cross_build_reuse_qualified")),
        production_key_binding_zero=True,
        production_key_sha256=sha256(args.output_key),
        source_mem_sha256=source_hashes,
        encoded_mem_sha256=encoded_hashes,
        route_reference=dict(
            project="cnn_deploy_opt4",
            relative_path=str(args.baseline_route.relative_to(ROOT.parent)),
            route_netlist_sha256=sha256(args.baseline_route)),
        encoding="int8 negation for weight taps selected by captured binding & stable mask",
        layers=stats,
        route_or_pnr_run=False,
        bitstream_generated=False,
        limitations=[
            "PUF-controlled weight encoding covers dense1 and dense2 only; other layer weights remain unchanged.",
            "This folder contains model inputs for a route-preserving update, not a new bitstream.",
            "The enrollment remains a run-through candidate; power-cycle and cross-build reuse are unverified.",
        ],
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
