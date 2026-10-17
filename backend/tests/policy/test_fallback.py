from pathlib import Path
import pytest
from backend.app.policy import load_fallback
from backend.app.policy.validate_rules import validate_rules
from backend.app.contracts.policy import CompiledPolicy

ROOT = Path(__file__).resolve().parents[3]


def test_fallback():
    p = load_fallback(ROOT / "data/policy/fallback_rules.json")
    assert len(p.rules) == 10


@pytest.mark.parametrize(
    "change", ["unknown_type", "category", "clause", "amount", "parameters", "scope"]
)
def test_invalid_rules(change):
    p = load_fallback(ROOT / "data/policy/fallback_rules.json").model_dump(mode="json")
    r = p["rules"][0]
    if change == "unknown_type":
        r["rule_type"] = "UNKNOWN"
    if change == "category":
        r["category"] = "UNKNOWN"
    if change == "clause":
        r["clause_id"] = "999"
    if change == "amount":
        r["parameters"]["amount"] = "-1.00"
    if change == "parameters":
        r["parameters"] = {}
    if change == "scope":
        r["scope"] = "unknown"
    with pytest.raises(ValueError):
        validate_rules(CompiledPolicy.model_validate(p))


def test_bad_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{")
    with pytest.raises(ValueError):
        load_fallback(path)
