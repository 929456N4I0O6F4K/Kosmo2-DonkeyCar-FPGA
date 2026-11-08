"""Freeze a checked RO implementation before comparing boards or sessions."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from check_build import ROOT, BASE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    args=parser.parse_args()
    if not args.name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in args.name):
        parser.error("Use a simple new archive name")
    report=ROOT/"build/implementation_validation.json"
    validation=json.loads(report.read_text(encoding="utf-8"))
    for path,expected in validation["hashes"].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:
            raise ValueError(f"Checked implementation changed: {path}")
    target=ROOT/"archive"/args.name
    target.mkdir(parents=True,exist_ok=False)
    for name in ("rtl","constraints","scripts","tools","tests"):
        shutil.copytree(ROOT/name,target/name,ignore=shutil.ignore_patterns("__pycache__"))
    for source,name in ((BASE/"generate_bitstream/ro_puf_top.sbit","ro_puf_top.sbit"),
                        (BASE/"generate_netlist/ro_puf_top_sim.v","ro_puf_top_sim.v"),
                        (BASE/"report_timing/ro_puf_top.rtr","ro_puf_top.rtr"),
                        (report,"implementation_validation.json")):
        shutil.copy2(source,target/name)
    for name in ("README.md","PROTOCOL.md"):
        shutil.copy2(ROOT/name,target/name)
    transport=target/"transport"; transport.mkdir()
    for name in ("jtag_shell.py","jtag_test.py"):
        shutil.copy2(ROOT.parent/"camera/tools"/name,transport/name)
    sim=ROOT/"build/sim"
    if sim.exists():
        logs=target/"simulation_logs"; logs.mkdir()
        for file in sim.glob("*.log"):
            shutil.copy2(file,logs/file.name)
    hashes={p.relative_to(target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in target.rglob("*") if p.is_file()}
    (target/"archive_sha256.json").write_text(json.dumps(hashes,indent=2)+"\n",encoding="utf-8")
    print(f"Frozen {validation['bitstream_sha256']} in {target}")


if __name__=="__main__":
    main()
