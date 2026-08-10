"""Seat driven by a Claude Code agent session with real game tools.

Each seat is one persistent Claude Agent SDK session. The game is exposed to
the agent as in-process MCP tools:

- post_message(text): post to the shared public board, visible to all seats
  immediately (live, mid-turn).
- read_board(): read the latest board messages, including posts made by other
  seats during the current turn.
- paint_pixel(x, y, color): submit this turn's single pixel. The game turn
  resolves only when every seat has painted.

The agent works freely (thinks, uses bash/python/files in its workspace,
posts and reads board messages) until it decides to call paint_pixel.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import websockets
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
    tool,
)

from codrawing.player.llm_player import SEAT_COLORS

COLOR_HINT = "#RRGGBB"


def claude_environment() -> None:
    """Set env for the claude subprocess; hosted seats use the Bedrock sidecar."""
    env = os.environ
    sidecar = env.get("AWS_ENDPOINT_URL_BEDROCK_RUNTIME")
    if sidecar:
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        env["ANTHROPIC_BEDROCK_BASE_URL"] = sidecar
        env.setdefault("AWS_REGION", "us-east-1")
        # The sidecar authenticates by network position; the AWS client only
        # needs syntactically valid credentials to sign with.
        env.setdefault("AWS_ACCESS_KEY_ID", "sidecar")
        env.setdefault("AWS_SECRET_ACCESS_KEY", "sidecar")
        home = Path("/tmp/claude-home")
        home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(home)
    env.setdefault("DISABLE_TELEMETRY", "1")
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")


class Seat:
    def __init__(self) -> None:
        self.websocket: Any = None
        self.slot: int | None = None
        self.turn: int = 0
        self.painted: bool = False
        self.board: list[dict[str, Any]] = []
        self.observations: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    @property
    def color(self) -> str:
        return SEAT_COLORS[self.slot or 0]

    async def reader(self) -> None:
        try:
            async for raw in self.websocket:
                payload = cast(dict[str, Any], json.loads(raw))
                kind = payload.get("type")
                if kind == "welcome":
                    self.slot = int(payload["slot"])
                elif kind == "board_update":
                    self.board.append(payload["message"])
                elif kind == "observation":
                    for message in payload.get("messages", []):
                        if message not in self.board:
                            self.board.append(message)
                    await self.observations.put(payload)
                elif kind == "final":
                    await self.observations.put(None)
                    return
        except websockets.ConnectionClosed:
            await self.observations.put(None)


seat = Seat()


@tool(
    "post_message",
    "Post a message (max 240 chars) to the shared public board. All seats see it immediately.",
    {"text": str},
)
async def post_message(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", ""))[:240]
    await seat.websocket.send(json.dumps({"type": "message", "turn": seat.turn, "text": text}))
    return {"content": [{"type": "text", "text": "posted"}]}


@tool(
    "read_board",
    "Read the latest shared board messages, including posts other seats made during this turn.",
    {},
)
async def read_board(args: dict[str, Any]) -> dict[str, Any]:
    tail = seat.board[-30:]
    text = "\n".join(f"T{m['turn']} seat{m['slot']}: {m['text']}" for m in tail) or "(board is empty)"
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "paint_pixel",
    "Submit your single pixel for this turn. This ends your turn. Use your seat color, or #FFFFFF to erase.",
    {"x": int, "y": int, "color": str},
)
async def paint_pixel(args: dict[str, Any]) -> dict[str, Any]:
    if seat.painted:
        return {"content": [{"type": "text", "text": "you already painted this turn"}]}
    try:
        x, y = int(args["x"]), int(args["y"])
    except (KeyError, TypeError, ValueError):
        return {"content": [{"type": "text", "text": "x and y must be integers"}], "is_error": True}
    color = str(args.get("color", seat.color)).upper()
    if color != "#FFFFFF":
        color = seat.color
    await seat.websocket.send(
        json.dumps({"turn": seat.turn, "message": "", "paint": {"x": x, "y": y, "color": color}})
    )
    seat.painted = True
    return {
        "content": [
            {"type": "text", "text": f"submitted ({x},{y}) {color}; the turn resolves when all seats have painted"}
        ]
    }


def briefing(observation: dict[str, Any], slot: int) -> str:
    width, height = observation["width"], observation["height"]
    rounds = int(observation.get("rounds", 1) or 1)
    round_line = (
        f"The episode has {rounds} rounds of {observation.get('turns_per_round')} turns. "
        "At each round's end the score is logged and compared against other teams.\n"
        if rounds > 1
        else ""
    )
    return f"""You are agent {slot}, one of five agents in co/place, a cooperative pixel-art game. You share one
{width}x{height} canvas (x right, y down) and must draw the target together. Target: {observation['target']}.
Episode length: {observation['max_turns']} turns. {round_line}All seats act in the same turn. Each seat paints exactly
one pixel per turn with the paint_pixel tool. If two seats paint the same pixel in the same turn, both writes are
dropped. Your paint color is {SEAT_COLORS[slot]}; #FFFFFF erases. A black-box classifier scores the canvas after
every turn; the team's recorded score is the BEST score ever reached; infer the classifier's behavior from deltas.

