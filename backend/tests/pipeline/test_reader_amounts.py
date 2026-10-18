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


def test_split_subtotal_whole_total_and_component_gst():
    fields = read_fields({"lines": [{"text": text, "confidence": .99} for text in [
        "EXAMPLE CAFE", "Date : 24/02/25", "Sub Total :", "260.00",
        "SGST @2.5% :", "6.50", "CGST @2.5% :", "6.50", "Total :", "273", "(01:21 PM)"]]})
    assert fields["subtotal"] == "260.00"
    assert fields["total"] == "273.00"
    assert fields["tax"] == "13.00"
    assert fields["transaction_date"] == "2025-02-24"
    assert fields["transaction_time"] == "13:21"
    assert not fields.get("line_items")
    assert not fields.get("currency")  # Location/tax labels do not establish printed currency.


def test_subtotal_alone_does_not_supply_total():
    fields = read_fields({"lines": [{"text": "Sub Total : 260.00"}]})
    assert fields["subtotal"] == "260.00"
    assert "total" not in fields


def test_tax_invoice_and_registration_are_not_tax_amounts():
    fields = read_fields({"lines": [{"text": text} for text in
                                  ["TAX INVOICE", "233978", "GST NO: 123456", "Total :", "273"]]})
    assert "tax" not in fields
    assert fields["total"] == "273.00"


def test_split_columns_service_charge_rate_is_not_amount():
    fields = read_fields({"lines": [
        {"text": "Service Charge 010.00 : +", "box": [0, 0, 250, 20]},
        {"text": "201.10", "box": [270, 1, 330, 21]},
        {"text": "V.A.T. 012.50 : +", "box": [0, 30, 250, 50]},
        {"text": "221.51", "box": [270, 31, 330, 51]},
        {"text": "Grand Total :", "box": [0, 70, 250, 90]},
        {"text": "2521.61", "box": [270, 71, 330, 91]},
    ]})
    assert fields["other_charges"] == "201.10"
    assert fields["total"] == "2521.61"
    assert not fields.get("line_items")
