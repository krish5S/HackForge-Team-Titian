"""Regression checks for photographed copies with unreliable OCR merchants."""

from backend.app.pipeline.duplicates import find_duplicates


def _receipt(identifier: str, merchant: str, phash: str) -> dict:
    return {"receipt_id": identifier, "file_sha256": identifier,
            "extraction": {"merchant_name": merchant}, "fx": {},
            "fingerprints": {"merchant_norm": merchant.lower(), "phash": phash}}


def test_shared_ocr_and_image_recovers_misread_merchant():
    left = _receipt("a", "1 sam da sod mineral water", "b1c2e5ba1996cbc2")
    right = _receipt("b", "hni", "b9d2e5ba1996c8c2")
    text = "1 SAM DA SOD MINERAL WATER 16,000 2 TWIST DONUT 18,000 TOTAL 34,000 CASH 50,000"
    found = find_duplicates([left, right], {"a": text, "b": "HnI " + text})
    assert [(row["receipt_id"], row["duplicate_of"]) for row in found] == [("b", "a")]


def test_shared_ocr_recovers_photo_outside_standard_phash_limit():
    left = _receipt("a", "udg gr tlur asin", "cb9b5ec62ccc64c4")
    right = _receipt("b", "udg gr tlur asin", "cb8957c339c87d84")
    text = "UDG GR TLUR ASIN 165,000 SAPO TH SEAFOOD 129,000 TOTAL 294,000 " * 2
    found = find_duplicates([left, right], {"a": text, "b": text})
    assert [(row["receipt_id"], row["duplicate_of"]) for row in found] == [("b", "a")]


def test_unreadable_images_do_not_match_from_phash_alone():
    left = _receipt("a", "", "8f1e9649e51e8cb4")
    right = _receipt("b", "", "8f1e9649e51a9cb4")
    assert find_duplicates([left, right], {"a": "BR", "b": "n"}) == []
