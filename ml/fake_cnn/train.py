"""Train a receipt authenticity baseline from a verified split manifest."""

import argparse
from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
import random

import numpy as np
from PIL import Image, ImageOps
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms

SEED = 42
IMAGE_SIZE = 384
LABELS = {"real": 0, "fake": 1}


class JpegReencode:
    def __call__(self, image: Image.Image) -> Image.Image:
        quality = random.randint(40, 95)
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=quality)
        buffer.seek(0)
        with Image.open(buffer) as compressed:
            return compressed.copy()


class ReceiptDataset(Dataset):
    def __init__(self, rows: list[dict], training: bool = False):
        self.rows = rows
        augment = ([transforms.RandomRotation(7, fill=255),
                    transforms.RandomPerspective(distortion_scale=0.2, p=0.5, fill=255),
                    transforms.RandomApply([transforms.GaussianBlur(3)], p=0.3),
                    transforms.ColorJitter(brightness=0.2, contrast=0.2),
                    transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.9, 1.0), ratio=(1.0, 1.0)),
                    JpegReencode()] if training else [])
        self.transform = transforms.Compose(augment + [transforms.Grayscale(num_output_channels=3),
                                                        transforms.ToTensor(),
                                                        transforms.Normalize((0.5,) * 3, (0.5,) * 3)])

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        with Image.open(row["image_path"]) as source:
            image = ImageOps.exif_transpose(source).convert("L")
        image.thumbnail((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.LANCZOS)
        canvas = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 255)
        canvas.paste(image, ((IMAGE_SIZE - image.width) // 2, (IMAGE_SIZE - image.height) // 2))
        return self.transform(canvas), LABELS[row["label"]]


def validate_manifest(manifest: dict) -> dict[str, list[dict]]:
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Split manifest must contain a rows array")
    splits = {name: [] for name in ("train", "val", "test", "unseen_real")}
    seen_ids, seen_hashes, seen_groups, seen_leakage_groups = set(), {}, {}, {}
    for row in rows:
        split = row.get("split")
        if split not in splits:
            continue
        label = row.get("label")
        if label == "unknown":
            continue
        if label not in LABELS:
            raise ValueError(f"Invalid label: {label}")
        if label == "fake" and not row.get("label_provenance"):
            raise ValueError(f"Fake label lacks provenance: {row.get('record_id')}")
        if label == "fake" and row.get("source") != "gpt4o-receipt":
            raise ValueError(f"CNN fake examples must be GPT4o-Receipt: {row.get('record_id')}")
        if row.get("source") in {"sroie", "cord_v2", "express_expense"} and label == "fake":
            raise ValueError(f"Real-receipt source labelled fake: {row.get('record_id')}")
        if row.get("test_month") and split not in {"test", "unseen_real"}:
            raise ValueError(f"Test-month image is in {split}: {row.get('record_id')}")
        path = Path(row["image_path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        record_id = row.get("record_id")
        if not record_id or record_id in seen_ids:
            raise ValueError(f"Missing or repeated record ID: {record_id}")
        seen_ids.add(record_id)
        digest = row.get("image_sha256")
        if not digest:
            raise ValueError(f"Missing image hash: {record_id}")
        if not row.get("leakage_group"):
            raise ValueError(f"Missing leakage group: {record_id}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Image changed since split generation: {record_id}")
        group = (row.get("source"), row.get("merchant_category") if row.get("source") == "gpt4o-receipt" else row.get("group_id"))
        for mapping, key in ((seen_hashes, digest), (seen_groups, group),
                             (seen_leakage_groups, row.get("leakage_group"))):
            if key in mapping and mapping[key] != split:
                raise ValueError(f"Leakage across splits for {record_id}: {key}")
            mapping[key] = split
        splits[split].append(row)
    for name, items in splits.items():
        counts = Counter(row["label"] for row in items)
        if name == "unseen_real":
            if len(items) < 198 or any(row["source"] != "express_expense" or row["label"] != "real" for row in items):
                raise ValueError("Need all 198 available Express Expense receipts as unseen real test data")
        else:
            minimum = 10 if name == "train" else 2
            if any(counts[label] < minimum for label in LABELS):
                raise ValueError(f"Insufficient verified labels in {name}: {dict(counts)}; need {minimum} of each")
    return splits


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> dict:
    confusion = [[0, 0], [0, 0]]
    actual_all, scores_all = [], []
    model.eval()
    with torch.no_grad():
        for images, labels in loader:
            scores = model(images.to(device)).softmax(1)[:, 1].cpu().tolist()
            predictions = [int(score >= 0.5) for score in scores]
            actual_all.extend(labels.tolist())
            scores_all.extend(scores)
            for actual, predicted in zip(labels.tolist(), predictions):
                confusion[actual][predicted] += 1
    correct = confusion[0][0] + confusion[1][1]
    total = sum(sum(row) for row in confusion)
    negatives = confusion[0][0] + confusion[0][1]
    positives = sum(actual_all)
    negatives_count = len(actual_all) - positives
    auc = None
    if positives and negatives_count:
        ordered = sorted(zip(scores_all, actual_all))
        positive_rank_sum = 0.0
        index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and ordered[end][0] == ordered[index][0]:
                end += 1
            average_rank = (index + 1 + end) / 2
            positive_rank_sum += average_rank * sum(label for _, label in ordered[index:end])
            index = end
        auc = (positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives_count)
    return {"auc": auc, "accuracy": correct / total, "false_positive_rate":
            confusion[0][1] / negatives if negatives else None,
            "confusion_matrix": confusion, "count": total}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path.home() / "datasets" / "fake_cnn_artifacts")
    parser.add_argument("--metrics-output", type=Path,
                        default=Path("data/models/fake_cnn_metrics.json"))
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output == repository or repository in output.parents:
        parser.error("Output must be outside the repository")
    if args.epochs < 1 or args.batch_size < 1 or args.lr <= 0:
        parser.error("epochs, batch-size, and lr must be positive")
    splits = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but no CUDA GPU is available")
    device = torch.device(args.device)
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(SEED)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    print(f"Device: {device}; GPU: {torch.cuda.get_device_name(0) if device.type == 'cuda' else 'none'}")
    print(f"Config: model=efficientnet_b0, pretrained=True, seed={SEED}, image_size={IMAGE_SIZE}, "
          f"epochs={args.epochs}, batch_size={args.batch_size}, lr={args.lr}")
    try:
        import timm
    except ImportError as exc:
        raise RuntimeError("timm is required for the plan's ImageNet pretrained EfficientNet-B0") from exc
    class_counts = Counter(row["label"] for row in splits["train"])
    weights = [1.0 / class_counts[row["label"]] for row in splits["train"]]
    sampler = WeightedRandomSampler(weights, num_samples=len(weights), replacement=True,
                                    generator=torch.Generator().manual_seed(SEED))
    loaders = {name: DataLoader(ReceiptDataset(rows, training=name == "train"),
                                batch_size=args.batch_size, sampler=sampler if name == "train" else None,
                                num_workers=0)
               for name, rows in splits.items()}
    model = timm.create_model("efficientnet_b0", pretrained=True, num_classes=2)
    model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    output.mkdir(parents=True, exist_ok=True)
    history, best_accuracy = [], -1.0
    for epoch in range(args.epochs):
        model.train()
        running_loss = 0.0
        for images, labels in loaders["train"]:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
                loss = criterion(model(images), labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            running_loss += loss.item() * len(labels)
        scheduler.step()
        val = evaluate(model, loaders["val"], device)
        metrics = {"epoch": epoch + 1, "train_loss": running_loss / len(splits["train"]), "val": val}
        history.append(metrics)
        print(json.dumps(metrics))
        if val["auc"] > best_accuracy:
            best_accuracy = val["auc"]
            torch.save({"model_state_dict": model.state_dict(), "class_to_index": LABELS,
                        "image_size": IMAGE_SIZE, "epoch": epoch + 1,
                        "model_name": "efficientnet_b0", "pretrained": True,
                        "config": {"seed": SEED, "lr": args.lr, "batch_size": args.batch_size}},
                       output / "best_model.pt")
    checkpoint = torch.load(output / "best_model.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["model_state_dict"])
    test_rows = splits["test"] + splits["unseen_real"]
    test = evaluate(model, DataLoader(ReceiptDataset(test_rows), batch_size=args.batch_size), device)
    express = evaluate(model, loaders["unseen_real"], device)
    test["express_expense_false_positive_rate"] = express["false_positive_rate"]
    test["cnn_weight_enabled"] = test["auc"] >= 0.75
    (output / "training_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    (output / "test_metrics.json").write_text(json.dumps(test, indent=2), encoding="utf-8")
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(json.dumps(test, indent=2), encoding="utf-8")
    print(f"Held-out test metrics: {json.dumps(test)}")


if __name__ == "__main__":
    main()
