"""Resolve connected confirmed matches; possible/cross-employee matches stay review."""


def resolve(submissions, candidates):
    subs = {s.receipt_id: s for s in submissions}
    parent = {rid: rid for rid in subs}

    def root(rid):
        while parent[rid] != rid:
            rid = parent[rid]
        return rid

    possible = []
    for c in candidates:
        ids = sorted(set(c.receipt_ids) & subs.keys())
        if len(ids) < 2:
            continue
        if c.confirmed and len({subs[r].employee_id for r in ids}) == 1:
            for rid in ids[1:]:
                parent[root(rid)] = root(ids[0])
        else:
            possible.append(ids)
    groups = {}
    for rid in subs:
        groups.setdefault(root(rid), []).append(rid)
    result = {}

    def order(rid):
        return (subs[rid].submitted_at, rid)

    for ids in groups.values():
        ids.sort(key=order)
        for rid in ids[1:]:
            result[rid] = ("DUPLICATE", "REJECT", ids[0])
    for ids in possible:
        ids.sort(key=order)
        for rid in ids[1:]:
            result.setdefault(rid, ("POSSIBLE_DUPLICATE", "REVIEW", ids[0]))
    return result
