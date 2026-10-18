# Text-only receipt reader

Set `RECEIPT_LLM_ENDPOINT` to an HTTP(S) endpoint that accepts a JSON POST with
`task`, `ocr_text`, and `fields`, and returns a JSON object containing any of
`category`, `line_items`, `city`, `country`, `guest_count`, `total`,
`transaction_date`, and `itemization`. Set `RECEIPT_LLM_API_KEY` if the endpoint
requires a bearer token. Only OCR text is sent. Successful responses are cached
by the original file's SHA-256 hash.

Without an endpoint, Reader B returns an empty result and the pattern reader
provides conservative fields and line items.

## Policy compiler

`compile_policy_text(text, temperature, timeout)` is the callback Dev 2's compiler
expects. Wire it once at startup:

```python
from backend.app.llm.client import compile_policy_text
from backend.app.policy import configure_compiler
configure_compiler(compile_policy_text)
```

It posts `policy_text` and the task above to the same endpoint and returns
`{"sentences": [...], "rules": [...]}`. Without an endpoint it raises, and the
compiler reports `COMPILER_UNAVAILABLE` while the hand-written rules stay active.
