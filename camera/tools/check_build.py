"""Verify implementation reports, PDS input manifest and programming artifact."""
import datetime as dt
import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jtag',action='store_true')
    args=parser.parse_args()
    top_name='camera_jtag_top' if args.jtag else 'camera_top'
    run=ROOT/'build'/('pds_jtag' if args.jtag else 'pds')/'prj_tasks/pnr_1'
    report=run/'report_timing'/f'{top_name}.rtr'
    text=report.read_text(errors='replace')
    assert re.search(r'Design Summary\s*:\s*All Constraints Met\.',text),'timing constraints failed'
    assert re.search(r'sysclk_50\s+20\.0000\s+\{',text),'50 MHz system clock missing'
    assert re.search(r'cam_pclk\s+41\.6670\s+\{',text),'24 MHz PCLK constraint missing'
    bit=run/'generate_bitstream'/f'{top_name}.sbit'
    assert bit.stat().st_size>100000,'missing/truncated bitstream'
    sources=sorted((ROOT/'rtl').glob('*.v'))+[ROOT/'constraints/camera.fdc']
    if args.jtag:
        from update_jtag_project import sources as jtag_sources
        sources=jtag_sources()+[ROOT/'constraints/camera.fdc',ROOT/'constraints/camera_jtag.fdc']
        assert re.search(r'jtag_tck\s+66\.6670\s+\{',text),'JTAG clock constraint missing'
    def label(path):
        return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    assert bit.stat().st_mtime>=max(p.stat().st_mtime for p in sources),'bitstream predates RTL/constraint edits'
    pcf=(run/'device_map'/f'{top_name}.pcf').read_text()
    mapping={m[0]:dict(re.findall(r'(\w+)=(\S+)',m[1])) for m in re.findall(r'^def_port\s+\{([^}]+)\}\s+(.+)$',pcf,re.M)}
    expected={'cam_pclk':'Y7','sysclk_50':'T9','cam_vsync':'W6','cam_href':'Y13','cam_reset_n':'V6',
              'cam_scl':'W9','cam_sda':'W8','uart_rx':'T20','uart_tx':'U20','rstn':'C20'}
    expected.update({f'cam_data[{i}]':v for i,v in enumerate(['U5','Y12','V11','Y11','W11','W10','Y9','Y8'])})
    expected.update({f'led_n[{i}]':v for i,v in enumerate(['G14','E18','E19','F16','F17'])})
    assert mapping.keys()==expected.keys(),'unexpected or missing top-level IO'
    for name,pin in expected.items():
        voltage='2.5' if name=='rstn' or name.startswith('led_n') else '3.3'
        assert mapping[name]['LOC']==pin,(name,mapping[name])
        assert mapping[name]['VCCIO']==voltage,(name,mapping[name])
        assert mapping[name]['IOSTANDARD']==('LVCMOS25' if voltage=='2.5' else 'LVCMOS33')
    if args.jtag:
        for name in ['cam_scl','cam_sda']:
            assert mapping[name].get('BUS_KEEPER')=='PULLUP', f'{name}: internal pullup missing'
        netlist=(run/'generate_netlist'/f'{top_name}_sim.v').read_text(errors='replace')
        for name in ['cam_scl','cam_sda']:
            assert re.search(r'PAP_IO_BUS_KEEPER="PULLUP"[^\n]*inout '+name+r';',netlist), f'{name}: routed pullup missing'
        assert '.SCCB_HZ(10000)' in (ROOT/'jtag/camera_jtag_top.v').read_text(), 'Expected 10 kHz bench profile'
    tree=ET.parse(ROOT/('camera_jtag.pds' if args.jtag else 'camera.pds'))
    part=tree.find('.//part')
    assert part.attrib=={'family':'Kosmo2','device':'PG2K100','speedgrade':'-6','package':'MBG400'}
    top=tree.find("./members[@category='design_set']/task/options/option[@name='top_module']")
    assert top.get('value')==top_name
    files={Path(x.get('file')).as_posix() for x in tree.findall('.//inputs/item[@type="FILE"]')}
    assert files=={label(p) for p in sources},'GUI project inputs differ from build inputs'
    dmr=(run/'device_map'/f'{top_name}.dmr').read_text(errors='replace')
    usage=re.search(r'Device Utilization Summary:(.*?)(?:\n\n)',dmr,re.S)
    resources={}
    if usage:
        for line in usage[1].splitlines():
            fields=[x.strip() for x in line.split('|')]
            if len(fields)>=5 and re.fullmatch(r'\d+(\.\d+)?',fields[2]): resources[fields[1]]={'used':fields[2],'available':fields[3]}
    assert float(resources.get('DRM',{}).get('used',0))>0,'frame RAM did not map to block RAM'
    performance={name:{'requested_mhz':float(req),'estimated_mhz':float(est),'slack_ns':float(slack)}
        for name,req,est,slack in re.findall(r'(sysclk_50|cam_pclk|jtag_tck)\s+([\d.]+) MHz\s+([\d.]+) MHz\s+[\d.]+\s+[\d.]+\s+([\d.-]+)',text)}
    result={'checked_at':dt.datetime.now().astimezone().isoformat(),'timing':'All Constraints Met',
        'part':part.attrib,'performance':performance,'resources':resources,'verified_pins':len(mapping),
        'pclk_connector':'J8-10 / Y7; J8-9 is GND; J8-8 / Y6 is not used',
        'bitstream':bit.relative_to(ROOT).as_posix(),'bitstream_bytes':bit.stat().st_size,
        'bitstream_sha256':hashlib.sha256(bit.read_bytes()).hexdigest(),
        'sources_sha256':{label(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'board_test':'Not assessed by this implementation checker; see runs/*/session.json for hardware evidence',
        'external_timing':'PCLK <= 24 MHz and 0..8 ns falling-edge input delays assumed; measure actual module',
        'sccb_profile':{'bus_hz':10000 if args.jtag else 100000,'internal_pullups':args.jtag},
        'jtag_profile':({'signature':'CA02','page_bytes':256,'data_probes':[1,3,4,5,6,7,8,9],
                         'diagnostic_probe':2,'monitor_probe':10} if args.jtag else None)}
    target=ROOT/'build'/('implementation_jtag_validation.json' if args.jtag else 'implementation_validation.json')
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
