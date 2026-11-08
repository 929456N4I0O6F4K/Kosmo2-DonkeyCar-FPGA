'use strict';
const $ = id => document.getElementById(id);
const client = Array.from(crypto.getRandomValues(new Uint8Array(16)), x => x.toString(16).padStart(2, '0')).join('');
let sequence = 0, gesture = 0, active = false, sending = false, polling = false, ready = false, recording = false;
let needsStop = false, inputError = '', statusError = '', angle = 0, throttle = 0, maxThrottle = 1;
let pointer = null, source = '待机';
const heldKeys = new Set(), blockedKeys = new Set();
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const rounded = value => Math.round(value * 1000) / 1000;
let steeringDirty = false, steeringBusy = false, steeringCanSave = false;
let exposureDirty = false, exposureBusy = false, exposureCanSave = false;
let exposureSupported = false, exposureLocked = true;
let recordBusy = false;
let videoFailed = false, videoRetryAt = 0;
let appliedExposure = null;
function reconnectVideo() {
  $('video').src = '/video.mjpg?reconnect='+Date.now();
  videoRetryAt = Date.now()+1000;
}
function renderExposure() {
  $('exposureValueLabel').value = $('exposureValue').value;
  $('exposureMode').disabled = !exposureSupported || exposureLocked || active || exposureBusy;
  $('exposureValue').disabled = !exposureSupported || exposureLocked || active || exposureBusy || $('exposureMode').value !== 'manual';
  $('exposureSave').disabled = !exposureCanSave || active || exposureBusy || !exposureDirty;
}
function readExposure(state) {
  const e = state.exposure;
  exposureSupported = !!e?.supported;
  exposureLocked = !!e?.busy || state.enabled || recording || state.frame.flags !== 0;
  if (e && !e.busy) {
    const key = e.mode+':'+e.value;
    if (appliedExposure !== null && appliedExposure !== key) reconnectVideo();
    appliedExposure = key;
  }
  exposureCanSave = !!e && e.supported && !e.busy && ready && !state.enabled && !recording && state.frame.flags === 0;
  if (e) {
    $('exposureSaved').textContent = '当前设置：'+(e.mode === 'auto' ? '自动曝光' : '手动曝光 · '+e.value);
    if (!exposureDirty && !exposureBusy) {
      $('exposureMode').value = e.mode;
      $('exposureValue').value = e.value;
      $('exposureMessage').textContent = !e.supported ? '曝光调节需要完整更新 FPGA 固件；视频与录制可正常使用' : e.busy ? '正在应用，等待新画面' : exposureCanSave ? '调整后点击应用并保存' : '停车并结束录制后可调整';
    }
  } else $('exposureMessage').textContent = '请更新小车系统以启用曝光设置';
  renderExposure();
}
for (const id of ['exposureMode','exposureValue']) {
  $(id).oninput = () => {exposureDirty = true; $('exposureMessage').textContent = exposureCanSave ? '尚未应用' : '草稿未应用，连接恢复后可保存'; renderExposure();};
}
$('exposureSave').onclick = async () => {
  if (!exposureCanSave || active || exposureBusy || !exposureDirty) return;
  exposureBusy = true; renderExposure();
  $('exposureMessage').textContent = '正在应用，等待新画面';
  try {
    const state = await api('/api/exposure', {mode:$('exposureMode').value, value:Number($('exposureValue').value)}, 4000);
    const previousExposure = appliedExposure;
    exposureDirty = false; exposureBusy = false; readExposure(state);
    if (appliedExposure === previousExposure) reconnectVideo();
    $('exposureMessage').textContent = '已应用并保存，下次启动自动恢复';
  } catch (error) {$('exposureMessage').textContent = error.message;}
  finally {exposureBusy = false; renderExposure(); await status();}
};
function renderSteering() {
  for (const side of ['Left','Right']) {
    $('steering'+side+'Value').value = $('steering'+side).value+'%';
    $('steering'+side).disabled = !steeringCanSave || active || steeringBusy;
  }
  $('steeringOriginal').disabled = !steeringCanSave || active || steeringBusy;
  $('steeringSave').disabled = !steeringCanSave || active || steeringBusy || !steeringDirty;
}
function readSteering(state) {
  steeringCanSave = !!state.steering && ready && !state.enabled && !recording && state.frame.flags === 0;
  if (state.steering) {
    $('steeringSaved').textContent = '当前设置：左 '+state.steering.left_percent+'% · 右 '+state.steering.right_percent+'%';
    if (!steeringDirty && !steeringBusy) {
      $('steeringLeft').value = state.steering.left_percent;
      $('steeringRight').value = state.steering.right_percent;
      $('steeringMessage').textContent = steeringCanSave ? '调整后点击保存' : '停车并结束录制后可调整';
    }
  }
  renderSteering();
}
for (const side of ['Left','Right']) {
  $('steering'+side).oninput = () => { steeringDirty = true; $('steeringMessage').textContent = '尚未保存'; renderSteering(); };
}
$('steeringOriginal').onclick = () => {
  if (!steeringCanSave || active || steeringBusy) return;
  $('steeringLeft').value = 100; $('steeringRight').value = 100;
  steeringDirty = true; $('steeringMessage').textContent = '原行程已填入，点击保存后生效'; renderSteering();
};
$('steeringSave').onclick = async () => {
  if (!steeringCanSave || active || steeringBusy || !steeringDirty) return;
  steeringBusy = true; renderSteering();
  try {
    const state = await api('/api/steering', {left_percent:Number($('steeringLeft').value), right_percent:Number($('steeringRight').value)});
    steeringDirty = false; steeringBusy = false; readSteering(state);
    $('steeringMessage').textContent = '已保存，下次启动自动恢复';
  } catch (error) { $('steeringMessage').textContent = error.message; }
  finally { steeringBusy = false; renderSteering(); }
};
function showError() { $('error').textContent = inputError || statusError; }
async function api(path, body, timeout = 800) {
  const opts = {signal: AbortSignal.timeout(timeout)};
  if (body !== undefined) Object.assign(opts, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const response = await fetch(path, opts);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
function limit() { return Math.min(maxThrottle, Number($('limit').value)); }
function render() {
  renderSteering();
  renderExposure();
  $('angle').value = angle;
  $('throttle').value = throttle;
  $('angleValue').value = angle.toFixed(2);
  $('throttleValue').value = throttle.toFixed(2);
  $('limitValue').value = limit().toFixed(2);
  $('inputMode').textContent = active ? source : '已停止';
  $('joystick').classList.toggle('engaged', pointer !== null);
  if (pointer === null) {
    $('stick').style.left = '50%';
    $('stick').style.top = '65%';
  }
}
function clearInput() {
  for (const key of heldKeys) blockedKeys.add(key);
  active = false; angle = 0; throttle = 0; pointer = null;
  render();
}
async function send() {
  if (sending || (!active && !needsStop)) return;
  const enable = active && ready && !document.hidden;
  sending = true;
  try {
    await api('/api/drive', {client, sequence:++sequence, gesture, enable, angle:enable ? angle : 0, throttle:enable ? throttle : 0});
    if (!enable) needsStop = false;
    if (enable) inputError = '';
  } catch (error) {
    clearInput(); needsStop = true; inputError = error.message;
  } finally { sending = false; showError(); }
}
function stop() {
  needsStop = true; clearInput(); send();
}
function setInput(nextAngle, nextThrottle, inputSource) {
  if (!ready || document.hidden || exposureBusy) return;
  if (!active) gesture++;
  active = true; needsStop = true; inputError = ''; source = inputSource;
  angle = rounded(clamp(nextAngle, -1, 1));
  throttle = rounded(clamp(nextThrottle, 0, limit()));
  render(); send();
}
function adjust(axis, direction, fine = false) {
  // DonkeyCar's incremental keyboard controls, with a smaller steering step.
  const step = fine ? .01 : Number($('step').value);
  pointer = null;
  setInput(angle + (axis === 'angle' ? direction * step : 0),
    throttle + (axis === 'throttle' ? direction * step : 0), '键盘 / 滑杆');
}
const keyActions = {
  i:['throttle',1], w:['throttle',1], arrowup:['throttle',1],
  k:['throttle',-1], s:['throttle',-1], arrowdown:['throttle',-1],
  j:['angle',-1], a:['angle',-1], arrowleft:['angle',-1],
  l:['angle',1], d:['angle',1], arrowright:['angle',1]
};
document.addEventListener('keydown', event => {
  const key = event.key.toLowerCase();
  if (key === 'escape' || key === ' ') { event.preventDefault(); stop(); return; }
  if (event.ctrlKey || event.altKey || event.metaKey) return;
  const target = event.target;
  if (['steeringLeft','steeringRight','exposureValue'].includes(target.id)) return;
  if (target.isContentEditable || ['TEXTAREA','SELECT'].includes(target.tagName) ||
      (target.tagName === 'INPUT' && target.type !== 'range')) return;
  if (keyActions[key]) {
    event.preventDefault();
    if (blockedKeys.has(key) || (event.repeat && !heldKeys.has(key))) return;
    heldKeys.add(key);
    if (!ready) { blockedKeys.add(key); return; }
    adjust(...keyActions[key], event.shiftKey);
  } else if (key === 'c' && !event.repeat) {
    event.preventDefault(); pointer = null; setInput(0, throttle, '键盘 / 滑杆');
  } else if (key === 'r' && !event.repeat) {
    event.preventDefault(); toggleRecording();
  }
});
document.addEventListener('keyup', event => {
  const key = event.key.toLowerCase(); heldKeys.delete(key); blockedKeys.delete(key);
});
$('stop').onclick = stop;
$('center').onclick = () => { pointer = null; setInput(0, throttle, '键盘 / 滑杆'); };
for (const axis of ['angle','throttle']) {
  $(axis).oninput = () => {
    pointer = null;
    setInput(axis === 'angle' ? Number($(axis).value) : angle,
      axis === 'throttle' ? Number($(axis).value) : throttle, '键盘 / 滑杆');
  };
  $(axis+'Minus').onclick = () => adjust(axis, -1);
  $(axis+'Plus').onclick = () => adjust(axis, 1);
}
$('limit').oninput = () => {
  const bounded = Math.min(throttle, limit());
  if (active) setInput(angle, bounded, source);
  else render();
};
function moveStick(event) {
  if (pointer === null || event.pointerId !== pointer.id) return;
  const dx = clamp((event.clientX-pointer.x)/pointer.radius, -1, 1);
  const dy = clamp((pointer.y-event.clientY)/pointer.radius, 0, 1);
  setInput(dx, dy * limit(), '比例摇杆');
  $('stick').style.left = (pointer.x-pointer.left+dx*pointer.radius)+'px';
  $('stick').style.top = (pointer.y-pointer.top-dy*pointer.radius)+'px';
}
$('joystick').addEventListener('pointerdown', event => {
  event.preventDefault();
  if (!ready || pointer !== null || (event.button !== undefined && event.button !== 0)) return;
  const rect = $('joystick').getBoundingClientRect();
  pointer = {id:event.pointerId, x:event.clientX, y:event.clientY, left:rect.left, top:rect.top,
    radius:Math.min(100, rect.width*.35, rect.height*.35)};
  $('joystick').setPointerCapture(event.pointerId);
  setInput(0, 0, '比例摇杆'); moveStick(event);
});
$('joystick').addEventListener('pointermove', moveStick);
for (const name of ['pointerup','pointercancel','lostpointercapture']) {
  $('joystick').addEventListener(name, event => { if (pointer !== null && event.pointerId === pointer.id) stop(); });
}
window.addEventListener('blur', stop);
window.addEventListener('pagehide', stop);
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else reconnectVideo(); });
async function toggleRecording() {
  if ($('record').disabled || exposureBusy || recordBusy) return;
  recordBusy = true;
  $('record').disabled = true;
  try { await api('/api/record', {recording:!recording}, 15000); inputError = ''; await status(); }
  catch (error) { inputError = error.message; showError(); }
  finally { recordBusy = false; await status(); }
}
$('record').onclick = toggleRecording;
async function status() {
  if (polling) return;
  polling = true;
  try {
    const state = await api('/api/status', undefined, 2000);
    const fresh = state.frame_age_ms >= 0 && state.frame_age_ms < 500;
    if (fresh && !state.fault && videoFailed && Date.now() >= videoRetryAt) reconnectVideo();
    const controller = state.controller;
    ready = fresh && !videoFailed && !state.fault && !state.exposure?.busy && !exposureBusy && (!controller ||
      (controller.ready && controller.armed && !controller.fault && !controller.shutdown_unconfirmed));
    if (!ready && active) stop();
    recording = state.record_open;
    readSteering(state);
    readExposure(state);
    maxThrottle = state.max_throttle;
    $('limit').max = maxThrottle; $('throttle').max = maxThrottle;
    if (Number($('limit').value) > maxThrottle) $('limit').value = maxThrottle;
    if (throttle > limit()) setInput(angle, limit(), source);
    $('mode').textContent = state.backend === 'simulation' ? '模拟模式' : 'KOSMO 实机';
    $('fresh').textContent = videoFailed ? '视频重连中 · 控制已停止' : fresh ? '帧 '+state.frame.frame_sequence+' · '+state.frame_age_ms+' ms' : '视频中断 · 控制已停止';
    document.querySelector('.camera').classList.toggle('stale', !fresh || videoFailed);
    $('controller').textContent = state.fault || (controller && controller.fault ? '执行器故障' :
      controller && controller.shutdown_unconfirmed ? '正在关闭输出' :
      controller && !controller.armed ? '设备正在完成一次中位初始化，完成后即可连续操控' :
      exposureBusy || state.exposure?.busy ? '正在调整曝光，等待新画面后恢复操控' :
      ready ? '就绪 · 停车后可直接再次操控' : '等待视频与控制连接');
    $('setpoints').textContent = '板端反馈：转向 '+state.frame['user/angle'].toFixed(2)+' · 油门 '+state.frame['user/throttle'].toFixed(2);
    for (const id of ['angle','throttle','angleMinus','anglePlus','throttleMinus','throttlePlus','center']) $(id).disabled = !ready;
    $('joystick').setAttribute('aria-disabled', String(!ready));
    $('record').textContent = state.record_closing ? '正在保存录制…' : state.record_opening ? '正在准备录制…' : recording ? '结束录制 · R' : '开始录制 · R';
    $('record').disabled = recordBusy || !!state.record_closing || !!state.record_opening || exposureBusy || !!state.exposure?.busy;
    const io = state.recording_io;
    const storageError = state.recording_error || io?.error;
    $('recordHealth').textContent = storageError ? '录制存储错误：'+storageError+'；请结束录制，视频与控制继续运行' :
      io?.dropped > 0 ? '存储写入偏慢，已跳过 '+io.dropped+' 帧；待保存 '+io.queued+' 帧，视频与控制优先' :
      io?.queued > 0 || io?.write_age_ms > 200 ? '录制正在写入存储，待保存 '+io.queued+' 帧' : '';
    $('recordHealth').hidden = !$('recordHealth').textContent;
    $('count').textContent = state.saved+' 帧';
    $('session').textContent = state.session;
    $('download').hidden = recording || !state.session;
    statusError = state.fault || ''; showError(); render();
  } catch (error) {
    ready = false;
    steeringCanSave = false; renderSteering();
    exposureCanSave = false; renderExposure();
    if (exposureDirty && !exposureBusy) $('exposureMessage').textContent = '连接读取超时，草稿已保留，恢复后可保存';
    if (active) stop();
    $('fresh').textContent = '连接中断 · 控制已停止';
    statusError = error.message; showError();
    document.querySelector('.camera').classList.add('stale');
  } finally { polling = false; }
}
// Direct LAN access, no login dialog or token. Old bookmarked fragments can go.
if (location.hash) history.replaceState(null, '', location.pathname);
$('video').src = '/video.mjpg';
$('video').addEventListener('load', () => {videoFailed = false;});
$('video').addEventListener('error', () => {
  videoFailed = true; ready = false;
  if (active) stop();
  $('fresh').textContent = '视频重连中 · 控制已停止';
  document.querySelector('.camera').classList.add('stale');
});
// Browsers can suspend an off-screen MJPEG image without firing an error.
// Reopen it when scrolling back from settings or returning from the background.
if (typeof IntersectionObserver !== 'undefined') {
  let wasVisible = null;
  new IntersectionObserver(entries => {
    const visible = entries[0].isIntersecting;
    if (visible && wasVisible === false) reconnectVideo();
    wasVisible = visible;
  }).observe($('video'));
}
render(); status();
setInterval(status, 250);
setInterval(send, 50);
