"""Run real RTL crop/CNN/requantizer tests; never connects to a board."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import puf_key_image


def write_key_fixtures(out):
    """Fixed, non-board key images for tb_puf_key_store."""
    binding=0x9a3c_5e71_0f2d_8b46_c193_e05a_77d1_24bf_6c08&((1<<144)-1)
    sign_mask=0xffff_7f3e_fdbf_ffef_d77f_ffff_fbff_df7f_eef7
    puf_key_image.write(out/'key_drive.mem','drive',binding,sign_mask)
    puf_key_image.write(out/'key_capture.mem','capture')
    bad=puf_key_image.words('drive',binding,sign_mask)
    bad[16]^=1
    (out/'key_bad.mem').write_text(''.join(f'{w:05x}\n' for w in bad),encoding='ascii')
    assert puf_key_image.read(out/'key_drive.mem')==dict(mode='drive',binding=binding,sign_mask=sign_mask)
    (out/'key_fixture.vh').write_text(f"localparam [143:0] TEST_BINDING=144'h{binding:036x};\n"
                                      f"localparam [143:0] TEST_SIGN_MASK=144'h{sign_mask:036x};\n")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vivado-bin', type=Path, default=Path('C:/AMDDesignTools/2025.2/Vivado/bin'))
    args=parser.parse_args()
    out=ROOT/'build/sim'
    out.mkdir(parents=True,exist_ok=True)
    for folder in (ROOT/'rtl/generated',ROOT/'sim/generated'):
        for p in folder.iterdir():
            if p.suffix in ('.mem','.vh'):
                shutil.copyfile(p,out/p.name)
    manifest=json.loads((ROOT/'model_manifest.json').read_text())
    first=manifest['cases'][0]
    write_key_fixtures(out)
    (out/'recovery_case.vh').write_text(f'run_case("{first["name"]}", {first["steering_q16"]}, {first["throttle_q16"]});\n')
    def run(label,cmd,marker=None):
        logpath=out/(label+'.log')
        with logpath.open('w') as f:
            result=subprocess.run([str(v) for v in cmd],cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=1200)
        log=logpath.read_text(errors='replace')
        if result.returncode or any(v in log for v in ('FATAL','Fatal','ERROR:')) or (marker and marker not in log):
            raise RuntimeError(f'{label} failed:\n{log[-7000:]}')
        print('\n'.join(line for line in log.splitlines() if 'PASS' in line),flush=True)
        return log
    files=sorted((ROOT/'rtl').glob('*.v'))+[ROOT/'rtl/generated/mypilot_parameters.v']+sorted((ROOT/'sim').glob('*.sv'))
    run('compile',[args.vivado_bin/'xvlog.bat','-sv',*files,'-i',out,'-i',ROOT/'rtl/generated'])
    for top,marker in [('tb_requantize','MYPILOT_REQUANT_RTL PASS'),('tb_crop_timeout','CROP_TIMEOUT PASS'),
                       ('tb_puf_enroll','PUF_ENROLL_MAJORITY PASS'),
                       ('tb_ro_puf_enroll','RO_PUF_ENROLL PASS'),
                       ('tb_puf_binding','PUF_BINDING PASS'),('tb_puf_key_store','PUF_KEY_STORE PASS'),
                       ('tb_pipeline','PIPELINE_ALL PASS')]:
        run(top+'_elaborate',[args.vivado_bin/'xelab.bat','-debug','typical',top,'-s',top])
        run(top,[args.vivado_bin/'xsim.bat',top,'-runall'],marker)
    rows=list(csv.DictReader((out/'pipeline_results.csv').open()))
    assert len(rows)==len(manifest['cases'])+3
    max_cycles=max(int(r['total_cycles']) for r in rows)
    result=dict(success=True,board_access=False,clock_mhz=50,
                model_sha256=manifest['model_sha256'],frames=len(rows),
                exact_layer_bytes=sum(int(r['exact_layer_bytes']) for r in rows),
                exact_crop_bytes=sum(int(r['exact_crop_bytes']) for r in rows),
                max_processing_cycles=max_cycles,processing_ms_at_50mhz=max_cycles/50000,
                compute_only_fps_at_50mhz=50000000/max_cycles,
                watchdog_ms=50,watchdog_infer_recovery=True,watchdog_crop_recovery=True,
                result_backpressure=True,unread_result_expiry_recovery=True,
                result_hold_cycles_test=64,result_hold_cycles_default=500000,
                busy_frame_rejection=True,repeat_without_reset=True,
                puf_matching_vector_exact=True,puf_refresh_isolated_per_frame=True,
                limitation='Cycle timing at 50 MHz is simulation; no placed timing or sensor-to-actuator latency implied.',
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    main()
