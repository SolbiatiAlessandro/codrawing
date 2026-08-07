from __future__ import annotations

import unittest

from codrawing.game.engine import PixelArtEngine, choose_target
from codrawing.game.image_model import MODEL_NAME, PASS_THRESHOLD, TARGET_INDICES
from codrawing.player.llm_player import (
    AgentMemory,
    SEAT_COLORS,
    SEAT_ROLES,
    SCORE_CAPTAIN_SLOT,
    enforce_seat_color,
    extract_action,
    extract_model_output,
    prompt_for,
)
from codrawing.player.pixel_templates import make_template


def action(x: int, y: int, color: str = "#123ABC", message: str = "") -> dict[str, object]:
    return {"message": message, "paint": {"x": x, "y": y, "color": color}}


class PixelArtEngineTest(unittest.TestCase):
    def make_engine(self, max_turns: int = 2) -> PixelArtEngine:
        return PixelArtEngine(
            width=8,
            height=8,
            max_turns=max_turns,
            target="cat",
            player_names=[f"Artist {index}" for index in range(5)],
        )

    def test_target_selection_is_seeded(self) -> None:
        targets = ["cat", "dog", "elephant"]
        self.assertEqual(choose_target(targets, 123), choose_target(targets, 123))
        with self.assertRaises(ValueError):
            choose_target(targets, None)

    def test_unique_pixels_apply_simultaneously(self) -> None:
        engine = self.make_engine()
        result = engine.resolve({0: action(1, 1), 1: action(2, 1, "#FFFFFF")})
        self.assertEqual(result["accepted_slots"], [0, 1])
        self.assertEqual(engine.canvas[9], "#123ABC")
        self.assertEqual(engine.owners[10], 1)

    def test_collisions_drop_every_conflicting_write(self) -> None:
        engine = self.make_engine()
        result = engine.resolve({0: action(1, 1), 2: action(1, 1, "#ABCDEF")})
        self.assertEqual(result["accepted_slots"], [])
        self.assertEqual(result["collision_slots"], [0, 2])
        self.assertEqual(engine.canvas[9], "#FFFFFF")

    def test_invalid_action_is_ignored(self) -> None:
        engine = self.make_engine()
        result = engine.resolve({0: action(99, 1), 1: action(1, 1, "red")})
        self.assertEqual(result["accepted_slots"], [])

    def test_public_message_is_recorded_with_sender(self) -> None:
        engine = self.make_engine()
        result = engine.resolve({3: action(1, 1, message="Painting the ear")})
        self.assertEqual(result["messages"][0]["player"], "Artist 3")
        self.assertEqual(result["messages"][0]["text"], "Painting the ear")

    def test_scores_stay_neutral_for_human_review(self) -> None:
        engine = self.make_engine(max_turns=1)
        engine.resolve({0: action(1, 1)})
        self.assertEqual(engine.results()["scores"], [0.0] * 5)
        self.assertTrue(engine.done)


