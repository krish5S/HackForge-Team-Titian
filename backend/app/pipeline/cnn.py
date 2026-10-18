"""Optional trained receipt-authenticity inference with the held-out AUC gate."""

import json
import os
from pathlib import Path

_MODEL = None
_DEVICE = None


def predict_fake_probability(image_path: str | Path) -> tuple[float, bool]:
    global _MODEL, _DEVICE
    repository = Path(__file__).resolve().parents[3]
    metrics_path = Path(os.environ.get("RECEIPT_CNN_METRICS",
                               str(repository / "data" / "models" / "fake_cnn_metrics.json")))
    checkpoint_path = Path(os.environ.get("RECEIPT_CNN_MODEL",
                                  str(Path.home() / "datasets" / "fake_cnn_artifacts" / "best_model.pt")))
    if not metrics_path.is_file() or not checkpoint_path.is_file():
        return 0.0, False
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if (not metrics.get("cnn_weight_enabled") or (metrics.get("auc") or 0) < .75 or
            (metrics.get("express_expense_false_positive_rate") or 0) > .10):
        return 0.0, False
    import timm
    import torch
    from ml.fake_cnn.prepare import letterbox
    from torchvision import transforms

    if _MODEL is None:
        _DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        checkpoint = torch.load(checkpoint_path, map_location=_DEVICE, weights_only=True)
        _MODEL = timm.create_model("efficientnet_b0", pretrained=False, num_classes=2)
        _MODEL.load_state_dict(checkpoint["model_state_dict"])
        _MODEL.to(_DEVICE).eval()
    image = letterbox(Path(image_path)).convert("RGB")
    tensor = transforms.Compose([transforms.ToTensor(),
                                 transforms.Normalize((.5, .5, .5), (.5, .5, .5))])(image)
    with torch.no_grad():
        probability = _MODEL(tensor.unsqueeze(0).to(_DEVICE)).softmax(1)[0, 1].item()
    return float(probability), True
