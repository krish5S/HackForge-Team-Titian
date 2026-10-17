import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

from PIL import Image, ImageDraw

from backend.app.pipeline.duplicates import find_duplicates
from backend.app.pipeline.cnn import predict_fake_probability
from backend.app.pipeline.normalize import load_image
from backend.app.pipeline.process import process_receipt
from backend.app.pipeline.reader_a import read_fields as read_patterns
from backend.app.llm.client import extract_receipt_fields
from scripts.compare_month_readers import compare


class ReaderPipelineTests(unittest.TestCase):
    def test_text_model_answer_is_cached_by_file_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            with (patch.dict(os.environ, {"RECEIPT_LLM_ENDPOINT": "https://example.invalid/receipt"}),
                  patch("backend.app.llm.client.urlopen", return_value=io.BytesIO(b'{"category":"MEALS"}')) as post):
                first = extract_receipt_fields("OCR text", "a" * 64, Path(folder))
                second = extract_receipt_fields("OCR text", "a" * 64, Path(folder))
            self.assertEqual(first, {"category": "MEALS"})
            self.assertEqual(second, first)
            self.assertEqual(post.call_count, 1)
            sent = json.loads(post.call_args[0][0].data)
            self.assertEqual(sent["ocr_text"], "OCR text")

    def test_reader_switch_rejects_incomplete_month(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            index = root / "images_index.json"
            scenarios = root / "scenarios.json"
            index.write_text('{"images": [], "pending_public_scenarios": ["r_001"]}',
                             encoding="utf-8")
            scenarios.write_text('{"scenarios": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finalized 100"):
                compare(index, root, scenarios, root / "metrics.json")

    def test_item_lines_support_auditable_alcohol_exclusion(self):
        texts = ["Cafe", "Receipt: r_050", "SUBTOTAL", "20.00 USD", "Food", "15.00", "Beer", "5.00", "TOTAL", "20.00 USD"]
        result = read_patterns({"lines": [{"text": value, "confidence": .95, "box": []}
                                          for value in texts]})
        self.assertEqual(result["line_items"], [
            {"description": "Food", "amount": "15.00", "item_class": "FOOD"},
            {"description": "Beer", "amount": "5.00", "item_class": "ALCOHOL"}])
        self.assertEqual(result["itemization"], "FULL")
        self.assertEqual(result["receipt_number"], "R_050")

    def test_cnn_gate_rejects_unqualified_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            metrics = root / "metrics.json"
            (root / "unused.pt").write_bytes(b"unused")
            metrics.write_text('{"auc": 0.74, "cnn_weight_enabled": true}', encoding="utf-8")
            with patch.dict(os.environ, {"RECEIPT_CNN_METRICS": str(metrics),
                                      "RECEIPT_CNN_MODEL": str(root / "unused.pt")}):
                self.assertEqual(predict_fake_probability(root / "receipt.jpg"), (0.0, False))
                metrics.write_text('{"auc": 0.99, "cnn_weight_enabled": true, '
                                   '"express_expense_false_positive_rate": 0.35}', encoding="utf-8")
                self.assertEqual(predict_fake_probability(root / "receipt.jpg"), (0.0, False))

    def test_pdf_first_page_is_readable_image(self):
        import pypdfium2 as pdfium

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.pdf"
            document = pdfium.PdfDocument.new()
            document.new_page(200, 300)
            document.save(str(path))
            document.close()
            pixels = load_image(path)
            self.assertEqual(pixels.shape, (600, 400, 3))

    def test_contract_and_arithmetic_from_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "receipt.jpg"
            image = Image.new("RGB", (300, 450), "white")
            ImageDraw.Draw(image).text((20, 20), "BISTRO", fill="black")
            image.save(source)
            rows = [("BISTRO", .99), ("2026-09-01 12:00", .98),
                    ("SUBTOTAL 20.00", .98), ("TAX 2.00", .95),
                    ("TIP 3.00", .96), ("TOTAL 25.00 USD", .97)]
            ocr = {"lines": [{"text": line, "confidence": confidence,
                              "box": [[0, 0], [100, 0], [100, 20], [0, 20]]}
                             for line, confidence in rows],
                   "full_text": "\n".join(line for line, _ in rows)}
            with patch("backend.app.pipeline.process.extract_text", return_value=ocr):
                result = process_receipt(source, {"receipt_id": "r_001"}, root / "out")
            self.assertEqual(result["receipt_id"], "r_001")
            self.assertEqual(result["extraction"]["total"], "25.00")
            self.assertEqual(result["fx"]["total_base"], "25.00")
            self.assertTrue(result["is_receipt"])
            self.assertTrue(next(c for c in result["validation"]["checks"]
                                 if c["name"] == "components_vs_total")["passed"])
            self.assertEqual(len(result["file_sha256"]), 64)
            self.assertEqual(len(result["fingerprints"]["phash"]), 16)
            json.dumps(result)
            with (patch("backend.app.pipeline.process.extract_text", return_value=ocr),
                  patch("backend.app.pipeline.process.read_model", return_value={"total": "30.00"})):
                disputed = process_receipt(source, {"receipt_id": "r_001"}, root / "out")
            self.assertIn("reader_disagreement_total", disputed["forensics"]["signals"])
            self.assertLess(disputed["extraction"]["confidence"]["total"], .5)
            with (patch("backend.app.pipeline.process.extract_text", return_value=ocr),
                  patch("backend.app.pipeline.process.read_layoutlm", return_value={
                      "total": "26.00", "confidence": {"total": .99},
                      "boxes": {"total": [0, 0, 100, 20]}})):
                switched = process_receipt(source, {"receipt_id": "r_001"}, root / "out")
            self.assertEqual(switched["extraction"]["total"], "26.00")
            self.assertIn("reader_a_layoutlm", switched["extraction"]["readers"])
            with (patch("backend.app.pipeline.process.extract_text", return_value=ocr),
                  patch("backend.app.pipeline.process.read_layoutlm", side_effect=RuntimeError("model unavailable"))):
                fallback = process_receipt(source, {"receipt_id": "r_001"}, root / "out")
            self.assertEqual(fallback["extraction"]["total"], "25.00")
            self.assertIn("reader_a_layoutlm_error", fallback["extraction"]["readers"])

    def test_duplicate_guards_and_exact_copy(self):
        def receipt(identifier, digest, number="123", time="12:00"):
            return {"receipt_id": identifier, "file_sha256": digest,
                    "extraction": {"merchant_name": "Bistro", "receipt_number": number,
                                   "card_last4": "1234", "transaction_time": time,
                                   "transaction_date": "2026-09-01"},
                    "fx": {"total_base": "25.00"},
                    "fingerprints": {"merchant_norm": "bistro", "phash": "0000000000000000"}}
        rows = [receipt("a", "sha1"), receipt("b", "sha1"),
                receipt("c", "sha2", number="999"), receipt("d", "sha3", time="13:00"),
                receipt("e", "sha4")]
        pairs = find_duplicates(rows)
        self.assertIn({"receipt_id": "b", "duplicate_of": "a", "reason": "exact_file"}, pairs)
        self.assertIn({"receipt_id": "e", "duplicate_of": "a", "reason": "transaction"}, pairs)
        self.assertFalse(any(pair["receipt_id"] in ("c", "d") for pair in pairs))

    def test_numeric_merchant_names_do_not_merge(self):
        base = {"extraction": {"transaction_date": "2026-09-01", "transaction_time": "12:00"},
                "fx": {"total_base": "20.00"}}
        receipts = [{**base, "receipt_id": "a", "file_sha256": "one",
                     "fingerprints": {"merchant_norm": "merchant 1", "phash": "0000000000000000"}},
                    {**base, "receipt_id": "b", "file_sha256": "two",
                     "fingerprints": {"merchant_norm": "merchant 3", "phash": "0000000000000000"}}]
        self.assertEqual(find_duplicates(receipts), [])


if __name__ == "__main__":
    unittest.main()
