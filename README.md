# Codrawing

Codrawing is a minimal five-agent Coworld for collaborative pixel art. Every turn, each player sends one public message and chooses one pixel and color. All actions resolve at once. The shared target is randomly selected from `cat`, `dog`, and `elephant`; a human judges the finished image in the replay viewer.

This first version deliberately has no image grader. Its Coworld `scores` are all zero, so they do not pretend that activity equals image quality. The replay and PNG are the result.

## Rules

- Five fixed seats share a 24×24 canvas and a target.
- Each seat submits at most one public message (240 characters) and one `#RRGGBB` pixel per turn.
- If two or more seats select the same pixel in one turn, all writes to that pixel are dropped.
- The default episode lasts 50 turns, for at most 250 accepted pixel writes.
- Missing, late, or invalid actions become skipped turns; they never hang the game.

The bundled `Template Team Player` is a deterministic smoke-test policy, not an LLM. Five copies divide a small target template among themselves, proving that simultaneous actions, artifacts, and replay rendering work. In a hosted episode, LLM policy images can replace those five bundled players without changing the game.

The same image also contains `python -m codrawing.player.llm_player`. It calls Anthropic models through Coworld's hosted Bedrock sidecar and makes one bounded call per turn. Normal development runs fall back to the deterministic template on errors or throttling. Set `REQUIRE_LLM=true` for evidence runs: the player exits instead of falling back, and emits one structured `llm_action` log record for every successful model turn. Upload it as a policy with `--run python --run -m --run codrawing.player.llm_player --use-bedrock --bedrock-model <model-id>`. For a local direct Anthropic run, inject `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` as secret environment variables. The game never receives those secrets.

## Coworld workflow

Prerequisites: Python 3.12+, `uv`, and a running Docker engine. Coworld builds `linux/amd64` images, so Apple Silicon also needs the current [Coworld macOS setup](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/MACOS.md).

```bash
uv run --with 'coworld[auth]' coworld build --project . --version 0.1.0
uv run --with 'coworld[auth]' coworld run-episode dist/coworld_manifest.json
uv run --with 'coworld[auth]' coworld replay dist/coworld_manifest.json path/to/replay
uv run --with 'coworld[auth]' coworld certify dist/coworld_manifest.json
```

For manual play, run `coworld play dist/coworld_manifest.json`, open all five player links, and use the global viewer to watch the image. The replay viewer includes a **Download PNG** button.

Before a hosted upload, publish this folder at `https://github.com/SolbiatiAlessandro/codrawing` or change the three `source_url`/documentation URLs in `coworld_manifest_template.json` to the real public repository. The current URL is the intended destination but does not exist yet.

## GitHub Actions

The `Coworld CI` workflow runs on every push, pull request, and manual dispatch using an `ubuntu-24.04` x86 runner. It runs unit tests, builds the Docker image and hydrated manifest, completes a 50-turn episode with five separate baseline-player containers, verifies replay mode, renders the final canvas to PNG, and runs `coworld certify`.

Each ordinary CI run uploads a 14-day artifact containing the hydrated manifest and certification transcript. It deliberately does not upload the Coworld to Softmax and requires no secrets.

The separate manual `Hosted five-LLM episode` workflow builds and uploads the Coworld, uploads the LLM player with hosted Bedrock access, and requests one episode with five independent player containers. It requires a `SOFTMAX_TOKEN` repository secret. Deterministic fallback is disabled for this run, and the workflow checks all five player logs for one successful model response per requested turn before rendering `final-image.png`.

## Local tests without Docker

```bash
python3 -m unittest discover -s tests -v
```

These tests cover deterministic target selection, action validation, simultaneous collisions, message logging, and the five-player template plan. Full Coworld certification still requires Docker.
