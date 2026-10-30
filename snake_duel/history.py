"""Every finished match, kept per opponent and arena, so models can be compared: one JSON line
per match in ``SNAKE_DUEL_DATA_DIR`` (``~/.local/share/snake_duel`` by default; the App Store
keeps it in a volume).

A match is ``{"at", "model", "snakes", "people", "speed", "seconds", "lang", "sides": [side, …],
"asks", "ask_secs", "failed", "bad"}``; a side is ``{"name", "kind", "score", "apples", "golds",
"crashes"}``, and an AI's side also has its own ``asks``, ``ask_secs``, ``failed``, ``bad`` and
``left`` (a person's snake it took over). ``model`` is the AI Hub's label for the model that
answered, or ``"practice"`` for practice snakes; ``ask_secs`` is the mean time to decide (null
when no AI ever answered). Matches kept before people could play together have ``you`` and
``ai``/``ais`` instead of ``sides``; :func:`sides_of` reads both.
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


def sides_of(match: dict[str, Any]) -> list[dict[str, Any]]:
    """Every snake of a match, however old the record is (the person's first)."""
    if isinstance(match.get("sides"), list):
        return [side for side in match["sides"] if isinstance(side, dict)]
    out = []
    if isinstance(match.get("you"), dict):
        out.append({**match["you"], "kind": "person"})
    old = match.get("ais") if isinstance(match.get("ais"), list) else [match.get("ai")]
    out.extend({**side, "kind": "ai"} for side in old if isinstance(side, dict))
    return out


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
            if isinstance(match, dict) and len(sides_of(match)) >= 2:
                out.append(match)
    return out


@dataclasses.dataclass
class ModelRow:
    model: str
    arena: str  # "3 隻蛇", "5 隻蛇（2 人）" …
    matches: int
    you_won: int  # a person came first alone
    ai_won: int  # an AI snake came first, no person with it
    draws: int  # a person and an AI snake share first place
    ai_points: str  # an AI snake's mean score, "7.5"
    ai_crashes: str  # an AI snake's crashes per match, "0.5"
    ai_secs: str  # its mean time to decide, "1.2" ("–" when it never answered)


def _mean(values: list[float]) -> str:
    return f"{sum(values) / len(values):.1f}" if values else "–"


def board(matches: list[dict[str, Any]], words: dict[str, str]) -> list[ModelRow]:
    """A row per opponent and arena, the most played first. ``words`` names the practice snake
    (``practice``) and the arena (``mode`` with ``{n}`` snakes, ``mode_people`` with ``{p}``
    people as well)."""
    groups: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for match in matches:
        sides = sides_of(match)
        people = int(match.get("people") or sum(1 for side in sides if side.get("kind") == "person"))
        groups.setdefault((str(match.get("model") or "?"), len(sides), people), []).append(match)
    rows = []
    for (model, snakes, people), played in groups.items():
        won = lost = drawn = 0
        ais: list[dict[str, Any]] = []
        for match in played:
            sides = sides_of(match)
            top = max(int(side.get("score", 0)) for side in sides)
            best = {side.get("kind") for side in sides if int(side.get("score", 0)) == top}
            won += best == {"person"}
            lost += best == {"ai"}
            drawn += len(best) > 1
            ais.extend(side for side in sides if side.get("kind") == "ai")
        timed = [float(match["ask_secs"]) for match in played if isinstance(match.get("ask_secs"), (int, float))]
        rows.append(
            ModelRow(
                model=words["practice"] if model == PRACTICE else model,
                arena=(words["mode_people"] if people > 1 else words["mode"]).format(n=snakes, p=people),
                matches=len(played),
                you_won=won,
                ai_won=lost,
                draws=drawn,
                ai_points=_mean([float(side.get("score", 0)) for side in ais]),
                ai_crashes=_mean([float(side.get("crashes", 0)) for side in ais]),
                ai_secs=_mean(timed),
            )
        )
    rows.sort(key=lambda row: (-row.matches, row.model, row.arena))
    return rows
