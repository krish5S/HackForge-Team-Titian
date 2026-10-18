# Shared text LLM client

Both receipt Reader B and Dev 2's policy compiler use `client.py`. Public task
signatures and startup `configure_compiler(compile_policy_text)` wiring are unchanged.
No additional service or SDK is needed; transport uses Python urllib.

## Gemini configuration

Put secrets only in **backend/.env**, never frontend variables. Uncomment actual
assignments: lines starting with `#` are inactive. Placeholder example:

```dotenv
RECEIPT_LLM_PROVIDER=gemini
RECEIPT_LLM_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
RECEIPT_LLM_API_KEY=<your-Gemini-API-key>
RECEIPT_LLM_MODEL=<verified-available-text-model-ID>
```

Gemini uses that fixed endpoint (the endpoint setting may be omitted), requires
bearer authentication, and requires an explicit model. There is no invented default
model or automatic model fallback. Check availability using your own key:

```sh
.venv/bin/python scripts/check_llm.py
```

This loads backend/.env and lists model IDs from Google's OpenAI-compatible models
endpoint without printing the key. Select an available text model using
RECEIPT_LLM_MODEL. Being listed does not guarantee quota or structured-output support;
a successful task call verifies those. Environment variables exported in the process
take precedence over the file.

From the repository root, stop the old backend with Ctrl+C and restart:

```sh
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001 --env-file backend/.env
```

`make backend` now also loads backend/.env when it exists. Importing the client does
not search for environment files. Worker processes need the same backend variables
in their environment; for example, launch the worker through python-dotenv:

```sh
.venv/bin/python -m dotenv -f backend/.env run -- python -m scripts.run_receipt_worker --directory /path/to/bundle
```

The worker still needs its existing OCR/model environment; Gemini does not replace OCR.

## Transport and validation

Gemini receives system task instructions plus a user message containing only the
provided OCR text/field context or policy text. `response_format: json_schema` uses
Pydantic schemas, and returned `choices[0].message.content` is parsed and validated.
Refusals, truncated responses, invalid JSON and invalid schemas fail explicitly.
Receipt fields are restricted to the supported subset, with nullable unknowns and
string monetary values. Reader B's existing conservative fallback handles failures.
No missing receipt facts are intentionally inferred.

Policy output requires nonempty sentence classifications plus a rules list using
Dev 2's actual Rule schema. Its original instructions, temperature and timeout are
preserved. Coverage, source grounding, three-run agreement, conflicts and boundary
checks still execute in Dev 2; transport validation does not activate a policy.
Policy calls are never cached. Failed compilation preserves the existing active
policy and completed evaluation through the existing API transaction logic.

Receipt cache keys include source hash, OCR text, provider, endpoint, model and
schema version/schema. Legacy hash-only caches are not reused. Validated cache writes
are atomic; malformed cache entries are regenerated. Cache keys contain no API key.

Authentication, unsupported model/request and malformed output failures are not
retried. Transient 429/5xx/network/timeouts get at most three attempts within the
caller's timeout budget, with backoff and numeric Retry-After honored. Error messages
do not contain provider response bodies, authorization headers or credentials.

## Existing custom service

Set `RECEIPT_LLM_PROVIDER=custom` (also the backwards-compatible default),
`RECEIPT_LLM_ENDPOINT=<your-custom-JSON-endpoint>` and optionally
`RECEIPT_LLM_API_KEY=<bearer-token>`. No model is required in this mode.
Receipt requests retain `task`, `ocr_text`, `fields`; policy requests retain
`task`, `policy_text`, `temperature`. Both return plain JSON objects matching the
validated task schemas. A local unauthenticated custom endpoint is supported.
Without a custom endpoint, receipt extraction returns an empty result for fallback;
policy compilation reports unavailable.

## Read-only live verification

After configuring a model, use **actual saved OCR text** and the actual numbered
policy source (do not substitute extracted answers for OCR):

```sh
.venv/bin/python scripts/check_llm.py --ocr-file /path/to/actual-ocr.txt --policy-file /path/to/actual-policy.md
```

This checks model availability, exercises extraction in a temporary cache, and runs
the real three-call policy compiler with its checks. It prints status/flag codes only;
it never writes receipts, activates policies or changes evaluation records. Calls
use the configured remote service and may consume quota.

Offline checks: `PYTHONPATH=backend:. .venv/bin/python -m unittest backend.tests.test_llm -q`.

API reference: https://ai.google.dev/gemini-api/docs/openai (structured output and model listing).

## Verified local configuration

On this integration run, the configured key successfully listed models.
`gemini-2.5-flash` was listed but rejected for new users (HTTP 404); Google's response
recommended the also-listed `gemini-3.8-flash`. That model successfully performed
receipt extraction from actual receipt text and a policy translation call, and is
now selected in the ignored backend/.env. This is a verified local selection, not
a hardcoded default or a guarantee of future availability. The receipt smoke check
used macOS Vision OCR into a temporary file because the project's worker OCR cache
was absent; it did not execute or change the production OCR pipeline.

The subsequent real three-run `compile_policy` check returned
`COMPILER_UNAVAILABLE` and no accepted policy. A successful single translation does
not prove agreement or acceptance. No policy was activated and no evaluation was
changed. The compiler intentionally reports a generic unavailable flag for callback
failures; the live check did not establish which of its three calls failed.
