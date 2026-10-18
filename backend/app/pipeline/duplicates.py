"""Candidate duplicate matching with explicit non-match guards."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

import imagehash
from rapidfuzz.fuzz import ratio


def _base_total(receipt: dict[str, Any]) -> Decimal | None:
    value = receipt.get("fx", {}).get("total_base")
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _time_gap_minutes(a: str, b: str) -> float | None:
    if not a or not b:
        return None
    try:
        first = datetime.strptime(a[:5], "%H:%M")
        second = datetime.strptime(b[:5], "%H:%M")
        return abs((first - second).total_seconds()) / 60
    except ValueError:
        return None


def _identical_image(first: dict[str, Any], second: dict[str, Any]) -> bool:
    phash_a = first.get("fingerprints", {}).get("phash")
    phash_b = second.get("fingerprints", {}).get("phash")
    try:
        return bool(phash_a and phash_b and
                    imagehash.hex_to_hash(phash_a) - imagehash.hex_to_hash(phash_b) <= 2)
    except ValueError:
        return False


def find_duplicates(receipts: list[dict[str, Any]],
                    ocr_texts: dict[str, str] | None = None) -> list[dict[str, Any]]:
    ocr_texts = ocr_texts or {}
    candidates = []
    for index, first in enumerate(receipts):
        for second in receipts[index + 1:]:
            a, b = first.get("extraction", {}), second.get("extraction", {})
            exact = bool(first.get("file_sha256") and
                         first["file_sha256"] == second.get("file_sha256"))
            if exact:
                candidates.append({"receipt_id": second["receipt_id"],
                                   "duplicate_of": first["receipt_id"], "reason": "exact_file"})
                continue
            if a.get("receipt_number") and b.get("receipt_number") and a["receipt_number"] != b["receipt_number"]:
                continue
            if a.get("card_last4") and b.get("card_last4") and a["card_last4"] != b["card_last4"]:
                continue
            gap = _time_gap_minutes(a.get("transaction_time", ""), b.get("transaction_time", ""))
            if gap is not None and gap > 5:
                continue
            phash_a = first.get("fingerprints", {}).get("phash")
            phash_b = second.get("fingerprints", {}).get("phash")
            distance = None
            if phash_a and phash_b:
                try:
                    distance = imagehash.hex_to_hash(phash_a) - imagehash.hex_to_hash(phash_b)
                except ValueError:
                    pass
            text_a = ocr_texts.get(first["receipt_id"], "")
            text_b = ocr_texts.get(second["receipt_id"], "")
            # OCR may misread the merchant on a photographed copy. Require both
            # substantial text agreement and a close image before bypassing it.
            if (distance is not None and distance <= 16 and
                    len(text_a) >= 75 and len(text_b) >= 75 and
                    ratio(text_a, text_b) >= 92 and
                    (not a.get("transaction_date") or not b.get("transaction_date") or
                     a["transaction_date"] == b["transaction_date"])):
                total_a, total_b = _base_total(first), _base_total(second)
                if (total_a is None or total_b is None or
                        abs(total_a - total_b) <= max(total_a, total_b, Decimal("1")) * Decimal("0.01")):
                    candidates.append({"receipt_id": second["receipt_id"],
                                       "duplicate_of": first["receipt_id"],
                                       "reason": "similar_text_image"})
                    continue
            left = first.get("fingerprints", {}).get("merchant_norm", "")
            right = second.get("fingerprints", {}).get("merchant_norm", "")
            if set(re.findall(r"\b\d+\b", left)) != set(re.findall(r"\b\d+\b", right)):
                continue
            if left and right:
                if ratio(left, right) < 90:
                    continue
            elif (not _identical_image(first, second) or
                  ((text_a or text_b) and
                   (len(text_a) < 40 or len(text_b) < 40 or ratio(text_a, text_b) < 80))):
                # An unreadable merchant only passes when the image itself is
                # an almost exact copy and OCR contains substantial shared text.
                continue
            total_a, total_b = _base_total(first), _base_total(second)
            same_transaction = (a.get("transaction_date") and
                                a.get("transaction_date") == b.get("transaction_date") and
                                total_a is not None and total_b is not None and
                                abs(total_a - total_b) <= max(total_a, total_b, Decimal("1")) * Decimal("0.01"))
            near_image = distance is not None and distance <= 12
            if same_transaction or near_image:
                candidates.append({"receipt_id": second["receipt_id"],
                                   "duplicate_of": first["receipt_id"],
                                   "reason": "transaction" if same_transaction else "similar_image"})
    return candidates
