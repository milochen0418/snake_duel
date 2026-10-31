"""One match as it is played: the world, each AI snake's plan, and when to ask each AI again.

No Reflex here: a room (:mod:`snake_duel.rooms`) owns a :class:`Match`, calls :meth:`Match.step`
every tick with each person's turns, starts an ask for an AI snake whenever :meth:`Match.due`
says so (each snake has at most one out at a time; the snakes don't wait for them) and hands each
answer to :meth:`Match.take`. An AI snake's plan is a list of places (:class:`brain.Target`); it
heads for the first one still there, and an answer replaces the plan.

A match has 2 to 5 snakes in the seats ``s1`` … ``s5``: the people playing take the first seats
and AI snakes fill the rest, so five snakes with two people playing means three AI snakes. A
person who goes away is taken over by an AI (:meth:`Match.hand_to_ai`), so the arena stays full;
someone who comes back, or who was watching, takes a snake from an AI
(:meth:`Match.hand_to_person`).
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
TOTALS = ("2", "3", "4", "5")  # snakes in the arena, people and AI snakes together
REASK = 1.5  # seconds after an answer before the AI is asked again anyway (the board moves on)
RETRY = 3.0  # seconds after an ask that failed
MIN_GAP = 0.4  # seconds between the starts of two asks for one snake
PRACTICE_SECS = 0.8  # how long a practice snake "thinks"
SLOW = 6.0  # an ask out this long is worth a word on the page
NAME_LEN = 12


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

    who: str  # the seat's id
    name: str
    at: str  # seconds into the match
    aim: str  # where it said to go: "B → D", "(12,5)" or "—"
    words: str
    secs: str
    tone: str  # ok, odd (off format) or failed


@dataclasses.dataclass
class Seat:
    """One snake of the match: a person's, or an AI's with its plan and how its asks went."""

    id: str
    name: str
    kind: str  # person or ai
    avatar: str = ""  # a person's picture, for who is who on the page
    left: bool = False  # a person who went away, now played by an AI
    plan: list[brain.Target] = dataclasses.field(default_factory=list)
    aim: Cell | None = None
    way: list[Cell] = dataclasses.field(default_factory=list)
    words: str = ""
    note: str = ""  # why its last ask gave nothing
    secs: list[float] = dataclasses.field(default_factory=list)
    asks: int = 0
    failed: int = 0
    bad: int = 0
    asked_at: float = -1e9
    answered_at: float = -1e9
    failed_at: float = -1e9
    asking: bool = False
    gold_new: bool = False


def name_of(name: str, seat: int) -> str:
    """A person's name as the board shows it, or ``P<seat>`` when they gave none."""
    return name.strip()[:NAME_LEN] or f"P{seat}"


