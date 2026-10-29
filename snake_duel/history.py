"""Every finished match, kept per opponent and mode, so models can be compared: one JSON line per
match in ``SNAKE_DUEL_DATA_DIR`` (``~/.local/share/snake_duel`` by default; the App Store keeps
it in a volume).

A match is ``{"at", "model", "mode", "snakes", "speed", "seconds", "lang", "you": side, "ais":
[side, …], "asks", "ask_secs", "failed", "bad"}``; a side is ``{"score", "apples", "golds",
"crashes"}``, an AI's side also has its own ``asks``, ``ask_secs``, ``failed`` and ``bad``.
``mode`` is ``duel`` (one AI snake) or ``crowd`` (a free-for-all of ``snakes``); ``model`` is the
AI Hub's label for the model that answered, or ``"practice"`` for practice snakes; ``ask_secs``
is the AI's mean time to decide (null when it never answered). Matches kept before the
free-for-all have one ``ai`` side instead of ``ais``.
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


def _ais(match: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(match.get("ais"), list):
        return [a for a in match["ais"] if isinstance(a, dict)]
    return [match["ai"]] if isinstance(match.get("ai"), dict) else []


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
            if isinstance(match, dict) and isinstance(match.get("you"), dict) and _ais(match):
                out.append(match)
    return out


@dataclasses.dataclass
class ModelRow:
    model: str
    mode: str  # "1 對 1", "4 條蛇混戰" …
    matches: int
    you_won: int  # alone at the top
    ai_won: int  # an AI snake on top, you not
    draws: int  # you on top with an AI snake
    ai_points: str  # an AI snake's mean score, "7.5"
    ai_crashes: str  # an AI snake's crashes per match, "0.5"
    ai_secs: str  # its mean time to decide, "1.2" ("–" when it never answered)


def _mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.1f}" if values else "–"


def board(matches: list[dict[str, Any]], words: dict[str, str]) -> list[ModelRow]:
    """A row per opponent and mode, the most played first. ``words`` names the practice snake
    (``practice``) and the modes (``mode_duel``, and ``mode_crowd`` with ``{n}`` snakes)."""
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for match in matches:
        snakes = int(match.get("snakes") or 2) if match.get("mode") == "crowd" else 2
        groups.setdefault((str(match.get("model") or "?"), snakes), []).append(match)
    rows = []
    for (model, snakes), played in groups.items():
        won = lost = drawn = 0
        for m in played:
            you, theirs = int(m["you"].get("score", 0)), [int(a.get("score", 0)) for a in _ais(m)]
            top = max(theirs)
            won += you > top
            lost += you < top
            drawn += you == top
        sides = [a for m in played for a in _ais(m)]
        timed = [float(m["ask_secs"]) for m in played if isinstance(m.get("ask_secs"), (int, float))]
        rows.append(
            ModelRow(
                model=words["practice"] if model == PRACTICE else model,
                mode=words["mode_duel"] if snakes == 2 else words["mode_crowd"].format(n=snakes),
                matches=len(played),
                you_won=won,
                ai_won=lost,
                draws=drawn,
                ai_points=_mean([float(a.get("score", 0)) for a in sides]),
                ai_crashes=_mean([float(a.get("crashes", 0)) for a in sides]),
                ai_secs=_mean(timed),
            )
        )
    rows.sort(key=lambda row: (-row.matches, row.model, row.mode))
    return rows
