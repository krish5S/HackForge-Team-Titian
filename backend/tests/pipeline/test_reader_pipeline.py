import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from backend.app.pipeline.duplicates import find_duplicates
from backend.app.pipeline.normalize import load_image
from backend.app.pipeline.process import process_receipt


class ReaderPipelineTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
