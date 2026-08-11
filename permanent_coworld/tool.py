from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def call(method: str, endpoint: str, body: Optional[object] = None) -> int:
    base_url = os.environ.get("COWORLD_URL", "http://127.0.0.1:8083").rstrip("/")
    token = os.environ.get("COWORLD_TOKEN")
    if not token:
        print(json.dumps({"error": "COWORLD_TOKEN is not set"}))
        return 2
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        base_url + endpoint,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            print(json.dumps(json.load(response), indent=2))
            return 0
    except HTTPError as error:
        print(error.read().decode())
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="The only board API client agents should use.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("board")
    commands.add_parser("score")
    commands.add_parser("messages")
    say = commands.add_parser("say")
    say.add_argument("message")
    for command in ("paint", "erase"):
        pixel = commands.add_parser(command)
        pixel.add_argument("x", type=int)
        pixel.add_argument("y", type=int)
    args = parser.parse_args()
    if args.command == "board":
        return call("GET", "/api/board")
    if args.command == "score":
        return call("GET", "/api/score")
    if args.command == "messages":
        return call("GET", "/api/messages")
    if args.command == "say":
        return call("POST", "/api/messages", {"message": args.message})
    return call("POST", "/api/pixel", {"x": args.x, "y": args.y, "action": args.command})


if __name__ == "__main__":
    sys.exit(main())
