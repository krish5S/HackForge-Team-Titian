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

Open **http://localhost:5173**. API: **http://localhost:8001/api**. Restart an already-running backend to load the integrated routers. `VITE_API_BASE_URL` is already supported. For a local backend `.env`, pass `--env-file backend/.env` to uvicorn; shell-exported variables work too. Keep frontend/backend on `localhost` consistently for cookies. See `backend/.env.example` and `AUTHENTICATION.md` for cookie/origin settings.

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

Startup wires Dev 1's `compile_policy_text` callback into Dev 2's compiler. Set `RECEIPT_LLM_ENDPOINT` (and optional `RECEIPT_LLM_API_KEY`) to the actual text service described in `backend/app/llm/README.md`. The API does not introduce another model client.

The Policy page shows source clauses, compiled rules, exact source quotes, actual Trust Report checks, and compiler flags. A returned, accepted policy is saved as a new version and reevaluated in the same activation transaction. Null/unaccepted compiler output never replaces the active policy. No endpoint is configured locally, so **live successful compilation/activation remains unverified**; its unavailable path is verified.

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

The runner calls `process_receipt` and `find_duplicates` unchanged, caches completed per-job results, and holds a directory lock against concurrent runs of the same bundle. Optional CNN/LayoutLM are governed by Dev 1's existing weight/report gates. Fresh OCR requires PaddleOCR/model resources; learned readers additionally require their worker environment and weights. These are **not installed or executed locally**.

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

Not verified: live external compilation acceptance, fresh OCR/GPU inference, or real-account browser clicks/responsive visual rendering (no browser provider was available). No scores, Trust Reports, or model metrics were fabricated.

Demo checklist:

1. Restart backend/frontend, sign in with your existing reviewer account.
2. Overview: inspect counts, filter an employee/verdict, open a receipt, download CSV.
3. Policy: inspect source/rules/checks; without a text service, compile reports unavailable and preserves the policy.
4. Replay: move the arrival slider and inspect real flips/budget use.
5. Log out; sign in as an employee, upload a real receipt, see its actual ID and pending status.
6. After actual worker processing/import and reevaluation, refresh employee history and reviewer results.

No branch has been pushed or merged into main automatically. See `OWNERSHIP.md` for preserved developer boundaries.
