"""Run a local episode where every seat is a full Claude Code agent session.

    .venv/bin/python scripts/run_agent_episode.py --seats 2 --turns 2 --target "light bulb"

Each seat gets a persistent claude session (resumed across turns) and its own
workspace directory under the run folder, where the agent can keep plans,
notes, and planning scripts. Artifacts land in runs/agent-<slug>-<timestamp>/.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]


async def wait_for_server(port: int, timeout: float = 30.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2):
                return
        except Exception:
            await asyncio.sleep(0.5)
    raise RuntimeError("game server did not become healthy")


async def run(seats: int, turns: int, turns_per_round: int | None, target: str, model: str, port: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = REPO_ROOT / "runs" / f"agent-{target.replace(' ', '-')}-{stamp}"
    run_dir.mkdir(parents=True)
    tokens = [secrets.token_hex(8) for _ in range(seats)]
    config = {
        "tokens": tokens,
        "players": [{"name": f"Agent {index + 1}"} for index in range(seats)],
        "width": 24,
        "height": 24,
        "max_turns": turns,
        "targets": [target],
        "player_connect_timeout_seconds": 60,
        "action_timeout_seconds": 300,
    }
    if turns_per_round:
        config["turns_per_round"] = turns_per_round
    (run_dir / "config.json").write_text(json.dumps(config, indent=2))

    server_env = os.environ | {
        "PYTHONPATH": str(REPO_ROOT),
        "COGAME_CONFIG_URI": str(run_dir / "config.json"),
        "COGAME_RESULTS_URI": str(run_dir / "results.json"),
        "COGAME_SAVE_REPLAY_URI": str(run_dir / "replay.json"),
        "COGAME_HOST": "127.0.0.1",
        "COGAME_PORT": str(port),
        "CODRAWING_QUICKDRAW_MODEL": str(
            REPO_ROOT / "codrawing" / "game" / "models" / "quickdraw_prototypes.json"
        ),
    }
    server_log = open(run_dir / "server.log", "w")
    server = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "codrawing.game.server",
        env=server_env,
        stdout=server_log,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        await wait_for_server(port)
        players, logs = [], []
        for slot in range(seats):
            workspace = run_dir / f"workspace-{slot}"
            workspace.mkdir()
            player_env = os.environ | {
                "PYTHONPATH": str(REPO_ROOT),
                "COWORLD_PLAYER_WS_URL": (
                    f"ws://127.0.0.1:{port}/player?slot={slot}&token={tokens[slot]}"
                ),
                "AGENT_MODEL": model,
                "AGENT_WORKSPACE": str(workspace),
            }
            log = open(run_dir / f"agent-{slot}.log", "w")
            logs.append(log)
            players.append(
                await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "codrawing.player.agent_player",
                    env=player_env,
                    stdout=log,
                    stderr=asyncio.subprocess.STDOUT,
                )
            )
        await server.wait()
        for player in players:
            try:
                await asyncio.wait_for(player.wait(), timeout=20)
            except TimeoutError:
                player.kill()
        for log in logs:
            log.close()
    finally:
        if server.returncode is None:
            server.kill()
        server_log.close()

    results = json.loads((run_dir / "results.json").read_text())
    print(f"run directory: {run_dir}")
    print(f"accepted pixels by seat: {results['accepted_pixels']}")
    feedback = results.get("final_image_model_feedback")
    if feedback:
        print(f"best score: {results.get('best_target_score'):.4f}")
        print(f"round scores: {results.get('round_scores')}")
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seats", type=int, default=2)
    parser.add_argument("--turns", type=int, default=2)
    parser.add_argument("--turns-per-round", type=int, default=None)
    parser.add_argument("--target", default="light bulb")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--port", type=int, default=8331)
    args = parser.parse_args()
    asyncio.run(run(args.seats, args.turns, args.turns_per_round, args.target, args.model, args.port))


if __name__ == "__main__":
    main()
