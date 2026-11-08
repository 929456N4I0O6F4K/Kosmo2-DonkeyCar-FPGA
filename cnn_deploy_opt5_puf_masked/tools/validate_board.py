"""Same-frame TFLite comparison; optional short, wheels-raised actuator checks."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integration/tools'))
from board_connection import board_host


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames',type=int,default=50)
    parser.add_argument('--motion',action='store_true')
    parser.add_argument('--allow-mismatch',action='store_true',help='Record FPGA/TFLite mismatches instead of failing (unbound board)')
    args=parser.parse_args()
    import numpy as np
    import tensorflow as tf
    manifest=json.loads((ROOT/'model_manifest.json').read_text())
    model=ROOT.parent/manifest['model']
    assert hashlib.sha256(model.read_bytes()).hexdigest()==manifest['model_sha256']
    interpreter=tf.lite.Interpreter(model_content=model.read_bytes(),experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors()
    inp=interpreter.get_input_details()[0]['index'];out=interpreter.get_output_details()[0]['index']
    host=board_host();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    folder=ROOT/'runs'/time.strftime('%Y%m%d-%H%M%S-cnn-board')
    folder.mkdir(parents=True)
    def api(path,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        request=urllib.request.Request(f'http://{host}:8080/api/{path}',data=data,headers={'Content-Type':'application/json'})
        with opener.open(request,timeout=3) as response:return json.load(response)
    report={'success':False,'host':host,'model_sha256':manifest['model_sha256'],'frames':[],'motion_requested':args.motion}
    try:
        before=api('status');report['status_before']=before
        if args.motion and (before['enabled'] or before['record_open']):raise RuntimeError('Active driving/recording session')
        deadline=time.monotonic()+max(30,args.frames)
        previous=None
        while len(report['frames'])<args.frames:
            if time.monotonic()>deadline:raise TimeoutError('Board comparison did not complete')
            snap=api('inference-frame');frame=snap['frame'];seq=frame['frame_sequence']
            if seq==previous:time.sleep(.03);continue
            previous=seq
            raw=base64.b64decode(snap['rgb']);assert len(raw)==160*120*3
            rgb=np.frombuffer(raw,dtype=np.uint8).reshape(120,160,3)
            image=(rgb[25:120,2:158,:].astype(np.int16)-128).astype(np.int8)[None,...]
            interpreter.set_tensor(inp,image);interpreter.invoke()
            q=interpreter.get_tensor(out).reshape(-1).astype(np.int64)
            output_quant=interpreter.get_output_details()[0]['quantization']
            products=(q-output_quant[1])*round(output_quant[0]*(1<<30))
            expected=[int((v+8192)//16384) if v>=0 else -int((-v+8192)//16384) for v in products]
            p=frame['prediction'];actual=[p['angle_q16'],p['throttle_q16']]
            row={'sequence':seq,'capture_us':frame['capture_us'],'cycles':p['cycles'],'age_ms':snap['age_ms'],
                 'tflite_int8':q.tolist(),'expected_q16':expected,'fpga_q16':actual,'rgb_sha256':hashlib.sha256(raw).hexdigest()}
            report['frames'].append(row)
            if p['status']!=1 or p['frame_sequence']!=seq:raise RuntimeError('FPGA prediction not for this frame: '+str(row))
            row['exact']=actual==expected
            # A PUF-bound image on another board computes the wrong model; record, do not stop.
            if not row['exact'] and not args.allow_mismatch:raise RuntimeError('FPGA/TFLite prediction mismatch: '+str(row))
            if p['cycles']>=2500000:raise RuntimeError('Inference exceeded 50 ms')
            if len(report['frames']) in (1,args.frames):
                (folder/f'frame-{seq}.json').write_text(json.dumps(snap,indent=2))
                from PIL import Image
                Image.fromarray(rgb).save(folder/f'frame-{seq}.png')
            print(f'{"EXACT" if row["exact"] else "MISMATCH"} frame={seq} q16={actual} expected={expected} cycles={p["cycles"]}',flush=True)
        after=api('status');report['status_after_comparison']=after
        assert not after['fault'] and after['command_ack']>before['command_ack']
        rows=report['frames']
        report['comparison_sample_fps']=(len(rows)-1)*1e6/(rows[-1]['capture_us']-rows[0]['capture_us'])
        report['source_sequence_fps']=(rows[-1]['sequence']-rows[0]['sequence'])*1e6/(rows[-1]['capture_us']-rows[0]['capture_us'])
        report['max_processing_ms']=max(r['cycles'] for r in rows)/50000
        report['exact_frames']=sum(r['exact'] for r in rows)
        if args.motion:
            if after['enabled'] or after['record_open']:raise RuntimeError('Active user session before actuator tests')
            client='cnn-raised-wheel-test';sequence=0;gesture=0
            def drive(enable,angle=0,throttle=0,mode='manual',new=False):
                nonlocal sequence,gesture
                sequence+=1
                if new:gesture+=1
                return api('drive',dict(client=client,sequence=sequence,gesture=gesture,enable=enable,angle=angle,throttle=throttle,mode=mode))
            def run_segment(name,angle,throttle,mode='manual',duration=.5):
                end=time.monotonic()+duration;first=True;observed=[]
                while time.monotonic()<end:
                    drive(True,angle,throttle,mode,new=first);first=False
                    state=api('status');observed.append(state)
                    if state['fault'] or state.get('controller',{}).get('fault'):raise RuntimeError('Actuator fault during '+name)
                    time.sleep(.04)
                report.setdefault('motion',[]).append({'name':name,'status':observed})
                return observed
            try:
                left=run_segment('steer-left',-.2,0)
                assert any(s['frame']['flags']&1 and s['frame']['user/angle']<-.1 for s in left)
                drive(False);time.sleep(.2)
                right=run_segment('steer-right',.2,0)
                assert any(s['frame']['flags']&1 and s['frame']['user/angle']>.1 for s in right)
                drive(False);time.sleep(.2)
                forward=run_segment('short-throttle',0,.15)
                assert any(s['frame']['flags']&1 and .1<s['frame']['user/throttle']<=.15 for s in forward)
                drive(False);time.sleep(.2)
                automatic=run_segment('model-steering-and-throttle',0,.15,'auto',duration=1.)
                assert any(s['drive_mode']=='auto' and s['frame']['flags']&1 for s in automatic)
                assert all(0<=s['frame']['user/throttle']<=.15 for s in automatic)
                # Manual input takes over immediately, then loss of input must stop.
                takeover=run_segment('manual-takeover',0,0,duration=.4)
                assert any(s['drive_mode']=='manual' and s['frame']['flags']&1 and s['frame']['user/throttle']==0 for s in takeover)
                time.sleep(.8)
                stopped=api('status');report['status_after_lease_loss']=stopped
                assert not stopped['enabled'] and stopped['frame']['flags']==0 and stopped['frame']['user/throttle']==0
                try:drive(True,0,.1)
                except urllib.error.HTTPError as e:
                    if e.code!=409:raise
                else:raise RuntimeError('Expired gesture automatically resumed')
                report['stale_gesture_rejected']=True
            finally:
                drive(False)
                time.sleep(.6)
                report['final_status']=api('status')
                assert not report['final_status']['enabled'] and report['final_status']['frame']['flags']==0
        report['success']=True
    finally:
        (folder/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Evidence: {folder}',flush=True)
    print('BOARD VALIDATION PASS',flush=True)


if __name__=='__main__':main()
