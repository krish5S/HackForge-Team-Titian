from ..explain import reason


def evaluate(rule, ctx, ex, claimed):
    if claimed > rule.parameters.amount and not ctx["submission"].approved:
        return [
            reason(
                rule,
                "APPROVAL_REQUIRED",
                "REVIEW",
                f"Claim {claimed:.2f} exceeds approval threshold {rule.parameters.amount:.2f}.",
            )
        ]
    return []
