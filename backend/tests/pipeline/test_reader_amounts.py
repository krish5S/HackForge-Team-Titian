"""Common printed whole-number prices must keep their thousands separators."""

from backend.app.pipeline.reader_a import _amount, read_fields


def test_grouped_whole_amounts():
    assert _amount("TOTAL 34,000") == "34000"
    assert _amount("TOTAL 43.636") == "43636"
    assert _amount("TOTAL 1,234.56") == "1234.56"
    assert _amount("TOTAL 12,50") == "12.50"


def test_tax_percent_does_not_replace_amount():
    fields = read_fields({"lines": [
        {"text": "SUBTOTAL", "confidence": 1},
        {"text": "43.636", "confidence": 1},
        {"text": "TAX 10.00 %", "confidence": 1},
        {"text": "4.364", "confidence": 1},
        {"text": "GRAND TOTAL", "confidence": 1},
        {"text": "50.000", "confidence": 1},
    ]})
    assert fields["subtotal"] == "43636"
    assert fields["tax"] == "4364"
    assert fields["total"] == "50000"


def test_currency_prefixes_in_ocr_text():
    fields = read_fields({"lines": [{"text": "RM 72.74"}, {"text": "Rp. 34,000"}]})
    assert fields["currency"] == "MYR"
