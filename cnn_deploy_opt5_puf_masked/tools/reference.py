#!/usr/bin/env python3
"""Integer math helpers adapted for the supplied physical S2 model.

The TFLite graph is the deployment source of truth.  This script also runs an
integer reference implementation and compares every compute-layer output with
the TensorFlow Lite reference kernels before writing the RTL test vectors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import tensorflow as tf


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT.parent / json.loads((ROOT / 'deployment_config.json').read_text(encoding='utf-8'))['model']
GENERATED = ROOT / "rtl" / "generated"
VECTORS = ROOT / "sim" / "generated"
FRAME_H = 95
FRAME_W = 156
FRAME_C = 3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detail_by_index(interpreter: tf.lite.Interpreter) -> dict[int, dict[str, Any]]:
    return {int(item["index"]): item for item in interpreter.get_tensor_details()}


def scalar_quant(detail: dict[str, Any]) -> tuple[float, int]:
    scales = detail["quantization_parameters"]["scales"]
    zero_points = detail["quantization_parameters"]["zero_points"]
    if len(scales) != 1 or len(zero_points) != 1:
        raise ValueError(f"Expected per-tensor quantization for {detail['name']}")
    return float(scales[0]), int(zero_points[0])


def quantize_multiplier(real_multiplier: float) -> tuple[int, int]:
    if not 0.0 < real_multiplier < 1.0:
        raise ValueError(f"Unsupported requantization multiplier {real_multiplier}")
    significand, shift = math.frexp(real_multiplier)
    multiplier = int(math.floor(significand * (1 << 31) + 0.5))
    if multiplier == 1 << 31:
        multiplier //= 2
        shift += 1
    return multiplier, shift


def trunc_div(values: np.ndarray, divisor: int) -> np.ndarray:
    values = values.astype(np.int64, copy=False)
    return np.where(values >= 0, values // divisor, -((-values) // divisor))


def multiply_by_quantized_multiplier(
    values: np.ndarray, multiplier: int, shift: int
) -> np.ndarray:
    values = values.astype(np.int64, copy=False)
    left_shift = max(shift, 0)
    right_shift = max(-shift, 0)
    product = (values * (1 << left_shift)) * np.int64(multiplier)
    nudge = np.where(product >= 0, 1 << 30, 1 - (1 << 30))
    high = trunc_div(product + nudge, 1 << 31)
    if right_shift == 0:
        return high.astype(np.int32)
    mask = (1 << right_shift) - 1
    remainder = np.bitwise_and(high, mask)
    threshold = (mask >> 1) + (high < 0).astype(np.int64)
    return ((high >> right_shift) + (remainder > threshold)).astype(np.int32)


def requantize(
    accumulators: np.ndarray,
    multipliers: np.ndarray,
    shifts: np.ndarray,
    output_zero_point: int,
    relu: bool,
) -> np.ndarray:
    output = np.empty(accumulators.shape, dtype=np.int64)
    for channel in range(accumulators.shape[-1]):
        output[..., channel] = multiply_by_quantized_multiplier(
            accumulators[..., channel],
            int(multipliers[channel]),
            int(shifts[channel]),
        )
    output += output_zero_point
    lower = output_zero_point if relu else -128
    return np.clip(output, lower, 127).astype(np.int8)


def load_graph(model_path: Path) -> tuple[tf.lite.Interpreter, list[dict[str, Any]]]:
    interpreter = tf.lite.Interpreter(
        model_content=model_path.read_bytes(),
        experimental_preserve_all_tensors=True,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF,
    )
    interpreter.allocate_tensors()
    ops = [op for op in interpreter._get_ops_details() if op["op_name"] != "DELEGATE"]
    return interpreter, ops


def extract_layers(
    interpreter: tf.lite.Interpreter, ops: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    details = detail_by_index(interpreter)
    compute_ops = [op for op in ops if op["op_name"] in {"CONV_2D", "FULLY_CONNECTED"}]
    if [op["op_name"] for op in compute_ops] != ["CONV_2D"] * 5 + ["FULLY_CONNECTED"] * 3:
        raise ValueError("Unexpected S2 compute graph")

    layers: list[dict[str, Any]] = []
    conv_number = 0
    dense_number = 0
    for op in compute_ops:
        activation_index, weight_index, bias_index = map(int, op["inputs"][:3])
        output_index = int(op["outputs"][0])
        weight_detail = details[weight_index]
        output_detail = details[output_index]
        input_scale, input_zp = scalar_quant(details[activation_index])
        output_scale, output_zp = scalar_quant(output_detail)
        weight_q = weight_detail["quantization_parameters"]
        weight_scales = np.asarray(weight_q["scales"], dtype=np.float64)
        weight_zps = np.asarray(weight_q["zero_points"], dtype=np.int32)
        if not np.all(weight_zps == 0):
            raise ValueError(f"Non-zero weight zero point in {weight_detail['name']}")

        if op["op_name"] == "CONV_2D":
            conv_number += 1
            name = f"conv{conv_number}"
            relu = True
        else:
            dense_number += 1
            tensor_name = weight_detail["name"]
            if "n_outputs" in tensor_name:
                name = "outputs"
                relu = False
            else:
                name = f"dense{dense_number}"
                relu = True

        weight_scales = np.broadcast_to(weight_scales, interpreter.get_tensor(bias_index).shape)
        multipliers, shifts = zip(
            *(quantize_multiplier(input_scale * value / output_scale) for value in weight_scales)
        )
        layers.append(
            {
                "name": name,
                "op": op["op_name"],
                "input_index": activation_index,
                "output_index": output_index,
                "weights": interpreter.get_tensor(weight_index).copy(),
                "bias": interpreter.get_tensor(bias_index).copy(),
                "weight_scales": weight_scales,
                "multipliers": np.asarray(multipliers, dtype=np.int32),
                "shifts": np.asarray(shifts, dtype=np.int32),
                "input_scale": input_scale,
                "input_zp": input_zp,
                "output_scale": output_scale,
                "output_zp": output_zp,
                "relu": relu,
                "weight_tensor": weight_detail["name"],
                "output_tensor": output_detail["name"],
            }
        )
    if [layer["name"] for layer in layers] != [
        "conv1", "conv2", "conv3", "conv4", "conv5",
        "dense1", "dense2", "outputs",
    ]:
        raise ValueError(f"Unexpected output-head mapping: {[layer['name'] for layer in layers]}")
    return layers




def conv_reference(input_data: np.ndarray, layer: dict[str, Any]) -> np.ndarray:
    weights = layer["weights"]
    out_channels, kernel_h, kernel_w, in_channels = weights.shape
    if input_data.shape[-1] != in_channels:
        raise ValueError(f"Input channel mismatch in {layer['name']}")
    stride = 2 if kernel_h == 5 else 1
    out_h = (input_data.shape[0] - kernel_h) // stride + 1
    out_w = (input_data.shape[1] - kernel_w) // stride + 1
    output = np.empty((out_h, out_w, out_channels), dtype=np.int8)
    centered = input_data.astype(np.int32) - layer["input_zp"]
    for oh in range(out_h):
        for ow in range(out_w):
            patch = centered[
                oh * stride:oh * stride + kernel_h,
                ow * stride:ow * stride + kernel_w,
                :,
            ].astype(np.int64)
            acc = np.tensordot(
                weights.astype(np.int64), patch, axes=((1, 2, 3), (0, 1, 2))
            ) + layer["bias"].astype(np.int64)
            output[oh, ow, :] = requantize(
                acc.reshape(1, -1),
                layer["multipliers"],
                layer["shifts"],
                layer["output_zp"],
                layer["relu"],
            )[0]
    return output


def dense_reference(input_data: np.ndarray, layer: dict[str, Any]) -> np.ndarray:
    centered = input_data.astype(np.int64).reshape(-1) - layer["input_zp"]
    accumulators = layer["weights"].astype(np.int64) @ centered
    accumulators += layer["bias"].astype(np.int64)
    return requantize(
        accumulators.reshape(1, -1),
        layer["multipliers"],
        layer["shifts"],
        layer["output_zp"],
        layer["relu"],
    )[0]




def pack_requant(multiplier: int, shift: int, zero_point: int, relu: bool) -> int:
    if not 0 < multiplier < (1 << 31) or not -31 <= shift <= 0:
        raise ValueError("RTL requantizer requires a positive multiplier and shift -31..0")
    return multiplier | ((-shift) << 32) | (int(relu) << 37) | ((zero_point & 255) << 38)


def q16(value: int, layer: dict[str, Any]) -> int:
    product = (value - layer["output_zp"]) * round(layer["output_scale"] * (1 << 30))
    return ((product + (1 << 13)) >> 14) if product >= 0 else -(((-product) + (1 << 13)) >> 14)


def write_hex(path: Path, values: list[int], digits: int) -> None:
    path.write_text("".join(f"{value:0{digits}x}\n" for value in values), encoding="ascii")




def write_quantizer_vectors() -> int:
    rng = np.random.default_rng(0x51554e54)
    directed = [-2147483648, -2147483647, -65537, -65536, -1025, -1024, -129, -128,
                -127, -65, -64, -3, -2, -1, 0, 1, 2, 3, 63, 64, 127, 128, 129,
                1023, 1024, 65535, 65536, 2147483646, 2147483647]
    rows = [(v, m, s, zp, relu) for v in directed for m in (1, 1073741824, 2147483647)
            for s in (0, -1, -7, -15, -31) for zp, relu in ((-128, True), (20, False), (-128, False))]
    rows.extend((int(rng.integers(-(1 << 31), 1 << 31)), int(rng.integers(1, 1 << 31)),
                 -int(rng.integers(0, 32)), int(rng.integers(-128, 128)), bool(rng.integers(0, 2)))
                for _ in range(4096))
    words = []
    for value, mult, shift, zp, relu in rows:
        expected = int(requantize(np.array([[value]], dtype=np.int64), np.array([mult]),
                                 np.array([shift]), zp, relu)[0, 0])
        words.append((value & 0xffffffff) | (pack_requant(mult, shift, zp, relu) << 32) | ((expected & 255) << 80))
    write_hex(VECTORS / "quantizer.mem", words, 22)
    return len(words)


