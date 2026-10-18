"""Convert printed totals using the fixed rates supplied for the test month."""

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_RATES = Path(__file__).resolve().parents[3] / "data" / "fx_rates.csv"


def load_rates(path: Path = DEFAULT_RATES) -> dict[str, Decimal]:
    if not path.is_file():
        raise FileNotFoundError(f"FX rate file missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rates = {}
    for row in rows:
        code = row["currency"].strip().upper()
        if code in rates:
            raise ValueError(f"Repeated FX currency: {code}")
        rate = Decimal(row["rate_to_usd"])
        if rate <= 0:
            raise ValueError(f"FX rate must be positive: {code}")
        rates[code] = rate
    if rates.get("USD") != Decimal("1"):
        raise ValueError("FX file must define USD at rate 1")
    return rates


def convert_total(total: str, currency: str, rates: dict[str, Decimal]) -> dict[str, str]:
    code = currency.upper()
    if code not in rates or not total:
        return {"base_currency": "USD", "rate": "", "total_base": ""}
    try:
        amount = Decimal(total)
    except InvalidOperation:
        return {"base_currency": "USD", "rate": "", "total_base": ""}
    rate = rates[code]
    return {"base_currency": "USD", "rate": str(rate),
            "total_base": f"{amount * rate:.2f}"}
