"""Deterministic stand-in for Reader B when no text model is configured.

It reads only OCR text. It never claims to be a model answer: the pipeline
records its output under readers["text_rules"], not readers["reader_b"].
Every rule is a plain keyword or pattern, so a result is either found in the
text or left empty.
"""

from decimal import Decimal, InvalidOperation
import re
from typing import Any

CATEGORY_WORDS = {
    "ENTERTAINMENT": ("entertainment", "cinema", "theatre", "theater", "concert", "show ticket", "tickets",
                      "bowling", "arcade", "museum", "amusement", "karaoke", "comedy club"),
    "LODGING": ("hotel", "folio", "room charge", "lodging", "guest room", "resort", "motel"),
    "TRAVEL": ("taxi", "cab fare", "ride fare", "trip fare", "airline", "flight", "railway",
               "train ticket", "car rental", "parking", "toll"),
    "OFFICE": ("stationery", "office supplies", "printer", "toner", "paper ream"),
    "MEALS": ("restaurant", "bistro", "cafe", "coffee", "grill", "kitchen", "diner", "pizza",
              "burger", "bakery", "noodle", "sushi", "dinner", "lunch", "breakfast", "meal",
              "food", "bar &", "eatery"),
}
# First match wins on equal counts: a specific venue beats a generic food word.
CATEGORY_PRIORITY = ("ENTERTAINMENT", "LODGING", "TRAVEL", "OFFICE", "MEALS")
ALCOHOL = re.compile(r"\b(beer|wine|vodka|whisky|whiskey|gin|rum|cocktail|lager|ale|champagne|"
                     r"liquor|sake|tequila|bourbon|brandy|ipa|stout|prosecco|margarita|martini)\b")
FOOD = re.compile(r"\b(food|meal|lunch|dinner|breakfast|burger|pizza|pasta|salad|soup|steak|"
                  r"noodles?|rice|sandwich|coffee|tea|dessert)\b")
GUESTS = re.compile(r"\b(?:party size|guests?|covers|pax|persons?|diners)\s*[:#=-]?\s*(\d{1,2})\b")
CITY_COUNTRY = re.compile(r"^\s*([A-Za-z][A-Za-z .'-]{1,40}),\s*([A-Z]{2,3})\s*$")
CURRENCY_COUNTRY = {"IDR": "ID", "MYR": "MY", "INR": "IN", "GBP": "GB", "EUR": "EU"}


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def infer_category(text: str) -> str:
    lower = text.lower()
    counts = {name: sum(lower.count(word) for word in words) for name, words in CATEGORY_WORDS.items()}
    best = max(counts.values())
    if not best:
        return ""
    return next(name for name in CATEGORY_PRIORITY if counts[name] == best)


def classify_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classified = []
    for item in items:
        description = str(item.get("description", "")).lower()
        item_class = ("ALCOHOL" if ALCOHOL.search(description)
                      else "FOOD" if FOOD.search(description) else item.get("item_class", "OTHER"))
        classified.append({**item, "item_class": item_class})
    return classified


def itemization(items: list[dict[str, Any]], fields: dict[str, Any]) -> str:
    """FULL only when the printed lines add up to the printed pre-tax amount."""
    amounts = [_decimal(item.get("amount")) for item in items]
    if not items or any(amount is None for amount in amounts):
        return ""
    subtotal = _decimal(fields.get("subtotal"))
    if subtotal is None:
        total = _decimal(fields.get("total"))
        extras = [_decimal(fields.get(name) or "0") for name in ("tax", "tip", "other_charges")]
        if total is None or any(extra is None for extra in extras):
            return ""
        subtotal = total - sum(extras)
    return "FULL" if sum(amounts) == subtotal else ""


def infer_fields(ocr: dict[str, Any], reader_a: dict[str, Any]) -> dict[str, Any]:
    """Fill category, city, country, guest count, item classes and itemization from text."""
    lines = [str(line.get("text", "")) for line in ocr.get("lines") or []]
    text = str(ocr.get("full_text") or "\n".join(lines))
    result: dict[str, Any] = {}
    category = infer_category(text)
    if category:
        result["category"] = category
    if not reader_a.get("city"):
        for line in lines:
            match = CITY_COUNTRY.match(line)
            if match:
                result["city"], result["country"] = match.group(1).strip(), match.group(2)
                break
    if not reader_a.get("country") and "country" not in result and reader_a.get("currency") in CURRENCY_COUNTRY:
        result["country"] = CURRENCY_COUNTRY[reader_a["currency"]]
    guests = [int(match.group(1)) for match in GUESTS.finditer(text.lower())]
    if guests:
        result["guest_count"] = max(guests)
    items = classify_items(reader_a.get("line_items") or [])
    if items:
        result["line_items"] = items
        full = itemization(items, reader_a)
        if full:
            result["itemization"] = full
    return result
