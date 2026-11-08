"""Check native RO feedback, LUT truth tables, actual placement and counter timing."""
import hashlib
import json
import re
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"build/pds/prj_tasks/pnr_1"


def main():
    netfile=BASE/"generate_netlist/ro_puf_top_sim.v"
    timingfile=BASE/"report_timing/ro_puf_top.rtr"
    image=BASE/"generate_bitstream/ro_puf_top.sbit"
    sources=[*sorted((ROOT/"rtl").glob("*.v")),*sorted((ROOT/"constraints").glob("*")),ROOT/"scripts/build.tcl"]
    if any(p.stat().st_mtime>image.stat().st_mtime for p in sources):
        raise RuntimeError("Implementation predates current sources; complete a new build first")
    text=netfile.read_text(encoding="utf-8")
    timing=timingfile.read_text(encoding="utf-8")
    if "Design Summary : All Constraints Met." not in timing:
        raise RuntimeError("RO/counter/system timing constraints failed")
    for clock in ("sysclk_50","ro_a","ro_b","ro_a_div16","ro_b_div16"):
        if not re.search(rf"^\s*{clock}\s+",timing,re.M):
            raise RuntimeError(f"Missing constrained clock {clock}")
    for clock,period in (("ro_a",1.666667),("ro_b",1.666667),("ro_a_div16",26.666672),("ro_b_div16",26.666672)):
        measured=float(re.search(rf"^\s*{clock}\s+([0-9.]+)",timing,re.M).group(1))
        if abs(measured-period)>0.0001:
            raise RuntimeError(f"Counter timing bound differs: {clock} {measured}")
    expected={(r["oscillator"],r["stage"]):r for r in json.loads((ROOT/"constraints/ro_layout.json").read_text())}
    found={}
    pattern=r'\(\* PAP_BLE_DEF="([A-D])" \*\)\s+V_LUT6CARRY /\* (CLMA_\d+_\d+) \*/ #(.*?)\);'
    for block in re.finditer(pattern,text,re.S):
        body=block.group(3)
        cell=re.search(r'\\(bank/osc\[(\d+)\]\.ro_unit/(gate0|inv[1-6])/[^\s]+)',body)
        if not cell:
            continue
        oscillator=int(cell.group(2))
        stage=0 if cell.group(3)=="gate0" else int(cell.group(3)[3:])
        key=(oscillator,stage)
        if key in found or key not in expected or block.group(2)!=expected[key]["target"]:
            raise RuntimeError(f"Missing, duplicated or misplaced native RO stage: {key}")
        init=int(re.search(r"\.INIT\(64'h([0-9a-fA-F]+)\)",body).group(1),16)
        pins={int(p):v.strip() for p,v in re.findall(r'\.I([0-5])\s*\(([^)]*)\)',body)}
        output=re.search(r'\.Z\s*\(([^)]*)\)',body).group(1).strip()
        found[key]=dict(oscillator=oscillator,stage=stage,tile=block.group(2),ble=block.group(1),pins=pins,output=output,init=init)
    if len(found)!=448:
        raise RuntimeError(f"Expected 448 native LUT stages, got {len(found)}")
    for key,row in found.items():
        oscillator,stage=key
        pins=row["pins"]; init=row["init"]
        previous=found[(oscillator,(stage-1)%7)]["output"]
        normalize=lambda value: re.sub(r'\s+', '',value).lstrip('\\')
        feedback=[p for p,v in pins.items() if normalize(v)==normalize(previous)]
        if len(feedback)!=1:
            raise RuntimeError(f"RO feedback is not preserved: {key}")
        feedback=feedback[0]
        dynamic=[p for p,v in pins.items() if v.startswith("\\bank/") and p!=feedback]
        if (stage==0 and len(dynamic)!=1) or (stage!=0 and dynamic):
            raise RuntimeError(f"Unexpected dynamic LUT inputs: {key}")
        for value in range(64):
            wanted=1-((value>>feedback)&1)
            if stage==0:
                wanted=1-(((value>>feedback)&1)&((value>>dynamic[0])&1))
            if ((init>>value)&1)!=wanted:
                raise RuntimeError(f"Native LUT is not the intended inverter/NAND: {key}")
        row.update(feedback_pin=feedback,enable_pin=dynamic[0] if dynamic else None)
    for buffer,width in (("count_page",1536),("batch_ties",256)):
        retained=set(map(int,re.findall(rf'\.Q\s*\({buffer}\s*\[(\d+)\]\)',text)))
        if retained!=set(range(width)):
            raise RuntimeError(f"Raw buffer lost: {buffer}; {len(retained)}/{width} registered bits")
    if "count_memory/gopdrm" not in text:
        raise RuntimeError("Raw count RAM lost")
    if image.stat().st_size<100000:
        raise RuntimeError("Image absent or implausibly small")
    files=[*sources,netfile,timingfile,image]
    report=dict(utc=datetime.now(timezone.utc).isoformat(),firmware="ro_puf_v1",oscillators=64,ro_stages=7,native_lut_stages=448,
                native_truth_tables_checked=True,feedback_checked=True,placement_checked=True,timing_constraints_met=True,
                counter_input_limit_hz=600_000_000,bitstream_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                actual_stages=[found[k] for k in sorted(found)],
                hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                scope="Native structure and fixed tiles verified; routing is not locked; no proof of PUF entropy or cross-board quality")
    (ROOT/"build/implementation_validation.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("RO_BUILD_CHECK PASS: 64 intact seven-LUT loops, truth tables, fixed tiles, full raw buffers, counter/system timing")
    print("Bitstream SHA256:",report["bitstream_sha256"])


if __name__=="__main__":
    main()
