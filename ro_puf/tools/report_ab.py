"""Report RO cross-board differences and fixed-reference repeatability."""
import argparse
import json
import os
from pathlib import Path
from compare import compare
from report_board import report


def build_report(a_reference, a_verification, b_reference, b_verification):
    a = report(a_reference, a_verification)
    b = report(b_reference, b_verification)
    pairs = [compare(left, right) for left in (a_reference, a_verification)
             for right in (b_reference, b_verification)]
    captures = []
    for folder, manifest in zip((a_reference, a_verification, b_reference, b_verification),
                                (a["reference"], a["verification"], b["reference"], b["verification"])):
        captures.append(dict(folder=Path(folder).as_posix(), manifest=manifest))
    return dict(firmware="ro_puf_v1", bitstream_sha256=pairs[0]["bitstream_sha256"],
                scope="Two physical boards, two sessions each; shared RO comparisons; no confirmed cold-boot or environmental qualification",
                captures=captures, boards=dict(A=a, B=b), between_boards=pairs,
                total_response_bytes=sum(c["manifest"]["samples"] for c in captures),
                total_counter_pairs=sum(c["manifest"]["counter_rows"] for c in captures))


def pct(value):
    return "无可比较位" if value is None else f"{value:.3%}"


def markdown(result, output, json_output):
    primary = result["between_boards"][0]
    total = primary["aggregate"]
    a, b = result["boards"]["A"], result["boards"]["B"]
    held_a = a["repeat_comparison"]["aggregate"]
    held_b = b["repeat_comparison"]["aggregate"]
    def rel(path):
        return Path(os.path.relpath(Path(path).resolve(), Path(output).parent.resolve())).as_posix()
    lines = ["# Kosmo RO PUF A/B 对照", "",
             f"同一冻结七级 RO 位流、相同 {primary['challenge_count']} 个挑战，每挑战 32 次原始响应，两板各两轮。共 {result['total_response_bytes']:,} 个响应字节和 {result['total_counter_pairs']:,} 对计数。两板基线多数位差异为 **{total['majority_differences']}/{total['comparable_bits']} = {pct(total['ab_majority_hamming'])}**，任一侧无效多数排除 {total['excluded_ties']} 位。", "",
             f"固定各板首轮多数位验证第二轮，A 原始错误率为 **{pct(held_a['raw_error_rate'])}**，B 为 **{pct(held_b['raw_error_rate'])}**。", "",
             f"位流 SHA256：`{result['bitstream_sha256']}`。完整机器可读记录见 [{Path(json_output).name}]({rel(json_output)})。", "",
             "## 会话与校验", "",
             "每批次通过响应 CRC32 和全部计数 CRC32，再以底层计数重构响应和平局掩码。报告生成时重新核对 CSV 哈希、顺序、计数条件与完整性。板标签由操作员指定，JTAG ID 只用于确认器件型号。", "",
             "| 板 | 会话 | 响应字节 | 计数对 | 上电记录 |", "| --- | --- | ---: | ---: | --- |"]
    for capture in result["captures"]:
        m = capture["manifest"]
        lines.append(f"| {m['board']} | [{m['session']}]({rel(Path(capture['folder'])/'manifest.json')}) | {m['samples']} | {m['counter_rows']} | {m['power_cycle_id']} |")
    lines += ["", "裸板、标称 50 MHz 参考、每对 RO 测量 1 ms，计数前除以 16；温度和电压未仪器记录。同板重复采集期间未要求断电，上电标记不能证明真实冷启动。实际条件保存在各 manifest 中。", "",
              "## 逐路板间差异", "",
              "多数位排除任意一次相等计数或投票平局的 challenge/lane。1 占比各自使用该板有效基线多数位，A/B 差异使用两板可比较位的交集；整体差异用计数总数加权。", "",
              "| lane | A 多数为 1 | B 多数为 1 | A/B 差异/可比较 | A/B 差异率 | A/B 无效多数数 |",
              "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    for lane, la, lb in zip(primary["lanes"], a["summary"]["lanes"], b["summary"]["lanes"]):
        lines.append(f"| {lane['lane']} | {pct(la['majority_ones'])} | {pct(lb['majority_ones'])} | {lane['majority_differences']}/{lane['comparable_challenges']} | {pct(lane['ab_majority_hamming'])} | {la['tied_challenges']}/{lb['tied_challenges']} |")
    lines += ["", "## 固定参考的同板验证", "",
              "| 板 | 第二轮原始错误/有效原始位 | 错误率 | 多数位变化/可比较 | 多数比较排除位 |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for board, data in (("A", a), ("B", b)):
        v = data["repeat_comparison"]["aggregate"]
        lines.append(f"| {board} | {v['raw_errors_to_reference']}/{v['verification_bits']} | {pct(v['raw_error_rate'])} | {v['majority_differences']}/{v['comparable_bits']} | {v['excluded_ties']} |")
    lines += ["", "## 四种 A/B 会话组合", "",
              "以两板基线对照为主结果，另三种组合观察采集变化。它们复用两块板和同一组数据，不能当作四对独立器件。", "",
              "| A 会话 | B 会话 | 差异/可比较 | 差异率 | 排除位 |", "| --- | --- | ---: | ---: | ---: |"]
    for pair in result["between_boards"]:
        v = pair["aggregate"]
        lines.append(f"| {pair['board_a']} | {pair['board_b']} | {v['majority_differences']}/{v['comparable_bits']} | {pct(v['ab_majority_hamming'])} | {v['excluded_ties']} |")
    lines += ["", "## 固定注册掩码的验证", "",
              "默认注册仅保留首轮 32 次全一致且无平局的位。掩码和参考响应固定后计算第二轮错误；第二轮不可用观察单独报告。", "",
              "| 板 | 基线注册观察位 | 第二轮原始错误/有效位 | 错误率 | 相等计数次数 | 多数位变化/可比较 | 多数不可用位 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for board, data in (("A", a), ("B", b)):
        e = data["enrollment_verification"]
        lines.append(f"| {board} | {e['registered_bits']} | {e['raw_errors']}/{e['verified_raw_bits']} | {pct(e['raw_error_rate'])} | {e['equal_count_raw_bits']} | {e['majority_changes']}/{e['comparable_majorities']} | {e['unavailable_majorities']} |")
    lines += ["", "## 计数与边界", "",
              "| 板 | 基线已测 RO 数 | 标称计数频率范围 | 绝对计数差中位数 |", "| --- | ---: | ---: | ---: |"]
    for board, data in (("A", a), ("B", b)):
        frequencies = data["oscillator_frequencies"]
        lo, hi = min(f["min_hz"] for f in frequencies), max(f["max_hz"] for f in frequencies)
        lines.append(f"| {board} | {len(frequencies)}/64 | {lo/1e6:.3f}–{hi/1e6:.3f} MHz | {data['median_abs_count_delta']} |")
    lines += ["", "RO 在多个挑战中复用，比较位存在相关性；注册观察位数和响应长度不能作为独立熵位数。本报告描述这两块板的差异和短期重复性，尚未验证器件群体唯一性、真实断电、温度/供电变化或加密密钥恢复。物理 tile 已固定，全部路径尚未锁定；所测差异包含该实现的位置与布线影响。", "",
              "原始输出与 APUF 保持八位响应及 CSV 形式，但两类挑战映射和样本规模不同，跨类型数值只能作初步参考。接口见 [PROTOCOL](../PROTOCOL.md)，板内明细见 [A 报告](A_ro7_20261009.md)和 [B 报告](B_ro7_20261009.md)。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("a_reference", "a_verification", "b_reference", "b_verification"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.json_output.exists():
        parser.error("Use new output paths; existing reports are preserved")
    result = build_report(args.a_reference, args.a_verification, args.b_reference, args.b_verification)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(markdown(result, args.output, args.json_output))
    with args.json_output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2); stream.write("\n")
    print(f"Wrote {args.output} and {args.json_output}")


if __name__ == "__main__":
    main()
