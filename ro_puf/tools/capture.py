"""Capture RO PUF bytes and all underlying divided-frequency counts over JTAG."""
import argparse
import csv
import hashlib
import json
import random
import re
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "camera/tools"))
from jtag_shell import Debugger
from jtag_test import dvio_json, port_value

BITSTREAM = ROOT / "build/pds/prj_tasks/pnr_1/generate_bitstream/ro_puf_top.sbit"
WINDOW_CLOCKS = 50000
DIVIDER = 16
COUNTER_INPUT_LIMIT_HZ = 600_000_000
MAX_COUNT = 37502  # 600 MHz timing bound plus two ticks for start/stop phase.
MAPPING = "a=(index[4:0]+3*lane)%32; b=32+(index[9:5]+7*lane)%32"
FIELDS = ["challenge_index", "repeat", "response_hex", "arrived_hex", "status_hex",
          "batch_crc32", "clock_ticks", "utc", "tie_mask_hex", "counts_crc32"]
COUNT_FIELDS = ["challenge_index", "repeat", "lane", "ro_a", "ro_b", "count_a", "count_b",
                "delta", "window_clocks", "divider", "utc"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def pair_indices(index, lane):
    if not 0 <= index < 1024 or not 0 <= lane < 8:
        raise ValueError("RO challenge index must be 0..1023; lane 0..7")
    return ((index & 31) + 3 * lane) & 31, 32 + (((index >> 5) + 7 * lane) & 31)


def decode_batch(status, responses, batch_info, counts, counts_crc, ties):
    if (status >> 48 != 0x5258 or not status & (1 << 23) or status & (1 << 22)
            or (status >> 14) & 255 != 255 or status & 0x30):
        raise ValueError("RO batch is incomplete, stopped or overflowed")
    if batch_info >> 48 != 0x5231 or (batch_info >> 40) & 255 != 32 or (batch_info >> 32) & 255 != (status >> 24) & 255:
        raise ValueError("RO batch metadata/token mismatch")
    if len(responses) != 32 or zlib.crc32(responses) != batch_info & 0xffffffff:
        raise ValueError("Response CRC32 mismatch")
    if len(counts) != 1536 or zlib.crc32(counts) != counts_crc or len(ties) != 32:
        raise ValueError("Count CRC32 or length mismatch")
    if responses[-1] != (status >> 6) & 255:
        raise ValueError("Last response mismatch")
    pairs = []
    for repeat in range(32):
        byte = tie = 0
        for lane in range(8):
            offset = (repeat * 8 + lane) * 6
            a = int.from_bytes(counts[offset:offset+3], "little")
            b = int.from_bytes(counts[offset+3:offset+6], "little")
            if not 0 < a <= MAX_COUNT or not 0 < b <= MAX_COUNT:
                raise ValueError(f"RO count outside 600 MHz validated range: {a}, {b}")
            byte |= (a > b) << lane
            tie |= (a == b) << lane
            pairs.append((a, b))
        if responses[repeat] != byte or ties[repeat] != tie:
            raise ValueError("Raw counts, response or tie mask disagree")
    return pairs


class RoDvio:
    def __init__(self, shell):
        self.shell = shell
        shell.command("dbg_connect -ip 127.0.0.1 -port 65420", timeout=100)
        shell.command("dbg_scan_chain", timeout=40)
        obj = dvio_json(shell.command("dbg_dvio_refresh -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0"))
        if len(obj["probe_ins"]) != 12:
            raise RuntimeError("Expected twelve RO PUF probes")
        self.control = port_value(obj["probe_outs"][0])
        self.token = (port_value(obj["probe_ins"][0]) >> 24) & 255
        self.sample()

    def sample(self):
        obj = dvio_json(self.shell.command("dbg_dvio_refresh_input -device 1 -dvio 0\ndbg_dvio_print -device 1 -dvio 0", timeout=30))
        ports = list(map(port_value, obj["probe_ins"]))
        if ports[0] >> 48 != 0x5258 or ports[1] >> 32 != 0x524f4631:
            raise RuntimeError("Wrong firmware; expected separate RO PUF v1")
        self.status, self.diagnostics = ports[:2]
        self.responses = ports[2].to_bytes(32, "little")
        self.batch_info = ports[3]
        self.count_page = b"".join(port.to_bytes(32, "little") for port in ports[4:10])
        self.count_info = ports[10]
        self.ties = ports[11].to_bytes(32, "little")
        return self.status

    def set_control(self, value):
        commands = [f"dbg_dvio_set_output -device 1 -dvio 0 -channel {{ProbeOut0[{bit}]}} -value {(value >> bit) & 1}"
                    for bit in range(32) if (self.control ^ value) & (1 << bit)]
        commands.append("dbg_dvio_commit_output -device 1 -dvio 0")
        self.shell.command("\n".join(commands), timeout=30)
        self.control = value

    def measure_batch(self, index):
        pair_indices(index, 0)
        if not self.status & 2:
            raise RuntimeError("RO power-on reset has not released")
        self.set_control((self.token << 24) | index)
        self.token ^= 1 if self.token in (0, 128) else 128
        self.set_control((self.token << 24) | index)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.sample()
            if (status >> 24) & 255 == self.token and status & (1 << 23) and not status & (1 << 22):
                break
        else:
            raise TimeoutError("RO batch timed out")
        if (status >> 32) & 65535 != index or (status >> 14) & 255 != 255 or status & 0x30:
            raise RuntimeError(f"RO health/challenge failure: {status:016x}")
        responses, batch_info, ties = self.responses, self.batch_info, self.ties
        pages = []
        counts_crc = None
        for page in range(8):
            self.set_control((self.token << 24) | (page << 16) | index)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.sample()
                info = self.count_info
                if info >> 48 != 0x4341 or (info >> 40) & 255 != self.token:
                    raise RuntimeError("Count page token/signature mismatch")
                if ((info >> 32) & 0x87) == (0x80 | page):
                    break
            else:
                raise TimeoutError("Count page timed out")
            if (self.status >> 32) & 65535 != index or (self.status >> 24) & 255 != self.token or self.status & (1 << 22):
                raise RuntimeError("Batch changed during count readout")
            if self.responses != responses or self.ties != ties or self.batch_info != batch_info:
                raise RuntimeError("Response cache changed during page readout")
            crc = info & 0xffffffff
            if counts_crc is not None and crc != counts_crc:
                raise RuntimeError("Count checksum changed between pages")
            counts_crc = crc
            pages.append(self.count_page)
        counts = b"".join(pages)
        pairs = decode_batch(self.status, responses, batch_info, counts, counts_crc, ties)
        return responses, pairs, ties, counts_crc


def capture(args):
    if not 1 <= args.challenges <= 1024 or args.repeats != 32:
        raise ValueError("RO v1 needs 1..1024 challenges and exactly 32 repeats")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.session):
        raise ValueError("Invalid session name")
    digest = hashlib.sha256(BITSTREAM.read_bytes()).hexdigest()
    validation = json.loads((ROOT / "build/implementation_validation.json").read_text())
    if validation["bitstream_sha256"] != digest:
        raise ValueError("Image differs from checked implementation")
    if validation.get("ro_stages") != 7 or validation.get("counter_input_limit_hz") != COUNTER_INPUT_LIMIT_HZ:
        raise ValueError("Implementation measurement parameters differ from host")
    folder = ROOT / "runs" / args.session
    folder.mkdir(parents=True, exist_ok=False)
    indices = random.Random(args.seed).sample(range(1024), args.challenges)
    manifest = dict(board=args.board, session=args.session, started_utc=now(), firmware="ro_puf_v1",
                    challenge_mapping=MAPPING,
                    challenges=indices, repeats=32, seed=args.seed, oscillator_count=64, ro_stages=7,
                    window_clocks=WINDOW_CLOCKS, divider=DIVIDER, system_clock_hz=50_000_000,
                    counter_input_limit_hz=COUNTER_INPUT_LIMIT_HZ,
                    bitstream_sha256=digest, conditions=args.conditions, power_cycle_id=args.power_cycle_id,
                    status="incomplete", samples=0, counter_rows=0)
    path = folder / "manifest.json"
    def checkpoint():
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checkpoint()
    shell = None
    try:
        shell = Debugger(args.pds / "bin/cdt_dbg_shell.exe", folder)
        device = RoDvio(shell)
        manifest.update(initial_status_hex=f"{device.status:016x}", initial_clock_ticks=device.diagnostics & 0xffffffff)
        with (folder / "samples.csv").open("w", newline="", encoding="utf-8") as raw, (folder / "counts.csv").open("w", newline="", encoding="utf-8") as counter:
            samples = csv.DictWriter(raw, fieldnames=FIELDS)
            counts = csv.DictWriter(counter, fieldnames=COUNT_FIELDS)
            samples.writeheader(); counts.writeheader()
            for index in indices:
                responses, pairs, ties, count_crc = device.measure_batch(index)
                received = now()
                for repeat, response in enumerate(responses):
                    samples.writerow(dict(challenge_index=index,repeat=repeat,response_hex=f"{response:02x}",arrived_hex="ff",
                                          status_hex=f"{device.status:016x}",batch_crc32=f"{device.batch_info & 0xffffffff:08x}",
                                          clock_ticks=device.diagnostics & 0xffffffff,utc=received,tie_mask_hex=f"{ties[repeat]:02x}",counts_crc32=f"{count_crc:08x}"))
                    for lane in range(8):
                        a,b=pairs[repeat*8+lane]
                        ia,ib=pair_indices(index,lane)
                        counts.writerow(dict(challenge_index=index,repeat=repeat,lane=lane,ro_a=ia,ro_b=ib,count_a=a,count_b=b,
                                             delta=a-b,window_clocks=WINDOW_CLOCKS,divider=DIVIDER,utc=received))
                        manifest["counter_rows"] += 1
                    manifest["samples"] += 1
                raw.flush(); counter.flush(); checkpoint()
                print(f"{args.board}: {manifest['samples']}/{len(indices)*32} RO byte samples", flush=True)
        manifest["status"]="complete"
    except BaseException as exc:
        manifest["error"]=f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            if shell:
                shell.close()
        finally:
            manifest["ended_utc"]=now()
            for name in ("samples","counts"):
                file=folder / f"{name}.csv"
                if file.exists():
                    manifest[f"{name}_sha256"]=hashlib.sha256(file.read_bytes()).hexdigest()
            checkpoint()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board",required=True,choices=("A","B"))
    parser.add_argument("--session",required=True)
    parser.add_argument("--challenges",type=int,default=256)
    parser.add_argument("--repeats",type=int,default=32)
    parser.add_argument("--seed",type=int,default=20261008)
    parser.add_argument("--conditions",default="ambient; temperature and supply not instrumented")
    parser.add_argument("--power-cycle-id",default="unconfirmed")
    parser.add_argument("--pds",type=Path,default=Path("C:/pango/PDS_2025.2-ads"))
    capture(parser.parse_args())


if __name__=="__main__":
    main()
