"""Re-evaluate a saved CNN on the untouched test and Express Expense splits."""

import argparse
import json
from pathlib import Path

import timm
import torch
from torch.utils.data import DataLoader

from ml.fake_cnn.train import ReceiptDataset, evaluate, validate_manifest


def evaluate_checkpoint(manifest: Path, checkpoint: Path, device: str = "cuda") -> dict:
    splits = validate_manifest(json.loads(manifest.read_text(encoding="utf-8")))
    target = torch.device(device)
    payload = torch.load(checkpoint, map_location=target, weights_only=True)
    model = timm.create_model("efficientnet_b0", pretrained=False, num_classes=2)
    model.load_state_dict(payload["model_state_dict"])
    model.to(target)
    combined = evaluate(model, DataLoader(ReceiptDataset(splits["test"] + splits["unseen_real"]),
                                          batch_size=32), target)
    express = evaluate(model, DataLoader(ReceiptDataset(splits["unseen_real"]), batch_size=32), target)
    combined["express_expense_false_positive_rate"] = express["false_positive_rate"]
    combined["cnn_weight_enabled"] = (combined["auc"] >= .75 and
                                      express["false_positive_rate"] <= .10)
    combined["cnn_gate"] = {"minimum_auc": .75, "maximum_unseen_real_fpr": .10,
                            "reason": "enabled" if combined["cnn_weight_enabled"] else
                                      "held-out AUC or unseen-source false-positive rate failed"}
    return combined


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path,
                        default=Path.home() / "datasets" / "fake_cnn_artifacts" / "best_model.pt")
    parser.add_argument("--output", type=Path, default=Path("data/models/fake_cnn_metrics.json"))
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    metrics = evaluate_checkpoint(args.manifest, args.checkpoint, args.device)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics))
