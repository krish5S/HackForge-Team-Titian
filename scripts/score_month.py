"""Independent decision scoring. No OCR/model performance claims.

Verdict accuracy denominator: every answer-key entry (missing predictions are wrong).
Reason accuracy uses exact SET equality, ignoring reason order and duplicates.
Duplicate recall requires correct duplicate_of AND REJECT for expected confirmed copies.
Duplicate precision denominator: predictions carrying the DUPLICATE reason.
Extra/missing predictions are listed; duplicate IDs are rejected, never silently overwritten.
"""

import argparse
import json
from pathlib import Path


def score_month(expected, actual):
    expected_ids = [r["receipt_id"] for r in expected]
    actual_ids = [r["receipt_id"] for r in actual]
    if len(set(expected_ids)) != len(expected_ids) or len(set(actual_ids)) != len(
        actual_ids
    ):
        raise ValueError("Duplicate IDs in answer key or predictions")
    predictions = {r["receipt_id"]: r for r in actual}
    verdict_correct = reason_correct = duplicate_correct = duplicates = (
        duplicate_approved
    ) = 0
    failures = []
    predicted_duplicates = {
        r["receipt_id"]
        for r in actual
        if "DUPLICATE" in {x["code"] for x in r["reasons"]}
    }
    for expected_row in expected:
        rid = expected_row["receipt_id"]
        prediction = predictions.get(rid)
        confirmed = (
            expected_row["verdict"] == "REJECT"
            and "DUPLICATE" in expected_row["reason_codes"]
        )
        duplicates += confirmed
        issues = []
        if prediction is None:
            issues.append("missing_prediction")
        else:
            codes = {r["code"] for r in prediction["reasons"]}
            if prediction["verdict"] == expected_row["verdict"]:
                verdict_correct += 1
            else:
                issues.append("verdict")
            if codes == set(expected_row["reason_codes"]):
                reason_correct += 1
            else:
                issues.append("reason_codes")
            link = prediction.get("duplicate_of") == expected_row.get("duplicate_of")
            if not link:
                issues.append("duplicate_of")
            if confirmed:
                duplicate_correct += bool(
                    link
                    and prediction["verdict"] == "REJECT"
                    and rid in predicted_duplicates
                )
                duplicate_approved += prediction["verdict"] == "APPROVE"
        if issues:
            failures.append(dict(receipt_id=rid, mismatches=issues))

    def ratio(n, d):
        return n / d if d else None

    total = len(expected)
    return dict(
        expected_count=total,
        evaluated_count=len(set(expected_ids) & set(actual_ids)),
        correct_verdict_count=verdict_correct,
        verdict_accuracy=ratio(verdict_correct, total),
        correct_reason_sets=reason_correct,
        reason_accuracy=ratio(reason_correct, total),
        confirmed_duplicate_count=duplicates,
        correct_duplicate_count=duplicate_correct,
        duplicate_recall=ratio(duplicate_correct, duplicates),
        duplicate_precision=ratio(duplicate_correct, len(predicted_duplicates)),
        confirmed_duplicates_approved=duplicate_approved,
        failures=failures,
        extra_predictions=sorted(set(actual_ids) - set(expected_ids)),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-key", default="data/month/answer_key.json")
    parser.add_argument(
        "--decisions", required=True, help="JSON list of decisions or EvaluationResult"
    )
    parser.add_argument("--output", default="data/month/metrics.json")
    args = parser.parse_args()
    try:
        expected = json.loads(Path(args.answer_key).read_text(encoding="utf-8"))
        actual = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
        if isinstance(actual, dict):
            actual = actual["decisions"]
        result = score_month(expected, actual)
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Scoring blocked: {exc}\n")
    print(
        f"Correct verdicts: {result['correct_verdict_count']}/{result['expected_count']}; "
        f"confirmed duplicates approved: {result['confirmed_duplicates_approved']}; "
        f"mismatches: {len(result['failures'])}."
    )


if __name__ == "__main__":
    main()
