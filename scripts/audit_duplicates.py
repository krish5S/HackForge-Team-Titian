"""Audit duplicate matching against indexed planted variants using scenario facts."""

import argparse
import json
from pathlib import Path

from backend.app.pipeline.duplicates import find_duplicates
from backend.app.pipeline.fingerprints import normalize_merchant, perceptual_hash, sha256_file
from backend.app.pipeline.fx import convert_total, load_rates

DUPLICATE_TYPES = {"exact_duplicate", "rephotographed_duplicate",
                   "pdf_photo_duplicate", "cross_employee_duplicate"}


def _load_scenarios(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        import yaml
        payload = yaml.safe_load(raw)
    return payload["scenarios"] if isinstance(payload, dict) else payload


def audit(index_path: Path, images_dir: Path, scenarios_path: Path) -> dict:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    scenarios = {row["scenario_id"]: row for row in _load_scenarios(scenarios_path)}
    rates = load_rates()
    receipts = []
    expected = set()
    for entry in index["images"]:
        identifier = entry["scenario_id"]
        scenario = scenarios[identifier]
        source = images_dir / entry["file"]
        extraction = {field: str(scenario.get(field) or "") for field in
                      ("merchant", "transaction_date", "transaction_time",
                       "receipt_number", "card_last4", "total", "currency")}
        extraction["merchant_name"] = extraction.pop("merchant")
        if entry["source"] == "rendered" and not extraction["receipt_number"]:
            related = entry.get("related_ids") or []
            extraction["receipt_number"] = (related[0] if entry.get("planted_problem") in DUPLICATE_TYPES
                                            and related else identifier)
        fx = convert_total(extraction["total"], extraction["currency"], rates)
        receipts.append({"receipt_id": identifier, "file_sha256": sha256_file(source),
                         "extraction": extraction, "fx": fx,
                         "fingerprints": {"phash": perceptual_hash(source),
                                          "merchant_norm": normalize_merchant(extraction["merchant_name"])}})
        if entry.get("planted_problem") in DUPLICATE_TYPES:
            expected.update(tuple(sorted((identifier, related))) for related in entry.get("related_ids", []))
    candidates = find_duplicates(receipts)
    found = {tuple(sorted((row["receipt_id"], row["duplicate_of"]))) for row in candidates}
    return {"images": len(receipts), "expected_pairs": len(expected),
            "found_expected_pairs": len(expected & found),
            "missed_pairs": sorted(expected - found),
            "extra_candidates": sorted(found - expected),
            "candidate_count": len(found)}


def audit_processed(index_path: Path, processed_dir: Path, scenarios_path: Path) -> dict:
    """Measure the actual batch output, including cached OCR text evidence."""
    index = json.loads(index_path.read_text(encoding="utf-8"))["images"]
    scenarios = {row["scenario_id"]: row for row in _load_scenarios(scenarios_path)}
    receipts, ocr_texts, expected = [], {}, set()
    for entry in index:
        identifier = entry["scenario_id"]
        receipt = json.loads((processed_dir / f"{identifier}.json").read_text(encoding="utf-8"))
        receipts.append(receipt)
        cache = processed_dir / "work" / "ocr_cache" / f"{receipt['file_sha256']}.json"
        if cache.is_file():
            ocr_texts[identifier] = json.loads(cache.read_text(encoding="utf-8")).get("full_text", "")
        if scenarios[identifier].get("planted_issue") in DUPLICATE_TYPES:
            expected.update(tuple(sorted((identifier, other)))
                            for other in scenarios[identifier].get("related_ids", []))
    found = {tuple(sorted((row["receipt_id"], row["duplicate_of"])))
             for row in find_duplicates(receipts, ocr_texts)}
    return {"images": len(receipts), "expected_pairs": len(expected),
            "found_expected_pairs": len(expected & found),
            "missed_pairs": sorted(expected - found),
            "extra_candidates": sorted(found - expected),
            "candidate_count": len(found), "basis": "processed_receipts_and_cached_ocr"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("data/month/images_index.json"))
    parser.add_argument("--images", type=Path, default=Path("data/month/images"))
    parser.add_argument("--scenarios", type=Path, default=Path("data/month/scenarios.yaml"))
    parser.add_argument("--processed", type=Path,
                        help="Audit the batch output and cached OCR instead of scenario facts")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = (audit_processed(args.index, args.processed, args.scenarios)
              if args.processed else audit(args.index, args.images, args.scenarios))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
