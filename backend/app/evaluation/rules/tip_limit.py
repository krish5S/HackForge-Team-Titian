from decimal import Decimal, ROUND_HALF_UP
from ...contracts.policy import parse_money
from ..explain import reason


def evaluate(rule, ex, rate, proposed, eligible_share):
    if eligible_share is None:
        return proposed, []
    try:
        tip = parse_money(ex.get("tip", "0.00")) * eligible_share * rate
        cap = (
            parse_money(ex.get("subtotal"))
            * eligible_share
            * rate
            * rule.parameters.fraction
        )
        excess = max(Decimal("0"), tip - cap).quantize(
            Decimal(".01"), rounding=ROUND_HALF_UP
        )
    except (ValueError, ArithmeticError):
        return proposed, [
            reason(
                rule,
                "TIP_AMOUNTS",
                "REVIEW",
                "Subtotal and tip are needed to verify the tip limit.",
            )
        ]
    if excess:
        return max(Decimal("0"), proposed - excess), [
            reason(
                rule,
                "TIP_LIMIT",
                "CAP",
                f"Tip exceeds the allowed share by {excess:.2f}.",
            )
        ]
    return proposed, []
