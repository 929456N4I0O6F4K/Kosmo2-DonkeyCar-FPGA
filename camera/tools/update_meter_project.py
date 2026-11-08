"""Create the separate static meter test PDS project."""
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PDS = Path('C:/pango/PDS_2025.2-ads')


def sources():
    ip = PDS/'ip/system_ip/ips_dvio/ips_dvio_eval'
    return (sorted((ROOT/'meter').glob('*.v')) + [ROOT/'jtag/camera_dvio.v'] +
            sorted((ip/'ips_dvio/rtl').glob('*.v')) + sorted((ip/'ips_dvio_jtag_hub/rtl').glob('*.v')))


def label(path):
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


def main():
    tree = ET.parse(ROOT/'camera.pds')
    root = tree.getroot()
    root.find("./members[@category='design_set']/task/options/option[@name='top_module']").set('value','camera_meter_top')
    for category, action, paths, fmt in [
        ('design_set','design',sources(),'verilog'),
        ('constraint_set','constraint',[ROOT/'constraints/camera_meter.fdc'],'fdc')]:
        inputs = root.find(f"./members[@category='{category}']/task/action[@name='{action}']/inputs")
        inputs.clear()
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(path)
            item = ET.SubElement(inputs,'item',dict(type='FILE',file=label(path),format=fmt,library='work'))
            options = ET.SubElement(item,'options')
            for name,value in [('format',fmt),('library','work')]:
                ET.SubElement(options,'option',dict(name=name,type='string',value=value))
            if path.name == 'camera_meter_top.v':
                ET.SubElement(options,'option',dict(name='is_top_spec',type='boolean',value='TRUE'))
    ET.indent(tree,space='    ')
    tree.write(ROOT/'camera_meter.pds',encoding='UTF-8',xml_declaration=True)
    print('camera_meter.pds: static RST/SCL/SDA tests via board JTAG')


if __name__ == '__main__':
    main()
