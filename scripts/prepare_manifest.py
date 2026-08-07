from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


def prepare(path: Path, repository_url: str, revision: str) -> None:
    document: dict[str, Any] = json.loads(path.read_text())
    repository_url = repository_url.rstrip("/")
    document["game"]["runnable"]["source_url"] = f"{repository_url}/tree/{revision}"
    document["player"][0]["source_url"] = f"{repository_url}/tree/{revision}/codrawing/player"
    document["game"]["protocols"]["player"]["value"] = (
        f"{repository_url}/blob/{revision}/docs/player-protocol.md"
    )
    document["game"]["protocols"]["global"]["value"] = (
        f"{repository_url}/blob/{revision}/docs/global-protocol.md"
    )
    document["game"]["docs"]["readme"]["value"] = f"{repository_url}/blob/{revision}/README.md"
    path.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: prepare_manifest.py MANIFEST_TEMPLATE REPOSITORY_URL REVISION")
    prepare(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
