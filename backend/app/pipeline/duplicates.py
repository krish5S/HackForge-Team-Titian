"""Candidate duplicate matching with explicit non-match guards."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
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


def find_duplicates(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
            left = first.get("fingerprints", {}).get("merchant_norm", "")
            right = second.get("fingerprints", {}).get("merchant_norm", "")
            if not left or not right or ratio(left, right) < 90:
                continue
            total_a, total_b = _base_total(first), _base_total(second)
            same_transaction = (a.get("transaction_date") and
                                a.get("transaction_date") == b.get("transaction_date") and
                                total_a is not None and total_b is not None and
                                abs(total_a - total_b) <= max(total_a, total_b, Decimal("1")) * Decimal("0.01"))
            phash_a = first.get("fingerprints", {}).get("phash")
            phash_b = second.get("fingerprints", {}).get("phash")
            near_image = False
            if phash_a and phash_b:
                try:
                    near_image = imagehash.hex_to_hash(phash_a) - imagehash.hex_to_hash(phash_b) <= 12
                except ValueError:
                    pass
            if same_transaction or near_image:
                candidates.append({"receipt_id": second["receipt_id"],
                                   "duplicate_of": first["receipt_id"],
                                   "reason": "transaction" if same_transaction else "similar_image"})
    return candidates
