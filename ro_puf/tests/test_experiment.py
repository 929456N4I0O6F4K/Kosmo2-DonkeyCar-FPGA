"""Check integrity rejection, enrollment masks and the two-commit JTAG protocol."""
import csv
import hashlib
import json
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from capture import FIELDS, COUNT_FIELDS, WINDOW_CLOCKS, DIVIDER, MAX_COUNT, COUNTER_INPUT_LIMIT_HZ, MAPPING, decode_batch, pair_indices, RoDvio
from compare import load, compare, summarize
from export_response import export
from report_board import report, markdown
from report_ab import build_report


def batch(index=0, token=1, change=None):
    data, ties, packed = bytearray(), bytearray(), bytearray()
    for repeat in range(32):
        response = tie = 0
        for lane in range(8):
            a, b = (1001, 1000) if lane % 2 else (999, 1000)
            if change:
                a, b = change(index, repeat, lane, a, b)
            response |= (a > b) << lane
            tie |= (a == b) << lane
            packed.extend(a.to_bytes(3, "little")); packed.extend(b.to_bytes(3, "little"))
        data.append(response); ties.append(tie)
    status = (0x5258 << 48) | (index << 32) | (token << 24) | (1 << 23) | (255 << 14) | (data[-1] << 6) | 10
    info = (0x5231 << 48) | (32 << 40) | (token << 32) | zlib.crc32(data)
    return status, bytes(data), info, bytes(packed), zlib.crc32(packed), bytes(ties)


