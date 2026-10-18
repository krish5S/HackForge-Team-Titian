from copy import deepcopy
from pathlib import Path
import pytest
from backend.app.policy import load_fallback
from backend.app.evaluation import evaluate_month

ROOT = Path(__file__).resolve().parents[3]


def sample(total="20.00", category="TRAVEL"):
    return dict(
        policy=load_fallback(ROOT / "data/policy/fallback_rules.json"),
        receipts=[
            dict(
                receipt_id="a",
                is_receipt=True,
                extraction_status="OK",
                extraction=dict(
                    total=total,
                    subtotal=total,
                    tax="0.00",
                    tip="0.00",
                    other_charges="0.00",
                    currency="USD",
                    city="Chicago",
                    transaction_date="2026-09-01",
                    transaction_time="12:00:00",
                    category=category,
                    itemization="FULL",
                    line_items=[
                        dict(description="Service", amount=total, item_class="OTHER")
                    ],
                ),
            )
        ],
        employees=[dict(id="e", name="Test", home_city="New York")],
        candidates=[],
        submissions=[
            dict(
                receipt_id="a",
                employee_id="e",
                submitted_at="2026-09-02T12:00:00+05:30",
                channel="email",
            )
        ],
        period=dict(start="2026-09-01", end="2026-09-30"),
    )


@pytest.mark.parametrize(
    "amount,verdict",
    [("499.99", "APPROVE"), ("500.00", "APPROVE"), ("500.01", "NEEDS_REVIEW")],
)
def test_approval_boundaries(amount, verdict):
    assert evaluate_month(sample(amount)).decisions[0].verdict == verdict


def test_pure_and_cutoff():
    inp = sample()
    before = deepcopy(inp)
    assert evaluate_month(inp) == evaluate_month(inp)
    assert inp == before
    assert not evaluate_month(inp, "2026-09-01T00:00:00+05:30").decisions


def test_alcohol_and_tip():
    inp = sample("130.00")
    inp["receipts"][0]["extraction"].update(
        subtotal="100.00",
        tip="30.00",
        line_items=[
            dict(amount="20.00", item_class="ALCOHOL"),
            dict(amount="80.00", item_class="FOOD"),
        ],
    )
    d = evaluate_month(inp).decisions[0]
    assert str(d.proposed) == "96.00"
    assert {r.code for r in d.reasons} == {"EXCLUDED_ITEM", "TIP_LIMIT"}


@pytest.mark.parametrize(
    "change,code",
    [
        ("client", "MISSING_CLIENT_NAME"),
        ("item", "MISSING_ITEMIZATION"),
        ("unreadable", "UNREADABLE"),
        ("date", "SUBMISSION_DATE"),
    ],
)
def test_review_conditions(change, code):
    inp = sample("30.00", "MEALS")
    if change == "client":
        inp["submissions"][0]["client_meal"] = True
    if change == "item":
        inp["receipts"][0]["extraction"]["itemization"] = "NONE"
    if change == "unreadable":
        inp["receipts"][0]["is_receipt"] = False
    if change == "date":
        inp["submissions"][0]["submitted_at"] = "2026-11-01T00:00:00+05:30"
    d = evaluate_month(inp).decisions[0]
    assert d.verdict == "NEEDS_REVIEW"
    assert code in {r.code for r in d.reasons}
    assert all(
        r.clause_id in {c.clause_id for c in inp["policy"].clauses} for r in d.reasons
    )
