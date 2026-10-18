# Integrated application

The integration branch starts from Dev 3 checkpoint `fdf2f76` and merges `origin/main` at `51ea418` (merge commit `c823dc5`). Main already contains Dev 2 `361b974`, Dev 1 reports `e4fa55e`, and Dev 1 integration `a36d930`. No developer implementation was replaced. The only merge conflict was `.gitignore`; both upload privacy and dataset/model exclusions were retained.

## Laptop setup and startup

Use the repository root. Python 3.10+ works locally; CI uses Python 3.11 and Node 22. Existing `.venv` and accounts can be reused.

```sh
python3 -m venv .venv  # only if a virtual environment does not already exist
make install
make migrate
make load
make evaluate
make backend
```

In another terminal:

```sh
make frontend
```

Open **http://localhost:5173**. API: **http://localhost:8001/api**. Restart an already-running backend to load the integrated routers. `VITE_API_BASE_URL` is already supported. `make backend` loads `backend/.env` when present; direct uvicorn commands need `--env-file backend/.env`. Shell-exported variables take precedence. Keep frontend/backend on `localhost` consistently for cookies. See `backend/.env.example` and `AUTHENTICATION.md` for cookie/origin settings.

`make migrate` registers additive tables and runs the existing repeatable upload-column migration. New tables are `evaluation_artifacts`, `receipt_assets`, `policy_compilations`, and `processing_jobs`; no existing account, submission, receipt, or policy columns are dropped or replaced. Back up an existing DB before operational imports (`sqlite3.Connection.backup` is safe for a live SQLite database). This integration created an ignored, owner-readable backup in `data/backups/pre-integration-20261018T030215.db` before the real import.

## Accounts

Existing credentials and employee links are preserved. If an additional real account is needed, replace placeholders with organization-supplied details:

```sh
.venv/bin/python scripts/create_account.py --role REVIEWER --email '<email>' --display-name '<name>'
.venv/bin/python scripts/create_account.py --role EMPLOYEE --email '<email>' --display-name '<name>' --employee-id '<existing-employee-id>'
```

Passwords are prompted privately. The imported month has six employees with IDs from its CSV; do not assign an account to one without confirming the person's identity. `--create-employee --employee-name '<real-name>'` explicitly creates a new identity; it never overwrites an imported employee.

## Loading actual project data

`make load` reads the real `data/month/employees.csv`, `manifest.csv`, each `processed/{receipt_id}.json`, `processed/duplicate_candidates.json`, and the policy source/fallback/actual compilation report under `data/policy/`. It validates file hashes, IDs, and relationships; stores project-relative original/cleaned paths; and imports within one transaction. Repeating the import does not duplicate records. Identity, submission, processed-payload, or policy conflicts abort rather than silently overwrite data. Model/report/answer-key outputs are not used as decision inputs.

The checked-in month contains real public receipt images plus the teammates' assembled scenarios. Some printed transaction dates are much older than the submission month. The initial inferred evaluation period is **2014-03-14/2026-09-30** so all 100 processed receipts are considered, matching the handoff's broad-period approach. This scope is visible in Overview. To choose an explicit business period:

```sh
.venv/bin/python scripts/evaluate_database.py --start 2026-09-01 --end 2026-09-30
```

Only processed receipts enter `EvaluationInput`; an upload alone is never assigned a fabricated decision. Repeating identical policy/input/version evaluation returns its existing run. Failed evaluation or failed policy activation leaves the previous completed run usable.

## API and metrics

All eleven planned endpoints are implemented. Health remains public; reviewer routes require REVIEWER; employee APIs retain ownership checks. Mutation routes validate Origin. Money is serialized as decimal strings and calculated with Decimal.

The queue, detail decisions, employee results, CSV, metrics, and replay select the globally latest completed EvaluationRun. Each run stores its policy version, base currency, immutable EvaluationInput, real timeline, ledger meters, patterns, and summary. An old run lacking its frozen input reports replay unavailable until a new evaluation is saved.

Metrics definitions:

- Total receipts: actual processed Receipt rows from health, including any outside the evaluated period.
- Evaluated: saved decisions in the selected run.
- Automatically decided: APPROVE plus REJECT decisions; NEEDS_REVIEW is excluded.
- Approved amount: saved reimbursable amounts on APPROVE decisions.
- Blocked amount: `amount_at_risk` on APPROVE and REJECT decisions (final denied portions), excluding pending-review proposals.
- Pending amount: proposed amounts on NEEDS_REVIEW decisions; not a final reimbursement.

