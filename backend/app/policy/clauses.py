"""Numbered policy clauses, preserving source text for grounding."""

import re
from ..contracts.policy import Clause


def split_clauses(text: str) -> list[Clause]:
    matches = list(re.finditer(r"^## (\d+\.\d+) [^\n]+\n", text, re.M))
    clauses = [
        Clause(
            clause_id=m.group(1),
            text=text[
                m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)
            ].strip(),
        )
        for i, m in enumerate(matches)
    ]
    if not clauses or len({c.clause_id for c in clauses}) != len(clauses):
        raise ValueError("Policy needs unique numbered ## clauses")
    return clauses
