"""Local seat driven by a full agent harness (Claude Code session).

Unlike llm_player (one stateless model call per turn), each seat here is one
persistent Claude Code session: the first turn starts the session with the
game briefing, later turns resume it with only the new observation, and the
agent keeps a private workspace directory where it can run bash/python to
plan coordinates and keep notes between turns.

    COWORLD_PLAYER_WS_URL=... AGENT_MODEL=claude-sonnet-5 AGENT_WORKSPACE=/tmp/seat0 \
        python -m codrawing.player.agent_player
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import websockets

from codrawing.player.llm_player import (
    SEAT_COLORS,
    enforce_seat_color,
    normalize_decision,
    validate_decision,
)


def briefing(observation: dict[str, Any], slot: int) -> str:
    width, height = observation["width"], observation["height"]
    rounds = int(observation.get("rounds", 1) or 1)
    round_line = (
        f"The episode is split into {rounds} rounds of {observation.get('turns_per_round')} turns; "
        "at each round's end the score is logged and compared against other teams.\n"
        if rounds > 1
        else ""
    )
    return f"""You are seat {slot} in co/place, a cooperative pixel-art game. You and the other seats share one
{width}x{height} canvas (x grows right, y grows down) and must draw the target together: one pixel per seat per turn,
all seats act simultaneously, and if two seats paint the same pixel in the same turn both writes are dropped.
Shared target: {observation['target']}. Episode length: {observation['max_turns']} turns.
{round_line}Your paint color is {SEAT_COLORS[slot]}; #FFFFFF erases. A classifier scores the canvas after every turn
and the team's recorded score is the BEST score ever reached. The classifier is a black box - infer how it behaves
from the score deltas you observe.

You are a full agent with a private workspace directory (your current directory). USE IT:
- write yourself a PLAN file and update it as the game evolves;
- use python or shell to compute exact coordinate lists for shapes instead of guessing;
- keep a log of score deltas and what caused them, and consult it before acting.
Coordinate with the other seats through your public message: claim coordinates, divide work, follow agreements.

Each time I send you an observation, reply however you like (think, use tools), but your reply MUST end with a
single line of the form:
ACTION: {{"message": "<public message, max 240 chars>", "paint": {{"x": <int>, "y": <int>, "color": "#RRGGBB"}}}}
"""


def observation_update(observation: dict[str, Any], slot: int) -> str:
    width = observation["width"]
    painted = [
        f"{index % width},{index // width}:{color}"
        for index, color in enumerate(observation["canvas"])
        if color != "#FFFFFF"
    ]
    messages = "\n".join(
        f"T{item['turn']} seat{item['slot']}: {item['text']}"
        for item in observation.get("recent_messages", [])[-10:]
    ) or "(none)"
    feedback = observation.get("image_model_feedback")
    if feedback:
        score_line = (
            f"score {feedback['target_score']:.6f} (delta {feedback['score_delta']:+.6f}), "
            f"rank {feedback['target_rank']}/{feedback.get('label_count', '?')}, "
            f"top: {', '.join(p['label'] + ' ' + format(p['probability'], '.1%') for p in feedback['top_predictions'][:3])}"
        )
    else:
        score_line = "unavailable"
    accepted = observation.get("previous_accepted_slots", [])
    collided = observation.get("previous_collision_slots", [])
    return f"""Turn {observation['turn']} of {observation['max_turns']} (round {observation.get('round', 1)}/{observation.get('rounds', 1)}).
Classifier: {score_line}
Last turn: accepted seats {accepted}, collided seats {collided}.
Painted pixels: {'; '.join(painted) if painted else '(blank canvas)'}
Recent board:
{messages}

