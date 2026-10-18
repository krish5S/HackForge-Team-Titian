def budget(rule, ctx, sub):
    if ctx["day"] is None:
        return None
    month = ctx["day"].strftime("%Y-%m")
    return (
        (sub.employee_id, rule.rule_type, rule.category, month),
        f"{rule.category} {month}",
        rule.parameters.amount,
    )
