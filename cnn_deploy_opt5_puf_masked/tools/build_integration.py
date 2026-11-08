"""Build the isolated full camera/CNN/AXI/PCA9685 FPGA image."""
from pathlib import Path
import subprocess
import sys
import time
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
TRAIN=ROOT/'integration/training'


def main():
    output=TRAIN/'build/board'
    output.mkdir(parents=True,exist_ok=True)
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for folder in [ROOT/'rtl',ROOT/'integration/training/rtl',ROOT/'integration/training/board',ROOT/'integration/training/scripts',ROOT/'integration/camera/rtl',ROOT/'integration/actuators/rtl']
             for p in folder.rglob('*') if p.is_file()}
    (output/'source_sha256.json').write_text(json.dumps(sources,indent=2)+'\n')
    with (output/'build.log').open('w') as log:
        code=subprocess.call(['C:/pango/PDS_2025.2-ads/bin/pds_shell.exe','-file',
                              (TRAIN/'scripts/build_board.tcl').as_posix()],cwd=output,stdout=log,stderr=subprocess.STDOUT)
    tail=(output/'build.log').read_text(errors='replace')[-4000:]
    print(tail)
    if code or 'TRAINING_BOARD_BUILD_FINISHED' not in tail:
        raise SystemExit('Integrated FPGA build failed; inspect build/board/build.log')
    for name,digest in sources.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise SystemExit('Build inputs changed: '+name)
    print('INTEGRATED FPGA BUILD PASS')
    (output/'build-validation.txt').write_text('INTEGRATED FPGA BUILD PASS\n')


if __name__=='__main__':
    main()
