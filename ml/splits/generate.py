"""Create deterministic, source-aware receipt splits from a reviewed JSON manifest.

Input rows require source, source_id, image_path, and group_id. Labels must be
"real", "fake", or "unknown"; an unknown label is never promoted to fake.
GPT4o-Receipt rows also require merchant_category. Related variants must share
group_id. Exact file duplicates are grouped automatically.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import re

import numpy as np
from PIL import Image, ImageOps

RATIOS = {"gpt4o-receipt": (0.7, 0.1, 0.2), "sroie": (0.8, 0.1, 0.1),
          "cord_v2": (0.8, 0.1, 0.1)}
ALIASES = {"cord-v2": "cord_v2", "cord": "cord_v2", "gpt4o_receipt": "gpt4o-receipt",
           "express expense": "express_expense", "express-expense": "express_expense"}


_COSINE = np.cos(np.pi * (2 * np.arange(32)[:, None] + 1) * np.arange(32)[None, :] / 64)


def phash(path: Path) -> int:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L").resize((32, 32))
    pixels = np.asarray(image, dtype=np.float64)
    low = (_COSINE.T @ pixels @ _COSINE)[:8, :8]
    threshold = np.median(low[1:, :])
    return sum(int(value > threshold) << index for index, value in enumerate(low.flat))


def generate(rows: list[dict], heldout_ids: set[str], seed: int = 42) -> list[dict]:
    """Assign whole groups to splits; fail on conflicting source/group data."""
    normalized = []
    seen_ids = set()
    for item in rows:
        row = dict(item)
        for field in ("source", "source_id", "image_path", "group_id", "label"):
            if not row.get(field):
                raise ValueError(f"Missing {field} in input row: {item}")
        row["source"] = ALIASES.get(row["source"].lower(), row["source"].lower())
        if row["label"] not in {"real", "fake", "unknown"}:
            raise ValueError(f"Invalid label for {row['source_id']}: {row['label']}")
        if row["source"] in {"sroie", "cord_v2", "express_expense"} and row["label"] == "fake":
            raise ValueError(f"Cannot infer fake label from real-receipt source: {row['source_id']}")
        if row["label"] == "fake" and not row.get("label_provenance"):
            raise ValueError(f"Fake label needs annotation provenance: {row['source_id']}")
        key = f"{row['source']}:{row['source_id']}"
        if key in seen_ids:
            raise ValueError(f"Repeated source ID: {key}")
        seen_ids.add(key)
        if row["source"] == "gpt4o-receipt" and not row.get("merchant_category"):
            raise ValueError(f"Missing merchant_category for {key}")
        path = Path(row["image_path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        row["image_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        row["phash"] = f"{phash(path):016x}"
        row["record_id"] = key
        normalized.append(row)

    normalized.sort(key=lambda row: row["record_id"])

    # Union user-supplied variant IDs, GPT merchant categories, and exact or
    # perceptually similar images. This keeps duplicate variants together.
    parent = list(range(len(normalized)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        parent[find(right)] = find(left)

    group_first, hash_first = {}, {}
    for index, row in enumerate(normalized):
        key = (row["source"], row["merchant_category"] if row["source"] == "gpt4o-receipt" else row["group_id"])
        if key in group_first:
            union(index, group_first[key])
        group_first[key] = index
        digest = row["image_sha256"]
        if digest in hash_first:
            previous = hash_first[digest]
            if row["source"] != normalized[previous]["source"]:
                raise ValueError(f"Exact duplicate spans sources: {row['record_id']}, {normalized[previous]['record_id']}")
            union(index, previous)
        hash_first[digest] = index
    for index, left in enumerate(normalized):
        for other in range(index + 1, len(normalized)):
            right = normalized[other]
            if (int(left["phash"], 16) ^ int(right["phash"], 16)).bit_count() <= 3:
                if left["source"] != right["source"]:
                    raise ValueError(f"Possible duplicate spans sources: {left['record_id']}, {right['record_id']}")
                union(index, other)

    by_source = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(normalized):
        group = find(index)
        row["leakage_group"] = f"{row['source']}:{group}"
        by_source[row["source"]][group].append(row)

    for source, groups in by_source.items():
        if source in {"express_expense", "find_it_again", "wildreceipt"}:
            split_by_group = {key: "unseen_real" if source == "express_expense" else "unassigned"
                              for key in groups}
        elif source in RATIOS:
            keys = sorted(groups)
            if len(keys) < 3:
                raise ValueError(f"Need at least three independent groups for {source} splits")
            random.Random(f"{seed}:{source}").shuffle(keys)
            split_by_group = {}
            reserved = {key for key, members in groups.items()
                        if any(row["record_id"] in heldout_ids for row in members)}
            available = [key for key in keys if key not in reserved]
            if len(available) < 2:
                raise ValueError(f"Insufficient non-heldout groups for train and val: {source}")
            train_count = max(1, min(len(available) - (1 if reserved else 2),
                                     round(len(keys) * RATIOS[source][0])))
            val_count = max(1, min(len(available) - train_count - (0 if reserved else 1),
                                   round(len(keys) * RATIOS[source][1])))
            split_by_group.update({key: "test" for key in reserved})
            for index, key in enumerate(available):
                split_by_group[key] = "train" if index < train_count else "val" if index < train_count + val_count else "test"
        else:
            raise ValueError(f"Unsupported source: {source}")
        for key, members in groups.items():
            for row in members:
                row["split"] = split_by_group[key]
                is_heldout = (key in reserved) if source in RATIOS else (row["record_id"] in heldout_ids)
                if is_heldout:
                    if row["split"] not in {"test", "unseen_real"}:
                        raise ValueError(f"Held-out test-month row is assigned to {row['split']}: {row['record_id']}")
                    row["test_month"] = True
                else:
                    row["test_month"] = False
    missing = heldout_ids - {row["record_id"] for row in normalized}
    if missing:
        raise ValueError(f"Held-out IDs absent from input: {sorted(missing)}")
    return sorted(normalized, key=lambda row: row["record_id"])


def real_rows_from_prepared(path: Path) -> list[dict]:
    """Import known real-only images without inventing fake labels."""
    rows = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        if item["status"] != "ok":
            continue
        source = item["source"].lower()
        if source not in {"sroie", "cord_v2", "express_expense"}:
            raise ValueError(f"Prepared source is not approved for real-only import: {source}")
        rows.append({"source": source, "source_id": item["source_id"],
                     "image_path": item["prepared_path"],
                     "group_id": Path(item["source_id"]).stem, "label": "real"})
    return rows


def gpt_rows_from_prepared(path: Path) -> list[dict]:
    """Use only files matching the dataset card's documented fake filename rule."""
    rows = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        if item.get("source") != "gpt4o_receipt" or item.get("status") != "ok":
            continue
        filename = Path(item["source_id"]).name
        match = re.fullmatch(r"receipt_(.+)_([0-9]+)\.png", filename, re.I)
        if not match:
            continue
        category = match.group(1).lower()
        rows.append({"source": "gpt4o-receipt", "source_id": item["source_id"],
                     "image_path": item["prepared_path"], "group_id": category,
                     "merchant_category": category, "label": "fake",
                     "label_provenance": "Scam-AI/gpt4o-receipt README filename rule"})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path, help="Reviewed JSON array of source images")
    inputs.add_argument("--prepared-real", type=Path, help="Preparation manifest for known real-only sources")
    parser.add_argument("--output", required=True, type=Path, help="Split manifest JSON outside the repo")
    parser.add_argument("--split-list", type=Path,
                        help="Portable split list under ml/splits for Git")
    parser.add_argument("--heldout-ids", type=Path, help="JSON array of source:source_id keys for test month")
    parser.add_argument("--prepared-fake", type=Path,
                        help="GPT4o preparation manifest; combine with the selected real input")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output == repository or repository in output.parents:
        parser.error("Output must be outside the repository")
    selected_input = args.input or args.prepared_real
    if output == selected_input.resolve():
        parser.error("Output must differ from input")
    split_list = None
    if args.split_list:
        split_list = args.split_list.resolve()
        splits_dir = (repository / "ml" / "splits").resolve()
        if splits_dir not in split_list.parents:
            parser.error("Split list must be under ml/splits")
    rows = (json.loads(args.input.read_text(encoding="utf-8")) if args.input
            else real_rows_from_prepared(args.prepared_real))
    if args.prepared_fake:
        rows.extend(gpt_rows_from_prepared(args.prepared_fake))
    heldout = set(json.loads(args.heldout_ids.read_text(encoding="utf-8"))) if args.heldout_ids else set()
    result = generate(rows, heldout, args.seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"seed": args.seed, "rows": result}, indent=2), encoding="utf-8")
    if split_list:
        fields = ("record_id", "source", "source_id", "label", "split", "leakage_group",
                  "image_sha256", "phash", "test_month", "merchant_category", "label_provenance")
        portable = [{field: row[field] for field in fields if field in row} for row in result]
        split_list.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in portable]
        split_list.write_text('{"seed":' + str(args.seed) + ',"rows":[\n' +
                              ',\n'.join(lines) + '\n]}\n', encoding="utf-8")
    counts = defaultdict(int)
    for row in result:
        counts[(row["source"], row["split"])] += 1
    print(f"Wrote {len(result)} rows to {output}; counts: {dict(counts)}")


if __name__ == "__main__":
    main()
