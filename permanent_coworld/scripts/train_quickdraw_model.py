from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import json
import math
from pathlib import Path
import struct
from urllib.parse import quote
from urllib.request import Request, urlopen


CLASSES = (
    "light bulb",
    "hot air balloon",
    "candle",
    "flashlight",
    "lollipop",
    "pear",
    "sun",
    "wine glass",
    "clock",
    "snowman",
)
BASE_URL = "https://storage.googleapis.com/quickdraw_dataset/full/numpy_bitmap"
DIMENSIONS = 28 * 28
TEMPERATURE = 0.002
PASS_THRESHOLD = 0.95


def npy_header_size(prefix: bytes) -> tuple[int, tuple[int, ...]]:
    if prefix[:6] != b"\x93NUMPY":
        raise ValueError("download did not start with an NPY header")
    major = prefix[6]
    if major == 1:
        length = struct.unpack("<H", prefix[8:10])[0]
        start = 10
    else:
        length = struct.unpack("<I", prefix[8:12])[0]
        start = 12
    metadata = ast.literal_eval(prefix[start : start + length].decode("latin1"))
    return start + length, tuple(metadata["shape"])


def download_prefix(label: str, samples: int) -> tuple[bytes, int, int]:
    url = f"{BASE_URL}/{quote(label)}.npy"
    header_request = Request(url, headers={"Range": "bytes=0-255"})
    with urlopen(header_request, timeout=30) as response:
        prefix = response.read()
    header_size, shape = npy_header_size(prefix)
    if len(shape) != 2 or shape[1] != DIMENSIONS or shape[0] < samples:
        raise ValueError(f"unexpected shape for {label}: {shape}")
    end = header_size + samples * DIMENSIONS - 1
    request = Request(url, headers={"Range": f"bytes=0-{end}"})
    with urlopen(request, timeout=60) as response:
        payload = response.read()
    body = payload[header_size:]
    expected = samples * DIMENSIONS
    if len(body) != expected:
        raise ValueError(f"expected {expected} bitmap bytes for {label}, received {len(body)}")
    return body, header_size, shape[0]


def prototype(body: bytes, samples: int) -> list[int]:
    sums = [0] * DIMENSIONS
    for sample in range(samples):
        row = body[sample * DIMENSIONS : (sample + 1) * DIMENSIONS]
        for index, value in enumerate(row):
            sums[index] += value
    return [round(value / samples) for value in sums]


def probabilities(row: bytes, prototypes: dict[str, list[int]]) -> dict[str, float]:
    distances = {}
    for label, expected in prototypes.items():
        distances[label] = sum(
            ((value - prototype_value) / 255.0) ** 2
            for value, prototype_value in zip(row, expected)
        ) / DIMENSIONS
    minimum = min(distances.values())
    weights = {label: math.exp(-(distance - minimum) / TEMPERATURE) for label, distance in distances.items()}
    total = sum(weights.values())
    return {label: weight / total for label, weight in weights.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--train-samples", type=int, default=1500)
    parser.add_argument("--validation-samples", type=int, default=100)
    args = parser.parse_args()
    total_samples = args.train_samples + args.validation_samples
    prototypes = {}
    validation = {}
    source_counts = {}
    for label in CLASSES:
        body, _, available = download_prefix(label, total_samples)
        prototypes[label] = prototype(body[: args.train_samples * DIMENSIONS], args.train_samples)
        validation[label] = body[args.train_samples * DIMENSIONS :]
        source_counts[label] = available
        print(f"learned {label!r} from {args.train_samples} bitmaps")

    correct = 0
    passing_light_bulbs = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for actual, body in validation.items():
        for index in range(args.validation_samples):
            row = body[index * DIMENSIONS : (index + 1) * DIMENSIONS]
            scores = probabilities(row, prototypes)
            predicted = max(scores, key=scores.get)
            confusion[actual][predicted] += 1
            correct += predicted == actual
            if actual == "light bulb" and scores[actual] > PASS_THRESHOLD:
                passing_light_bulbs += 1

    evaluated = args.validation_samples * len(CLASSES)
    payload = {
        "format": "quickdraw_nearest_prototype_v1",
        "classes": list(CLASSES),
        "target": "light bulb",
        "temperature": TEMPERATURE,
        "pass_threshold": PASS_THRESHOLD,
        "train_samples_per_class": args.train_samples,
        "validation_samples_per_class": args.validation_samples,
        "validation_accuracy": correct / evaluated,
        "validation_light_bulb_pass_rate": passing_light_bulbs / args.validation_samples,
        "source": "Google Quick, Draw! numpy_bitmap",
        "source_base_url": BASE_URL,
        "source_class_counts": source_counts,
        "prototypes": prototypes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"wrote {args.output} ({args.output.stat().st_size} bytes)")
    print(f"validation accuracy: {payload['validation_accuracy']:.1%}")
    print(f"light-bulb examples above {PASS_THRESHOLD:.0%}: {payload['validation_light_bulb_pass_rate']:.1%}")


if __name__ == "__main__":
    main()
