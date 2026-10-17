from ..contracts.decision import DecisionReason


def reason(rule, code, effect, text):
    return DecisionReason(
        code=code,
        effect=effect,
        clause_id=rule.clause_id,
        message=f"?{rule.clause_id}: {text}",
    )
