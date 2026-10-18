"""Conservative pattern reader for PaddleOCR text and boxes."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

MONEY = re.compile(r"(?<!\d)(?:[$€£₹]\s*)?(-?\d+(?:,\d{3})*(?:\.\d{2})|-?\d+,\d{2})(?!\d)")
DATE = re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
TIME = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b")
FIELD_LABELS = {"subtotal": ("subtotal", "sub total"), "tax": ("tax", "gst", "vat"),
                "tip": ("tip", "gratuity"), "other_charges": ("service charge", "other charge", "other"),
                "total": ("grand total", "amount due", "total", "balance due")}


def _amount(text: str) -> str | None:
    matches = list(MONEY.finditer(text))
    if not matches:
        return None
    value = matches[-1].group(1)
    value = value.replace(",", ".") if "." not in value else value.replace(",", "")
    return value


def _box(value: Any) -> list[int] | None:
    try:
        if len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
            return [int(v) for v in value]
        x = [float(point[0]) for point in value]
        y = [float(point[1]) for point in value]
        return [int(min(x)), int(min(y)), int(max(x)), int(max(y))]
    except (TypeError, ValueError, IndexError):
        return None


def read_fields(ocr: dict[str, Any]) -> dict[str, Any]:
    lines = ocr.get("lines") or []
    result: dict[str, Any] = {"confidence": {}, "boxes": {}}
    for index, line in enumerate(lines):
        text = str(line.get("text", "")).strip()
        lower = text.lower()
        if not text:
            continue
        is_field_label = any(re.search(r"\b" + re.escape(label) + r"\b", lower)
                             for labels in FIELD_LABELS.values() for label in labels)
        if ("merchant_name" not in result and len(text) >= 3 and not is_field_label
                and not MONEY.fullmatch(text) and not DATE.search(text)):
            result["merchant_name"] = text
        for field, labels in FIELD_LABELS.items():
            if not any(re.search(r"\b" + re.escape(label) + r"\b", lower) for label in labels):
                continue
            if field == "total" and "subtotal" in lower:
                continue
            amount_line = line
            amount = _amount(text)
            if amount is None and index + 1 < len(lines):
                following = lines[index + 1]
                following_text = str(following.get("text", "")).strip()
                if re.fullmatch(r"(?:[$€£₹]\s*)?\d[\d,.]*\s*(?:USD|EUR|GBP|INR|IDR|MYR)?", following_text, re.I):
                    amount = _amount(following_text)
                    amount_line = following
            if amount is None:
                continue
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
                            "%m-%d-%Y", "%d-%m-%Y", "%m/%d/%y"):
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
                result["transaction_time"] = match.group(0)[:5]
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
        if "city" not in result:
            location = re.fullmatch(r"\s*([A-Za-z][A-Za-z .'-]{1,40}),\s*([A-Z]{2,3})\s*", text)
            if location:
                result["city"] = location.group(1).strip()
                result["country"] = location.group(2)
    all_text = str(ocr.get("full_text") or "\n".join(str(line.get("text", "")) for line in lines)).lower()
    if any(word in all_text for word in ("taxi", "hotel", "lodging", "ride fare", "trip fare")):
        result["category"] = "TRAVEL"
    elif any(word in all_text for word in ("restaurant", "bistro", "cafe", "meal", "dinner", "lunch")):
        result["category"] = "MEALS"
    items = []
    for index, line in enumerate(lines):
        description = str(line.get("text", "")).strip()
        lower = description.lower()
        if (not re.search(r"[a-zA-Z]", description) or
                any(re.search(r"\b" + word + r"\b", lower) for word in
                    ("merchant", "receipt", "invoice", "date", "time", "subtotal",
                     "tax", "tip", "total", "other", "balance", "card", "thank"))):
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