class Match:
    def __init__(
        self,
        foe: str,
        lang: str,
        speed: str,
        seconds: int,
        people: list[str],
        total: int,
        seed: int | None = None,
        model: str = "",
    ) -> None:
        self.foe = foe  # hub or practice
        self.lang = lang
        self.speed = speed if speed in SPEEDS else "normal"
        self.total = max(2, min(total, engine.MAX_SNAKES))
        named = [name_of(name, i + 1) for i, name in enumerate(people[: self.total])]
        self.people = len(named)
        ais = self.total - self.people
        ids = [f"s{i + 1}" for i in range(self.total)]
        self.world = engine.new_world(ids, SPEEDS[self.speed], seconds, seed)
        self.seats: dict[str, Seat] = {}
        for i, sid in enumerate(ids):
            if i < len(named):
                self.seats[sid] = Seat(sid, named[i], "person")
            else:
                self.seats[sid] = Seat(sid, "AI" if ais == 1 else f"AI {i - len(named) + 1}", "ai")
        self.events: list[dict[str, Any]] = []
        self.model = model  # what the lobby was told answers; each answer says it again
        self.had_ai = ais > 0  # an AI played some snake (for the scoreboard)

    @property
    def names(self) -> dict[str, str]:
        return {sid: seat.name for sid, seat in self.seats.items()}

    @property
    def ai_seats(self) -> dict[str, Seat]:
        return {sid: seat for sid, seat in self.seats.items() if seat.kind == "ai"}

    def hand_to_ai(self, sid: str) -> None:
        """A person left: an AI takes their snake over (it keeps their name and their score)."""
        seat = self.seats[sid]
        seat.kind, seat.left = "ai", True
        seat.plan, seat.aim, seat.way = [], None, []
        seat.asked_at = seat.answered_at = seat.failed_at = -1e9
        seat.asking = seat.gold_new = False
        self.had_ai = True

    def hand_to_person(self, sid: str, name: str = "", avatar: str = "") -> None:
        """A person takes a snake from an AI: their own coming back, or (with ``name``) one they
        were watching. The snake goes on as it is, with its score."""
        seat = self.seats[sid]
        seat.kind, seat.left = "person", False
        seat.plan, seat.aim, seat.way = [], None, []
        if name:
            seat.name, seat.avatar = name, avatar

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

    def step(self, turns: dict[str, list[str]]) -> list[dict[str, Any]]:
        """One tick. ``turns`` holds each person's queue of turns by seat: the first that changes
        their way is taken off it (the rest wait for the next ticks)."""
        world = self.world
        moves: dict[str, str | None] = {}
        for sid, seat in self.seats.items():
            if seat.kind != "person":
                moves[sid] = engine.pilot(world, sid, self.target(sid))[0]
                continue
            snake = world.snakes[sid]
            queue = turns.setdefault(sid, [])
            turn = None
            while queue and snake.alive:
                way = queue.pop(0)
                if way in engine.DIRS and way not in (snake.heading, engine.OPPOSITE[snake.heading]):
                    turn = way
                    break
            if not snake.alive:
                queue.clear()
            moves[sid] = turn
        events = engine.step(world, moves)
        for event in events:
            if event["kind"] == "gold":
                for seat in self.ai_seats.values():
                    seat.gold_new = True
            elif event["kind"] == "crash" and self.seats[event["who"]].kind == "ai":
                self.seats[event["who"]].plan = []  # it starts somewhere else: a new plan when it's back
        for seat in self.ai_seats.values():
            self._aim(seat)
        self.events = events
        return events

    def _aim(self, seat: Seat) -> None:
        snake = self.world.snakes[seat.id]
        seat.aim = self.target(seat.id) if snake.alive else None
        seat.way = engine.path(self.world, snake.head, seat.aim, engine.blocked(self.world, seat.id)) if seat.aim else []

    def frame(self) -> dict[str, Any]:
        """The board for the page's canvas, each snake with its kind (``person`` or ``ai``)."""
        aims = {sid: (seat.aim, seat.way) for sid, seat in self.ai_seats.items()}
        out = engine.frame(self.world, self.names, aims, self.events)
        for snake in out["snakes"]:
            snake["k"] = self.seats[snake["id"]].kind
        return out

    # ------------------------------------------------------------ asking the AIs

    def due(self, sid: str, now: float) -> bool:
        """Whether to ask AI snake ``sid``'s AI now: its plan has run out, a gold one showed up,
        or a few seconds went by since its last answer (never while an ask is out for it, or
        while it is off the board)."""
        seat = self.seats[sid]
        if seat.kind != "ai" or seat.asking or self.world.over or not self.world.snakes[sid].alive:
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
        people = sum(1 for s in self.seats.values() if s.kind == "person")
        return brain.system(self.lang, self.world, people, self.total - people), brain.messages(self.world, sid, self.lang, self.seats)

    def thinking(self, sid: str, now: float) -> float:
        """Seconds the ask out for ``sid`` has taken so far (0 when none is)."""
        seat = self.seats[sid]
        return now - seat.asked_at if seat.asking else 0.0

    def take(self, sid: str, asked: Asked, now: float) -> Decision:
        """The answer to ``sid``'s ask: its places become the plan (an answer naming nowhere
        keeps the old one)."""
        seat = self.seats[sid]
        seat.asking, seat.answered_at = False, now
        seat.asks += 1
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
        return Decision(
            who=sid,
            name=seat.name,
            at=f"{self.world.seconds(self.world.tick):.0f}",
            aim=aim,
            words=words or (seat.note if tone == "failed" else ""),
            secs=f"{asked.secs:.1f}",
            tone=tone,
        )

    # ------------------------------------------------------------ the end

    def summary(self, seconds: int) -> dict[str, Any]:
        """The finished match, as :mod:`history` keeps it."""

        def mean(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 2) if values else None

        sides = []
        for sid, seat in self.seats.items():
            snake = self.world.snakes[sid]
            side = {
                "name": seat.name,
                "kind": seat.kind,
                "score": snake.score,
                "apples": snake.apples,
                "golds": snake.golds,
                "crashes": snake.crashes,
            }
            if seat.kind == "ai":
                side |= {"asks": seat.asks, "ask_secs": mean(seat.secs), "failed": seat.failed, "bad": seat.bad, "left": seat.left}
            sides.append(side)
        ais = list(self.ai_seats.values())
        return {
            "at": round(time.time()),
            "model": history.PEOPLE if not self.had_ai else history.PRACTICE if self.foe == "practice" else (self.model or "?"),
            "snakes": self.total,
            "people": sum(1 for seat in self.seats.values() if seat.kind == "person" or seat.left),
            "speed": self.speed,
            "seconds": seconds,
            "lang": self.lang,
            "sides": sides,
            "asks": sum(seat.asks for seat in ais),
            "ask_secs": mean([x for seat in ais for x in seat.secs]),
            "failed": sum(seat.failed for seat in ais),
            "bad": sum(seat.bad for seat in ais),
        }
