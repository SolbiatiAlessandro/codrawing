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
    turns_per_round: int = 10,
) -> None:
    if turns < 1 or turns > 200:
        raise ValueError("turns must be between 1 and 200")
    if target not in {"cat", "dog", "elephant", "light bulb"}:
        raise ValueError("target must be cat, dog, elephant, or light bulb")
    if turns_per_round < 1 or turns_per_round > 200:
        raise ValueError("turns_per_round must be between 1 and 200")
    payload = {
        "idempotency_key": idempotency_key,
        "coworld_id": coworld_id,
        "variant_id": "light-bulb" if target == "light bulb" else "human-review",
        "game_config_overrides": {
            "max_turns": turns,
            "turns_per_round": min(turns_per_round, turns),
            "targets": [target],
            "player_connect_timeout_seconds": 120,
            "action_timeout_seconds": 120,
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
    if len(sys.argv) not in (7, 8):
        raise SystemExit(
            "usage: create_xp_request.py COWORLD_ID POLICY_REF OUTPUT TURNS TARGET IDEMPOTENCY_KEY [TURNS_PER_ROUND]"
        )
    create(
        sys.argv[1],
        sys.argv[2],
        Path(sys.argv[3]),
        int(sys.argv[4]),
        sys.argv[5],
        sys.argv[6],
        int(sys.argv[7]) if len(sys.argv) == 8 else 10,
    )
