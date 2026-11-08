"""Attach local RTL/constraints to the user's existing PG2K100 PDS project."""
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    path=ROOT/'camera.pds'
    backup=ROOT/'camera.original.pds'
    if not backup.exists(): shutil.copy2(path,backup)
    tree=ET.parse(path)
    root=tree.getroot()
    design=root.find("./members[@category='design_set']/task")
    options=design.find('options')
    top=options.find("option[@name='top_module']")
    if top is None: top=ET.SubElement(options,'option',{'name':'top_module','type':'string'})
    top.set('value','camera_top')
    inner=design.find('inner_options')
    specified=inner.find("inner[@name='is_user_specify_top']")
    if specified is None: specified=ET.SubElement(inner,'inner',{'name':'is_user_specify_top','type':'interger'})
    specified.set('value','1')
    for category,action_name,paths,fmt in [
        ('design_set','design',sorted((ROOT/'rtl').glob('*.v')),'verilog'),
        ('constraint_set','constraint',[ROOT/'constraints/camera.fdc'],'fdc')]:
        action=root.find(f"./members[@category='{category}']/task/action[@name='{action_name}']")
        inputs=action.find('inputs')
        if inputs is None: inputs=ET.SubElement(action,'inputs')
        existing={x.get('file') for x in inputs}
        for p in paths:
            rel=p.relative_to(ROOT).as_posix()
            if rel in existing: continue
            item=ET.SubElement(inputs,'item',{'type':'FILE','file':rel,'format':fmt,'library':'work'})
            opts=ET.SubElement(item,'options')
            for name,value,kind in [('format',fmt,'string'),('library','work','string')]:
                ET.SubElement(opts,'option',{'name':name,'type':kind,'value':value})
            if p.name=='camera_top.v': ET.SubElement(opts,'option',{'name':'is_top_spec','type':'boolean','value':'TRUE'})
    ET.indent(tree,space='    ')
    tree.write(path,encoding='UTF-8',xml_declaration=True)
    for node in root.findall('.//inputs/item[@type="FILE"]'):
        if not (ROOT/node.get('file')).is_file(): raise FileNotFoundError(node.get('file'))
    print('camera.pds: camera_top, local RTL and FDC attached; original backup retained')
if __name__=='__main__': main()
