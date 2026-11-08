// Regression tests for the shipped UI, without external browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const settle = () => new Promise(setImmediate);
async function fixture() {
  const handlers = new Map(), elements = new Map(), intervals = [], requests = [];
  const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]));
  const make = id => ({value: id === 'limit' ? '1' : id === 'step' ? '.05' : '0',
    tagName:'DIV', type:'', textContent:'', style:{}, disabled:false,
    classList:{toggle(){},add(){}}, setPointerCapture(){}, setAttribute(){},
    getBoundingClientRect(){return {left:0,top:0,width:400,height:300};},
    addEventListener(event,fn){handlers.set(id+':'+event,fn);}});
  const get = id => {assert(ids.has(id)||id==='camera','unknown element '+id);if(!elements.has(id))elements.set(id,make(id));return elements.get(id);};
  const data = {backend:'pa-uio-ktr1',frame_age_ms:10,fault:'',enabled:false,max_throttle:1,
    controller:{ready:true,armed:true,active:true,fault:false,shutdown_unconfirmed:false},
    frame:{frame_sequence:1,'user/angle':0,'user/throttle':0,flags:0},saved:0,session:'',record_open:false,
    steering:{left_percent:110,right_percent:110},
    exposure:{mode:'auto',value:300,min:0,max:1200,supported:true,busy:false}};
  let rejectDrive=false, rejectStatus=false, rejectExposure=false;
  const document = {hidden:false,getElementById:get,querySelector:()=>get('camera'),
    addEventListener(event,fn){handlers.set('document:'+event,fn);}};
  const context = vm.createContext({crypto:webcrypto,AbortSignal,
    location:{hash:'',pathname:'/'},history:{replaceState(){}},document,
    window:{addEventListener(event,fn){handlers.set('window:'+event,fn);}},
    setInterval(fn,ms){intervals.push({fn,ms});},
    async fetch(url,opts){
      requests.push({url,body:opts.body?JSON.parse(opts.body):undefined});
      if(url==='/api/status'&&rejectStatus)throw new Error('status timed out');
      if(url==='/api/exposure'&&rejectExposure)throw new Error('exposure request timed out');
      if(url==='/api/drive'&&rejectDrive)return {ok:false,text:async()=>'control request failed'};
      if(url==='/api/record')data.record_open=JSON.parse(opts.body).recording;
      if(url==='/api/steering')data.steering=JSON.parse(opts.body);
      if(url==='/api/exposure')data.exposure={...data.exposure,...JSON.parse(opts.body)};
      return {ok:true,json:async()=>['/api/status','/api/steering','/api/exposure'].includes(url)?data:{accepted:true}};
    }});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8'),context);
  await settle();
  return {get,requests,handlers,document,data,setReject(value){rejectDrive=value;},
    setRejectStatus(value){rejectStatus=value;},setRejectExposure(value){rejectExposure=value;},
    command(){return requests.filter(r=>r.url==='/api/drive').at(-1)?.body;},
    async key(type,key,options={}) {
      handlers.get('document:'+type)({key,target:{tagName:'INPUT',type:'range'},repeat:false,shiftKey:false,preventDefault(){},...options});await settle();
    },
    async pointer(type,x=200,y=200,id=1) {
      handlers.get('joystick:'+type)({clientX:x,clientY:y,pointerId:id,button:0,preventDefault(){}});await settle();
    },
    async tick(ms){await intervals.find(i=>i.ms===ms).fn();await settle();}};
}
(async()=>{
  const p=await fixture();
  assert(!p.requests.some(r=>r.url.includes('login')),'page must open without login');
  await p.tick(50);assert.equal(p.command(),undefined,'idle page must not send controls');
  await p.key('keydown','i');assert.equal(p.command().throttle,.05);
  await p.key('keyup','i');await p.tick(50);
  assert.equal(p.command().enable,true,'keyboard setpoint persists after key release');
  assert.equal(p.command().throttle,.05);
  await p.key('keydown','j');assert.equal(p.command().angle,-.05);
  await p.key('keyup','j');
  await p.key('keydown','l',{shiftKey:true});assert.equal(p.command().angle,-.04);
  await p.key('keyup','l');
  await p.key('keydown','c');assert.equal(p.command().angle,0);assert.equal(p.command().throttle,.05);
  await p.key('keydown',' ');assert.equal(p.command().enable,false);
  const firstGesture=p.command().gesture;
  await p.key('keydown','w');assert.equal(p.command().throttle,.05);assert(p.command().gesture>firstGesture);
  await p.key('keydown','Escape');assert.equal(p.command().enable,false);
  await p.key('keydown','w',{repeat:true});await p.tick(50);
  assert.equal(p.command().enable,false,'key held across stop must not restart');
  await p.key('keyup','w');
  await p.key('keydown','w',{target:{tagName:'INPUT',type:'text'}});
  assert.equal(p.command().enable,false,'text input must not drive');
  await p.pointer('pointerdown');assert.equal(p.command().throttle,0);
  await p.pointer('pointermove',250,160);assert.equal(p.command().angle,.5);assert.equal(p.command().throttle,.4);
  p.get('limit').value='.2';p.get('limit').oninput();await settle();assert.equal(p.command().throttle,.2);
  await p.pointer('pointermove',200,100);assert.equal(p.command().throttle,.2);
  await p.pointer('pointermove',200,230);assert.equal(p.command().throttle,0,'downward drag must not reverse');
  await p.pointer('pointerup');assert.equal(p.command().enable,false);
  await p.pointer('pointerdown');await p.pointer('pointermove',175,150);
  await p.pointer('pointercancel');assert.equal(p.command().enable,false);
  p.get('angle').value='.17';p.get('angle').oninput();await settle();
  assert.equal(p.command().angle,.17);assert.equal(p.command().throttle,0,'steering works while stationary');
  await p.key('keydown','r');assert.equal(p.data.record_open,true);
  p.handlers.get('window:blur')();await settle();assert.equal(p.command().enable,false);
  p.setReject(true);await p.key('keydown','w');await p.tick(250);
  assert.match(p.get('error').textContent,/control request failed/,'status must preserve control errors');
  p.setReject(false);await p.tick(50);assert.equal(p.command().enable,false);
  await p.key('keydown','w',{repeat:true});await p.tick(50);assert.equal(p.command().enable,false);
  await p.key('keyup','w');await p.key('keydown','w');assert.equal(p.command().enable,true);
  p.data.controller.armed=false;await p.tick(250);assert.equal(p.command().enable,false);
  p.data.controller.armed=true;await p.tick(250);await p.tick(50);assert.equal(p.command().enable,false,'ready recovery must not replay input');
  await p.key('keyup','w');await p.key('keydown','ArrowUp');assert.equal(p.command().throttle,.05);
  p.document.hidden=true;p.handlers.get('document:visibilitychange')();await settle();assert.equal(p.command().enable,false);
  const q=await fixture();
  assert.equal(Number(q.get('steeringLeft').value),110);
  q.get('steeringLeft').value='125';q.get('steeringLeft').oninput();
  q.get('steeringRight').value='90';q.get('steeringRight').oninput();
  await q.tick(250);assert.equal(q.get('steeringLeft').value,'125','polling must preserve unsaved draft');
  await q.key('keydown','ArrowLeft',{target:{id:'steeringLeft',tagName:'INPUT',type:'range'}});
  assert.equal(q.command(),undefined,'settings slider arrows must not drive');
  await q.get('steeringSave').onclick();await settle();
  assert.deepEqual(q.data.steering,{left_percent:125,right_percent:90});
  assert.equal(q.command(),undefined,'saving endpoints must not drive');
  assert(q.get('steeringSave').disabled);
  q.data.record_open=true;await q.tick(250);assert(q.get('steeringLeft').disabled);
  q.data.record_open=false;q.data.enabled=true;await q.tick(250);assert(q.get('steeringLeft').disabled);
  q.data.enabled=false;await q.tick(250);q.get('steeringOriginal').onclick();
  assert.equal(q.get('steeringLeft').value,100);assert.equal(q.get('steeringRight').value,100);
  assert.equal(q.data.steering.left_percent,125,'restore button must leave settings as a draft until save');
  const e=await fixture();
  assert.equal(e.get('exposureMode').value,'auto');
  assert(e.get('exposureValue').disabled,'auto mode disables manual value');
  e.get('exposureMode').value='manual';e.get('exposureMode').oninput();
  assert(!e.get('exposureValue').disabled);
  e.get('exposureValue').value='600';e.get('exposureValue').oninput();
  await e.tick(250);assert.equal(e.get('exposureValue').value,'600','polling preserves draft exposure');
  await e.key('keydown','ArrowUp',{target:{id:'exposureValue',tagName:'INPUT',type:'range'}});
  assert.equal(e.command(),undefined,'exposure slider keys must not drive');
  await e.get('exposureSave').onclick();await settle();
  assert.equal(e.data.exposure.mode,'manual');assert.equal(e.data.exposure.value,600);
  assert.match(e.get('video').src,/reconnect=/,'confirmed exposure must refresh the video stream');
  assert.equal(e.command(),undefined,'exposure save must not drive');
  assert(e.get('exposureSave').disabled);
  e.data.exposure.busy=true;await e.tick(250);
  assert(e.get('exposureMode').disabled);assert(e.get('record').disabled);
  await e.key('keydown','w');assert.equal(e.command(),undefined,'pending exposure blocks driving');
  e.data.exposure.busy=false;e.data.record_open=true;await e.tick(250);assert(e.get('exposureMode').disabled);
  e.data.record_open=false;e.data.enabled=true;await e.tick(250);assert(e.get('exposureMode').disabled);
  e.data.enabled=false;await e.tick(250);
  e.get('exposureMode').value='auto';e.get('exposureMode').oninput();
  await e.get('exposureSave').onclick();await settle();assert(e.get('exposureValue').disabled);
  const slow=await fixture();
  slow.data.record_open=true;slow.data.record_closing=true;
  slow.data.recording_io={queued:32,dropped:7,write_age_ms:2600};
  await slow.tick(250);
  assert(slow.get('record').disabled,'flush must not allow a second recording operation');
  assert.match(slow.get('recordHealth').textContent,/7/,'recording drops must be visible');
  assert(!slow.get('recordHealth').hidden);
  await slow.key('keydown','w');assert.equal(slow.command().enable,true,'storage backlog must not disable healthy live controls');
  await slow.key('keydown','Escape');
  slow.data.recording_error='disk full';await slow.tick(250);
  assert.match(slow.get('recordHealth').textContent,/disk full/);
  slow.data.exposure.supported=false;await slow.tick(250);assert(slow.get('exposureMode').disabled);
  const stream=await fixture();
  await stream.key('keydown','i');assert.equal(stream.command().enable,true);
  stream.handlers.get('video:error')();await settle();assert.equal(stream.command().enable,false,'video loss must stop driving');
  await stream.tick(250);const reconnect=stream.get('video').src;
  assert.match(reconnect,/reconnect=/,'a healthy board must reconnect a failed video stream');
  await stream.tick(250);assert.equal(stream.get('video').src,reconnect,'retry must be rate limited');
  await stream.key('keydown','w');assert.equal(stream.command().enable,false,'failed video must block new driving input');
  stream.handlers.get('video:load')();await stream.tick(250);await stream.tick(50);
  assert.equal(stream.command().enable,false,'video recovery must not resume old driving');
  const draft=await fixture();
  draft.get('exposureMode').value='manual';draft.get('exposureMode').oninput();
  draft.get('exposureValue').value='477';draft.get('exposureValue').oninput();
  draft.setRejectStatus(true);await draft.tick(250);
  assert(!draft.get('exposureMode').disabled && !draft.get('exposureValue').disabled,'status timeout must not freeze local exposure editing');
  assert(draft.get('exposureSave').disabled,'offline draft must not be applied');
  assert(draft.get('angle').disabled || draft.command()===undefined,'offline editing must not drive');
  draft.get('exposureValue').value='600';draft.get('exposureValue').oninput();
  draft.setRejectStatus(false);await draft.tick(250);
  assert.equal(draft.get('exposureValue').value,'600','recovery must retain edited draft');
  assert(!draft.get('exposureSave').disabled,'healthy connection must allow explicit save again');
  assert.equal(draft.command(),undefined,'draft edit and recovery must not send driving commands');
  const failedExposure=await fixture();
  failedExposure.get('exposureMode').value='manual';failedExposure.get('exposureMode').oninput();
  failedExposure.setRejectExposure(true);await failedExposure.get('exposureSave').onclick();
  assert(!failedExposure.get('exposureMode').disabled,'failed exposure request must release UI busy state');
  assert(!failedExposure.get('angle').disabled,'healthy controls must recover after a failed exposure request');
  assert.equal(failedExposure.command(),undefined,'exposure recovery must not drive');
  console.log('UI regressions passed: driving, recovery, steering, auto/manual exposure, drafts, idle-only save, no motion on edit/save');
})().catch(error=>{console.error(error);process.exitCode=1;});
