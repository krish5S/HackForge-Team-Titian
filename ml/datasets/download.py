
"""
Dev 1 — Receipt dataset downloader.

Downloads datasets from Hugging Face into a directory outside the repo.
Dataset IDs and configurations must be verified before downloading.
"""

from pathlib import Path
import argparse
import json
import logging
import os

# Keep raw datasets outside the Git repository.
DATA_ROOT = Path.home() / "datasets"
MANIFEST_PATH = DATA_ROOT / "download_manifest.json"

# Dataset IDs are configurable because the execution plan names datasets,
# but does not specify verified Hugging Face repository IDs for all of them.
DATASETS = {
    "sroie": {
        "repo_id": "darentang/sroie",
        "split": "train",
        "local_path": DATA_ROOT / "sroie_extracted" / "sroie",
    },
    "cord_v2": {
        "repo_id": "naver-clova-ix/cord-v2",
        "split": "train",
        "local_path": DATA_ROOT / "cord_v2",
    },
    "wildreceipt": {"repo_id": None, "local_path": DATA_ROOT / "wildreceipt",
                    "source_url": "https://download.openmmlab.com/mmocr/data/wildreceipt.tar"},
    "express_expense": {"repo_id": None, "local_path": DATA_ROOT / "express_expense",
                        "source_url": "https://zenodo.org/records/13688441"},
    "find_it_again": {"repo_id": None, "local_path": DATA_ROOT / "find_it_again",
                      "source_url": "https://l3i-share.univ-lr.fr/2023Finditagain/"},
    "gpt4o_receipt": {"repo_id": "Scam-AI/gpt4o-receipt",
                       "local_path": DATA_ROOT / "gpt4o_receipt",
                       "source_url": "https://huggingface.co/datasets/Scam-AI/gpt4o-receipt"},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def download_dataset(name: str, config: dict) -> dict:
    """Download one dataset and save it to disk."""
    if not config.get("repo_id"):
        raise ValueError(f"No verified download ID for {name}; check source access and license")
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError("The datasets package is unavailable in this Python environment") from exc
    output_dir = DATA_ROOT / name

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
    parser = argparse.ArgumentParser(description="Audit or download receipt datasets outside Git")
    parser.add_argument("--download", action="store_true", help="Download only configured, missing datasets")
    args = parser.parse_args()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}

    for name, config in DATASETS.items():
        local = config["local_path"]
        if local.exists() and any(local.iterdir()):
            manifest[name] = {"name": name, "status": "available", "saved_to": str(local),
                              "repo_id": config["repo_id"], "source_url": config.get("source_url")}
            continue
        if name == "gpt4o_receipt" and not (os.environ.get("HF_TOKEN") or
                                             (Path.home() / ".cache" / "huggingface" / "token").is_file()):
            manifest[name] = {"name": name, "status": "access_required",
                              "repo_id": config["repo_id"], "source_url": config.get("source_url"),
                              "reason": "Accept dataset terms and authenticate Hugging Face locally"}
            continue
        if not args.download:
            manifest[name] = {"name": name, "status": "missing", "repo_id": config["repo_id"],
                              "source_url": config.get("source_url"),
                              "reason": "No local copy; download not requested"}
            continue
        if not config["repo_id"]:
            manifest[name] = {"name": name, "status": "needs_source", "repo_id": None,
                              "source_url": config.get("source_url"),
                              "reason": "Verified access and license are required"}
            continue
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

    failed = [name for name, result in manifest.items() if result["status"] == "failed"]
    if failed:
        raise SystemExit(f"Downloads failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
