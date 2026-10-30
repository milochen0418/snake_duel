"""The arenas people share, and the task that plays one.

A room is a plain object in this process — no Reflex state — so every tab in it sees the same
world: its task moves the match on step by step, asks each AI snake's AI, and keeps the board as
JSON. Each player's page (:class:`snake_duel.state.Game`) copies that into its own view and puts
the keys its person presses into their player's turns.

A room holds at most :data:`snake_duel.engine.MAX_SNAKES` snakes. The people in it take the first
seats and AI snakes fill the rest, so a room of five with two people playing has three AI snakes.
Playing alone is a room of one that is not listed and starts at once. A person who goes away is
dropped; mid-match an AI takes their snake over, so the arena stays as full as it started.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import math
import random
import time
from typing import Any

from reflex_ddns_auth import ai

from snake_duel import brain, engine, history
from snake_duel.match import LENGTHS, PRACTICE_SECS, SLOW, SPEEDS, Asked, Decision, Match

logger = logging.getLogger(__name__)

COUNTDOWN = 3  # seconds before a match starts
ASK_TIMEOUT = 60.0  # an answer this late is about a board long gone
WARMUP_TIMEOUT = 90.0
STALE = 6.0  # seconds without a word from a tab before its player counts as gone
OPEN_TICK = 0.25  # how often a room that isn't playing looks at itself
LOG_ROWS = 6  # decisions kept for the page
CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0 or 1: they are read wrong
CODE_LEN = 4

rooms: dict[str, "Room"] = {}


# ------------------------------------------------------------ what a page shows


@dataclasses.dataclass
class Chip:
    """One snake on the scoreboard."""

    id: str
    name: str
    kind: str  # person or ai
    left: bool
    score: int
    out: str  # seconds until it is back after a crash, "" while it is on the board


@dataclasses.dataclass
class AiLook:
    """What one AI snake is doing, in no language: the page puts it into words."""

    id: str
    name: str
    left: bool  # a person's snake an AI took over
    state: str  # thinking, plan, idle or out
    think: int  # seconds the ask out has taken
    slow: bool  # long enough to be worth saying why
    aim: str  # the food's letter, or a cell
    gold: bool  # the aim is a gold one
    words: str
    note: str  # why its last ask gave nothing


@dataclasses.dataclass
class Place:
    """One snake's line in the result."""

    rank: int
    id: str
    name: str
    kind: str
    score: int
    apples: int
    golds: int
    crashes: int
    asks: str  # "" for a person
    secs: str


@dataclasses.dataclass
class Card:
    """An open room, as the lobby lists it."""

    id: str
    host: str
    who: str  # everyone in it, "小明 · 阿美"
    people: int
    total: int
    foe: str
    speed: str
    length: str


# ------------------------------------------------------------ a room


@dataclasses.dataclass
class Player:
    token: str  # the tab's Reflex client token
    name: str
    seat: str = ""  # which snake is theirs, once a match is on
    turns: list[str] = dataclasses.field(default_factory=list)
    seen: float = 0.0  # when its page last looked (time.monotonic)

    def here(self, now: float) -> bool:
        return now - self.seen < STALE


@dataclasses.dataclass
class Room:
    id: str
    host: str  # a player's token
    lang: str  # the host's, for what the AIs are told
    foe: str  # hub or practice
    speed: str
    length: str
    total: int  # snakes in the arena, people and AI snakes together
    listed: bool = True  # playing alone opens a room nobody is invited to
    players: dict[str, Player] = dataclasses.field(default_factory=dict)
    match: Match | None = None
    phase: str = "open"  # open, warmup, countdown, play or result
    count: int = 0  # the countdown
    left: int = 0  # seconds of the match left
    frame: str = ""  # the board, as JSON for the canvas
    chips: list[Chip] = dataclasses.field(default_factory=list)
    ais: list[AiLook] = dataclasses.field(default_factory=list)
    said: list[Decision] = dataclasses.field(default_factory=list)
    places: list[Place] = dataclasses.field(default_factory=list)
    rep: dict[str, str] = dataclasses.field(default_factory=dict)
    model: str = ""
    seq: int = 0  # bumped to end what the task is doing
    task: asyncio.Task | None = None

    @property
    def people(self) -> list[Player]:
        return list(self.players.values())

    @property
    def full(self) -> bool:
        return len(self.players) >= self.total

    @property
    def playing(self) -> bool:
        return self.phase in ("warmup", "countdown", "play")

    def card(self) -> Card:
        host = self.players.get(self.host)
        return Card(
            id=self.id,
            host=host.name if host else "",
            who=" · ".join(p.name for p in self.people),
            people=len(self.players),
            total=self.total,
            foe=self.foe,
            speed=self.speed,
            length=self.length,
        )


