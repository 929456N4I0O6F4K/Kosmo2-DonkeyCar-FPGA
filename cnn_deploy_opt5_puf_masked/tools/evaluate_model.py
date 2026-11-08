"""Sample original capture sessions; report existing model/quantization errors.

These recordings may overlap training. This is deployment regression evidence,
not a held-out driving accuracy evaluation.
"""
import io
import json
import os
from pathlib import Path
import zipfile

os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','2')
import numpy as np
from PIL import Image
import tensorflow as tf
from export import MODEL, ROOT, CONFIG, rgb565_bytes, rgb888
from reference import sha256


def main():
    quant=tf.lite.Interpreter(model_content=MODEL.read_bytes(),experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    floating=tf.lite.Interpreter(model_content=(ROOT.parent/CONFIG['float_model']).read_bytes())
    keras=tf.keras.models.load_model(ROOT.parent/CONFIG['keras_model'],compile=False)
    for interpreter in (quant,floating):
        interpreter.allocate_tensors()
    qi,qo=quant.get_input_details()[0],quant.get_output_details()[0]
    fi,fo=floating.get_input_details()[0],floating.get_output_details()[0]
    rows=[]
    archives={}
    for archive in sorted(ROOT.parent.glob(CONFIG['recording_archives'])):
        archives[archive.name]=sha256(archive)
        with zipfile.ZipFile(archive) as z:
            records_name=next(n for n in z.namelist() if n.endswith('records.jsonl'))
            records=[json.loads(line) for line in z.read(records_name).decode().splitlines() if line.strip()]
            for index in np.linspace(0,len(records)-1,min(8,len(records)),dtype=int):
                record=records[index]
                name=str(Path(records_name).parent/record['cam/image_array']).replace('\\','/')
                rgb=np.asarray(Image.open(io.BytesIO(z.read(name))).convert('RGB'))
                assert rgb.shape==(120,160,3)
                np.testing.assert_array_equal(rgb888(rgb565_bytes(rgb)),rgb)
                x=rgb[None,25:120,2:158].astype(np.float32)/255
                q=(rgb[None,25:120,2:158].astype(np.int16)-128).astype(np.int8)
                quant.set_tensor(qi['index'],q); quant.invoke()
                floating.set_tensor(fi['index'],x); floating.invoke()
                i8=quant.get_tensor(qo['index']).reshape(-1).astype(float)
                dequant=(i8-qo['quantization'][1])*qo['quantization'][0]
                fp=floating.get_tensor(fo['index']).reshape(-1)
                # Check supplied float TFLite and best Keras are the same model
                # on at least one image per archive, without re-exporting either.
                kd=None
                if index==0:
                    kp=np.asarray(keras([x],training=False)).reshape(-1)
                    kd=float(np.max(np.abs(kp-fp)))
                    np.testing.assert_allclose(kp,fp,atol=1e-5,rtol=1e-5)
                rows.append(dict(archive=archive.name,image=name,
                                 labels=[record['user/angle'],record['user/throttle']],
                                 quantized=dequant.tolist(),floating=fp.tolist(),
                                 keras_float_max_abs_error=kd))
        print(f'Evaluated {archive.name}: {len(rows)} cumulative frames',flush=True)
    q=np.array([r['quantized'] for r in rows])
    f=np.array([r['floating'] for r in rows])
    y=np.array([r['labels'] for r in rows])
    delta=np.abs(q-f)
    result=dict(model_sha256=sha256(MODEL),frames=len(rows),sessions=len(archives),
                scope='Samples from provided recordings, potentially used in training; not held-out accuracy.',
                outputs=['steering','throttle'],rgb565_roundtrip_mismatches=0,
                int8_vs_float_mae=delta.mean(0).tolist(),
                int8_vs_float_p95=np.percentile(delta,95,axis=0).tolist(),
                int8_vs_float_max=delta.max(0).tolist(),
                int8_label_mae=np.abs(q-y).mean(0).tolist(),
                float_label_mae=np.abs(f-y).mean(0).tolist(),
                int8_output_range=[q.min(0).tolist(),q.max(0).tolist()],
                keras_vs_float_tflite_max=max(r['keras_float_max_abs_error'] or 0 for r in rows),
                archive_sha256=archives,rows=rows)
    out=ROOT/'build/model_evaluation.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','archive_sha256')},indent=2))


if __name__=='__main__':
    main()
