import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from ml.layoutlm.prepare import normalize_box, prepare


class LayoutPreparationTests(unittest.TestCase):
    def test_polygon_boxes_and_field_mapping(self):
        self.assertEqual(normalize_box([20, 40, 80, 40, 80, 60, 20, 60], 100, 100),
                         [200, 400, 800, 600])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "wildreceipt"
            root.mkdir()
            (root / "class_list.txt").write_text("0 Ignore\n1 Store_name_value\n2 Total_value\n",
                                                  encoding="utf-8")
            Image.new("RGB", (100, 100), "white").save(root / "receipt.jpg")
            record = {"file_name": "receipt.jpg", "annotations": [
                {"text": "Cafe", "label": 1, "box": [10, 10, 50, 10, 50, 30, 10, 30]},
                {"text": "12.00", "label": 2, "box": [60, 60, 90, 60, 90, 80, 60, 80]}]}
            line = json.dumps(record) + "\n"
            (root / "train.txt").write_text(line * 2, encoding="utf-8")
            (root / "test.txt").write_text(line, encoding="utf-8")
            metadata = prepare(root, Path(directory) / "prepared")
            self.assertEqual(metadata["counts"], {"train": 1, "val": 1, "test": 1})
            example = json.loads((Path(directory) / "prepared" / "test.jsonl").read_text().splitlines()[0])
            self.assertEqual(example["labels"], [1, 9])
            self.assertEqual(example["boxes"], [[100, 100, 500, 300], [600, 600, 900, 800]])


if __name__ == "__main__":
    unittest.main()
