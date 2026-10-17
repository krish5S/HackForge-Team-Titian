"""Build submissions from scenarios and Dev 1's real image index.

Provisional index shape: {"images": [{"scenario_id": "r_001", "path": "images/001.png"}]}.
Run from repository root: python -m scripts.build_month --help
"""

import argparse
import csv
import json
from pathlib import Path

import yaml

EMPLOYEES = [
    dict(id=f"e_{i + 1:02}", name=name, home_city=city)
    for i, (name, city) in enumerate(
        [
            ("Asha Rao", "New York"),
            ("Ben Tan", "Jakarta"),
            ("Cara Lee", "Kuala Lumpur"),
            ("Dev Shah", "New York"),
            ("Eva Lim", "Jakarta"),
            ("Finn Ray", "New York"),
        ]
    )
]


def build_month(scenarios_path, index_path, output):
    scenarios = yaml.safe_load(Path(scenarios_path).read_text(encoding="utf-8"))[
        "scenarios"
    ]
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))["images"]
    images = {r["scenario_id"]: r["path"] for r in index}
    ids = {r["scenario_id"] for r in scenarios}
    if len(ids) != len(scenarios) or len(images) != len(index):
        raise ValueError("Duplicate scenario/image IDs")
    if ids - images.keys():
        raise ValueError(f"Missing real image handoff: {sorted(ids - images.keys())}")
    for name in images.values():
        path = (Path(index_path).parent / name).resolve()
        root = Path(index_path).parent.resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Image path missing or outside month directory: {name}")
    fields = [
        "receipt_id",
        "employee_id",
        "image_path",
        "channel",
        "submitted_at",
        "client_meal",
        "client_name",
        "attendee_count",
        "attendee_names",
        "approved",
    ]
    manifest = []
    answers = []
    for row in scenarios:
        manifest.append(
            dict(
                receipt_id=row["scenario_id"],
                employee_id=row["employee_id"],
                image_path=images[row["scenario_id"]],
                channel=row["channel"],
                submitted_at=row["submitted_at"],
                client_meal=str(row["client_meal"]).lower(),
                client_name=row["client_name"] or "",
                attendee_count=row["attendee_count"] or "",
                attendee_names=json.dumps(row["attendee_names"]),
                approved=str(row["approved"]).lower(),
            )
        )
        answers.append(dict(receipt_id=row["scenario_id"], **row["expected"]))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows, columns in [
        ("employees.csv", EMPLOYEES, ["id", "name", "home_city"]),
        ("manifest.csv", manifest, fields),
    ]:
        with (output / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    (output / "answer_key.json").write_text(
        json.dumps(answers, indent=2) + "\n", encoding="utf-8"
    )
    return len(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default="data/month/scenarios.yaml")
    parser.add_argument("--index", default="data/month/images_index.json")
    parser.add_argument("--output", default="data/month")
    args = parser.parse_args()
    try:
        count = build_month(args.scenarios, args.index, args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Month build blocked: {exc}\n")
    print(
        f"Built {count} submissions; answer key comes from scenarios, not predictions."
    )


if __name__ == "__main__":
    main()
