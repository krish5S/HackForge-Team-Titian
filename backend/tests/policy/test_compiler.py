from pathlib import Path
import re
from copy import deepcopy
from backend.app.policy import load_fallback, compile_policy, configure_compiler
from backend.app.policy.clauses import split_clauses
from backend.app.policy.boundary_tests import run_boundaries

ROOT = Path(__file__).resolve().parents[3]


def test_no_client_is_truthful():
    configure_compiler(None)
    result = compile_policy(
        (ROOT / "data/policy/policy.md").read_text(encoding="utf-8")
    )
    assert result.policy is None
    assert result.trust_report.agreement.status == "NOT_RUN"
    assert result.flags[0].code == "COMPILER_UNAVAILABLE"


def test_boundaries_use_engine():
    report, flags = run_boundaries(
        load_fallback(ROOT / "data/policy/fallback_rules.json")
    )
    assert report.status == "PASSED", flags
    assert report.checked == 27


def payload(text):
    clauses = split_clauses(text)
    rules = load_fallback(ROOT / "data/policy/fallback_rules.json").model_dump(
        mode="json"
    )["rules"]
    tags = []
    for c in clauses:
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", c.text):
            tags.append(
                dict(
                    clause_id=c.clause_id,
                    text=s,
                    kind="rule" if c.clause_id not in ("11.1", "12.1") else "info",
                )
            )
    return dict(rules=rules, sentences=tags)


def test_grounding_and_coverage_reject_bad_output():
    text = (ROOT / "data/policy/policy.md").read_text(encoding="utf-8")
    data = payload(text)
    data["rules"][0]["source_quote"] = "Invented quotation"
    configure_compiler(lambda text, **kw: deepcopy(data))
    try:
        result = compile_policy(text)
        assert result.policy is None
        assert {"UNGROUNDED", "MISSED"} <= {f.code for f in result.flags}
    finally:
        configure_compiler(None)


def test_agreement_and_valid_compile():
    text = (ROOT / "data/policy/policy.md").read_text(encoding="utf-8")
    data = payload(text)
    configure_compiler(lambda text, **kw: deepcopy(data))
    try:
        result = compile_policy(text)
        assert result.policy is None
        assert any(
            f.code == "AMBIGUOUS" and f.clause_id == "11.1" for f in result.flags
        )
        assert result.trust_report.agreement.status == "PASSED"
    finally:
        configure_compiler(None)


def test_disagreement_is_not_majority_acceptance():
    from itertools import count

    text = (ROOT / "data/policy/policy.md").read_text(encoding="utf-8")
    counter = count()

    def extractor(text, **kw):
        data = payload(text)
        if next(counter) == 2:
            data["rules"][0]["parameters"]["amount"] = "350.00"
        return data

    configure_compiler(extractor)
    try:
        result = compile_policy(text)
        assert result.policy is None
        assert result.trust_report.agreement.status == "FAILED"
    finally:
        configure_compiler(None)


def test_checker_conflict():
    from backend.app.policy.checker import check_policy

    policy = load_fallback(ROOT / "data/policy/fallback_rules.json")
    copy = policy.rules[0].model_copy(deep=True)
    copy.parameters.amount = "350.00"
    policy.rules.append(copy)
    assert "CONFLICT" in {f.code for f in check_policy(policy)}
