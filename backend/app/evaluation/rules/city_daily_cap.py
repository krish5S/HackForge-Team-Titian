def budget(rule, ctx, sub):
    if ctx["trip"] is not True or ctx["day"] is None:
        return None
    city = ctx["city"]
    table = rule.parameters.cities
    cap = next(
        (v for k, v in table.items() if k.casefold() == city.casefold()),
        table["DEFAULT"],
    )
    return (
        (sub.employee_id, rule.rule_type, city.casefold(), ctx["day"].isoformat()),
        f"{city} trip meals, {ctx['day']}",
        cap,
    )
