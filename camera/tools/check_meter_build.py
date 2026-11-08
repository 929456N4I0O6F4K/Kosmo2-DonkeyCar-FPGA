"""Check meter firmware clocks, IO mapping and GUI/build source agreement."""
import datetime as dt
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from update_meter_project import ROOT, sources, label


def main():
    run = ROOT/'build/pds_meter/prj_tasks/pnr_1'
    top = 'camera_meter_top'
    timing = (run/'report_timing'/f'{top}.rtr').read_text(errors='replace')
    assert re.search(r'Design Summary\s*:\s*All Constraints Met\.',timing), 'Timing failed'
    for clock,period in [('sysclk_50','20.0000'),('jtag_tck','66.6670')]:
        assert re.search(rf'{clock}\s+{re.escape(period)}\s+\{{',timing), f'{clock} missing'
    pcf = (run/'device_map'/f'{top}.pcf').read_text()
    ports = {name:dict(re.findall(r'(\w+)=(\S+)',attrs))
             for name,attrs in re.findall(r'^def_port\s+\{([^}]+)\}\s+(.+)$',pcf,re.M)}
    expected = dict(sysclk_50='T9',rstn='C20',cam_reset_n='V6',cam_scl='W9',cam_sda='W8')
    expected.update({f'led_n[{i}]':v for i,v in enumerate(['G14','E18','E19','F16','F17'])})
    assert ports.keys()==expected.keys(), 'Unexpected/missing IO'
    for name,pin in expected.items():
        voltage = '2.5' if name=='rstn' or name.startswith('led_n') else '3.3'
        assert ports[name]['LOC']==pin and ports[name]['VCCIO']==voltage, (name,ports[name])
        assert ports[name]['IOSTANDARD']==('LVCMOS25' if voltage=='2.5' else 'LVCMOS33')
    for name in ['cam_scl','cam_sda']:
        assert ports[name].get('BUS_KEEPER')=='PULLUP', f'{name}: internal pullup was not applied'
    netlist=(run/'generate_netlist'/f'{top}_sim.v').read_text(errors='replace')
    for name in ['cam_scl','cam_sda']:
        assert re.search(r'PAP_IO_BUS_KEEPER="PULLUP"[^\n]*inout '+name+r';',netlist), f'{name}: routed pullup missing'
    assert '.INTERNAL_PULLUPS(1)' in (ROOT/'meter/camera_meter_top.v').read_text(), 'Pullup profile marker missing'
    inputs = sources()+[ROOT/'constraints/camera_meter.fdc']
    bit = run/'generate_bitstream'/f'{top}.sbit'
    assert bit.stat().st_size>100000 and bit.stat().st_mtime>=max(p.stat().st_mtime for p in inputs)
    project = ET.parse(ROOT/'camera_meter.pds')
    assert project.find('.//part').attrib==dict(family='Kosmo2',device='PG2K100',speedgrade='-6',package='MBG400')
    assert project.find("./members[@category='design_set']/task/options/option[@name='top_module']").get('value')==top
    assert {x.get('file') for x in project.findall('.//inputs/item[@type="FILE"]')}=={label(p) for p in inputs}
    result = dict(checked_at=dt.datetime.now().astimezone().isoformat(),timing='All Constraints Met',
                  verified_pins=expected,internal_pullups=['cam_scl','cam_sda'],bitstream=label(bit),bitstream_sha256=hashlib.sha256(bit.read_bytes()).hexdigest(),
                  sources_sha256={label(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
                  hardware='Digital and multimeter results belong in runs/*_meter/session.json and the hardware notes')
    (ROOT/'build/implementation_meter_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
