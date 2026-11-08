"""Write the production puf_key.mem from a board-A enrollment capture.

The key is block-ROM data only. Build the production image with
scripts/build_board.tcl from the same sources as the capture image, then run
tools/compare_implementations.py to confirm both are one implementation.
"""
import argparse
import json
from pathlib import Path
import re
import hashlib
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import puf_key_image

KEY = ROOT / "integration/training/build/board/puf_key.mem"
WIDTH = 144
FULL_MASK = (1 << WIDTH) - 1


def read_capture(args):
    data = json.loads(args.capture_json.read_text(encoding='utf-8'))
    if data.get('schema')!='kosmo-opt4-ro-capture-v2' or data.get('board')!='A':
        raise ValueError('Use a new board-A RO7/opt4 capture; legacy APUF captures are not accepted')
    if data.get('min_count_margin')!=50 or data.get('repeats_per_comparison')!=9:
        raise ValueError('Capture does not use the frozen RO margin/voting policy')
    captures = data.get("captures_hex")
    quality=data.get('quality_hex')
    if not isinstance(quality,list) or not isinstance(captures,list) or len(quality)!=len(captures) or len(captures)<8:
        raise ValueError('At least eight enrollments with matching RO quality masks are required')
    values = []
    for capture in captures:
        capture = str(capture).removeprefix("0x").replace("_", "")
        if not re.fullmatch(r"[0-9a-fA-F]{36}", capture):
            raise ValueError("each captures_hex value must be exactly 36 hexadecimal digits")
        values.append(int(capture, 16))
    stable = FULL_MASK
    for other in values[1:]:
        stable &= ~(values[0] ^ other) & FULL_MASK
    for mask in quality:
        if not re.fullmatch(r'[0-9a-fA-F]{36}',str(mask)):
            raise ValueError('Each quality mask must have 36 hexadecimal digits')
        stable &= int(mask,16)
    # Parity cannot be registered if any of its source comparisons is excluded.
    for group in range(16):
        if (stable>>(group*9))&255 != 255:
            stable &= ~(1<<(group*9+8))
    return values[0], stable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-json", type=Path, required=True,
                        help="host-side capture JSON from capture_puf_reference.py")
    parser.add_argument("--output", type=Path, default=KEY,
                        help="production key ROM image (defaults to build/board/puf_key.mem)")
    args = parser.parse_args()

    reference, stable = read_capture(args)
    raw_by_group = [sum(bool(stable & (1 << (group*9+lane))) for lane in range(8))
                    for group in range(16)]
    raw_stable = sum(raw_by_group)
    # Run-through candidate threshold only; this is not an entropy estimate.
    if raw_stable < 96 or min(raw_by_group) < 4:
        raise SystemExit(f"Only {raw_stable}/128 stable raw comparisons; each group needs at least four")
    binding = reference & stable

    puf_key_image.write(args.output, 'drive', binding, stable)
    capture = json.loads(args.capture_json.read_text(encoding='utf-8'))
    args.output.with_suffix('.json').write_text(json.dumps(dict(
        kind='ro7-opt4',board='A',registered_symbols=stable.bit_count(),
        registered_comparisons=raw_stable,minimum_raw_comparisons=96,
        minimum_comparisons_per_group=4,group_comparison_counts=raw_by_group,
        capture_sha256=hashlib.sha256(args.capture_json.read_bytes()).hexdigest(),
        capture_bitstream_sha256=capture.get('bitstream_sha256'),
        key_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
        status='run_through_candidate',independent_holdout_passed=False,power_cycle_verified=False,
        same_implementation_verified=False),indent=2)+'\n',encoding='utf-8')
    print(f"Wrote production key {args.output}: {stable.bit_count()} stable bits; "
          "capture not copied to board storage.")


if __name__ == "__main__":
    main()