def _code() -> str:
    while True:
        code = "".join(random.choice(CODE) for _ in range(CODE_LEN))
        if code not in rooms:
            return code


def open_room(
    token: str,
    name: str,
    lang: str,
    foe: str,
    speed: str,
    length: str,
    total: int,
    listed: bool = True,
    model: str = "",
) -> Room:
    """A new room with its host in it."""
    room = Room(
        id=_code(),
        host=token,
        lang=lang if lang in ("zh", "en") else "zh",
        foe=foe if foe in ("hub", "practice") else "practice",
        speed=speed if speed in SPEEDS else "normal",
        length=length if length in LENGTHS else "60",
        total=max(2, min(total, engine.MAX_SNAKES)),
        listed=listed,
        model=model,
    )
    room.players[token] = Player(token=token, name=name, seen=time.monotonic())
    rooms[room.id] = room
    return room


def get(code: str) -> Room | None:
    return rooms.get((code or "").strip().upper())


def of(token: str) -> Room | None:
    """The room this tab is in, if any."""
    return next((room for room in rooms.values() if token in room.players), None)


def listing() -> list[Card]:
    """The open rooms anyone may join, the fullest first."""
    now = time.monotonic()
    out = [
        room.card()
        for room in rooms.values()
        if room.listed and room.phase == "open" and not room.full and any(p.here(now) for p in room.people)
    ]
    out.sort(key=lambda card: (-card.people, card.id))
    return out


def join(room: Room, token: str, name: str) -> bool:
    """Puts a tab in a room (True), unless the match has begun or the room is full."""
    if token in room.players:
        room.players[token].name = name
        return True
    if room.phase != "open" or room.full:
        return False
    room.players[token] = Player(token=token, name=name, seen=time.monotonic())
    return True


def touch(room: Room, token: str) -> None:
    if player := room.players.get(token):
        player.seen = time.monotonic()


def turn(room: Room, token: str, way: str) -> None:
    """A key the person pressed; their snake takes it on one of the next ticks."""
    player = room.players.get(token)
    if player is None or not room.playing:
        return
    if not player.turns or player.turns[-1] != way:
        player.turns = [*player.turns, way][-3:]


def leave(room: Room, token: str) -> None:
    """A tab that went back to the lobby (mid-match an AI takes its snake over)."""
    player = room.players.pop(token, None)
    if player is None:
        return
    if player.seat and room.match is not None and room.playing:
        room.match.hand_to_ai(player.seat)
    if not room.players:
        close(room)
    elif room.host == token:
        room.host = next(iter(room.players))


def close(room: Room) -> None:
    room.seq += 1
    rooms.pop(room.id, None)


def set_up(room: Room, **changes: Any) -> None:
    """The host's settings, as far as they make sense (never fewer seats than there are people)."""
    for key, value in changes.items():
        if key == "total":
            room.total = max(len(room.players), min(int(value), engine.MAX_SNAKES))
        elif key == "foe" and value in ("hub", "practice"):
            room.foe = value
        elif key == "speed" and value in SPEEDS:
            room.speed = value
        elif key == "length" and value in LENGTHS:
            room.length = value


