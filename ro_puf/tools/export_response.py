"""Export enrolled RO bytes and a bit validity mask for later experiments."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from compare import load, majority


def export(folder, policy="unanimous", min_count_margin=0):
    if policy not in ("unanimous", "majority") or min_count_margin < 0:
        raise ValueError("Invalid enrollment policy or count margin")
    folder = Path(folder)
    manifest, samples = load(folder)
    margins = {}
    with (folder / "counts.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = int(row["challenge_index"]), int(row["lane"])
            margin = abs(int(row["delta"]))
            margins[key] = min(margins.get(key, margin), margin)
    rows = []
    for index, values in samples.items():
        response = mask = 0
        for bit in range(8):
            decision, errors, ties = majority(values, bit)
            keep = (decision is not None and ties == 0
                    and (policy == "majority" or errors == 0)
                    and margins[index, bit] >= min_count_margin)
            if keep:
                response |= decision << bit
                mask |= 1 << bit
        rows.append(dict(challenge_index=index, response_hex=f"{response:02x}", valid_mask_hex=f"{mask:02x}"))
    binding = dict(firmware=manifest["firmware"], bitstream_sha256=manifest["bitstream_sha256"],
                   challenge_mapping=manifest["challenge_mapping"], challenges=manifest["challenges"],
                   policy=policy, min_count_margin=min_count_margin)
    binding_hash = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return dict(**binding, binding_sha256=binding_hash, board=manifest["board"], session=manifest["session"],
                samples_sha256=manifest["samples_sha256"], counts_sha256=manifest["counts_sha256"],
                response_bytes_hex="".join(row["response_hex"] for row in rows),
                valid_mask_bytes_hex="".join(row["valid_mask_hex"] for row in rows),
                valid_bits=sum(int(row["valid_mask_hex"], 16).bit_count() for row in rows), rows=rows,
                scope="Observed enrollment bytes and mask; invalid bits are zero placeholders; no entropy or key derivation claim")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", choices=("unanimous", "majority"), default="unanimous")
    parser.add_argument("--min-count-margin", type=int, default=0)
    args = parser.parse_args()
    result = export(args.session, args.policy, args.min_count_margin)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(f"Exported {len(result['rows'])} bytes; {result['valid_bits']} observed valid bits; policy={args.policy}")


if __name__ == "__main__":
    main()
