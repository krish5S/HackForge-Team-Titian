"""Conservative pattern reader for PaddleOCR text and boxes."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

MONEY = re.compile(r"(?<!\d)(?:[$€£₹]\s*)?(-?(?:\d{1,3}(?:,\d{3})+(?:\.\d{2})?|"
                   r"\d{1,3}(?:\.\d{3})+|\d+\.\d{2}|\d+,\d{2}))(?![\d.,])")
DATE = re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
TIME = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b")
FIELD_LABELS = {"subtotal": ("subtotal", "sub total"), "tax": ("tax", "gst", "vat", "sgst", "cgst", "igst"),
                "tip": ("tip", "gratuity"), "other_charges": ("service charge", "other charge", "other"),
                "total": ("grand total", "amount due", "total", "balance due")}


def _amount(text: str) -> str | None:
    matches = [match for match in MONEY.finditer(text)
               if not re.match(r"\s*%", text[match.end():])]
    if not matches:
        return None
    value = matches[-1].group(1)
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d{2})?", value):
        value = value.replace(",", "")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", value):
        value = value.replace(".", "")
    elif "," in value:
        value = value.replace(",", ".")
    return value


def _label_amount(text: str) -> str | None:
    """Whole prices are allowed only in an already identified amount context."""
    amount = _amount(text)
    if amount is not None:
        return amount
    match = re.search(r"(?:^|[:\s])([0-9]+)\s*(?:USD|EUR|GBP|INR|IDR|MYR)?$", text, re.I)
    return f"{int(match.group(1))}.00" if match else None


def _box(value: Any) -> list[int] | None:
    try:
        if len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
            return [int(v) for v in value]
        x = [float(point[0]) for point in value]
        y = [float(point[1]) for point in value]
        return [int(min(x)), int(min(y)), int(max(x)), int(max(y))]
    except (TypeError, ValueError, IndexError):
        return None


def reading_rows(lines):
    """Join OCR boxes on the same printed row; preserve unboxed input order."""
    if not lines or any(_box(line.get("box")) is None for line in lines):
        return lines
    rows = []
    for line in sorted(lines, key=lambda x: (_box(x['box'])[1] + _box(x['box'])[3]) / 2):
        box = _box(line['box']); center = (box[1] + box[3]) / 2
        if rows and abs(center - rows[-1][0]) <= .45 * min(box[3] - box[1], rows[-1][1]):
            rows[-1][2].append(line)
        else:
            rows.append((center, box[3] - box[1], [line]))
    result = []
    for _, _, row in rows:
        row.sort(key=lambda line: _box(line['box'])[0])
        boxes = [_box(line['box']) for line in row]
        result.append({'text': ' '.join(str(line['text']) for line in row),
                       'confidence': min(float(line.get('confidence', 0)) for line in row),
                       'box': [min(b[0] for b in boxes), min(b[1] for b in boxes),
                               max(b[2] for b in boxes), max(b[3] for b in boxes)]})
    return result


def read_fields(ocr: dict[str, Any]) -> dict[str, Any]:
    lines = reading_rows(ocr.get("lines") or [])
    result: dict[str, Any] = {"confidence": {}, "boxes": {}}
    component_taxes = {}
    for index, line in enumerate(lines):
        text = str(line.get("text", "")).strip()
        lower = text.lower().replace("v.a.t.", "vat").replace("v.a.t", "vat")
        if not text:
            continue
        is_field_label = any(re.search(r"\b" + re.escape(label) + r"\b", lower)
                             for labels in FIELD_LABELS.values() for label in labels)
        if ("merchant_name" not in result and len(text) >= 3 and not is_field_label
                and not MONEY.fullmatch(text) and not DATE.search(text)):
            result["merchant_name"] = text
        all_label_re = r"\b(grand total|sub\s*total|amount due|balance due|total|tax invoice|tax|gst|vat|sgst|cgst|igst|tip|gratuity|service charge|other charge)\b"
        positions = [(m.start(), m.group(0)) for m in re.finditer(all_label_re, text, re.I)]
        for field, labels in FIELD_LABELS.items():
            matched_label = next((label for label in labels if re.search(r"\b" + re.escape(label) + r"\b", lower)), None)
            if not matched_label:
                continue
            if field == "total" and re.search(r"\bsub\s*total\b", lower) and not re.search(r"(?<!\bsub\s)(?<!\bsub)total\b", lower):
                continue
            if field == "tax" and re.search(r"\b(?:tax\s+invoice|(?:gst|tax|vat)\s*(?:no|id|number|registration))\b", lower):
                continue
            amount_line = line
            matching_pos = [pos for pos, lbl in positions if re.search(r"\b" + re.escape(matched_label) + r"\b", lbl, re.I)]
            if matching_pos:
                pos = matching_pos[-1]
                next_positions = [p for p, _ in positions if p > pos]
                end_pos = min(next_positions) if next_positions else len(text)
                amount = _label_amount(text[pos:end_pos])
            else:
                amount = _label_amount(text)
            if amount is None and index + 1 < len(lines):
                following = lines[index + 1]
                following_text = str(following.get("text", "")).strip()
                if re.fullmatch(r"(?:[$€£₹]\s*)?\d[\d,.]*\s*(?:USD|EUR|GBP|INR|IDR|MYR)?", following_text, re.I):
                    amount = _label_amount(following_text)
                    amount_line = following
            if amount is None:
                continue
            if field == "tax":
                component = re.search(r"\b(sgst|cgst|igst|vat)\b", lower)
                if component:
                    component_taxes[(f'vat-{index}' if component.group(1) == 'vat' else component.group(1))] = Decimal(amount)
                    amount = format(sum(component_taxes.values()), ".2f")
            result[field] = amount
            result["confidence"][field] = float(amount_line.get("confidence", 0.0))
            box = _box(amount_line.get("box"))
            if box:
                result["boxes"][field] = box
        if "transaction_date" not in result:
            match = DATE.search(text)
            if match:
                raw = match.group(1)
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
                            "%m-%d-%Y", "%d-%m-%Y", "%m/%d/%y", "%d/%m/%y"):
                    try:
                        result["transaction_date"] = datetime.strptime(raw, fmt).date().isoformat()
                        result["confidence"]["transaction_date"] = float(line.get("confidence", 0.0))
                        box = _box(line.get("box"))
                        if box:
                            result["boxes"]["transaction_date"] = box
                        break
                    except ValueError:
                        continue
        if "transaction_time" not in result:
            match = TIME.search(text)
            if match:
                raw_time = match.group(0)
                meridiem = re.search(r"\b(AM|PM)\b", text, re.I)
                if meridiem:
                    try:
                        result["transaction_time"] = datetime.strptime(raw_time + " " + meridiem.group(1).upper(),
                            "%I:%M:%S %p" if raw_time.count(":") == 2 else "%I:%M %p").strftime("%H:%M")
                    except ValueError:
                        pass
                else:
                    result["transaction_time"] = raw_time[:5]
        if "card_last4" not in result:
            match = re.search(r"(?:card|visa|mastercard|amex|\*{4})\D{0,20}(\d{4})\b", lower)
            if match:
                result["card_last4"] = match.group(1)
        if "receipt_number" not in result:
            match = re.search(r"\b(?:receipt|invoice|bill)\s*(?:no\.?|#|number|:)?\s*([a-z0-9_-]{3,})", lower)
            if match:
                result["receipt_number"] = match.group(1).upper()
        if "currency" not in result:
            for marker, currency in (("₹", "INR"), ("€", "EUR"), ("£", "GBP"), ("$", "USD")):
                if marker in text:
                    result["currency"] = currency
                    break
            for code in ("USD", "EUR", "GBP", "INR", "IDR", "MYR"):
                if re.search(r"\b" + code + r"\b", text.upper()):
                    result["currency"] = code
                    break
            if not result.get("currency") and re.search(r"\bRM\s*-?\d", text, re.I):
                result["currency"] = "MYR"
            if not result.get("currency") and re.search(r"\bRP\.?\s*-?\d", text, re.I):
                result["currency"] = "IDR"
        if "city" not in result:
            location = re.fullmatch(r"\s*([A-Za-z][A-Za-z .'-]{1,40}),\s*([A-Z]{2,3})\s*", text)
            if location:
                result["city"] = location.group(1).strip()
                result["country"] = location.group(2)
    items = []
    for index, line in enumerate(lines):
        description = str(line.get("text", "")).strip()
        lower = description.lower().replace("v.a.t.", "vat").replace("v.a.t", "vat")
        if (not re.search(r"[a-zA-Z]", description) or
                any(re.search(r"\b" + word + r"\b", lower) for word in
                    ("merchant", "receipt", "invoice", "date", "time", "subtotal",
                     "tax", "gst", "sgst", "cgst", "igst", "vat", "service", "tip", "total", "other", "balance", "card", "thank"))):
            continue
        amount_match = MONEY.search(description)
        if amount_match:
            prefix = description[:amount_match.start()].strip(" -:.")
            if not prefix:
                continue
            description = prefix
            amount = _amount(amount_match.group(0))
        elif index + 1 < len(lines):
            next_text = str(lines[index + 1].get("text", "")).strip()
            if not re.fullmatch(r"(?:[$€£₹]\s*)?\d[\d,.]*\s*(?:USD|EUR|GBP|INR|IDR|MYR)?", next_text, re.I):
                continue
            amount = _amount(next_text)
        else:
            continue
        if amount is None:
            continue
        item_class = ("ALCOHOL" if re.search(r"\b(beer|wine|vodka|whisky|whiskey|gin|rum|cocktail)\b", lower)
                      else "FOOD" if re.search(r"\b(food|meal|lunch|dinner|breakfast)\b", lower)
                      else "OTHER")
        items.append({"description": description, "amount": amount, "item_class": item_class})
    if items:
        result["line_items"] = items
        try:
            if len(items) >= 2 and sum(Decimal(item["amount"]) for item in items) == Decimal(result["subtotal"]):
                result["itemization"] = "FULL"
        except (InvalidOperation, KeyError):
            pass
    return result
