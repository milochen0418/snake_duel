"""One match as it is played: the world, each AI snake's plan, and when to ask each AI again.

No Reflex here: the page's background task (``Game.run_match``) owns a :class:`Match`, calls
:meth:`Match.step` every tick with the person's turns, starts an ask for an AI snake whenever
:meth:`Match.due` says so (each snake has at most one out at a time; the snakes don't wait for
them) and hands each answer to :meth:`Match.take`. An AI snake's plan is a list of places
(:class:`brain.Target`); it heads for the first one still there, and an answer replaces the plan.

A duel is the person against one AI snake (``ai1``); a free-for-all has two to four (``ai1`` …).
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from snake_duel import brain, engine, history
from snake_duel.engine import Cell

# Milliseconds per step: how fast all snakes move.
SPEEDS = {"slow": 210, "normal": 160, "fast": 120}
LENGTHS = {"60": 60, "120": 120}
CROWDS = ("2", "3", "4")  # AI snakes in a free-for-all
REASK = 1.5  # seconds after an answer before the AI is asked again anyway (the board moves on)
RETRY = 3.0  # seconds after an ask that failed
MIN_GAP = 0.4  # seconds between the starts of two asks for one snake
PRACTICE_SECS = 0.8  # how long a practice snake "thinks"
SLOW = 6.0  # an ask out this long is worth a word on the page


@dataclasses.dataclass
class Asked:
    """What came back for one ask: the AI's text, or a practice snake's plan."""

    text: str = ""
    model: str = ""
    stop: str = ""
    error: str = ""
    secs: float = 0.0
    plan: list[brain.Target] | None = None


@dataclasses.dataclass
class Decision:
    """One answer, as the page lists it."""

    who: str  # the snake's id
    name: str
    at: str  # seconds into the match
    aim: str  # where it said to go: "B → D", "(12,5)" or "—"
    words: str
    secs: str
    tone: str  # ok, odd (off format) or failed


@dataclasses.dataclass
class Seat:
    """One AI snake's mind: its plan, where it heads, and how its asks went."""

    id: str
    name: str
    plan: list[brain.Target] = dataclasses.field(default_factory=list)
    aim: Cell | None = None
    way: list[Cell] = dataclasses.field(default_factory=list)
    words: str = ""
    note: str = ""  # why its last ask gave nothing
    decisions: list[Decision] = dataclasses.field(default_factory=list)
    secs: list[float] = dataclasses.field(default_factory=list)
    failed: int = 0
    bad: int = 0
    asked_at: float = -1e9
    answered_at: float = -1e9
    failed_at: float = -1e9
    asking: bool = False
    gold_new: bool = False


