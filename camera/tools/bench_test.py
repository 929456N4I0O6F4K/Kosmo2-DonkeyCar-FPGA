"""Record an actual PA UART bench session with raw packets and failures."""
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
import serial
from camera_host import ROOT, transact, save_frame

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--mode',choices=['status','colorbar','normal'],default='status')
    p.add_argument('--count',type=int,default=1)
    a=p.parse_args()
    if a.count<1: p.error('--count must be positive')
    folder=ROOT/'runs'/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f_bench')
    folder.mkdir(parents=True,exist_ok=False)
    result={'started_at':dt.datetime.now().astimezone().isoformat(),'port':a.port,
            'baud':115200,'mode':a.mode,'events':[],'frames':[],'pass':False}
    bit=ROOT/'build/pds/prj_tasks/pnr_1/generate_bitstream/camera_top.sbit'
    result['bitstream_sha256']=hashlib.sha256(bit.read_bytes()).hexdigest()
    def persist():
        (folder/'session.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    def event(port,cmd,timeout=12):
        t=time.monotonic()
        info,raw,packet=transact(port,cmd,timeout)
        name=f'{len(result["events"]):03d}_{cmd.decode()}.bin'
        (folder/name).write_bytes(packet)
        result['events'].append({'time':dt.datetime.now().astimezone().isoformat(),
                                 'command':cmd.decode(),'elapsed_s':time.monotonic()-t,'packet':name,'status':info})
        persist()
        return info,raw,packet
    persist()
    print(f'BENCH_SESSION {folder}',flush=True)
    try:
        port=serial.Serial(port=None,baudrate=115200,timeout=.2,write_timeout=2)
        port.dtr=False; port.rts=False; port.port=a.port
        with port:
            time.sleep(.1); port.reset_input_buffer()
            info,_,_=event(port,b'S',3)
            print(json.dumps(info,ensure_ascii=False),flush=True)
            if not (info['flags']&1):
                raise RuntimeError(f"Camera not configured: {info['error_text']}, PID/VER={info['pid']:02x}/{info['ver']:02x}")
            if a.mode=='status':
                time.sleep(1)
                after,_,_=event(port,b'S',3)
                first=result['events'][-2]; last=result['events'][-1]
                interval=(dt.datetime.fromisoformat(last['time'])-dt.datetime.fromisoformat(first['time'])).total_seconds()
                result['vsync_hz']=(after['vsync_count']-info['vsync_count'])%2**32/interval
                if after['vsync_count']==info['vsync_count']: raise RuntimeError('VSYNC counter not advancing')
                print(f"Observed VSYNC rate: {result['vsync_hz']:.3f} Hz",flush=True)
            else:
                event(port,b'T' if a.mode=='colorbar' else b'N',3)
                deadline=time.monotonic()+5
                while True:
                    time.sleep(.1)
                    info,_,_=event(port,b'S',3)
                    if info['flags']&2: raise RuntimeError(info['error_text'])
                    if info['flags']&1: break
                    if time.monotonic()>deadline: raise TimeoutError('Initialization timeout')
                time.sleep(2)  # allow sensor exposure and DSP to settle
                for index in range(a.count):
                    info,raw,packet=event(port,b'F')
                    if info['kind']!=2: raise RuntimeError(json.dumps(info,ensure_ascii=False))
                    frame=folder/f'frame_{index:03d}'
                    metadata=save_frame(info,raw,packet,frame)
                    result['frames'].append({'folder':frame.name,'metadata':metadata})
                    persist()
                    print(f"FRAME {index}: {info['width']}x{info['height']}, {len(raw)} bytes, CRC OK, unique_pixels={metadata['unique_pixel_values']}, sha256={metadata['raw_sha256']}",flush=True)
            result['pass']=True
    except Exception as exc:
        result['error']=f'{type(exc).__name__}: {exc}'
        print(result['error'],file=sys.stderr,flush=True)
    finally:
        result['finished_at']=dt.datetime.now().astimezone().isoformat()
        persist()
    return 0 if result['pass'] else 1
if __name__=='__main__': sys.exit(main())

