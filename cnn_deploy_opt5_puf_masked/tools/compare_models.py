"""Inspect actual TFLite graphs instead of assuming training JSON is current."""
from pathlib import Path
import os
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','2')
import json
import hashlib
import numpy as np
import reference as ref
from export import validate_graph

ROOT=Path(__file__).resolve().parents[1]


def describe(path):
    codes=validate_graph(path)
    interpreter,ops=ref.load_graph(path);layers=ref.extract_layers(interpreter,ops)
    def detail(d):
        return dict(shape=d['shape'].tolist(),dtype=str(d['dtype']),scale=d['quantization'][0],zero_point=d['quantization'][1])
    return dict(model_sha256=ref.sha256(path),bytes=path.stat().st_size,
                inputs=[detail(d) for d in interpreter.get_input_details()],outputs=[detail(d) for d in interpreter.get_output_details()],
                operators=codes,layers=[dict(name=l['name'],weight_shape=list(l['weights'].shape),input_zp=l['input_zp'],output_zp=l['output_zp'],
                                            input_scale=l['input_scale'],output_scale=l['output_scale'],
                                            weights_sha256=hashlib.sha256(l['weights'].tobytes()).hexdigest(),
                                            bias_sha256=hashlib.sha256(l['bias'].tobytes()).hexdigest()) for l in layers])


def main():
    cfg=json.loads((ROOT/'deployment_config.json').read_text(encoding='utf-8'))
    old=ROOT.parent/cfg['previous_model']
    new=ROOT.parent/cfg['model'];a=describe(old);b=describe(new)
    same=a['inputs']==b['inputs'] and a['operators']==b['operators'] and [l['weight_shape'] for l in a['layers']]==[l['weight_shape'] for l in b['layers']]
    report={'previous':a,'new':b,'same_geometry_and_input_quantization':same,
            'changed_weight_layers':[l['name'] for l,r in zip(a['layers'],b['layers']) if l['weights_sha256']!=r['weights_sha256']],
            'new_output_scale_q30':round(b['outputs'][0]['scale']*2**30)}
    target=ROOT/'build/model_comparison.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
