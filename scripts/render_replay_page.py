"""Render a replay.json into a self-contained HTML replay viewer.

    python scripts/render_replay_page.py runs/local-*/replay.json out.html

The page is content-only HTML (no doctype/html/head/body wrapper) so it can be
published directly as a Claude artifact; browsers also render it standalone.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

TEMPLATE = """<title>__TITLE__</title>
<style>
:root {
  --paper: #FAF7F0;
  --card: #FFFFFF;
  --grid: #E9E3D6;
  --line: #D8D2C4;
  --ink: #26221A;
  --muted: #7A7466;
  --accent: #B45309;
  --good: #15803D;
  --bad: #B91C1C;
}
:root:not([data-theme="light"]) { }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #161512;
    --card: #201E19;
    --grid: #2E2B24;
    --line: #3A362D;
    --ink: #EAE6DC;
    --muted: #948D7D;
    --accent: #F59E0B;
    --good: #4ADE80;
    --bad: #F87171;
  }
}
:root[data-theme="dark"] {
  --paper: #161512;
  --card: #201E19;
  --grid: #2E2B24;
  --line: #3A362D;
  --ink: #EAE6DC;
  --muted: #948D7D;
  --accent: #F59E0B;
  --good: #4ADE80;
  --bad: #F87171;
}
body {
  background: var(--paper);
  color: var(--ink);
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  margin: 0;
  padding: 24px 16px 64px;
  font-variant-numeric: tabular-nums;
}
.wrap { max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
.eyebrow { text-transform: uppercase; letter-spacing: 0.14em; font-size: 12px; color: var(--muted); }
h1 { font-size: 22px; font-weight: 700; margin: 4px 0 0; letter-spacing: 0.02em; text-wrap: balance; }
.statrow { display: flex; flex-wrap: wrap; gap: 12px 28px; align-items: baseline; }
.stat { display: flex; flex-direction: column; gap: 2px; }
.stat .k { font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); }
.stat .v { font-size: 18px; font-weight: 700; }
.stat .v.pass { color: var(--good); }
.stat .v.fail { color: var(--bad); }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 16px 18px 12px;
}
.card h2 {
  font-size: 13px; font-weight: 700; letter-spacing: 0.08em;
  margin: 0 0 12px; text-transform: uppercase;
  border-bottom: 1px solid var(--line); padding-bottom: 10px;
}
.gridbox { overflow-x: auto; }
#board {
  display: grid;
  gap: 1px;
  background: var(--grid);
  border: 1px solid var(--grid);
  width: max-content;
  margin: 0 auto;
}
#board .c { width: 22px; height: 22px; background: var(--card); }
#board .c.changed { box-shadow: inset 0 0 0 2.5px var(--ink); }
.cardfoot {
  display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  border-top: 1px solid var(--line);
  margin-top: 12px; padding-top: 10px;
  font-size: 12.5px; color: var(--muted);
}
.controls { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
.controls button {
  font: inherit; color: var(--ink); background: var(--card);
  border: 1px solid var(--line); border-radius: 4px;
  padding: 4px 12px; cursor: pointer;
}
.controls button:hover { border-color: var(--muted); }
.controls button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.controls input[type="range"] { flex: 1; accent-color: var(--accent); }
.turnlabel { min-width: 76px; text-align: right; font-size: 13px; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 720px) { .split { grid-template-columns: 1fr; } }
.preds { display: flex; flex-direction: column; gap: 6px; }
.pred { display: grid; grid-template-columns: 110px 1fr 52px; gap: 8px; align-items: center; font-size: 12.5px; }
.pred .bar { height: 8px; background: var(--grid); border-radius: 2px; overflow: hidden; }
.pred .bar i { display: block; height: 100%; background: var(--muted); }
.pred.target .bar i { background: var(--accent); }
.pred .pv { text-align: right; color: var(--muted); }
.scoreline { font-size: 13px; margin-bottom: 12px; }
.scoreline .delta.up { color: var(--good); }
.scoreline .delta.down { color: var(--bad); }
#spark { width: 100%; height: 64px; display: block; }
.msgs { display: flex; flex-direction: column; gap: 9px; font-size: 13px; line-height: 1.5; }
.msg { display: flex; gap: 9px; align-items: baseline; }
.chip { flex: none; width: 10px; height: 10px; border-radius: 2px; transform: translateY(1px); }
.msg .who { color: var(--muted); flex: none; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: 12.5px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
</style>
<div class="wrap">
  <header>
    <div class="eyebrow">co/place replay &middot; quickdraw_nearest_prototype_v1</div>
    <h1 id="title"></h1>
  </header>
  <div class="statrow" id="stats"></div>

  <section class="card">
    <h2 id="canvastitle">Canvas</h2>
    <div class="gridbox"><div id="board"></div></div>
    <div class="controls">
      <button id="prev" aria-label="previous turn">&#8249;</button>
      <button id="play">play</button>
      <button id="next" aria-label="next turn">&#8250;</button>
      <input type="range" id="scrub" min="0" value="0">
      <span class="turnlabel" id="turnlabel"></span>
    </div>
    <div class="cardfoot"><span id="lastaction"></span><span id="framestamp"></span></div>
  </section>

  <div class="split">
    <section class="card">
      <h2>Classifier</h2>
      <div class="scoreline" id="scoreline"></div>
      <svg id="spark" viewBox="0 0 400 64" preserveAspectRatio="none" aria-label="score by turn"></svg>
      <div class="preds" id="preds"></div>
    </section>
    <section class="card">
      <h2>Board messages</h2>
      <div class="msgs" id="msgs"></div>
    </section>
  </div>

  <div class="legend" id="legend"></div>
</div>
<script type="application/json" id="replay-data">__DATA__</script>
<script>
const replay = JSON.parse(document.getElementById("replay-data").textContent);
const frames = replay.frames;
const results = replay.results;
const W = frames[0].width, H = frames[0].height;
const SEATS = ["#EF4444", "#3B82F6", "#22C55E", "#F59E0B", "#A855F7"];
const names = frames[0].player_names;
const WHITE = "#FFFFFF";

document.getElementById("title").textContent =
  "Target: " + frames[0].target + " \\u00b7 " + names.length + " agents \\u00b7 " +
  frames[0].max_turns + " turns";
document.getElementById("canvastitle").textContent = "Canvas (" + W + "\\u00d7" + H + ")";

const finalFb = results.final_image_model_feedback;
const bestScore = results.best_target_score !== undefined
  ? results.best_target_score
  : Math.max(...frames.map(fr => fr.image_model_feedback ? fr.image_model_feedback.target_score : 0));
const stats = [
  ["best score", (bestScore * 100).toFixed(1) + "%", ""],
  ["final score", (finalFb.target_score * 100).toFixed(1) + "%", ""],
  ["threshold", (finalFb.pass_threshold * 100).toFixed(0) + "%", ""],
  ["evaluation", results.evaluation_passed ? "PASS" : "NOT PASSING",
    results.evaluation_passed ? "pass" : "fail"],
  ["target rank", finalFb.target_rank + " of " + finalFb.label_count, ""],
  ["accepted pixels", results.accepted_pixels.join(" / "), ""],
];
document.getElementById("stats").innerHTML = stats.map(([k, v, cls]) =>
  '<div class="stat"><span class="k">' + k + '</span><span class="v ' + cls + '">' + v + "</span></div>"
).join("");

document.getElementById("legend").innerHTML = names.map((n, i) =>
  '<span><span class="chip" style="background:' + SEATS[i] + '"></span>' + n +
  (i === 4 ? " (score captain)" : "") + "</span>"
).join("");

const board = document.getElementById("board");
board.style.gridTemplateColumns = "repeat(" + W + ", 22px)";
const cells = [];
for (let i = 0; i < W * H; i++) {
  const d = document.createElement("div");
  d.className = "c";
  board.appendChild(d);
  cells.push(d);
}

const scrub = document.getElementById("scrub");
scrub.max = frames.length - 1;

function fmtDelta(d) {
  return (d >= 0 ? "+" : "") + d.toFixed(6);
}

function show(f) {
  scrub.value = f;
  const frame = frames[f];
  const prev = f > 0 ? frames[f - 1] : null;
  const changed = [];
  for (let i = 0; i < W * H; i++) {
    const color = frame.canvas[i];
    cells[i].style.background = color === WHITE ? "" : color;
    const was = prev ? prev.canvas[i] : WHITE;
    const isChanged = was !== color;
    cells[i].classList.toggle("changed", isChanged);
    if (isChanged) changed.push(i);
  }
  document.getElementById("turnlabel").textContent = "T" + (frame.turn) + "/" + frame.max_turns;
  document.getElementById("framestamp").textContent =
    "frame " + (f + 1) + " of " + frames.length;

  const acts = changed.map(i => {
    const owner = frame.owners ? frame.owners[i] : null;
    const who = owner === null || owner === undefined || owner < 0 ? "?" : names[owner];
    const verb = frame.canvas[i] === WHITE ? "erased" : "painted";
    return who + " " + verb + " (" + (i % W) + "," + Math.floor(i / W) + ")";
  });
  document.getElementById("lastaction").textContent = acts.length ? acts.join(" \\u00b7 ") : "no accepted writes";

  const fb = frame.image_model_feedback;
  if (fb) {
    const d = fb.score_delta;
    document.getElementById("scoreline").innerHTML =
      "score <strong>" + fb.target_score.toFixed(6) + "</strong> " +
      '<span class="delta ' + (d >= 0 ? "up" : "down") + '">' + fmtDelta(d) + "</span>" +
      " \\u00b7 rank " + fb.target_rank + "/" + fb.label_count;
    document.getElementById("preds").innerHTML = fb.top_predictions.map(p =>
      '<div class="pred' + (p.label === frame.target ? " target" : "") + '">' +
      "<span>" + p.label + "</span>" +
      '<span class="bar"><i style="width:' + (p.probability * 100).toFixed(1) + '%"></i></span>' +
      '<span class="pv">' + (p.probability * 100).toFixed(1) + "%</span></div>"
    ).join("");
  }

  document.getElementById("msgs").innerHTML = (frame.messages || []).map(m =>
    '<div class="msg"><span class="chip" style="background:' + SEATS[m.slot] + '"></span>' +
    '<span class="who">' + m.player + "</span><span>" + m.text.replace(/</g, "&lt;") + "</span></div>"
  ).join("") || '<span style="color:var(--muted)">no messages this turn</span>';
  drawSpark(f);
}

function drawSpark(f) {
  const scores = frames.map(fr => fr.image_model_feedback ? fr.image_model_feedback.target_score : 0);
  const max = Math.max(...scores, results.evaluation_threshold, 0.01);
  const x = i => frames.length > 1 ? (i / (frames.length - 1)) * 392 + 4 : 200;
  const y = v => 58 - (v / max) * 52;
  const path = scores.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
  const ty = y(results.evaluation_threshold);
  document.getElementById("spark").innerHTML =
    '<line x1="4" y1="' + ty + '" x2="396" y2="' + ty +
      '" stroke="var(--line)" stroke-dasharray="4 4" stroke-width="1"></line>' +
    '<path d="' + path + '" fill="none" stroke="var(--accent)" stroke-width="2"></path>' +
    '<circle cx="' + x(f) + '" cy="' + y(scores[f]) + '" r="4" fill="var(--accent)"></circle>';
}

let cursor = frames.length - 1;
let timer = null;
function go(f) { cursor = Math.max(0, Math.min(frames.length - 1, f)); show(cursor); }
document.getElementById("prev").addEventListener("click", () => go(cursor - 1));
document.getElementById("next").addEventListener("click", () => go(cursor + 1));
scrub.addEventListener("input", () => go(Number(scrub.value)));
document.getElementById("play").addEventListener("click", function () {
  if (timer) { clearInterval(timer); timer = null; this.textContent = "play"; return; }
  if (cursor >= frames.length - 1) cursor = -1;
  this.textContent = "stop";
  timer = setInterval(() => {
    if (cursor >= frames.length - 1) { clearInterval(timer); timer = null; document.getElementById("play").textContent = "play"; return; }
    go(cursor + 1);
  }, 700);
});
go(cursor);
</script>
"""


def render(replay_path: Path, output_path: Path) -> None:
    replay = json.loads(replay_path.read_text())
    title = "co/place replay: " + replay["frames"][0]["target"]
    payload = json.dumps(
        {"frames": replay["frames"], "results": replay["results"]},
        separators=(",", ":"),
    ).replace("</", "<\\/")
    output_path.write_text(
        TEMPLATE.replace("__TITLE__", title).replace("__DATA__", payload)
    )
    print(f"wrote {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: render_replay_page.py REPLAY_JSON OUTPUT_HTML")
    render(Path(sys.argv[1]), Path(sys.argv[2]))
