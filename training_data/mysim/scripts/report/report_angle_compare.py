#!/usr/bin/env python3
"""
角度对比 HTML 报告生成器 (人工分析用)

对 physicaldata2 全量行车帧逐帧推理, 生成:
  1. angle_compare_report.html — 两视图:
     a) 整圈回放: 按 session 连续帧播放 (非随机), 真实/预测角度曲线, 大图逐帧步进
     b) 异常分析表: 图片+真实+预测+误差+分箱+标记, 支持筛选/排序
  2. angle_compare_full.csv   — 全量数据 (供进一步处理)

预处理与 FPGA 部署一致: 裁剪(25/2/2) + /255, 无 CLAHE
输出列顺序动态判断 (与真值相关性高者为 angle)
符号约定: 负=左转, 正=右转 (LEFT_ANGLE=-1)

用法:
  python report_angle_compare.py [model.keras] [输出html路径]
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
from evaluate.evaluate_sim_vs_physic import (PHYSIC_DIR, load_physic_records,
                                        load_img, preprocess)

DEFAULT_MODEL = (f'{MYSIM_DIR}/models/'
                 'mypilot1_s2_physical2_opt4/mypilot1_s2_physical_best.keras')
DEFAULT_OUT = (f'{MYSIM_DIR}/reports/'
               'angle_compare_report.html')

# 分箱定义与训练一致
ANGLE_BINS = [-1.01, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.01]
BIN_NAMES = ['急左', '中左', '小左', '直行', '小右', '中右', '急右']

STRAIGHT_TH = 0.08
SHARP_TH = 0.5
UNDER_RATIO = 0.8
OVERSHOOT = 0.3
BATCH = 256


def bin_of(a):
    for i in range(len(ANGLE_BINS) - 1):
        if ANGLE_BINS[i] <= a < ANGLE_BINS[i + 1]:
            return i
    return len(ANGLE_BINS) - 2


def flags_of(t, p):
    """异常标记: 欠转/过冲/反向/直行预判"""
    f = []
    at, ap = abs(t), abs(p)
    if at >= SHARP_TH and ap < UNDER_RATIO * at:
        f.append('欠转')
    if ap > at + OVERSHOOT:
        f.append('过冲')
    if at >= 0.15 and t * p < 0:
        f.append('反向')
    if at < STRAIGHT_TH and ap > 0.2:
        f.append('预判')
    return f


def predict_batched(model, recs):
    """分批加载图片推理, 返回 (N,2) 原始输出, 避免一次性 800MB 内存"""
    outs = []
    for i in range(0, len(recs), BATCH):
        imgs = np.array([load_img(r['_img']) for r in recs[i:i + BATCH]])
        y = model.predict(imgs, verbose=0, batch_size=BATCH)
        if isinstance(y, (list, tuple)):
            y = np.stack([np.asarray(o).reshape(-1) for o in y], axis=1)
        else:
            y = np.asarray(y).reshape(len(imgs), -1)
        outs.append(y)
        done = min(i + BATCH, len(recs))
        print(f'  推理 {done}/{len(recs)}')
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

    y_raw = predict_batched(model, recs)
    y_true = np.array([r.get('user/angle', 0.0) for r in recs])
    c0 = abs(np.corrcoef(y_raw[:, 0], y_true)[0, 1])
    c1 = abs(np.corrcoef(y_raw[:, 1], y_true)[0, 1])
    a_col = 0 if c0 >= c1 else 1
    print(f'输出列映射: [{a_col}]=angle (corr {c0:.3f}/{c1:.3f})')
    y_pred = y_raw[:, a_col]

    err = y_pred - y_true

    # ============ 汇总统计 ============
    sharp = np.abs(y_true) >= SHARP_TH
    straight = np.abs(y_true) < STRAIGHT_TH
    under = sharp & (np.abs(y_pred) < UNDER_RATIO * np.abs(y_true))
    summary = {
        'n': n,
        'mae': float(np.mean(np.abs(err))),
        'corr': float(np.corrcoef(y_pred, y_true)[0, 1]),
        'straight_n': int(straight.sum()),
        'straight_pred02_pct': float((np.abs(y_pred[straight]) > 0.2).mean() * 100),
        'sharp_n': int(sharp.sum()),
        'sharp_under_pct': float(under.sum() / sharp.sum() * 100),
        'bins': [],
    }
    for b, name in enumerate(BIN_NAMES):
        m = np.array([bin_of(t) for t in y_true]) == b
        if not m.any():
            summary['bins'].append({'name': name, 'n': 0})
            continue
        summary['bins'].append({
            'name': name, 'n': int(m.sum()),
            'mae': float(np.mean(np.abs(err[m]))),
            'bias': float(np.mean(err[m])),
        })
    flag_cnt = {'欠转': 0, '过冲': 0, '反向': 0, '预判': 0}
    rows = []
    for i, r in enumerate(recs):
        session = os.path.basename(os.path.dirname(os.path.dirname(r['_img'])))
        fname = os.path.basename(r['_img'])
        img_path = f'{session}/{fname}'
        b = bin_of(y_true[i])
        fl = flags_of(y_true[i], y_pred[i])
        for k in fl:
            flag_cnt[k] += 1
        rows.append({'img': img_path, 'session': session, 'file': fname,
                     't': round(float(y_true[i]), 4),
                     'p': round(float(y_pred[i]), 4),
                     'e': round(float(err[i]), 4), 'b': b, 'f': fl})
    summary['flag_cnt'] = flag_cnt

    # ============ CSV ============
    with open(out_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['session', 'file', 'img_path', 'true_angle',
                    'pred_angle', 'err', 'bin', 'flags'])
        for r in rows:
            rel_path = f"{r['session']}/{r['file']}"
            w.writerow([r['session'], r['file'], rel_path, r['t'], r['p'],
                        r['e'], BIN_NAMES[r['b']], '|'.join(r['f'])])
    print('CSV 已保存:', out_csv)

    # ============ HTML ============
    data_json = json.dumps(rows, ensure_ascii=False)
    bin_json = json.dumps(BIN_NAMES, ensure_ascii=False)
    sum_json = json.dumps(summary, ensure_ascii=False)
    html = HTML_TMPL.replace('__DATA__', data_json) \
                    .replace('__BINS__', bin_json) \
                    .replace('__SUM__', sum_json) \
                    .replace('__MODEL__', os.path.basename(os.path.dirname(model_path)))
    with open(out_html, 'w') as f:
        f.write(html)
    size_mb = os.path.getsize(out_html) / 1e6
    print(f'HTML 已保存: {out_html} ({size_mb:.1f} MB)')
    print(f'汇总: MAE {summary["mae"]:.4f}  corr {summary["corr"]:.4f}  '
          f'大转弯欠转率 {summary["sharp_under_pct"]:.1f}%  '
          f'直行预判占比 {summary["straight_pred02_pct"]:.1f}%  标记统计 {flag_cnt}')


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>角度对比分析 __MODEL__</title>
<style>
body{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:16px;background:#111;color:#ddd}
h1{font-size:20px} h2{font-size:15px;margin:14px 0 6px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}
.card{background:#1c1c1c;border:1px solid #333;border-radius:8px;padding:10px 14px;min-width:130px}
.card .v{font-size:22px;font-weight:600;color:#4fc3f7}
.card .l{font-size:12px;color:#999}
#lap{background:#1a1a1a;border:1px solid #333;border-radius:10px;padding:12px;margin:12px 0}
#chartbox{width:100%}
#chart{width:100%;height:220px;display:block;background:#111;border-radius:6px;cursor:crosshair}
.legend{font-size:12px;color:#999;margin:6px 0}
.legend .k{display:inline-block;width:22px;height:3px;vertical-align:middle;margin:0 4px 2px 12px}
.lapbar{display:flex;align-items:center;gap:8px;margin:10px 0;flex-wrap:wrap}
.lapbar button{background:#2a2a2a;color:#ddd;border:1px solid #444;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:15px}
.lapbar button.play{background:#0277bd;border-color:#0277bd;min-width:60px}
.lapbar select{background:#1c1c1c;color:#ddd;border:1px solid #444;border-radius:6px;padding:5px 8px;max-width:340px}
.bigview{display:flex;gap:16px;align-items:flex-start;margin-top:10px}
.bigview img{width:480px;max-width:45vw;border-radius:8px;background:#000}
.biginfo{font-size:14px;line-height:1.9}
.biginfo .ang{font-size:30px;font-weight:700;font-family:ui-monospace,Consolas,monospace}
.t-l{color:#4fc3f7}.t-p{color:#ffb74d}.t-e{font-size:20px}
.badge{display:inline-block;border-radius:4px;padding:1px 6px;margin:0 2px;font-size:12px}
.b-欠转{background:#b71c1c}.b-过冲{background:#e65100}.b-反向{background:#8e24aa}.b-预判{background:#1b5e20}
table{border-collapse:collapse;width:100%;font-size:13px}
th{position:sticky;top:0;background:#222;cursor:pointer;padding:6px 8px;border-bottom:2px solid #444;white-space:nowrap;z-index:2}
td{padding:4px 8px;border-bottom:1px solid #2a2a2a;white-space:nowrap}
tr:hover td{background:#232323}
img.thumb{width:120px;height:90px;object-fit:cover;border-radius:4px;background:#000}
.num{font-family:ui-monospace,Consolas,monospace;text-align:right}
.pos{color:#ef9a9a}.neg{color:#a5d6a7}
#tblwrap{max-height:560px;overflow:auto;border:1px solid #2a2a2a;border-radius:6px}
.ctrl{margin:10px 0;line-height:2.2}
.ctrl button{background:#2a2a2a;color:#ddd;border:1px solid #444;border-radius:6px;padding:4px 12px;cursor:pointer;margin-right:4px}
.ctrl button.on{background:#0277bd;border-color:#0277bd}
input{background:#1c1c1c;color:#ddd;border:1px solid #444;border-radius:6px;padding:5px 8px}
#cnt{color:#999;font-size:12px;margin-left:8px}
.bincell{font-size:12px;color:#aaa}
</style></head><body>
<h1>角度对比分析 — <span id="model"></span></h1>
<div class="cards" id="cards"></div>

<div id="lap">
<h2 style="margin-top:0">整圈回放 (连续帧, 模拟小车行驶)</h2>
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
<div id="chartbox"><svg id="chart" viewBox="0 0 1000 220" preserveAspectRatio="none">
 <line x1="0" y1="110" x2="1000" y2="110" stroke="#333" stroke-width="1"/>
 <line x1="0" y1="10" x2="1000" y2="10" stroke="#222" stroke-width="1"/>
 <line x1="0" y1="210" x2="1000" y2="210" stroke="#222" stroke-width="1"/>
 <polyline id="lnT" fill="none" stroke="#4fc3f7" stroke-width="1.5"/>
 <polyline id="lnP" fill="none" stroke="#ffb74d" stroke-width="1.5"/>
 <g id="dots"></g>
 <line id="cursor" y1="0" y2="220" stroke="#fff" stroke-width="1" opacity="0.7"/>
</svg></div>
<div class="legend">图例<span class="k" style="background:#4fc3f7"></span>真实角度
<span class="k" style="background:#ffb74d"></span>预测角度
<span class="k" style="background:none;border-bottom:3px solid #e040fb"></span>反向帧
<span class="k" style="background:none;border-bottom:3px solid #ff5252"></span>欠转帧 (曲线上方=右转/正, 下方=左转/负)</div>
<div class="bigview">
 <img id="bigImg" alt="当前帧">
 <div class="biginfo" id="bigInfo"></div>
</div>
</div>

<h2>分箱统计</h2>
<table id="bintbl" style="width:auto"></table>

<h2>异常分析表 (全量, 可筛选排序)</h2>
<div class="ctrl" id="ctrl"></div>
<div id="tblwrap"><table id="tbl">
<thead><tr>
<th data-k="idx">#</th><th>图片</th><th data-k="session">session / 帧</th>
<th data-k="t">真实角度</th><th data-k="p">预测角度</th><th data-k="e">误差</th>
<th data-k="b">分箱</th><th>标记</th></tr></thead>
<tbody id="tb"></tbody></table></div>

<script>
const DATA=__DATA__, BINS=__BINS__, SUM=__SUM__;
document.getElementById('model').textContent='__MODEL__';
document.title='角度对比分析 __MODEL__';

// ============ 汇总卡片 ============
const cards=[
 ['MAE',SUM.mae.toFixed(4)],['相关系数',SUM.corr.toFixed(4)],
 ['大转弯欠转率',SUM.sharp_under_pct.toFixed(1)+'%'],
 ['直行预判占比',SUM.straight_pred02_pct.toFixed(1)+'%'],
 ['帧数',SUM.n],
 ['欠转/过冲/反向',SUM.flag_cnt['欠转']+' / '+SUM.flag_cnt['过冲']+' / '+SUM.flag_cnt['反向']]];
document.getElementById('cards').innerHTML=cards.map(c=>
 `<div class="card"><div class="v">${c[1]}</div><div class="l">${c[0]}</div></div>`).join('');

// ============ 分箱表 ============
let bh='<tr><th>分箱</th><th>样本</th><th>MAE</th><th>偏差(bias)</th></tr>';
SUM.bins.forEach((b,i)=>{bh+=`<tr><td>${b.name}</td><td class="num">${b.n}</td>`+
 (b.mae!==undefined?`<td class="num">${b.mae.toFixed(4)}</td><td class="num">${b.bias.toFixed(4)}</td>`:'<td colspan=2>-</td>')+'</tr>'});
document.getElementById('bintbl').innerHTML=bh;

// ============ 整圈回放 ============
const SESS=[];
DATA.forEach((r,i)=>{const s=SESS[SESS.length-1];
 if(!s||s.name!==r.session){SESS.push({name:r.session,start:i,n:1})}else{s.n++}});
const sessSel=document.getElementById('sessSel');
SESS.forEach((s,i)=>{const o=document.createElement('option');
 o.value=i;o.textContent=`${s.name} (${s.n} 帧)`;sessSel.appendChild(o)});
// 默认选最长 session (主圈)
let curS=0;SESS.forEach((s,i)=>{if(s.n>SESS[curS].n)curS=i});sessSel.value=curS;

const chart=document.getElementById('chart'),lnT=document.getElementById('lnT'),
 lnP=document.getElementById('lnP'),dots=document.getElementById('dots'),
 cursor=document.getElementById('cursor'),bigImg=document.getElementById('bigImg'),
 bigInfo=document.getElementById('bigInfo'),posLbl=document.getElementById('posLbl');
let curPos=0,timer=null;

function sessData(){const s=SESS[curS];return DATA.slice(s.start,s.start+s.n)}
function drawChart(){
 const rows=sessData(),n=rows.length,step=Math.max(1,Math.ceil(n/1200));
 const pt=a=>(110-a*95).toFixed(1);
 let t='',p='';
 for(let i=0;i<n;i+=step){t+=`${(i/(n-1)*1000).toFixed(1)},${pt(rows[i].t)} `;
  p+=`${(i/(n-1)*1000).toFixed(1)},${pt(rows[i].p)} `;}
 lnT.setAttribute('points',t.trim());lnP.setAttribute('points',p.trim());
 let d='';
 for(let i=0;i<n;i+=step){const r=rows[i];
  if(r.f.includes('反向'))d+=`<circle cx="${(i/(n-1)*1000).toFixed(1)}" cy="${pt(r.p)}" r="2.5" fill="#e040fb"/>`;
  else if(r.f.includes('欠转'))d+=`<circle cx="${(i/(n-1)*1000).toFixed(1)}" cy="${pt(r.p)}" r="2.5" fill="#ff5252"/>`;}
 dots.innerHTML=d;
 moveCursor();
}
function moveCursor(){
 const s=SESS[curS],x=(curPos/(s.n-1)*1000).toFixed(1);
 cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);
 posLbl.textContent=`第 ${curPos+1} / ${s.n} 帧`;
}
function bigShow(){
 const r=DATA[SESS[curS].start+curPos];
 bigImg.src=r.img;
 const eCls=r.e>0?'t-p':'t-l';
 bigInfo.innerHTML=
  `<div><span class="ang t-l">${r.t.toFixed(3)}</span> <span style="color:#888">真实(左−/右+)</span></div>`+
  `<div><span class="ang t-p">${r.p.toFixed(3)}</span> <span style="color:#888">预测</span></div>`+
  `<div class="t-e ${r.e>0?'pos':'neg'}">误差 ${r.e>0?'+':''}${r.e.toFixed(3)}</div>`+
  `<div>分箱 <b>${BINS[r.b]}</b> ${r.f.map(f=>`<span class="badge b-${f}">${f}</span>`).join('')}</div>`+
  `<div style="color:#666;font-size:11px">${r.session}<br>${r.file}</div>`;
 moveCursor();
}
function setPos(p,keepPlay){
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

// ============ 异常分析表 ============
const st={bin:'all',flag:'all',sort:'idx',q:'',minE:0};
const ctrl=document.getElementById('ctrl');
function group(label){const s=document.createElement('span');s.textContent=label+' ';
 s.style.cssText='color:#888;margin-left:12px';ctrl.appendChild(s);
 const c=document.createElement('span');ctrl.appendChild(c);return c}
function btn(g,label,cb,on){const b=document.createElement('button');b.textContent=label;
 b.className=on?'on':'';b.title=label;
 b.onclick=()=>{[...g.querySelectorAll('button')].forEach(x=>x.classList.remove('on'));
  b.classList.add('on');cb();render()};g.appendChild(b)}
const gBin=group('分箱'),gFlag=group('标记'),gSort=group('排序');
btn(gBin,'全部',()=>{st.bin='all'},true);
BINS.forEach((n,i)=>btn(gBin,n,()=>{st.bin=i},false));
btn(gFlag,'全部',()=>{st.flag='all'},true);
['欠转','过冲','反向','预判'].forEach(f=>btn(gFlag,f,()=>{st.flag=f},false));
btn(gFlag,'仅异常',()=>{st.flag='abn'},false);
[['误差↓','e2'],['误差↑','e'],['|误差|↓','a2'],['真实角度↓','t2'],['帧序','idx']].forEach(([l,k])=>
 btn(gSort,l,()=>{st.sort=k},k==='idx'));
group('筛选');
const q=document.createElement('input');q.placeholder='搜索 session…';q.style.width='180px';
q.oninput=()=>{st.q=q.value;render()};ctrl.appendChild(q);
const me=document.createElement('input');me.type='number';me.step='0.05';me.value='0';me.style.width='60px';
me.title='只显示 |误差| ≥ 该值';
me.oninput=()=>{st.minE=parseFloat(me.value)||0;render()};
ctrl.appendChild(me);
const sl=document.createElement('span');sl.textContent='≥|误差|';sl.style.color='#888';ctrl.appendChild(sl);
const cnt=document.createElement('span');cnt.id='cnt';ctrl.appendChild(cnt);

const tb=document.getElementById('tb');
function render(){
 let rows=DATA.map((r,i)=>({...r,i}));
 rows=rows.filter(r=>
  (st.bin==='all'||r.b===st.bin)&&
  (st.flag==='all'||(st.flag==='abn'?r.f.some(f=>f!=='预判'):r.f.includes(st.flag)))&&
  Math.abs(r.e)>=st.minE&&
  (!st.q||r.session.includes(st.q)));
 const s=st.sort;
 if(s==='e2')rows.sort((a,b)=>b.e-a.e);
 else if(s==='e')rows.sort((a,b)=>a.e-b.e);
 else if(s==='a2')rows.sort((a,b)=>Math.abs(b.e)-Math.abs(a.e));
 else if(s==='t2')rows.sort((a,b)=>b.t-a.t);
 else rows.sort((a,b)=>a.i-b.i);
 cnt.textContent=`显示 ${rows.length} / ${DATA.length} 帧`;
 const frag=document.createDocumentFragment();
 for(const r of rows){
  const tr=document.createElement('tr');
  const eCls=r.e>0?'pos':'neg';
  tr.innerHTML=`<td class="num">${r.i}</td>`+
   `<td><img class="thumb" loading="lazy" src="${r.img}"></td>`+
   `<td>${r.session}<br><span style="color:#888;font-size:11px">${r.file}</span></td>`+
   `<td class="num">${r.t.toFixed(3)}</td><td class="num">${r.p.toFixed(3)}</td>`+
   `<td class="num ${eCls}">${r.e>0?'+':''}${r.e.toFixed(3)}</td>`+
   `<td class="bincell">${BINS[r.b]}</td>`+
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
