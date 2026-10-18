"""Process the indexed month images and write duplicate candidates."""

import argparse
import json
from pathlib import Path

from backend.app.pipeline.duplicates import find_duplicates
from backend.app.pipeline.process import process_receipt


def process_month(index_path: Path, images_dir: Path, output_dir: Path,
                  limit: int | None = None, resume: bool = False) -> list[dict]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    rows = index["images"]
    if len({row["scenario_id"] for row in rows}) != len(rows):
        raise ValueError("Repeated scenario IDs in images index")
    output_dir.mkdir(parents=True, exist_ok=True)
    receipts = []
    ocr_texts = {}
    for row in rows[:limit]:
        receipt_id = row["scenario_id"]
        destination = output_dir / f"{receipt_id}.json"
        if resume and destination.is_file():
            receipt = json.loads(destination.read_text(encoding="utf-8"))
        else:
            source = images_dir / row["file"]
            if not source.is_file():
                raise FileNotFoundError(source)
            receipt = process_receipt(source, {"receipt_id": receipt_id}, output_dir / "work")
            destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        receipts.append(receipt)
        cache = output_dir / "work" / "ocr_cache" / f"{receipt['file_sha256']}.json"
        if cache.is_file():
            ocr_texts[receipt_id] = json.loads(cache.read_text(encoding="utf-8")).get("full_text", "")
    duplicates = find_duplicates(receipts, ocr_texts)
    (output_dir / "duplicate_candidates.json").write_text(
        json.dumps(duplicates, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("data/month/images_index.json"))
    parser.add_argument("--images", type=Path, default=Path("data/month/images"))
    parser.add_argument("--output", type=Path, default=Path("data/month/processed"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = process_month(args.index, args.images, args.output, args.limit, args.resume)
    print(f"Processed {len(result)} receipts in {args.output}")
