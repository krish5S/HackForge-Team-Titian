from datetime import date, time


def context(receipt, submission, employee):
    ex = receipt.get("extraction") or {}
    city = ex.get("city")
    home = employee.home_city if employee else None
    try:
        day = date.fromisoformat(ex.get("transaction_date", ""))
    except (TypeError, ValueError):
        day = None
    try:
        hour = time.fromisoformat(ex.get("transaction_time") or "").hour
        meal = "BREAKFAST" if hour < 11 else "LUNCH" if hour < 16 else "DINNER"
    except (ValueError, TypeError):
        meal = None
    return dict(
        city=city,
        trip=None if not city or not home else city.casefold() != home.casefold(),
        day=day,
        meal_type=meal,
        category=ex.get("category"),
        submission=submission,
    )
