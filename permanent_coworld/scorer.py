from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

from permanent_coworld.config import MODEL_PATH, PASS_THRESHOLD, TARGET


MODEL_SIZE = 28
DRAWING_SIZE = 22


class QuickDrawPrototypeScorer:
    """Small shape classifier learned from aligned Quick, Draw! bitmaps.

    The model is deliberately color-blind. It crops the occupied canvas, scales
    it into a centered 28x28 mask, and compares that mask with per-class learned
    prototypes. A softmax over the prototype distances provides the score.
    """

    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        payload = json.loads(model_path.read_text())
        self.classes = tuple(payload["classes"])
        self.temperature = float(payload["temperature"])
        self.prototypes = {
            label: tuple(value / 255.0 for value in payload["prototypes"][label])
            for label in self.classes
        }
        if TARGET not in self.classes:
            raise ValueError(f"model does not contain target {TARGET!r}")
        if any(len(values) != MODEL_SIZE * MODEL_SIZE for values in self.prototypes.values()):
            raise ValueError("every model prototype must be 28x28")

    @staticmethod
    def _mask(
        pixels: Iterable[tuple[int, int]],
        *,
        width: int,
        height: int,
    ) -> list[float]:
        occupied = list(pixels)
        output = [0.0] * (MODEL_SIZE * MODEL_SIZE)
        if not occupied:
            return output

        min_x = min(x for x, _ in occupied)
        max_x = max(x for x, _ in occupied)
        min_y = min(y for _, y in occupied)
        max_y = max(y for _, y in occupied)
        if not (0 <= min_x <= max_x < width and 0 <= min_y <= max_y < height):
            raise ValueError("occupied pixel lies outside the canvas")

        source_width = max_x - min_x + 1
        source_height = max_y - min_y + 1
        scale = min(DRAWING_SIZE / source_width, DRAWING_SIZE / source_height)
        scaled_width = max(1, round(source_width * scale))
        scaled_height = max(1, round(source_height * scale))
        offset_x = (MODEL_SIZE - scaled_width) // 2
        offset_y = (MODEL_SIZE - scaled_height) // 2

        for x, y in occupied:
            target_x = offset_x + min(scaled_width - 1, int((x - min_x) * scale))
            target_y = offset_y + min(scaled_height - 1, int((y - min_y) * scale))
            output[target_y * MODEL_SIZE + target_x] = 1.0
        return output

    def score(
        self,
        pixels: Iterable[tuple[int, int]],
        *,
        width: int,
        height: int,
    ) -> dict[str, object]:
        mask = self._mask(pixels, width=width, height=height)
        distances = {}
        for label, prototype in self.prototypes.items():
            distances[label] = sum((value - expected) ** 2 for value, expected in zip(mask, prototype)) / len(mask)

        minimum = min(distances.values())
        weights = {
            label: math.exp(-(distance - minimum) / self.temperature)
            for label, distance in distances.items()
        }
        total = sum(weights.values())
        probabilities = {label: value / total for label, value in weights.items()}
        ordered = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        target_score = probabilities[TARGET]
        return {
            "model": "quickdraw_nearest_prototype_v1",
            "target": TARGET,
            "target_score": target_score,
            "passing": target_score > PASS_THRESHOLD,
            "pass_threshold": PASS_THRESHOLD,
            "target_rank": next(index for index, item in enumerate(ordered, 1) if item[0] == TARGET),
            "top_predictions": [
                {"label": label, "probability": probability}
                for label, probability in ordered[:5]
            ],
            "foreground_pixels": int(sum(mask)),
        }
