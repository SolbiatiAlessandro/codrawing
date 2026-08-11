from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from permanent_coworld.config import DEFAULT_DATABASE
from permanent_coworld.db import CoworldDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="Local permanent collaborative pixel-art world")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    serve = commands.add_parser("serve")
    serve.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8083)
    round_parser = commands.add_parser("round")
    round_parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    round_parser.add_argument("--url", default="http://127.0.0.1:8083")
    round_parser.add_argument("--timeout", type=float, default=900)
    round_parser.add_argument("--codex-model")
    round_parser.add_argument("--claude-model")
    round_parser.add_argument("--rounds", type=int)
    round_parser.add_argument("--keep-going-after-pass", action="store_true")
    args = parser.parse_args()

    if args.command == "init":
        CoworldDatabase(args.database).initialize()
        print(f"Initialized permanent board at {args.database}")
        return 0
    if args.command == "serve":
        os.environ["PERMANENT_COWORLD_DB"] = str(args.database)
        import uvicorn

        uvicorn.run("permanent_coworld.server:app", host=args.host, port=args.port, reload=False)
        return 0
    from permanent_coworld.runner import main as round_main

    forwarded = ["--url", args.url, "--database", str(args.database), "--timeout", str(args.timeout)]
    if args.codex_model:
        forwarded += ["--codex-model", args.codex_model]
    if args.claude_model:
        forwarded += ["--claude-model", args.claude_model]
    if args.rounds is not None:
        forwarded += ["--rounds", str(args.rounds)]
    if args.keep_going_after_pass:
        forwarded.append("--keep-going-after-pass")
    return round_main(forwarded)


if __name__ == "__main__":
    sys.exit(main())
