"""Check routed clocks, pins, voltage standards and source/bitstream freshness."""
import datetime as dt
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from update_project import sources as project_sources, label

ROOT = Path(__file__).resolve().parents[1]


def main():
    run = ROOT/'build/pds/prj_tasks/pnr_1'
    timing = (run/'report_timing/pca_bench_top.rtr').read_text(errors='replace')
    assert re.search(r'Design Summary\s*:\s*All Constraints Met\.', timing)
    for name, period in [('sysclk_50', '20.0000'), ('jtag_tck', '66.6670')]:
        assert re.search(name+r'\s+'+re.escape(period)+r'\s+\{', timing)
    pcf = (run/'device_map/pca_bench_top.pcf').read_text()
    mapping = {m[0]: dict(re.findall(r'(\w+)=(\S+)', m[1]))
               for m in re.findall(r'^def_port\s+\{([^}]+)\}\s+(.+)$', pcf, re.M)}
    expected = dict(sysclk_50='T9', rstn='C20', pca_scl='V10', pca_sda='U9')
    expected.update({f'led_n[{i}]': pin for i, pin in enumerate(['G14', 'E18', 'E19', 'F16', 'F17'])})
    assert mapping.keys() == expected.keys()
    for name, pin in expected.items():
        voltage = '2.5' if name == 'rstn' or name.startswith('led_n') else '3.3'
        assert mapping[name]['LOC'] == pin
        assert mapping[name]['VCCIO'] == voltage
        assert mapping[name]['IOSTANDARD'] == ('LVCMOS25' if voltage == '2.5' else 'LVCMOS33')
    netlist = (run/'generate_netlist/pca_bench_top_sim.v').read_text(errors='replace')
    for name in ['pca_scl', 'pca_sda']:
        assert mapping[name]['BUS_KEEPER'] == 'PULLUP'
        assert re.search(r'PAP_IO_BUS_KEEPER="PULLUP"[^\n]*inout '+name+r';', netlist)
    sources = [*sorted((ROOT/'rtl').glob('*.v')), ROOT/'constraints/pca_bench.fdc', ROOT/'scripts/build.tcl']
    tree = ET.parse(ROOT/'pca_bench.pds')
    assert tree.find('.//part').attrib == dict(family='Kosmo2', device='PG2K100', speedgrade='-6', package='MBG400')
    top = tree.find("./members[@category='design_set']/task/options/option[@name='top_module']")
    assert top.get('value') == 'pca_bench_top'
    inputs = {Path(item.get('file')).as_posix() for item in tree.findall('.//inputs/item[@type="FILE"]')}
    assert inputs == {label(path) for path in [*project_sources(), ROOT/'constraints/pca_bench.fdc']}
    bit = run/'generate_bitstream/pca_bench_top.sbit'
    assert bit.stat().st_size > 100000
    assert bit.stat().st_mtime >= max(path.stat().st_mtime for path in sources)
    summary = dict(checked_at=dt.datetime.now().astimezone().isoformat(), timing='All Constraints Met',
                   verified_pins=expected, gui_inputs_match=True, bitstream_bytes=bit.stat().st_size,
                   bitstream_sha256=hashlib.sha256(bit.read_bytes()).hexdigest(),
                   sources_sha256={path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sources},
                   limitations='Digital timing and pin check; no physical PWM, voltage or chassis test')
    (ROOT/'build/implementation_validation.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
