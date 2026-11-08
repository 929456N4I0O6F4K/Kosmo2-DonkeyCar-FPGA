#!/usr/bin/env python3
"""
镜像对称性诊断报告 (模拟反向流程)

同一帧照片 → 水平翻转 (镜像世界, 真实角度取反) → 模型推理,
与原图预测并排对比, 连续整圈回放, 量化模型镜像等变性:

  理想等变:  Pf(翻转帧) = −P(原图)  →  失配 asym = P + Pf 应为 0
  TTA 模拟:  (P − Pf)/2  — 部署端若启用 原图+翻转平均 即为此输出

用途: 区分两类病因
  a) 失配大 (|asym|大) → 模型翻转等变性差 (依赖非对称背景特征)
  b) P≈−Pf 但都不到 |T| → 左右对称的幅值压缩 (镜像增广救不了)

预处理与 FPGA 部署一致: 裁剪(25/2/2) + /255 (左右对称, 翻转等价)
用法:
  python report_mirror_compare.py [model.keras] [输出html路径]
"""
import os
import sys
import csv
import json
import numpy as np
from pathlib import Path
MYSIM_DIR = str(Path(__file__).resolve().parents[2])
CAR_DIR = str(Path(MYSIM_DIR).parent)

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluate.evaluate_sim_vs_physic import PHYSIC_DIR, load_physic_records, load_img
from report.report_angle_compare import (ANGLE_BINS, BIN_NAMES, bin_of, flags_of,
                                         DEFAULT_MODEL, STRAIGHT_TH, SHARP_TH,
                                         UNDER_RATIO)

DEFAULT_OUT = (f'{MYSIM_DIR}/reports/'
               'angle_mirror_report.html')
BATCH = 256
MISMATCH_TH = 0.3


def predict(model, recs, tag, flip):
    """分批推理, flip=True 时水平镜像输入"""
    outs = []
    for i in range(0, len(recs), BATCH):
        imgs = np.array([load_img(r['_img']) for r in recs[i:i + BATCH]])
        if flip:
            imgs = imgs[:, ::-1, :].copy()
        y = model.predict(imgs, verbose=0, batch_size=BATCH)
        if isinstance(y, (list, tuple)):
            y = np.stack([np.asarray(o).reshape(-1) for o in y], axis=1)
        else:
            y = np.asarray(y).reshape(len(imgs), -1)
        outs.append(y)
        done = min(i + BATCH, len(recs))
        print(f'  {tag}推理 {done}/{len(recs)}')
    return np.concatenate(outs)


