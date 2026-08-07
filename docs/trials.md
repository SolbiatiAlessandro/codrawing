# Hosted five-LLM trials

These episodes used five separate hosted player processes running
`us.anthropic.claude-haiku-4-5-20251001-v1:0`. Each process made one structured
model call per turn. Deterministic fallback was disabled, and GitHub Actions
verified all 250 `llm_action` records before accepting each trial.

| Figure | Accepted pixels by seat | GitHub Actions evidence | Replay data |
| --- | --- | --- | --- |
| Cat | 36, 46, 45, 38, 44 | [run 31155379655](https://github.com/SolbiatiAlessandro/codrawing/actions/runs/31155379655) | [replay](https://softmax-public.s3.amazonaws.com/replays/c4fb284f-f343-4dba-8254-f4a6adf4789d.replay) |
| Dog | 47, 49, 38, 41, 45 | [run 31156500535](https://github.com/SolbiatiAlessandro/codrawing/actions/runs/31156500535) | [replay](https://softmax-public.s3.amazonaws.com/replays/43623a8e-c726-4ff6-b868-07033da1ca08.replay) |
| Elephant | 50, 48, 50, 50, 48 | [run 31157541548](https://github.com/SolbiatiAlessandro/codrawing/actions/runs/31157541548) | [replay](https://softmax-public.s3.amazonaws.com/replays/bf6c7c5d-8911-4697-b411-37c6a05f30dc.replay) |

The downloadable artifact on each Actions run contains `final-image.png` at
480×480, the replay, five agent logs, and request metadata. The five seat colors
are red, blue, green, amber, and purple. Pixel-art quality is intentionally
human-reviewed; accepted-pixel counts are diagnostics, not grades.
