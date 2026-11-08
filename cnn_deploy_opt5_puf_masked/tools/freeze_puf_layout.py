"""Check integrated RO loops and export their actual tile/BLE constraints."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "integration/training"
CELL_BLOCK = re.compile(
    r'\(\* PAP_BLE_DEF="([A-D])" \*\)\s+V_LUT6CARRY /\* (CLMA_\d+_\d+) \*/ #(.*?)\);', re.S)
PUF_CELL = re.compile(r'\\(puf_core/bank/osc\[(\d+)\]\.ro_unit/(gate0|inv[1-6]))/[^\s]+')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value):
    return re.sub(r'\s+', '', value).lstrip('\\')


def read_layout(build):
    netlist = build / "prj_tasks/pnr_1/generate_netlist/kosmo_training_top_sim.v"
    cells = {}
    for match in CELL_BLOCK.finditer(netlist.read_text(encoding="utf-8")):
        cell = PUF_CELL.search(match[3])
        if not cell:
            continue
        name, oscillator, stage_name = cell.groups()
        if name in cells:
            raise ValueError(f"Duplicate RO stage: {name}")
        ports = {int(pin):normalize(net) for pin, net in re.findall(r'\.I([0-5])\s*\(([^)]*)\)', match[3])}
        cells[name] = dict(tile=match[2], ble=match[1], oscillator=int(oscillator),
                           stage=0 if stage_name=='gate0' else int(stage_name[3:]),
                           init=int(re.search(r"\.INIT\(64'h([0-9a-fA-F]+)\)",match[3])[1],16),
                           pins=ports, output=normalize(re.search(r'\.Z\s*\(([^)]*)\)',match[3])[1]))
    if len(cells)!=448 or len({(v['tile'],v['ble']) for v in cells.values()})!=448:
        raise ValueError(f"Expected 448 distinct RO LUTs; got {len(cells)}")
    by_stage = {(v['oscillator'],v['stage']):v for v in cells.values()}
    for row in cells.values():
        prev = by_stage[row['oscillator'],(row['stage']-1)%7]['output']
        feedback = [p for p,v in row['pins'].items() if v==prev]
        if len(feedback)!=1:
            raise ValueError(f"RO feedback changed: {row}")
        dynamic = [p for p,v in row['pins'].items() if v.startswith('puf_core/') and p!=feedback[0]]
        if len(dynamic)!=(1 if row['stage']==0 else 0):
            raise ValueError("Unexpected dynamic RO inputs")
        for value in range(64):
            expected = 1-((value>>feedback[0])&1)
            if dynamic:
                expected = 1-(((value>>feedback[0])&1)*((value>>dynamic[0])&1))
            if ((row['init']>>value)&1)!=expected:
                raise ValueError("RO LUT is not the intended NAND/inverter")
    return cells, netlist


def mapping_signature(cells):
    """Compare physical RO placement, wiring roles, and effective LUT function.

    The mapper can repack unused LUT inputs and their tied constants between
    otherwise equivalent builds, changing the raw INIT word without changing
    the oscillator. Compare the feedback/control pins and the truth table over
    those functional inputs instead of implementation-specific don't-cares.
    """
    by_stage = {(row['oscillator'], row['stage']): row for row in cells.values()}
    signature = {}
    for name, row in cells.items():
        previous = by_stage[row['oscillator'], (row['stage'] - 1) % 7]['output']
        feedback = next(pin for pin, net in row['pins'].items() if net == previous)
        dynamic = [pin for pin, net in row['pins'].items()
                   if net.startswith('puf_core/') and pin != feedback]
        dynamic_pin = dynamic[0] if dynamic else None
        truth = []
        for feedback_value in range(2):
            for dynamic_value in range(2):
                value = feedback_value << feedback
                if dynamic_pin is not None:
                    value |= dynamic_value << dynamic_pin
                truth.append((row['init'] >> value) & 1)
        signature[name] = (row['tile'], row['ble'], row['oscillator'], row['stage'],
                           row['output'], feedback, dynamic_pin, tuple(truth))
    return signature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("--output", type=Path, default=TRAIN/"board/ro_locations.fdc")
    parser.add_argument("--verify", type=Path, help="compare all mapped LUTs/pins/INIT with another build")
    args = parser.parse_args()
    cells, netlist = read_layout(args.build)
    timing = args.build/"prj_tasks/pnr_1/report_timing/kosmo_training_top.rtr"
    report_text = timing.read_text(encoding="utf-8")
    if not re.search(r'Design Summary\s*:\s*All Constraints Met\.', report_text):
        raise ValueError("Integrated RO counter/system timing failed")
    for clock, period in [('ro_a',1.666667),('ro_b',1.666667),('ro_a_div16',26.666672),('ro_b_div16',26.666672)]:
        found = re.search(rf'^\s*{clock}\s+([0-9.]+)',report_text,re.M)
        if not found or abs(float(found[1])-period)>0.0001:
            raise ValueError(f"Missing or incorrect RO clock constraint: {clock}")
    lines = ['# Integrated RO7 actual placement: 448 native LUTs; feedback and truth tables checked.',
             '# PAP_LOC fixes tile and FY[A-D] BLE.',
             '# Input-pin assignment is now fixed at RTL level: ro_cell.v directly instantiates',
             '# V_LUT6CARRY with feedback on I0 and gate-enable on I1 — the mapper cannot',
             '# rearrange explicitly-named physical primitive ports between builds.',
             '# Feedback routing is still NOT locked.',
             '# IMPORTANT: regenerate this file from the final production netlist before enrolling.']
    for name, row in sorted(cells.items()):
        lines.append(f"define_attribute {{i:{name}}} {{PAP_LOC}} {{{row['tile']}:FY{row['ble']}}}")
    report = dict(schema="kosmo-opt4-ro-layout-v3",fixed_stages=448,
                  tile_and_ble_pinned=True,init_locked=True,feedback_and_truth_tables_checked=True,
                  counter_clock_constraints_checked=True,routes_fixed=False,reuse_qualified=False,
                  seed_netlist=str(netlist.resolve()),seed_netlist_sha256=digest(netlist),
                  mapped_stages=cells)
    if args.verify:
        other, other_net = read_layout(args.verify)
        reference_signature = mapping_signature(cells)
        other_signature = mapping_signature(other)

        def control_pin(layout, row):
            by_stage = {(value['oscillator'], value['stage']): value for value in layout.values()}
            previous = by_stage[row['oscillator'], (row['stage'] - 1) % 7]['output']
            feedback = next(pin for pin, net in row['pins'].items() if net == previous)
            return next((pin for pin, net in row['pins'].items()
                         if net.startswith('puf_core/') and pin != feedback), None)

        remapped_controls = sum(
            control_pin(cells, cells[name]) != control_pin(other, other[name])
            for name in cells if cells[name]['stage'] == 0)
        if other_signature != reference_signature:
            changed = [name for name in cells if other_signature.get(name)!=reference_signature[name]]
            raise ValueError(
                f"RO mapping changed for {len(changed)} LUTs; "
                f"{remapped_controls} gate-enable input pins changed; routes remain unverified")
        report.update(mapping_identical=True, control_input_ble_pin_remaps=remapped_controls,
                      verified_netlist_sha256=digest(other_net))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    report.update(constraint=str(args.output.resolve()),constraint_sha256=digest(args.output))
    image=args.build/'prj_tasks/pnr_1/generate_bitstream/kosmo_training_top.sbit'
    if image.exists():
        report.update(bitstream=str(image.resolve()),bitstream_sha256=digest(image))
    args.output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='mapped_stages'},indent=2))


if __name__=='__main__':
    main()
