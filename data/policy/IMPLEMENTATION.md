# Dev 2 implementation agreement

Source: Receipt_Graveyard_Execution_Plan (1).docx and the latest Dev 2 implementation prompt.
The user authorized provisional contracts and rule types because the referenced original
PRD sections are absent. These are proposals for Dev 1/3 integration, not frozen contracts.

Ten provisional types: MONTHLY_CAP, CITY_DAILY_CAP, LOCAL_MEAL, EXCLUDE_ITEMS,
CLIENT_DETAILS, APPROVAL_THRESHOLD, ITEMIZATION, TIP_LIMIT, SUBMISSION_DEADLINE,
EVIDENCE_REVIEW. Duplicate and pattern decisions are separate evaluation passes.

Decision/timeline field names follow the document examples. Policy/input/result wrappers
are provisional. ProcessedReceipt remains Dev 1-owned and is consumed as a mapping.
One receipt_id identifies one submission; repeated images need separate receipt IDs.
Amounts are base USD, nonnegative Decimal cents; FX comes exclusively from Dev 1.
Risk amount: proposed for pending review, claimed for rejected, claimed minus proposed
for approved. Review claims reserve proposed budget; rejected duplicates reserve none.
Transactions sort by date/time then receipt ID, arrivals by timestamp then receipt ID.
Policy choices below are fictional demo settings, not recovered PRD constants.

No Git operations were completed: the Git metadata escalation was declined. Work remains
local and uncommitted until the user permits the branch/commit workflow.


## Local use and handoff

From repository root:

```powershell
python -m pip install -r backend/requirements/policy.txt
python -m pytest backend/tests/policy backend/tests/evaluation -q
python -m scripts.build_month --index data/month/images_index.json
python -m scripts.score_month --decisions path/to/actual-decisions.json
```

The environment used to validate this implementation has Python 3.13.9, Pydantic 2.12.4,
Pytest 8.4.2 and PyYAML 6.0.3. Code targets Python 3.11 syntax; a Python 3.11 runtime
was not available for execution. Windows sandbox restrictions required elevated pytest
runs for temporary-file tests. No model, GPU, database or API server is needed for unit tests.

```python
from backend.app.policy import load_fallback, compile_policy, configure_compiler
from backend.app.evaluation import evaluate_month, build_timeline

policy = load_fallback("data/policy/fallback_rules.json")
# inp is EvaluationInput, or a mapping matching backend/app/contracts/decision.py.
# result = evaluate_month(inp, as_of="2026-09-15T23:59:59+05:30")
# payload = result.model_dump(mode="json")
# events = [e.model_dump(mode="json") for e in build_timeline(inp)]
```

When running from backend/, use imports from `app` instead of `backend.app`.
Only Dev 3 services may persist decisions. `EvaluationResult` includes verdict counts and
aggregate amounts for snapshots. `TimelineEvent.flips` also reports amount-only changes:
`from` and `to` may both be APPROVE with reason CITY_DAILY_CAP. Dev 3 should fetch the
snapshot to show amounts; no extra unagreed fields were added to the example flip shape.
Submissions with transaction dates outside the requested period are excluded. Unknown
transaction dates remain reviewable. All timestamps supplied to replay must be aware.

### Dev 1 handoff

Provide real processed receipts using the execution-plan shape and a real image index:

```json
{"images": [{"scenario_id": "r_001", "path": "images/r_001.png"}]}
```

Paths resolve relative to the image index and must point to existing files inside that
month directory. Builder validates all references before writing output. The scenario
file is JSON-compatible YAML, with decimal amounts kept as strings. Four scenarios
include fictional scenario_fx_rate values to request reproducible foreign-currency
examples; Dev 1 must explicitly adopt those demo rates or coordinate updated expectations.
No production FX table or processed receipt has been fabricated by Dev 2.

Duplicate adapter proposal: `{receipt_ids: [id1, id2], confirmed: true/false}`.
Both sides must refer to submission-specific receipt IDs, even when images are identical.
The original plan places candidates at data/month/duplicate_candidates.json while the
implementation guide also mentions data/month/processed/duplicate_candidates.json.
Dev 3's loader must agree the actual path with Dev 1; the pure engine takes data, not paths.

### Compiler integration

The user approved a callback interface while Dev 1's shared client is absent:

```python
configure_compiler(shared_client_adapter)
# shared_client_adapter(text, temperature=0.7, timeout=80)
# returns {"rules": [Rule mappings], "sentences": [
#   {"clause_id": "1.1", "text": "exact sentence", "kind": "rule"}
# ]}
```

Sentence kinds: rule, definition, info. The callback must honor its network timeout.
Three calls run concurrently; compiler waiting is capped at 85 seconds, but Python
cannot forcibly stop a callback that ignores its timeout. No direct model client exists
in Dev 2 code. Callback must be thread-safe and not changed during compilation.

Compilation is conservative: missed coverage, ungrounded rules, disagreement, invalid
parameters, conflicts, failed boundary checks, or detected vague wording prevent a
replacement policy from activating. Keep the manually reviewed fallback active when
CompileResult.policy is null. POSSIBLE_EXCEPTION is advisory. Vague-word detection is a
small deterministic safeguard, not a comprehensive ambiguity classifier; the three
LLM classifications remain necessary. No live compiler result has been measured.
`compiled.json` records the actual unavailable-client result, not a successful compilation.
Fallback rule parameters are manually reviewed demo data. Compiler grounding checks exact
source quotes; it does not mathematically prove the LLM interpreted every sentence correctly.

### Current acceptance status

Implemented locally: contracts, policy/scenarios, fallback validation, all ten provisional
rule evaluators, pure evaluation, monetary adjustments, monthly/daily ledger, duplicate
resolution, patterns, counterfactuals, replay, month builder, compiler callback/checks,
and scoring. Every no-issue decision cites explanation clause 12.1.

Still pending external handoffs: real images/index, real processed receipts, shared LLM
client and Dev 3's final schema review. Consequently manifest.csv, employees.csv,
answer_key.json and real metrics.json are not generated yet. The builder generates the
first three together when the real image handoff is available. Scoring defaults to
`data/month/metrics.json` (provisional path for team review).

All 100 scenarios are evaluated in test_synthetic_month.py using explicitly simulated
reader/forensic evidence. Those results validate decision logic against scenarios only;
they are not OCR/model accuracy or production month scores. Integration gates G1/G2
cannot be declared complete until real processed receipts have been evaluated.

The eight section branch/commit/PR workflow is pending: no remote fetch, branch, commit,
push, merge or tag was performed after the Git update was declined. No Dev 1/Dev 3
source files were changed.
