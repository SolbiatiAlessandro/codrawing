from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
DEFAULT_DATABASE = STATE_DIR / "coworld.sqlite3"
MODEL_PATH = ROOT / "models" / "quickdraw_prototypes.json"
AGENTS_DIR = ROOT / "agents"
TRACES_DIR = STATE_DIR / "traces"
SNAPSHOTS_DIR = STATE_DIR / "snapshots"

BOARD_WIDTH = 128
BOARD_HEIGHT = 128
TARGET = "light bulb"
PIXEL_BUDGET = 10
PASS_THRESHOLD = 0.95
CODEX_MODEL = "gpt-5.6-luna"
CLAUDE_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class AgentConfig:
    slug: str
    name: str
    color: str
    provider: str
    model: str


AGENTS = (
    AgentConfig("luma_finch", "Luma Finch", "#EF4444", "codex", CODEX_MODEL),
    AgentConfig("miro_volt", "Miro Volt", "#3B82F6", "claude", CLAUDE_MODEL),
    AgentConfig("ivy_prism", "Ivy Prism", "#22C55E", "codex", CODEX_MODEL),
    AgentConfig("sol_wick", "Sol Wick", "#F59E0B", "claude", CLAUDE_MODEL),
    AgentConfig("nyx_filament", "Nyx Filament", "#A855F7", "codex", CODEX_MODEL),
)
