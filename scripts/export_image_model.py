from __future__ import annotations

import json
from pathlib import Path
import sys

import torch
from torchvision.models import SqueezeNet1_1_Weights, squeezenet1_1


def export(model_path: Path, labels_path: Path) -> None:
    weights = SqueezeNet1_1_Weights.IMAGENET1K_V1
    model = squeezenet1_1(weights=weights).eval()
    example = torch.zeros(1, 3, 224, 224)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        example,
        model_path,
        input_names=["image"],
        output_names=["logits"],
        opset_version=17,
        dynamo=False,
    )
    labels_path.write_text(json.dumps(list(weights.meta["categories"])))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: export_image_model.py MODEL.onnx LABELS.json")
    export(Path(sys.argv[1]), Path(sys.argv[2]))