How to play each turn:
1. Use read_board to see what the other agents are saying right now.
2. Talk with post_message: on your FIRST turn, introduce yourself ("I am agent {slot}...") and state your strategy.
   In later turns, coordinate: claim coordinates, divide work, react to what others post this turn.
3. Plan in your private workspace: keep a PLAN file, use python to compute exact coordinates.
4. When coordination is clear, call paint_pixel EXACTLY ONCE, then end your reply. The game turn resolves only when
   all five seats have painted, so do not stall forever - a few board posts, then paint.
5. BE FAST. You have a strict time budget per turn; a seat that misses the paint window loses its pixel. Each turn:
   read_board once, post at most TWO short messages, then paint. Post exact coordinates ("seat N takes (x,y)"), not
   vague zones. Long file work is only worth it once, early, to compute the full point plan.
"""


def observation_text(observation: dict[str, Any]) -> str:
    width = observation["width"]
    painted = [
        f"{index % width},{index // width}:{color}"
        for index, color in enumerate(observation["canvas"])
        if color != "#FFFFFF"
    ]
    feedback = observation.get("image_model_feedback")
    if feedback:
        score_line = (
            f"score {feedback['target_score']:.6f} (delta {feedback['score_delta']:+.6f}), "
            f"rank {feedback['target_rank']}/{feedback.get('label_count', '?')}, "
            f"top: {', '.join(p['label'] + ' ' + format(p['probability'], '.1%') for p in feedback['top_predictions'][:3])}"
        )
    else:
        score_line = "unavailable"
    return f"""Turn {observation['turn']} of {observation['max_turns']} (round {observation.get('round', 1)}/{observation.get('rounds', 1)}).
Classifier: {score_line}
Last turn accepted seats: {observation.get('previous_accepted_slots', [])}; collided: {observation.get('previous_collision_slots', [])}.
Painted pixels: {'; '.join(painted) if painted else '(blank canvas)'}

Your turn: read the board, coordinate, then call paint_pixel once."""


async def main() -> None:
    claude_environment()
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    model = os.environ.get("AGENT_MODEL", "claude-sonnet-5")
    workspace = Path(os.environ.get("AGENT_WORKSPACE", "/tmp/agent-workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    turn_timeout = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "240"))

    async with websockets.connect(url, max_size=None) as websocket:
        seat.websocket = websocket
        reader = asyncio.create_task(seat.reader())
        try:
            first = await seat.observations.get()
            if first is None or seat.slot is None:
                return
            game_server = create_sdk_mcp_server(
                name="game", tools=[post_message, read_board, paint_pixel]
            )
            options = ClaudeAgentOptions(
                system_prompt=briefing(first, seat.slot),
                mcp_servers={"game": game_server},
                allowed_tools=[
                    "Bash",
                    "Read",
                    "Write",
                    "Edit",
                    "Glob",
                    "Grep",
                    "mcp__game__post_message",
                    "mcp__game__read_board",
                    "mcp__game__paint_pixel",
                ],
                permission_mode="bypassPermissions",
                cwd=str(workspace),
                model=model,
                max_turns=30,
            )
            async with ClaudeSDKClient(options=options) as client:
                observation: dict[str, Any] | None = first
                while observation is not None:
                    seat.turn = int(observation["turn"])
                    seat.painted = False
                    prompt = observation_text(observation)
                    for nudge in range(3):
                        budget = turn_timeout if nudge == 0 else 25.0
                        try:
                            reply = await asyncio.wait_for(_run_query(client, prompt), timeout=budget)
                        except (TimeoutError, asyncio.TimeoutError):
                            print(f"turn {seat.turn}: agent query timed out", flush=True)
                            if nudge == 2 or seat.painted:
                                break
                            reply = ""
                        except Exception as exc:
                            print(f"turn {seat.turn}: agent query failed: {exc!r}", flush=True)
                            break
                        if seat.painted:
                            break
                        if reply:
                            print(f"turn {seat.turn}: no paint in reply: {reply[:200]}", flush=True)
                        prompt = "You have not painted yet. Call paint_pixel immediately."
                    if seat.painted:
                        print(
                            json.dumps(
                                {
                                    "event": "llm_action",
                                    "slot": seat.slot,
                                    "turn": seat.turn,
                                    "harness": "claude-agent-sdk",
                                }
                            ),
                            flush=True,
                        )
                    else:
                        print(f"turn {seat.turn}: no paint submitted", flush=True)
                    observation = await seat.observations.get()
        finally:
            reader.cancel()


async def _run_query(client: ClaudeSDKClient, prompt: str) -> str:
    await client.query(prompt)
    parts: list[str] = []
    async for message in client.receive_response():
        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        result = getattr(message, "result", None)
        if result:
            parts.append(str(result))
        if getattr(message, "is_error", False):
            parts.append(f"[error message: {message}]")
    return " ".join(parts)


if __name__ == "__main__":
    asyncio.run(main())