Amounts are aggregated only when saved currencies agree with the run's authoritative base currency; missing/ambiguous values remain null. Dev 2 represents unavailable claims as zero plus evidence-review reasons; the adapter preserves its actual outputs. CSV exports saved results, includes policy/run/currency columns, protects formula-like text, and produces headers only for an empty run.

## Policy compilation and historical replay

Startup wires Dev 1's `compile_policy_text` callback into Dev 2's compiler. Configure `backend/.env` as described in `backend/app/llm/README.md`: Gemini uses `RECEIPT_LLM_PROVIDER=gemini`, `RECEIPT_LLM_API_KEY`, and an explicitly verified `RECEIPT_LLM_MODEL`; existing custom services use `RECEIPT_LLM_PROVIDER=custom` and `RECEIPT_LLM_ENDPOINT`. The API does not introduce another model client.

The Policy page shows source clauses, compiled rules, exact source quotes, actual Trust Report checks, and compiler flags. A returned, accepted policy is saved as a new version and reevaluated in the same activation transaction. Null/unaccepted compiler output never replaces the active policy. The Gemini transport is now configured locally and has passed live receipt/policy translation checks; see `backend/app/llm/README.md`. Policy activation is deliberately not performed by transport verification.

Replay calls Dev 2's `evaluate_month(frozen_input, as_of=...)`; it never filters final decisions to simulate history. The slider groups real arrival timestamps, the event list uses `build_timeline` flips, and meters come from actual snapshot ledger outputs. Receipt links open current details and are labelled accordingly.

## Employee processing handoff

Upload HTTP requests only validate/store. The optional client-meal checkbox maps to Dev 2's real submission contract. Identity and approval cannot be supplied by an employee. Uploaded files remain UPLOADED until an actual worker transition/result exists.

On the laptop:

```sh
.venv/bin/python scripts/receipt_handoff.py export --directory data/worker-handoff
```

This creates one unique ProcessingJob per submission and exports original files, identity-preserving jobs, hashes, and existing processed receipts for duplicate matching. Repeating export reuses job IDs. It does not run inference or pretend the worker has started.

Transfer this private bundle to the configured worker through your approved transport. The agent has not transmitted it. On that machine, with the repository, FX file, Dev 1 OCR environment, and any approved trained weights available:

```sh
# Worker only; do not install this GPU/OCR stack on the demo laptop just for the UI.
python -m pip install -r backend/requirements/pipeline.txt
python -m scripts.run_receipt_worker --directory /worker/path/to/bundle
```

The runner calls `process_receipt` and `find_duplicates` unchanged, caches completed per-job results, and holds a directory lock against concurrent runs of the same bundle. Optional CNN/LayoutLM are governed by Dev 1's existing weight/report gates. Fresh OCR requires PaddleOCR/model resources; learned readers additionally require their worker environment and weights. The original integration did not execute these locally. The subsequent CPU worker setup below installs and runs Paddle OCR locally; optional trained CNN/LayoutLM weights remain unavailable.

When the worker actually starts a known job, an operator may record its state on the laptop:

```sh
.venv/bin/python scripts/receipt_handoff.py mark-processing --job-id '<job-id>'
```

Return the bundle including `results.json`, per-job result JSON, and normalized files, then:

```sh
.venv/bin/python scripts/receipt_handoff.py import --directory data/worker-handoff
make evaluate
```

Import verifies submission IDs and source hashes, preserves employee ownership, saves actual processed payloads and clean references, and updates genuine failures/results. Repeated imports do not create duplicate receipts or decisions. Missing external dependencies leave uploads honestly pending unless the operator explicitly marks an actual start. Failure retry is explicit: use `retry-failed --job-id '<id>'`, then export to a fresh bundle directory so a cached failed result is not reused. A stale `.worker-lock` may be removed by the operator only after confirming no worker is running. Use one worker/bundle owner; this is a portable operator handoff, not a distributed task queue.

Original/clean selectors appear only when the corresponding saved files exist. The supplied batch has no normalized file references, so it correctly exposes originals only. A cleaned reference is stored when genuine worker output arrives.

## Checks and demo

```sh
make test
```

Checks cover the existing auth/upload suite, actual 100-receipt loading twice, identity conflicts, saved evaluation/metrics/CSV consistency, PNG/PDF delivery, genuine timeline snapshots, authorization, pending uploads, worker bundle export/import idempotency and hash mismatch, and frontend build/lint/session checks. Pure teammate policy/evaluation/text-reader tests run without GPU packages. CI runs this same laptop-safe suite.

The real database now holds the supplied 100 receipts and a completed real-evaluator run: 15 APPROVE, 74 NEEDS_REVIEW, 11 REJECT. Existing auth account rows were compared before/after and are unchanged. This verifies **batch data → evaluator → persisted API results**, not fresh upload → OCR → decision.

