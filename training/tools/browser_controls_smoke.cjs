// Run the real page in headless Edge against a local simulator, never the car.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'build', 'browser-controls');
  fs.mkdirSync(output, {recursive:true});
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout=10000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) {try {const value=await fn();if(value)return value;}catch{}await pause(100);}
  throw new Error('Browser check timed out');
}
async function main() {
  const settingsFolder=fs.mkdtempSync(path.join(output,'steering-test-'));
  const collector=spawn(path.join(root,'bin','kosmo-collect.exe'),
    ['-backend','sim','-listen','127.0.0.1:18081','-max-throttle','1','-data',path.join(output,'data'),'-steering-config',path.join(settingsFolder,'steering.json'),'-exposure-config',path.join(settingsFolder,'exposure.json')],
    {cwd:root,windowsHide:true,stdio:'ignore'});
  let browser, socket;
  try {
    await until(async()=>{const r=await fetch('http://127.0.0.1:18081/api/status');return r.ok&&(await r.json()).frame_age_ms>=0;});
    browser=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      ['--headless=new','--disable-gpu','--no-first-run','--disable-background-networking','--disable-extensions',
       '--remote-debugging-port=19222','--user-data-dir='+path.join(output,'edge-profile'),'about:blank'],
      {windowsHide:true,stdio:'ignore'});
    const targets=await until(async()=>{const r=await fetch('http://127.0.0.1:19222/json/list');const t=await r.json();return t.some(x=>x.type==='page')&&t;});
    socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
    const pending=new Map();let id=0;
    socket.onmessage=event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const [resolve,reject]=pending.get(data.id);pending.delete(data.id);data.error?reject(data.error):resolve(data.result);}};
    const cdp=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,[resolve,reject]);socket.send(JSON.stringify({id:n,method,params}));});
    const evaluate=async expression=>{const value=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(value.exceptionDetails)throw new Error(JSON.stringify(value.exceptionDetails));return value.result.value;};
    const key=async(name,code,modifiers=0)=>{
      await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:name,windowsVirtualKeyCode:code,modifiers});
      await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:name,windowsVirtualKeyCode:code,modifiers});
    };
    const state=async()=>{const r=await fetch('http://127.0.0.1:18081/api/status');return r.json();};
    await cdp('Page.enable');
    await cdp('Emulation.setDeviceMetricsOverride',{width:1360,height:1120,deviceScaleFactor:1,mobile:false});
    await cdp('Page.navigate',{url:'http://127.0.0.1:18081/'});
    await until(()=>evaluate("document.getElementById('controller')?.textContent.includes('就绪')"));
    assert.equal(await evaluate("document.querySelector('dialog')===null"),true);
    await key('i',73);
    await until(async()=>Math.abs((await state()).frame['user/throttle']-.05)<.001);
    await key('j',74);
    await until(async()=>Math.abs((await state()).frame['user/angle']+.05)<.001);
    await key('l',76,8);
    await until(async()=>Math.abs((await state()).frame['user/angle']+.04)<.001);
    await pause(400);
    assert((await state()).enabled,'keyboard release must retain continuous driving');
    await key(' ',32);
    await until(async()=>{const s=await state();return !s.enabled&&s.frame.flags===0;});
    const box=await evaluate("JSON.stringify(document.getElementById('joystick').getBoundingClientRect().toJSON())");
    const rect=JSON.parse(box),x=rect.x+rect.width/2,y=rect.y+rect.height*.7;
    await cdp('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});
    await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:x+30,y:y-60,button:'left',buttons:1});
    await until(async()=>{const s=await state();return s.frame['user/angle']>.1&&s.frame['user/throttle']>.3;});
    await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',x:x+30,y:y-60,button:'left',clickCount:1});
    await until(async()=>{const s=await state();return !s.enabled&&s.frame.flags===0;});
    await until(()=>evaluate("!document.getElementById('steeringLeft').disabled"));
    await evaluate("document.getElementById('steeringPanel').open=true; document.getElementById('steeringLeft').focus()");
    assert.equal(await evaluate('document.activeElement.id'),'steeringLeft');
    await key('ArrowLeft',37);await pause(100);
    assert.equal((await state()).enabled,false,'settings keyboard input must not drive');
    await evaluate("for(const [id,value] of [['steeringLeft',125],['steeringRight',90]]){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event('input'))} document.getElementById('steeringSave').click()");
    await until(async()=>{const s=await state();return s.steering.left_percent===125&&s.steering.right_percent===90;});
    assert.equal((await state()).enabled,false,'saving steering settings must not drive');
    const persisted=JSON.parse(fs.readFileSync(path.join(settingsFolder,'steering.json'),'utf8'));
    assert.deepEqual(persisted,{left_percent:125,right_percent:90});
    await cdp('Page.reload');
    await until(()=>evaluate("document.getElementById('steeringLeft').value==='125' && document.getElementById('steeringRight').value==='90'"));
    await until(()=>evaluate("!document.getElementById('exposureMode').disabled"));
    await evaluate("document.getElementById('exposurePanel').open=true; const e=document.getElementById('exposureMode');e.value='manual';e.dispatchEvent(new Event('input'));const v=document.getElementById('exposureValue');v.value=600;v.dispatchEvent(new Event('input'));document.getElementById('exposureSave').click()");
    await until(async()=>{const s=await state();return s.exposure.mode==='manual'&&s.exposure.value===600&&!s.exposure.busy;});
    assert.equal((await state()).enabled,false,'saving exposure must not drive');
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(settingsFolder,'exposure.json'),'utf8')),{mode:'manual',value:600});
    await cdp('Page.reload');
    await until(()=>evaluate("document.getElementById('exposureMode').value==='manual' && document.getElementById('exposureValue').value==='600'"));
    await evaluate("document.getElementById('exposurePanel').open=true;document.getElementById('exposureValue').focus()");
    await key('ArrowUp',38);assert.equal((await state()).enabled,false,'exposure slider must not drive');
    const streamBeforeScroll=await evaluate("document.getElementById('video').src");
    await evaluate("window.originalFetch=window.fetch;window.fetch=(...args)=>args[0]==='/api/status'?Promise.reject(new Error('injected status timeout')):window.originalFetch(...args);document.getElementById('exposureValue').dispatchEvent(new Event('input'));document.getElementById('exposureMode').scrollIntoView({block:'center'});document.getElementById('exposureMode').focus()");
    await until(()=>evaluate("document.getElementById('error').textContent.includes('injected status timeout')"));
    await key('ArrowUp',38);await key('ArrowDown',40);
    assert(await evaluate("!document.getElementById('exposureMode').disabled && !document.getElementById('exposureValue').disabled"),'status failure must not lock native exposure controls');
    const slider=await evaluate("document.getElementById('exposureValue').getBoundingClientRect().toJSON()");
    await cdp('Input.dispatchMouseEvent',{type:'mousePressed',x:slider.x+slider.width*.7,y:slider.y+slider.height/2,button:'left',clickCount:1});
    await cdp('Input.dispatchMouseEvent',{type:'mouseMoved',x:slider.x+slider.width*.8,y:slider.y+slider.height/2,button:'left',buttons:1});
    await cdp('Input.dispatchMouseEvent',{type:'mouseReleased',x:slider.x+slider.width*.8,y:slider.y+slider.height/2,button:'left',clickCount:1});
    const draftValue=await evaluate("document.getElementById('exposureValue').value");
    assert.notEqual(draftValue,'600','real pointer must update the slider while offline');
    assert(await evaluate("document.getElementById('exposureSave').disabled"),'offline draft must not be applied');
    assert.equal((await state()).exposure.value,600,'draft interaction must not change the sensor');
    assert.equal((await state()).enabled,false,'offline settings interaction must not drive');
    await cdp('Emulation.setDeviceMetricsOverride',{width:1360,height:600,deviceScaleFactor:1,mobile:false});
    await evaluate("window.scrollTo(0,document.body.scrollHeight)");await pause(150);
    await evaluate("window.fetch=window.originalFetch;window.scrollTo(0,0)");
    await until(()=>evaluate("!document.getElementById('exposureSave').disabled"));
    assert.equal(await evaluate("document.getElementById('exposureValue').value"),draftValue,'connection recovery must preserve native edits');
    await until(async()=>await evaluate("document.getElementById('video').src")!==streamBeforeScroll);
    await cdp('Emulation.setDeviceMetricsOverride',{width:1360,height:1120,deviceScaleFactor:1,mobile:false});
    await evaluate("const e=document.getElementById('exposureMode');e.value='auto';e.dispatchEvent(new Event('input'));document.getElementById('exposureSave').click()");
    await until(async()=>{const s=await state();return s.exposure.mode==='auto'&&!s.exposure.busy;});
    await until(()=>evaluate("document.getElementById('exposureValue').disabled"));
    await evaluate("document.getElementById('video').dispatchEvent(new Event('error'))");
    await until(()=>evaluate("document.getElementById('video').src.includes('reconnect=') && !document.getElementById('angle').disabled && document.getElementById('fresh').textContent.startsWith('帧 ')"));
    assert.equal((await state()).enabled,false,'video recovery must not resume driving');
    await evaluate("document.getElementById('exposurePanel').open=false;window.scrollTo(0,0)");
    for(const [name,width,height,mobile] of [['desktop',1360,1120,false],['mobile',390,844,true]]) {
      await cdp('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile});
      await pause(300);
      assert(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),'horizontal page overflow');
      if(mobile)assert(await evaluate("document.getElementById('stop').getBoundingClientRect().bottom<=window.innerHeight"),'mobile joystick and stop must be visible with the video');
      const shot=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
      fs.writeFileSync(path.join(output,name+'.png'),Buffer.from(shot.data,'base64'));
      await evaluate("document.getElementById('steeringPanel').open=true");
      await evaluate("document.getElementById('exposurePanel').open=true");
      assert(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),'expanded steering settings overflow');
      const settingsShot=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
      fs.writeFileSync(path.join(output,name+'-settings.png'),Buffer.from(settingsShot.data,'base64'));
      await evaluate("document.getElementById('steeringPanel').open=false");
      await evaluate("document.getElementById('exposurePanel').open=false;window.scrollTo(0,0)");
    }
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({simulation_only:true,direct_access:true,
      incremental_keys:true,fine_adjustment:true,latched_keyboard:true,proportional_joystick:true,
      release_stop:true,desktop_and_mobile_layout:true,independent_steering_settings:true,
      settings_persisted:true,settings_reload:true,no_drive_from_settings:true,
      auto_manual_exposure:true,exposure_persisted:true,exposure_reload:true,exposure_slider_no_drive:true,
      live_image_reconnect:true,video_recovery_no_drive:true,native_exposure_edit_during_status_timeout:true,scroll_resume_video:true},null,2)+'\n');
    console.log('Headless Edge control checks passed; screenshots and evidence:',output);
    await cdp('Browser.close');
  } finally {
    if(socket)socket.close();
    if(browser)browser.kill();
    collector.kill();
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
