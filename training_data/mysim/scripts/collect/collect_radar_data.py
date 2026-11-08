#!/usr/bin/env python3
"""通过 WebSocket 控制 donkeycar 自动驾驶 + 记录雷达数据

用法: python collect_radar_data.py [duration_seconds]
默认采集 60 秒
"""
import asyncio
import json
import sys

try:
    import tornado.websocket as ws
except ImportError:
    import websockets as ws
    WS_MODE = 'websockets'
else:
    WS_MODE = 'tornado'

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 60


async def send_control():
    url = "ws://localhost:8887/wsDrive"
    print(f"连接 {url}...")
    print(f"采集时长: {DURATION} 秒")

    if WS_MODE == 'tornado':
        conn = await ws.websocket_connect(url)

        # 发送自动驾驶 + 记录命令 (每 3 秒重发,保持连接)
        drive_msg = json.dumps({
            "drive_mode": "auto",
            "recording": True,
            "throttle": 0.5,
            "angle": 0.0,
        })

        await conn.write_message(drive_msg)
        print(f"已发送: {drive_msg}")

        elapsed = 0
        while elapsed < DURATION:
            await asyncio.sleep(3)
            elapsed += 3
            try:
                await conn.write_message(drive_msg)
                print(f"  [{elapsed}s] 重发驱动命令")
            except Exception as e:
                print(f"  [{elapsed}s] 连接断开: {e}")
                break

        # 停止
        stop_msg = json.dumps({
            "drive_mode": "user",
            "recording": False,
            "throttle": 0.0,
        })
        try:
            await conn.write_message(stop_msg)
            print(f"已发送停止: {stop_msg}")
        except Exception:
            pass
        conn.close()
    else:
        async with ws.connect(url) as conn:
            drive_msg = json.dumps({
                "drive_mode": "auto",
                "recording": True,
                "throttle": 0.5,
                "angle": 0.0,
            })
            await conn.send(drive_msg)
            print(f"已发送: {drive_msg}")

            elapsed = 0
            while elapsed < DURATION:
                await asyncio.sleep(3)
                elapsed += 3
                try:
                    await conn.send(drive_msg)
                    print(f"  [{elapsed}s] 重发驱动命令")
                except Exception as e:
                    print(f"  [{elapsed}s] 连接断开: {e}")
                    break

            stop_msg = json.dumps({
                "drive_mode": "user",
                "recording": False,
                "throttle": 0.0,
            })
            try:
                await conn.send(stop_msg)
                print(f"已发送停止: {stop_msg}")
            except Exception:
                pass

asyncio.run(send_control())
print("完成")
