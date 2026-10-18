"""Render fictional scenario receipts and their planted duplicate variants."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ml.datagen.copies import make_copy

WIDTH = 900
DUPLICATE_VARIANTS = {"exact_duplicate": "exact",
                      "cross_employee_duplicate": "exact",
                      "rephotographed_duplicate": "rephotographed",
                      "pdf_photo_duplicate": "pdf"}
PUBLIC_TYPES = {"forged", "ai_generated"}


def load_scenarios(path: Path) -> list[dict]:
    source = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML is required for non-JSON scenarios.yaml") from exc
        payload = yaml.safe_load(source)
    rows = payload.get("scenarios") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Scenario file must contain a scenarios list")
    ids = [row.get("scenario_id") for row in rows]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("Scenario IDs must be nonempty and unique")
    return rows


def choose_template(scenario: dict) -> str:
    if scenario.get("template") in {"restaurant", "hotel", "taxi"}:
        return scenario["template"]
    if scenario.get("category") in {"MEALS", "ENTERTAINMENT"}:
        return "restaurant"
    text = " ".join(item.get("description", "") for item in scenario.get("line_items", []))
    if "hotel" in text.lower() or "room" in text.lower() or "lodging" in text.lower():
        return "hotel"
    if scenario.get("category") == "TRAVEL" and hashlib.sha256(
            scenario["scenario_id"].encode()).digest()[0] % 3 == 0:
        return "hotel"
    return "taxi"


GENERIC_ITEM = {"restaurant": "Dinner", "hotel": "Room charge", "taxi": "Trip fare"}


def item_description(description: str, template: str, category: str | None) -> str:
    """Give the placeholder item a line that fits the receipt type."""
    if description.strip().lower() != "business expense":
        return description
    if category == "ENTERTAINMENT":
        return "Show tickets"
    return GENERIC_ITEM[template]


def _font(size: int, bold: bool = False):
    candidates = (["C:/Windows/Fonts/consolab.ttf"] if bold else ["C:/Windows/Fonts/consola.ttf"])
    candidates += ["DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_receipt(scenario: dict, output: Path) -> Path:
    """Render one receipt with the scenario's printed facts."""
    template = choose_template(scenario)
    items = scenario.get("line_items") or []
    height = max(1100, 850 + 66 * len(items))
    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)
    headline = {"restaurant": "RESTAURANT RECEIPT", "hotel": "HOTEL FOLIO",
                "taxi": "TAXI TRIP RECEIPT"}[template]
    if template == "restaurant" and scenario.get("category") == "ENTERTAINMENT":
        headline = "SHOW & ENTERTAINMENT"
    y = 45

    def line(text: str, size: int = 30, bold: bool = False, gap: int = 52) -> None:
        nonlocal y
        draw.text((65, y), text, font=_font(size, bold), fill="black")
        y += gap

    line(str(scenario["merchant"]), 43, True, 62)
    line(headline, 26, False, 52)
    line(f"{scenario.get('city', '')}, {scenario.get('country', '')}", 27)
    if template == "hotel":
        line("Guest folio / room charges", 25)
    elif template == "taxi":
        line("Trip fare / local transport", 25)
    else:
        line(f"Party size: {scenario.get('attendee_count', 1)}", 25)
    draw.line((65, y, WIDTH - 65, y), fill="black", width=2)
    y += 24
    line(f"Date: {scenario.get('transaction_date', '')}")
    line(f"Time: {scenario.get('transaction_time', '')}")
    line(f"Receipt: {scenario.get('receipt_number') or scenario['scenario_id']}")
    draw.line((65, y, WIDTH - 65, y), fill="black", width=2)
    y += 30
    for item in items:
        description = item_description(str(item.get("description", "")), template,
                                       scenario.get("category"))[:34]
        amount = str(item.get("amount", ""))
        line(f"{description:<34} {amount:>12}", 27, gap=55)
    draw.line((65, y, WIDTH - 65, y), fill="black", width=2)
    y += 22
    for field, label in (("subtotal", "SUBTOTAL"), ("tax", "TAX"),
                         ("tip", "TIP"), ("other_charges", "OTHER"), ("total", "TOTAL")):
        value = str(scenario.get(field, "0.00"))
        line(f"{label:<18} {value:>18} {scenario.get('currency', '')}",
             32 if field == "total" else 27, field == "total", 60)
    if scenario.get("attendee_count") and template == "restaurant":
        line(f"Guests: {scenario['attendee_count']}", 25)
    line("Thank you for your visit", 24)
    if y > height - 30:
        raise ValueError(f"Receipt content exceeds canvas: {scenario['scenario_id']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=90)
    return output


def render_month(scenarios: list[dict], images_dir: Path, index_path: Path,
                 public_scenario_ids: set[str] | None = None) -> dict:
    """Render supported scenarios; leave public source rows for pick_public.py."""
    by_id = {row["scenario_id"]: row for row in scenarios}
    if len(by_id) != len(scenarios):
        raise ValueError("Repeated scenario IDs")
    existing_index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"images": []}
    entries = list(existing_index["images"])
    paths: dict[str, Path] = {entry["scenario_id"]: images_dir / entry["file"] for entry in entries}
    skipped = []
    public_scenario_ids = public_scenario_ids or set()
    if not public_scenario_ids.issubset(by_id):
        raise ValueError("Public assignment refers to an unknown scenario")
    pending = list(scenarios)
    while pending:
        next_pending = []
        progressed = False
        for row in pending:
            scenario_id = row["scenario_id"]
            kind = row.get("scenario_type", "clean")
            if scenario_id in paths:
                progressed = True
                continue
            if kind in PUBLIC_TYPES or scenario_id in public_scenario_ids:
                if scenario_id not in paths:
                    skipped.append(scenario_id)
                progressed = True
                continue
            variant = DUPLICATE_VARIANTS.get(kind)
            if variant:
                related = row.get("related_ids") or []
                if not related or related[0] not in by_id:
                    raise ValueError(f"Duplicate scenario lacks a valid source: {scenario_id}")
                if related[0] not in paths:
                    next_pending.append(row)
                    continue
                suffix = ".pdf" if variant == "pdf" else ".jpg"
                path = images_dir / f"{scenario_id}{suffix}"
                seed = int.from_bytes(hashlib.sha256(scenario_id.encode()).digest()[:4], "big")
                make_copy(paths[related[0]], path, variant, seed=seed)
                template = choose_template(by_id[related[0]])
            else:
                path = images_dir / f"{scenario_id}.jpg"
                render_receipt(row, path)
                if kind == "unreadable":
                    with Image.open(path) as readable:
                        blurred = readable.filter(ImageFilter.GaussianBlur(12))
                    blurred.save(path, "JPEG", quality=80)
                template = choose_template(row)
            paths[scenario_id] = path
            entries.append({"image_id": scenario_id, "file": path.name, "source": "rendered",
                            "path": os.path.relpath(path, index_path.parent).replace(os.sep, "/"),
                            "scenario_id": scenario_id, "planted_problem": row.get("planted_issue"),
                            "related_ids": row.get("related_ids", []), "template": template})
            progressed = True
        if not progressed:
            raise ValueError("Unresolvable duplicate dependency among scenarios")
        pending = next_pending
    result = {"images": sorted(entries, key=lambda item: item["image_id"]),
              "pending_public_scenarios": sorted(set(skipped))}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--images-dir", type=Path, default=Path("data/month/images"))
    parser.add_argument("--index", type=Path, default=Path("data/month/images_index.json"))
    parser.add_argument("--public-assignments", type=Path,
                        help="JSON assignments; these scenarios use held-out public images")
    args = parser.parse_args()
    public_ids = {item["scenario_id"] for item in json.loads(args.public_assignments.read_text(encoding="utf-8"))} if args.public_assignments else set()
    result = render_month(load_scenarios(args.scenarios), args.images_dir, args.index, public_ids)
    print(f"Rendered {len(result['images'])} scenario images; "
          f"{len(result['pending_public_scenarios'])} need held-out public sources. Index: {args.index}")


if __name__ == "__main__":
    main()
