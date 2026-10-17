"""Three-run compiler via Dev 1-supplied callback, never a competing model client.

Callback(text, temperature=0.7, timeout=80) -> mapping with rules and sentences.
Sentences: [{clause_id, text, kind: rule|definition|info}]. Rules match Rule schema.
Callback must honor its network timeout; this module bounds waiting to 85 seconds.
"""

from concurrent.futures import ThreadPoolExecutor, wait
import json
import re

from ..contracts.policy import (
    Rule,
    CompiledPolicy,
    CompileResult,
    CompilerFlag,
    CheckResult,
    TrustReport,
)
from .clauses import split_clauses
from .checker import check_policy
from .boundary_tests import run_boundaries

_extractor = None


def configure_compiler(extractor):
    global _extractor
    _extractor = extractor


def _check(status="NOT_RUN", checked=0, failed=0, detail="Not executed."):
    return CheckResult(status=status, checked=checked, failed=failed, detail=detail)


def _key(rule):
    # Source wording and summary are not rule semantics; grounding is checked separately.
    return json.dumps(
        rule.model_dump(mode="json", exclude={"summary", "source_quote"}),
        sort_keys=True,
    )


def compile_policy(text: str) -> CompileResult:
    report = TrustReport(
        **{
            k: _check()
            for k in ("coverage", "grounding", "agreement", "checker", "boundary")
        }
    )
    flags = []

    def flag(code, clause, message):
        flags.append(CompilerFlag(code=code, clause_id=clause, message=message))

    try:
        clauses = split_clauses(text)
    except ValueError as exc:
        flag("INVALID_POLICY", None, str(exc))
        return CompileResult(policy=None, flags=flags, trust_report=report)
    if _extractor is None:
        flag(
            "COMPILER_UNAVAILABLE",
            None,
            "Configure Dev 1 shared client callback; use load_fallback for decisions.",
        )
        return CompileResult(policy=None, flags=flags, trust_report=report)
    executor = ThreadPoolExecutor(max_workers=3)
    jobs = [
        executor.submit(_extractor, text, temperature=0.7, timeout=80) for _ in range(3)
    ]
    done, pending = wait(jobs, timeout=85)
    executor.shutdown(wait=False, cancel_futures=True)
    if pending:
        flag(
            "COMPILER_TIMEOUT",
            None,
            "Three-run compilation exceeded 85 seconds; retain fallback rules.",
        )
        return CompileResult(policy=None, flags=flags, trust_report=report)
    try:
        runs = [job.result() for job in jobs]
    except Exception as exc:
        flag(
            "COMPILER_UNAVAILABLE",
            None,
            f"Extractor failed: {type(exc).__name__}; retain fallback rules.",
        )
        return CompileResult(policy=None, flags=flags, trust_report=report)
    for clause in clauses:
        if re.search(r"\b(generally|reasonable|unusually lavish)\b", clause.text, re.I):
            flag(
                "AMBIGUOUS",
                clause.clause_id,
                "Vague policy wording requires human interpretation; no automatic rule activated.",
            )
    texts = {c.clause_id: c.text for c in clauses}
    sentences = [
        (c.clause_id, s)
        for c in clauses
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", c.text)
        if s.strip()
    ]
    rule_sets = []
    coverage_total = coverage_failed = grounded_total = grounded_failed = 0
    for run in runs:
        rules = {}
        try:
            if (
                not isinstance(run, dict)
                or not isinstance(run.get("rules"), list)
                or not isinstance(run.get("sentences"), list)
            ):
                raise ValueError(
                    "Callback must return rules and sentence classifications"
                )
            for raw in run["rules"]:
                grounded_total += 1
                try:
                    rule = Rule.model_validate(raw)
                except ValueError:
                    flag(
                        "INVALID_RULE",
                        raw.get("clause_id") if isinstance(raw, dict) else None,
                        "Extracted rule has invalid schema.",
                    )
                    grounded_failed += 1
                    continue
                if (
                    rule.clause_id not in texts
                    or rule.source_quote not in texts[rule.clause_id]
                ):
                    flag(
                        "UNGROUNDED",
                        rule.clause_id,
                        "Source quote does not occur in the claimed clause.",
                    )
                    grounded_failed += 1
                    continue
                rules[_key(rule)] = rule
            tags = {}
            for tag in run["sentences"]:
                key = (tag["clause_id"], tag["text"])
                if (
                    key in tags
                    or key not in sentences
                    or tag["kind"] not in {"rule", "definition", "info"}
                ):
                    raise ValueError(
                        "Invalid, repeated or ungrounded sentence classification"
                    )
                tags[key] = tag["kind"]
            for cid, sentence in sentences:
                coverage_total += 1
                classification = tags.get((cid, sentence))
                covered = any(
                    r.clause_id == cid
                    and (sentence in r.source_quote or r.source_quote in sentence)
                    for r in rules.values()
                )
                if classification is None or (classification == "rule" and not covered):
                    coverage_failed += 1
                    flag(
                        "MISSED",
                        cid,
                        "Unclassified sentence or rule-bearing sentence has no grounded extraction.",
                    )
        except (KeyError, ValueError, TypeError):
            flag(
                "INVALID_RESPONSE",
                None,
                "Malformed extractor response; no compiled policy activated.",
            )
            return CompileResult(policy=None, flags=flags, trust_report=report)
        rule_sets.append(rules)
    report.coverage = _check(
        "FAILED" if coverage_failed else "PASSED",
        coverage_total,
        coverage_failed,
        "All source sentences checked across three runs.",
    )
    report.grounding = _check(
        "FAILED" if grounded_failed else "PASSED",
        grounded_total,
        grounded_failed,
        "Exact quotes checked against source clauses.",
    )
    common = set(rule_sets[0]) & set(rule_sets[1]) & set(rule_sets[2])
    union = set().union(*rule_sets)
    for key in sorted(union - common):
        flag(
            "AMBIGUOUS",
            json.loads(key)["clause_id"],
            "Rule semantics differ across runs.",
        )
    report.agreement = _check(
        "FAILED" if union - common else "PASSED",
        len(union),
        len(union - common),
        "Unanimous 3/3 agreement required.",
    )
    policy = CompiledPolicy(
        policy_id="compiled",
        base_currency="USD",
        clauses=clauses,
        rules=[rule_sets[0][k] for k in sorted(common)],
    )
    checker_flags = check_policy(policy)
    flags.extend(checker_flags)
    blocking = [f for f in checker_flags if f.code in {"CONFLICT", "INVALID_RULE"}]
    report.checker = _check(
        "FAILED" if blocking else "PASSED",
        len(policy.rules),
        len(blocking),
        "Structural validation and same-scope conflicts; possible exceptions are advisory.",
    )
    if not blocking:
        report.boundary, boundary_flags = run_boundaries(policy)
        flags.extend(boundary_flags)
    # A failed coverage/agreement check must not silently weaken the active policy.
    unsafe = (
        any(f.code == "AMBIGUOUS" for f in flags)
        or any(
            getattr(report, k).status != "PASSED"
            for k in ("coverage", "grounding", "agreement", "checker")
        )
        or report.boundary.status == "FAILED"
    )
    return CompileResult(
        policy=None if unsafe else policy, flags=flags, trust_report=report
    )
