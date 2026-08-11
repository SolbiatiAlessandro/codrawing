from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.error import URLError
from urllib.request import Request, urlopen

from permanent_coworld.audit import audit_output
from permanent_coworld.config import (
    AGENTS_DIR,
    CLAUDE_MODEL,
    CODEX_MODEL,
    DEFAULT_DATABASE,
    ROOT,
    SNAPSHOTS_DIR,
    TRACES_DIR,
)
from permanent_coworld.db import CoworldDatabase


REPO_ROOT = ROOT.parent


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_path(slug: str) -> Path:
    return AGENTS_DIR / slug / ".session.json"


def load_session(slug: str) -> dict[str, str]:
    path = session_path(slug)
    return json.loads(path.read_text()) if path.exists() else {}


def save_session(slug: str, provider: str, session_id: str) -> None:
    session_path(slug).write_text(json.dumps({"provider": provider, "session_id": session_id}, indent=2) + "\n")


def parse_session_id(provider: str, output: str) -> str | None:
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if provider == "codex" and event.get("type") == "thread.started":
            return event.get("thread_id")
        session_id = event.get("session_id")
        if session_id:
            return str(session_id)
        result = event.get("result")
        if isinstance(result, dict) and result.get("session_id"):
            return str(result["session_id"])
    return None


def parse_actual_model(output: str) -> str | None:
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        model = event.get("model")
        if isinstance(model, str):
            return model
        message = event.get("message")
        if isinstance(message, dict) and isinstance(message.get("model"), str):
            return message["model"]
    return None


def prompt(slug: str, round_id: int, snapshot_path: Path) -> str:
    character = (AGENTS_DIR / slug / "CHARACTER.md").read_text()
    rules = (ROOT / "PROMPT.md").read_text().format(
        round_id=round_id,
        snapshot_path=snapshot_path,
    )
    return f"{character}\n\n{rules}"


def command_for(
    provider: str,
    slug: str,
    text: str,
    model: str | None,
    snapshot_path: Path,
) -> tuple[list[str], str]:
    agent_dir = AGENTS_DIR / slug
    prior = load_session(slug)
    prior_id = prior.get("session_id") if prior.get("provider") == provider else None
    if provider == "codex":
        if prior_id:
            command = [
                "codex", "exec", "resume", "--json",
                "--config", "sandbox_workspace_write.network_access=true",
                "--image", str(snapshot_path),
                prior_id, "-",
            ]
        else:
            command = [
                "codex", "exec", "--json", "--sandbox", "workspace-write",
                "--config", "sandbox_workspace_write.network_access=true",
                "--image", str(snapshot_path),
                "--skip-git-repo-check", "--cd", str(agent_dir), "-",
            ]
        if model:
            command[2:2] = ["--model", model]
        return command, prior_id or ""
    if provider == "claude":
        if prior_id:
            command = [
                "claude", "--print", "--verbose", "--output-format", "stream-json",
                "--resume", prior_id,
                "--allowedTools", f"Bash(python3 -m permanent_coworld.tool *),Read({snapshot_path})",
                "--permission-mode", "bypassPermissions", text,
            ]
        else:
            new_id = str(uuid.uuid4())
            command = [
                "claude", "--print", "--verbose", "--output-format", "stream-json",
                "--session-id", new_id,
                "--allowedTools", f"Bash(python3 -m permanent_coworld.tool *),Read({snapshot_path})",
                "--permission-mode", "bypassPermissions", text,
            ]
        if model:
            command[1:1] = ["--model", model]
        return command, prior_id or ""
    raise ValueError(f"unsupported provider {provider!r}")


