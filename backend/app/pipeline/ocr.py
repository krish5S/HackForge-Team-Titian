
"""
PaddleOCR receipt text extraction.
Returns recognized text, bounding boxes, and confidence scores.
"""

from pathlib import Path
from typing import Any

import numpy as np
from paddleocr import PaddleOCR

# Initialize once and reuse the model between receipts.
_ocr_engine = None


def get_ocr_engine():
    global _ocr_engine

    if _ocr_engine is None:
        _ocr_engine = PaddleOCR(
            lang="en",
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    return _ocr_engine


def extract_text(image_path: str | Path) -> dict[str, Any]:
    """Run OCR on an image and return text, boxes, and confidence."""
    path = Path(image_path)

    if not path.is_file():
        raise FileNotFoundError(f"Receipt image not found: {path}")

    engine = get_ocr_engine()
    results = engine.predict(input=str(path))

    lines = []

    for result in results:
        data = result.json
        if callable(data):
            data = data()

        # PaddleOCR 3.x returns structured results in this format.
        payload = data.get("res", data) if isinstance(data, dict) else {}

        texts = payload.get("rec_texts", [])
        scores = payload.get("rec_scores", [])
        boxes = payload.get("rec_polys", payload.get("dt_polys", []))

        for index, text in enumerate(texts):
            score = float(scores[index]) if index < len(scores) else 0.0
            box = boxes[index].tolist() if hasattr(boxes[index], "tolist") else boxes[index]

            lines.append(
                {
                    "text": str(text),
                    "confidence": score,
                    "box": box,
                }
            )

    return {
        "image_path": str(path.resolve()),
        "line_count": len(lines),
        "lines": lines,
        "full_text": "\n".join(line["text"] for line in lines),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Extract receipt text with PaddleOCR.")
    parser.add_argument("image", help="Path to receipt image")
    parser.add_argument(
        "--output",
        help="Optional JSON output path",
        default=None,
    )
    args = parser.parse_args()

    output = extract_text(args.image)
    rendered = json.dumps(output, indent=2, ensure_ascii=False)
    print(rendered)

    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        print(f"\nOCR result saved to: {destination.resolve()}")
