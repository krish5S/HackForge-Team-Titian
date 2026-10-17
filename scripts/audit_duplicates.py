"""Audit duplicate matching against indexed planted variants using scenario facts."""

import argparse
import json
from pathlib import Path

from backend.app.pipeline.duplicates import find_duplicates
from backend.app.pipeline.fingerprints import normalize_merchant, perceptual_hash, sha256_file
from backend.app.pipeline.fx import convert_total, load_rates
from scripts.compare_month_readers import _load_scenarios

DUPLICATE_TYPES = {"exact_duplicate", "rephotographed_duplicate",
                   "pdf_photo_duplicate", "cross_employee_duplicate"}


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("data/month/images_index.json"))
    parser.add_argument("--images", type=Path, default=Path("data/month/images"))
    parser.add_argument("--scenarios", type=Path, default=Path("data/month/scenarios.yaml"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.index, args.images, args.scenarios)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
