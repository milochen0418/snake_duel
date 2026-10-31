"""The arenas people share, and the task that plays one.

A room is a plain object in this process — no Reflex state — so every tab in it sees the same
world: its task moves the match on step by step, asks each AI snake's AI, and keeps the board as
JSON. Each person's page (:class:`snake_duel.state.Game`) copies that into its own view and puts
the keys they press into their player's turns.

People are known by a ``uid``: the signed-in account, so all of someone's tabs are one person
with one snake, or ``guest-<id>`` for one tab of someone not signed in.

A room holds at most :data:`snake_duel.engine.MAX_SNAKES` snakes. The people here take the first
seats and AI snakes fill the rest, so a room of five with two people playing has three AI snakes;
anyone else watches, and may take a snake over from an AI or wait for the next match. Playing
alone is a room of one that is not listed in the lobby and starts at once.

A link must keep working while people come and go, so nothing here hurries to end:

- A person whose page has gone quiet for :data:`STALE` seconds is away, not gone: an AI plays
  their snake, and they get it back the moment their page speaks again. A phone that switched
  apps to paste the link loses nothing.
- A host away for :data:`HOST_WAIT` seconds lets anyone here start the match.
- A match with nobody here for :data:`EMPTY_PLAY` seconds is called off.
- A room lives on for :data:`LINGER` seconds after its last person went quiet.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import math
import random
import time

from reflex_ddns_auth import ai

from snake_duel import brain, engine, history, preview
from snake_duel.match import LENGTHS, NAME_LEN, PRACTICE_SECS, SLOW, SPEEDS, Asked, Decision, Match

logger = logging.getLogger(__name__)

COUNTDOWN = 3  # seconds before a match starts
ASK_TIMEOUT = 60.0  # an answer this late is about a board long gone
WARMUP_TIMEOUT = 90.0
STALE = 6.0  # seconds without a word from a page before its person counts as away
HOST_WAIT = 15.0  # how long a host may be away before anyone here may start the match
EMPTY_PLAY = 30.0  # seconds a match goes on with nobody here
LINGER = 600.0  # seconds a person and a room wait for someone to come back
INVITE_SECONDS = 60.0  # how long an invitation stays on someone's screen
ONLINE_SECONDS = 8.0  # someone in the lobby who has gone this quiet isn't offered any more
OPEN_TICK = 0.25  # how often a room that isn't playing looks at itself
THUMB_SECONDS = 1.5  # how old the lobby's little picture of a room may be
LOG_ROWS = 6  # decisions kept for the page
MAX_PEOPLE = 30  # people in a room, watchers included
MAX_FRIENDS = 8  # people online a room shows
CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0 or 1: they are read wrong
CODE_LEN = 4

rooms: dict[str, "Room"] = {}
online: dict[str, "Online"] = {}  # who has the game open right now, by uid
invites: dict[str, "Invite"] = {}  # the invitation on someone's screen, by uid


# ------------------------------------------------------------ what a page shows


@dataclasses.dataclass
class Chip:
    """One snake on the scoreboard."""

    id: str
    name: str
    kind: str  # person or ai
    left: bool  # a person's snake an AI is playing
    score: int
    out: str  # seconds until it is back after a crash, "" while it is on the board
    avatar: str = ""


@dataclasses.dataclass
class AiLook:
    """What one AI snake is doing, in no language: the page puts it into words."""

    id: str
    name: str
    left: bool  # a person's snake an AI is playing
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
    avatar: str = ""


@dataclasses.dataclass
class Card:
    """A room, as the lobby lists it."""

    id: str
    who: str  # everyone in it, "小明 · 阿美"
    people: int
    total: int
    status: str  # open, play or result
    left: int  # seconds of the match left
    thumb: str  # a little picture of the board, as a data URL


@dataclasses.dataclass
class Online:
    """Someone with the game open."""

    uid: str
    key: str  # what the page calls them: not their e-mail
    name: str
    avatar: str
    seen: float
    busy: bool  # in the middle of a match


@dataclasses.dataclass
class Invite:
    """An invitation on someone's screen."""

    code: str
    by: str  # who asked
    at: float


# ------------------------------------------------------------ a room


@dataclasses.dataclass
class Player:
    uid: str
    name: str
    avatar: str = ""
    seat: str = ""  # which snake is theirs in this match ("": they watch)
    turns: list[str] = dataclasses.field(default_factory=list)
    seen: float = 0.0  # when their page last spoke (time.monotonic)

    def here(self, now: float) -> bool:
        return now - self.seen < STALE


