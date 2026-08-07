from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


MODEL_NAME = "squeezenet1_1_imagenet1k_v1"
PASS_THRESHOLD = 0.5

# ILSVRC-2012 indices in TorchVision's canonical category order. A group score
# is useful here because ImageNet splits cats, dogs, and elephants into breeds.
TARGET_INDICES = {
    "cat": tuple(range(281, 286)),
    "dog": tuple(range(151, 269)),
    "elephant": (101, 385, 386),
}


class ImageModelScorer:
    """Small ImageNet classifier used as shared, per-turn team feedback."""

    def __init__(self, model_path: Path, labels_path: Path) -> None:
        import numpy as np
        import onnxruntime as ort

        self.np = np
        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.labels = json.loads(labels_path.read_text())
        if len(self.labels) != 1000:
            raise ValueError("image model labels must contain 1000 ImageNet classes")

    def score(
        self,
        *,
        canvas: list[str],
        width: int,
        height: int,
        target: str,
        turn: int,
        previous_score: float | None,
    ) -> dict[str, Any]:
        from PIL import Image

        if target not in TARGET_INDICES:
            raise ValueError(f"image model has no target mapping for {target!r}")
        if len(canvas) != width * height:
            raise ValueError("canvas length does not match its dimensions")

        pixels = [tuple(bytes.fromhex(color.removeprefix("#"))) for color in canvas]
        image = Image.new("RGB", (width, height))
        image.putdata(pixels)
        image = image.resize((256, 256), Image.Resampling.BILINEAR)
        image = image.crop((16, 16, 240, 240))

        array = self.np.asarray(image, dtype=self.np.float32) / 255.0
        array = (array - self.np.array([0.485, 0.456, 0.406], dtype=self.np.float32)) / self.np.array(
            [0.229, 0.224, 0.225], dtype=self.np.float32
        )
        batch = self.np.transpose(array, (2, 0, 1))[None, ...]
        logits = self.session.run(None, {self.input_name: batch})[0][0]
        probabilities = self.np.exp(logits - logits.max())
        probabilities /= probabilities.sum()

        target_indices = TARGET_INDICES[target]
        target_score = float(probabilities[list(target_indices)].sum())
        best_target_index = max(target_indices, key=lambda index: float(probabilities[index]))
        ordered = self.np.argsort(probabilities)[::-1]
        target_rank = int(self.np.where(ordered == best_target_index)[0][0]) + 1
        top_indices = ordered[:5]
        delta = 0.0 if previous_score is None else target_score - previous_score

        return {
            "model": MODEL_NAME,
            "turn": turn,
            "target_score": target_score,
            "score_delta": delta,
            "pass_threshold": PASS_THRESHOLD,
            "passing": target_score > PASS_THRESHOLD,
            "target_rank": target_rank,
            "best_target_label": self.labels[best_target_index],
            "top_predictions": [
                {
                    "label": self.labels[int(index)],
                    "probability": float(probabilities[int(index)]),
                }
                for index in top_indices
            ],
        }


def scorer_from_environment() -> ImageModelScorer | None:
    model_path = os.environ.get("CODRAWING_IMAGE_MODEL")
    if not model_path:
        return None
    labels_path = os.environ.get("CODRAWING_IMAGE_MODEL_LABELS")
    if not labels_path:
        raise ValueError("CODRAWING_IMAGE_MODEL_LABELS is required when the image model is enabled")
    return ImageModelScorer(Path(model_path), Path(labels_path))
