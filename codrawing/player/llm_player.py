from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, cast
from urllib.parse import quote
from urllib.request import Request, urlopen

import websockets

from codrawing.player.pixel_templates import make_template


def extract_action(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response."""
    match = re.search(r"\{", text)
    if match is None:
        raise ValueError("model response did not contain JSON")
    value, _ = json.JSONDecoder().raw_decode(text[match.start() :])
    if not isinstance(value, dict):
        raise ValueError("model response was not a JSON object")
    return cast(dict[str, Any], value)


def prompt_for(observation: dict[str, Any], slot: int) -> str:
    width, height = observation["width"], observation["height"]
    painted = []
    for index, color in enumerate(observation["canvas"]):
        if color != "#FFFFFF":
            painted.append(f"{index % width},{index // width}:{color}")
    messages = "\n".join(
        f"T{item['turn']} {item['player']}: {item['text']}" for item in observation["recent_messages"]
    ) or "(none yet)"
    return f"""You are artist seat {slot} in a five-agent collaborative pixel-art game.
Shared target: {observation['target']}
Canvas: {width}x{height}; x grows right, y grows down; valid x=0..{width - 1}, y=0..{height - 1}.
Turn: {observation['turn']} of {observation['max_turns']}.
Painted pixels as x,y:#RRGGBB (all omitted pixels are white):
{'; '.join(painted) if painted else '(blank canvas)'}
Recent public board:
{messages}

Coordinate with the other artists and improve the recognizable image. Choose exactly one pixel and a short public
message. Return JSON only, with this exact shape:
{{"message":"...","paint":{{"x":0,"y":0,"color":"#RRGGBB"}}}}
"""


def call_model(prompt: str) -> str:
    sidecar = os.environ.get("AWS_ENDPOINT_URL_BEDROCK_RUNTIME")
    model = os.environ["BEDROCK_MODEL"] if sidecar else os.environ["ANTHROPIC_MODEL"]
    request_body: dict[str, Any] = {
        "model": model,
        "max_tokens": 180,
        "temperature": 0.4,
        "messages": [{"role": "user", "content": prompt}],
    }
    if sidecar:
        request_body.pop("model")
        request_body["anthropic_version"] = "bedrock-2023-05-31"
        url = f"{sidecar.rstrip('/')}/model/{quote(model, safe='')}/invoke"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
    else:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        }
    body = json.dumps(request_body).encode()
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=float(os.environ.get("MODEL_TIMEOUT_SECONDS", "10"))) as response:
        payload = json.loads(response.read())
    return "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")


def fallback_action(observation: dict[str, Any], slot: int) -> dict[str, Any]:
    plan = make_template(observation["target"], observation["width"], observation["height"])
    assigned = plan[slot :: len(observation["player_names"])]
    index = min(observation["turn"], max(len(assigned) - 1, 0))
    x, y, color = assigned[index] if assigned else (slot, 0, "#FFFFFF")
    return {"message": "", "paint": {"x": x, "y": y, "color": color}}


def validate_decision(decision: dict[str, Any], observation: dict[str, Any]) -> None:
    message, paint = decision.get("message"), decision.get("paint")
    if not isinstance(message, str) or len(message) > 240 or not isinstance(paint, dict):
        raise ValueError("invalid message or paint object")
    x, y, color = paint.get("x"), paint.get("y"), paint.get("color")
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("pixel coordinates must be integers")
    if not (0 <= x < observation["width"] and 0 <= y < observation["height"]):
        raise ValueError("pixel is outside the canvas")
    if not isinstance(color, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
        raise ValueError("color must use #RRGGBB")


async def main() -> None:
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    require_llm = os.environ.get("REQUIRE_LLM", "").lower() in {"1", "true", "yes"}
    async with websockets.connect(url) as websocket:
        slot: int | None = None
        async for raw_message in websocket:
            observation = cast(dict[str, Any], json.loads(raw_message))
            if observation["type"] == "welcome":
                slot = int(observation["slot"])
                continue
            if observation["type"] == "final":
                return
            if observation["type"] != "observation" or slot is None:
                continue
            try:
                action = await asyncio.to_thread(call_model, prompt_for(observation, slot))
                decision = extract_action(action)
                validate_decision(decision, observation)
            except Exception as exc:
                if require_llm:
                    print(f"required model call failed on turn {observation['turn']}: {exc}", flush=True)
                    raise
                print(f"model call failed; using deterministic fallback: {exc}", flush=True)
                decision = fallback_action(observation, slot)
            else:
                print(
                    json.dumps({"event": "llm_action", "slot": slot, "turn": observation["turn"]}),
                    flush=True,
                )
            decision["turn"] = observation["turn"]
            await websocket.send(json.dumps(decision))


if __name__ == "__main__":
    asyncio.run(main())
