from ..explain import reason


def evaluate(rule, ctx, ex, claimed):
    s = ctx["submission"]
    hits = []
    if s.client_meal and not (s.client_name or "").strip():
        hits.append(
            reason(rule, "MISSING_CLIENT_NAME", "REVIEW", "Add the client name.")
        )
    if s.client_meal and s.attendee_count is None:
        hits.append(
            reason(rule, "MISSING_ATTENDEE_COUNT", "REVIEW", "Add the attendee count.")
        )
    count = s.attendee_count or ex.get("guest_count")
    if (
        count
        and count > 1
        and (
            len(s.attendee_names) != count
            or not all(n.strip() for n in s.attendee_names)
        )
    ):
        hits.append(
            reason(
                rule,
                "MISSING_ATTENDEE_NAMES",
                "REVIEW",
                "Add attendee names matching the count.",
            )
        )
    return hits
