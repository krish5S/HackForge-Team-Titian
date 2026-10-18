"""TEST ONLY: simulated reader evidence, never committed as production processed JSON."""

import json
from pathlib import Path
from backend.app.evaluation import evaluate_month, build_timeline
from backend.app.policy import load_fallback
from scripts.build_month import EMPLOYEES
from scripts.score_month import score_month

ROOT = Path(__file__).resolve().parents[3]


def synthetic_month():
    rows = json.loads((ROOT / "data/month/scenarios.yaml").read_text())["scenarios"]
    receipts = []
    submissions = []
    candidates = []
    answers = []
    fields = (
        "merchant",
        "city",
        "country",
        "transaction_date",
        "transaction_time",
        "currency",
        "subtotal",
        "total",
        "tax",
        "tip",
        "other_charges",
        "line_items",
        "category",
    )
    for r in rows:
        ex = {k: r[k] for k in fields}
        ex["merchant_name"] = ex.pop("merchant")
        ex["itemization"] = "FULL"
        receipts.append(
            dict(
                receipt_id=r["scenario_id"],
                extraction=ex,
                is_receipt=r["scenario_type"] != "unreadable",
                extraction_status="OK",
                forensics=dict(
                    score=70 if r["scenario_type"] in ("forged", "ai_generated") else 0
                ),
            )
        )
        if "scenario_fx_rate" in r:
            from decimal import Decimal

            receipts[-1]["fx"] = dict(
                base_currency="USD",
                rate=r["scenario_fx_rate"],
                total_base=format(
                    Decimal(r["total"]) * Decimal(r["scenario_fx_rate"]), ".2f"
                ),
            )
        submissions.append(
            dict(
                receipt_id=r["scenario_id"],
                **{
                    k: r[k]
                    for k in (
                        "employee_id",
                        "submitted_at",
                        "channel",
                        "client_meal",
                        "client_name",
                        "attendee_count",
                        "attendee_names",
                        "approved",
                    )
                },
            )
        )
        if r["scenario_type"].endswith("duplicate"):
            candidates.append(
                dict(
                    receipt_ids=[r["scenario_id"], *r["related_ids"]],
                    confirmed=r["scenario_type"] != "cross_employee_duplicate",
                )
            )
        answers.append(dict(receipt_id=r["scenario_id"], **r["expected"]))
    return dict(
        policy=load_fallback(ROOT / "data/policy/fallback_rules.json"),
        receipts=receipts,
        employees=EMPLOYEES,
        candidates=candidates,
        submissions=submissions,
        period=dict(start="2026-09-01", end="2026-09-30"),
    ), answers


def test_full_synthetic_month_against_independent_scenarios():
    inp, answers = synthetic_month()
    result = evaluate_month(inp)
    score = score_month(answers, result.model_dump(mode="json")["decisions"])
    assert score["failures"] == []
    assert score["confirmed_duplicates_approved"] == 0
    assert len(result.decisions) == 100
    timeline = build_timeline(inp)
    assert len(timeline) == 100
    assert any(f.reason == "SPLIT_TRANSACTION" for e in timeline for f in e.flips)
    assert any(f.reason == "CITY_DAILY_CAP" for e in timeline for f in e.flips)
