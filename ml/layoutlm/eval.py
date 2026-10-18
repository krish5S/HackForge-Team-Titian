"""Re-evaluate the saved LayoutLM field tagger on WildReceipt test boxes."""

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from transformers import AutoProcessor, LayoutLMv3ForTokenClassification

from ml.layoutlm.train import ReceiptBoxes, evaluate, read_jsonl


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path.home() / "datasets" / "layoutlm_prepared")
    parser.add_argument("--checkpoint", type=Path,
                        default=Path.home() / "datasets" / "layoutlm_artifacts" / "best")
    parser.add_argument("--output", type=Path, default=Path("data/models/layoutlm_metrics.json"))
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    fields = json.loads((args.data / "metadata.json").read_text(encoding="utf-8"))["fields"]
    processor = AutoProcessor.from_pretrained(args.checkpoint, apply_ocr=False)
    model = LayoutLMv3ForTokenClassification.from_pretrained(args.checkpoint)
    device = torch.device(args.device)
    model.to(device)
    loader = DataLoader(ReceiptBoxes(read_jsonl(args.data / "test.jsonl"), processor),
                        batch_size=4, num_workers=0)
    metrics = evaluate(model, loader, device, fields)
    metrics.update({"model_switch_enabled": False,
                    "model_switch_reason": "Requires measured test-month total/date accuracy above pattern reader"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics))
