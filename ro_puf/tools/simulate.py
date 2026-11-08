"""Verify real counter/control RTL with deterministic clock and DVIO substitutes."""
import subprocess
from pathlib import Path
from capture import ROOT, decode_batch

BIN=Path("C:/AMDDesignTools/2025.2/Vivado/bin")
OUT=ROOT / "build/sim"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    commands=[
        [BIN/"xvlog.bat",ROOT/"rtl/ro_counter.v",ROOT/"rtl/ro_puf_top.v",ROOT/"tests/tb_control.v"],
        [BIN/"xelab.bat","tb_control","-s","ro_control_sim","--timescale","1ns/1ps"],
        [BIN/"xsim.bat","ro_control_sim","-runall"],
    ]
    for name,command in zip(("compile","elaborate","run"),commands):
        log=OUT/f"{name}.log"
        with log.open("w",encoding="utf-8") as stream:
            result=subprocess.run(list(map(str,command)),cwd=OUT,stdout=stream,stderr=subprocess.STDOUT)
        text=log.read_text(encoding="utf-8",errors="replace")
        if result.returncode or "FATAL" in text or "Fatal" in text:
            raise RuntimeError(text[-5000:])
    if "PASS RO control:" not in text:
        raise RuntimeError("Simulation pass marker missing")
    print(next(line for line in text.splitlines() if "PASS RO control:" in line))
    frames=(OUT/"frames.hex").read_text().splitlines()
    counts=(OUT/"counts.hex").read_text().splitlines()
    if len(frames)!=2 or len(counts)!=512:
        raise RuntimeError("Simulation did not save two complete count batches")
    for batch,line in enumerate(frames):
        status,response,crc,count_crc,ties=map(lambda value:int(value,16),line.split())
        raw=b"".join(int(value,16).to_bytes(6,"little") for value in counts[batch*256:(batch+1)*256])
        info=(0x5231<<48)|(32<<40)|(((status>>24)&255)<<32)|crc
        decode_batch(status,response.to_bytes(32,"little"),info,raw,count_crc,ties.to_bytes(32,"little"))
    print("PASS all 512 raw counter pairs, response/tie reconstruction, both hardware CRC32 values against Python zlib")


if __name__=="__main__":
    main()
