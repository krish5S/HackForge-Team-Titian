"""Select source-disjoint public candidates before matching scenario fields."""

import argparse
import csv
import json
from pathlib import Path
import random


def select(split_list: Path, findit_root: Path, seed: int = 42) -> dict:
    rows = json.loads(split_list.read_text(encoding="utf-8"))["rows"]
    by_source = {}
    for source in ("sroie", "cord_v2", "express_expense", "gpt4o-receipt"):
        by_source[source] = [row for row in rows if row["source"] == source]
    rng = random.Random(seed)
    real = []
    for source in ("sroie", "cord_v2", "express_expense"):
        eligible = [row for row in by_source[source] if row["split"] in {"test", "unseen_real"}]
        rng.shuffle(eligible)
        if len(eligible) < 20:
            raise ValueError(f"Need 20 held-out real receipts from {source}")
        real.extend({"record_id": row["record_id"], "source": source,
                     "source_id": row["source_id"], "field_verified": False}
                    for row in eligible[:20])
    fake = [row for row in by_source["gpt4o-receipt"] if row["split"] == "test"]
    rng.shuffle(fake)
    selected_fake, categories = [], set()
    for row in fake:
        if row["merchant_category"] in categories:
            continue
        selected_fake.append({"record_id": row["record_id"], "source": "gpt4o-receipt",
                              "source_id": row["source_id"], "field_verified": False})
        categories.add(row["merchant_category"])
        if len(selected_fake) == 4:
            break
    if len(selected_fake) != 4:
        raise ValueError("Need four distinct held-out GPT merchant categories")
    sroie_test = {Path(row["source_id"]).stem.lower(): row["record_id"]
                  for row in by_source["sroie"] if row["split"] == "test"}
    forged = []
    for split in ("test", "val", "train"):
        with (findit_root / f"{split}.txt").open(newline="", encoding="utf-8-sig") as handle:
            for item in csv.DictReader(handle):
                if item["forged"] != "1":
                    continue
                name = item["image"]
                parent = sroie_test.get(Path(name).stem.lower())
                if not parent or not (findit_root / split / name).is_file():
                    continue
                forged.append({"record_id": f"find_it_again:{split}/{name}",
                               "source": "find_it_again", "source_id": f"{split}/{name}",
                               "parent_record_id": parent, "parent_model_split": "test",
                               "field_verified": False})
    selected_forged = forged[:6]
    if len(selected_forged) != 6:
        raise ValueError("Need six forged images whose SROIE originals are held out")
    return {"seed": seed, "status": "candidate_only", "real": real,
            "forged": selected_forged, "ai_generated": selected_fake,
            "note": "Match and verify printed merchant/date/total against scenarios before copying images."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", type=Path, default=Path("ml/splits/source_splits.json"))
    parser.add_argument("--findit", type=Path, default=Path.home() / "datasets" / "find_it_again" / "findit2")
    parser.add_argument("--output", type=Path, default=Path("ml/splits/test_month_candidates.json"))
    args = parser.parse_args()
    result = select(args.splits, args.findit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Selected {len(result['real'])} real, {len(result['forged'])} forged, "
          f"{len(result['ai_generated'])} AI candidates: {args.output}")