async def run_agent(
    wake: dict[str, object],
    *,
    url: str,
    timeout: float,
    codex_model: str | None,
    claude_model: str | None,
    db: CoworldDatabase,
    snapshot_path: Path,
) -> dict[str, object]:
    agent = wake["agent"]
    provider = agent.provider
    text = prompt(agent.slug, int(wake["round_id"]), snapshot_path)
    override = codex_model if provider == "codex" else claude_model
    model = override or agent.model
    command, prior_id = command_for(provider, agent.slug, text, model, snapshot_path)
    environment = os.environ.copy()
    environment.update(
        {
            "COWORLD_URL": url,
            "COWORLD_TOKEN": str(wake["token"]),
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    started_at = now()
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=AGENTS_DIR / agent.slug,
        env=environment,
        stdin=asyncio.subprocess.PIPE if provider == "codex" else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if provider == "codex" and process.stdin is not None:
        process.stdin.write(text.encode())
        await process.stdin.drain()
        process.stdin.close()
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []

    async def consume_stdout() -> None:
        assert process.stdout is not None
        while line := await process.stdout.readline():
            stdout_parts.append(line)

    async def consume_stderr() -> None:
        assert process.stderr is not None
        while line := await process.stderr.readline():
            stderr_parts.append(line)

    stdout_task = asyncio.create_task(consume_stdout())
    stderr_task = asyncio.create_task(consume_stderr())
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        process.terminate()
        await process.wait()
    await asyncio.gather(stdout_task, stderr_task)
    completed_at = now()
    stdout_bytes = b"".join(stdout_parts)
    stderr_bytes = b"".join(stderr_parts)
    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")
    violations = audit_output(provider, stdout)
    session_id = parse_session_id(provider, stdout) or prior_id
    actual_model = parse_actual_model(stdout) or model
    if session_id:
        save_session(agent.slug, provider, session_id)

    trace_dir = TRACES_DIR / f"round-{wake['round_id']:06d}"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{agent.slug}.jsonl.gz"
    trace_content = json.dumps(
        {"command": command, "started_at": started_at, "completed_at": completed_at},
        separators=(",", ":"),
    ) + "\n" + stdout
    if stderr:
        trace_content += json.dumps({"type": "runner.stderr", "text": stderr}, separators=(",", ":")) + "\n"
    with gzip.open(trace_path, "wt", encoding="utf-8") as trace:
        trace.write(trace_content)
    digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    db.record_run(
        round_id=wake["round_id"],
        wake_id=wake["wake_id"],
        agent_id=wake["agent_id"],
        provider=provider,
        requested_model=model,
        actual_model=actual_model,
        session_id=session_id,
        started_at=started_at,
        completed_at=completed_at,
        return_code=124 if timed_out else (process.returncode if process.returncode is not None else 1),
        valid=not violations,
        violations=violations,
        trace_path=str(trace_path.relative_to(ROOT)),
        trace_sha256=digest,
    )
    db.finish_wake(int(wake["wake_id"]), status="timeout" if timed_out else "complete")
    return {
        "agent": agent.name,
        "provider": provider,
        "requested_model": model,
        "actual_model": actual_model,
        "return_code": 124 if timed_out else process.returncode,
        "session_id": session_id,
        "valid": not violations,
        "violations": violations,
        "trace": str(trace_path),
    }


def server_ready(url: str) -> bool:
    try:
        with urlopen(url.rstrip("/") + "/api/public/state", timeout=3) as response:
            return response.status == 200
    except URLError:
        return False


def fetch_start_snapshot(url: str, wakes: list[dict[str, object]], round_id: int) -> Path:
    images = []
    for wake in wakes:
        request = Request(
            url.rstrip("/") + "/api/snapshot.png",
            headers={"Authorization": f"Bearer {wake['token']}"},
        )
        with urlopen(request, timeout=10) as response:
            images.append(response.read())
    if not images or any(image != images[0] for image in images[1:]):
        raise RuntimeError("agents did not receive an identical start snapshot")
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"round-{round_id:06d}-start.png"
    path.write_bytes(images[0])
    return path


async def run_one_round(
    args: argparse.Namespace,
    db: CoworldDatabase,
) -> tuple[bool, dict[str, object]]:
    round_id, wakes = db.begin_round()
    try:
        snapshot_path = fetch_start_snapshot(args.url, wakes, round_id)
        print(f"Starting permanent-board round {round_id} with five concurrent subscription sessions.")
        results = await asyncio.gather(*(
            run_agent(
                wake,
                url=args.url,
                timeout=args.timeout,
                codex_model=args.codex_model,
                claude_model=args.claude_model,
                db=db,
                snapshot_path=snapshot_path,
            )
            for wake in wakes
        ))
    finally:
        db.finish_round(round_id)
    for result in results:
        print(json.dumps(result, separators=(",", ":"), default=str))
    state = db.state()
    summary = {
        "round": round_id,
        "score": state["score"],
        "occupied_pixels": len(state["pixels"]),
    }
    print(json.dumps(summary, indent=2))
    complete = len(results) == 5
    successful = all(result["return_code"] == 0 for result in results)
    invalid = [str(result["agent"]) for result in results if not bool(result.get("valid", True))]
    if invalid:
        print(
            "Trace audit warning (recorded, round will continue): " + ", ".join(invalid),
            file=sys.stderr,
        )
    return complete and successful, summary


async def run_rounds(args: argparse.Namespace) -> int:
    if not server_ready(args.url):
        print(f"Coworld server is not reachable at {args.url}. Start it with `python -m permanent_coworld serve`.", file=sys.stderr)
        return 2
    if args.rounds is not None and args.rounds < 1:
        print("--rounds must be at least 1", file=sys.stderr)
        return 2
    db = CoworldDatabase(args.database)
    initial_score = db.state()["score"]
    if bool(initial_score.get("passing")) and not args.keep_going_after_pass:
        print("The permanent board already passes the classifier; no new round is needed.")
        return 0
    completed = 0
    while args.rounds is None or completed < args.rounds:
        sequence = completed + 1
        destination = str(args.rounds) if args.rounds is not None else "until pass"
        print(f"\n=== Coworld sequence {sequence}/{destination} ===")
        successful, summary = await run_one_round(args, db)
        completed += 1
        if not successful:
            print("Stopping: at least one resident process failed.", file=sys.stderr)
            return 1
        score = summary["score"]
        if bool(score.get("passing")) and not args.keep_going_after_pass:
            print(f"Stopping early after {completed} round(s): the board passed the classifier.")
            return 0
    print(f"Completed all {completed} requested round(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8083")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--codex-model", default=CODEX_MODEL)
    parser.add_argument("--claude-model", default=CLAUDE_MODEL)
    parser.add_argument("--rounds", type=int)
    parser.add_argument("--keep-going-after-pass", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(run_rounds(args))


if __name__ == "__main__":
    sys.exit(main())
