"""OV2640 single-frame bench utility: UART packets, CRC32, raw RGB565 + PPM.
Protocol details: ../README.md. Only pyserial is required for live serial use.
"""
import argparse
import datetime as dt
import hashlib
import json
import struct
import sys
import time
import zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAGIC=b'CAM1'
HEADER=struct.Struct('<4sBBBBBBHHHIIHHHBBII')
FIELDS=('magic','version','kind','flags','error','pid','ver','sequence','width','height',
        'payload_length','captured_bytes','lines','last_line_bytes','config_index','format',
        'capture_errors','vsync_count','bad_count')
ERRORS={0:'OK',1:'SCCB NACK: check power, oscillator, SDA/SCL and pull-ups',
        2:'SCCB timeout: bus held low or no pull-ups',3:'unexpected sensor ID',
        4:'sensor not initialized',5:'invalid DVP frame dimensions',
        6:'capture timeout: check PCLK/VSYNC/HREF and sensor clock',7:'unknown command'}
FLAGS=('configured','config_failed','id_ok','frame_good','pclk_seen','vsync_seen','href_seen','colorbar')

def decode_packet(packet):
    if len(packet)<HEADER.size+4: raise ValueError('truncated packet')
    values=HEADER.unpack_from(packet)
    info=dict(zip(FIELDS,values))
    if info['magic']!=MAGIC or info['version']!=1: raise ValueError('unsupported packet magic/version')
    n=info['payload_length']
    if n>38400 or len(packet)!=HEADER.size+n+4: raise ValueError('invalid packet length')
    if zlib.crc32(packet[:-4])!=struct.unpack_from('<I',packet,len(packet)-4)[0]:
        raise ValueError('CRC32 mismatch; discard frame and check UART wiring/baud')
    if info['kind'] not in (1,2,3): raise ValueError('invalid packet kind')
    if info['kind']==2:
        if (info['error'] or info['format']!=1 or info['width']<=0 or info['height']<=0 or
            n!=info['width']*info['height']*2 or info['captured_bytes']!=n or
            info['lines']!=info['height'] or info['last_line_bytes']!=info['width']*2 or
            info['capture_errors'] or not (info['flags']&8)):
            raise ValueError('frame failed metadata validation')
    elif n: raise ValueError('status/error packet must have no payload')
    info['magic']=info['magic'].decode('ascii')
    info['flag_names']=[name for bit,name in enumerate(FLAGS) if info['flags'] & (1<<bit)]
    info['error_text']=ERRORS.get(info['error'],'unknown firmware error')
    return info,packet[HEADER.size:-4]

def read_exact(port,size,deadline):
    data=bytearray()
    while len(data)<size:
        if time.monotonic()>deadline: raise TimeoutError(f'UART timeout: {len(data)}/{size} bytes')
        data.extend(port.read(size-len(data)))
    return bytes(data)

def transact(port,command,timeout=12):
    # One outstanding command; firmware freezes frame memory until TX completes.
    port.write(command)
    port.flush()
    deadline=time.monotonic()+timeout
    magic=bytearray()
    while bytes(magic)!=MAGIC:
        magic.extend(read_exact(port,1,deadline))
        if len(magic)>4: del magic[0]
    header=MAGIC+read_exact(port,HEADER.size-4,deadline)
    n=HEADER.unpack(header)[10]
    if n>38400: raise ValueError('invalid payload length (wrong firmware/baud?)')
    packet=header+read_exact(port,n+4,deadline)
    return (*decode_packet(packet),packet)

def rgb565_to_rgb888(raw,swap_bytes=False,swap_rb=False):
    if len(raw)%2: raise ValueError('odd RGB565 byte count')
    out=bytearray()
    for i in range(0,len(raw),2):
        p=(raw[i+1]<<8|raw[i]) if swap_bytes else (raw[i]<<8|raw[i+1])
        r=(p>>11)&31; g=(p>>5)&63; b=p&31
        r=(r<<3)|(r>>2); g=(g<<2)|(g>>4); b=(b<<3)|(b>>2)
        out.extend((b,g,r) if swap_rb else (r,g,b))
    return bytes(out)

