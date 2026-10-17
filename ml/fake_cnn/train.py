
"""
Receipt authenticity CNN baseline.
Input images: 384x384 RGB, letterboxed on a white canvas.
Expected dataset:
    ~/datasets/receipt_authenticity/
        real/
            receipt_001.jpg
        fake/
            receipt_002.jpg

Labels must be verified; do not label a receipt fake merely
because it comes from a particular dataset.
"""

from pathlib import Path
import random
import json

import numpy as np
from PIL import Image, ImageOps
import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader, random_split
from torchvision import models, transforms

SEED = 42
IMAGE_SIZE = 384
BATCH_SIZE = 8
EPOCHS = 5
LEARNING_RATE = 1e-4

DATA_ROOT = Path.home() / "datasets" / "receipt_authenticity"
OUTPUT_DIR = Path("ml/fake_cnn/checkpoints")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def preprocess_image(path: Path) -> Image.Image:
    """Resize proportionally and letterbox on a white 384x384 canvas."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")

    image.thumbnail((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), "white")
    x = (IMAGE_SIZE - image.width) // 2
    y = (IMAGE_SIZE - image.height) // 2
    canvas.paste(image, (x, y))
    return canvas


class ReceiptDataset(Dataset):
    def __init__(self, root: Path):
        self.samples = []

        for folder, label in [("real", 0), ("fake", 1)]:
            directory = root / folder
            if not directory.exists():
                continue

            for path in directory.rglob("*"):
                if path.suffix.lower() in {
                    ".jpg", ".jpeg", ".png", ".webp", ".bmp"
                }:
                    self.samples.append((path, label))

        if not self.samples:
            raise RuntimeError(
                f"No labelled images found in {root}. "
                "Create real/ and fake/ folders and add verified images."
            )

        labels = {label for _, label in self.samples}
        if labels != {0, 1}:
            raise RuntimeError(
                "Both classes are required. Add verified images to real/ and fake/."
            )

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        path, label = self.samples[index]
        image = preprocess_image(path)
        tensor = transforms.ToTensor()(image)
        return tensor, torch.tensor(label, dtype=torch.long)


def main():
    dataset = ReceiptDataset(DATA_ROOT)

    if len(dataset) < 10:
        raise RuntimeError(
            f"Only {len(dataset)} labelled images found. "
            "Collect more verified examples before training."
        )

    val_size = max(1, int(len(dataset) * 0.2))
    train_size = len(dataset) - val_size

    generator = torch.Generator().manual_seed(SEED)
    train_data, val_data = random_split(
        dataset, [train_size, val_size], generator=generator
    )

    train_loader = DataLoader(
        train_data, batch_size=BATCH_SIZE, shuffle=True, num_workers=0
    )
    val_loader = DataLoader(
        val_data, batch_size=BATCH_SIZE, shuffle=False, num_workers=0
    )

    # ImageNet-pretrained ResNet18; replace the final layer for two classes.
    model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    model.fc = nn.Linear(model.fc.in_features, 2)
    model = model.to(DEVICE)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4
    )

    best_val_accuracy = 0.0
    history = []

    print(f"Device: {DEVICE}")
    if DEVICE.type == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"Images: {len(dataset)} | Train: {train_size} | Val: {val_size}")

    for epoch in range(EPOCHS):
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for images, labels in train_loader:
            images = images.to(DEVICE)
            labels = labels.to(DEVICE)

            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * labels.size(0)
            train_correct += (logits.argmax(1) == labels).sum().item()
            train_total += labels.size(0)

        model.eval()
        val_correct = 0
        val_total = 0

        with torch.no_grad():
            for images, labels in val_loader:
                images = images.to(DEVICE)
                labels = labels.to(DEVICE)
                logits = model(images)
                val_correct += (logits.argmax(1) == labels).sum().item()
                val_total += labels.size(0)

        train_accuracy = train_correct / train_total
        val_accuracy = val_correct / val_total
        mean_loss = train_loss / train_total

        metrics = {
            "epoch": epoch + 1,
            "train_loss": round(mean_loss, 4),
            "train_accuracy": round(train_accuracy, 4),
            "val_accuracy": round(val_accuracy, 4),
        }
        history.append(metrics)
        print(metrics)

        if val_accuracy > best_val_accuracy:
            best_val_accuracy = val_accuracy
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "class_to_index": {"real": 0, "fake": 1},
                    "image_size": IMAGE_SIZE,
                    "epoch": epoch + 1,
                    "val_accuracy": val_accuracy,
                },
                OUTPUT_DIR / "best_model.pt",
            )

    (OUTPUT_DIR / "training_history.json").write_text(
        json.dumps(history, indent=2), encoding="utf-8"
    )
    print(f"Training complete. Best validation accuracy: {best_val_accuracy:.3f}")
    print(f"Checkpoint directory: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
