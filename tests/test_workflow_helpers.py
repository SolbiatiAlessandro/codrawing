from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from scripts.create_xp_request import create
from scripts.prepare_manifest import prepare
from scripts.render_replay import render
from scripts.verify_llm_logs import verify


class WorkflowHelpersTest(unittest.TestCase):
    def test_prepare_manifest_pins_current_repository_revision(self) -> None:
        source = Path("coworld_manifest_template.json")
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_bytes(source.read_bytes())
            prepare(manifest, "https://github.com/example/codrawing", "abc123")
            document = json.loads(manifest.read_text())
            self.assertEqual(
                document["game"]["runnable"]["source_url"],
                "https://github.com/example/codrawing/tree/abc123",
            )
            self.assertIn("/blob/abc123/", document["game"]["docs"]["readme"]["value"])

    def test_render_replay_writes_scaled_png(self) -> None:
        replay = {
            "frames": [
                {
                    "width": 2,
                    "height": 1,
                    "canvas": ["#FF0000", "#00FF00"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            replay_path = Path(directory) / "replay"
            output_path = Path(directory) / "image.png"
            replay_path.write_text(json.dumps(replay))
            render(replay_path, output_path, scale=3)
            png = output_path.read_bytes()
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", png[16:24])
            self.assertEqual((width, height), (6, 3))

    def test_xp_request_has_five_pinned_copies_of_the_llm_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "request.json"
            create("cow_00000000-0000-0000-0000-000000000000", "artist:v1", output, 50, "cat", "test-key")
            request = json.loads(output.read_text())
            self.assertEqual([seat["slot"] for seat in request["roster"]], [0, 1, 2, 3, 4])
            self.assertEqual({seat["player"]["policy_ref"] for seat in request["roster"]}, {"artist:v1"})
            self.assertEqual(request["game_config_overrides"]["max_turns"], 50)
            self.assertEqual(
                request["game_config_overrides"]["player_connect_timeout_seconds"],
                120,
            )
            self.assertEqual(request["game_config_overrides"]["action_timeout_seconds"], 60)

    def test_strict_log_check_requires_every_agent_and_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            for slot in range(5):
                lines = [json.dumps({"event": "llm_action", "slot": slot, "turn": turn}) for turn in range(3)]
                (logs / f"agent-{slot}.log").write_text("\n".join(lines))
            verify(logs, 3)
            (logs / "agent-2.log").write_text('{"event": "llm_action", "slot": 2, "turn": 0}')
            with self.assertRaises(ValueError):
                verify(logs, 3)


if __name__ == "__main__":
    unittest.main()
