"""Stable file, image, merchant, and transaction fingerprints."""

import hashlib
from pathlib import Path
import re
import unicodedata
from typing import Any

import imagehash
from PIL import Image


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def perceptual_hash(path: str | Path) -> str:
    if Path(path).suffix.lower() == ".pdf":
        from backend.app.pipeline.normalize import load_image
        import cv2

        pixels = load_image(path)
        image = Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
        return str(imagehash.phash(image))
    with Image.open(path) as image:
        return str(imagehash.phash(image.convert("RGB")))


def normalize_merchant(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text.lower())).strip()


def transaction_key(extraction: dict[str, Any], total_base: str = "") -> tuple[str, str, str]:
    return (normalize_merchant(str(extraction.get("merchant_name", ""))),
            str(extraction.get("transaction_date", "")),
            total_base or str(extraction.get("total", "")))