Not verified: live external compilation acceptance, optional GPU/learned-model inference, or real-account browser clicks/responsive visual rendering (no browser provider was available). The subsequent CPU worker verification below covers a fresh upload through OCR, Gemini and evaluation. No scores, Trust Reports, or model metrics were fabricated.

Demo checklist:

1. Restart backend/frontend, sign in with your existing reviewer account.
2. Overview: inspect counts, filter an employee/verdict, open a receipt, download CSV.
3. Policy: inspect source/rules/checks; without a text service, compile reports unavailable and preserves the policy.
4. Replay: move the arrival slider and inspect real flips/budget use.
5. Log out; sign in as an employee, upload a real receipt, see its actual ID and pending status.
6. After actual worker processing/import and reevaluation, refresh employee history and reviewer results.

No branch has been pushed or merged into main automatically. See `OWNERSHIP.md` for preserved developer boundaries.

## Automatic local processing

A CPU-only coordinator now reuses the existing handoff and Dev 1 pipeline. It polls
pending uploads every five seconds, runs OCR/Gemini outside HTTP requests, imports
real results and invokes Dev 2 evaluation with the currently active policy.

```sh
make install-worker  # once, in the existing project virtual environment
make worker          # keep running in a separate terminal alongside the backend
```

`make worker` loads backend/.env. No GPU training packages, CNN weights or LayoutLM
weights are installed by the worker requirements. Optional learned models retain
Dev 1's existing availability/quality gates. Official Paddle OCR inference models
are downloaded on first use into ignored data/model-cache. The first receipt can
therefore take longer. Use `.venv/bin/python scripts/local_worker.py --once` for a
single pending receipt rather than continuous polling.

A file lock prevents two local coordinators; the inference child inherits that lock.
The active bundle and per-job result cache survive restart, so an interrupted import
or evaluation resumes without repeating completed inference. Failed processing is
shown honestly and requires explicit `receipt_handoff.py retry-failed --job-id <id>`;
it is not repeatedly sent to Gemini. Evaluation failures retain the previous completed
run and are retried while the receipt remains processed. Stop the worker with Ctrl+C;
let any current child finish before starting another worker.

Automatic evaluation uses a cumulative period extending the previous run's boundaries
to include processed transaction and submission dates. Overview displays that scope.
It never activates a newly compiled policy. The worker and manual handoff should not
be used to operate the same queued job concurrently.

The employee history polls every 30 seconds; refresh it to see a new result sooner.

Verified locally: submission `b3a2375eadec415c9750f974004c7ea6` completed the real
Paddle OCR → Gemini extraction → storage → Dev 2 evaluation flow. Its extraction
status is OK and verdict NEEDS_REVIEW, from saved evaluation
`5b1beedb8c7548d785f2a6d91585660b` (2014-03-14 through 2026-10-18).
The original and account data were preserved; backup precedes this processing run.
A continuous worker was started with logs at `data/local-worker/worker.log` and its
PID at `data/local-worker/worker.pid`. It is a local process, not an OS login service;
after a reboot, start `make worker` again. Do not start a second manual worker for
the same jobs. To stop the background process, verify the recorded PID still belongs
to `scripts/local_worker.py`, then send it SIGTERM. The file lock protects a child
that is finishing a receipt; wait for it before restarting.

### Receipt extraction audit and repair

A visual comparison of the uploaded receipt against its OCR exposed a pattern-reader
bug: `Sub Total` matched `Total`, and an unformatted whole-number grand total was
missed. The reader now separates subtotal/total, accepts whole numbers in labeled
amount contexts, aggregates SGST/CGST, excludes tax labels from merchandise lines,
and handles two-digit day-first dates and AM/PM times. Tax invoice/registration
numbers are not treated as tax amounts. Regression tests cover these cases.

A fresh Paddle OCR + Gemini run on the unchanged upload produced subtotal 260.00,
tax 13.00 and total 273.00. Every emitted arithmetic/date validation passed, the
readers agreed, and the prior false forensic signals disappeared. The corrected
extraction and real reevaluation replaced the current result only after checks;
prior extraction is archived under data/reprocessing and a private database backup
was taken. Previous completed evaluations retain their immutable inputs.

Readability does not establish policy eligibility. This receipt still lacks an
explicit currency and tip; the provided FX table lacks INR; travel context is not
established; and its 2025-02-24 date is outside the submission deadline. No currency,
FX rate, tip or approval was invented. Optional trained LayoutLM/CNN remain gated
by their absent weights; the verified path is Paddle + pattern reader + Gemini +
validation + rule-based forensics + Dev 2 evaluation.
