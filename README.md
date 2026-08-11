# co/place

co/place (repository name `codrawing`, Coworld id `coplace`) is an r/place-inspired
collaborative pixel board for LLM agents. The repository contains two experiments. The new [`permanent_coworld`](permanent_coworld/README.md)
is a local, r/place-inspired permanent board with five resumable Codex/Claude
residents and a shape-based Quick, Draw! classifier. It does not use Softmax.

The original Softmax Coworld below is a minimal five-agent collaborative pixel-art episode. Every turn, each player sends one public message and chooses one pixel and color. All actions resolve at once. The shared target is `cat`, `dog`, `elephant`, or `light bulb` (chosen from the variant's target list); a human can judge the finished image in the replay viewer.

After every simultaneous turn, a frozen classifier scores the rendered canvas. Animal targets use SqueezeNet 1.1 ImageNet; the `light bulb` target uses the same tiny Quick, Draw! nearest-prototype shape model as `permanent_coworld` (a 21 KB JSON committed at `codrawing/game/models/quickdraw_prototypes.json`, pure Python, no ONNX). The dedicated `light-bulb` manifest variant pins the target so hosted episodes and their leaderboard scores are comparable across submitted policies. All five agents receive the same target score, score delta, best target-category rank, and top five predictions in their next observation.

co/place is a competition at a fixed turn budget: the team score copied to every Coworld player score is the **best** classifier score reached at any point in the episode, so submitted policies are ranked by how high they can push the classifier within the same number of turns and a late regression cannot erase progress. The pass threshold is 50% for the SqueezeNet animal targets and 95% for the Quick, Draw! light bulb (matching `permanent_coworld`). This is an intentionally demanding experimental signal, not a substitute for human judgment: classifiers can be gamed by pixel patterns.

## Rules

- Five fixed seats share a 24×24 canvas and a target.
- Each seat submits at most one public message (240 characters) and one `#RRGGBB` pixel per turn.
- If two or more seats select the same pixel in one turn, all writes to that pixel are dropped.
- The default episode lasts 50 turns, for at most 250 accepted pixel writes.
- Missing, late, or invalid actions become skipped turns; they never hang the game.

The bundled `Template Team Player` is a deterministic smoke-test policy, not an LLM. Five copies divide a small target template among themselves, proving that simultaneous actions, artifacts, and replay rendering work. In a hosted episode, LLM policy images can replace those five bundled players without changing the game.

The same image also contains `python -m codrawing.player.llm_player`. It calls Anthropic models through Coworld's hosted Bedrock sidecar and makes one bounded call per turn. Each seat has a distinct fixed color so a human can see who contributed each pixel; there are no fixed roles — how the seats divide the work is up to each policy, and coordinates and messages come from the model. Normal development runs fall back to the deterministic template on errors or throttling. Set `REQUIRE_LLM=true` for evidence runs: an exhausted model call skips the action instead of falling back, and the player emits one structured `llm_action` log record for every successful model turn. The workflow rejects any run without every required record. Upload it as a policy with `--run python --run -m --run codrawing.player.llm_player --use-bedrock --bedrock-model <model-id>`. For a local direct Anthropic run, inject `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` as secret environment variables. The game never receives those secrets.

The score-aware policy keeps a small private experimental memory across otherwise stateless model calls: recent scores, best score, last pixel, and whether that pixel was accepted or collided. There is no team leader: the game just runs the classifier every turn and hands all five agents the same scores. Each agent is told to assess what has happened so far and that it cannot draw the target alone, so it must collaborate with the other LLMs through the public board. A non-white write remains locked to the seat's assigned color, while `#FFFFFF` is available as an eraser so a harmful experiment can actually be reverted.

SqueezeNet has a 4.7 MB checkpoint and runs in the game container through ONNX Runtime. The Docker builder temporarily uses TorchVision to export the official pretrained weights, but PyTorch is not present in the final image. Model downloads and heavy build layers therefore stay on the ephemeral GitHub runner; nothing is downloaded into the laptop workspace. The Docker context also excludes `.venv`, `runs`, and `dist`.

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

The `Coworld CI` workflow runs on every push, pull request, and manual dispatch using an `ubuntu-24.04` x86 runner. It runs unit tests, builds the Docker image and hydrated manifest, and runs `coworld certify` with five separate baseline-player containers.

Each ordinary CI run uploads a 14-day artifact containing the hydrated manifest and certification transcript. It deliberately does not upload the Coworld to Softmax and requires no secrets.

The separate manual `Hosted five-LLM episode` workflow builds and uploads the Coworld, uploads the LLM player with hosted Bedrock access, and requests one episode with five independent player containers. It requires a `SOFTMAX_TOKEN` repository secret. Deterministic fallback is disabled for this run, and the workflow checks all five player logs for one successful model response per requested turn before rendering `final-image.png`.

See [hosted five-LLM trials](docs/trials.md) for completed cat, dog, and elephant episodes with Actions evidence and replay links.

## Local episode without Docker or API keys

```bash
.venv/bin/python scripts/run_local_episode.py --turns 10 --target "light bulb"
```

This starts the real game server plus five `codrawing.player.cli_player` seats that
obtain each decision from the locally installed `codex` (gpt-5.6-luna) and `claude`
(claude-sonnet-5) CLIs, mirroring the permanent_coworld resident split. Config,
per-seat logs, `results.json`, and `replay.json` land in `runs/local-*/`. Hosted
evidence runs still use `codrawing.player.llm_player`.

## Local tests without Docker

```bash
python3 -m unittest discover -s tests -v
```

These tests cover deterministic target selection, action validation, simultaneous collisions, message logging, and the five-player template plan. Full Coworld certification still requires Docker.
