import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.contracts.decision import Decision, TimelineEvent

ROOT = Path(__file__).resolve().parents[3]


def test_document_example_roundtrip():
    data = json.loads(
        (ROOT / "fixtures/decision_sample.json").read_text(encoding="utf-8")
    )
    assert Decision.model_validate(data).model_dump(mode="json") == data


@pytest.mark.parametrize("amount", [1.2, "-1.00", "NaN", "Infinity", "1.001", "bad"])
def test_invalid_money(amount):
    data = json.loads(
        (ROOT / "fixtures/decision_sample.json").read_text(encoding="utf-8")
    )
    data["claimed"] = amount
    with pytest.raises(ValidationError):
        Decision.model_validate(data)


def test_timeline_alias_and_timezone():
    data = dict(
        seq=1,
        submitted_at="2026-09-19T18:04:00+05:30",
        receipt_id="b",
        verdict_at_arrival="NEEDS_REVIEW",
        flips=[
            {
                "receipt_id": "a",
                "from": "APPROVE",
                "to": "NEEDS_REVIEW",
                "reason": "SPLIT_TRANSACTION",
            }
        ],
    )
    assert (
        TimelineEvent.model_validate(data).model_dump(mode="json", by_alias=True)
        == data
    )
    data["submitted_at"] = "2026-09-19T18:04:00"
    with pytest.raises(ValidationError):
        TimelineEvent.model_validate(data)
