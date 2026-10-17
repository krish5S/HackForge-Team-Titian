"""Fine-tune LayoutLMv3 on prepared WildReceipt boxes and report entity F1."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random

from PIL import Image
import torch
from torch.utils.data import DataLoader, Dataset


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class ReceiptBoxes(Dataset):
    def __init__(self, rows: list[dict], processor):
        self.rows = rows
        self.processor = processor

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        with Image.open(row["image_path"]) as image:
            encoded = self.processor(image.convert("RGB"), row["words"], boxes=row["boxes"],
                                     word_labels=row["labels"], truncation=True,
                                     padding="max_length", max_length=512, return_tensors="pt")
        return {key: value.squeeze(0) for key, value in encoded.items()}


def spans(labels: list[int]) -> set[tuple[int, int, int]]:
    # WildReceipt labels individual text boxes, so adjacent same-class boxes
    # are separate entities rather than one BIO span.
    return {(label, position, position + 1) for position, label in enumerate(labels)
            if label > 0}


def evaluate(model, loader, device, fields):
    counts = {field: Counter() for field in fields[1:]}
    model.eval()
    with torch.no_grad():
        for batch in loader:
            labels = batch["labels"].tolist()
            outputs = model(**{key: value.to(device) for key, value in batch.items()})
            predictions = outputs.logits.argmax(-1).cpu().tolist()
            for expected, predicted in zip(labels, predictions):
                valid = [(actual, guess) for actual, guess in zip(expected, predicted) if actual != -100]
                gold = spans([actual for actual, _ in valid])
                found = spans([guess for _, guess in valid])
                for class_id, field in enumerate(fields[1:], start=1):
                    actual = {span for span in gold if span[0] == class_id}
                    guessed = {span for span in found if span[0] == class_id}
                    counts[field]["tp"] += len(actual & guessed)
                    counts[field]["fp"] += len(guessed - actual)
                    counts[field]["fn"] += len(actual - guessed)
    def f1(counter):
        denominator = 2 * counter["tp"] + counter["fp"] + counter["fn"]
        return 2 * counter["tp"] / denominator if denominator else None
    combined = Counter()
    for counter in counts.values():
        combined.update(counter)
    return {"entity_f1": f1(combined),
            "per_field": {field: {"f1": f1(counter), **dict(counter)}
                          for field, counter in counts.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path.home() / "datasets" / "layoutlm_prepared")
    parser.add_argument("--output", type=Path, default=Path.home() / "datasets" / "layoutlm_artifacts")
    parser.add_argument("--metrics-output", type=Path, default=Path("data/models/layoutlm_metrics.json"))
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    if args.output.resolve() == repository or repository in args.output.resolve().parents:
        parser.error("Model checkpoints must stay outside Git")
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA is unavailable")
    if args.epochs < 1:
        parser.error("epochs must be positive")
    from transformers import AutoProcessor, LayoutLMv3ForTokenClassification, get_linear_schedule_with_warmup

    fields = json.loads((args.data / "metadata.json").read_text(encoding="utf-8"))["fields"]
    torch.manual_seed(42)
    random.seed(42)
    processor = AutoProcessor.from_pretrained("microsoft/layoutlmv3-base", apply_ocr=False)
    model = LayoutLMv3ForTokenClassification.from_pretrained(
        "microsoft/layoutlmv3-base", num_labels=len(fields),
        id2label={index: field for index, field in enumerate(fields)},
        label2id={field: index for index, field in enumerate(fields)},
        ignore_mismatched_sizes=True)
    device = torch.device(args.device)
    if device.type == "cuda":
        model.gradient_checkpointing_enable()
    model.to(device)
    loaders = {name: DataLoader(ReceiptBoxes(read_jsonl(args.data / f"{name}.jsonl"), processor),
                                batch_size=4, shuffle=name == "train", num_workers=0)
               for name in ("train", "val", "test")}
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-5)
    steps_per_epoch = math.ceil(len(loaders["train"]) / 2)
    total_steps = steps_per_epoch * args.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=max(1, round(total_steps * .1)),
                                                num_training_steps=total_steps)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    best_f1 = -1.0
    args.output.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        running_loss = 0.0
        for batch_index, batch in enumerate(loaders["train"]):
            batch = {key: value.to(device) for key, value in batch.items()}
            with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
                loss = model(**batch).loss / 2
            scaler.scale(loss).backward()
            running_loss += loss.item() * 2
            if (batch_index + 1) % 2 == 0 or batch_index + 1 == len(loaders["train"]):
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
        validation = evaluate(model, loaders["val"], device, fields)
        print(json.dumps({"epoch": epoch + 1, "train_loss": running_loss / len(loaders["train"]),
                          "val": validation}), flush=True)
        current = validation["entity_f1"] or 0
        if current > best_f1:
            best_f1 = current
            model.save_pretrained(args.output / "best")
            processor.save_pretrained(args.output / "best")
    model = LayoutLMv3ForTokenClassification.from_pretrained(args.output / "best").to(device)
    test = evaluate(model, loaders["test"], device, fields)
    test.update({"checkpoint": "microsoft/layoutlmv3-base", "epochs": args.epochs,
                 "batch_size": 4, "gradient_accumulation": 2, "learning_rate": 3e-5,
                 "model_switch_enabled": False,
                 "model_switch_reason": "Requires measured test-month total/date accuracy above pattern reader"})
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(json.dumps(test, indent=2), encoding="utf-8")
    print(json.dumps(test), flush=True)


if __name__ == "__main__":
    main()
