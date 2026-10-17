from copy import deepcopy
from decimal import Decimal
import pytest
from backend.app.evaluation import evaluate_month, build_timeline
from backend.tests.evaluation.test_engine import sample
from backend.tests.evaluation.test_ledger import pair


@pytest.mark.parametrize(
    "amount,allowed", [("74.99", "74.99"), ("75.00", "75.00"), ("75.01", "75.00")]
)
def test_daily_boundary(amount, allowed):
    assert evaluate_month(sample(amount, "MEALS")).decisions[0].proposed == Decimal(
        allowed
    )


def test_threshold_hugging_across_days():
    inp = pair()
    third = deepcopy(inp["receipts"][0])
    third["receipt_id"] = "c"
    third["extraction"]["transaction_date"] = "2026-09-03"
    inp["receipts"][1]["extraction"]["transaction_date"] = "2026-09-02"
    inp["receipts"].append(third)
    sub = deepcopy(inp["submissions"][1])
    sub.update(receipt_id="c", submitted_at="2026-09-04T12:00:00+05:30")
    inp["submissions"].append(sub)
    assert all(
        "THRESHOLD_HUGGING" in {r.code for r in d.reasons}
        for d in evaluate_month(inp).decisions
    )


def test_fx_valid_and_missing():
    inp = sample("100.00")
    inp["receipts"][0]["extraction"]["currency"] = "MYR"
    inp["receipts"][0]["fx"] = dict(
        base_currency="USD", rate="0.23", total_base="23.00"
    )
    assert evaluate_month(inp).decisions[0].claimed == Decimal("23")
    inp["receipts"][0]["fx"]["rate"] = "NaN"
    assert evaluate_month(inp).decisions[0].verdict == "NEEDS_REVIEW"


def test_missing_employee_and_unknown_category():
    inp = sample()
    inp["employees"] = []
    with pytest.raises(ValueError, match="employee"):
        evaluate_month(inp)
    assert (
        evaluate_month(sample(category="UNKNOWN")).decisions[0].verdict
        == "NEEDS_REVIEW"
    )


def test_transitive_duplicate_cluster():
    inp = pair("20.00")
    receipt = deepcopy(inp["receipts"][0])
    receipt["receipt_id"] = "c"
    inp["receipts"].append(receipt)
    sub = deepcopy(inp["submissions"][1])
    sub.update(receipt_id="c", submitted_at="2026-09-04T12:00:00+05:30")
    inp["submissions"].append(sub)
    inp["candidates"] = [
        dict(receipt_ids=["b", "c"], confirmed=True),
        dict(receipt_ids=["a", "b"], confirmed=True),
    ]
    result = evaluate_month(inp)
    assert [d.duplicate_of for d in result.decisions] == [None, "a", "a"]


def test_replay_serializes_reserved_from_keyword():
    event = build_timeline(pair())[1].model_dump(mode="json")
    assert "from" in event["flips"][0]


def test_guest_names_and_counterfactual():
    inp = sample(category="MEALS")
    inp["submissions"][0].update(attendee_count=2)
    result = evaluate_month(inp)
    assert result.decisions[0].verdict == "NEEDS_REVIEW"
    assert result.decisions[0].counterfactuals[0].verdict_if_fixed == "APPROVE"
