from decimal import Decimal
from ..contracts.decision import Decision


def decide(
    receipt_id,
    claimed,
    proposed,
    reasons,
    risk_score=0,
    ledger_refs=None,
    duplicate_of=None,
):
    effects = {r.effect for r in reasons}
    verdict = (
        "REJECT"
        if "REJECT" in effects
        else "NEEDS_REVIEW"
        if "REVIEW" in effects
        else "APPROVE"
    )
    reimbursable = (
        Decimal("0")
        if verdict == "REJECT"
        else None
        if verdict == "NEEDS_REVIEW"
        else proposed
    )
    at_risk = (
        claimed
        if verdict == "REJECT"
        else proposed
        if verdict == "NEEDS_REVIEW"
        else claimed - proposed
    )
    return Decision(
        receipt_id=receipt_id,
        verdict=verdict,
        claimed=claimed,
        proposed=proposed,
        reimbursable=reimbursable,
        amount_at_risk=at_risk,
        risk_score=risk_score,
        reasons=reasons,
        counterfactuals=[],
        ledger_refs=ledger_refs or [],
        duplicate_of=duplicate_of,
    )
