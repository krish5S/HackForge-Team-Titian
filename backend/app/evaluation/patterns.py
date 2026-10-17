from collections import defaultdict
from ..contracts.decision import Pattern


def detect(receipts, submissions, decisions, rules, duplicate_ids):
    patterns = []
    subs = {s.receipt_id: s for s in submissions}
    for rule in rules:
        if rule.rule_type != "APPROVAL_THRESHOLD":
            continue
        splits = defaultdict(list)
        hugging = defaultdict(list)
        for rid, d in decisions.items():
            if rid in duplicate_ids:
                continue
            ex = receipts[rid].get("extraction") or {}
            sub = subs[rid]
            if rule.category not in ("ALL", ex.get("category")):
                continue
            merchant = (receipts[rid].get("fingerprints") or {}).get(
                "merchant_norm"
            ) or ex.get("merchant_name")
            day = ex.get("transaction_date")
            if not day:
                continue
            if merchant and d.claimed < rule.parameters.amount:
                splits[(sub.employee_id, merchant.casefold(), day)].append(rid)
            if rule.parameters.amount * 9 / 10 <= d.claimed <= rule.parameters.amount:
                hugging[(sub.employee_id, ex.get("category"), day[:7])].append(rid)
        for ids in splits.values():
            if (
                len(ids) > 1
                and sum(decisions[r].claimed for r in ids) > rule.parameters.amount
            ):
                patterns.append(
                    Pattern(
                        code="SPLIT_TRANSACTION",
                        receipt_ids=sorted(ids),
                        clause_id=rule.clause_id,
                    )
                )
        for ids in hugging.values():
            if len(ids) >= 3:
                patterns.append(
                    Pattern(
                        code="THRESHOLD_HUGGING",
                        receipt_ids=sorted(ids),
                        clause_id=rule.clause_id,
                    )
                )
    return sorted(patterns, key=lambda p: (p.code, p.receipt_ids))
