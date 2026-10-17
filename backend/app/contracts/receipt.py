from typing import Any, TypedDict


class LineItem(TypedDict):
    description: str
    amount: str
    item_class: str


class Extraction(TypedDict):
    merchant_name: str
    receipt_number: str
    card_last4: str
    transaction_date: str
    transaction_time: str
    city: str
    country: str
    currency: str
    subtotal: str
    tax: str
    tip: str
    other_charges: str
    total: str
    line_items: list[LineItem]
    itemization: str
    category: str
    guest_count: int
    confidence: dict[str, float]
    boxes: dict[str, list[int]]
    readers: dict[str, dict[str, Any]]


class ValidationCheck(TypedDict):
    name: str
    expected: str
    printed: str
    passed: bool


class Validation(TypedDict):
    checks: list[ValidationCheck]


class FX(TypedDict):
    base_currency: str
    rate: str
    total_base: str


class Fingerprints(TypedDict):
    phash: str
    merchant_norm: str


class Forensics(TypedDict):
    score: int
    cnn_fake_probability: float
    signals: list[Any]


class ProcessedReceipt(TypedDict):
    receipt_id: str
    file_sha256: str
    is_receipt: bool
    extraction_status: str
    extraction: Extraction
    validation: Validation
    fx: FX
    fingerprints: Fingerprints
    forensics: Forensics