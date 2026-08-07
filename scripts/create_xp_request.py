from __future__ import annotations

import json
from pathlib import Path
import sys


def create(
    coworld_id: str,
    policy_ref: str,
    output_path: Path,
    turns: int,
    target: str,
    idempotency_key: str,
) -> None:
    if turns < 1 or turns > 200:
        raise ValueError("turns must be between 1 and 200")
    if target not in {"cat", "dog", "elephant"}:
        raise ValueError("target must be cat, dog, or elephant")
    payload = {
        "idempotency_key": idempotency_key,
        "coworld_id": coworld_id,
        "variant_id": "human-review",
        "game_config_overrides": {
            "max_turns": turns,
            "targets": [target],
            "action_timeout_seconds": 15,
        },
        "roster": [
            {"player": {"policy_ref": policy_ref}, "slot": slot}
            for slot in range(5)
        ],
        "num_episodes": 1,
        "notes": "Five strict LLM agents; deterministic fallback disabled.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 7:
        raise SystemExit(
            "usage: create_xp_request.py COWORLD_ID POLICY_REF OUTPUT TURNS TARGET IDEMPOTENCY_KEY"
        )
    create(sys.argv[1], sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6])
