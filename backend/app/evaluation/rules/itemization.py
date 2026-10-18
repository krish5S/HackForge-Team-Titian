from ..explain import reason


def evaluate(rule, ctx, ex, claimed):
    if claimed > rule.parameters.amount and ex.get("itemization") != "FULL":
        return [
            reason(
                rule,
                "MISSING_ITEMIZATION",
                "REVIEW",
                f"Claims above {rule.parameters.amount:.2f} need full itemization.",
            )
        ]
    return []
