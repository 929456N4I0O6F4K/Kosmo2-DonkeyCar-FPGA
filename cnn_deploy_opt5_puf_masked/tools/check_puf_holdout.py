"""Count binding mismatches of fresh captures against a production puf_key.mem.

A mismatch is a stable (sign_mask) bit whose live value differs from the
enrolled binding; each one negates a dense MAC tap in the production image.
Zero mismatches in every holdout enrollment means the image reproduces opt4.
The holdout capture must be a separate session from the enrollment capture.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import puf_key_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--holdout-json', type=Path, required=True)
    parser.add_argument('--enrollment-json', type=Path, required=True,
                        help='capture used to write the key; must differ from the holdout')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    key = puf_key_image.read(args.key)
    if key['mode'] != 'drive':
        raise SystemExit('Key is not a production key')
    holdout = json.loads(args.holdout_json.read_text(encoding='utf-8'))
    enrollment = json.loads(args.enrollment_json.read_text(encoding='utf-8'))
    if args.holdout_json.read_bytes() == args.enrollment_json.read_bytes():
        raise SystemExit('Holdout and enrollment are the same capture')
    if holdout.get('board') != enrollment.get('board') or holdout.get('bitstream_sha256') != enrollment.get('bitstream_sha256'):
        raise SystemExit('Holdout must come from the same board and capture image as the enrollment')
    rows = []
    for index, value in enumerate(holdout['captures_hex']):
        live = int(value, 16)
        mismatch = key['sign_mask'] & (live ^ key['binding'])
        rows.append(dict(enrollment=index + 1, mismatched_bits=mismatch.bit_count(),
                         mismatch_hex=f'{mismatch:036x}',
                         quality_bits=int(holdout['quality_hex'][index], 16).bit_count()))
    worst = max(r['mismatched_bits'] for r in rows)
    result = dict(board=holdout['board'], key_sha256=hashlib.sha256(args.key.read_bytes()).hexdigest(),
                  holdout_sha256=hashlib.sha256(args.holdout_json.read_bytes()).hexdigest(),
                  bitstream_sha256=holdout['bitstream_sha256'], stable_bits=key['sign_mask'].bit_count(),
                  holdout_enrollments=len(rows), max_mismatched_bits=worst,
                  exact_in_every_holdout=worst == 0, rows=rows,
                  power_cycle_between=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    for r in rows:
        print(f"holdout {r['enrollment']}: {r['mismatched_bits']} mismatched of {result['stable_bits']} stable bits")
    print(f"max mismatched bits: {worst}")


if __name__ == '__main__':
    main()
