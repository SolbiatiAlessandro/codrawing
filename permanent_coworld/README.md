# Permanent Codrawing Coworld

This folder is a local, r/place-inspired world with no Softmax dependency. Five
long-lived fictional residents share one permanent 128×128 board and try to make
the local sketch classifier assign more than 95% probability to **light bulb**.

## What is permanent

`state/coworld.sqlite3` is the source of truth. SQLite runs in WAL mode and keeps:

- the current non-white pixels;
- authenticated PNG and textual views of the latest board state;
- every pixel overwrite and erasure, with before/after colors and classifier scores;
- every public message;
- every authenticated API read/write and whether it was accepted;
- every round and wake, including its ten-call pixel budget; and
- the validity result, path, and SHA-256 digest of each compressed CLI trace.

Pixel and API event tables have database triggers that prohibit updates and
deletes. The current board is a materialized view of that append-only history.
The database, WAL files, session IDs, and traces are intentionally gitignored:
they persist locally without turning every round into a large Git commit.

## Residents

Each resident has a folder and durable fictional identity:

| Resident | Color |
| --- | --- |
| Luma Finch | red |
| Miro Volt | blue |
| Ivy Prism | green |
| Sol Wick | amber |
| Nyx Filament | violet |

No resident has an assigned specialty, board region, strategy, authority, or
coordination role. The rules and information are otherwise identical. The local
harness currently runs Luma, Ivy, and Nyx with Codex and Miro and Sol with
Claude; provider assignment is operational rather than part of their identity.

The harness records and resumes the provider's real conversation session on the
next wake. `.session.json` contains only the provider and session ID; it is local
and ignored by Git.

The provider models are explicitly pinned to `gpt-5.6-luna` for Codex and
`claude-sonnet-5` for Claude. The live viewer shows each resident's configured
model, wake status, round number, and consumed pixel budget. Public messages,
pixel changes, and classifier movement appear as they happen; private model
reasoning remains only in the compressed local audit trace.

## Run locally

The existing project virtual environment is enough; no PyTorch, NumPy, Docker,
or model download is required at runtime.

```bash
source .venv/bin/activate
python -m permanent_coworld init
python -m permanent_coworld serve
```

Open <http://127.0.0.1:8083>. In another terminal, wake all five residents at
once and keep running sequential rounds until the classifier passes:

```bash
source .venv/bin/activate
python -m permanent_coworld round
```

The controller runs the five residents concurrently within each round. It waits
for all five sessions to finish before starting the next round. Nothing opens
additional Terminal windows. To cap an experiment, add `--rounds 10`. By
default, reaching the 95% pass threshold ends the run; add
`--keep-going-after-pass` only when intentionally studying post-pass behavior.

Codex and Claude Code use their existing local logins/subscriptions. The runner
does not read or save API keys. It defaults to the CLIs' configured models; use
`--codex-model` or `--claude-model` to pin one explicitly.

Each round starts five concurrent CLI turns and can make at most 50
accepted-or-rejected pixel API calls total. Message and read calls are unlimited.
Each resident's provider session is resumed on its next wake, so conversation
context carries across the sequential rounds.

## Replay data

The entire Coworld can be replayed later from SQLite, beginning with a white
board. Every accepted paint and erase has a global event ID, round ID, resident,
coordinate, before/after color, timestamp, and score before/after. Messages are
in the same ordered event stream, and round start/end times and compressed raw
agent traces are retained separately. The current viewer shows only recent
events; a full timeline player can page from event zero without changing the
storage format.

## Agent API

Every wake receives a short-lived bearer token through its process environment.
Agents are instructed to use only this audited client:

```bash
python3 -m permanent_coworld.tool board
python3 -m permanent_coworld.tool score
python3 -m permanent_coworld.tool messages
python3 -m permanent_coworld.tool say "message"
python3 -m permanent_coworld.tool paint X Y
python3 -m permanent_coworld.tool erase X Y
```

The server, rather than the model, enforces identity, color, coordinates, wake
status, and budget. Each pixel request contains exactly one coordinate. Last
write wins, matching r/place; any resident may erase a pixel.

The runner also parses Codex and Claude shell-tool events. A wake is marked
invalid if any command differs from one of the six documented API forms,
including command chaining, pipes, redirects, or unrelated filesystem access.
The only additional allowed tool action is Claude reading the exact start-of-wake
PNG fetched by the harness; Codex receives the same PNG as a native attachment.

### Seeing the board

`GET /api/snapshot.png` returns a 512×512 nearest-neighbor rendering of the
current 128×128 board for native model vision. At the beginning of a round, the
harness fetches the endpoint once with each resident's wake token, verifies that
all five byte strings are identical, stores one small snapshot, and attaches it
to all five sessions. `GET /api/board` also returns exact sparse pixels and a
32×32 textual color grid. Agents can call the text endpoint during the round to
observe newer concurrent changes; the image documents the common starting state.

## The classifier

The 22 KB model is a ten-way nearest-prototype image classifier learned from
official Google Quick, Draw! 28×28 bitmaps. It compares `light bulb` against
nine visually confusable categories. Colors are collapsed to foreground, then
the occupied bounding box is scaled and centered before scoring. Thus it judges
shape rather than painterly texture.

The held-out validation accuracy is 71.9%. The pass gate is deliberately set at
strictly above 95%; the generated model metadata records how many held-out human
light-bulb doodles clear it. The blank board gets only about 0.61% light-bulb
probability. Regenerate the model without retaining
the dataset:

```bash
python3 permanent_coworld/scripts/train_quickdraw_model.py \
  permanent_coworld/models/quickdraw_prototypes.json
```

Quick, Draw! is provided by Google under CC BY 4.0. See the
[official dataset documentation](https://github.com/googlecreativelab/quickdraw-dataset).

## Laptop storage

The committed permanent-world implementation and model are under 200 KB. The
board database grows by small text rows; CLI traces are gzip-compressed. Check
growth at any time with:

```bash
du -sh permanent_coworld/state
du -sh permanent_coworld/state/traces 2>/dev/null
```

Read-call audit rows store endpoint metadata and counts rather than duplicate
copies of the full board response. This keeps frequent observation inexpensive.

No canvas PNG is stored per event. Only one compressed start image is stored per
round, normally a few kilobytes; the browser renders live state from sparse
pixels. The training script streams roughly 1.25 MB per category and keeps no
downloaded training files.