class Match:
    def __init__(self, foe: str, lang: str, speed: str, seconds: int, ais: int = 1, seed: int | None = None, model: str = "") -> None:
        self.foe = foe  # hub or practice
        self.lang = lang
        self.speed = speed if speed in SPEEDS else "normal"
        ids = [f"ai{i}" for i in range(1, ais + 1)]
        self.world = engine.new_world(["you", *ids], SPEEDS[self.speed], seconds, seed)
        self.seats = {sid: Seat(sid, brain.ai_name(sid, ais)) for sid in ids}
        self.names = {"you": "你" if lang == "zh" else "You", **{sid: seat.name for sid, seat in self.seats.items()}}
        self.events: list[dict[str, Any]] = []
        self.model = model  # what the lobby was told answers; each answer says it again

    @property
    def crowd(self) -> bool:
        return len(self.seats) > 1

    # ------------------------------------------------------------ a tick

    def target(self, sid: str) -> Cell | None:
        """Where AI snake ``sid`` heads now: the first place of its plan that is still there
        (food eaten or gone, or a cell reached, drops out)."""
        seat, snake = self.seats[sid], self.world.snakes[sid]
        while seat.plan:
            first = seat.plan[0]
            if first.label:
                food = self.world.food(first.label)
                if food is not None:
                    return food.cell
            elif first.cell is not None and not (snake.alive and first.cell == snake.head):
                return first.cell
            seat.plan.pop(0)
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
        moves: dict[str, str | None] = {"you": turn}
        for sid in self.seats:
            moves[sid] = engine.pilot(world, sid, self.target(sid))[0]
        events = engine.step(world, moves)
        for event in events:
            if event["kind"] == "gold":
                for seat in self.seats.values():
                    seat.gold_new = True
            elif event["kind"] == "crash" and event["who"] in self.seats:
                self.seats[event["who"]].plan = []  # it starts somewhere else: a new plan when it's back
        for seat in self.seats.values():
            self._aim(seat)
        self.events = events
        return events

    def _aim(self, seat: Seat) -> None:
        snake = self.world.snakes[seat.id]
        seat.aim = self.target(seat.id) if snake.alive else None
        seat.way = engine.path(self.world, snake.head, seat.aim, engine.blocked(self.world, seat.id)) if seat.aim else []

    def frame(self) -> dict[str, Any]:
        aims = {sid: (seat.aim, seat.way) for sid, seat in self.seats.items()}
        return engine.frame(self.world, self.names, aims, self.events)

    # ------------------------------------------------------------ asking the AIs

    def due(self, sid: str, now: float) -> bool:
        """Whether to ask AI snake ``sid``'s AI now: its plan has run out, a gold one showed up,
        or a few seconds went by since its last answer (never while an ask is out for it, or
        while it is off the board)."""
        seat = self.seats[sid]
        if seat.asking or self.world.over or not self.world.snakes[sid].alive:
            return False
        if now - seat.asked_at < MIN_GAP or now - seat.failed_at < RETRY:
            return False
        return self.target(sid) is None or seat.gold_new or now - seat.answered_at >= REASK

    def ask(self, sid: str, now: float) -> tuple[str, list[dict[str, str]]] | list[brain.Target]:
        """Starts an ask for AI snake ``sid``: what to send the AI Hub (system, messages), or for
        a practice snake its plan, decided at once from the board as it is now (it answers a
        moment later)."""
        seat = self.seats[sid]
        seat.asking, seat.asked_at, seat.gold_new = True, now, False
        if self.foe == "practice":
            return [brain.Target(label=label) for label in engine.greedy(self.world, sid)]
        return brain.system(self.lang, self.world), brain.messages(self.world, sid, self.lang)

    def thinking(self, sid: str, now: float) -> float:
        """Seconds the ask out for ``sid`` has taken so far (0 when none is)."""
        seat = self.seats[sid]
        return now - seat.asked_at if seat.asking else 0.0

    def take(self, sid: str, asked: Asked, now: float) -> Decision:
        """The answer to ``sid``'s ask: its places become the plan (an answer naming nowhere
        keeps the old one)."""
        seat = self.seats[sid]
        seat.asking, seat.answered_at = False, now
        if asked.model:
            self.model = asked.model
        zh = self.lang == "zh"
        plan: list[brain.Target] = []
        words, tone, seat.note = "", "ok", ""
        if asked.error:
            tone, seat.note, seat.failed_at = "failed", asked.error, now
            seat.failed += 1
        elif asked.plan is not None:
            plan = asked.plan
        elif not asked.text.strip():
            tone, seat.failed_at = "failed", now
            seat.failed += 1
            if asked.stop == "max_tokens":
                seat.note = "想太久，字數用完了還沒給答案" if zh else "it thought too long and ran out of words before answering"
            else:
                seat.note = "沒有給答案" if zh else "it gave no answer"
        else:
            move = brain.parse(asked.text, {f.label for f in self.world.foods}, self.world.w, self.world.h)
            plan, words = move.targets, move.say
            if not move.well_formed:
                tone = "odd"
                seat.bad += 1
        if tone != "failed":
            seat.secs.append(asked.secs)
        if plan:
            seat.plan = plan
            self._aim(seat)
        if words:
            seat.words = words
        aim = " → ".join(t.label or f"({t.cell[0]},{t.cell[1]})" for t in plan if t.label or t.cell) or "—"
        decision = Decision(
            who=sid,
            name=seat.name,
            at=f"{self.world.seconds(self.world.tick):.0f}",
            aim=aim,
            words=words or (seat.note if tone == "failed" else ""),
            secs=f"{asked.secs:.1f}",
            tone=tone,
        )
        seat.decisions.append(decision)
        return decision

    # ------------------------------------------------------------ the end

    def summary(self, seconds: int) -> dict[str, Any]:
        """The finished match, as :mod:`history` keeps it."""

        def side(who: str) -> dict[str, int]:
            s = self.world.snakes[who]
            return {"score": s.score, "apples": s.apples, "golds": s.golds, "crashes": s.crashes}

        def mean(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 2) if values else None

        seats = list(self.seats.values())
        return {
            "at": round(time.time()),
            "model": history.PRACTICE if self.foe == "practice" else (self.model or "?"),
            "mode": "crowd" if self.crowd else "duel",
            "snakes": len(self.world.snakes),
            "speed": self.speed,
            "seconds": seconds,
            "lang": self.lang,
            "you": side("you"),
            "ais": [{**side(s.id), "asks": len(s.decisions), "ask_secs": mean(s.secs), "failed": s.failed, "bad": s.bad} for s in seats],
            "asks": sum(len(s.decisions) for s in seats),
            "ask_secs": mean([x for s in seats for x in s.secs]),
            "failed": sum(s.failed for s in seats),
            "bad": sum(s.bad for s in seats),
        }
