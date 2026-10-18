import pytest
from scripts.score_month import score_month


def test_missing_wrong_and_extra_predictions():
    expected = [
        dict(
            receipt_id="a",
            verdict="REJECT",
            reason_codes=["DUPLICATE"],
            duplicate_of="original",
        ),
        dict(receipt_id="b", verdict="APPROVE", reason_codes=[], duplicate_of=None),
    ]
    actual = [
        dict(receipt_id="a", verdict="APPROVE", reasons=[], duplicate_of=None),
        dict(
            receipt_id="extra",
            verdict="REJECT",
            reasons=[dict(code="DUPLICATE")],
            duplicate_of="original",
        ),
    ]
    result = score_month(expected, actual)
    assert result["verdict_accuracy"] == 0
    assert result["confirmed_duplicates_approved"] == 1
    assert result["evaluated_count"] == 1
    assert result["duplicate_precision"] == 0
    assert len(result["failures"]) == 2
    assert result["extra_predictions"] == ["extra"]


def test_duplicate_ids_rejected():
    expected = [dict(receipt_id="a")] * 2
    with pytest.raises(ValueError):
        score_month(expected, [])


def test_empty_denominators_are_not_fake_perfect_scores():
    assert score_month([], [])["verdict_accuracy"] is None
