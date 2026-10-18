"""Assemble the 100-receipt month: rendered scenarios plus held-out public receipts.

Public receipts are copied from their ORIGINAL dataset files (not the 384px
CNN copies). Expected merchant/date/total are taken only from dataset
annotations (SROIE tags, CORD ground truth); where a dataset has no such
labels the scenario's merchant/date/total are blanked so no reader is scored
against facts the image does not print. Output scenarios are derived from
Dev 2's provisional file and written separately; the source file is untouched.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
import re
import shutil

from ml.datagen.render import DUPLICATE_VARIANTS, load_scenarios, render_month

DUPLICATE_TYPES = set(DUPLICATE_VARIANTS)

# Scenario types that take a real receipt, in assignment order. The first 60
# eligible scenarios (clean first) become real public receipts.
REAL_ORDER = ["clean", "missing_client", "late_original", "alcohol"]
FACT_FIELDS = ("merchant", "transaction_date", "transaction_time", "total",
               "subtotal", "tax", "tip", "other_charges", "currency")


def _iso_date(text: str) -> str | None:
    match = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    year += 2000 if year < 100 else 0
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _amount(text: str) -> str | None:
    match = re.search(r"\d[\d,]*\.\d{2}", text.replace(" ", ""))
    return match.group(0).replace(",", "") if match else None


def sroie_truth(root: Path, source_id: str) -> dict:
    split, _, name = source_id.split("/")
    tagged = json.loads((root / split / "tagged" / f"{Path(name).stem}.json").read_text(encoding="utf-8"))
    grouped: dict[str, list[str]] = {}
    for word, label in zip(tagged["words"], tagged["labels"]):
        if label != "O":
            grouped.setdefault(label[2:], []).append(word)
    # TOTAL may repeat as B-/I- runs; keep the first run of tokens.
    truth = {}
    if grouped.get("COMPANY"):
        truth["merchant"] = " ".join(grouped["COMPANY"]).title()
    if grouped.get("DATE") and _iso_date(" ".join(grouped["DATE"])):
        truth["transaction_date"] = _iso_date(" ".join(grouped["DATE"]))
    if grouped.get("TOTAL") and _amount(grouped["TOTAL"][0]):
        truth["total"] = _amount(grouped["TOTAL"][0])
    return truth


def cord_truth(dataset, source_id: str) -> tuple[dict, bytes | None]:
    row = dataset[int(source_id)]
    parse = json.loads(row["ground_truth"])["gt_parse"]
    total = parse.get("total", {})
    value = total.get("total_price") if isinstance(total, dict) else None
    truth = {"total": _amount(str(value))} if value and _amount(str(value)) else {}
    return truth, row["image"]


def _open_original(record: dict, datasets: Path, cord):
    from PIL import Image
    source, source_id = record["source"], record["source_id"]
    if source == "cord_v2":
        return cord[int(source_id)]["image"].convert("L")
    root = datasets / ("sroie_extracted/sroie" if source == "sroie" else "express_expense")
    return Image.open(root / source_id).convert("L")


def _signature(image):
    import numpy as np
    pixels = np.asarray(image.resize((96, 144)), dtype=np.float32)
    return (pixels - pixels.mean()) / (pixels.std() + 1e-6)


def drop_lookalikes(real: list[dict], spare: list[dict], datasets: Path, cord) -> list[dict]:
    """Replace real receipts that are visually identical to an earlier pick.

    Public datasets contain the same receipt twice (e.g. CORD 000197/000215);
    left in, they would be unplanted duplicates in the month.
    """
    kept, signatures = [], []
    spare = list(spare)
    for record in real:
        candidate = record
        while True:
            signature = _signature(_open_original(candidate, datasets, cord))
            if all(float((signature * other).mean()) < 0.98 for other in signatures):
                break
            replacements = [row for row in spare if row["source"] == record["source"]]
            if not replacements:
                raise ValueError(f"No spare held-out receipt for {record['record_id']}")
            candidate = replacements[0]
            spare.remove(candidate)
        kept.append(candidate)
        signatures.append(signature)
    return kept


def assemble(scenarios_path: Path, manifest_path: Path, datasets: Path,
             images_dir: Path, index_path: Path, output: Path) -> dict:
    scenarios = load_scenarios(scenarios_path)
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))["rows"]
    pools = {"real": [r for r in rows if r["label"] == "real"],
             "forged": [r for r in rows if r["label"] == "forged"],
             "fake": [r for r in rows if r["label"] == "fake"]}
    forged_ids = [s["scenario_id"] for s in scenarios if s["scenario_type"] == "forged"]
    ai_ids = [s["scenario_id"] for s in scenarios if s["scenario_type"] == "ai_generated"]
    real_ids = []
    for kind in REAL_ORDER:
        real_ids += [s["scenario_id"] for s in scenarios if s["scenario_type"] == kind]
    real_ids = sorted(real_ids[:len(pools["real"])])
    if len(real_ids) != len(pools["real"]) or len(forged_ids) != len(pools["forged"]) \
            or len(ai_ids) != len(pools["fake"]):
        raise ValueError("Scenario counts do not match public pool sizes")
    # Interleave sources so every source spreads over the month.
    pools["real"].sort(key=lambda r: (r["source"], r["record_id"]))
    from datasets import load_from_disk
    cord = load_from_disk(str(datasets / "cord_v2"))
    chosen = {r["record_id"] for r in rows}
    spare = sorted((r for r in json.loads((datasets / "real_splits.json").read_text(encoding="utf-8"))["rows"]
                    if r["split"] in {"test", "unseen_real"} and r["record_id"] not in chosen),
                   key=lambda r: (r["source"], r["record_id"]))
    pools["real"] = drop_lookalikes(pools["real"], spare, datasets, cord)
    assignment = list(zip(real_ids, pools["real"])) + list(zip(forged_ids, pools["forged"])) \
        + list(zip(ai_ids, pools["fake"]))
    assigned = {sid for sid, _ in assignment}

    findit = datasets / "find_it_again" / "findit2"
    by_id = {s["scenario_id"]: dict(s) for s in scenarios}
    public_entries = []
    images_dir.mkdir(parents=True, exist_ok=True)
    for scenario_id, record in assignment:
        source, source_id = record["source"], record["source_id"]
        truth: dict = {}
        if source == "sroie":
            origin = datasets / "sroie_extracted" / "sroie" / source_id
            truth = sroie_truth(datasets / "sroie_extracted" / "sroie", source_id)
            target = images_dir / f"{scenario_id}{origin.suffix.lower()}"
            shutil.copyfile(origin, target)
        elif source == "cord_v2":
            truth, image = cord_truth(cord, source_id)
            target = images_dir / f"{scenario_id}.png"
            image.save(target)
        elif source == "express_expense":
            origin = datasets / "express_expense" / source_id
            target = images_dir / f"{scenario_id}{origin.suffix.lower()}"
            shutil.copyfile(origin, target)
        elif source == "find_it_again":
            origin = findit / source_id
            target = images_dir / f"{scenario_id}{origin.suffix.lower()}"
            shutil.copyfile(origin, target)
        elif source == "gpt4o-receipt":
            origin = datasets / "gpt4o_receipt" / source_id
            target = images_dir / f"{scenario_id}{origin.suffix.lower()}"
            shutil.copyfile(origin, target)
        else:
            raise ValueError(f"Unknown source: {source}")
        scenario = by_id[scenario_id]
        # Blank every printed fact the dataset does not label; keep labeled ones.
        for field in FACT_FIELDS:
            scenario[field] = truth.get(field, "")
        if "total" in truth:
            scenario["subtotal"] = ""
        scenario["line_items"] = []
        scenario["derived_from_public"] = {"source": source, "source_id": source_id,
                                           "labeled_fields": sorted(truth)}
        public_entries.append((scenario_id, record, target, sorted(truth)))

    for scenario in by_id.values():
        related = scenario.get("related_ids") or []
        if scenario["scenario_type"] in DUPLICATE_TYPES and related and related[0] in assigned:
            for field in FACT_FIELDS + ("line_items",):
                scenario[field] = by_id[related[0]][field]
    final = [by_id[s["scenario_id"]] for s in scenarios]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_status": "provisional_d1_derived",
                                  "scenarios": final}, indent=2), encoding="utf-8")
    index = {"images": [], "status": "provisional_scenarios"}
    for scenario_id, record, target, labeled in public_entries:
        scenario = by_id[scenario_id]
        index["images"].append({
            "image_id": scenario_id, "file": target.name, "source": record["source"],
            "source_id": record["source_id"], "scenario_id": scenario_id,
            "planted_problem": scenario.get("planted_issue"),
            "related_ids": scenario.get("related_ids", []),
            "verified_fields": True,
            "label_basis": ("dataset annotation: " + ", ".join(labeled)) if labeled
            else "no field annotations in dataset; expected facts left blank"})
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    result = render_month(final, images_dir, index_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["status"] = "provisional_scenarios"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return {"images": len(index["images"]), "pending": result["pending_public_scenarios"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=Path("data/month/scenarios.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path.home() / "datasets" / "public_month_manifest.json")
    parser.add_argument("--datasets", type=Path, default=Path.home() / "datasets")
    parser.add_argument("--images-dir", type=Path, default=Path("data/month/images"))
    parser.add_argument("--index", type=Path, default=Path("data/month/images_index.json"))
    parser.add_argument("--output", type=Path, default=Path("data/month/scenarios_final.json"))
    args = parser.parse_args()
    print(assemble(args.scenarios, args.manifest, args.datasets, args.images_dir, args.index, args.output))


if __name__ == "__main__":
    main()
