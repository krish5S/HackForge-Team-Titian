"""Receipt arithmetic and basic field sanity checks."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


def _money(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def validate_extraction(extraction: dict[str, Any]) -> dict[str, list[dict]]:
    checks: list[dict] = []
    total = _money(extraction.get("total"))
    if total is None:
        checks.append({"name": "total_present", "expected": "amount", "printed": "",
                       "passed": False})
    elif total < 0:
        checks.append({"name": "nonnegative_total", "expected": ">= 0",
                       "printed": str(total), "passed": False})
    else:
        checks.append({"name": "nonnegative_total", "expected": ">= 0",
                       "printed": str(total), "passed": True})
    subtotal = _money(extraction.get("subtotal"))
    extras = [_money(extraction.get(field)) for field in ("tax", "tip", "other_charges")]
    if subtotal is not None and total is not None and any(item is not None for item in extras):
        expected = subtotal + sum((item or Decimal("0") for item in extras), Decimal("0"))
        checks.append({"name": "components_vs_total", "expected": f"{expected:.2f}",
                       "printed": f"{total:.2f}", "passed": abs(expected - total) <= Decimal("0.01")})
    items = extraction.get("line_items") or []
    item_amounts = [_money(item.get("amount")) for item in items]
    if items and subtotal is not None and all(amount is not None for amount in item_amounts):
        expected = sum(item_amounts, Decimal("0"))
        checks.append({"name": "items_vs_subtotal", "expected": f"{expected:.2f}",
                       "printed": f"{subtotal:.2f}", "passed": abs(expected - subtotal) <= Decimal("0.01")})
    raw_date = extraction.get("transaction_date")
    if raw_date:
        try:
            date.fromisoformat(str(raw_date))
            valid_date = True
        except ValueError:
            valid_date = False
        checks.append({"name": "date_format", "expected": "YYYY-MM-DD",
                       "printed": str(raw_date), "passed": valid_date})
    return {"checks": checks}