def start(room: Room, warm: bool = False) -> None:
    """Begins a match: the people here take the first seats, AI snakes fill the rest."""
    if room.playing:
        return
    now = time.monotonic()
    here = [p for p in room.people if p.here(now)]
    seconds = LENGTHS.get(room.length, 60)
    room.match = Match(room.foe, room.lang, room.speed, seconds, [p.name for p in here], room.total, model=room.model)
    for player in room.people:
        player.seat, player.turns = "", []
    for player, sid in zip(here, room.match.seats):
        player.seat = sid
    room.seq += 1
    room.phase = "warmup" if warm and room.foe == "hub" else "countdown"
    room.count, room.left = COUNTDOWN, seconds
    room.said, room.places, room.rep = [], [], {}
    room.frame = json.dumps(room.match.frame(), separators=(",", ":"))
    _show(room, room.match, now)
    ensure_task(room)


def ensure_task(room: Room) -> None:
    """Starts the room's own task (it ends when the room does). Without a loop running — in a
    test — there is no task and the room is stepped by hand."""
    if room.task is not None and not room.task.done():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        room.task = None
        return
    room.task = asyncio.create_task(_run(room), name=f"snake_duel_room_{room.id}")


# ------------------------------------------------------------ playing it


async def _ask(system: str, messages: list[dict[str, str]], started: float, lang: str) -> Asked:
    out = Asked()
    try:
        reply = ai.stream(brain.ROLE, system, messages, max_tokens=brain.MAX_TOKENS, effort="low")

        async def read() -> str:
            return "".join([piece async for piece in reply])

        out.text = await asyncio.wait_for(read(), ASK_TIMEOUT)
        out.model, out.stop = reply.model, reply.stop
    except asyncio.TimeoutError:
        out.error = f"超過 {ASK_TIMEOUT:.0f} 秒沒答" if lang == "zh" else f"no answer in {ASK_TIMEOUT:.0f} s"
    except ai.HubUnavailable as e:
        out.error = str(e)
    except Exception as e:  # noqa: BLE001 - whatever it was, the snake goes on without it
        out.error = f"{type(e).__name__}: {e}"
    out.secs = round(time.monotonic() - started, 1)
    return out


async def _practice(plan: list[brain.Target], started: float) -> Asked:
    await asyncio.sleep(PRACTICE_SECS)
    return Asked(plan=plan, secs=round(time.monotonic() - started, 1))


async def _run(room: Room) -> None:
    """A room's whole life: waiting, playing, and the result, until nobody is left."""
    try:
        while room.id in rooms:
            if room.playing:
                await _play(room)
                continue
            await asyncio.sleep(OPEN_TICK)
            now = time.monotonic()
            _drop_absent(room, now)
            if not room.players:
                return
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - one room's trouble must not take the server with it
        logger.exception("room %s stopped", room.id)
    finally:
        if rooms.get(room.id) is room:
            rooms.pop(room.id, None)


async def _play(room: Room) -> None:
    """One match, from its warm-up to its result."""
    seq, game = room.seq, room.match
    if game is None:
        return
    tick = game.world.tick_ms / 1000
    if room.phase == "warmup":
        # Loads a local model before the countdown, so its loading isn't counted as thinking.
        try:
            await asyncio.wait_for(ai.complete(brain.ROLE, "Reply with OK.", [{"role": "user", "content": "OK?"}], max_tokens=1), WARMUP_TIMEOUT)
        except Exception:  # noqa: BLE001 - the first ask will say what is wrong
            pass
        if room.seq != seq:
            return
        room.phase = "countdown"
    go_at = time.monotonic() + COUNTDOWN
    next_at = go_at
    asking: dict[str, asyncio.Task[Asked]] = {}
    try:
        while room.seq == seq:
            now = time.monotonic()
            if now < go_at:
                await asyncio.sleep(min(0.1, go_at - now))
            else:
                next_at += tick
                wait = next_at - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                else:
                    next_at = time.monotonic()  # fell behind: go on from now, don't rush
            if room.seq != seq:
                return
            now = time.monotonic()
            for sid, task in list(asking.items()):
                if task.done():
                    _take(room, game, sid, task.result(), now)
                    del asking[sid]
            _drop_absent(room, now)
            if not room.players:
                close(room)
                return
            if room.phase == "countdown":
                if now >= go_at:
                    room.phase, room.count = "play", 0
                else:
                    room.count = math.ceil(go_at - now)
            if room.phase == "play":
                game.step({p.seat: p.turns for p in room.people if p.seat})
                room.frame = json.dumps(game.frame(), separators=(",", ":"))
                if game.world.over:
                    _show(room, game, now)  # the last tick counts too
                    _finish(room, game)
                    return
            _show(room, game, now)
            for sid in game.ai_seats:
                if sid not in asking and game.due(sid, now):
                    question = game.ask(sid, now)
                    if isinstance(question, list):
                        asking[sid] = asyncio.create_task(_practice(question, now))
                    else:
                        asking[sid] = asyncio.create_task(_ask(*question, now, game.lang))
    finally:
        for task in asking.values():
            if not task.done():
                task.cancel()  # ends the hub's request, so the model stops too


