"""Validate fields returned by the optional text-only model."""

from typing import Any

from backend.app.llm.client import extract_receipt_fields


def read_fields(ocr_text: str, file_sha256: str, cache_dir) -> dict[str, Any]:
    raw = extract_receipt_fields(ocr_text, file_sha256, cache_dir)
    if not raw:
        return {}
    result: dict[str, Any] = {}
    for field in ("merchant_name", "receipt_number", "currency", "subtotal", "tax", "tip", "other_charges", "category", "city", "country", "total", "transaction_date", "itemization"):
        value = raw.get(field)
        if value is not None and isinstance(value, (str, int, float)):
            result[field] = str(value).strip().upper() if field in ("category", "itemization") else str(value).strip()
    count = raw.get("guest_count")
    if count is not None:
        try:
            result["guest_count"] = max(0, int(count))
        except (TypeError, ValueError):
            pass
    items = raw.get("line_items")
    if isinstance(items, list):
        result["line_items"] = [
            {"description": str(item.get("description") or ""),
             "amount": str(item.get("amount") or ""),
             "item_class": str(item.get("item_class") or "OTHER").upper()}
            for item in items if isinstance(item, dict)
        ]
    return result
