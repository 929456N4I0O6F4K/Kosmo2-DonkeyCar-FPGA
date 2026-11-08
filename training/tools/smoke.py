"""Test the built executable over TCP and retain two synthetic sessions for training smoke tests."""
import argparse
import datetime
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
import io
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    p.add_argument("--binary", type=Path, default=root / "bin/kosmo-collect.exe")
    args = p.parse_args()
    out = root / "build" / ("smoke_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    out.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    def api(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)
    with (out / "collector.log").open("w") as log:
        proc = subprocess.Popen([str(args.binary), "-backend", "sim", "-listen", f"127.0.0.1:{port}",
                                 "-data", str(out / "data")], stdout=log, stderr=log,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for _ in range(60):
                if proc.poll() is not None:
                    raise RuntimeError("collector exited; see collector.log")
                try:
                    if api("/api/status")["frame_age_ms"] >= 0:
                        break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(.05)
            else:
                raise TimeoutError("collector did not start")
            video = urllib.request.Request(base + "/video.mjpg")
            with urllib.request.urlopen(video, timeout=2) as response:
                header = response.readline()
                assert header == b"--frame\r\n"
                length = None
                while (line := response.readline()) != b"\r\n":
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":")[1])
                from PIL import Image
                with Image.open(io.BytesIO(response.read(length))) as image:
                    assert image.size == (160, 120)
            sessions = []
            sequence = 0
            for session in range(2):
                api("/api/record", {"recording": True})
                start = time.monotonic()
                while time.monotonic() - start < 2.4:
                    sequence += 1
                    api("/api/drive", {"client": "smoke-driver", "sequence": sequence, "gesture": session+1, "enable": True,
                                      "angle": (-.3, 0, .3)[(sequence // 8) % 3], "throttle": .12})
                    time.sleep(.05)
                result = api("/api/record", {"recording": False})
                assert result["saved"] >= 20, result
                sessions.append(str(out / "data" / result["session"]))
            time.sleep(.45)
            state = api("/api/status")
            assert state["frame"]["flags"] == 0 and state["frame"]["user/throttle"] == 0, state
            req = urllib.request.Request(base + "/api/download")
            with urllib.request.urlopen(req, timeout=3) as response:
                data = response.read()
            (out / "download.zip").write_bytes(data)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
            report = {"synthetic_only": True, "mjpeg_decoded": True, "network_controls": True,
                      "lease_loss_stopped": True, "zip_validated": True, "sessions": sessions}
            (out / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            print("Report:", out)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