Decide your move. End with the ACTION line."""


def extract_last_action(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidate: dict[str, Any] | None = None
    index = 0
    while True:
        start = text.find("{", index)
        if start == -1:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict) and "message" in value and "paint" in value:
            candidate = cast(dict[str, Any], value)
        index = start + max(end, 1)
    if candidate is None:
        raise ValueError("agent reply contained no ACTION object")
    return candidate


def claude_environment() -> dict[str, str]:
    """Environment for the claude subprocess; hosted seats use the Bedrock sidecar."""
    env = os.environ.copy()
    sidecar = env.get("AWS_ENDPOINT_URL_BEDROCK_RUNTIME")
    if sidecar:
        env.setdefault("CLAUDE_CODE_USE_BEDROCK", "1")
        env.setdefault("ANTHROPIC_BEDROCK_BASE_URL", sidecar)
        env.setdefault("AWS_REGION", "us-east-1")
        # The sidecar authenticates by network position; the AWS client only
        # needs syntactically valid credentials to sign with.
        env.setdefault("AWS_ACCESS_KEY_ID", "sidecar")
        env.setdefault("AWS_SECRET_ACCESS_KEY", "sidecar")
    env.setdefault("HOME", "/tmp")
    env.setdefault("DISABLE_TELEMETRY", "1")
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    return env


async def run_claude(
    prompt: str,
    *,
    model: str,
    workspace: Path,
    session_id: str | None,
    timeout: float,
) -> tuple[str | None, str]:
    command = [
        "claude",
        "--print",
        "--verbose",
        "--output-format",
        "stream-json",
        "--model",
        model,
        "--permission-mode",
        "bypassPermissions",
    ]
    if session_id:
        command += ["--resume", session_id]
    command.append(prompt)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=workspace,
        env=claude_environment(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        raise
    if process.returncode != 0:
        raise RuntimeError(f"claude failed: {stderr.decode()[-400:]}")
    new_session: str | None = None
    result_text = ""
    for line in stdout.decode().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            if event.get("session_id"):
                new_session = str(event["session_id"])
            if event.get("type") == "result":
                result_text = str(event.get("result", ""))
    return new_session, result_text


async def main() -> None:
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    model = os.environ.get("AGENT_MODEL", "claude-sonnet-5")
    workspace = Path(os.environ.get("AGENT_WORKSPACE", "/tmp/agent-workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    timeout = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "240"))
    session_id: str | None = None
    briefed = False
    async with websockets.connect(url, max_size=None) as websocket:
        slot: int | None = None
        while True:
            try:
                pending = [await websocket.recv()]
                while True:
                    try:
                        pending.append(await asyncio.wait_for(websocket.recv(), timeout=0.05))
                    except asyncio.TimeoutError:
                        break
            except websockets.ConnectionClosed:
                return
            observation: dict[str, Any] | None = None
            for raw_message in pending:
                payload = cast(dict[str, Any], json.loads(raw_message))
                if payload["type"] == "welcome":
                    slot = int(payload["slot"])
                elif payload["type"] == "final":
                    return
                elif payload["type"] == "observation":
                    observation = payload
            if observation is None or slot is None:
                continue

            prompt = observation_update(observation, slot)
            if not briefed:
                prompt = briefing(observation, slot) + "\n" + prompt
            decision: dict[str, Any] | None = None
            for attempt in range(2):
                try:
                    session_id, reply = await run_claude(
                        prompt,
                        model=model,
                        workspace=workspace,
                        session_id=session_id,
                        timeout=timeout,
                    )
                    briefed = True
                    decision = extract_last_action(reply)
                    normalize_decision(decision)
                    enforce_seat_color(decision, slot)
                    validate_decision(decision, observation)
                    break
                except Exception as exc:
                    decision = None
                    print(f"agent attempt {attempt + 1}/2 failed on turn {observation['turn']}: {exc}", flush=True)
            if decision is None:
                continue
            print(
                json.dumps(
                    {
                        "event": "llm_action",
                        "slot": slot,
                        "turn": observation["turn"],
                        "harness": "claude-code-session",
                        "session": session_id,
                    }
                ),
                flush=True,
            )
            decision["turn"] = observation["turn"]
            await websocket.send(json.dumps(decision))


if __name__ == "__main__":
    asyncio.run(main())
