from pathlib import Path
from ..contracts.policy import CompiledPolicy
from .validate_rules import validate_rules


def load_fallback(path) -> CompiledPolicy:
    return validate_rules(
        CompiledPolicy.model_validate_json(Path(path).read_text(encoding="utf-8"))
    )
