"""Every finished match, kept per opponent, so models can be compared: one JSON line per match in
``SNAKE_DUEL_DATA_DIR`` (``~/.local/share/snake_duel`` by default; the App Store keeps it in a
volume).

A match is ``{"at", "model", "speed", "seconds", "lang", "you": side, "ai": side, "asks",
"ask_secs", "failed", "bad"}``, a side ``{"score", "apples", "golds", "crashes"}``; ``model`` is
the AI Hub's label for the model that answered, or ``"practice"`` for the practice snake;
``ask_secs`` is the AI's mean time to decide (null when it never answered).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_lock = threading.Lock()
PRACTICE = "practice"


def data_dir() -> Path:
    return Path(os.environ.get("SNAKE_DUEL_DATA_DIR") or Path.home() / ".local" / "share" / "snake_duel")


def _file() -> Path:
    return data_dir() / "matches.jsonl"


def save(match: dict[str, Any]) -> None:
    path = _file()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(match, ensure_ascii=False) + "\n")


def load() -> list[dict[str, Any]]:
    path = _file()
    if not path.exists():
        return []
    out = []
    with _lock, path.open(encoding="utf-8") as f:
        for line in f:
            try:
                match = json.loads(line)
            except ValueError:
                continue
            if isinstance(match, dict) and isinstance(match.get("you"), dict) and isinstance(match.get("ai"), dict):
                out.append(match)
    return out


@dataclasses.dataclass
class ModelRow:
    model: str
    matches: int
    you_won: int
    ai_won: int
    draws: int
    ai_points: str  # the AI's mean score, "7.5"
    ai_crashes: str  # its crashes per match, "0.5"
    ai_secs: str  # its mean time to decide, "1.2" ("–" when it never answered)


def _mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.1f}" if values else "–"


def board(matches: list[dict[str, Any]], practice_label: str) -> list[ModelRow]:
    """A row per opponent, the most played first; the practice snake goes by ``practice_label``."""
    by_model: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        by_model.setdefault(str(match.get("model") or "?"), []).append(match)
    rows = []
    for model, played in by_model.items():
        you = [int(m["you"].get("score", 0)) for m in played]
        ai = [int(m["ai"].get("score", 0)) for m in played]
        timed = [float(m["ask_secs"]) for m in played if isinstance(m.get("ask_secs"), (int, float))]
        rows.append(
            ModelRow(
                model=practice_label if model == PRACTICE else model,
                matches=len(played),
                you_won=sum(1 for a, b in zip(you, ai) if a > b),
                ai_won=sum(1 for a, b in zip(you, ai) if b > a),
                draws=sum(1 for a, b in zip(you, ai) if a == b),
                ai_points=_mean([float(p) for p in ai]),
                ai_crashes=_mean([float(m["ai"].get("crashes", 0)) for m in played]),
                ai_secs=_mean(timed),
            )
        )
    rows.sort(key=lambda row: (-row.matches, row.model))
    return rows
