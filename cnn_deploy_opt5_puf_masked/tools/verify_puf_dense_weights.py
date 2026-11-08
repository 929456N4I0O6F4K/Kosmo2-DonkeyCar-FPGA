"""Verify encoded dense ROMs against the opt5 TFLite and saved enrollment."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import tensorflow as tf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import puf_key_image
import reference as ref
from encode_puf_dense_weights import stable_capture


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_rom(weights, toggle_mask):
    output_channels, taps = weights.shape
    lines = []
    negated_taps = 0
    for tap in range(taps):
        values = weights[:, tap].astype(np.int16)
        if (toggle_mask >> (tap % 144)) & 1:
            values = -values
            negated_taps += 1
        if np.any(values < -128) or np.any(values > 127):
            raise ValueError(f"int8 negation overflow at tap {tap}")
        lines.append(bytes((int(value) & 0xff) for value in values[::-1]).hex())
    return lines, negated_taps, output_channels * negated_taps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--enrollment-key", type=Path, required=True)
    parser.add_argument("--enrollment-key-json", type=Path, required=True)
    parser.add_argument("--production-key", type=Path,
                        default=ROOT / "integration/training/build/board/puf_key.mem")
    args = parser.parse_args()

    capture, key_meta, reference, stable = stable_capture(
        args.capture, args.enrollment_key, args.enrollment_key_json)
    manifest_path = ROOT / "integration/training/build/board/puf_obfuscation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_path = ROOT.parent / manifest["model"]
    if "opt5" not in manifest["model"] or sha256(model_path) != manifest["model_sha256"]:
        raise ValueError("Manifest does not identify the configured opt5 model")
    if manifest["enrollment_capture_sha256"] != sha256(args.capture):
        raise ValueError("Manifest capture hash does not match the supplied enrollment")
    route_path = ROOT.parent / manifest["route_reference"]["relative_path"]
    if sha256(route_path) != manifest["route_reference"]["route_netlist_sha256"]:
        raise ValueError("The opt4 route reference changed after this candidate was generated")
    if manifest["production_key_binding_zero"] is not True:
        raise ValueError("Production key is expected to have zero binding")

    production_key = puf_key_image.read(args.production_key)
    if production_key != dict(mode="drive", binding=0, sign_mask=stable):
        raise ValueError("Production key does not contain zero binding and the enrolled stable mask")
    if manifest["production_key_sha256"] != sha256(args.production_key):
        raise ValueError("Production key hash does not match the manifest")

    interpreter, operators = ref.load_graph(model_path)
    layers = ref.extract_layers(interpreter, operators)
    toggle_mask = reference & stable
    summary = {}
    for index, name in ((5, "stage5_weights.mem"), (6, "stage6_weights.mem")):
        weights = layers[index]["weights"].reshape(layers[index]["weights"].shape[0], -1)
        expected, taps, selected = expected_rom(weights, toggle_mask)
        path = ROOT / "rtl/generated" / name
        actual = path.read_text(encoding="ascii").splitlines()
        if actual != expected:
            raise ValueError(f"{name} differs from the PUF-encoded opt5 TFLite weights")
        if manifest["encoded_mem_sha256"][name] != sha256(path):
            raise ValueError(f"{name} hash does not match the manifest")
        if manifest["layers"][name] != dict(
                taps_transformed=taps, weights_selected_for_negation=selected):
            raise ValueError(f"{name} transformation counts do not match the manifest")
        summary[name] = dict(taps_verified=taps, weights_verified=selected)

    if manifest["stable_symbols"] != stable.bit_count():
        raise ValueError("Stable-symbol count does not match the enrollment")
    if manifest["registered_comparisons"] != key_meta["registered_comparisons"]:
        raise ValueError("Raw comparison count does not match the enrollment")
    if manifest["power_cycle_verified"] != bool(capture.get("power_cycle_verified")):
        raise ValueError("Power-cycle verification status was changed")
    print(json.dumps(dict(result="PASS", layers=summary,
                          production_key_binding_zero=True,
                          power_cycle_verified=manifest["power_cycle_verified"],
                          bitstream_generated=manifest["bitstream_generated"]), indent=2))


if __name__ == "__main__":
    main()
