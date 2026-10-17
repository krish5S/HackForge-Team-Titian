import json
from pathlib import Path
import hashlib
import tempfile
import unittest

from PIL import Image

from ml.fake_cnn.prepare import letterbox, prepare
from ml.splits.generate import generate
from ml.fake_cnn.train import validate_manifest


class PreparationTests(unittest.TestCase):
    def test_grayscale_letterbox_and_failure_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            Image.new("RGB", (100, 200), (20, 30, 40)).save(source / "good.png")
            (source / "bad.png").write_bytes(b"not an image")
            image = letterbox(source / "good.png")
            self.assertEqual(image.mode, "L")
            self.assertEqual(image.size, (384, 384))
            self.assertEqual(image.getpixel((0, 0)), 255)
            rows = prepare({"sample": source}, root / "output")
            self.assertEqual([row["status"] for row in rows], ["failed", "ok"])
            self.assertEqual(len(json.loads((root / "output" / "prepare_manifest.json").read_text())), 2)
            with Image.open(rows[1]["prepared_path"]) as saved:
                self.assertEqual(saved.size, (384, 384))
                self.assertEqual(saved.mode, "L")


class SplitTests(unittest.TestCase):
    def test_sroie_ratios_and_heldout_reservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            rows = []
            for index in range(10):
                path = Path(temporary) / f"{index}.png"
                # Distinct deterministic image content prevents duplicate groups.
                image = Image.new("L", (9, 8))
                image.putdata([((index * 137 + pixel * 41 + pixel * pixel * (index + 1)) % 256)
                               for pixel in range(72)])
                image.save(path)
                rows.append({"source": "sroie", "source_id": str(index), "image_path": str(path),
                             "group_id": str(index), "label": "real"})
            result = generate(rows, {"sroie:0"}, seed=42)
            counts = {split: sum(row["split"] == split for row in result)
                      for split in ("train", "val", "test")}
            self.assertEqual(counts, {"train": 8, "val": 1, "test": 1})
            self.assertTrue(next(row for row in result if row["record_id"] == "sroie:0")["test_month"])
            self.assertEqual(result, generate(rows, {"sroie:0"}, seed=42))

    def test_fake_label_requires_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.png"
            Image.new("L", (10, 10), 255).save(path)
            with self.assertRaisesRegex(ValueError, "Fake label needs annotation provenance"):
                generate([{"source": "gpt4o-receipt", "source_id": "1", "image_path": str(path),
                           "group_id": "1", "merchant_category": "food", "label": "fake"}], set())

    def test_training_refuses_single_class(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "real.png"
            Image.new("L", (10, 10), 255).save(path)
            row = {"record_id": "sroie:1", "source": "sroie", "group_id": "1",
                   "image_path": str(path), "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "leakage_group": "sroie:1", "label": "real", "split": "train"}
            with self.assertRaisesRegex(ValueError, "Insufficient verified labels"):
                validate_manifest({"rows": [row]})


if __name__ == "__main__":
    unittest.main()