@dataclasses.dataclass
class Room:
    id: str
    host: str  # a player's uid
    lang: str  # the host's, for what the AIs are told and for the link's card
    foe: str  # hub or practice
    speed: str
    length: str
    total: int  # snakes in the arena, people and AI snakes together
    listed: bool = True  # playing alone opens a room nobody is invited to
    players: dict[str, Player] = dataclasses.field(default_factory=dict)  # in the order they came
    match: Match | None = None
    phase: str = "open"  # open, warmup, countdown, play or result
    count: int = 0  # the countdown
    left: int = 0  # seconds of the match left
    frame: str = ""  # the board, as JSON for the canvas
    faces: str = "{}"  # each person's picture by seat, as JSON for the canvas
    chips: list[Chip] = dataclasses.field(default_factory=list)
    ais: list[AiLook] = dataclasses.field(default_factory=list)
    said: list[Decision] = dataclasses.field(default_factory=list)
    places: list[Place] = dataclasses.field(default_factory=list)
    rep: dict[str, str] = dataclasses.field(default_factory=dict)
    model: str = ""
    notice: str = ""  # what happened that everyone here should read ("called_off")
    thumb: str = ""
    thumb_at: float = -1e9
    seq: int = 0  # bumped to end what the task is doing
    task: asyncio.Task | None = None
    changed: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)  # set every tick

    @property
    def people(self) -> list[Player]:
        return list(self.players.values())

    @property
    def playing(self) -> bool:
        return self.phase in ("warmup", "countdown", "play")

    def card(self, now: float) -> Card:
        if now - self.thumb_at > THUMB_SECONDS:
            self.thumb, self.thumb_at = preview.thumb(self), now
        status = "open" if self.phase == "open" else "result" if self.phase == "result" else "play"
        return Card(self.id, " · ".join(p.name for p in self.people), len(self.players), self.total, status, self.left, self.thumb)


def clean_name(name: str) -> str:
    return (name or "").strip()[:NAME_LEN]


def _code() -> str:
    while True:
        code = "".join(random.choice(CODE) for _ in range(CODE_LEN))
        if code not in rooms:
            return code


def open_room(
    uid: str,
    name: str,
    avatar: str,
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
        host=uid,
        lang=lang if lang in ("zh", "en") else "zh",
        foe=foe if foe in ("hub", "practice") else "practice",
        speed=speed if speed in SPEEDS else "normal",
        length=length if length in LENGTHS else "60",
        total=max(2, min(total, engine.MAX_SNAKES)),
        listed=listed,
        model=model,
    )
    room.players[uid] = Player(uid, clean_name(name), avatar, seen=time.monotonic())
    rooms[room.id] = room
    return room


def get(code: str) -> Room | None:
    return rooms.get((code or "").strip().upper())


def of(uid: str) -> Room | None:
    """The room this person is in, if any."""
    return next((room for room in rooms.values() if uid in room.players), None)


def listing() -> list[Card]:
    """The rooms the lobby offers: those with someone here, the ones still waiting first."""
    now = time.monotonic()
    shown = [room for room in rooms.values() if room.listed and any(p.here(now) for p in room.people)]
    shown.sort(key=lambda room: (room.phase != "open", -len(room.players), room.id))
    return [room.card(now) for room in shown]


def enter(room: Room, uid: str, name: str, avatar: str = "") -> bool:
    """Puts someone in a room, whatever it is doing: in the middle of a match they watch until
    they take a snake over or the next match starts. False when it can hold no more."""
    player = room.players.get(uid)
    if player is not None:
        player.name, player.avatar, player.seen = clean_name(name), avatar, time.monotonic()
        return True
    if len(room.players) >= MAX_PEOPLE:
        return False
    room.players[uid] = Player(uid, clean_name(name), avatar, seen=time.monotonic())
    invites.pop(uid, None)
    _pulse(room)
    return True


def rename(old: str, uid: str, name: str, avatar: str) -> None:
    """Someone signed in or out in this tab: the same person under another uid. When the account
    is already somewhere, that place wins and the old guest leaves."""
    room = of(old)
    if room is None or old == uid:
        return
    if of(uid) is not None:
        leave(room, old)
        return
    player = room.players[old]
    player.uid, player.name, player.avatar = uid, clean_name(name), avatar
    room.players = {(uid if key == old else key): p for key, p in room.players.items()}
    if room.host == old:
        room.host = uid
    if room.match is not None and player.seat in room.match.seats:
        seat = room.match.seats[player.seat]
        seat.name, seat.avatar = player.name, avatar


