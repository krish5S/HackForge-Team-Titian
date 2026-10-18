from decimal import Decimal, ROUND_HALF_UP
from ...contracts.policy import parse_money
from ..explain import reason


def evaluate(rule, ex, rate, proposed):
    items = ex.get("line_items") or []
    excluded = [i for i in items if i.get("item_class") in rule.parameters.item_classes]
    if not excluded:
        return proposed, Decimal("1"), []
    try:
        subtotal = parse_money(ex.get("subtotal"))
        amounts = [parse_money(i.get("amount")) for i in items]
        if not subtotal or sum(amounts) != subtotal:
            raise ValueError("Inconsistent subtotal")
        disallowed = sum(parse_money(i.get("amount")) for i in excluded)
        share = disallowed / subtotal
        charges = sum(
            parse_money(ex.get(k, "0.00")) for k in ("tax", "tip", "other_charges")
        )
        removed = ((disallowed + charges * share) * rate).quantize(
            Decimal(".01"), rounding=ROUND_HALF_UP
        )
        return (
            max(Decimal("0"), proposed - removed),
            1 - share,
            [
                reason(
                    rule,
                    "EXCLUDED_ITEM",
                    "EXCLUDE",
                    f"Excluded items plus allocated tax/tip/charges: {removed:.2f}; share {share:.6f}.",
                )
            ],
        )
    except (ValueError, ArithmeticError):
        return (
            proposed,
            None,
            [
                reason(
                    rule,
                    "ITEM_AMOUNTS",
                    "REVIEW",
                    "Item amounts cannot support an auditable exclusion.",
                )
            ],
        )
