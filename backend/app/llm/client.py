"""Optional text-only receipt reader. The endpoint accepts OCR text as JSON."""

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def extract_receipt_fields(ocr_text: str, file_sha256: str, cache_dir: Path) -> dict[str, Any]:
    """Cache model JSON by source-file hash; never send the image to the endpoint."""
    cache_path = cache_dir / f"{file_sha256}.json"
    if cache_path.is_file():
        result = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(result, dict):
            return result
        raise ValueError(f"Invalid cached model response: {cache_path}")

    endpoint = os.environ.get("RECEIPT_LLM_ENDPOINT")
    if not endpoint:
        return {}
    request_body = json.dumps({
        "task": "Extract receipt fields as JSON. Use only supplied OCR text; return null for unknown fields.",
        "ocr_text": ocr_text,
        "fields": ["category", "line_items", "city", "country", "guest_count",
                   "total", "transaction_date", "itemization"],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("RECEIPT_LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['RECEIPT_LLM_API_KEY']}"
    request = Request(endpoint, data=request_body, headers=headers, method="POST")
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Receipt model must return a JSON object")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
