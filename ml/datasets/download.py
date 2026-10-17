
"""
Dev 1 — Receipt dataset downloader.

Downloads datasets from Hugging Face into a directory outside the repo.
Dataset IDs and configurations must be verified before downloading.
"""

from pathlib import Path
import json
import logging

from datasets import load_dataset

# Keep raw datasets outside the Git repository.
DATA_ROOT = Path.home() / "datasets"
MANIFEST_PATH = DATA_ROOT / "download_manifest.json"

# Dataset IDs are configurable because the execution plan names datasets,
# but does not specify verified Hugging Face repository IDs for all of them.
DATASETS = {
    "sroie": {
        "repo_id": "darentang/sroie",
        "split": "train",
    },
    "cord_v2": {
        "repo_id": "naver-clova-ix/cord-v2",
        "split": "train",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def download_dataset(name: str, config: dict) -> dict:
    """Download one dataset and save it to disk."""
    output_dir = DATA_ROOT / name
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading %s from %s", name, config["repo_id"])

    dataset = load_dataset(
        config["repo_id"],
        split=config["split"],
    )

    dataset.save_to_disk(str(output_dir))

    result = {
        "name": name,
        "repo_id": config["repo_id"],
        "split": config["split"],
        "rows": len(dataset),
        "saved_to": str(output_dir),
        "status": "success",
    }

    logger.info(
        "Saved %s: %s rows -> %s",
        name,
        len(dataset),
        output_dir,
    )
    return result


def main() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {}

    for name, config in DATASETS.items():
        try:
            manifest[name] = download_dataset(name, config)
        except Exception as exc:
            logger.exception("Failed to download %s", name)
            manifest[name] = {
                "name": name,
                "repo_id": config["repo_id"],
                "status": "failed",
                "error": str(exc),
            }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    logger.info("Manifest written to %s", MANIFEST_PATH)

    failed = [
        name
        for name, result in manifest.items()
        if result["status"] != "success"
    ]
    if failed:
        raise SystemExit(f"Downloads failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
