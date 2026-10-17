import json
from pathlib import Path
import pytest
from scripts.build_month import build_month

ROOT = Path(__file__).resolve().parents[3]


def test_missing_image_handoff_does_not_write(tmp_path):
    index = tmp_path / "images_index.json"
    index.write_text('{"images": []}')
    with pytest.raises(ValueError, match="Missing real image"):
        build_month(ROOT / "data/month/scenarios.yaml", index, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_build_with_explicit_test_images(tmp_path):
    scenarios = json.loads((ROOT / "data/month/scenarios.yaml").read_text())[
        "scenarios"
    ]
    rows = []
    for r in scenarios:
        filename = r["scenario_id"] + ".test"
        (tmp_path / filename).write_text("TEST ONLY image reference")
        rows.append(dict(scenario_id=r["scenario_id"], path=filename))
    index = tmp_path / "images_index.json"
    index.write_text(json.dumps(dict(images=rows)))
    assert (
        build_month(ROOT / "data/month/scenarios.yaml", index, tmp_path / "out") == 100
    )
    answer = json.loads((tmp_path / "out/answer_key.json").read_text())
    assert [a["verdict"] for a in answer] == [
        r["expected"]["verdict"] for r in scenarios
    ]
