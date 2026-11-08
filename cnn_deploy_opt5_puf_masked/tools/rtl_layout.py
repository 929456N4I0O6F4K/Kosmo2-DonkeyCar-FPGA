"""Generate model constants and native ROMs without output-channel padding."""
from pathlib import Path
import hashlib
import numpy as np


def write_parallel_roms(layers, interpreter, output: Path):
    from reference import pack_requant
    details = {int(d['index']): d for d in interpreter.get_tensor_details()}
    expected = [(24,5,5,3),(32,5,5,24),(64,5,5,32),(64,3,3,64),
                (16,3,3,64),(100,960),(50,100),(2,50)]
    if [tuple(x['weights'].shape) for x in layers] != expected:
        raise ValueError('Unexpected cropped model geometry')
    if tuple(interpreter.get_input_details()[0]['shape']) != (1,95,156,3):
        raise ValueError('Expected a 95x156x3 model')
    stages = [[x] for x in layers]
    ports = ['input wire clk', 'input wire [2:0] tail_stage', 'input wire tail_group']
    for e, lanes in enumerate([24,32,64]):
        ports += [f'input wire ce{e}, pce{e}', f'input wire [9:0] addr{e}',
                  f'input wire [6:0] paddr{e}', f'output wire [{lanes*8-1}:0] w{e}',
                  f'output wire [{lanes*32-1}:0] b{e}', f'output reg [47:0] p{e}']
    code = ['// Generated from the deployed TFLite.\n`default_nettype none\n',
            'module mypilot_parameters(\n    '+',\n    '.join(ports)+'\n);\n']
    configs=[]
    hashes={}
    for i, items in enumerate(stages):
        x=items[0]
        e=min(i,2)
        w=np.concatenate([x['weights'].reshape(len(x['bias']),-1) for x in items])
        b=np.concatenate([x['bias'] for x in items])
        oc,taps=w.shape
        if any(x['input_zp'] != -128 for x in items):
            raise ValueError('Activation zero point must be -128')
        if np.any(np.abs(w.astype(np.int64)).sum(axis=1)*255+np.abs(b.astype(np.int64)) >= 2**31):
            raise ValueError('32-bit accumulation may overflow')
        words=w.T.copy()
        name=f'stage{i}_weights.mem'
        (output/name).write_text(''.join(row.tobytes()[::-1].hex()+'\n' for row in words),encoding='ascii')
        restored=np.array([list(bytes.fromhex(line)[::-1]) for line in (output/name).read_text().splitlines()],dtype=np.uint8)
        np.testing.assert_array_equal(restored.view(np.int8).T,w)
        hashes[name]=hashlib.sha256((output/name).read_bytes()).hexdigest()
        params=[pack_requant(int(m),int(s),x['output_zp'],x['relu'])
                for x in items for m,s in zip(x['multipliers'],x['shifts'])]
        pname=f'stage{i}_requant.mem'
        (output/pname).write_text(''.join(f'{v:012x}\n' for v in params),encoding='ascii')
        hashes[pname]=hashlib.sha256((output/pname).read_bytes()).hexdigest()
        distributed=i in [0,6,7]
        code += [f'    (* rom_style="{"distributed" if distributed else "block"}", syn_romstyle="{"logic" if distributed else "block_rom"}" *) reg [{oc*8-1}:0] wmem{i} [0:{taps-1}];\n',
                 f'    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem{i} [0:{oc-1}];\n',
                 f'    reg [{oc*8-1}:0] wq{i};\n',
                 f'    localparam [{oc*32-1}:0] B{i} = {oc*32}\'h'+''.join(f'{int(v)&0xffffffff:08x}' for v in b[::-1])+';\n',
                 f'    initial begin $readmemh("{name}",wmem{i}); $readmemh("{pname}",pmem{i}); end\n',
                 f'    always @(posedge clk) if (ce{e}'+(f' && tail_stage==3\'d{i}' if e==2 else '')+f') wq{i} <= wmem{i}[addr{e}];\n']
        if i<2:
            code += [f'    assign w{i}=wq{i}; assign b{i}=B{i};\n',
                     f'    always @(posedge clk) if(pce{i}) p{i} <= pmem{i}[paddr{i}];\n']
        if x['op']=='CONV_2D':
            _,ih,iw,ic=map(int,details[x['input_index']]['shape'])
            _,oh,ow,_=map(int,details[x['output_index']]['shape'])
            k=x['weights'].shape[1]; s=2 if k==5 else 1
            if (ih-k)//s+1!=oh or (iw-k)//s+1!=ow:
                raise ValueError('Only VALID convolution is supported')
            row_span=k*ic; row_skip=(iw-k)*ic; sx=s*ic; sy=s*iw*ic
        else:
            oh=ow=1; row_span=taps; row_skip=sx=sy=0
        configs.append(dict(stage=i,name='+'.join(x['name'] for x in items),taps=taps,
                            row_span=row_span,row_skip=row_skip,stride_x=sx,stride_y=sy,
                            out_h=oh,out_w=ow,out_c=oc,groups=(oc+63)//64))
    code += ['    reg [511:0] tail_w; reg [2047:0] tail_b;\n',
             '    assign w2=tail_w; assign b2=tail_b;\n',
             '    always @* begin\n        tail_w=0; tail_b=0;\n        case(tail_stage)\n']
    for i,oc in [(2,64),(3,64),(4,16),(5,100),(6,50),(7,2)]:
        if oc>64:
            code += [f"            3'd{i}: begin tail_w=tail_group ? {{224'b0,wq{i}[799:512]}} : wq{i}[511:0]; tail_b=tail_group ? {{896'b0,B{i}[3199:2048]}} : B{i}[2047:0]; end\n"]
        else:
            code += [f"            3'd{i}: begin tail_w=wq{i}; tail_b=B{i}; end\n"]
    code += ['        endcase\n    end\n    always @(posedge clk) if(pce2) begin\n        case(tail_stage)\n']
    code += [f"            3'd{i}: p2 <= pmem{i}[paddr2];\n" for i in range(2,8)]
    code += ["            default: p2 <= 0;\n        endcase\n    end\nendmodule\n`default_nettype wire\n"]
    (output/'mypilot_parameters.v').write_text(''.join(code),encoding='ascii')
    cfg=['// Generated for 95x156 model.\n']
    for prefix in ('STEERING', 'THROTTLE'):
        layer=layers[-1]
        cfg += [f"localparam signed [31:0] {prefix}_ZP = {layer['output_zp']};\n",
                f"localparam signed [31:0] {prefix}_SCALE_Q30 = {round(layer['output_scale']*(1<<30))};\n"]
    cfg += ['always @* begin\n    cfg_taps=0; cfg_row_span=0; cfg_row_skip=0; cfg_stride_x=0; cfg_stride_y=0;\n',
            '    cfg_out_h=0; cfg_out_w=0; cfg_out_c=0; cfg_ring_bytes=0;\n    case(tail_stage)\n']
    for x in configs[2:]:
        cfg += [f"        3'd{x['stage']}: begin\n"]
        for key in ['taps','row_span','row_skip','stride_x','stride_y','out_h','out_w','out_c']:
            cfg += [f"            cfg_{key}={x[key]};\n"]
        if x['stage']==2: cfg += ['            cfg_ring_bytes=6912;\n']
        cfg += ['        end\n']
    cfg += ['    endcase\nend\n']
    (output/'model_config.vh').write_text(''.join(cfg),encoding='ascii')
    return dict(mac_lanes=[24,32,64],weight_bytes=sum(x['weights'].size for x in layers),
                frame_bytes=44460,line_buffer_bytes=[10944,6912],tail_buffer_bytes=[9216,6272],
                stages=configs,rom_sha256=hashes)
