from ..explain import reason


def evaluate(rule, receipt, amount_valid):
    hits = []
    if (
        receipt.get("is_receipt") is not True
        or receipt.get("extraction_status") != "OK"
    ):
        hits.append(
            reason(rule, "UNREADABLE", "REVIEW", "A readable receipt is required.")
        )
    if not amount_valid:
        hits.append(
            reason(
                rule,
                "MISSING_AMOUNT_OR_FX",
                "REVIEW",
                "A valid total and matching FX conversion are required.",
            )
        )
    if (receipt.get("extraction") or {}).get("category") not in {
        "MEALS",
        "ENTERTAINMENT",
        "TRAVEL",
        "LODGING",
        "OFFICE",
    }:
        hits.append(
            reason(
                rule,
                "UNKNOWN_CATEGORY",
                "REVIEW",
                "A known expense category is required.",
            )
        )
    checks = (receipt.get("validation") or {}).get("checks", [])
    if (
        any(c.get("passed") is False for c in checks)
        or (receipt.get("forensics") or {}).get("score", 0)
        >= rule.parameters.risk_threshold
    ):
        hits.append(
            reason(
                rule,
                "SUSPICIOUS",
                "REVIEW",
                "Receipt arithmetic or forensic evidence needs review.",
            )
        )
    return hits