class TemplateTest(unittest.TestCase):
    def test_each_target_has_a_nonempty_in_bounds_plan(self) -> None:
        for target in ("cat", "dog", "elephant"):
            plan = make_template(target, 24, 24)
            self.assertGreater(len(plan), 20)
            self.assertTrue(all(0 <= x < 24 and 0 <= y < 24 for x, y, _ in plan))
            self.assertEqual(len({(x, y) for x, y, _ in plan}), len(plan))

    def test_llm_action_parser_accepts_fenced_or_plain_json(self) -> None:
        plain = '{"message":"left ear","paint":{"x":2,"y":3,"color":"#112233"}}'
        self.assertEqual(extract_action(plain)["paint"]["x"], 2)
        self.assertEqual(extract_action(f"```json\n{plain}\n```")["message"], "left ear")

    def test_llm_tool_input_is_used_as_structured_output(self) -> None:
        payload = {
            "content": [
                {
                    "type": "tool_use",
                    "name": "paint_pixel",
                    "input": {"message": "outline", "paint": {"x": 1, "y": 2, "color": "#000000"}},
                }
            ]
        }
        decision = extract_action(extract_model_output(payload))
        self.assertEqual(decision["message"], "outline")
        self.assertEqual(decision["paint"]["y"], 2)

    def test_llm_prompt_assigns_a_distinct_color_to_each_seat(self) -> None:
        observation = {
            "width": 8,
            "height": 8,
            "canvas": ["#FFFFFF"] * 64,
            "recent_messages": [],
            "target": "cat",
            "turn": 0,
            "max_turns": 50,
        }
        self.assertEqual(len(set(SEAT_COLORS)), 5)
        self.assertEqual(len(set(SEAT_ROLES)), 5)
        for slot in range(5):
            self.assertIn(
                f"assigned paint color is {SEAT_COLORS[slot]}",
                prompt_for(observation, slot),
            )
            self.assertIn(f"specialization is {SEAT_ROLES[slot]}", prompt_for(observation, slot))

    def test_llm_prompt_includes_shared_image_model_feedback(self) -> None:
        observation = {
            "width": 8,
            "height": 8,
            "canvas": ["#FFFFFF"] * 64,
            "recent_messages": [],
            "target": "cat",
            "turn": 2,
            "max_turns": 50,
            "image_model_feedback": {
                "model": MODEL_NAME,
                "turn": 2,
                "target_score": 0.012345,
                "score_delta": 0.001,
                "pass_threshold": PASS_THRESHOLD,
                "passing": False,
                "target_rank": 17,
                "best_target_label": "tabby",
                "top_predictions": [
                    {"label": "comic book", "probability": 0.12},
                    {"label": "tabby", "probability": 0.01},
                ],
            },
        }
        prompt = prompt_for(observation, 0)
        self.assertIn("target score: 0.012345 (+0.001000 this turn)", prompt)
        self.assertIn("team passes only with a final target score strictly greater than 50%", prompt)
        self.assertIn("evaluation: NOT PASSING", prompt)
        self.assertIn("best target label: tabby (rank 17 of 1000)", prompt)
        self.assertIn("comic book 12.00%", prompt)

    def test_image_model_target_groups_use_expected_imagenet_classes(self) -> None:
        self.assertEqual(TARGET_INDICES["cat"], tuple(range(281, 286)))
        self.assertEqual(len(TARGET_INDICES["dog"]), 118)
        self.assertEqual(TARGET_INDICES["elephant"], (101, 385, 386))

    def test_score_captain_receives_persistent_experimental_memory(self) -> None:
        memory = AgentMemory(
            last_action={"x": 3, "y": 4, "color": SEAT_COLORS[SCORE_CAPTAIN_SLOT]}
        )
        observation = {
            "width": 8,
            "height": 8,
            "canvas": ["#FFFFFF"] * 64,
            "recent_messages": [],
            "target": "cat",
            "turn": 1,
            "max_turns": 50,
            "previous_accepted_slots": [SCORE_CAPTAIN_SLOT],
            "previous_collision_slots": [],
            "image_model_feedback": {
                "model": MODEL_NAME,
                "turn": 1,
                "target_score": 0.002,
                "score_delta": -0.001,
                "pass_threshold": PASS_THRESHOLD,
                "passing": False,
                "target_rank": 250,
                "best_target_label": "tabby",
                "top_predictions": [{"label": "whistle", "probability": 0.1}],
            },
        }
        memory.observe(observation, SCORE_CAPTAIN_SLOT)
        prompt = prompt_for(observation, SCORE_CAPTAIN_SLOT, memory)
        self.assertIn("sole SCORE CAPTAIN", prompt)
        self.assertIn("accepted; simultaneous team score delta -0.00100000", prompt)
        self.assertIn("erasing that exact pixel with #FFFFFF", prompt)

    def test_white_is_an_eraser_and_other_colors_are_seat_locked(self) -> None:
        erase = action(1, 2, "#ffffff")
        enforce_seat_color(erase, 2)
        self.assertEqual(erase["paint"]["color"], "#FFFFFF")

        paint = action(1, 2, "#000000")
        enforce_seat_color(paint, 2)
        self.assertEqual(paint["paint"]["color"], SEAT_COLORS[2])


if __name__ == "__main__":
    unittest.main()
