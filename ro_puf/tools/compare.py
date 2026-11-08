"""Validate both RO CSVs and report comparable APUF-style per-lane statistics."""
import argparse
import csv
import hashlib
import json
import zlib
from pathlib import Path
from capture import decode_batch,pair_indices,MAX_COUNT,WINDOW_CLOCKS,DIVIDER,COUNTER_INPUT_LIMIT_HZ,MAPPING


def load(folder):
    folder=Path(folder)
    manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status")!="complete" or manifest.get("firmware")!="ro_puf_v1":
        raise ValueError("Need a complete separate RO PUF capture")
    expected_parameters=dict(ro_stages=7,oscillator_count=64,window_clocks=WINDOW_CLOCKS,divider=DIVIDER,
                             system_clock_hz=50_000_000,counter_input_limit_hz=COUNTER_INPUT_LIMIT_HZ,
                             challenge_mapping=MAPPING)
    if any(manifest.get(key)!=value for key,value in expected_parameters.items()):
        raise ValueError("Capture measurement parameters or mapping differ")
    if manifest["repeats"]!=32 or not manifest["challenges"] or len(set(manifest["challenges"]))!=len(manifest["challenges"]):
        raise ValueError("Invalid challenge/repeat manifest")
    for name in ("samples","counts"):
        if hashlib.sha256((folder/f"{name}.csv").read_bytes()).hexdigest()!=manifest[f"{name}_sha256"]:
            raise ValueError("Raw CSV hash mismatch")
    with (folder/"samples.csv").open(newline="",encoding="utf-8") as stream:
        rows=list(csv.DictReader(stream))
    with (folder/"counts.csv").open(newline="",encoding="utf-8") as stream:
        counters=list(csv.DictReader(stream))
    expected=len(manifest["challenges"])*32
    if len(rows)!=expected or len(counters)!=expected*8 or manifest["samples"]!=expected or manifest["counter_rows"]!=expected*8:
        raise ValueError("Incomplete sample or counter rows")
    samples={}
    for position,index in enumerate(manifest["challenges"]):
        raw=rows[position*32:(position+1)*32]
        count_rows=counters[position*256:(position+1)*256]
        data=bytearray(); ties=bytearray(); packed=bytearray()
        for repeat,row in enumerate(raw):
            if int(row["challenge_index"])!=index or int(row["repeat"])!=repeat or row["arrived_hex"]!="ff":
                raise ValueError("Missing, duplicated or reordered response")
            status=int(row["status_hex"],16)
            if (status>>32)&65535!=index or status>>48!=0x5258:
                raise ValueError("Stored challenge/firmware mismatch")
            if row["batch_crc32"]!=raw[0]["batch_crc32"] or row["counts_crc32"]!=raw[0]["counts_crc32"] or row["status_hex"]!=raw[0]["status_hex"]:
                raise ValueError("Batch metadata changed between rows")
            data.append(int(row["response_hex"],16)); ties.append(int(row["tie_mask_hex"],16))
            for lane in range(8):
                counter=count_rows[repeat*8+lane]
                a,b=int(counter["count_a"]),int(counter["count_b"])
                if (int(counter["challenge_index"]),int(counter["repeat"]),int(counter["lane"]))!=(index,repeat,lane):
                    raise ValueError("Missing, duplicated or reordered counter")
                if (int(counter["ro_a"]),int(counter["ro_b"]))!=pair_indices(index,lane) or int(counter["delta"])!=a-b:
                    raise ValueError("RO mapping or signed delta mismatch")
                if int(counter["window_clocks"])!=WINDOW_CLOCKS or int(counter["divider"])!=DIVIDER:
                    raise ValueError("Counter measurement conditions differ")
                if not 0<a<=MAX_COUNT or not 0<b<=MAX_COUNT:
                    raise ValueError("RO counter outside validated range")
                packed.extend(a.to_bytes(3,"little")); packed.extend(b.to_bytes(3,"little"))
        info=(0x5231<<48)|(32<<40)|(((status>>24)&255)<<32)|int(raw[0]["batch_crc32"],16)
        decode_batch(status,bytes(data),info,bytes(packed),int(raw[0]["counts_crc32"],16),bytes(ties))
        samples[index]=list(zip(data,ties))
    return manifest,samples


def majority(values,bit):
    valid=[(value>>bit)&1 for value,ties in values if not (ties>>bit)&1]
    ones=sum(valid)
    # Conservative enrollment: any equal-count sample makes this challenge/lane
    # unavailable. Raw response bytes remain in CSV exactly as observed.
    decided=None if len(valid)!=len(values) or ones*2==len(valid) else int(ones*2>len(valid))
    return decided,min(ones,len(valid)-ones),len(values)-len(valid)


