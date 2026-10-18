"""Optional text-only receipt reader. The endpoint accepts OCR text as JSON."""

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def extract_receipt_fields(ocr_text: str, file_sha256: str, cache_dir: Path) -> dict[str, Any]:
    """Cache model JSON by source-file hash; never send the image to the endpoint."""
    cache_path = cache_dir / f"{file_sha256}.json"
    if cache_path.is_file():
        result = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(result, dict):
            return result
        raise ValueError(f"Invalid cached model response: {cache_path}")

    endpoint = os.environ.get("RECEIPT_LLM_ENDPOINT")
    if not endpoint:
        return {}
    request_body = json.dumps({
        "task": "Extract receipt fields as JSON. Use only supplied OCR text; return null for unknown fields.",
        "ocr_text": ocr_text,
        "fields": ["category", "line_items", "city", "country", "guest_count",
                   "total", "transaction_date", "itemization"],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("RECEIPT_LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['RECEIPT_LLM_API_KEY']}"
    request = Request(endpoint, data=request_body, headers=headers, method="POST")
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Receipt model must return a JSON object")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


POLICY_TASK = (
    "Compile this expense policy. Return a JSON object with two lists. "
    "'sentences': one entry per sentence of the policy, exactly as written, as "
    "{clause_id, text, kind} where kind is 'rule', 'definition' or 'info'. "
    "'rules': one entry per enforceable rule as {rule_type, clause_id, source_quote, summary, "
    "category, parameters}. rule_type is one of MONTHLY_CAP, CITY_DAILY_CAP, LOCAL_MEAL, "
    "EXCLUDE_ITEMS, CLIENT_DETAILS, APPROVAL_THRESHOLD, ITEMIZATION, TIP_LIMIT, "
    "SUBMISSION_DEADLINE, EVIDENCE_REVIEW. category is one of ALL, MEALS, ENTERTAINMENT, "
    "TRAVEL, LODGING, OFFICE. source_quote must be copied verbatim from the clause. "
    "parameters may hold amount (string with two decimals), cities (name to amount), "
    "item_classes, fraction, days, risk_threshold. Do not invent rules for vague wording."
)


def compile_policy_text(text: str, temperature: float = 0.7, timeout: float = 80) -> dict[str, Any]:
    """Callback for policy.compiler.configure_compiler: one uncached model run.

    Raises RuntimeError when no endpoint is configured, which the compiler
    reports as COMPILER_UNAVAILABLE instead of inventing rules.
    """
    endpoint = os.environ.get("RECEIPT_LLM_ENDPOINT")
    if not endpoint:
        raise RuntimeError("No text model configured (set RECEIPT_LLM_ENDPOINT)")
    body = json.dumps({"task": POLICY_TASK, "policy_text": text,
                       "temperature": temperature}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("RECEIPT_LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['RECEIPT_LLM_API_KEY']}"
    request = Request(endpoint, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Policy model must return a JSON object")
    return result
