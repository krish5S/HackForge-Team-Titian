"""Normalize, OCR, read, and validate a receipt into the shared contract."""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from backend.app.contracts.receipt import ProcessedReceipt
from backend.app.pipeline.fingerprints import normalize_merchant, perceptual_hash, sha256_file
from backend.app.pipeline.cnn import predict_fake_probability
from backend.app.pipeline.forensics import score_receipt
from backend.app.pipeline.fx import convert_total, load_rates
from backend.app.pipeline.normalize import save_normalized
from backend.app.pipeline.ocr import extract_text
from backend.app.pipeline.reader_a import read_fields as read_patterns
from backend.app.pipeline.reader_b import read_fields as read_model
from backend.app.pipeline.validate import validate_extraction

LOG = logging.getLogger(__name__)
STRING_FIELDS = ("merchant_name", "receipt_number", "card_last4", "transaction_date",
                 "transaction_time", "city", "country", "currency", "subtotal", "tax",
                 "tip", "other_charges", "total", "itemization", "category")


def process_receipt(
    path: str | Path,
    submission: dict[str, Any] | str | Path | None = None,
    output_dir: str | Path | None = None,
) -> ProcessedReceipt:
    """Read one receipt. A string second argument remains a CLI output directory."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if isinstance(submission, (str, Path)):
        output_dir = submission
        submission = None
    submission = submission or {}
    target = Path(output_dir) if output_dir else Path.home() / "datasets" / "processed_receipts"
    target.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(source)
    normalized_path = target / f"{source.stem}_{digest[:12]}_normalized.jpg"
    save_normalized(source, normalized_path)
    ocr = extract_text(normalized_path)
    pattern = read_patterns(ocr)
    model: dict[str, Any] = {}
    model_error = ""
    try:
        model = read_model(ocr.get("full_text", ""), digest, target / "llm_cache")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        model_error = str(exc)
        LOG.warning("Text model unavailable for %s: %s", source, exc)

    extraction: dict[str, Any] = {field: "" for field in STRING_FIELDS}
    extraction.update({"line_items": [], "guest_count": 0,
                       "confidence": {}, "boxes": {}, "readers": {"reader_a": pattern,
                                                                   "reader_b": model}})
    for field in STRING_FIELDS:
        value = pattern.get(field) or model.get(field)
        if value is not None:
            extraction[field] = str(value)
    extraction["line_items"] = model.get("line_items", pattern.get("line_items", []))
    extraction["guest_count"] = model.get("guest_count", pattern.get("guest_count", 0))
    extraction["confidence"] = pattern.get("confidence", {})
    extraction["boxes"] = pattern.get("boxes", {})
    if model_error:
        extraction["readers"]["reader_b_error"] = {"message": model_error}
    disagreement = []
    for field in ("total", "transaction_date"):
        if pattern.get(field) and model.get(field) and str(pattern[field]) != str(model[field]):
            disagreement.append(field)
            extraction["confidence"][field] = min(extraction["confidence"].get(field, 1.0), 0.49)

    rates = load_rates()
    validation = validate_extraction(extraction)
    if disagreement:
        for field in disagreement:
            validation["checks"].append({"name": f"reader_disagreement_{field}",
                                          "expected": str(pattern[field]),
                                          "printed": str(model[field]), "passed": False})
    fx = convert_total(extraction["total"], extraction["currency"], rates)
    line_count = len(ocr.get("lines") or [])
    is_receipt = line_count > 0 and bool(extraction["merchant_name"] or extraction["total"])
    status = "unreadable" if not line_count else ("ok" if extraction["total"] else "partial")
    result: ProcessedReceipt = {
        "receipt_id": str(submission.get("receipt_id") or submission.get("scenario_id") or source.stem),
        "file_sha256": digest,
        "is_receipt": is_receipt,
        "extraction_status": status,
        "extraction": extraction,
        "validation": validation,
        "fx": fx,
        "fingerprints": {"phash": perceptual_hash(source),
                         "merchant_norm": normalize_merchant(extraction["merchant_name"])},
        "forensics": {"score": 0, "cnn_fake_probability": 0.0, "signals": []},
    }
    probability, enabled = predict_fake_probability(normalized_path)
    result["forensics"] = score_receipt(result, probability, enabled)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process one receipt into the shared JSON contract")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", default=str(Path.home() / "datasets" / "processed_receipts"))
    args = parser.parse_args()
    receipt = process_receipt(args.image, output_dir=args.output_dir)
    output = Path(args.output_dir) / f"{receipt['receipt_id']}.json"
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
