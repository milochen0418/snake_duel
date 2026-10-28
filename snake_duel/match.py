"""One match as it is played: the world, the AI's plan, and when to ask the AI again.

No Reflex here: the page's background task (``Game.run_match``) owns a :class:`Match`, calls
:meth:`Match.step` every tick with the person's turns, starts an ask whenever :meth:`Match.due`
says so (only one is out at a time; the snakes don't wait for it) and hands the answer to
:meth:`Match.take`. The AI's plan is a list of places (:class:`brain.Target`); its snake heads
for the first one still there, and an answer replaces the plan.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from snake_duel import brain, engine, history
from snake_duel.engine import Cell

# Milliseconds per step: how fast both snakes move.
SPEEDS = {"slow": 210, "normal": 160, "fast": 120}
LENGTHS = {"60": 60, "120": 120}
REASK = 1.5  # seconds after an answer before the AI is asked again anyway (the board moves on)
RETRY = 3.0  # seconds after an ask that failed
MIN_GAP = 0.4  # seconds between the starts of two asks
PRACTICE_SECS = 0.8  # how long the practice snake "thinks"
SLOW = 6.0  # an ask out this long is worth a word on the page


@dataclasses.dataclass
class Asked:
    """What came back for one ask: the AI's text, or the practice snake's plan."""

    text: str = ""
    model: str = ""
    stop: str = ""
    error: str = ""
    secs: float = 0.0
    plan: list[brain.Target] | None = None


@dataclasses.dataclass
class Decision:
    """One answer, as the page lists it."""

    at: str  # seconds into the match
    aim: str  # where it said to go: "B → D", "(12,5)" or "—"
    words: str
    secs: str
    tone: str  # ok, odd (off format) or failed


class Match:
    def __init__(self, foe: str, lang: str, speed: str, seconds: int, seed: int | None = None) -> None:
        self.foe = foe  # hub or practice
        self.lang = lang
        self.speed = speed if speed in SPEEDS else "normal"
        self.world = engine.new_world(SPEEDS[self.speed], seconds, seed)
        self.plan: list[brain.Target] = []
        self.aim: Cell | None = None
        self.way: list[Cell] = []
        self.events: list[dict[str, Any]] = []
        self.model = ""
        self.words = ""
        self.note = ""  # why the last ask gave nothing
        self.decisions: list[Decision] = []
        self.secs: list[float] = []
        self.failed = 0
        self.bad = 0
        self.asked_at = self.answered_at = self.failed_at = -1e9
        self.asking = False
        self.gold_new = False

    # ------------------------------------------------------------ a tick

    def target(self) -> Cell | None:
        """Where the AI snake heads now: the first place of the plan that is still there (food
        eaten or gone, or a cell reached, drops out)."""
        ai = self.world.snakes["ai"]
        while self.plan:
            first = self.plan[0]
            if first.label:
                food = self.world.food(first.label)
                if food is not None:
                    return food.cell
            elif first.cell is not None and not (ai.alive and first.cell == ai.head):
                return first.cell
            self.plan.pop(0)
        return None

    def step(self, turns: list[str]) -> list[dict[str, Any]]:
        """One tick. ``turns`` is the person's queue of turns: the first that changes their way is
        taken off it (the rest wait for the next ticks)."""
        world = self.world
        you = world.snakes["you"]
        turn = None
        while turns and you.alive:
            way = turns.pop(0)
            if way in engine.DIRS and way not in (you.heading, engine.OPPOSITE[you.heading]):
                turn = way
                break
        if not you.alive:
            turns.clear()
        ai_turn, _ = engine.pilot(world, "ai", self.target())
        events = engine.step(world, {"you": turn, "ai": ai_turn})
        for event in events:
            if event["kind"] == "gold":
                self.gold_new = True
            elif event["kind"] == "crash" and event["who"] == "ai":
                self.plan = []  # it starts somewhere else: a new plan when it's back
        self._aim()
        self.events = events
        return events

    def _aim(self) -> None:
        ai = self.world.snakes["ai"]
        self.aim = self.target() if ai.alive else None
        self.way = engine.path(self.world, ai.head, self.aim, engine.blocked(self.world, "ai")) if self.aim else []

    def frame(self) -> dict[str, Any]:
        return engine.frame(self.world, self.aim, self.way, self.events)

    # ------------------------------------------------------------ asking the AI

    def due(self, now: float) -> bool:
        """Whether to ask the AI now: its plan has run out, a gold one showed up, or a few
        seconds went by since its last answer (never while an ask is out, or the snake is off
        the board)."""
        ai = self.world.snakes["ai"]
        if self.asking or self.world.over or not ai.alive:
            return False
        if now - self.asked_at < MIN_GAP or now - self.failed_at < RETRY:
            return False
        return self.target() is None or self.gold_new or now - self.answered_at >= REASK

    def ask(self, now: float) -> tuple[str, list[dict[str, str]]] | list[brain.Target]:
        """Starts an ask: what to send the AI Hub (system, messages), or for the practice snake
        its plan, decided at once from the board as it is now (it answers a moment later)."""
        self.asking, self.asked_at, self.gold_new = True, now, False
        if self.foe == "practice":
            return [brain.Target(label=label) for label in engine.greedy(self.world, "ai")]
        return brain.system(self.lang), brain.messages(self.world, self.lang)

    def thinking(self, now: float) -> float:
        """Seconds the ask that is out has taken so far (0 when none is)."""
        return now - self.asked_at if self.asking else 0.0

    def take(self, asked: Asked, now: float) -> Decision:
        """The answer to the ask that was out: its places become the plan (an answer naming
        nowhere keeps the old one)."""
        self.asking, self.answered_at = False, now
        if asked.model:
            self.model = asked.model
        zh = self.lang == "zh"
        plan: list[brain.Target] = []
        words, tone, self.note = "", "ok", ""
        if asked.error:
            tone, self.note, self.failed_at = "failed", asked.error, now
            self.failed += 1
        elif asked.plan is not None:
            plan = asked.plan
        elif not asked.text.strip():
            tone, self.failed_at = "failed", now
            self.failed += 1
            if asked.stop == "max_tokens":
                self.note = "想太久，字數用完了還沒給答案" if zh else "it thought too long and ran out of words before answering"
            else:
                self.note = "沒有給答案" if zh else "it gave no answer"
        else:
            move = brain.parse(asked.text, {f.label for f in self.world.foods})
            plan, words = move.targets, move.say
            if not move.well_formed:
                tone = "odd"
                self.bad += 1
        if tone != "failed":
            self.secs.append(asked.secs)
        if plan:
            self.plan = plan
            self._aim()
        if words:
            self.words = words
        aim = " → ".join(t.label or f"({t.cell[0]},{t.cell[1]})" for t in plan if t.label or t.cell) or "—"
        decision = Decision(
            at=f"{self.world.seconds(self.world.tick):.0f}",
            aim=aim,
            words=words or (self.note if tone == "failed" else ""),
            secs=f"{asked.secs:.1f}",
            tone=tone,
        )
        self.decisions.append(decision)
        return decision

    # ------------------------------------------------------------ the end

    def summary(self, seconds: int) -> dict[str, Any]:
        """The finished match, as :mod:`history` keeps it."""

        def side(who: str) -> dict[str, int]:
            s = self.world.snakes[who]
            return {"score": s.score, "apples": s.apples, "golds": s.golds, "crashes": s.crashes}

        return {
            "at": round(time.time()),
            "model": history.PRACTICE if self.foe == "practice" else (self.model or "?"),
            "speed": self.speed,
            "seconds": seconds,
            "lang": self.lang,
            "you": side("you"),
            "ai": side("ai"),
            "asks": len(self.decisions),
            "ask_secs": round(sum(self.secs) / len(self.secs), 2) if self.secs else None,
            "failed": self.failed,
            "bad": self.bad,
        }
