from ..contracts.decision import EvaluationInput, TimelineEvent, Flip
from .evaluate import evaluate_month


def build_timeline(inp: EvaluationInput | dict) -> list[TimelineEvent]:
    inp = EvaluationInput.model_validate(inp)
    events = []
    previous = {}
    arrived = []
    for sub in sorted(inp.submissions, key=lambda s: (s.submitted_at, s.receipt_id)):
        arrived.append(sub)
        # An explicit prefix distinguishes simultaneous arrivals deterministically.
        partial = inp.model_copy(update={"submissions": list(arrived)})
        result = evaluate_month(partial)
        current = {d.receipt_id: d for d in result.decisions}
        if sub.receipt_id not in current:
            continue
        flips = []
        for rid, old in sorted(previous.items()):
            new = current[rid]
            if old.verdict != new.verdict or old.proposed != new.proposed:
                added = [
                    r.code
                    for r in new.reasons
                    if r.code not in {x.code for x in old.reasons}
                ]
                flips.append(
                    Flip(
                        receipt_id=rid,
                        from_verdict=old.verdict,
                        to=new.verdict,
                        reason=added[0] if added else "REEVALUATED",
                    )
                )
        events.append(
            TimelineEvent(
                seq=len(events) + 1,
                submitted_at=sub.submitted_at,
                receipt_id=sub.receipt_id,
                verdict_at_arrival=current[sub.receipt_id].verdict,
                flips=flips,
            )
        )
        previous = current
    return events
