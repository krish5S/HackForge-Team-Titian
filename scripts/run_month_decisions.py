"""Run Dev 2's engine on Dev 1's processed month and score it (integration glue).

Reads data/month/{manifest.csv,employees.csv,processed/*.json,
processed/duplicate_candidates.json}, calls evaluate_month/build_timeline and
scores against answer_key.json. Public stand-in receipts (real photos whose
policy-relevant facts are not annotated) are reported but not scored, because
no independent expected verdict exists for them.
"""

import argparse
import csv
import json
from pathlib import Path

from backend.app.evaluation import build_timeline, evaluate_month
from backend.app.policy import load_fallback
from scripts.score_month import score_month

UNSCORED_NOTE = ("real public receipt used as a stand-in; only the labeled facts are known, "
                 "so no independent expected verdict exists")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_input(month: Path, policy_path: Path) -> tuple[dict, dict[str, str]]:
    with (month / "employees.csv").open(encoding="utf-8", newline="") as handle:
        employees = list(csv.DictReader(handle))
    with (month / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    submissions, owner = [], {}
    for row in manifest:
        owner[row["receipt_id"]] = row["employee_id"]
        submissions.append({
            "receipt_id": row["receipt_id"], "employee_id": row["employee_id"],
            "submitted_at": row["submitted_at"], "channel": row["channel"],
            "client_meal": row["client_meal"] == "true",
            "client_name": row["client_name"] or None,
            "attendee_count": int(row["attendee_count"]) if row["attendee_count"] else None,
            "attendee_names": json.loads(row["attendee_names"] or "[]"),
            "approved": row["approved"] == "true"})
    receipts = [_read(month / "processed" / f"{row['receipt_id']}.json") for row in manifest]
    raw = _read(month / "processed" / "duplicate_candidates.json")
    candidates = []
    for row in raw:
        pair = [row["receipt_id"], row["duplicate_of"]]
        # Copies by one employee are confirmed; a second employee claiming the
        # same receipt is only a possible duplicate (Appendix A).
        candidates.append({"receipt_ids": pair,
                           "confirmed": owner[pair[0]] == owner[pair[1]]})
    # The engine drops receipts dated outside the period. Real public photos carry
    # their original (older) dates, so start the period at the earliest printed date;
    # the submission-deadline rule then flags them instead of losing them.
    dates = [r["extraction"]["transaction_date"] for r in receipts
             if r.get("extraction", {}).get("transaction_date", "")[:4].isdigit()]
    period = {"start": min(["2026-09-01", *dates]), "end": "2026-09-30"}
    return {"policy": load_fallback(policy_path), "receipts": receipts, "employees": employees,
            "candidates": candidates, "submissions": submissions, "period": period}, owner


def unscored_ids(scenarios_path: Path) -> set[str]:
    scenarios = _read(scenarios_path)["scenarios"]
    return {row["scenario_id"] for row in scenarios
            if row.get("derived_from_public") and
            row["scenario_type"] not in {"forged", "ai_generated"} and
            not row.get("related_ids")}


def run(month: Path, policy_path: Path, scenarios_path: Path, output: Path) -> dict:
    inp, _ = load_input(month, policy_path)
    result = evaluate_month(inp)
    decisions = result.model_dump(mode="json")
    timeline = [event.model_dump(mode="json", by_alias=True) for event in build_timeline(inp)]
    (month / "decisions.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    (month / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    answers = _read(month / "answer_key.json")
    skip = unscored_ids(scenarios_path)
    scored = score_month([row for row in answers if row["receipt_id"] not in skip],
                         [row for row in decisions["decisions"] if row["receipt_id"] not in skip])
    verdicts = {}
    for row in decisions["decisions"]:
        verdicts[row["verdict"]] = verdicts.get(row["verdict"], 0) + 1
    (month / "metrics.json").write_text(json.dumps(scored, indent=2), encoding="utf-8")
    report = {"scored_receipts": len(answers) - len(skip), "unscored_receipts": len(skip),
              "unscored_reason": UNSCORED_NOTE, "score": scored,
              "all_receipt_verdicts": verdicts, "flips": sum(len(e["flips"]) for e in timeline),
              "scenario_status": "provisional"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", type=Path, default=Path("data/month"))
    parser.add_argument("--policy", type=Path, default=Path("data/policy/fallback_rules.json"))
    parser.add_argument("--scenarios", type=Path, default=Path("data/month/scenarios_final.json"))
    parser.add_argument("--output", type=Path, default=Path("data/models/decision_metrics.json"))
    args = parser.parse_args()
    report = run(args.month, args.policy, args.scenarios, args.output)
    score = report["score"]
    print(json.dumps({k: score[k] for k in ("expected_count", "correct_verdict_count",
                                            "verdict_accuracy", "reason_accuracy",
                                            "duplicate_recall", "confirmed_duplicates_approved")}))
    print("verdicts (all 100):", report["all_receipt_verdicts"], "flips:", report["flips"])
    for failure in score["failures"]:
        print(failure)
