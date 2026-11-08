"""Verify camera/AXI/control regressions and real CNN/DMA ownership."""
from pathlib import Path
import subprocess
import shutil
import json
import hashlib

ROOT=Path(__file__).resolve().parents[1]
TRAIN=ROOT/'integration/training'
BIN=Path('C:/AMDDesignTools/2025.2/Vivado/bin')


def main():
    subprocess.run(['python','tools/simulate_transport.py'],cwd=TRAIN,check=True)
    subprocess.run(['python','tools/simulate_drive.py'],cwd=TRAIN,check=True)
    out=TRAIN/'build/cnn-bridge-sim';out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/'model_manifest.json').read_text())
    cases=manifest['cases'][:2]
    for folder in [ROOT/'rtl/generated',ROOT/'sim/generated']:
        for path in folder.iterdir():
            if path.suffix in ('.mem','.vh'):shutil.copyfile(path,out/path.name)
    (out/'bridge_cases.vh').write_text('\n'.join(f'run_case("{c["name"]}", {c["steering_q16"]}, {c["throttle_q16"]});' for c in cases))
    sources=[*sorted((ROOT/'rtl').glob('*.v')),ROOT/'rtl/generated/mypilot_parameters.v',TRAIN/'rtl/kosmo_cnn_bridge.v',TRAIN/'sim/tb_cnn_bridge.sv']
    commands=[ [BIN/'xvlog.bat','-sv',*sources,'-i',out],
              [BIN/'xelab.bat','-debug','typical','tb_cnn_bridge','-s','bridge_sim'],
              [BIN/'xsim.bat','bridge_sim','-runall'] ]
    for i,cmd in enumerate(commands):
        path=out/f'{i}.log'
        with path.open('w') as log:
            r=subprocess.run(list(map(str,cmd)),cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
        text=path.read_text(errors='replace')
        if r.returncode or any(s in text for s in ['FATAL','Fatal','ERROR:']):raise RuntimeError(text[-4000:])
    if 'CNN_BRIDGE_ALL PASS' not in text:raise RuntimeError(text[-4000:])
    print(text[-1800:])
    result={'success':True,'transport_abi':4,'real_cnn_same_frame_cases':len(cases),'watchdog_unblocks_dma':True,
            'fault_latches_stop':True,'dma_backpressure_no_duplicate_inference':True,
            'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
