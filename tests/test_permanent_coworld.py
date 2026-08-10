from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from permanent_coworld.db import CoworldDatabase
from permanent_coworld.scorer import QuickDrawPrototypeScorer
from permanent_coworld.audit import audit_output
from permanent_coworld.render import png_snapshot, textual_snapshot
from permanent_coworld import runner


class PermanentCoworldTest(unittest.TestCase):
    def test_visual_and_text_snapshots_are_dependency_free(self) -> None:
        pixels = [{"x": 64, "y": 64, "color": "#EF4444"}]
        image = png_snapshot(pixels, width=128, height=128)
        text = textual_snapshot(pixels, width=128, height=128)
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(len(text["rows"]), 32)
        self.assertIn("R", "".join(text["rows"]))

    def test_trace_audit_accepts_only_board_api_commands(self) -> None:
        allowed = json.dumps({
            "type": "item.started",
            "item": {"type": "command_execution", "command": "python3 -m permanent_coworld.tool paint 10 20"},
        })
        forbidden = json.dumps({
            "type": "item.started",
            "item": {"type": "command_execution", "command": "python3 -m permanent_coworld.tool board && ls"},
        })
        self.assertEqual(audit_output("codex", allowed), [])
        self.assertEqual(audit_output("codex", forbidden), ["python3 -m permanent_coworld.tool board && ls"])

    def test_trace_audit_unwraps_codex_shell_without_allowing_chains(self) -> None:
        allowed = json.dumps({
            "type": "item.started",
            "item": {
                "type": "command_execution",
                "command": "/bin/zsh -lc 'python3 -m permanent_coworld.tool paint 10 20'",
            },
        })
        forbidden_command = "/bin/zsh -lc 'python3 -m permanent_coworld.tool board && ls'"
        forbidden = json.dumps({
            "type": "item.started",
            "item": {"type": "command_execution", "command": forbidden_command},
        })
        self.assertEqual(audit_output("codex", allowed), [])
        self.assertEqual(audit_output("codex", forbidden), [forbidden_command])

    def test_blank_board_is_not_a_light_bulb(self) -> None:
        result = QuickDrawPrototypeScorer().score([], width=128, height=128)
        self.assertLess(result["target_score"], 0.01)
        self.assertFalse(result["passing"])

    def test_learned_light_bulb_shape_can_pass(self) -> None:
        scorer = QuickDrawPrototypeScorer()
        model_path = Path(__file__).parents[1] / "permanent_coworld" / "models" / "quickdraw_prototypes.json"
        prototype = json.loads(model_path.read_text())["prototypes"]["light bulb"]
        pixels = [
            (x + 50, y + 50)
            for y in range(28)
            for x in range(28)
            if prototype[y * 28 + x] >= 110
        ]
        result = scorer.score(pixels, width=128, height=128)
        self.assertTrue(result["passing"])
        self.assertEqual(result["target_rank"], 1)

    def test_board_persists_and_budget_counts_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.sqlite3"
            database = CoworldDatabase(path)
            round_id, wakes = database.begin_round()
            wake = wakes[0]

            status, result = database.put_pixel(wake["token"], x=-1, y=0, action="paint")
            self.assertEqual(status, 422)
            self.assertEqual(result["pixel_calls_remaining"], 9)
            for x in range(9):
                status, _ = database.put_pixel(wake["token"], x=40 + x, y=40, action="paint")
                self.assertEqual(status, 200)
            status, _ = database.put_pixel(wake["token"], x=60, y=40, action="paint")
            self.assertEqual(status, 429)

            status, _ = database.post_message(wake["token"], "The upper contour is reserved.")
            self.assertEqual(status, 200)
            database.finish_round(round_id)

            reopened = CoworldDatabase(path)
            state = reopened.state()
            self.assertEqual(len(state["pixels"]), 9)
            self.assertEqual(state["messages"][0]["message"], "The upper contour is reserved.")
            self.assertEqual(len(reopened.history()), 10)
            self.assertEqual(state["agents"][0]["model"], "gpt-5.6-luna")
            self.assertEqual(state["agents"][1]["model"], "claude-sonnet-5")

    def test_event_history_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = CoworldDatabase(Path(directory) / "world.sqlite3")
            _, wakes = database.begin_round()
            database.put_pixel(wakes[0]["token"], x=10, y=10, action="paint")
            with database.connect() as connection:
                with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                    connection.execute("DELETE FROM events")

    def test_history_reconstructs_the_board_across_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = CoworldDatabase(Path(directory) / "world.sqlite3")
            first_round, first_wakes = database.begin_round()
            database.put_pixel(first_wakes[0]["token"], x=10, y=10, action="paint")
            database.finish_round(first_round)

            second_round, second_wakes = database.begin_round()
            database.put_pixel(second_wakes[1]["token"], x=10, y=10, action="paint")
            database.put_pixel(second_wakes[2]["token"], x=20, y=20, action="paint")
            database.put_pixel(second_wakes[3]["token"], x=20, y=20, action="erase")
            database.finish_round(second_round)

            events = database.history(limit=5000)
            self.assertEqual([event["round_id"] for event in events], [first_round, second_round, second_round, second_round])
            replayed: dict[tuple[int, int], str] = {}
            for event in events:
                coordinate = (event["x"], event["y"])
                if event["after_color"] == "#FFFFFF":
                    replayed.pop(coordinate, None)
                else:
                    replayed[coordinate] = event["after_color"]
            current = {(pixel["x"], pixel["y"]): pixel["color"] for pixel in database.state()["pixels"]}
            self.assertEqual(replayed, current)


class MultiRoundRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_unbounded_run_waits_for_rounds_and_stops_on_pass(self) -> None:
        args = SimpleNamespace(
            url="http://127.0.0.1:8083",
            database=Path("unused.sqlite3"),
            rounds=None,
            keep_going_after_pass=False,
        )
        summaries = [
            (True, {"score": {"passing": False}}),
            (True, {"score": {"passing": False}}),
            (True, {"score": {"passing": True}}),
        ]
        run_one = AsyncMock(side_effect=summaries)
        database = SimpleNamespace(state=lambda: {"score": {"passing": False}})
        with (
            patch("permanent_coworld.runner.server_ready", return_value=True),
            patch("permanent_coworld.runner.CoworldDatabase", return_value=database),
            patch("permanent_coworld.runner.run_one_round", run_one),
        ):
            result = await runner.run_rounds(args)

        self.assertEqual(result, 0)
        self.assertEqual(run_one.await_count, 3)
