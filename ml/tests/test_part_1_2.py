import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from ml.datagen.render import render_month
from ml.datagen.pick_public import copy_public


class MonthImageTests(unittest.TestCase):
    def test_variants_and_public_sources(self):
        base = {"scenario_id": "r_001", "scenario_type": "clean", "merchant": "Fictional Bistro",
                "city": "Chicago", "country": "US", "transaction_date": "2026-09-01",
                "transaction_time": "12:00", "currency": "USD", "category": "MEALS",
                "line_items": [{"description": "Lunch", "amount": "20.00"}],
                "subtotal": "20.00", "tax": "0.00", "tip": "0.00", "total": "20.00"}
        rows = [base,
                {**base, "scenario_id": "r_002", "scenario_type": "exact_duplicate", "related_ids": ["r_001"]},
                {**base, "scenario_id": "r_003", "scenario_type": "rephotographed_duplicate", "related_ids": ["r_001"]},
                {**base, "scenario_id": "r_004", "scenario_type": "pdf_photo_duplicate", "related_ids": ["r_001"]},
                {**base, "scenario_id": "r_005", "scenario_type": "ai_generated"}]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = render_month(rows, root / "images", root / "images_index.json")
            self.assertEqual(len(result["images"]), 4)
            self.assertEqual(result["pending_public_scenarios"], ["r_005"])
            self.assertEqual((root / "images" / "r_001.jpg").read_bytes(),
                             (root / "images" / "r_002.jpg").read_bytes())
            self.assertNotEqual((root / "images" / "r_001.jpg").read_bytes(),
                                (root / "images" / "r_003.jpg").read_bytes())
            self.assertTrue((root / "images" / "r_004.pdf").read_bytes().startswith(b"%PDF"))
            self.assertEqual(len(json.loads((root / "images_index.json").read_text())["images"]), 4)

    def test_public_copy_requires_heldout_verified_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "public.jpg"
            source.write_bytes(b"receipt image")
            scenarios = [{"scenario_id": "r_010", "scenario_type": "clean", "planted_issue": None}]
            row = {"record_id": "sroie:10", "source": "sroie", "source_id": "10",
                   "image_path": str(source), "image_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "split": "test", "label": "real"}
            assignment = {"scenario_id": "r_010", "record_id": "sroie:10", "verified_fields": True}
            result = copy_public(scenarios, [assignment], {"rows": [row]},
                                 root / "images", root / "index.json")
            self.assertEqual(result["images"][0]["source_id"], "10")
            row["split"] = "train"
            with self.assertRaisesRegex(ValueError, "not held out"):
                copy_public(scenarios, [assignment], {"rows": [row]},
                            root / "other_images", root / "other_index.json")


if __name__ == "__main__":
    unittest.main()
