from decimal import Decimal
from ..contracts.policy import CompiledPolicy

REQUIRED = {
    "MONTHLY_CAP": {"amount"},
    "CITY_DAILY_CAP": {"cities"},
    "LOCAL_MEAL": set(),
    "EXCLUDE_ITEMS": {"item_classes"},
    "CLIENT_DETAILS": set(),
    "APPROVAL_THRESHOLD": {"amount"},
    "ITEMIZATION": {"amount"},
    "TIP_LIMIT": {"fraction"},
    "SUBMISSION_DEADLINE": {"days"},
    "EVIDENCE_REVIEW": {"risk_threshold"},
}


def validate_rules(policy: CompiledPolicy) -> CompiledPolicy:
    clauses = {c.clause_id: c.text for c in policy.clauses}
    if len(clauses) != len(policy.clauses):
        raise ValueError("Duplicate clause IDs")
    seen = set()
    for rule in policy.rules:
        if (
            rule.clause_id not in clauses
            or rule.source_quote not in clauses[rule.clause_id]
        ):
            raise ValueError(f"Ungrounded rule: {rule.clause_id}")
        values = rule.parameters.model_dump(exclude_none=True)
        if set(values) != REQUIRED[rule.rule_type]:
            raise ValueError(
                f"{rule.rule_type}: expected parameters {REQUIRED[rule.rule_type]}"
            )
        if "amount" in values and values["amount"] <= 0:
            raise ValueError("Limit must be positive")
        if "cities" in values and (
            "DEFAULT" not in values["cities"]
            or any(v <= 0 for v in values["cities"].values())
        ):
            raise ValueError("City table needs DEFAULT and positive amounts")
        if "fraction" in values and not Decimal("0") <= values["fraction"] <= Decimal(
            "1"
        ):
            raise ValueError("Fraction must be between zero and one")
        if "item_classes" in values and (
            not values["item_classes"] or set(values["item_classes"]) - {"ALCOHOL"}
        ):
            raise ValueError("Unsupported excluded item class")
        key = (rule.rule_type, rule.category)
        if key in seen:
            raise ValueError("Conflicting or repeated same-scope rule")
        seen.add(key)
    return policy
