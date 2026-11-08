"""Review saved acceptance evidence and produce an offline image gallery/report."""
import argparse
import datetime as dt
import hashlib
import html
import json
import re
from pathlib import Path

from camera_host import decode_packet, rgb565_to_rgb888
from inspect_frame import colorbar_check
from jtag_test import monitor_delta


def review(folder, visual_note):
    run = json.loads((folder/'acceptance.json').read_text(encoding='utf-8'))
    if not run['passed']:
        raise ValueError('Acceptance run did not finish successfully')
    for event in run['events']:
        info, _ = decode_packet((folder/event['packet']).read_bytes())
        if info != event['info']:
            raise ValueError(f'Packet metadata mismatch: {event["packet"]}')
    if len(run['frames']) != run['settings']['normal_count'] + 5:
        raise ValueError('Incomplete startup/mode/reset capture set')
    frames, series = [], []
    previous_sequence = None
    for frame in run['frames']:
        path = folder/frame['folder']
        info, raw = decode_packet((path/'packet.bin').read_bytes())
        if raw != (path/'frame.rgb565').read_bytes() or hashlib.sha256(raw).hexdigest() != frame['raw_sha256']:
            raise ValueError(f'Raw frame mismatch: {path}')
        if (info['bad_count'] or info['kind'] != 2 or
                (info['width'], info['height'], len(raw)) != (160, 120, 38400)):
            raise ValueError(f'Invalid frame: {path}')
        if previous_sequence is not None and info['sequence'] != (previous_sequence+1)&65535:
            raise ValueError('Capture sequence is not consecutive')
        previous_sequence = info['sequence']
        rgb = rgb565_to_rgb888(raw)
        entry = dict(folder=frame['folder'], sequence=info['sequence'],
                     crc32_verified=True, bytes=len(raw), lines=info['lines'],
                     last_line_bytes=info['last_line_bytes'], raw_sha256=frame['raw_sha256'],
                     transfer_seconds=frame['seconds'])
        if info['flags'] & 128:
            entry['colorbar'] = colorbar_check(info['width'], info['height'], rgb)
            if not entry['colorbar']['passed']:
                raise ValueError(f'Color-bar channel order failed: {path}')
        frames.append(entry)
        if re.fullmatch(r'normal_\d{3}', frame['folder']):
            series.append((frame['folder'], rgb, frame['raw_sha256']))
    if len(series) != run['settings']['normal_count'] or len({x[2] for x in series}) < 2:
        raise ValueError('Normal series count/freshness check failed')
    differences = []
    for before, after in zip(series, series[1:]):
        delta = [abs(a-b) for a, b in zip(before[1], after[1])]
        differences.append(dict(before=before[0], after=after[0],
            mean_absolute_rgb_difference=sum(delta)/len(delta),
            fraction_pixels_with_channel_change_ge_32=sum(max(delta[i:i+3]) >= 32 for i in range(0, len(delta), 3))/(len(delta)//3)))

    rows = [json.loads(line) for line in (folder/'monitor.jsonl').read_text(encoding='utf-8').splitlines()]
    first_capture = next(e for e in run['events'] if e['command'] == 'F' and e['phase'] == 'normal_series')
    first_time = dt.datetime.fromisoformat(first_capture['command_issued_at'])
    intervals = []
    epochs = set()
    for previous, current in zip(rows, rows[1:]):
        if current['phase'] != 'normal_series' or dt.datetime.fromisoformat(current['time']) < first_time:
            continue
        if previous['epoch'] != current['epoch']:
            raise ValueError('Counter epoch changed in steady normal series')
        epochs.add(current['epoch'])
        gap = (dt.datetime.fromisoformat(current['time'])-dt.datetime.fromisoformat(previous['time'])).total_seconds()
        if not 0 < gap < 60:
            raise ValueError('Monitoring gap too large for an unambiguous tick difference')
        delta = monitor_delta(previous['monitor'], current['monitor'])
        mon = current['monitor']
        if (delta['bad_frames'] or delta['frames'] == 0 or mon['bad_frames'] or
                mon['last_bytes'] != 38400 or mon['last_lines'] != 120 or mon['last_line_bytes'] != 320):
            raise ValueError(f'Stalled/malformed DVP stream: {current}')
        intervals.append(delta)
    if len(epochs) != 1 or not intervals:
        raise ValueError('Missing a continuous normal-mode monitor epoch')
    seconds = sum(x['seconds'] for x in intervals)
    counted = sum(x['frames'] for x in intervals)
    pclk_edges = sum(x['seconds']*x['pclk_edges_per_second'] for x in intervals)
    if seconds < run['settings']['soak_seconds'] or abs(seconds-run['steady_monitor']['seconds']) > .001:
        raise ValueError('Monitored duration does not match the acceptance window')
    result = dict(reviewed_at=dt.datetime.now().astimezone().isoformat(),
                  automated_checks_passed=True, visual_note=visual_note,
                  bitstream_sha256=run['local_bitstream_sha256'],
                  settings=run['settings'], exported_frames=len(frames), frames=frames,
                  protocol_packets_verified=len(run['events']),
                  normal_series_distinct_hashes=len({x[2] for x in series}),
                  normal_frame_differences=differences,
                  host_sources_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted((folder/'host_source').glob('*.py'))},
                  steady=dict(seconds=seconds, frames=counted, bad_frames=0, fps=counted/seconds,
                              pclk_edges_per_second=pclk_edges/seconds,
                              interval_fps_min=min(x['fps'] for x in intervals),
                              interval_fps_max=max(x['fps'] for x in intervals)),
                  limitations=['Frame hashes can change because of sensor noise; use gallery to assess scene changes',
                               'PCLK edge rate and FPS use the nominal 50 MHz board clock',
                               'JTAG request/response capture is not a PU/Linux video interface',
                               'Reset command toggles camera RST; this run does not switch physical board power'])
    scene = folder/'scene_response.json'
    if scene.exists():
        result['scene_response'] = json.loads(scene.read_text(encoding='utf-8'))
    (folder/'review.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return result


def write_gallery(folder, report):
    cards = []
    for frame in report['frames']:
        name = html.escape(frame['folder'])
        cards.append(f'<figure><a href="{name}/frame.png"><img src="{name}/frame.png" alt="{name}"></a>'
                     f'<figcaption>{name} · 帧 {frame["sequence"]}<br>CRC 正确 · 160 × 120</figcaption></figure>')
    steady = report['steady']
    scene_html = ''
    if report.get('scene_response', {}).get('passed') and (folder/'scene_comparison.png').exists():
        scene_html = ('<h2>场景响应对照</h2><p>从左至右：遮挡前、遮挡中、移开后。'
                      '<a href="scene_response.json">操作时间与目视核验记录</a></p>'
                      '<p><img style="max-width:960px" src="scene_comparison.png" '
                      'alt="遮挡前、遮挡中、移开后的三张原始图像"></p>')
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Camera 验收图像</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;margin:32px auto;padding:0 24px;max-width:1450px;color:#17212b;background:#f3f5f7}}
h1{{font-size:28px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}}
figure{{margin:0;background:white;padding:12px;border-radius:8px}}img{{width:100%;image-rendering:pixelated}}
figcaption{{font-size:14px;padding-top:8px}}a{{color:#145e99}}</style>
<h1>独立 Camera 工程验收</h1><p>导出 {report['exported_frames']} 张图像；逐帧监测 {steady['seconds']:.1f} 秒，
{steady['frames']:,} 帧，结构错误 {steady['bad_frames']}，平均 {steady['fps']:.4f} 帧/秒。</p>
<p>{html.escape(report['visual_note'] or '图像内容待目视检查。')}</p>
<p><a href="acceptance.json">原始验收记录</a> · <a href="review.json">离线核验与帧差</a> ·
<a href="monitor.jsonl">逐帧统计快照</a></p>{scene_html}<div class="grid">{''.join(cards)}</div>
<p>图像保持相机原始方向和色序。PNG 由 RGB565 转换，不交换字节或红蓝通道；点击图像可查看原尺寸。</p></html>'''
    (folder/'gallery.html').write_text(body, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--visual-note', default='')
    args = parser.parse_args()
    result = review(args.folder, args.visual_note)
    write_gallery(args.folder, result)
    print(json.dumps({k: result[k] for k in ['automated_checks_passed', 'exported_frames', 'steady']}, indent=2))
    print(f'Gallery: {args.folder / "gallery.html"}')


if __name__ == '__main__':
    main()
