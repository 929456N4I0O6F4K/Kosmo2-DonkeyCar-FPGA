"""Simulate the meter pin driver without encrypted vendor JTAG IP."""
import argparse
import json
from pathlib import Path
from simulate import ROOT, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vivado',type=Path,default=Path('C:/AMDDesignTools/2025.2/Vivado'))
    args = parser.parse_args()
    bindir = args.vivado/'bin'
    out = ROOT/'build/sim_meter'
    out.mkdir(parents=True,exist_ok=True)
    run([bindir/'xvlog.bat',ROOT/'meter/camera_meter_core.v',ROOT/'meter/sim/tb_camera_meter.v'],out,out/'compile.log')
    run([bindir/'xelab.bat','tb_camera_meter','-s','meter_sim','-debug','typical'],out,out/'elaborate.log')
    text = run([bindir/'xsim.bat','meter_sim','-runall'],out,out/'run.log')
    assert 'ALL CAMERA METER TESTS PASS' in text
    checks = dict(static_modes=True,open_drain_no_high_drive=True,external_held_low_readback=True,
                  invalid_command_guard=True,repeated_token_guard=True,reset_releases_lines=True)
    (out/'validation.json').write_text(json.dumps(checks,indent=2)+'\n',encoding='utf-8')
    print('\n'.join(line for line in text.splitlines() if 'TESTS PASS' in line))


if __name__ == '__main__':
    main()