def _drop_absent(room: Room, now: float) -> None:
    """Players whose tabs stopped looking: mid-match an AI takes their snake over."""
    for player in [p for p in room.people if not p.here(now)]:
        room.players.pop(player.token, None)
        if player.seat and room.match is not None and room.playing:
            room.match.hand_to_ai(player.seat)
    if room.players and room.host not in room.players:
        room.host = next(iter(room.players))


def _take(room: Room, game: Match, sid: str, asked: Asked, now: float) -> None:
    decision = game.take(sid, asked, now)
    room.model = game.model
    room.said = [decision, *room.said][:LOG_ROWS]


def _show(room: Room, game: Match, now: float) -> None:
    """What the pages draw this tick, in no language."""
    world = game.world
    room.left = math.ceil(world.left)
    room.chips = [
        Chip(
            id=sid,
            name=seat.name,
            kind=seat.kind,
            left=seat.left,
            score=world.snakes[sid].score,
            out="" if world.snakes[sid].alive else f"{max(0.0, world.seconds(world.snakes[sid].back_at - world.tick)):.1f}",
        )
        for sid, seat in game.seats.items()
    ]
    looks = []
    for sid, seat in game.ai_seats.items():
        snake = world.snakes[sid]
        think = int(game.thinking(sid, now))
        aim, gold = "", False
        if seat.aim and seat.plan:
            first = seat.plan[0]
            if first.label and (food := world.food(first.label)):
                aim, gold = food.label, food.kind == "gold"
            else:
                aim = f"({seat.aim[0]},{seat.aim[1]})"
        looks.append(
            AiLook(
                id=sid,
                name=seat.name,
                left=seat.left,
                state="out" if not snake.alive else "thinking" if seat.asking else "plan" if seat.aim else "idle",
                think=think,
                slow=seat.asking and snake.alive and think >= SLOW,
                aim=aim,
                gold=gold,
                words=seat.words,
                note=seat.note,
            )
        )
    room.ais = looks


def _finish(room: Room, game: Match) -> None:
    summary = game.summary(LENGTHS.get(room.length, 60))
    history.save(summary)
    lines = sorted(zip(game.seats.items(), summary["sides"]), key=lambda pair: -pair[1]["score"])
    places, rank, last = [], 0, None
    for i, ((sid, seat), side) in enumerate(lines):
        if side["score"] != last:
            rank, last = i + 1, side["score"]
        secs = side.get("ask_secs")
        places.append(
            Place(
                rank=rank,
                id=sid,
                name=seat.name,
                kind=seat.kind,
                score=side["score"],
                apples=side["apples"],
                golds=side["golds"],
                crashes=side["crashes"],
                asks=str(side["asks"]) if seat.kind == "ai" else "",
                secs=(f"{secs:.1f}" if secs is not None else "–") if seat.kind == "ai" else "",
            )
        )
    secs = summary["ask_secs"]
    room.places = places
    room.left = 0
    room.model = summary["model"]
    room.rep = {
        "asks": str(summary["asks"]),
        "secs": f"{secs:.1f}" if secs is not None else "–",
        "failed": str(summary["failed"]),
        "bad": str(summary["bad"]),
    }
    room.ais = [dataclasses.replace(look, state="", think=0, slow=False, aim="") for look in room.ais]
    room.phase = "result"