def main():
    model_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    out_html = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    out_csv = str(Path(out_html).with_suffix('.csv'))

    print('加载模型:', model_path)
    model = tf.keras.models.load_model(model_path, compile=False)

    recs = load_physic_records()
    n = len(recs)
    print(f'physicaldata2 行车帧: {n}')

    y_raw = predict(model, recs, '原图', flip=False)
    y_flip = predict(model, recs, '翻转', flip=True)

    y_true = np.array([r.get('user/angle', 0.0) for r in recs])
    c0 = abs(np.corrcoef(y_raw[:, 0], y_true)[0, 1])
    c1 = abs(np.corrcoef(y_raw[:, 1], y_true)[0, 1])
    a_col = 0 if c0 >= c1 else 1
    print(f'输出列映射: [{a_col}]=angle (corr {c0:.3f}/{c1:.3f})')
    p = y_raw[:, a_col]              # 原图预测
    pf = y_flip[:, a_col]            # 翻转帧预测
    t = y_true
    asym = p + pf                    # 失配 (理想 0)
    tta = (p - pf) / 2               # TTA 合成输出 (部署端 翻转平均 即此值)

    # ============ 汇总统计 ============
    def under_rate(pred, m):
        return float((np.abs(pred[m]) <
                      UNDER_RATIO * np.abs(t[m])).mean() * 100)

    sharp = np.abs(t) >= SHARP_TH
    sharpL = sharp & (t < 0)         # 急左 (含中左? 不, sharp=|t|>=0.5 → 急左/急右)
    sharpR = sharp & (t > 0)
    mirror_mae = float(np.mean(np.abs(asym)))

    summary = {
        'n': n,
        'mirror_mae': mirror_mae,
        'corr_eq': float(np.corrcoef(p, -pf)[0, 1]),
        'mismatch_n': int((np.abs(asym) > MISMATCH_TH).sum()),
        'tta_mae': float(np.mean(np.abs(tta - t))),
        'sharp_n': int(sharp.sum()),
        'sharp_under_orig': under_rate(p, sharp),
        'sharp_under_mir': under_rate(pf, sharp),
        'sharp_under_tta': under_rate(tta, sharp),
        'bins': [],
    }
    for b, name in enumerate(BIN_NAMES):
        m = np.array([bin_of(x) for x in t]) == b
        if not m.any():
            summary['bins'].append({'name': name, 'n': 0})
            continue
        summary['bins'].append({
            'name': name, 'n': int(m.sum()),
            'orig_mae': float(np.mean(np.abs(p[m] - t[m]))),
            'mir_mae': float(np.mean(np.abs(asym[m]))),
            'asym_bias': float(np.mean(asym[m])),
            'under_orig': under_rate(p, m),
            'under_mir': under_rate(pf, m),
            'under_tta': under_rate(tta, m),
        })
    # 急左/急右到位率专项 (|x| >= 0.8|t| 认为到位)
    for key, m in (('extL', sharpL), ('extR', sharpR)):
        if m.any():
            summary[key] = {
                'n': int(m.sum()),
                'reach_orig': float((np.abs(p[m]) >=
                                     UNDER_RATIO * np.abs(t[m])).mean() * 100),
                'reach_mir': float((np.abs(pf[m]) >=
                                    UNDER_RATIO * np.abs(t[m])).mean() * 100),
                'reach_tta': float((np.abs(tta[m]) >=
                                    UNDER_RATIO * np.abs(t[m])).mean() * 100),
                'mag_orig': float(np.mean(np.abs(p[m]))),
                'mag_mir': float(np.mean(np.abs(pf[m]))),
                'mag_true': float(np.mean(np.abs(t[m]))),
            }

    # ============ 逐帧记录 ============
    flag_cnt = {'欠转': 0, '过冲': 0, '反向': 0, '预判': 0, '镜像失配': 0}
    rows = []
    for i, r in enumerate(recs):
        session = os.path.basename(os.path.dirname(os.path.dirname(r['_img'])))
        fname = os.path.basename(r['_img'])
        img_path = f'{session}/{fname}'
        b = bin_of(t[i])
        fl = flags_of(t[i], p[i])
        if abs(asym[i]) > MISMATCH_TH:
            fl.append('镜像失配')
        for k in fl:
            flag_cnt[k] += 1
        rows.append({'img': img_path, 'session': session, 'file': fname,
                     't': round(float(t[i]), 4),
                     'p': round(float(p[i]), 4),
                     'pf': round(float(pf[i]), 4),
                     'as': round(float(asym[i]), 4),
                     'tt': round(float(tta[i]), 4), 'b': b, 'f': fl})
    summary['flag_cnt'] = flag_cnt

    # ============ CSV ============
    with open(out_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['session', 'file', 'img_path', 'true_angle',
                    'pred_orig', 'pred_flip', 'asym_p_plus_pf',
                    'tta_p_minus_pf_over2', 'bin', 'flags'])
        for r in rows:
            rel_path = f"{r['session']}/{r['file']}"
            w.writerow([r['session'], r['file'], rel_path, r['t'], r['p'],
                        r['pf'], r['as'], r['tt'], BIN_NAMES[r['b']],
                        '|'.join(r['f'])])
    print('CSV 已保存:', out_csv)

    # ============ HTML ============
    data_json = json.dumps(rows, ensure_ascii=False)
    bin_json = json.dumps(BIN_NAMES, ensure_ascii=False)
    sum_json = json.dumps(summary, ensure_ascii=False)
    html = HTML_TMPL.replace('__DATA__', data_json) \
                    .replace('__BINS__', bin_json) \
                    .replace('__SUM__', sum_json) \
                    .replace('__MODEL__', os.path.basename(
                        os.path.dirname(model_path)))
    with open(out_html, 'w') as f:
        f.write(html)
    print(f'HTML 已保存: {out_html} '
          f'({os.path.getsize(out_html) / 1e6:.1f} MB)')
    print(f'汇总: 镜像一致性MAE {mirror_mae:.4f}  '
          f'等变相关 {summary["corr_eq"]:.4f}  '
          f'失配帧 {summary["mismatch_n"]}  TTA_MAE {summary["tta_mae"]:.4f}')
    for key, name in (('extL', '急左'), ('extR', '急右')):
        e = summary.get(key)
        if e:
            print(f'  {name}(n={e["n"]}): 平均|真实|={e["mag_true"]:.3f} '
                  f'原图|pred|={e["mag_orig"]:.3f} 翻转|pf|={e["mag_mir"]:.3f}'
                  f'  到位率 原/{e["reach_orig"]:.1f}% '
                  f'镜像/{e["reach_mir"]:.1f}% TTA/{e["reach_tta"]:.1f}%')


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>镜像对称性诊断 __MODEL__</title>
<style>
body{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:16px;background:#111;color:#ddd}
h1{font-size:20px} h2{font-size:15px;margin:14px 0 6px}
.note{color:#888;font-size:12px;line-height:1.7;max-width:900px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}
.card{background:#1c1c1c;border:1px solid #333;border-radius:8px;padding:10px 14px;min-width:150px}
.card .v{font-size:20px;font-weight:600;color:#4fc3f7}
.card .l{font-size:12px;color:#999}
#lap{background:#1a1a1a;border:1px solid #333;border-radius:10px;padding:12px;margin:12px 0}
#chart{width:100%;height:230px;display:block;background:#111;border-radius:6px;cursor:crosshair}
.legend{font-size:12px;color:#999;margin:6px 0}
.legend .k{display:inline-block;width:22px;height:3px;vertical-align:middle;margin:0 4px 2px 12px}
.lapbar{display:flex;align-items:center;gap:8px;margin:10px 0;flex-wrap:wrap}
.lapbar button{background:#2a2a2a;color:#ddd;border:1px solid #444;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:15px}
.lapbar button.play{background:#0277bd;border-color:#0277bd;min-width:60px}
.lapbar select{background:#1c1c1c;color:#ddd;border:1px solid #444;border-radius:6px;padding:5px 8px;max-width:340px}
.bigview{display:flex;gap:14px;align-items:flex-start;margin-top:10px;flex-wrap:wrap}
.pan img{width:400px;max-width:44vw;border-radius:8px;background:#000;display:block}
.pan img.mir{transform:scaleX(-1)}
.paninfo{font-size:13px;line-height:1.8;margin-top:6px}
.ang{font-size:24px;font-weight:700;font-family:ui-monospace,Consolas,monospace}
.t-l{color:#4fc3f7}.t-p{color:#ffb74d}.t-g{color:#66bb6a}.t-v{color:#ba68c8}
.badge{display:inline-block;border-radius:4px;padding:1px 6px;margin:0 2px;font-size:12px}
.b-欠转{background:#b71c1c}.b-过冲{background:#e65100}.b-反向{background:#8e24aa}
.b-预判{background:#1b5e20}.b-镜像失配{background:#ad1457}
table{border-collapse:collapse;width:100%;font-size:13px}
th{position:sticky;top:0;background:#222;cursor:pointer;padding:6px 8px;border-bottom:2px solid #444;white-space:nowrap;z-index:2}
td{padding:4px 8px;border-bottom:1px solid #2a2a2a;white-space:nowrap}
tr:hover td{background:#232323}
img.thumb{width:110px;height:82px;object-fit:cover;border-radius:4px;background:#000}
.num{font-family:ui-monospace,Consolas,monospace;text-align:right}
.pos{color:#ef9a9a}.neg{color:#a5d6a7}
#tblwrap{max-height:560px;overflow:auto;border:1px solid #2a2a2a;border-radius:6px}
.ctrl{margin:10px 0;line-height:2.2}
.ctrl button{background:#2a2a2a;color:#ddd;border:1px solid #444;border-radius:6px;padding:4px 12px;cursor:pointer;margin-right:4px}
.ctrl button.on{background:#0277bd;border-color:#0277bd}
input{background:#1c1c1c;color:#ddd;border:1px solid #444;border-radius:6px;padding:5px 8px}
#cnt{color:#999;font-size:12px;margin-left:8px}
.hl td{background:#2a1a1a}
</style></head><body>
<h1>镜像对称性诊断 (模拟反向流程) — <span id="model"></span></h1>
<div class="note">原理: 同一张照片水平翻转后喂给模型 = 小车在镜像赛道上行驶 (真实角度取反)。
若训练中的 50% 镜像增广充分起效, 翻转帧预测 Pf 应 ≈ −P(原图预测), 即失配 asym=P+Pf≈0。
<b style="color:#ef9a9a">失配大</b> → 模型依赖了不可镜像的背景特征 (等变性差);
<b style="color:#ef9a9a">P≈−Pf 但两者幅值都缩水</b> → 左右对称的幅值压缩, 镜像增广无能为力, 需从损失/采样下手。
TTA 列 = (P−Pf)/2, 即部署端若采用"原图+翻转取平均"两次推理时的实际输出。</div>
<div class="cards" id="cards"></div>

<div id="lap">
<h2 style="margin-top:0">整圈镜像回放 (左: 原图 | 右: 同一照片的镜像世界)</h2>
<div class="lapbar">
 <select id="sessSel"></select>
 <button id="btnPrev" title="上一帧 (←)">⏮</button>
 <button id="btnPlay" class="play" title="播放/暂停 (空格)">▶</button>
 <button id="btnNext" title="下一帧 (→)">⏭</button>
 <span style="color:#888;font-size:12px">速度</span>
 <select id="spd"><option value="500">0.5s/帧</option><option value="250" selected>0.25s/帧</option><option value="100">0.1s/帧</option></select>
 <span id="posLbl" style="color:#888;font-size:12px;margin-left:8px"></span>
 <span style="color:#666;font-size:12px">← → 步进, 空格播放, 点击曲线跳帧</span>
</div>
<svg id="chart" viewBox="0 0 1000 230" preserveAspectRatio="none">
 <line x1="0" y1="115" x2="1000" y2="115" stroke="#333" stroke-width="1"/>
 <line x1="0" y1="12" x2="1000" y2="12" stroke="#222" stroke-width="1"/>
 <line x1="0" y1="218" x2="1000" y2="218" stroke="#222" stroke-width="1"/>
 <polyline id="lnT" fill="none" stroke="#4fc3f7" stroke-width="1.5"/>
 <polyline id="lnP" fill="none" stroke="#ffb74d" stroke-width="1.5"/>
 <polyline id="lnF" fill="none" stroke="#66bb6a" stroke-width="1.5" stroke-dasharray="4 3"/>
 <polyline id="lnA" fill="none" stroke="#ba68c8" stroke-width="1.5"/>
 <g id="dots"></g>
 <line id="cursor" y1="0" y2="230" stroke="#fff" stroke-width="1" opacity="0.7"/>
</svg>
<div class="legend">图例<span class="k" style="background:#4fc3f7"></span>真实角度
<span class="k" style="background:#ffb74d"></span>原图预测 P
<span class="k" style="background:#66bb6a;border-top:1px dashed #66bb6a"></span>−翻转预测 −Pf (与橙线重合=完美镜像等变)
<span class="k" style="background:#ba68c8"></span>TTA 合成输出
<span class="k" style="background:none;border-bottom:3px solid #ff5252"></span>镜像失配
<span class="k" style="background:none;border-bottom:3px solid #e040fb"></span>TTA反向帧 (下方=左转/负)</div>
<div class="bigview">
 <div class="pan"><img id="imgO" alt="原图">
  <div class="paninfo" id="infoO"></div></div>
 <div class="pan"><img id="imgF" class="mir" alt="镜像帧">
  <div class="paninfo" id="infoF"></div></div>
 <div class="paninfo" id="infoA" style="flex:1;min-width:220px"></div>
</div>
</div>

<h2>分箱镜像统计 (到位率 = |预测| ≥ 0.8|真实|)</h2>
<table id="bintbl" style="width:auto"></table>

<h2>失配分析表 (全量, 可筛选排序)</h2>
<div class="ctrl" id="ctrl"></div>
<div id="tblwrap"><table id="tbl">
<thead><tr>
<th data-k="idx">#</th><th>图片</th><th data-k="session">session / 帧</th>
<th data-k="t">真实角度</th><th data-k="p">原图预测 P</th><th data-k="pf">翻转预测 Pf</th>
<th data-k="as">失配 P+Pf</th><th data-k="tt">TTA输出</th>
<th data-k="b">分箱</th><th>标记</th></tr></thead>
<tbody id="tb"></tbody></table></div>

<script>
const DATA=__DATA__, BINS=__BINS__, SUM=__SUM__;
document.getElementById('model').textContent='__MODEL__';
document.title='镜像对称性诊断 __MODEL__';

// ============ 汇总卡片 ============
const fmt=x=>x==null?'-':x.toFixed(1)+'%';
const cards=[
 ['镜像一致性 MAE |P+Pf|',SUM.mirror_mae.toFixed(4)],
 ['等变相关 corr(P,−Pf)',SUM.corr_eq.toFixed(4)],
 ['失配帧数 |asym|>0.3',SUM.mismatch_n],
 ['TTA MAE',SUM.tta_mae.toFixed(4)],
 ['大转弯欠转率 原/镜像/TTA',fmt(SUM.sharp_under_orig)+' / '+fmt(SUM.sharp_under_mir)+' / '+fmt(SUM.sharp_under_tta)],
 ['急左到位率 原/镜像/TTA',ext(SUM.extL)],
 ['急右到位率 原/镜像/TTA',ext(SUM.extR)]];
function ext(e){if(!e)return'-';return fmt(e.reach_orig)+' / '+fmt(e.reach_mir)+' / '+fmt(e.reach_tta)+' (n='+e.n+')'}
document.getElementById('cards').innerHTML=cards.map(c=>
 `<div class="card"><div class="v">${c[1]}</div><div class="l">${c[0]}</div></div>`).join('');

// ============ 分箱表 ============
let bh='<tr><th>分箱</th><th>样本</th><th>原图MAE</th><th>镜像失配MAE</th><th>失配偏置</th>'+
 '<th>欠转率 原</th><th>欠转率 镜像</th><th>欠转率 TTA</th></tr>';
SUM.bins.forEach(b=>{
 const hl=(b.name==='急左'||b.name==='急右')?' class="hl"':'';
 bh+=`<tr${hl}><td>${b.name}</td><td class="num">${b.n}</td>`+
 (b.orig_mae!==undefined?
  `<td class="num">${b.orig_mae.toFixed(4)}</td><td class="num">${b.mir_mae.toFixed(4)}</td>`+
  `<td class="num ${b.asym_bias>0?'pos':'neg'}">${b.asym_bias>0?'+':''}${b.asym_bias.toFixed(4)}</td>`+
  `<td class="num">${b.under_orig.toFixed(1)}%</td><td class="num">${b.under_mir.toFixed(1)}%</td>`+
  `<td class="num">${b.under_tta.toFixed(1)}%</td>`
  :'<td colspan="6">-</td>')+'</tr>'});
document.getElementById('bintbl').innerHTML=bh;

// ============ 整圈回放 ============
const SESS=[];
DATA.forEach((r,i)=>{const s=SESS[SESS.length-1];
 if(!s||s.name!==r.session){SESS.push({name:r.session,start:i,n:1})}else{s.n++}});
const sessSel=document.getElementById('sessSel');
SESS.forEach((s,i)=>{const o=document.createElement('option');
 o.value=i;o.textContent=`${s.name} (${s.n} 帧)`;sessSel.appendChild(o)});
let curS=0;SESS.forEach((s,i)=>{if(s.n>SESS[curS].n)curS=i});sessSel.value=curS;

const chart=document.getElementById('chart'),lnT=document.getElementById('lnT'),
 lnP=document.getElementById('lnP'),lnF=document.getElementById('lnF'),
 lnA=document.getElementById('lnA'),dots=document.getElementById('dots'),
 cursor=document.getElementById('cursor'),
 imgO=document.getElementById('imgO'),imgF=document.getElementById('imgF'),
 infoO=document.getElementById('infoO'),infoF=document.getElementById('infoF'),
 infoA=document.getElementById('infoA'),posLbl=document.getElementById('posLbl');
let curPos=0,timer=null;

function sessData(){const s=SESS[curS];return DATA.slice(s.start,s.start+s.n)}
function drawChart(){
 const rows=sessData(),n=rows.length,step=Math.max(1,Math.ceil(n/1200));
 const pt=a=>(115-a*100).toFixed(1);
 const X=i=>(i/(n-1)*1000).toFixed(1);
 let T='',P='',F='',A='';
 for(let i=0;i<n;i+=step){const r=rows[i];
  T+=`${X(i)},${pt(r.t)} `;P+=`${X(i)},${pt(r.p)} `;
  F+=`${X(i)},${pt(-r.pf)} `;A+=`${X(i)},${pt(r.tt)} `;}
 lnT.setAttribute('points',T.trim());lnP.setAttribute('points',P.trim());
 lnF.setAttribute('points',F.trim());lnA.setAttribute('points',A.trim());
 let d='';
 for(let i=0;i<n;i+=step){const r=rows[i],x=X(i);
  if(Math.abs(r.as)>0.3)d+=`<circle cx="${x}" cy="${pt(-r.pf)}" r="2.5" fill="#ff5252"/>`;
  else if(Math.abs(r.t)>=0.15&&r.t*r.tt<0)d+=`<circle cx="${x}" cy="${pt(r.tt)}" r="2.5" fill="#e040fb"/>`;}
 dots.innerHTML=d;
 moveCursor();
}
function moveCursor(){
 const s=SESS[curS],x=(curPos/(s.n-1)*1000).toFixed(1);
 cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);
 posLbl.textContent=`第 ${curPos+1} / ${s.n} 帧`;
}
function angHtml(v,cls){return `<span class="ang ${cls}">${v.toFixed(3)}</span>`}
function bigShow(){
 const r=DATA[SESS[curS].start+curPos];
 imgO.src=r.img;imgF.src=r.img;
 infoO.innerHTML=`<div style="color:#999">原图世界</div>`+
  `<div>${angHtml(r.t,'t-l')} <span style="color:#888">真实</span></div>`+
  `<div>${angHtml(r.p,'t-p')} <span style="color:#888">预测 P</span></div>`;
 infoF.innerHTML=`<div style="color:#999">镜像世界 (同一照片水平翻转)</div>`+
  `<div>${angHtml(-r.t,'t-l')} <span style="color:#888">镜像真实</span></div>`+
  `<div>${angHtml(r.pf,'t-g')} <span style="color:#888">翻转预测 Pf</span></div>`;
 infoA.innerHTML=
  `<div>失配 P+Pf <span class="ang" style="color:${Math.abs(r.as)>0.3?'#ff5252':'#ccc'};font-size:20px">${r.as>0?'+':''}${r.as.toFixed(3)}</span></div>`+
  `<div>TTA输出 (P−Pf)/2 ${angHtml(r.tt,'t-v')}</div>`+
  `<div>分箱 <b>${BINS[r.b]}</b> ${r.f.map(f=>`<span class="badge b-${f}">${f}</span>`).join('')}</div>`+
  `<div style="color:#666;font-size:11px">${r.session}<br>${r.file}</div>`;
 moveCursor();
}
function setPos(p){
 const s=SESS[curS];
 curPos=Math.max(0,Math.min(s.n-1,p));bigShow();
}
function stopPlay(){if(timer){clearInterval(timer);timer=null;btnPlay.textContent='▶'}}
const btnPlay=document.getElementById('btnPlay');
btnPlay.onclick=()=>{if(timer){stopPlay();return}
 btnPlay.textContent='⏸';
 timer=setInterval(()=>{if(curPos>=SESS[curS].n-1){stopPlay();return}
  setPos(curPos+1)},parseInt(spd.value))};
document.getElementById('btnPrev').onclick=()=>{stopPlay();setPos(curPos-1)};
document.getElementById('btnNext').onclick=()=>{stopPlay();setPos(curPos+1)};
const spd=document.getElementById('spd');
spd.onchange=()=>{if(timer){stopPlay();btnPlay.onclick()}};
sessSel.onchange=()=>{stopPlay();curS=parseInt(sessSel.value);curPos=0;drawChart();bigShow()};
chart.onclick=e=>{
 const rect=chart.getBoundingClientRect();
 const frac=(e.clientX-rect.left)/rect.width;
 stopPlay();setPos(Math.round(frac*(SESS[curS].n-1)))};
document.addEventListener('keydown',e=>{
 if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
 if(e.key==='ArrowLeft'){stopPlay();setPos(curPos-1);e.preventDefault()}
 else if(e.key==='ArrowRight'){stopPlay();setPos(curPos+1);e.preventDefault()}
 else if(e.key===' '){btnPlay.onclick();e.preventDefault()}});
drawChart();bigShow();

// ============ 失配分析表 ============
const st={bin:'all',flag:'all',sort:'idx',q:'',minAs:0};
const ctrl=document.getElementById('ctrl');
function group(label){const s=document.createElement('span');s.textContent=label+' ';
 s.style.cssText='color:#888;margin-left:12px';ctrl.appendChild(s);
 const c=document.createElement('span');ctrl.appendChild(c);return c}
function btn(g,label,cb,on){const b=document.createElement('button');b.textContent=label;
 b.className=on?'on':'';
 b.onclick=()=>{[...g.querySelectorAll('button')].forEach(x=>x.classList.remove('on'));
  b.classList.add('on');cb();render()};g.appendChild(b)}
const gBin=group('分箱'),gFlag=group('标记'),gSort=group('排序');
btn(gBin,'全部',()=>{st.bin='all'},true);
BINS.forEach((n,i)=>btn(gBin,n,()=>{st.bin=i},false));
btn(gFlag,'全部',()=>{st.flag='all'},true);
['欠转','镜像失配','反向','预判'].forEach(f=>btn(gFlag,f,()=>{st.flag=f},false));
btn(gFlag,'仅异常',()=>{st.flag='abn'},false);
[['|失配|↓','as2'],['失配↓','as'],['失配↑','asU'],['|真实|↓','t2'],['TTA↓','tt'],['帧序','idx']].forEach(([l,k])=>
 btn(gSort,l,()=>{st.sort=k},k==='idx'));
group('筛选');
const q=document.createElement('input');q.placeholder='搜索 session…';q.style.width='160px';
q.oninput=()=>{st.q=q.value;render()};ctrl.appendChild(q);
const ma=document.createElement('input');ma.type='number';ma.step='0.1';ma.value='0';ma.style.width='60px';
ma.title='只显示 |失配| ≥ 该值';
ma.oninput=()=>{st.minAs=parseFloat(ma.value)||0;render()};
ctrl.appendChild(ma);
const sl=document.createElement('span');sl.textContent='≥|失配|';sl.style.color='#888';ctrl.appendChild(sl);
const cnt=document.createElement('span');cnt.id='cnt';ctrl.appendChild(cnt);

const tb=document.getElementById('tb');
function render(){
 let rows=DATA.map((r,i)=>({...r,i}));
 rows=rows.filter(r=>
  (st.bin==='all'||r.b===st.bin)&&
  (st.flag==='all'||(st.flag==='abn'?r.f.some(f=>f!=='预判'):r.f.includes(st.flag)))&&
  Math.abs(r.as)>=st.minAs&&
  (!st.q||r.session.includes(st.q)));
 const s=st.sort;
 if(s==='as2')rows.sort((a,b)=>Math.abs(b.as)-Math.abs(a.as));
 else if(s==='as')rows.sort((a,b)=>b.as-a.as);
 else if(s==='asU')rows.sort((a,b)=>a.as-b.as);
 else if(s==='t2')rows.sort((a,b)=>Math.abs(b.t)-Math.abs(a.t));
 else if(s==='tt')rows.sort((a,b)=>b.tt-a.tt);
 else rows.sort((a,b)=>a.i-b.i);
 cnt.textContent=`显示 ${rows.length} / ${DATA.length} 帧`;
 const frag=document.createDocumentFragment();
 for(const r of rows){
  const tr=document.createElement('tr');
  const asCls=Math.abs(r.as)>0.3?'pos':'';
  tr.innerHTML=`<td class="num">${r.i}</td>`+
   `<td><img class="thumb" loading="lazy" src="${r.img}"></td>`+
   `<td>${r.session}<br><span style="color:#888;font-size:11px">${r.file}</span></td>`+
   `<td class="num">${r.t.toFixed(3)}</td><td class="num">${r.p.toFixed(3)}</td>`+
   `<td class="num">${r.pf.toFixed(3)}</td>`+
   `<td class="num ${asCls}">${r.as>0?'+':''}${r.as.toFixed(3)}</td>`+
   `<td class="num">${r.tt.toFixed(3)}</td>`+
   `<td>${BINS[r.b]}</td>`+
   `<td>${r.f.map(f=>`<span class="badge b-${f}">${f}</span>`).join('')}</td>`;
  frag.appendChild(tr);
 }
 tb.innerHTML='';tb.appendChild(frag);
}
render();
</script></body></html>
"""

if __name__ == '__main__':
    main()