def session(folder, board="A", indices=(0, 1023), change=None):
    folder.mkdir()
    with (folder / "samples.csv").open("w", newline="", encoding="utf-8") as raw, (folder / "counts.csv").open("w", newline="", encoding="utf-8") as count:
        sw = csv.DictWriter(raw, fieldnames=FIELDS); cw = csv.DictWriter(count, fieldnames=COUNT_FIELDS)
        sw.writeheader(); cw.writeheader()
        for index in indices:
            status, data, info, packed, crc, ties = batch(index, change=change)
            pairs = decode_batch(status, data, info, packed, crc, ties)
            for repeat, byte in enumerate(data):
                sw.writerow(dict(challenge_index=index, repeat=repeat, response_hex=f"{byte:02x}", arrived_hex="ff",
                                 status_hex=f"{status:016x}", batch_crc32=f"{info & 0xffffffff:08x}", clock_ticks=42,
                                 utc="synthetic", tie_mask_hex=f"{ties[repeat]:02x}", counts_crc32=f"{crc:08x}"))
                for lane in range(8):
                    a, b = pairs[repeat * 8 + lane]; ia, ib = pair_indices(index, lane)
                    cw.writerow(dict(challenge_index=index, repeat=repeat, lane=lane, ro_a=ia, ro_b=ib, count_a=a,
                                     count_b=b, delta=a-b, window_clocks=WINDOW_CLOCKS, divider=DIVIDER, utc="synthetic"))
    manifest = dict(status="complete", firmware="ro_puf_v1", board=board, session=folder.name, challenges=list(indices),
                    repeats=32, bitstream_sha256="synthetic-image", challenge_mapping=MAPPING,
                    ro_stages=7,oscillator_count=64,window_clocks=WINDOW_CLOCKS,divider=DIVIDER,
                    system_clock_hz=50_000_000,counter_input_limit_hz=COUNTER_INPUT_LIMIT_HZ,
                    conditions="synthetic fixture; no board",power_cycle_id="synthetic",
                    samples=len(indices)*32, counter_rows=len(indices)*256)
    for name in ("samples", "counts"):
        manifest[f"{name}_sha256"] = hashlib.sha256((folder / f"{name}.csv").read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_checksums_and_count_response_reconstruction(self):
        frame = list(batch())
        self.assertEqual(len(decode_batch(*frame)), 256)
        for slot in (1, 3):
            corrupted = frame.copy(); data = bytearray(corrupted[slot]); data[0] ^= 1; corrupted[slot] = bytes(data)
            with self.assertRaises(ValueError):
                decode_batch(*corrupted)
        wrong = frame.copy(); wrong[5] = bytes([1]) + wrong[5][1:]
        with self.assertRaisesRegex(ValueError, "tie mask"):
            decode_batch(*wrong)
        wrong = frame.copy(); wrong[0] |= 1 << 22
        with self.assertRaises(ValueError):
            decode_batch(*wrong)

    def test_zero_and_above_timing_bound_counts_rejected_even_with_valid_crc(self):
        for value in (0, MAX_COUNT+1):
            frame = batch(change=lambda i, r, l, a, b: (value, b) if r == 0 and l == 0 else (a, b))
            with self.assertRaisesRegex(ValueError, "validated range"):
                decode_batch(*frame)

    def test_incomplete_and_csv_tampering_rejected(self):
        folder = session(self.root / "good")
        self.assertEqual(len(load(folder)[1]), 2)
        with (folder / "counts.csv").open("a", encoding="utf-8") as stream:
            stream.write("tampering\n")
        with self.assertRaisesRegex(ValueError, "hash"):
            load(folder)
        manifest = json.loads((folder / "manifest.json").read_text()); manifest["status"] = "incomplete"
        (folder / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "complete"):
            load(folder)

    def test_conservative_tie_mask_and_unanimous_export(self):
        def change(i, r, l, a, b):
            if i == 0 and l == 0 and r == 0:
                return b, b
            if i == 0 and l == 1 and r == 0:
                return b-1, b
            return a, b
        folder = session(self.root / "ties", change=change)
        summary = summarize(folder)
        self.assertEqual(summary["aggregate"]["equal_count_samples"], 1)
        strict, voted = export(folder), export(folder, "majority")
        self.assertEqual(strict["rows"][0]["valid_mask_hex"], "fc")
        self.assertEqual(voted["rows"][0]["valid_mask_hex"], "fe")
        self.assertEqual(strict["rows"][0]["response_hex"], "a8")
        self.assertNotEqual(strict["binding_sha256"], voted["binding_sha256"])
        self.assertEqual(export(folder, min_count_margin=2)["valid_bits"], 0)

    def test_fixed_reference_errors_and_excluded_ties(self):
        a = session(self.root / "reference")
        def change(i, r, l, x, y):
            if i == 0 and l == 0 and r == 0:
                return y+1, y
            if i == 0 and l == 1 and r == 0:
                return y, y
            return x, y
        b = session(self.root / "verification", change=change)
        result = compare(a, b, same_board=True)
        self.assertEqual(result["aggregate"]["raw_errors_to_reference"], 1)
        self.assertEqual(result["aggregate"]["verification_bits"], 511)
        self.assertEqual(result["aggregate"]["comparable_bits"], 15)
        self.assertEqual(result["aggregate"]["raw_error_rate"], 1/511)
        with self.assertRaises(ValueError):
            compare(a, a, same_board=True)

    def test_cross_board_weighted_hamming_and_image_binding(self):
        a = session(self.root / "A")
        def change(i, r, l, x, y):
            return (y, y) if i == 0 and l == 0 else ((y-1, y) if l == 1 else (x, y))
        b = session(self.root / "B", board="B", change=change)
        result = compare(a, b)
        self.assertEqual(result["aggregate"]["ab_majority_hamming"], 2/15)
        path = b / "manifest.json"; manifest = json.loads(path.read_text()); manifest["bitstream_sha256"] = "different"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Bitstream"):
            compare(a, b)

    def test_measurement_parameters_cannot_be_relabelled(self):
        folder=session(self.root/"parameters")
        path=folder/"manifest.json"; manifest=json.loads(path.read_text()); manifest["divider"]=8
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,"parameters"):
            load(folder)

    def test_all_equal_counts_are_unavailable_in_report_and_export(self):
        folder=session(self.root/"all_ties",change=lambda i,r,l,a,b:(b,b))
        result=report(folder)
        self.assertEqual(result["summary"]["aggregate"]["raw_valid_bits"],0)
        self.assertEqual(result["enrollment_valid_bits"],0)
        self.assertIn("无有效位",markdown(result))
        self.assertEqual(export(folder)["valid_mask_bytes_hex"],"0000")

    def test_registered_mask_is_fixed_before_independent_verification(self):
        def baseline(i,r,l,a,b):
            return (b-1,b) if i==0 and l==1 and r==0 else (a,b)
        def verification(i,r,l,a,b):
            if i==0 and l==1:
                return b-1,b
            if i==0 and l==0 and r==0:
                return b,b
            if i==0 and l==2 and r==0:
                return b+1,b
            return a,b
        a=session(self.root/"registered",change=baseline)
        b=session(self.root/"independent",change=verification)
        result=report(a,b)["enrollment_verification"]
        self.assertEqual(result["registered_bits"],15)
        self.assertEqual(result["verified_raw_bits"],479)
        self.assertEqual(result["raw_errors"],1)
        self.assertEqual(result["equal_count_raw_bits"],1)
        self.assertEqual(result["unavailable_majorities"],1)

    def test_four_session_report_uses_weighted_hamming_and_fixed_reference(self):
        a=session(self.root/"A_reference")
        av=session(self.root/"A_verify")
        def change(i,r,l,x,y):
            return (y,y) if i==0 and l==0 else ((y-1,y) if l==1 else (x,y))
        b=session(self.root/"B_reference",board="B",change=change)
        bv=session(self.root/"B_verify",board="B",change=change)
        result=build_report(a,av,b,bv)
        self.assertEqual(result["total_response_bytes"],256)
        self.assertEqual(result["total_counter_pairs"],2048)
        self.assertEqual(len(result["between_boards"]),4)
        self.assertTrue(all(pair["aggregate"]["ab_majority_hamming"]==2/15 for pair in result["between_boards"]))
        self.assertEqual(result["boards"]["B"]["repeat_comparison"]["aggregate"]["raw_errors_to_reference"],0)
        with self.assertRaisesRegex(ValueError,"Expected A"):
            build_report(b,bv,a,av)

    def test_dvio_twelve_channels_little_endian_order(self):
        status, data, info, packed, crc, ties = batch()
        page = packed[:192]
        ports = [status, 0x524f463100000001, int.from_bytes(data, "little"), info]
        ports += [int.from_bytes(page[i:i+32], "little") for i in range(0, 192, 32)]
        ports += [(0x4341 << 48) | (1 << 40) | (1 << 39) | crc, int.from_bytes(ties, "little")]
        shell = unittest.mock.Mock()
        device = RoDvio.__new__(RoDvio); device.shell = shell
        with patch("capture.dvio_json", return_value={"probe_ins": ports}), patch("capture.port_value", side_effect=lambda x: x):
            device.sample()
        self.assertEqual(device.count_page, page)
        self.assertEqual(device.responses, data)
        self.assertEqual(device.ties, ties)

    def test_payload_commit_precedes_token_commit(self):
        status, data, info, packed, crc, ties = batch(index=17)
        device = RoDvio.__new__(RoDvio)
        device.status = 2; device.token = 0; writes = []
        device.set_control = writes.append
        def sample():
            device.status = status; device.responses = data; device.batch_info = info; device.ties = ties
            page = (writes[-1] >> 16) & 7
            device.count_page = packed[page*192:(page+1)*192]
            device.count_info = (0x4341 << 48) | (1 << 40) | (1 << 39) | (page << 32) | crc
            return status
        device.sample = sample
        self.assertEqual(device.measure_batch(17)[0], data)
        self.assertEqual(writes[:2], [17, (1 << 24) | 17])
        self.assertEqual([(v >> 16) & 7 for v in writes[2:]], list(range(8)))


if __name__ == "__main__":
    unittest.main()
