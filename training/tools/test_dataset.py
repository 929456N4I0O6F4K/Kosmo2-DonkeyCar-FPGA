import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from dataset import image_array, load_sessions


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "images").mkdir()
        Image.new("RGB", (160, 120), (255, 0, 0)).save(self.root / "images/1.png")
        self.meta = {"schema": "kosmo-training-v1", "session_id": "one", "synthetic": False}
        self.record = {"session_id": "one", "user/mode": "user", "user/angle": -.2, "user/throttle": .1,
                       "capture_us": 1, "frame_sequence": 1, "cam/image_array": "images/1.png"}
        self.save()

    def save(self, records=None):
        (self.root / "session.json").write_text(json.dumps(self.meta))
        (self.root / "records.jsonl").write_text("\n".join(json.dumps(r) for r in (records or [self.record])) + "\n")

    def test_crop_and_color(self):
        records, _ = load_sessions([self.root])
        rgb = image_array(records[0])
        self.assertEqual(rgb.shape, (95, 156, 3))
        self.assertEqual(rgb[0, 0].tolist(), [255, 0, 0])

    def test_synthetic_rejected_by_default(self):
        self.meta["synthetic"] = True
        self.save()
        with self.assertRaisesRegex(ValueError, "Synthetic"):
            load_sessions([self.root])
        self.assertEqual(len(load_sessions([self.root], True)[0]), 1)

    def test_duplicate_frame_and_session_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate session"):
            load_sessions([self.root, self.root])
        self.save([self.record, self.record])
        with self.assertRaisesRegex(ValueError, "Duplicate/out-of-order"):
            load_sessions([self.root])

    def test_invalid_labels_and_path(self):
        for key, value in [("user/angle", float("nan")), ("user/throttle", -1), ("cam/image_array", "../outside.png")]:
            original = self.record.copy()
            self.record[key] = value
            self.save()
            with self.assertRaises(ValueError):
                load_sessions([self.root])
            self.record = original

    def test_truncated_record_is_not_silently_used(self):
        with (self.root / "records.jsonl").open("a") as f:
            f.write('{"session_id":')
        with self.assertRaisesRegex(ValueError, "Truncated"):
            load_sessions([self.root])


if __name__ == "__main__":
    unittest.main()
