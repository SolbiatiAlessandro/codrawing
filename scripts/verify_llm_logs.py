from __future__ import annotations

from pathlib import Path
import re
import sys


EVENT_PATTERN = re.compile(r'"event"\s*:\s*"llm_action".*?"turn"\s*:\s*(\d+)')


def verify(log_directory: Path, expected_turns: int) -> None:
    logs = sorted(log_directory.glob("agent-*.log"))
    if len(logs) != 5:
        raise ValueError(f"expected five agent logs, found {len(logs)}")
    expected = set(range(expected_turns))
    failures: list[str] = []
    for log in logs:
        text = log.read_text(errors="replace")
        turns = {int(value) for value in EVENT_PATTERN.findall(text)}
        if turns != expected:
            missing = sorted(expected - turns)
            failures.append(f"{log.name}: {len(turns)}/{expected_turns} LLM turns; missing={missing}")
        if "required model call failed" in text or "deterministic fallback" in text:
            failures.append(f"{log.name}: contains a model failure or fallback marker")
    if failures:
        raise ValueError("strict five-LLM verification failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_llm_logs.py LOG_DIRECTORY EXPECTED_TURNS")
    verify(Path(sys.argv[1]), int(sys.argv[2]))
