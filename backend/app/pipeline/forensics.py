"""Evidence score for receipt anomalies. An untrained CNN contributes zero."""

from decimal import Decimal, InvalidOperation
from typing import Any


def score_receipt(receipt: dict[str, Any], cnn_probability: float | None = None,
                  cnn_enabled: bool = False) -> dict[str, Any]:
    score = 0
    signals: list[str] = []
    checks = receipt.get("validation", {}).get("checks", [])
    for check in checks:
        if not check.get("passed") and check.get("name") in ("components_vs_total", "items_vs_subtotal"):
            score += 25
            signals.append(check["name"])
    confidence = receipt.get("extraction", {}).get("confidence", {})
    amount_confidences = [confidence[field] for field in ("total", "subtotal", "tax")
                          if field in confidence]
    if amount_confidences and min(amount_confidences) < 0.6:
        score += 15
        signals.append("low_amount_ocr_confidence")
    total = receipt.get("extraction", {}).get("total", "")
    try:
        if total and Decimal(str(total)) % 10 == 0:
            score += 10
            signals.append("round_total")
    except InvalidOperation:
        pass
    probability = min(1.0, max(0.0, float(cnn_probability or 0.0))) if cnn_enabled else 0.0
    if cnn_enabled:
        score += round(probability * 30)
        signals.append("cnn_fake_probability")
    return {"score": min(100, score), "cnn_fake_probability": probability, "signals": signals}
