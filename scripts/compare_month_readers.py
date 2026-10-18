"""Compare pattern and LayoutLM total/date accuracy on a finalized test month."""

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import tempfile

from backend.app.pipeline.layoutlm_reader import read_fields as read_layoutlm
from backend.app.pipeline.normalize import save_normalized
from backend.app.pipeline.ocr import extract_text
from backend.app.pipeline.reader_a import read_fields as read_patterns


def _load_scenarios(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        import yaml
        payload = yaml.safe_load(raw)
    return payload["scenarios"] if isinstance(payload, dict) else payload


def _same(field: str, actual: str, expected: str) -> bool:
    if field == "total":
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except InvalidOperation:
            return False
    return str(actual) == str(expected)


def switch_reason(pattern: dict, layout: dict, enabled: bool) -> str:
    if enabled:
        return "LayoutLM improves total/date without regression"
    worse = [field for field in pattern if layout[field] is None or
             (pattern[field] is not None and layout[field] < pattern[field])]
    if worse:
        return "LayoutLM regresses on " + ", ".join(worse) + "; pattern reader kept"
    return "LayoutLM does not improve total/date; pattern reader kept"


def compare(index_path: Path, images_dir: Path, scenarios_path: Path, metrics_path: Path) -> dict:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    images = index["images"]
    scenarios = {row["scenario_id"]: row for row in _load_scenarios(scenarios_path)}
    source_counts = Counter(row["source"] for row in images)
    real_count = sum(source_counts[name] for name in ("sroie", "cord_v2", "express_expense"))
    public_rows = [row for row in images if row["source"] != "rendered"]
    if (len(images) != 100 or len(scenarios) != 100 or index.get("pending_public_scenarios") or
            real_count < 55 or source_counts["find_it_again"] < 6 or
            source_counts["gpt4o-receipt"] < 4 or
            any(row.get("verified_fields") is not True for row in public_rows)):
        raise ValueError("Reader switch requires the finalized 100-receipt test month")
    counts = {reader: {field: {"correct": 0, "total": 0} for field in ("total", "transaction_date")}
              for reader in ("pattern", "layoutlm")}
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        for image in images:
            scenario = scenarios[image["scenario_id"]]
            source = images_dir / image["file"]
            normalized = work / f"{image['scenario_id']}.jpg"
            save_normalized(source, normalized)
            ocr = extract_text(normalized)
            predictions = {"pattern": read_patterns(ocr),
                           "layoutlm": read_layoutlm(normalized, ocr, force=True)}
            for field in ("total", "transaction_date"):
                expected = scenario.get(field)
                if not expected:
                    continue
                for reader, prediction in predictions.items():
                    counts[reader][field]["total"] += 1
                    counts[reader][field]["correct"] += int(_same(field, prediction.get(field, ""), expected))
    accuracy = {reader: {field: value["correct"] / value["total"] if value["total"] else None
                         for field, value in fields.items()}
                for reader, fields in counts.items()}
    pattern, layout = accuracy["pattern"], accuracy["layoutlm"]
    enabled = (all(layout[field] is not None and pattern[field] is not None and
                   layout[field] >= pattern[field] for field in pattern) and
               any(layout[field] > pattern[field] for field in pattern))
    result = {"counts": counts, "accuracy": accuracy, "model_switch_enabled": enabled,
              "model_switch_reason": switch_reason(pattern, layout, enabled)}
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics.update({"test_month_comparison": result, "model_switch_enabled": enabled,
                    "model_switch_reason": result["model_switch_reason"]})
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("data/month/images_index.json"))
    parser.add_argument("--images", type=Path, default=Path("data/month/images"))
    parser.add_argument("--scenarios", type=Path, default=Path("data/month/scenarios.yaml"))
    parser.add_argument("--metrics", type=Path, default=Path("data/models/layoutlm_metrics.json"))
    args = parser.parse_args()
    print(json.dumps(compare(args.index, args.images, args.scenarios, args.metrics), indent=2))
