"""Run the actual FPGA RTL with AMD XSim, then validate its UART packet in Python."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run(cmd,cwd,logfile):
    with logfile.open('w',encoding='utf-8') as out:
        result=subprocess.run([str(x) for x in cmd],cwd=cwd,stdout=out,stderr=subprocess.STDOUT)
    text=logfile.read_text(encoding='utf-8',errors='replace')
    if result.returncode or 'FATAL:' in text or 'Fatal:' in text:
        print(text[-10000:]); raise RuntimeError(f'failed: {cmd[0]}; see {logfile}')
    return text

def main():
    p=argparse.ArgumentParser(); p.add_argument('--vivado',type=Path,default=Path('C:/AMDDesignTools/2025.2/Vivado'))
    args=p.parse_args(); bindir=args.vivado/'bin'
    out=ROOT/'build/sim'; out.mkdir(parents=True,exist_ok=True)
    sources=sorted((ROOT/'rtl').glob('*.v'))+sorted((ROOT/'sim').glob('*.v'))
    run([bindir/'xvlog.bat',*sources],out,out/'compile.log')
    for top in ['tb_camera_top','tb_camera_capture','tb_camera_jtag_bridge','tb_camera_sccb_slow','tb_camera_monitor','tb_camera_exposure']:
        if not (ROOT/'sim'/f'{top}.v').exists(): continue
        run([bindir/'xelab.bat',top,'-s',top+'_sim','-debug','typical'],out,out/f'{top}_elaborate.log')
        text=run([bindir/'xsim.bat',top+'_sim','-runall'],out,out/f'{top}.log')
        if 'ALL CAMERA' not in text or 'TESTS PASS' not in text: raise RuntimeError(f'{top}: missing pass marker')
        print('\n'.join(line for line in text.splitlines() if 'PASS' in line))
    from camera_host import decode_packet,save_frame
    packet=bytes.fromhex((out/'frame_packet.hex').read_text())
    info,raw=decode_packet(packet)
    (out/'frame_packet.bin').write_bytes(packet)
    checks={'rtl_uart_crc':True,'payload_bytes':len(raw),'width':info['width'],'height':info['height']}
    for pos in [0,6,39,40,len(packet)-1]:
        broken=bytearray(packet); broken[pos]^=1
        try: decode_packet(bytes(broken))
        except ValueError: pass
        else: raise AssertionError(f'corruption at {pos} not detected')
    for cut in [0,20,len(packet)-1]:
        try: decode_packet(packet[:cut])
        except ValueError: pass
        else: raise AssertionError('truncated packet accepted')
    checks['corruption_and_truncation_rejected']=True
    from camera_host import rgb565_to_rgb888
    assert rgb565_to_rgb888(bytes.fromhex('f80007e0001f'))==bytes([255,0,0,0,255,0,0,0,255])
    checks['rgb565_primary_colors']=True
    import datetime
    preview=out/('preview_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    metadata=save_frame(info,raw,packet,preview)
    assert (preview/'frame.bmp').read_bytes()[:2]==b'BM'
    (out/'validation.json').write_text(json.dumps(checks,indent=2)+'\n')
    print('PASS Python parser, CRC corruption/truncation checks, RGB565 and BMP export')
    print(f'Reports: {out}')
if __name__=='__main__': main()
