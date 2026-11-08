"""Verify a saved packet, export PNG, and check OV2640 color-bar channel order.

Uses only the standard library. Real-scene focus, exposure and orientation still
need visual inspection; a varied image alone does not prove correct imaging.
"""
import argparse
import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

from camera_host import decode_packet, rgb565_to_rgb888


def png_bytes(width, height, rgb):
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind + data)))
    rows = b''.join(b'\0' + rgb[y*width*3:(y+1)*width*3] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def colorbar_check(width, height, rgb):
    names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']
    expected = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0),
                (1, 0, 1), (1, 0, 0), (0, 0, 1), (0, 0, 0)]
    bars = []
    for i, (name, levels) in enumerate(zip(names, expected)):
        center = int((i + .5)*width/8)
        positions = [((y*width + x)*3) for y in range(height//10, height-height//10)
                     for x in range(max(0, center-1), min(width, center+2))]
        mean = [sum(rgb[p+c] for p in positions)/len(positions) for c in range(3)]
        passed = all(value >= 160 if high else value <= 80
                     for value, high in zip(mean, levels))
        bars.append(dict(name=name, center_x=center,
                         mean_rgb=[round(x, 2) for x in mean], passed=passed))
    return dict(passed=all(bar['passed'] for bar in bars), bars=bars,
                method='Central three columns per bar, middle 80% rows; high >=160, low <=80')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='Frame folder containing packet.bin and frame.rgb565')
    args = parser.parse_args()
    packet = (args.folder/'packet.bin').read_bytes()
    info, raw = decode_packet(packet)
    if info['kind'] != 2:
        raise ValueError('Packet is not a valid frame')
    if raw != (args.folder/'frame.rgb565').read_bytes():
        raise ValueError('Saved raw frame differs from verified packet')
    rgb = rgb565_to_rgb888(raw)
    width, height = info['width'], info['height']
    png = png_bytes(width, height, rgb)
    (args.folder/'frame.png').write_bytes(png)
    channels = [rgb[c::3] for c in range(3)]
    means = [sum(ch)/len(ch) for ch in channels]
    result = dict(packet_crc_and_dimensions_passed=True, width=width, height=height,
                  raw_sha256=hashlib.sha256(raw).hexdigest(),
                  png_sha256=hashlib.sha256(png).hexdigest(),
                  preview_swap_bytes=False, preview_swap_rb=False,
                  unique_rgb565_values=len(set(zip(raw[::2], raw[1::2]))),
                  mean_rgb=[round(x, 2) for x in means],
                  stddev_rgb=[round(math.sqrt(sum((x-m)**2 for x in ch)/len(ch)), 2)
                              for ch, m in zip(channels, means)])
    if info['flags'] & 128:
        result['colorbar'] = colorbar_check(width, height, rgb)
    else:
        result['scene_content_requires_visual_review'] = True
    (args.folder/'inspection.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result.get('colorbar', {}).get('passed', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