def touch(room: Room, uid: str) -> None:
    """This person's page spoke. If an AI was playing their snake, they have it back."""
    player = room.players.get(uid)
    if player is None:
        return
    player.seen = time.monotonic()
    if room.playing and room.match is not None and player.seat:
        seat = room.match.seats.get(player.seat)
        if seat is not None and seat.kind == "ai" and seat.left:
            room.match.hand_to_person(player.seat)
            player.turns = []


def turn(room: Room, uid: str, way: str) -> None:
    """A key the person pressed; their snake takes it on one of the next ticks."""
    player = room.players.get(uid)
    if player is None or not player.seat or not room.playing:
        return
    if not player.turns or player.turns[-1] != way:
        player.turns = [*player.turns, way][-3:]


def take_over(room: Room, uid: str, sid: str) -> bool:
    """Someone watching takes a snake from the AI playing it."""
    player = room.players.get(uid)
    game = room.match
    if player is None or player.seat or game is None or not room.playing:
        return False
    seat = game.seats.get(sid)
    if seat is None or seat.kind != "ai":
        return False
    for other in room.people:
        if other.seat == sid:  # it was theirs, and they are away: they watch when they are back
            other.seat, other.turns = "", []
    game.hand_to_person(sid, player.name, player.avatar)
    player.seat, player.turns = sid, []
    return True


def leave(room: Room, uid: str) -> None:
    """Someone went back to the lobby (mid-match an AI takes their snake over)."""
    player = room.players.pop(uid, None)
    if player is None:
        return
    if player.seat and room.match is not None and room.playing:
        seat = room.match.seats.get(player.seat)
        if seat is not None and seat.kind == "person":
            room.match.hand_to_ai(player.seat)
    if not room.players:
        close(room)
    elif room.host == uid:
        now = time.monotonic()
        room.host = next((p.uid for p in room.people if p.here(now)), room.people[0].uid)


def close(room: Room) -> None:
    room.seq += 1
    rooms.pop(room.id, None)
    _pulse(room)


def can_lead(room: Room, uid: str) -> bool:
    """Whether this person may start the match and set it up: the host, or anyone here when the
    host has been away for a while."""
    if uid not in room.players:
        return False
    host = room.players.get(room.host)
    return uid == room.host or host is None or time.monotonic() - host.seen > HOST_WAIT


def set_up(room: Room, total: int | None = None, speed: str = "", length: str = "") -> None:
    """The settings of the next match (never fewer seats than the people waiting, up to five)."""
    if total is not None:
        room.total = max(2, min(len(room.players), engine.MAX_SNAKES), min(total, engine.MAX_SNAKES))
    if speed in SPEEDS:
        room.speed = speed
    if length in LENGTHS:
        room.length = length


def start(room: Room, warm: bool = False) -> None:
    """Begins a match: the people here take the first seats, AI snakes fill the rest, and anyone
    beyond that many snakes watches."""
    if room.playing:
        return
    now = time.monotonic()
    seated = [p for p in room.people if p.here(now)][: room.total]
    if not seated:
        return
    seconds = LENGTHS.get(room.length, 60)
    game = Match(room.foe, room.lang, room.speed, seconds, [p.name for p in seated], room.total, model=room.model)
    room.match = game
    for player in room.people:
        player.seat, player.turns = "", []
    for player, sid in zip(seated, game.seats):
        player.seat = sid
        game.seats[sid].avatar = player.avatar
    room.seq += 1
    room.phase = "warmup" if warm and room.foe == "hub" and game.ai_seats else "countdown"
    room.count, room.left = COUNTDOWN, seconds
    room.said, room.places, room.rep, room.notice = [], [], {}, ""
    room.frame = json.dumps(game.frame(), separators=(",", ":"))
    room.faces = json.dumps({sid: seat.avatar for sid, seat in game.seats.items() if seat.avatar}, separators=(",", ":"))
    _show(room, game, now)
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


# ------------------------------------------------------------ who else is around


def _key(uid: str) -> str:
    return hashlib.sha1(uid.encode("utf-8")).hexdigest()[:12]


def seen_online(uid: str, name: str, avatar: str, busy: bool) -> None:
    online[uid] = Online(uid, _key(uid), clean_name(name), avatar, time.monotonic(), busy)


def others_online(room: Room) -> list[Online]:
    """People with the game open who are not in this room, the free ones first."""
    now = time.monotonic()
    for uid, who in list(online.items()):
        if now - who.seen > ONLINE_SECONDS:
            del online[uid]
    around = [who for who in online.values() if who.uid not in room.players]
    around.sort(key=lambda who: (who.busy, who.name))
    return around[:MAX_FRIENDS]


