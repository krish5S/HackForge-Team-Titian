from ..explain import reason


def evaluate(rule, ctx, ex, claimed):
    if ctx["trip"] is None or (not ctx["trip"] and not ctx["submission"].client_meal):
        return [
            reason(
                rule,
                "LOCAL_MEAL_REVIEW",
                "REVIEW",
                "Local meal or unknown travel context requires review.",
            )
        ]
    return []
