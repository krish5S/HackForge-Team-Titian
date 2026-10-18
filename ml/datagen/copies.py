"""Deterministic visual variants for planted duplicate receipts."""

from pathlib import Path
import random
import shutil

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def make_copy(source: Path, target: Path, variant: str, seed: int = 42) -> Path:
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError("Copy target must differ from source")
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if variant == "exact":
        shutil.copyfile(source, target)
        return target
    with Image.open(source) as original:
        image = original.convert("RGB")
    if variant == "pdf":
        image.save(target, "PDF", resolution=150.0)
        return target
    if variant == "rephotographed":
        rng = random.Random(seed)
        width, height = image.size
        shift = max(2, int(width * 0.04))
        corners = (rng.randint(0, shift), rng.randint(0, shift),
                   rng.randint(0, shift), height - rng.randint(0, shift),
                   width - rng.randint(0, shift), height - rng.randint(0, shift),
                   width - rng.randint(0, shift), rng.randint(0, shift))
        image = image.transform(image.size, Image.Transform.QUAD, corners,
                                resample=Image.Resampling.BICUBIC, fillcolor="white")
        image = image.filter(ImageFilter.GaussianBlur(0.8))
        pixels = np.asarray(image, dtype=np.int16)
        noise = np.random.default_rng(seed).normal(0, 3, pixels.shape)
        image = Image.fromarray(np.clip(pixels + noise, 0, 255).astype("uint8"), "RGB")
    elif variant == "faded":
        image = Image.blend(image, Image.new("RGB", image.size, "white"), 0.42)
        image = ImageEnhance.Contrast(image).enhance(0.75)
    elif variant == "rotated":
        image = image.rotate(7, resample=Image.Resampling.BICUBIC,
                             expand=True, fillcolor="white")
    elif variant == "unreadable":
        image = image.filter(ImageFilter.GaussianBlur(6))
    else:
        raise ValueError(f"Unknown copy variant: {variant}")
    image.save(target, "JPEG", quality=85)
    return target
