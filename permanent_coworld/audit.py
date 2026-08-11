from __future__ import annotations

import json
import re
import shlex
from typing import Any


ALLOWED_COMMAND = re.compile(
    r"^python3 -m permanent_coworld\.tool (?:"
    r"board|score|messages|paint [0-9]+ [0-9]+|erase [0-9]+ [0-9]+|"
    r"say (?:'[^'\n]*'|\"[^\"\n]*\")"
    r")$"
)


def commands_from_trace(provider: str, output: str) -> list[str]:
    commands: list[str] = []
    for line in output.splitlines():
        try:
            event: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if provider == "codex":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "command_execution":
                command = item.get("command")
                if isinstance(command, str):
                    commands.append(command.strip())
        elif provider == "claude":
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            for block in message.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") != "Bash":
                    continue
                tool_input = block.get("input")
                if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
                    commands.append(tool_input["command"].strip())
    return commands


def audit_output(provider: str, output: str) -> list[str]:
    violations = []
    commands = commands_from_trace(provider, output)
    for command in commands:
        normalized = command
        try:
            shell_parts = shlex.split(command)
        except ValueError:
            shell_parts = []
        if len(shell_parts) == 3 and shell_parts[0] in {"/bin/zsh", "/bin/bash", "/bin/sh"} and shell_parts[1] == "-lc":
            normalized = shell_parts[2].strip()
        if ALLOWED_COMMAND.fullmatch(normalized) is None:
            violations.append(command)
    for line in output.splitlines():
        try:
            event: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if provider == "codex":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") in {
                "file_change", "mcp_tool_call", "web_search", "image_generation",
            }:
                violations.append(f"disallowed Codex tool: {item['type']}")
        elif provider == "claude":
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            for block in message.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") == "Bash":
                    continue
                tool_input = block.get("input")
                file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
                allowed_snapshot = (
                    block.get("name") == "Read"
                    and re.search(r"/permanent_coworld/state/snapshots/round-[0-9]{6}-start\.png$", str(file_path))
                )
                if not allowed_snapshot:
                    violations.append(f"disallowed Claude tool: {block.get('name', 'unknown')}")
    return list(dict.fromkeys(violations))
