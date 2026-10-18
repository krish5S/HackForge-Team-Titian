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
from backend.app.pipeline.layoutlm_reader import read_fields as read_layoutlm
from backend.app.pipeline.fx import convert_total, load_rates
from backend.app.pipeline.normalize import save_normalized
from backend.app.pipeline.ocr import extract_text
from backend.app.pipeline.reader_a import read_fields as read_patterns, reading_rows
from backend.app.pipeline.reader_b import read_fields as read_model
from backend.app.pipeline.text_fallback import infer_fields
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
    ocr_path = target / "ocr_cache" / f"{digest}.json"
    if ocr_path.is_file():
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
    else:
        ocr = extract_text(normalized_path)
        ocr_path.parent.mkdir(parents=True, exist_ok=True)
        ocr_path.write_text(json.dumps(ocr, ensure_ascii=False), encoding="utf-8")
    pattern = read_patterns(ocr)
    layout: dict[str, Any] = {}
    layout_error = ""
    try:
        layout = read_layoutlm(normalized_path, ocr)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        layout_error = str(exc)
        LOG.warning("Layout reader unavailable for %s: %s", source, exc)
    reader_a = {**pattern, **{key: value for key, value in layout.items()
                            if key not in ("confidence", "boxes")}}
    reader_a["confidence"] = {**pattern.get("confidence", {}), **layout.get("confidence", {})}
    reader_a["boxes"] = {**pattern.get("boxes", {}), **layout.get("boxes", {})}
    model: dict[str, Any] = {}
    model_error = ""
    try:
        model = read_model("\n".join(line["text"] for line in reading_rows(ocr.get("lines") or [])), digest, target / "llm_cache")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        model_error = str(exc)
        LOG.warning("Text model unavailable for %s: %s", source, exc)

    text_rules = infer_fields(ocr, reader_a)
    extraction: dict[str, Any] = {field: "" for field in STRING_FIELDS}
    extraction.update({"line_items": [], "guest_count": 0,
                       "confidence": {}, "boxes": {}, "readers": {"reader_a": reader_a,
                                                                   "reader_b": model,
                                                                   "text_rules": text_rules}})
    if layout:
        extraction["readers"]["reader_a_pattern"] = pattern
        extraction["readers"]["reader_a_layoutlm"] = layout
    if layout_error:
        extraction["readers"]["reader_a_layoutlm_error"] = {"message": layout_error}
    for field in STRING_FIELDS:
        value = reader_a.get(field) or model.get(field) or text_rules.get(field)
        if value is not None:
            extraction[field] = str(value)
    extraction["line_items"] = (model.get("line_items") or text_rules.get("line_items")
                                or reader_a.get("line_items", []))
    extraction["guest_count"] = (model.get("guest_count") or text_rules.get("guest_count")
                                 or reader_a.get("guest_count", 0))
    extraction["confidence"] = reader_a.get("confidence", {})
    extraction["boxes"] = reader_a.get("boxes", {})
    if model_error:
        extraction["readers"]["reader_b_error"] = {"message": model_error}
    disagreement = []
    for field in ("total", "transaction_date"):
        if reader_a.get(field) and model.get(field) and str(reader_a[field]) != str(model[field]):
            disagreement.append(field)
            extraction["confidence"][field] = min(extraction["confidence"].get(field, 1.0), 0.49)

    rates = load_rates()
    validation = validate_extraction(extraction)
    if disagreement:
        for field in disagreement:
            validation["checks"].append({"name": f"reader_disagreement_{field}",
                                          "expected": str(reader_a[field]),
                                          "printed": str(model[field]), "passed": False})
    fx = convert_total(extraction["total"], extraction["currency"], rates)
    line_count = len(ocr.get("lines") or [])
    is_receipt = line_count > 0 and bool(extraction["merchant_name"] or extraction["total"])
    status = "UNREADABLE" if not line_count else ("OK" if extraction["total"] and not model_error else "PARTIAL")
    result: ProcessedReceipt = {
        "receipt_id": str(submission.get("receipt_id") or submission.get("scenario_id") or source.stem),
        "file_sha256": digest,
        "ocr_text": ocr.get("full_text", ""),
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
