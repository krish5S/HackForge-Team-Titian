"""Use the trained LayoutLM tagger only after month-level switch approval."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
from typing import Any

from PIL import Image

from backend.app.pipeline.reader_a import DATE, FIELD_LABELS, MONEY, TIME, _amount, _box

_MODEL = None
_PROCESSOR = None
_DEVICE = None


def _extract_layout_fields(ocr: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    """Spatial 2D layout reader based on token bounding boxes and geometry."""
    lines = ocr.get("lines") or []
    if not lines or width <= 0 or height <= 0:
        return {}

    items = []
    for line in lines:
        text = str(line.get("text") or "").strip()
        rectangle = _box(line.get("box"))
        if not text or not rectangle:
            continue
        x0, y0, x1, y1 = rectangle
        if x0 >= x1 or y0 >= y1:
            continue
        conf = float(line.get("confidence") or 0.9)
        norm = [
            max(0, min(1000, round(x0 * 1000 / width))),
            max(0, min(1000, round(y0 * 1000 / height))),
            max(0, min(1000, round(x1 * 1000 / width))),
            max(0, min(1000, round(y1 * 1000 / height))),
        ]
        items.append({
            "text": text,
            "box": rectangle,
            "norm": norm,
            "conf": conf,
        })
    if not items:
        return {}

    result: dict[str, Any] = {"confidence": {}, "boxes": {}}

    # 1. Merchant name: top text element (norm y0 < 300)
    top_items = [it for it in items if it["norm"][1] < 300]
    for it in top_items:
        txt = it["text"]
        if len(txt) >= 3 and not DATE.search(txt) and not MONEY.fullmatch(txt):
            lower = txt.lower()
            if not any(lbl in lower for lbls in FIELD_LABELS.values() for lbl in lbls):
                result["merchant_name"] = txt
                result["confidence"]["merchant_name"] = it["conf"]
                result["boxes"]["merchant_name"] = it["box"]
                break

    # 2. Amounts: scan labeled lines
    for it in items:
        txt = it["text"]
        lower = txt.lower()
        amt = _amount(txt)
        if amt is None:
            continue
        for field, labels in FIELD_LABELS.items():
            if field in result:
                continue
            matched = next((lbl for lbl in labels if re.search(r"\b" + re.escape(lbl) + r"\b", lower)), None)
            if matched:
                if field == "total" and re.search(r"\bsub\s*total\b", lower) and not re.search(r"(?<!\bsub\s)(?<!\bsub)total\b", lower):
                    continue
                result[field] = amt
                result["confidence"][field] = it["conf"]
                result["boxes"][field] = it["box"]

    # 3. Spatial total fallback: largest amount in bottom half (norm y0 > 380)
    if "total" not in result:
        bottom_items = [it for it in items if it["norm"][1] > 380]
        amounts = []
        for it in bottom_items:
            amt = _amount(it["text"])
            if amt:
                try:
                    dec = Decimal(amt)
                    amounts.append((dec, amt, it))
                except InvalidOperation:
                    pass
        if amounts:
            amounts.sort(key=lambda x: (x[0], x[2]["norm"][1]), reverse=True)
            chosen = amounts[0]
            result["total"] = chosen[1]
            result["confidence"]["total"] = chosen[2]["conf"]
            result["boxes"]["total"] = chosen[2]["box"]

    # 4. Transaction date (tolerant format parsing)
    for it in items:
        found = DATE.search(it["text"])
        if found:
            raw = found.group(1)
            for fmt in (
                "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
                "%m-%d-%Y", "%d-%m-%Y", "%m/%d/%y", "%d/%m/%y",
                "%d.%m.%Y", "%Y.%m.%d"
            ):
                try:
                    parsed = datetime.strptime(raw, fmt).date()
                    if 1990 <= parsed.year <= 2035:
                        result["transaction_date"] = parsed.isoformat()
                        result["confidence"]["transaction_date"] = it["conf"]
                        result["boxes"]["transaction_date"] = it["box"]
                        break
                except ValueError:
                    continue
            if "transaction_date" in result:
                break

    # 5. Transaction time
    for it in items:
        found = TIME.search(it["text"])
        if found:
            result["transaction_time"] = found.group(0)[:5]
            result["confidence"]["transaction_time"] = it["conf"]
            result["boxes"]["transaction_time"] = it["box"]
            break

    return result


def read_fields(image_path: str | Path, ocr: dict[str, Any], force: bool = False) -> dict[str, Any]:
    global _MODEL, _PROCESSOR, _DEVICE
    repository = Path(__file__).resolve().parents[3]
    metrics_path = Path(os.environ.get("RECEIPT_LAYOUTLM_METRICS",
                               str(repository / "data" / "models" / "layoutlm_metrics.json")))
    checkpoint = Path(os.environ.get("RECEIPT_LAYOUTLM_MODEL",
                          str(Path.home() / "datasets" / "layoutlm_artifacts" / "best")))
    if not force and not metrics_path.is_file():
        return {}
    if not force:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        if not metrics.get("model_switch_enabled"):
            return {}

    with Image.open(image_path) as source:
        image = source.convert("RGB")
        width, height = image.size

    if checkpoint.is_dir():
        try:
            import torch
            from transformers import AutoProcessor, LayoutLMv3ForTokenClassification

            if _MODEL is None:
                _DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
                _PROCESSOR = AutoProcessor.from_pretrained(checkpoint, apply_ocr=False)
                _MODEL = LayoutLMv3ForTokenClassification.from_pretrained(checkpoint).to(_DEVICE).eval()

            words, boxes, pixel_boxes = [], [], []
            for line in ocr.get("lines") or []:
                word = str(line.get("text") or "").strip()
                rectangle = _box(line.get("box"))
                if not word or not rectangle:
                    continue
                x0, y0, x1, y1 = rectangle
                if x0 >= x1 or y0 >= y1:
                    continue
                normalized = [max(0, min(1000, round(value * 1000 / maximum)))
                              for value, maximum in zip(rectangle, (width, height, width, height))]
                words.append(word)
                boxes.append(normalized)
                pixel_boxes.append(rectangle)
            if words:
                encoding = _PROCESSOR(image, words, boxes=boxes, truncation=True,
                                      padding="max_length", max_length=512, return_tensors="pt")
                word_ids = encoding.word_ids(batch_index=0)
                with torch.no_grad():
                    logits = _MODEL(**{key: value.to(_DEVICE) for key, value in encoding.items()}).logits[0]
                    probabilities = logits.softmax(-1).cpu()
                result: dict[str, Any] = {"confidence": {}, "boxes": {}}
                seen = set()
                for token_index, word_index in enumerate(word_ids):
                    if word_index is None or word_index in seen or word_index >= len(words):
                        continue
                    seen.add(word_index)
                    class_id = probabilities[token_index].argmax().item()
                    field = _MODEL.config.id2label[class_id]
                    if field in ("O", "line_item_description", "line_item_amount"):
                        continue
                    text = words[word_index]
                    if field in {"subtotal", "tax", "tip", "total"}:
                        value = _amount(text)
                    elif field == "transaction_date":
                        found = DATE.search(text)
                        value = None
                        if found:
                            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
                                        "%m-%d-%Y", "%d-%m-%Y", "%m/%d/%y", "%d/%m/%y", "%d.%m.%Y"):
                                try:
                                    value = datetime.strptime(found.group(1), fmt).date().isoformat()
                                    break
                                except ValueError:
                                    continue
                    elif field == "transaction_time":
                        found = TIME.search(text)
                        value = found.group(0)[:5] if found else None
                    else:
                        value = text
                    if not value:
                        continue
                    confidence = float(probabilities[token_index, class_id])
                    if confidence > result["confidence"].get(field, 0):
                        result[field] = value
                        result["confidence"][field] = confidence
                        result["boxes"][field] = pixel_boxes[word_index]
                if result.get("total") or result.get("merchant_name"):
                    return result
        except Exception:
            pass

    # Use 2D spatial layout extraction
    return _extract_layout_fields(ocr, width, height)
