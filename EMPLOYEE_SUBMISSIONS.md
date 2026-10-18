# Employee receipt submissions

The protected `/employee` page uses the existing dashboard styling and session system. Employees provide a purpose plus optional client name, attendee names/count, and notes. No identity, amount, or date is inferred or manually substituted for extraction.

## API

All routes below require a linked EMPLOYEE account. Ownership comes exclusively from the session. A foreign submission and an unknown ID return the same 404 response.

- `POST /api/employee/submissions`: multipart `file`, `purpose`, optional `client_name`, `attendee_names`, `attendee_count`, `notes`. Requires a trusted Origin and a 16–128 character `Idempotency-Key` header. Returns the saved submission, including its real `id`.
- `GET /api/employee/submissions`: this employee's history, newest first.
- `GET /api/employee/submissions/{id}`: context, status, and any real evaluation result.
- `GET /api/employee/submissions/{id}/file`: owned original file, validated storage path, correct MIME type, no caching.

JPEG, PNG, WebP, and nonencrypted PDFs are accepted, up to 10 MiB. Extensions are checked against parsed contents. The entire multipart request is bounded at 11 MiB, including streamed requests. File storage uses generated names under `data/month/images/uploads/`, which is Git-ignored. Existing original-file handling can serve these paths after the pipeline creates a Receipt.

## Storage and retries

The existing `Submission` table stores employee context; the new `submission_uploads` table stores MIME type, original name, byte count, request digest, and account-scoped idempotency key. The repeatable migration adds `user_id`, `file_sha256`, `processing_status`, and `processing_error` to the existing upload metadata table. It preserves all submission rows and original files. Normal API startup runs this migration.

A complete file is written and flushed before committing its database reference. Failed writes/transactions roll back and clean up the attempt's file. Concurrent identical retries resolve to one saved submission. Reusing a key with different content returns 409. A different key deliberately submits a new expense even if the file is identical; duplicate-claim judgments are left to evaluation. A process crash between file write and database commit can leave an unreferenced generated file; it never creates a successful database reference to a partial file.

The browser freezes the original request after an uncertain failure and retains the entered information. Retry resends that request and key. Session storage retains only a random key and SHA-256 digest, scoped to the user; reselecting the same file/details after a tab reload reuses it. Form contents/files are not persisted across reload. Starting a new submission after an uncertain outcome requires an explicit confirmation. Confirmed success clears the form and refreshes history.

## Processing boundary

Uploads create no Receipt, OCR output, approval, or policy result. Initial status is **Uploaded — awaiting processing**. If the external pipeline creates a Receipt linked to the existing submission ID, status becomes **Processed — awaiting evaluation**. A Decision in the globally latest completed EvaluationRun (the same selection as the reviewer queue) provides the actual verdict, amounts, reasons, and counterfactuals. History refreshes every 30 seconds and has a manual Refresh action.

## Run and verify

From the repository root:

```sh
.venv/bin/python -m pip install -r backend/requirements/api.txt
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
npm --prefix frontend run dev
```

Restart an already-running backend to load the routes and register the new table. Use `http://localhost:5173` with the existing `http://localhost:8001/api` configuration.

```sh
PYTHONPATH=backend:. .venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend run build
npm --prefix frontend run lint
cd frontend
node tests/submission.mjs
node tests/session.mjs
```

Tests use temporary databases and files, including two employee identities. Coverage includes ownership and role checks, context validation, all file formats, file/body size limits, concurrent idempotency, distinct deliberate submissions, disk failure, missing files, and real stored evaluation state. Frontend checks cover retry-key persistence/isolation/rotation and existing authentication behavior. Browser interactions, desktop/mobile rendering, and upload with a real account remain unverified; no real account, receipt, or database data was replaced for testing.


## Completion audit and migration

Existing form layout, ownership checks, multipart storage, previews, safe retries, and session integration were preserved. This audit adds a standalone file-content SHA-256, scopes new idempotency keys to the authenticated account (including accounts sharing an Employee record), aligns evaluation selection with the reviewer queue, exposes null monetary fields explicitly, and adds history amounts plus stored processing failures. Frontend validation now rejects mismatched filename/type combinations and whitespace-only purposes.

No additional dependencies are needed beyond the existing requirements. To migrate explicitly from the repository root:

```sh
.venv/bin/python scripts/migrate_uploads.py
```

Restart FastAPI afterwards to load the updated code. The migration also runs on normal startup. It uses an immediate SQLite transaction, checks existing columns, and can be repeated. It backfills file hashes from existing original files where available, leaving missing-file hashes null. Legacy retry attribution is backfilled only for an unambiguous account link. Ambiguous legacy retries return a conflict rather than creating another submission. The real database was inspected read-only during this audit; migration behavior was verified with temporary legacy-schema data.

## Exact worker dependencies

**Dev 1:** consume the existing `Submission` row and project-relative `file_path`, preserve its ID, read the supporting `employee_fields_json`, and create the actual `Receipt` with that `submission_id` after extraction succeeds. The worker may update `SubmissionUpload.processing_status` to `PROCESSING`, `PROCESSED`, or `FAILED` at actual transitions. On failure, `processing_error` must be a safe, employee-readable explanation, not a stack trace or internal file path. Clear it when retrying/succeeding. A real Receipt is evidence of processing for legacy records whose tracking row remains UPLOADED. No timers or employee-accessible state-update route exist.

**Dev 2:** save real `Decision` records linked to Receipt IDs and the applicable `EvaluationRun`; mark the run COMPLETED only when complete. Employees and reviewers select the same globally latest completed run. An older decision is not substituted if that run omits a receipt. Supply decimal strings and authoritative `currency` in `amounts_json`; missing values stay null and extraction currency is never guessed for reimbursements.

Processing state and verdict are separate response fields. `status=EVALUATED` requires an applicable saved Decision; `processing_status` remains the stored/derived processing state. The UI displays PROCESSING/FAILED only when actually stored. No OCR, evaluation worker, or automatic approvals have been introduced.

Additional isolated checks cover same-employee/different-account retry keys, legacy retry behavior, file-content hashing, DB reconnect persistence, saved failure explanations, latest-run alignment, and running the additive migration twice. Browser layout and real-account interactive submission remain unverified.
