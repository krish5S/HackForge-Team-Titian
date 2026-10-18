"""Prepare receipt images without assigning authenticity labels.

Example: python -m ml.fake_cnn.prepare --source sroie=C:/Users/mehta/datasets/sroie_extracted/sroie/train/images
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_SIZE = 384
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
LOG = logging.getLogger(__name__)


def letterbox(path: Path) -> Image.Image:
    """Return a grayscale receipt on a white 384 by 384 canvas."""
    with Image.open(path) as source:
        return letterbox_image(source)


def letterbox_image(source: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(source).convert("L")
    if not image.width or not image.height:
        raise ValueError("image has zero width or height")
    image.thumbnail((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 255)
    canvas.paste(image, ((IMAGE_SIZE - image.width) // 2, (IMAGE_SIZE - image.height) // 2))
    return canvas


def prepare(sources: dict[str, Path], output: Path) -> list[dict]:
    output = output.resolve()
    repository = Path(__file__).resolve().parents[2]
    if output == repository or repository in output.parents:
        raise ValueError("Prepared images must be saved outside the repository")
    if any(path.resolve() == output or output in path.resolve().parents or
           path.resolve() in output.parents for path in sources.values()):
        raise ValueError("Output and source directories must not contain one another")
    previous_path = output / "prepare_manifest.json"
    previous = {}
    if previous_path.is_file():
        previous = {item["source_path"]: item for item in json.loads(previous_path.read_text(encoding="utf-8"))}
    records = [item for item in previous.values() if item.get("source") not in sources]
    for source_name, source_root in sorted(sources.items()):
        source_root = source_root.resolve()
        if source_root == repository or repository in source_root.parents:
            raise ValueError(f"Source images must be outside the repository: {source_root}")
        if not source_root.is_dir():
            raise FileNotFoundError(f"Source directory missing: {source_root}")
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            relative = path.relative_to(source_root).as_posix()
            identifier = hashlib.sha256(f"{source_name}/{relative}".encode()).hexdigest()[:20]
            destination = output / source_name / f"{identifier}.jpg"
            record = {"source": source_name, "source_id": relative,
                      "source_path": str(path), "prepared_path": str(destination)}
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                record["source_sha256"] = digest
                old = previous.get(str(path), {})
                if not destination.exists() or old.get("source_sha256") != digest:
                    image = letterbox(path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    image.save(destination, "JPEG", quality=85)
                record["status"] = "ok"
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                record.update(status="failed", error=str(exc))
                LOG.error("Failed to prepare %s: %s", path, exc)
            records.append(record)
    output.mkdir(parents=True, exist_ok=True)
    records.sort(key=lambda item: (item["source"], item["source_id"]))
    (output / "prepare_manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def prepare_cord(dataset_dir: Path, output: Path) -> list[dict]:
    """Normalize CORD's Arrow images directly, without copying raw files."""
    from datasets import load_from_disk

    repository = Path(__file__).resolve().parents[2]
    dataset_dir = dataset_dir.resolve()
    output = output.resolve()
    if dataset_dir == repository or repository in dataset_dir.parents:
        raise ValueError("CORD source must be outside the repository")
    if output == repository or repository in output.parents:
        raise ValueError("Prepared images must be outside the repository")
    dataset = load_from_disk(str(dataset_dir))
    previous_path = output / "prepare_manifest.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else []
    records = [item for item in previous if item.get("source") != "cord_v2"]
    for index, item in enumerate(dataset):
        source_id = f"{index:06d}"
        identifier = hashlib.sha256(f"cord_v2/{source_id}".encode()).hexdigest()[:20]
        destination = output / "cord_v2" / f"{identifier}.jpg"
        record = {"source": "cord_v2", "source_id": source_id,
                  "source_path": f"{dataset_dir}#{source_id}", "prepared_path": str(destination)}
        try:
            image = letterbox_image(item["image"])
            buffer = image.tobytes()
            digest = hashlib.sha256(buffer).hexdigest()
            record["source_sha256"] = digest
            old = next((r for r in previous if r.get("source_path") == record["source_path"]), {})
            if not destination.exists() or old.get("source_sha256") != digest:
                destination.parent.mkdir(parents=True, exist_ok=True)
                image.save(destination, "JPEG", quality=85)
            record["status"] = "ok"
        except (OSError, ValueError, KeyError) as exc:
            record.update(status="failed", error=str(exc))
            LOG.error("Failed to prepare CORD row %s: %s", source_id, exc)
        records.append(record)
    records.sort(key=lambda item: (item["source"], item["source_id"]))
    output.mkdir(parents=True, exist_ok=True)
    previous_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", metavar="NAME=PATH")
    parser.add_argument("--cord-disk", type=Path, help="Existing CORD v2 Arrow dataset directory")
    parser.add_argument("--output", type=Path, default=Path.home() / "datasets" / "prepared_receipts")
    args = parser.parse_args()
    if not args.source and not args.cord_disk:
        parser.error("Specify --source or --cord-disk")
    logging.basicConfig(level=logging.INFO)
    sources = {}
    for item in args.source or []:
        name, separator, path = item.partition("=")
        if not separator or not name or not path or not name.replace("_", "").isalnum():
            parser.error(f"Expected --source NAME=PATH, got {item!r}")
        if name in sources:
            parser.error(f"Duplicate source name: {name}")
        sources[name] = Path(path)
    records = prepare(sources, args.output) if sources else []
    if args.cord_disk:
        records = prepare_cord(args.cord_disk, args.output)
    failed = sum(item["status"] == "failed" for item in records)
    print(f"Prepared {len(records) - failed} images; {failed} failed. Manifest: {args.output / 'prepare_manifest.json'}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