def invite(room: Room, by: str, key: str) -> None:
    """Puts an invitation to this room on the screen of someone online."""
    inviter = room.players.get(by)
    who = next((w for w in online.values() if w.key == key), None)
    if inviter is not None and who is not None and who.uid not in room.players:
        invites[who.uid] = Invite(room.id, inviter.name, time.monotonic())


def ask_first(room: Room, uid: str) -> None:
    """Someone in the middle of a match opened this room's link: they choose before they leave."""
    host = room.players.get(room.host)
    invites[uid] = Invite(room.id, host.name if host else room.id, time.monotonic())


def invited(room: Room, uid: str) -> bool:
    invite_now = invites.get(uid)
    return invite_now is not None and invite_now.code == room.id


def invitation(uid: str) -> Invite | None:
    """The invitation on this person's screen, while it still means something."""
    invite_now = invites.get(uid)
    if invite_now is None:
        return None
    room = get(invite_now.code)
    if room is None or uid in room.players or time.monotonic() - invite_now.at > INVITE_SECONDS:
        invites.pop(uid, None)
        return None
    return invite_now


def decline(uid: str) -> None:
    invites.pop(uid, None)


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
            _tidy(room, time.monotonic())
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
        room.phase = "open"
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
    nobody_since: float | None = None
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
            _tidy(room, now)
            if room.seq != seq:
                return
            if any(p.here(now) for p in room.people):
                nobody_since = None
            else:
                nobody_since = nobody_since or now
                if now - nobody_since > EMPTY_PLAY:
                    _call_off(room)
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
                    _pulse(room)
                    return
            _show(room, game, now)
            _pulse(room)
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


def _pulse(room: Room) -> None:
    """Wakes the pages waiting for this room's next tick."""
    done, room.changed = room.changed, asyncio.Event()
    done.set()


def _tidy(room: Room, now: float) -> None:
    """Who is here. An AI plays the snake of someone away; someone away too long is gone."""
    game = room.match if room.playing else None
    for player in room.people:
        if game is not None and player.seat and not player.here(now):
            seat = game.seats.get(player.seat)
            if seat is not None and seat.kind == "person":
                game.hand_to_ai(player.seat)
        if now - player.seen > LINGER:
            del room.players[player.uid]
    if not room.players:
        close(room)
    elif room.host not in room.players:
        room.host = next((p.uid for p in room.people if p.here(now)), room.people[0].uid)


def _call_off(room: Room) -> None:
    """Everyone has been gone for a while: the match ends unkept and the room waits."""
    if not room.listed:
        close(room)
        return
    room.seq += 1
    room.phase, room.match, room.frame, room.notice = "open", None, "", "called_off"
    room.chips, room.ais, room.said = [], [], []
    for player in room.people:
        player.seat, player.turns = "", []


def verdict(places: list[Place], me: str) -> tuple[str, dict[str, int | str], str]:
    """The final word as the person in seat ``me`` reads it: a word of the page's text, what goes
    in it, and its tone (you, ai or draw). Someone only watching is told who won."""
    if not places:
        return "", {}, ""
    first = [place for place in places if place.rank == 1]
    winner = {"name": first[0].name}
    mine = next((place for place in places if place.id == me), None)
    if mine is None:
        return ("draw", {}, "draw") if len(first) > 1 else ("won_by", winner, "draw")
    tied = sum(1 for place in places if place.rank == mine.rank) > 1
    if len(places) == 2:
        if tied:
            return "draw", {}, "draw"
        return ("you_win", {}, "you") if mine.rank == 1 else ("won_by", winner, "ai")
    if mine.rank == 1:
        return ("crowd_tie", {}, "draw") if tied else ("crowd_first", {}, "you")
    return "crowd_place", {"n": mine.rank}, "ai"


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
            avatar=seat.avatar,
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
                avatar=seat.avatar,
            )
        )
    secs = summary["ask_secs"]
    room.places = places
    room.left = 0
    room.model = summary["model"] if summary["model"] not in (history.PRACTICE, history.PEOPLE) else room.model
    room.rep = {
        "asks": str(summary["asks"]),
        "secs": f"{secs:.1f}" if secs is not None else "–",
        "failed": str(summary["failed"]),
        "bad": str(summary["bad"]),
    }
    room.ais = [dataclasses.replace(look, state="", think=0, slow=False, aim="") for look in room.ais]
    room.phase = "result"
