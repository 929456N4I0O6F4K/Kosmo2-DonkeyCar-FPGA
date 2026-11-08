"""Generate a board report from validated RO bytes and frequency counts."""
import argparse
import csv
import json
import statistics
from pathlib import Path
from compare import load, summarize, compare, majority
from export_response import export


def report(reference, verification=None):
    manifest,_=load(reference)
    summary=summarize(reference)
    enrollment=export(reference)
    frequency={}
    deltas=[]
    with (Path(reference)/"counts.csv").open(newline="",encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            scale=manifest["system_clock_hz"]*int(row["divider"])/int(row["window_clocks"])
            for side in ("a","b"):
                index=int(row[f"ro_{side}"])
                frequency.setdefault(index,[]).append(int(row[f"count_{side}"])*scale)
            deltas.append(abs(int(row["delta"])))
    frequencies=[dict(oscillator=index,count=len(values),median_hz=statistics.median(values),
                      min_hz=min(values),max_hz=max(values)) for index,values in sorted(frequency.items())]
    result=dict(reference=manifest,summary=summary,enrollment_valid_bits=enrollment["valid_bits"],
                oscillator_frequencies=frequencies,minimum_abs_count_delta=min(deltas),
                median_abs_count_delta=statistics.median(deltas),
                scope="Single-board descriptive counts and repeatability; nominal 50 MHz reference, no environmental or cross-board qualification")
    if verification:
        verify_manifest,verify_samples=load(verification)
        result["verification"]=verify_manifest
        result["repeat_comparison"]=compare(reference,verification,same_board=True)
        errors=bits=ties=changed=comparable=0
        for row in enrollment["rows"]:
            registered=int(row["response_hex"],16); mask=int(row["valid_mask_hex"],16)
            values=verify_samples[row["challenge_index"]]
            for value,tied in values:
                valid=mask & ~tied & 255
                bits+=valid.bit_count(); ties+=(mask & tied).bit_count()
                errors+=((registered ^ value) & valid).bit_count()
            for bit in range(8):
                if (mask>>bit)&1:
                    decision,_,_=majority(values,bit)
                    if decision is not None:
                        comparable+=1; changed+=decision!=((registered>>bit)&1)
        result["enrollment_verification"]=dict(policy="unanimous",registered_bits=enrollment["valid_bits"],
                                               verified_raw_bits=bits,raw_errors=errors,raw_error_rate=errors/bits if bits else None,
                                               equal_count_raw_bits=ties,comparable_majorities=comparable,
                                               majority_changes=changed,unavailable_majorities=enrollment["valid_bits"]-comparable,
                                               scope="Fixed baseline enrollment mask and values; unavailable observations reported separately")
    return result


def markdown(result):
    m=result["reference"]; s=result["summary"]; a=s["aggregate"]
    frequency=result["oscillator_frequencies"]
    repeat_rate="无有效位" if a["repeat_disagreement"] is None else f"{a['repeat_disagreement']:.4%}"
    lines=[f"# RO PUF 板 {m['board']} 实测", "",f"参考会话：`{m['session']}`；位流 SHA256：`{m['bitstream_sha256']}`。", "",
           f"共 {s['challenge_count']} 个挑战 × 32 次，{m['samples']:,} 个八位响应、{m['counter_rows']:,} 对底层计数。每批响应和计数均通过硬件 CRC，所有响应和平局掩码由计数重构核对。", "",
           f"记录条件：{m['conditions']}。上电标记：`{m['power_cycle_id']}`，标记本身不证明实际断电。", "",
           "| 基线指标 | 结果 |", "| --- | --- |",
           f"| 非平局原始位对本会话多数位的不一致 | {a['raw_disagreements']:,}/{a['raw_valid_bits']:,}（{repeat_rate}） |",
           f"| 相等计数的原始位 | {a['equal_count_samples']:,} |",
           f"| 无平局且多数确定的 challenge/lane | {a['majority_valid_bits']:,}/{s['challenge_count']*8:,} |",
           f"| 默认注册掩码保留的观察位数 | {result['enrollment_valid_bits']:,}/{s['challenge_count']*8:,} |",
           f"| 已测 RO 数量 | {len(frequency)}/64 |",
           f"| 标称参考时钟换算的计数频率范围 | {min(v['min_hz'] for v in frequency)/1e6:.3f}–{max(v['max_hz'] for v in frequency)/1e6:.3f} MHz |",
           f"| 绝对计数差最小值 / 中位数 | {result['minimum_abs_count_delta']} / {result['median_abs_count_delta']} |", "",
           "| lane | 本会话不一致率 | 多数为 1 比例 | 无效多数挑战 | 32 次全一致比例 |",
           "| ---: | ---: | ---: | ---: | ---: |"]
    for lane in s["lanes"]:
        percent=lambda value:"无有效位" if value is None else f"{value:.4%}"
        lines.append(f"| {lane['lane']} | {percent(lane['repeat_disagreement'])} | {percent(lane['majority_ones'])} | {lane['tied_challenges']} | {percent(lane['fully_stable_challenges'])} |")
    if "repeat_comparison" in result:
        repeat=result["repeat_comparison"]["aggregate"]; v=result["verification"]
        raw_rate="无有效位" if repeat['raw_error_rate'] is None else f"{repeat['raw_error_rate']:.4%}"
        lines += ["",f"独立验证会话：`{v['session']}`。固定参考会话的多数位，验证原始错误 {repeat['raw_errors_to_reference']:,}/{repeat['verification_bits']:,}（{raw_rate}）；多数位改变 {repeat['majority_differences']}/{repeat['comparable_bits']}，比较排除 {repeat['excluded_ties']} 位。验证中排除相等计数 {repeat['verification_equal_counts_excluded']} 个原始位。",
                  "",f"验证条件：{v['conditions']}。上电标记：`{v['power_cycle_id']}`。"]
        e=result["enrollment_verification"]
        enrolled_rate="无有效位" if e["raw_error_rate"] is None else f"{e['raw_error_rate']:.4%}"
        lines += ["",f"固定基线默认注册掩码的 {e['registered_bits']} 个观察位，第二会话原始错误 {e['raw_errors']}/{e['verified_raw_bits']}（{enrolled_rate}）；注册掩码内相等计数 {e['equal_count_raw_bits']} 次，多数位改变 {e['majority_changes']}/{e['comparable_majorities']}，第二会话多数不可用 {e['unavailable_majorities']} 位。掩码始终来自基线。"]
    lines += ["", "本会话对自身多数位的不一致率是描述性统计；独立会话验证才使用固定参考。不同挑战复用 RO 和比较对，掩码保留数量不能视为独立熵。上述频率基于标称 50 MHz 换算，包含启动/停止相位和参考时钟误差。", "",
              "目前此报告仅覆盖板内采样；A/B 区分度、真实断电复测和温度/供电复测需要另行实测。注册文件提供响应字节和有效位掩码，尚未实现纠错及加密密钥派生。", ""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference",type=Path)
    parser.add_argument("verification",type=Path,nargs="?")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--json-output",type=Path,required=True)
    args=parser.parse_args()
    for path in (args.output,args.json_output):
        if path.exists():
            parser.error(f"Output already exists: {path}")
    result=report(args.reference,args.verification)
    with args.output.open("x",encoding="utf-8") as stream:
        stream.write(markdown(result))
    with args.json_output.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,indent=2); stream.write("\n")
    print(f"Wrote {args.output} and {args.json_output}")


if __name__=="__main__":
    main()
