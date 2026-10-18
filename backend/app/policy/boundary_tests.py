"""Exercise the actual decision engine at each monetary boundary using synthetic inputs."""

from decimal import Decimal
from ..contracts.policy import CheckResult, CompilerFlag


def run_boundaries(policy):
    from ..evaluation import evaluate_month

    checked = 0
    failures = []
    for rule in policy.rules:
        cases = []
        if rule.rule_type in {"MONTHLY_CAP", "APPROVAL_THRESHOLD", "ITEMIZATION"}:
            cases = [(rule.parameters.amount, None)]
        elif rule.rule_type == "CITY_DAILY_CAP":
            cases = list(
                (amount, city) for city, amount in rule.parameters.cities.items()
            )
        elif rule.rule_type == "TIP_LIMIT":
            cases = [(Decimal("100") * rule.parameters.fraction, None)]
        for limit, city in cases:
            for delta in (Decimal("-.01"), Decimal("0"), Decimal(".01")):
                value = limit + delta
                if value < 0:
                    continue
                tip_test = rule.rule_type == "TIP_LIMIT"
                total = Decimal("100") + value if tip_test else value
                ex = dict(
                    total=f"{total:.2f}",
                    subtotal="100.00" if tip_test else f"{value:.2f}",
                    tip=f"{value:.2f}" if tip_test else "0.00",
                    currency=policy.base_currency,
                    city=city if city != "DEFAULT" else "Unlisted city",
                    transaction_date="2026-09-01",
                    transaction_time="12:00:00",
                    category=rule.category if rule.category != "ALL" else "TRAVEL",
                    itemization="NONE",
                    line_items=[],
                )
                isolated = policy.model_copy(update={"rules": [rule]})
                inp = dict(
                    policy=isolated,
                    receipts=[
                        dict(
                            receipt_id="boundary",
                            is_receipt=True,
                            extraction_status="OK",
                            extraction=ex,
                        )
                    ],
                    employees=[
                        dict(
                            id="test",
                            name="Synthetic boundary fixture",
                            home_city="Home",
                        )
                    ],
                    candidates=[],
                    submissions=[
                        dict(
                            receipt_id="boundary",
                            employee_id="test",
                            submitted_at="2026-09-02T00:00:00+00:00",
                            channel="upload",
                        )
                    ],
                    period=dict(start="2026-09-01", end="2026-09-30"),
                )
                checked += 1
                try:
                    result = evaluate_month(inp).decisions[0]
                    if rule.rule_type in {"APPROVAL_THRESHOLD", "ITEMIZATION"}:
                        expected = "NEEDS_REVIEW" if delta > 0 else "APPROVE"
                        good = result.verdict == expected and result.proposed == total
                    else:
                        allowed = min(value, limit) + (
                            Decimal("100") if tip_test else 0
                        )
                        good = (
                            result.verdict == "APPROVE" and result.proposed == allowed
                        )
                    if not good:
                        raise ValueError("Boundary outcome mismatch")
                except (ValueError, ArithmeticError, TypeError) as exc:
                    failures.append(
                        CompilerFlag(
                            code="TEST_FAILED",
                            clause_id=rule.clause_id,
                            message=f"{rule.rule_type} at {value:.2f}: {exc}",
                        )
                    )
    return CheckResult(
        status="FAILED" if failures else "PASSED" if checked else "NOT_RUN",
        checked=checked,
        failed=len(failures),
        detail="Actual engine on synthetic under/at/over inputs; nonmonetary rules excluded.",
    ), failures
