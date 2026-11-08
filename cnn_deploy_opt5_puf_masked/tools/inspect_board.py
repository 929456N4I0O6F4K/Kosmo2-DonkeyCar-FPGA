"""Read board boot, processes and the known PU/PA isolation state over SSH."""
from pathlib import Path
import sys
import os
import json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integration/tools'))
from pu_ssh import connect,BOARD_HOST


def main():
    with connect(os.environ.get('KOSMO_SSH_PASSWORD') or 'root') as client:
        result={}
        for key,cmd in {
            'system':'uname -a; cat /proc/sys/kernel/random/boot_id; ip -4 addr; ip route',
            'processes':'ps; ls -l /root/kosmo-training; tail -30 /root/kosmo-training/collector.log',
            'isolation':'devmem 0xe5006198 32',
            'uio':'cat /sys/class/uio/uio0/name; cat /sys/class/uio/uio0/maps/map0/addr',
        }.items():
            _,out,err=client.exec_command(cmd,timeout=15)
            result[key]=out.read().decode(errors='replace')+err.read().decode(errors='replace')
        if int(result['isolation'].strip(),0)==15:
            _,out,err=client.exec_command('devmem 0x00300000 32; devmem 0x00300004 32; devmem 0x00300034 32',timeout=10)
            result['transport']=out.read().decode(errors='replace')+err.read().decode(errors='replace')
        result['host']=BOARD_HOST
        target=ROOT/'runs/board-preflight/ssh-state.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
