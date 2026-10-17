from copy import deepcopy
from decimal import Decimal
from backend.app.evaluation import evaluate_month, build_timeline
from backend.tests.evaluation.test_engine import sample


def pair(amount="480.00", category="TRAVEL"):
    inp = sample(amount, category)
    inp["receipts"][0]["extraction"]["merchant_name"] = "Same merchant"
    receipt = deepcopy(inp["receipts"][0])
    receipt["receipt_id"] = "b"
    inp["receipts"].append(receipt)
    sub = deepcopy(inp["submissions"][0])
    sub.update(receipt_id="b", submitted_at="2026-09-03T12:00:00+05:30")
    inp["submissions"].append(sub)
    return inp


def test_split_flips_and_cutoff():
    inp = pair()
    assert (
        evaluate_month(inp, "2026-09-02T13:00:00+05:30").decisions[0].verdict
        == "APPROVE"
    )
    assert all(d.verdict == "NEEDS_REVIEW" for d in evaluate_month(inp).decisions)
    timeline = build_timeline(inp)
    assert timeline[1].flips[0].receipt_id == "a"
    assert timeline[1].flips[0].reason == "SPLIT_TRANSACTION"
    assert timeline == build_timeline(inp)


def test_duplicates_dont_consume_budget():
    inp = pair("50.00", "MEALS")
    inp["candidates"] = [dict(receipt_ids=["b", "a"], confirmed=True)]
    result = evaluate_month(inp)
    assert [d.verdict for d in result.decisions] == ["APPROVE", "REJECT"]
    assert result.decisions[1].duplicate_of == "a"
    assert result.ledger_meters[0].used_after == Decimal("50")


def test_monthly_and_daily_caps():
    inp = pair("200.00", "ENTERTAINMENT")
    assert [d.proposed for d in evaluate_month(inp).decisions] == [
        Decimal("200"),
        Decimal("100"),
    ]
    inp = pair("50.00", "MEALS")
    assert [d.proposed for d in evaluate_month(inp).decisions] == [
        Decimal("50"),
        Decimal("25"),
    ]


def test_counterfactual_keeps_other_blockers():
    inp = sample("30.00", "MEALS")
    inp["submissions"][0]["client_meal"] = True
    inp["receipts"][0]["extraction"]["itemization"] = "NONE"
    result = evaluate_month(inp)
    assert all(
        c.verdict_if_fixed == "NEEDS_REVIEW"
        for c in result.decisions[0].counterfactuals
    )


def test_late_receipt_reallocates_daily_budget():
    inp = pair("50.00", "MEALS")
    inp["receipts"][1]["extraction"]["transaction_time"] = "09:00:00"
    before = evaluate_month(inp, "2026-09-02T13:00:00+05:30")
    after = evaluate_month(inp)
    assert before.decisions[0].proposed == Decimal("50")
    assert after.decisions[0].proposed == Decimal("25")


def test_same_arrival_time_is_stable():
    inp = pair()
    inp["submissions"][1]["submitted_at"] = inp["submissions"][0]["submitted_at"]
    assert build_timeline(inp)[1].flips[0].receipt_id == "a"