def save_frame(info,raw,packet,folder,swap_bytes=False,swap_rb=False):
    folder.mkdir(parents=True,exist_ok=False)
    rgb=rgb565_to_rgb888(raw,swap_bytes,swap_rb)
    (folder/'frame.rgb565').write_bytes(raw)
    (folder/'packet.bin').write_bytes(packet)
    (folder/'frame.ppm').write_bytes(f"P6\n{info['width']} {info['height']}\n255\n".encode()+rgb)
    # BMP is viewable by standard Windows image viewers; original bytes retained.
    width,height=info['width'],info['height']
    stride=(width*3+3)&~3
    rows=bytearray()
    for y in range(height-1,-1,-1):
        row=rgb[y*width*3:(y+1)*width*3]
        for x in range(0,len(row),3): rows.extend((row[x+2],row[x+1],row[x]))
        rows.extend(bytes(stride-width*3))
    bmp=struct.pack('<2sIHHI',b'BM',54+len(rows),0,0,54)
    bmp+=struct.pack('<IiiHHIIiiII',40,width,height,1,24,0,len(rows),2835,2835,0,0)
    (folder/'frame.bmp').write_bytes(bmp+rows)
    metadata=dict(info,captured_at=dt.datetime.now().astimezone().isoformat(),
        raw_sha256=hashlib.sha256(raw).hexdigest(),preview_swap_bytes=swap_bytes,
        preview_swap_rb=swap_rb,unique_pixel_values=len(set(zip(raw[0::2],raw[1::2]))),
        rgb_min=min(rgb),rgb_max=max(rgb),host_path='PA UART bench capture; not PU/PA streaming')
    manifest=ROOT/'init_manifest.json'
    if manifest.exists():
        (folder/'init_manifest.json').write_bytes(manifest.read_bytes())
        metadata['init_manifest_sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
    (folder/'metadata.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return metadata

def wait_ready(port,timeout=5):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        info,_,_=transact(port,b'S')
        if info['flags']&2: raise RuntimeError(f"{info['error_text']}; PID={info['pid']:02x}, VER={info['ver']:02x}, config_index={info['config_index']}")
        if info['flags']&1: return info
        time.sleep(.1)
    raise TimeoutError('camera initialization did not finish')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',help='external PA USB-UART port, for example COM7')
    parser.add_argument('--baud',type=int,default=115200)
    parser.add_argument('--swap-bytes',action='store_true',help='preview only; raw bytes remain unchanged')
    parser.add_argument('--swap-rb',action='store_true',help='preview only; raw bytes remain unchanged')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('ports')
    sub.add_parser('status')
    sub.add_parser('reset')
    mode=sub.add_parser('mode'); mode.add_argument('value',choices=['normal','colorbar'])
    capture=sub.add_parser('capture'); capture.add_argument('--count',type=int,default=1)
    capture.add_argument('--out',type=Path,default=ROOT/'runs')
    capture.add_argument('--interval',type=float,default=0)
    decode=sub.add_parser('decode'); decode.add_argument('packet',type=Path); decode.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='decode':
        packet=args.packet.read_bytes(); info,raw=decode_packet(packet)
        if info['kind']!=2: raise ValueError('packet does not contain a valid frame')
        print(json.dumps(save_frame(info,raw,packet,args.out,args.swap_bytes,args.swap_rb),indent=2)); return
    import serial
    if args.command=='ports':
        from serial.tools import list_ports
        for p in list_ports.comports(): print(f'{p.device}: {p.description} [{p.hwid}]')
        return
    if not args.port: parser.error('--port is required for live commands')
    if args.command=='capture' and (args.count<1 or args.interval<0): parser.error('count must be positive; interval must be nonnegative')
    with serial.Serial(args.port,args.baud,timeout=.2,write_timeout=2,rtscts=False,dsrdtr=False) as port:
        time.sleep(.1); port.reset_input_buffer()
        if args.command=='status':
            info,_,_=transact(port,b'S'); print(json.dumps(info,indent=2)); return
        if args.command in ('mode','reset'):
            cmd=b'R' if args.command=='reset' else (b'T' if args.value=='colorbar' else b'N')
            transact(port,cmd); info=wait_ready(port)
            print(json.dumps(info,indent=2)); return
        wait_ready(port)
        for i in range(args.count):
            started=time.monotonic()
            info,raw,packet=transact(port,b'F')
            if info['kind']!=2: raise RuntimeError(json.dumps(info,indent=2))
            folder=args.out/dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            metadata=save_frame(info,raw,packet,folder,args.swap_bytes,args.swap_rb)
            print(f"{folder}: {info['width']}x{info['height']}, {len(raw)} bytes, CRC OK, unique pixels={metadata['unique_pixel_values']}, elapsed={time.monotonic()-started:.2f}s")
            if metadata['unique_pixel_values']<8: print('CHECK: nearly uniform image; verify lens/exposure/data lines.')
            if i+1<args.count: time.sleep(args.interval)
if __name__=='__main__':
    try: main()
    except (ValueError,RuntimeError,TimeoutError,OSError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr); sys.exit(1)

