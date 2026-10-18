"""Resolve held-out public candidates to local files for verified assignment."""

import argparse
import hashlib
import json
from pathlib import Path


def build(candidates_path: Path, source_manifest_path: Path, findit_root: Path) -> dict:
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    sources = {row["record_id"]: row for row in
               json.loads(source_manifest_path.read_text(encoding="utf-8"))["rows"]}
    rows = []
    for group in ("real", "ai_generated"):
        for candidate in candidates[group]:
            row = sources[candidate["record_id"]]
            if row["split"] not in {"test", "unseen_real"}:
                raise ValueError(f"Candidate source is not held out: {row['record_id']}")
            rows.append(row)
    for candidate in candidates["forged"]:
        parent = sources[candidate["parent_record_id"]]
        if parent["source"] != "sroie" or parent["split"] != "test":
            raise ValueError(f"Forged parent leaks into training: {candidate['record_id']}")
        source = (findit_root / candidate["source_id"]).resolve()
        if findit_root.resolve() not in source.parents or not source.is_file():
            raise FileNotFoundError(source)
        rows.append({"record_id": candidate["record_id"], "source": "find_it_again",
                     "source_id": candidate["source_id"], "image_path": str(source),
                     "image_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                     "split": "test", "label": "forged",
                     "parent_record_id": candidate["parent_record_id"]})
    return {"status": "candidate_only", "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=Path("ml/splits/test_month_candidates.json"))
    parser.add_argument("--source-manifest", type=Path,
                        default=Path.home() / "datasets" / "combined_splits.json")
    parser.add_argument("--findit", type=Path,
                        default=Path.home() / "datasets" / "find_it_again" / "findit2")
    parser.add_argument("--output", type=Path,
                        default=Path.home() / "datasets" / "public_month_manifest.json")
    args = parser.parse_args()
    result = build(args.candidates, args.source_manifest, args.findit)
    repository = Path(__file__).resolve().parents[2]
    if args.output.resolve() == repository or repository in args.output.resolve().parents:
        parser.error("Local public manifest contains dataset paths and must stay outside Git")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Resolved {len(result['rows'])} held-out candidate files: {args.output}")
