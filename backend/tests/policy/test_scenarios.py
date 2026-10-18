import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_policy_and_scenarios():
    text = (ROOT / "data/policy/policy.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^## \d+\.\d+ ", text, re.M)) == 12
    rows = json.loads((ROOT / "data/month/scenarios.yaml").read_text())["scenarios"]
    assert len(rows) == 100
    ids = {r["scenario_id"] for r in rows}
    assert len(ids) == 100
    counts = Counter(r["scenario_type"] for r in rows)
    for name, count in dict(
        exact_duplicate=5,
        rephotographed_duplicate=3,
        pdf_photo_duplicate=3,
        cross_employee_duplicate=2,
        forged=6,
        ai_generated=4,
        split_transaction=4,
        trip_over_cap=4,
        monthly_cap=3,
        alcohol=4,
        missing_client=3,
        late_arrival=2,
        unreadable=2,
    ).items():
        assert counts[name] == count
    for r in rows:
        assert set(r["related_ids"]) <= ids
        assert datetime.fromisoformat(r["submitted_at"]).tzinfo is not None
        assert sum(Decimal(i["amount"]) for i in r["line_items"]) == Decimal(
            r["subtotal"]
        )
        assert Decimal(r["total"]) == sum(
            Decimal(r[k]) for k in ("subtotal", "tax", "tip", "other_charges")
        )
