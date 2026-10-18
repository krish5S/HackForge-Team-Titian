"""Map official WildReceipt box annotations into LayoutLMv3 word examples."""

import argparse
import json
from pathlib import Path
import random

from PIL import Image

CLASS_TO_FIELD = {
    "Store_name_value": "merchant_name", "Date_value": "transaction_date",
    "Time_value": "transaction_time", "Prod_item_value": "line_item_description",
    "Prod_price_value": "line_item_amount", "Subtotal_value": "subtotal",
    "Tax_value": "tax", "Tips_value": "tip", "Total_value": "total",
}
FIELDS = ["O", *dict.fromkeys(CLASS_TO_FIELD.values())]


def read_classes(path: Path) -> dict[int, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        result[int(parts[0])] = parts[1].strip()
    if not result or "Total_value" not in result.values():
        raise ValueError(f"Unrecognized WildReceipt class list: {path}")
    return result


def normalize_box(points: list[float], width: int, height: int) -> list[int]:
    if len(points) not in (4, 8):
        raise ValueError(f"Expected rectangle or quadrilateral: {points}")
    xs = points[0::2]
    ys = points[1::2]
    if len(points) == 4:
        xs, ys = [points[0], points[2]], [points[1], points[3]]
    box = [min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height]
    return [max(0, min(1000, round(value * 1000))) for value in box]


def load_annotations(root: Path, filename: str, classes: dict[int, str]) -> list[dict]:
    examples = []
    with (root / filename).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            relative = record.get("file_name") or record.get("filename")
            image_path = (root / relative).resolve()
            if root.resolve() not in image_path.parents or not image_path.is_file():
                raise FileNotFoundError(image_path)
            with Image.open(image_path) as image:
                width, height = image.size
            words, boxes, labels = [], [], []
            for annotation in record.get("annotations", []):
                word = str(annotation.get("text") or "").strip()
                if not word:
                    continue
                label = classes.get(int(annotation["label"]), "Ignore")
                box = normalize_box(annotation["box"], width, height)
                if box[0] >= box[2] or box[1] >= box[3]:
                    continue
                words.append(word)
                boxes.append(box)
                labels.append(FIELDS.index(CLASS_TO_FIELD.get(label, "O")))
            if words:
                examples.append({"image_path": str(image_path), "words": words,
                                 "boxes": boxes, "labels": labels})
    return examples


def prepare(root: Path, output: Path, seed: int = 42) -> dict:
    root = root.resolve()
    output = output.resolve()
    repository = Path(__file__).resolve().parents[2]
    if output == repository or repository in output.parents:
        raise ValueError("Prepared training data must stay outside Git")
    classes = read_classes(root / "class_list.txt")
    train = load_annotations(root, "train.txt", classes)
    test = load_annotations(root, "test.txt", classes)
    random.Random(seed).shuffle(train)
    val_count = max(1, round(len(train) * 0.1))
    splits = {"train": train[val_count:], "val": train[:val_count], "test": test}
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        (output / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8")
    metadata = {"fields": FIELDS, "source": str(root), "seed": seed,
                "counts": {name: len(rows) for name, rows in splits.items()}}
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / "datasets" / "wildreceipt")
    parser.add_argument("--output", type=Path, default=Path.home() / "datasets" / "layoutlm_prepared")
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output), indent=2))
