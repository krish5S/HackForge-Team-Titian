"""Pure evaluation. No database, network, model or wall-clock dependency."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from ..contracts.decision import EvaluationInput, EvaluationResult
from ..contracts.policy import parse_money
from ..policy.validate_rules import validate_rules
from .context import context
from .decide import decide
from .rules import (
    local_meal,
    client_details,
    approval_threshold,
    itemization,
    submission_deadline,
    evidence_review,
    exclude_items,
    tip_limit,
)

CHECKS = {
    "LOCAL_MEAL": local_meal,
    "CLIENT_DETAILS": client_details,
    "APPROVAL_THRESHOLD": approval_threshold,
    "ITEMIZATION": itemization,
    "SUBMISSION_DEADLINE": submission_deadline,
}


def evaluate_month(
    inp: EvaluationInput | dict, as_of: datetime | str | None = None
) -> EvaluationResult:
    return _evaluate(inp, as_of, counterfactuals=True)


def _evaluate(inp, as_of=None, counterfactuals=False):
    inp = EvaluationInput.model_validate(inp)
    validate_rules(inp.policy)
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)
    if as_of is not None and as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    employees = {e.id: e for e in inp.employees}
    if len(employees) != len(inp.employees):
        raise ValueError("Employee IDs must be unique")
    if any(s.employee_id not in employees for s in inp.submissions):
        raise ValueError("Every submission must reference a supplied employee")
    receipts = {r["receipt_id"]: r for r in inp.receipts}
    if len(receipts) != len(inp.receipts) or len(
        {s.receipt_id for s in inp.submissions}
    ) != len(inp.submissions):
        raise ValueError("Receipt and submission IDs must be unique")
    decisions = []
    for sub in sorted(inp.submissions, key=lambda s: (s.submitted_at, s.receipt_id)):
        if as_of is not None and sub.submitted_at > as_of:
            continue
        if sub.receipt_id not in receipts:
            raise ValueError(f"Missing processed receipt: {sub.receipt_id}")
        receipt = receipts[sub.receipt_id]
        ex = receipt.get("extraction") or {}
        ctx = context(receipt, sub, employees.get(sub.employee_id))
        if ctx["day"] and not inp.period.start <= ctx["day"] <= inp.period.end:
            continue
        claimed, rate, valid = Decimal("0"), Decimal("1"), True
        try:
            total = parse_money(ex.get("total"))
            fx = receipt.get("fx") or {}
            if ex.get("currency") == inp.policy.base_currency:
                claimed = total
            else:
                if fx.get(
                    "base_currency"
                ) != inp.policy.base_currency or not isinstance(fx.get("rate"), str):
                    raise ValueError("Missing FX")
                rate = Decimal(fx["rate"])
                if not rate.is_finite() or rate <= 0:
                    raise ValueError("Invalid rate")
                claimed = parse_money(fx.get("total_base"))
                if claimed != (total * rate).quantize(
                    Decimal(".01"), rounding=ROUND_HALF_UP
                ):
                    raise ValueError("FX mismatch")
        except (ValueError, ArithmeticError):
            valid = False
            rate = Decimal("1")
        proposed, share, hits = claimed, Decimal("1"), []
        rules = [r for r in inp.policy.rules if r.category in ("ALL", ctx["category"])]
        for rule in rules:
            if rule.rule_type in CHECKS:
                hits.extend(CHECKS[rule.rule_type].evaluate(rule, ctx, ex, claimed))
            elif rule.rule_type == "EVIDENCE_REVIEW":
                hits.extend(evidence_review.evaluate(rule, receipt, valid))
        for rule in rules:
            if rule.rule_type == "EXCLUDE_ITEMS":
                proposed, share, more = exclude_items.evaluate(rule, ex, rate, proposed)
                hits.extend(more)
        for rule in rules:
            if rule.rule_type == "TIP_LIMIT":
                proposed, more = tip_limit.evaluate(rule, ex, rate, proposed, share)
                hits.extend(more)
        decisions.append(
            decide(
                sub.receipt_id,
                claimed,
                proposed,
                hits,
                (receipt.get("forensics") or {}).get("score", 0),
            )
        )
    from .duplicates_resolve import resolve
    from .patterns import detect
    from .ledger import apply_ledger
    from .explain import reason
    from ..contracts.decision import Counterfactual

    by_id = {d.receipt_id: d for d in decisions}
    active = [s for s in inp.submissions if s.receipt_id in by_id]
    duplicates = resolve(active, inp.candidates)
    evidence = next(
        (r for r in inp.policy.rules if r.rule_type == "EVIDENCE_REVIEW"), None
    )
    if duplicates and evidence is None:
        raise ValueError(
            "Duplicate decisions require an evidence/duplicate policy clause"
        )
    for rid, (code, effect, original) in duplicates.items():
        d = by_id[rid]
        hits = d.reasons + [
            reason(evidence, code, effect, f"Matches earlier submission {original}.")
        ]
        by_id[rid] = decide(
            rid, d.claimed, d.proposed, hits, d.risk_score, duplicate_of=original
        )
    patterns = detect(receipts, active, by_id, inp.policy.rules, set(duplicates))
    for pattern in patterns:
        rule = next(r for r in inp.policy.rules if r.clause_id == pattern.clause_id)
        for rid in pattern.receipt_ids:
            d = by_id[rid]
            by_id[rid] = decide(
                rid,
                d.claimed,
                d.proposed,
                d.reasons
                + [
                    reason(
                        rule,
                        pattern.code,
                        "REVIEW",
                        f"Related claims: {', '.join(pattern.receipt_ids)}.",
                    )
                ],
                d.risk_score,
                duplicate_of=d.duplicate_of,
            )
    meters = apply_ledger(inp, receipts, active, by_id)
    for decision in by_id.values():
        if not decision.reasons and any(
            c.clause_id == "12.1" for c in inp.policy.clauses
        ):
            from ..contracts.decision import DecisionReason

            decision.reasons.append(
                DecisionReason(
                    code="POLICY_COMPLIANT",
                    effect="INFO",
                    clause_id="12.1",
                    message="?12.1: Applicable policy checks passed.",
                )
            )
    if counterfactuals:
        fixes = {
            "MISSING_CLIENT_NAME": (
                "Add client name",
                "client_name",
                "Provided client",
            ),
            "MISSING_ATTENDEE_COUNT": ("Add attendee count", "attendee_count", 1),
            "MISSING_ATTENDEE_NAMES": ("Add attendee names", "attendee_names", None),
            "MISSING_ITEMIZATION": ("Provide missing itemization", None, None),
        }
        for rid, d in by_id.items():
            for hit in d.reasons:
                if hit.code not in fixes:
                    continue
                label, field, value = fixes[hit.code]
                hypothetical = inp.model_copy(deep=True)
                sub = next(s for s in hypothetical.submissions if s.receipt_id == rid)
                rec = next(r for r in hypothetical.receipts if r["receipt_id"] == rid)
                if field == "attendee_names":
                    value = [
                        f"Attendee {i + 1}"
                        for i in range(
                            sub.attendee_count
                            or rec["extraction"].get("guest_count")
                            or 1
                        )
                    ]
                if field:
                    setattr(sub, field, value)
                else:
                    rec["extraction"]["itemization"] = "FULL"
                fixed = next(
                    x
                    for x in _evaluate(hypothetical, as_of).decisions
                    if x.receipt_id == rid
                )
                d.counterfactuals.append(
                    Counterfactual(
                        fix=label,
                        verdict_if_fixed=fixed.verdict,
                        amount_if_fixed=fixed.reimbursable
                        if fixed.reimbursable is not None
                        else fixed.proposed,
                    )
                )
    return EvaluationResult(
        decisions=[by_id[d.receipt_id] for d in decisions],
        ledger_meters=meters,
        patterns=patterns,
        verdict_counts={
            v: sum(d.verdict == v for d in by_id.values())
            for v in ("APPROVE", "NEEDS_REVIEW", "REJECT")
        },
        amounts={
            "claimed": sum((d.claimed for d in by_id.values()), Decimal("0")),
            "reimbursable": sum(
                (d.reimbursable or Decimal("0") for d in by_id.values()), Decimal("0")
            ),
            "amount_at_risk": sum(
                (d.amount_at_risk for d in by_id.values()), Decimal("0")
            ),
        },
    )
