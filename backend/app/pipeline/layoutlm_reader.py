"""Use the trained LayoutLM tagger only after month-level switch approval."""

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image

from backend.app.pipeline.reader_a import DATE, TIME, _amount, _box

_MODEL = None
_PROCESSOR = None
_DEVICE = None


def read_fields(image_path: str | Path, ocr: dict[str, Any]) -> dict[str, Any]:
    global _MODEL, _PROCESSOR, _DEVICE
    repository = Path(__file__).resolve().parents[3]
    metrics_path = Path(os.environ.get("RECEIPT_LAYOUTLM_METRICS",
                               str(repository / "data" / "models" / "layoutlm_metrics.json")))
    checkpoint = Path(os.environ.get("RECEIPT_LAYOUTLM_MODEL",
                          str(Path.home() / "datasets" / "layoutlm_artifacts" / "best")))
    if not metrics_path.is_file() or not checkpoint.is_dir():
        return {}
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if not metrics.get("model_switch_enabled"):
        return {}

    import torch
    from transformers import AutoProcessor, LayoutLMv3ForTokenClassification

    if _MODEL is None:
        _DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _PROCESSOR = AutoProcessor.from_pretrained(checkpoint, apply_ocr=False)
        _MODEL = LayoutLMv3ForTokenClassification.from_pretrained(checkpoint).to(_DEVICE).eval()
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        width, height = image.size
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
    if not words:
        return {}
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
                            "%m-%d-%Y", "%d-%m-%Y", "%m/%d/%y"):
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
    return result
