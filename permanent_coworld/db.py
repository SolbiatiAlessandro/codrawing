from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Iterator

from permanent_coworld.config import (
    AGENTS,
    BOARD_HEIGHT,
    BOARD_WIDTH,
    DEFAULT_DATABASE,
    PASS_THRESHOLD,
    PIXEL_BUDGET,
    TARGET,
)
from permanent_coworld.scorer import QuickDrawPrototypeScorer
from permanent_coworld.render import png_snapshot, textual_snapshot


SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CoworldDatabase:
    def __init__(
        self,
        path: Path = DEFAULT_DATABASE,
        scorer: QuickDrawPrototypeScorer | None = None,
    ) -> None:
        self.path = path
        self.scorer = scorer or QuickDrawPrototypeScorer()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    color TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS wakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id INTEGER NOT NULL REFERENCES rounds(id),
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    token_hash TEXT NOT NULL UNIQUE,
                    pixel_budget INTEGER NOT NULL,
                    pixel_calls INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    UNIQUE(round_id, agent_id)
                );
                CREATE TABLE IF NOT EXISTS pixels (
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    color TEXT NOT NULL,
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    updated_event_id INTEGER NOT NULL,
                    PRIMARY KEY (x, y)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    round_id INTEGER NOT NULL REFERENCES rounds(id),
                    wake_id INTEGER NOT NULL REFERENCES wakes(id),
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    kind TEXT NOT NULL CHECK(kind IN ('pixel', 'message')),
                    x INTEGER,
                    y INTEGER,
                    before_color TEXT,
                    after_color TEXT,
                    message TEXT,
                    score_before REAL,
                    score_after REAL
                );
                CREATE TABLE IF NOT EXISTS api_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    wake_id INTEGER,
                    agent_id INTEGER,
                    method TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    request_json TEXT,
                    response_json TEXT NOT NULL,
                    accepted INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id INTEGER NOT NULL REFERENCES rounds(id),
                    wake_id INTEGER NOT NULL REFERENCES wakes(id),
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    provider TEXT NOT NULL,
                    requested_model TEXT NOT NULL,
                    actual_model TEXT,
                    session_id TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    return_code INTEGER NOT NULL,
                    valid INTEGER NOT NULL,
                    violations_json TEXT NOT NULL,
                    trace_path TEXT NOT NULL,
                    trace_sha256 TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS events_are_append_only_update
                BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_are_append_only_delete
                BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS api_calls_are_append_only_update
                BEFORE UPDATE ON api_calls BEGIN SELECT RAISE(ABORT, 'api calls are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS api_calls_are_append_only_delete
                BEFORE DELETE ON api_calls BEGIN SELECT RAISE(ABORT, 'api calls are append-only'); END;
                """
            )
            agent_columns = {row["name"] for row in connection.execute("PRAGMA table_info(agents)")}
            if "model" not in agent_columns:
                connection.execute("ALTER TABLE agents ADD COLUMN model TEXT NOT NULL DEFAULT ''")
            run_columns = {row["name"] for row in connection.execute("PRAGMA table_info(agent_runs)")}
            if "requested_model" not in run_columns:
                connection.execute("ALTER TABLE agent_runs ADD COLUMN requested_model TEXT NOT NULL DEFAULT ''")
            if "actual_model" not in run_columns:
                connection.execute("ALTER TABLE agent_runs ADD COLUMN actual_model TEXT")
            metadata = {
                "schema_version": str(SCHEMA_VERSION),
                "width": str(BOARD_WIDTH),
                "height": str(BOARD_HEIGHT),
                "target": TARGET,
                "pass_threshold": str(PASS_THRESHOLD),
                "created_at": utc_now(),
            }
            for key, value in metadata.items():
                if key == "created_at":
                    connection.execute(
                        "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
                        (key, value),
                    )
                else:
                    connection.execute(
                        """INSERT INTO metadata(key, value) VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                        (key, value),
                    )
            for agent_id, agent in enumerate(AGENTS, 1):
                connection.execute(
                    """INSERT INTO agents(id, slug, name, color, provider, model)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        slug = excluded.slug,
                        name = excluded.name,
                        color = excluded.color,
                        provider = excluded.provider,
                        model = excluded.model""",
                    (agent_id, agent.slug, agent.name, agent.color, agent.provider, agent.model),
                )
            connection.commit()

    def _occupied(self, connection: sqlite3.Connection) -> list[tuple[int, int]]:
        return [(row["x"], row["y"]) for row in connection.execute("SELECT x, y FROM pixels")]

    def _score(self, connection: sqlite3.Connection) -> dict[str, object]:
        return self.scorer.score(self._occupied(connection), width=BOARD_WIDTH, height=BOARD_HEIGHT)

    def begin_round(self) -> tuple[int, list[dict[str, Any]]]:
        self.initialize()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("INSERT INTO rounds(created_at) VALUES (?)", (utc_now(),))
            round_id = int(cursor.lastrowid)
            wakes = []
            for agent_id, agent in enumerate(AGENTS, 1):
                token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(token.encode()).hexdigest()
                cursor = connection.execute(
                    """INSERT INTO wakes(round_id, agent_id, token_hash, pixel_budget, started_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (round_id, agent_id, token_hash, PIXEL_BUDGET, utc_now()),
                )
                wakes.append(
                    {
                        "wake_id": int(cursor.lastrowid),
                        "round_id": round_id,
                        "agent_id": agent_id,
                        "agent": agent,
                        "token": token,
                    }
                )
            connection.commit()
        return round_id, wakes

    def finish_round(self, round_id: int) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE wakes SET completed_at = ?, status = 'complete' WHERE round_id = ? AND status = 'active'",
                (utc_now(), round_id),
            )
            connection.execute("UPDATE rounds SET completed_at = ? WHERE id = ?", (utc_now(), round_id))
            connection.commit()

    def finish_wake(self, wake_id: int, *, status: str = "complete") -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE wakes SET completed_at = ?, status = ?
                WHERE id = ? AND status = 'active'""",
                (utc_now(), status, wake_id),
            )
            connection.commit()

    def round_runs(self, round_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT agent_runs.*, agents.name AS agent_name, agents.slug AS agent_slug
                FROM agent_runs JOIN agents ON agents.id = agent_runs.agent_id
                WHERE agent_runs.round_id = ? ORDER BY agent_runs.agent_id""",
                (round_id,),
            )]

    def authenticate(self, connection: sqlite3.Connection, token: str) -> sqlite3.Row | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return connection.execute(
            """SELECT wakes.*, agents.slug, agents.name, agents.color, agents.provider
            FROM wakes JOIN agents ON agents.id = wakes.agent_id
            WHERE wakes.token_hash = ?""",
            (token_hash,),
        ).fetchone()

    def log_api_call(
        self,
        connection: sqlite3.Connection,
        *,
        wake: sqlite3.Row | None,
        method: str,
        endpoint: str,
        request: object | None,
        response: object,
        accepted: bool,
    ) -> None:
        connection.execute(
            """INSERT INTO api_calls(
                created_at, wake_id, agent_id, method, endpoint,
                request_json, response_json, accepted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                utc_now(),
                wake["id"] if wake else None,
                wake["agent_id"] if wake else None,
                method,
                endpoint,
                json.dumps(request, separators=(",", ":")) if request is not None else None,
                json.dumps(response, separators=(",", ":")),
                int(accepted),
            ),
        )

    def state(self) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            pixels = [dict(row) for row in connection.execute(
                "SELECT x, y, color, agent_id, updated_event_id FROM pixels ORDER BY y, x"
            )]
            agents = [dict(row) for row in connection.execute(
                """SELECT agents.id, agents.slug, agents.name, agents.color,
                agents.provider, agents.model, wakes.round_id AS latest_round,
                wakes.status AS wake_status, wakes.pixel_calls, wakes.pixel_budget
                FROM agents
                LEFT JOIN wakes ON wakes.id = (
                    SELECT MAX(candidate.id) FROM wakes AS candidate
                    WHERE candidate.agent_id = agents.id
                )
                ORDER BY agents.id"""
            )]
            messages = [dict(row) for row in connection.execute(
                """SELECT events.id, events.created_at, events.round_id, agents.name AS agent,
                agents.color, events.message FROM events JOIN agents ON agents.id = events.agent_id
                WHERE events.kind = 'message' ORDER BY events.id DESC LIMIT 100"""
            )]
            last_event = connection.execute("SELECT COALESCE(MAX(id), 0) AS id FROM events").fetchone()["id"]
            rounds = connection.execute("SELECT COUNT(*) AS count FROM rounds").fetchone()["count"]
            return {
                "width": BOARD_WIDTH,
                "height": BOARD_HEIGHT,
                "target": TARGET,
                "pixels": pixels,
                "text_snapshot": textual_snapshot(pixels, width=BOARD_WIDTH, height=BOARD_HEIGHT),
                "agents": agents,
                "messages": list(reversed(messages)),
                "score": self._score(connection),
                "event_id": last_event,
                "rounds": rounds,
            }

    def history(self, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT events.*, agents.slug AS agent_slug, agents.name AS agent_name
                FROM events JOIN agents ON agents.id = events.agent_id
                WHERE events.id > ? ORDER BY events.id LIMIT ?""",
                (after, min(max(limit, 1), 5000)),
            )]

    def agent_state(self, token: str, *, endpoint: str = "/api/board") -> tuple[int, dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            wake = self.authenticate(connection, token)
            if wake is None:
                response = {"error": "invalid wake token"}
                self.log_api_call(
                    connection, wake=None, method="GET", endpoint=endpoint,
                    request=None, response=response, accepted=False,
                )
                connection.commit()
                return 401, response
            response = self.state_for_connection(connection)
            response["you"] = {
                "agent_id": wake["agent_id"],
                "slug": wake["slug"],
                "name": wake["name"],
                "color": wake["color"],
                "round_id": wake["round_id"],
                "wake_id": wake["id"],
                "pixel_budget": wake["pixel_budget"],
                "pixel_calls": wake["pixel_calls"],
                "pixel_calls_remaining": max(0, wake["pixel_budget"] - wake["pixel_calls"]),
                "status": wake["status"],
            }
            audit_summary = {
                "event_id": response["event_id"],
                "pixel_count": len(response["pixels"]),
                "message_count": len(response["messages"]),
                "target_score": response["score"]["target_score"],
                "pixel_calls_remaining": response["you"]["pixel_calls_remaining"],
            }
            self.log_api_call(
                connection, wake=wake, method="GET", endpoint=endpoint,
                request=None, response=audit_summary, accepted=True,
            )
            connection.commit()
            return 200, response

    def state_for_connection(self, connection: sqlite3.Connection) -> dict[str, Any]:
        pixels = [dict(row) for row in connection.execute(
            "SELECT x, y, color, agent_id, updated_event_id FROM pixels ORDER BY y, x"
        )]
        messages = [dict(row) for row in connection.execute(
            """SELECT events.id, events.created_at, events.round_id, agents.slug AS agent_slug,
            agents.name AS agent, agents.color, events.message
            FROM events JOIN agents ON agents.id = events.agent_id
            WHERE events.kind = 'message' ORDER BY events.id DESC LIMIT 100"""
        )]
        return {
            "width": BOARD_WIDTH,
            "height": BOARD_HEIGHT,
            "target": TARGET,
            "pixels": pixels,
            "text_snapshot": textual_snapshot(pixels, width=BOARD_WIDTH, height=BOARD_HEIGHT),
            "messages": list(reversed(messages)),
            "score": self._score(connection),
            "event_id": connection.execute("SELECT COALESCE(MAX(id), 0) AS id FROM events").fetchone()["id"],
        }

    def agent_snapshot(self, token: str) -> tuple[int, bytes | dict[str, str]]:
        self.initialize()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            wake = self.authenticate(connection, token)
            if wake is None:
                response = {"error": "invalid wake token"}
                self.log_api_call(
                    connection, wake=None, method="GET", endpoint="/api/snapshot.png",
                    request=None, response=response, accepted=False,
                )
                connection.commit()
                return 401, response
            pixels = [dict(row) for row in connection.execute(
                "SELECT x, y, color FROM pixels ORDER BY y, x"
            )]
            image = png_snapshot(pixels, width=BOARD_WIDTH, height=BOARD_HEIGHT)
            response = {
                "content_type": "image/png",
                "bytes": len(image),
                "sha256": hashlib.sha256(image).hexdigest(),
                "event_id": connection.execute("SELECT COALESCE(MAX(id), 0) AS id FROM events").fetchone()["id"],
            }
            self.log_api_call(
                connection, wake=wake, method="GET", endpoint="/api/snapshot.png",
                request=None, response=response, accepted=True,
            )
            connection.commit()
            return 200, image

    def post_message(self, token: str, message: str) -> tuple[int, dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            wake = self.authenticate(connection, token)
            if wake is None:
                response = {"error": "invalid wake token"}
                self.log_api_call(
                    connection, wake=None, method="POST", endpoint="/api/messages",
                    request={"message": message}, response=response, accepted=False,
                )
                connection.commit()
                return 401, response
            if wake["status"] != "active":
                response = {"error": "wake is no longer active"}
                self.log_api_call(
                    connection, wake=wake, method="POST", endpoint="/api/messages",
                    request={"message": message}, response=response, accepted=False,
                )
                connection.commit()
                return 409, response
            message = message.strip()
            if not message or len(message) > 2000:
                response = {"error": "message must contain 1 to 2000 characters"}
                self.log_api_call(
                    connection, wake=wake, method="POST", endpoint="/api/messages",
                    request={"message": message}, response=response, accepted=False,
                )
                connection.commit()
                return 422, response
            score = float(self._score(connection)["target_score"])
            cursor = connection.execute(
                """INSERT INTO events(
                    created_at, round_id, wake_id, agent_id, kind, message,
                    score_before, score_after
                ) VALUES (?, ?, ?, ?, 'message', ?, ?, ?)""",
                (utc_now(), wake["round_id"], wake["id"], wake["agent_id"], message, score, score),
            )
            response = {"accepted": True, "event_id": int(cursor.lastrowid), "message": message}
            self.log_api_call(
                connection, wake=wake, method="POST", endpoint="/api/messages",
                request={"message": message}, response=response, accepted=True,
            )
            connection.commit()
            return 200, response

    def put_pixel(self, token: str, *, x: int, y: int, action: str) -> tuple[int, dict[str, Any]]:
        self.initialize()
        request = {"x": x, "y": y, "action": action}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            wake = self.authenticate(connection, token)
            if wake is None:
                response = {"error": "invalid wake token"}
                self.log_api_call(
                    connection, wake=None, method="POST", endpoint="/api/pixel",
                    request=request, response=response, accepted=False,
                )
                connection.commit()
                return 401, response
            if wake["status"] != "active":
                response = {"error": "wake is no longer active"}
                self.log_api_call(
                    connection, wake=wake, method="POST", endpoint="/api/pixel",
                    request=request, response=response, accepted=False,
                )
                connection.commit()
                return 409, response
            if wake["pixel_calls"] >= wake["pixel_budget"]:
                response = {"error": "pixel budget exhausted", "pixel_calls_remaining": 0}
                self.log_api_call(
                    connection, wake=wake, method="POST", endpoint="/api/pixel",
                    request=request, response=response, accepted=False,
                )
                connection.commit()
                return 429, response

            # Every authenticated mutation attempt consumes budget, including an
            # invalid coordinate. This prevents free probing around the cap.
            connection.execute("UPDATE wakes SET pixel_calls = pixel_calls + 1 WHERE id = ?", (wake["id"],))
            remaining = wake["pixel_budget"] - wake["pixel_calls"] - 1
            if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
                response = {"error": "x and y must be integers", "pixel_calls_remaining": remaining}
                self.log_api_call(
                    connection, wake=wake, method="POST", endpoint="/api/pixel",
                    request=request, response=response, accepted=False,
                )
                connection.commit()
                return 422, response
            if not (0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT) or action not in {"paint", "erase"}:
                response = {"error": "invalid coordinate or action", "pixel_calls_remaining": remaining}
                self.log_api_call(
                    connection, wake=wake, method="POST", endpoint="/api/pixel",
                    request=request, response=response, accepted=False,
                )
                connection.commit()
                return 422, response

            prior = connection.execute("SELECT color FROM pixels WHERE x = ? AND y = ?", (x, y)).fetchone()
            before_color = prior["color"] if prior else "#FFFFFF"
            after_color = wake["color"] if action == "paint" else "#FFFFFF"
            occupied_before = set(self._occupied(connection))
            occupied_after = occupied_before.copy()
            if action == "paint":
                occupied_after.add((x, y))
            else:
                occupied_after.discard((x, y))
            before_feedback = self.scorer.score(occupied_before, width=BOARD_WIDTH, height=BOARD_HEIGHT)
            after_feedback = self.scorer.score(occupied_after, width=BOARD_WIDTH, height=BOARD_HEIGHT)
            score_before = float(before_feedback["target_score"])
            score_after = float(after_feedback["target_score"])
            cursor = connection.execute(
                """INSERT INTO events(
                    created_at, round_id, wake_id, agent_id, kind, x, y,
                    before_color, after_color, score_before, score_after
                ) VALUES (?, ?, ?, ?, 'pixel', ?, ?, ?, ?, ?, ?)""",
                (
                    utc_now(), wake["round_id"], wake["id"], wake["agent_id"], x, y,
                    before_color, after_color, score_before, score_after,
                ),
            )
            event_id = int(cursor.lastrowid)
            if action == "paint":
                connection.execute(
                    """INSERT INTO pixels(x, y, color, agent_id, updated_event_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(x, y) DO UPDATE SET
                        color = excluded.color,
                        agent_id = excluded.agent_id,
                        updated_event_id = excluded.updated_event_id""",
                    (x, y, after_color, wake["agent_id"], event_id),
                )
            else:
                connection.execute("DELETE FROM pixels WHERE x = ? AND y = ?", (x, y))
            response = {
                "accepted": True,
                "event_id": event_id,
                "x": x,
                "y": y,
                "before_color": before_color,
                "after_color": after_color,
                "score_before": score_before,
                "score_after": score_after,
                "score_delta": score_after - score_before,
                "passing": after_feedback["passing"],
                "target_rank": after_feedback["target_rank"],
                "top_predictions": after_feedback["top_predictions"],
                "pixel_calls_remaining": remaining,
            }
            self.log_api_call(
                connection, wake=wake, method="POST", endpoint="/api/pixel",
                request=request, response=response, accepted=True,
            )
            connection.commit()
            return 200, response

    def record_run(self, **values: object) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_runs(
                    round_id, wake_id, agent_id, provider, requested_model, actual_model, session_id, started_at,
                    completed_at, return_code, valid, violations_json, trace_path, trace_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["round_id"], values["wake_id"], values["agent_id"],
                    values["provider"], values["requested_model"], values.get("actual_model"),
                    values.get("session_id"), values["started_at"],
                    values["completed_at"], values["return_code"], int(bool(values["valid"])),
                    json.dumps(values["violations"], separators=(",", ":")),
                    values["trace_path"], values["trace_sha256"],
                ),
            )
            connection.commit()
