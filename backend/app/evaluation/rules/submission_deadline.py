from ..explain import reason


def evaluate(rule, ctx, ex, claimed):
    if ctx["day"] is None:
        return [
            reason(
                rule,
                "MISSING_DATE",
                "REVIEW",
                "Transaction date is missing or invalid.",
            )
        ]
    elapsed = (ctx["submission"].submitted_at.date() - ctx["day"]).days
    if elapsed < 0 or elapsed > rule.parameters.days:
        return [
            reason(
                rule,
                "SUBMISSION_DATE",
                "REVIEW",
                f"Submission interval {elapsed} days; allowed 0?{rule.parameters.days}.",
            )
        ]
    return []
