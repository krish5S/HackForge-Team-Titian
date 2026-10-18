from decimal import Decimal
from ..contracts.decision import LedgerReference, LedgerMeter
from .context import context
from .explain import reason
from .decide import decide
from .rules import monthly_cap, city_daily_cap


def apply_ledger(inp, receipts, submissions, decisions):
    employees = {e.id: e for e in inp.employees}
    totals = {}
    meters = {}

    def ordering(sub):
        ex = receipts[sub.receipt_id].get("extraction") or {}
        return (
            ex.get("transaction_date") or "9999",
            ex.get("transaction_time") or "23:59:59",
            sub.receipt_id,
        )

    for sub in sorted(submissions, key=ordering):
        d = decisions[sub.receipt_id]
        if d.verdict == "REJECT":
            continue
        ctx = context(receipts[sub.receipt_id], sub, employees.get(sub.employee_id))
        applicable = []
        hits = list(d.reasons)
        amount = d.proposed
        for rule in inp.policy.rules:
            if rule.category not in ("ALL", ctx["category"]):
                continue
            module = {"MONTHLY_CAP": monthly_cap, "CITY_DAILY_CAP": city_daily_cap}.get(
                rule.rule_type
            )
            if module is None:
                continue
            budget = module.budget(rule, ctx, sub)
            if budget is None:
                continue
            key, label, cap = budget
            used = totals.get(key, Decimal("0"))
            allowed = min(amount, max(Decimal("0"), cap - used))
            if allowed < amount:
                hits.append(
                    reason(
                        rule,
                        rule.rule_type,
                        "CAP",
                        f"Eligible {amount:.2f}; limit {cap:.2f}, already reserved {used:.2f}; allows {allowed:.2f}.",
                    )
                )
            amount = allowed
            applicable.append((key, label, cap, used))
        refs = []
        # Reserve the final amount against every applicable budget, not intermediate amounts.
        for key, label, cap, used in applicable:
            totals[key] = used + amount
            refs.append(
                LedgerReference(
                    label=label, cap=cap, used_before=used, used_after=totals[key]
                )
            )
            meters[key] = LedgerMeter(
                employee_id=sub.employee_id,
                label=label,
                cap=cap,
                used_before=used,
                used_after=totals[key],
                remaining=cap - totals[key],
            )
        decisions[sub.receipt_id] = decide(
            d.receipt_id, d.claimed, amount, hits, d.risk_score, refs, d.duplicate_of
        )
    return [meters[k] for k in sorted(meters)]
