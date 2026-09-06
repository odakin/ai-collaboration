"""Locate the layer-1 tools (a clone of `ai-collaboration`).

Order: env `AI_COLLABORATION_ROOT` → a sibling directory named `ai-collaboration` next to this repo
→ `~/Claude/ai-collaboration` (the author's layout). Fails loudly instead of falling back silently.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def layer1_root() -> Path:
    cands = []
    if os.environ.get("AI_COLLABORATION_ROOT"):
        cands.append(Path(os.environ["AI_COLLABORATION_ROOT"]).expanduser())
    cands.append(REPO.parent / "ai-collaboration")
    cands.append(Path.home() / "Claude" / "ai-collaboration")
    for c in cands:
        if (c / "scripts" / "verification-campaign-report.py").exists():
            return c
    print("✗ layer-1 tools not found. Clone https://github.com/odakin/ai-collaboration next to this repo "
          "or set AI_COLLABORATION_ROOT.", file=sys.stderr)
    sys.exit(1)


def tool(name: str) -> Path:
    return layer1_root() / "scripts" / name
