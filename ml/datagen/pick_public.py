"""Copy manually matched public receipts only from held-out source lists.

Assignments JSON is a list of {scenario_id, record_id, verified_fields: true}.
The verification flag records a human check that the image matches the scenario
merchant, date, currency, total, and planted issue.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from ml.datagen.render import load_scenarios


def copy_public(scenarios: list[dict], assignments: list[dict], split_manifest: dict,
                images_dir: Path, index_path: Path) -> dict:
    by_scenario = {row["scenario_id"]: row for row in scenarios}
    by_record = {row["record_id"]: row for row in split_manifest["rows"]}
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"images": []}
    existing = {entry["image_id"] for entry in index["images"]}
    used_records = set()
    planned = []
    for assignment in assignments:
        scenario_id = assignment["scenario_id"]
        record_id = assignment["record_id"]
        if scenario_id not in by_scenario or record_id not in by_record:
            raise ValueError(f"Unknown scenario or source record: {scenario_id}, {record_id}")
        if scenario_id in existing or record_id in used_records:
            raise ValueError(f"Repeated scenario or source receipt: {scenario_id}, {record_id}")
        if assignment.get("verified_fields") is not True:
            raise ValueError(f"Source fields have not been checked against scenario {scenario_id}")
        scenario, record = by_scenario[scenario_id], by_record[record_id]
        if record["split"] not in {"test", "unseen_real"}:
            raise ValueError(f"Public source is not held out: {record_id}")
        kind = scenario.get("scenario_type")
        source, label = record["source"], record["label"]
        if kind == "ai_generated":
            valid = source == "gpt4o-receipt" and label == "fake"
        elif kind == "forged":
            valid = source == "find_it_again" and label == "forged"
        else:
            valid = source in {"sroie", "cord_v2", "express_expense"} and label == "real"
        if not valid:
            raise ValueError(f"Source/label incompatible with scenario {scenario_id}: {source}, {label}")
        source_path = Path(record["image_path"])
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != record["image_sha256"]:
            raise ValueError(f"Source image changed after split generation: {record_id}")
        target = images_dir / f"{scenario_id}{source_path.suffix.lower()}"
        if target.exists() and target.read_bytes() != source_path.read_bytes():
            raise FileExistsError(target)
        planned.append((scenario_id, scenario, record, source_path, target))
        existing.add(scenario_id)
        used_records.add(record_id)
    for scenario_id, scenario, record, source_path, target in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source_path, target)
        source = record["source"]
        index["images"].append({"image_id": scenario_id, "file": target.name,
                                "source": source, "source_id": record["source_id"],
                                "scenario_id": scenario_id,
                                "planted_problem": scenario.get("planted_issue"),
                                "related_ids": scenario.get("related_ids", [])})
    index["images"].sort(key=lambda item: item["image_id"])
    index["pending_public_scenarios"] = sorted(set(index.get("pending_public_scenarios", [])) - existing)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--images-dir", type=Path, default=Path("data/month/images"))
    parser.add_argument("--index", type=Path, default=Path("data/month/images_index.json"))
    args = parser.parse_args()
    result = copy_public(load_scenarios(args.scenarios),
                         json.loads(args.assignments.read_text(encoding="utf-8")),
                         json.loads(args.split_manifest.read_text(encoding="utf-8")),
                         args.images_dir, args.index)
    print(f"Indexed {len(result['images'])} images; "
          f"{len(result.get('pending_public_scenarios', []))} public scenarios remain")


if __name__ == "__main__":
    main()