def summarize(folder):
    manifest,samples=load(folder)
    lanes=[]
    for bit in range(8):
        decisions=[]; errors=ties=stable=0
        for values in samples.values():
            decision,error,tied=majority(values,bit)
            decisions.append(decision); errors+=error; ties+=tied
            stable+=error==0 and tied==0
        count=len(samples); valid_bits=count*32-ties
        lanes.append(dict(lane=bit,repeat_disagreement=errors/valid_bits if valid_bits else None,
                          majority_ones=sum(v==1 for v in decisions)/sum(v is not None for v in decisions) if any(v is not None for v in decisions) else None,
                          tied_challenges=sum(v is None for v in decisions),equal_count_samples=ties,
                          fully_stable_challenges=stable/count))
    total_valid=len(samples)*256-sum(v["equal_count_samples"] for v in lanes)
    total_errors=sum(majority(values,bit)[1] for values in samples.values() for bit in range(8))
    return dict(board=manifest["board"],session=manifest["session"],firmware=manifest["firmware"],
                bitstream_sha256=manifest["bitstream_sha256"],challenge_count=len(samples),repeats=32,lanes=lanes,
                aggregate=dict(repeat_disagreement=total_errors/total_valid if total_valid else None,
                               raw_disagreements=total_errors,raw_valid_bits=total_valid,
                               equal_count_samples=len(samples)*256-total_valid,
                               majority_valid_bits=len(samples)*8-sum(v["tied_challenges"] for v in lanes)))


def compare(a_dir,b_dir,same_board=False):
    a,sa=load(a_dir); b,sb=load(b_dir)
    if a["bitstream_sha256"]!=b["bitstream_sha256"] or a["challenges"]!=b["challenges"]:
        raise ValueError("Bitstream or challenge sequence differs")
    if same_board:
        if a["board"]!=b["board"] or Path(a_dir).resolve()==Path(b_dir).resolve():
            raise ValueError("Need independent sessions of the same board")
    elif a["board"]!="A" or b["board"]!="B":
        raise ValueError("Expected A followed by B")
    lanes=[]
    for bit in range(8):
        differences=compared=errors=bits=ref_excluded=raw_ties=0
        for index,values in sa.items():
            av,_,_=majority(values,bit); bv,_,_=majority(sb[index],bit)
            if av is not None and bv is not None:
                differences+=av!=bv; compared+=1
            if av is None:
                ref_excluded+=1
            else:
                for value,tie in sb[index]:
                    if (tie>>bit)&1:
                        raw_ties+=1
                    else:
                        errors+=((value>>bit)&1)!=av; bits+=1
        lane=dict(lane=bit,comparable_challenges=compared,majority_differences=differences,
                  ab_majority_hamming=differences/compared if compared else None,
                  reference_ties_excluded=ref_excluded)
        if same_board:
            lane.update(verification_bits=bits,raw_errors_to_reference=errors,raw_error_rate=errors/bits if bits else None,
                        verification_equal_counts_excluded=raw_ties,comparable_majorities=compared,
                        majority_disagreements=differences,majority_error_rate=differences/compared if compared else None)
        lanes.append(lane)
    differences=sum(v["majority_differences"] for v in lanes); comparable=sum(v["comparable_challenges"] for v in lanes)
    aggregate=dict(majority_differences=differences,comparable_bits=comparable,
                   excluded_ties=len(sa)*8-comparable,ab_majority_hamming=differences/comparable if comparable else None)
    if same_board:
        bits=sum(v["verification_bits"] for v in lanes)
        errors=sum(v["raw_errors_to_reference"] for v in lanes)
        aggregate.update(verification_bits=bits,raw_errors_to_reference=errors,
                         raw_error_rate=errors/bits if bits else None,
                         verification_equal_counts_excluded=sum(v["verification_equal_counts_excluded"] for v in lanes))
    return dict(board_a=a["session"],board_b=b["session"],comparison_type="same_board" if same_board else "A_B",
                bitstream_sha256=a["bitstream_sha256"],
                challenge_count=len(sa),scope="Conservative majority excludes any equal-count challenge/lane; power history recorded separately",
                lanes=lanes,aggregate=aggregate)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a",type=Path); parser.add_argument("b",type=Path,nargs="?")
    parser.add_argument("--same-board",action="store_true"); parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.same_board and not args.b:
        parser.error("--same-board needs a second independent session")
    result=compare(args.a,args.b,args.same_board) if args.b else summarize(args.a)
    text=json.dumps(result,indent=2)+"\n"
    if args.output:
        with args.output.open("x",encoding="utf-8") as stream:
            stream.write(text)
    print(text)


if __name__=="__main__":
    main()
