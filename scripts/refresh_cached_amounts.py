"""Refresh missing money and currency fields from cached OCR without running OCR again.

Use after changing Reader A's amount parser. Printed OCR text, rather than
scenario labels, supplies every value.
"""

import argparse
import json
from pathlib import Path

from backend.app.pipeline.forensics import score_receipt
from backend.app.pipeline.fx import convert_total, load_rates
from backend.app.pipeline.reader_a import read_fields
from backend.app.pipeline.validate import validate_extraction

AMOUNT_FIELDS = ("subtotal", "tax", "tip", "other_charges", "total")


def refresh(directory: Path, apply: bool = False) -> list[str]:
    rates = load_rates()
    changed = []
    for path in sorted(directory.glob("r_*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        extraction = receipt["extraction"]
        cache = directory / "work" / "ocr_cache" / f"{receipt['file_sha256']}.json"
        if not cache.is_file():
            continue
        pattern = read_fields(json.loads(cache.read_text(encoding="utf-8")))
        has_new_total = not extraction.get("total") and bool(pattern.get("total"))
        has_new_currency = not extraction.get("currency") and bool(pattern.get("currency"))
        if not has_new_total and not has_new_currency:
            continue
        reader = extraction["readers"]["reader_a"]
        if has_new_total:
            for field in AMOUNT_FIELDS:
                if pattern.get(field):
                    extraction[field] = pattern[field]
                    reader[field] = pattern[field]
            extraction["confidence"].update(pattern.get("confidence", {}))
            extraction["boxes"].update(pattern.get("boxes", {}))
            reader["confidence"].update(pattern.get("confidence", {}))
            reader["boxes"].update(pattern.get("boxes", {}))
            receipt["extraction_status"] = "OK"
        if has_new_currency:
            extraction["currency"] = reader["currency"] = pattern["currency"]
        receipt["validation"] = validate_extraction(extraction)
        receipt["fx"] = convert_total(extraction["total"], extraction["currency"], rates)
        receipt["forensics"] = score_receipt(receipt, 0, False)
        changed.append(receipt["receipt_id"])
        if apply:
            path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/month/processed"))
    parser.add_argument("--apply", action="store_true", help="Write refreshed receipt JSON")
    args = parser.parse_args()
    changed = refresh(args.directory, args.apply)
    print(json.dumps({"changed": len(changed), "receipt_ids": changed, "applied": args.apply}))
