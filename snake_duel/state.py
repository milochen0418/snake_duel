"""One browser tab: the lobby, the room it is in, the match and the result.

The match itself belongs to the room (:mod:`snake_duel.rooms`), which every tab playing in it
shares. This state only looks: one background task (``Game.watch``) tells the room the tab is
still there, copies the board and the scores into this tab's own view, and while nobody is in a
room keeps the lobby's list of open rooms fresh. Keys the person presses go straight into their
player's turns.

Playing alone opens a room of one that nobody is invited to; "找人一起玩" opens a listed room,
and whoever joins takes a seat, with AI snakes filling the rest up to the number of snakes the
host chose.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from urllib.parse import urlsplit

import reflex as rx
from reflex_ddns_auth import ai

from snake_duel import brain, history, rooms
from snake_duel.i18n import TEXT
from snake_duel.match import Decision, LENGTHS, SPEEDS, TOTALS
from snake_duel.rooms import Card, Chip, Place

WATCH_PLAY = 0.06  # seconds between looks at the room while a match is on
WATCH_IDLE = 0.3  # and while waiting in a room
CARDS_EVERY = 1.5  # seconds between refreshes of the lobby's room list
GONE = 3.0  # seconds with the tab disconnected before this task gives up
KEYS = {
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
    "w": "up",
    "s": "down",
    "a": "left",
    "d": "right",
    "W": "up",
    "S": "down",
    "A": "left",
    "D": "right",
}


def _watching(token: str) -> bool:
    """Whether the tab is still connected (True when it can't be told)."""
    try:
        from reflex.utils import prerequisites

        return token in prerequisites.get_app().app.event_namespace.token_to_sid
    except Exception:  # noqa: BLE001
        return True


@dataclasses.dataclass
class Person:
    """Someone in the room, as the page lists them."""

    name: str
    me: bool
    host: bool


@dataclasses.dataclass
class AiCard:
    """An AI snake as this tab shows it during a match."""

    id: str
    name: str
    left: bool  # a person's snake an AI took over
    state: str  # thinking, plan, idle or out
    status: str  # that in words, with the seconds it has been thinking
    slow: bool  # it has been thinking long enough to say why
    aim: str
    words: str
    note: str


class Game(rx.State):
    lang: str = rx.LocalStorage("", name="snake_duel_lang")
    name: str = rx.LocalStorage("", name="snake_duel_name")
    speed: str = rx.LocalStorage("normal", name="snake_duel_speed")
    length: str = rx.LocalStorage("60", name="snake_duel_length")
    foe: str = rx.LocalStorage("hub", name="snake_duel_foe")  # hub or practice
    total: str = rx.LocalStorage("2", name="snake_duel_total")  # snakes in the arena, 2 to 5

    # the lobby
    hub_state: str = "asking"  # asking, ok, none (no hub) or error
    hub_error: str = ""
    opponent: str = ""  # what answers, e.g. "Ollama (qwen2.5:7b)"
    opponent_local: bool = False
    board: list[history.ModelRow] = []
    cards: list[Card] = []  # the open rooms
    join_error: str = ""

    # the room
    phase: str = "lobby"  # lobby, room, warmup, countdown, play or result
    code: str = ""
    is_host: bool = False
    room_people: list[Person] = []
    room_total: int = 2
    room_foe: str = ""
    room_speed: str = ""
    room_length: str = ""

    # the match
    me: str = ""  # which snake is this tab's
    frame: str = ""  # the arena, as JSON for the canvas
    count: int = 0
    left: int = 0
    model: str = ""
    chips: list[Chip] = []
    ais: list[AiCard] = []
    said: list[Decision] = []

    # the result
    places: list[Place] = []
    outcome: str = ""
    outcome_tone: str = ""  # you, ai or draw
    rep: dict[str, str] = {}

    _seq: int = 0  # a new number for every page load: an older watcher sees it and stops

    # ------------------------------------------------------------ words

    @rx.var
    def t(self) -> dict[str, str]:
        return TEXT.get(self.lang, TEXT["zh"])

    @rx.var
    def can_start(self) -> bool:
        return self.foe == "practice" or self.hub_state == "ok"

    @rx.var
    def my_score(self) -> int:
        return next((chip.score for chip in self.chips if chip.id == self.me), 0)

    @rx.var
    def my_out(self) -> str:
        return next((chip.out for chip in self.chips if chip.id == self.me), "")

    @rx.var
    def total_note(self) -> str:
        """How the seats are filled, as the lobby or the room has them now."""
        t = self.t
        if self.phase == "room":
            people = len(self.room_people)
            ais = max(0, self.room_total - people)
            return (t["total_note_full"] if ais == 0 else t["total_note_room"]).format(people=people, ais=ais)
        ais = max(0, int(self.total) - 1)
        return t["total_note_solo"].format(n=ais) if ais else t["total_note_one"]

    @rx.var
    def others(self) -> list[Chip]:
        """Every snake but this tab's, for the scoreboard."""
        return [chip for chip in self.chips if chip.id != self.me]

    @rx.var
    def foe_name(self) -> str:
        return self.t["practice"] if (self.room_foe or self.foe) == "practice" else (self.model or self.opponent)

    @rx.var
    def share_link(self) -> str:
        return f"{self.router.headers.origin}/?r={self.code}" if self.code else ""

    @rx.var
    def hub_page(self) -> str:
        """The AI Hub's page, next to this app on the same domain ("" when run on its own)."""
        parts = urlsplit(self.router.headers.origin or "")
        host = parts.hostname or ""
        if "." not in host or host.replace(".", "").isdigit():
            return ""
        return f"{parts.scheme}://ai.{host.split('.', 1)[1]}"

    # ------------------------------------------------------------ the lobby

    @rx.event
    def on_load(self):
        if self.lang not in TEXT:
            self.lang = "zh" if "zh" in (self.router.headers.accept_language or "").lower() else "en"
        if self.speed not in SPEEDS:
            self.speed = "normal"
        if self.length not in LENGTHS:
            self.length = "60"
        if self.foe not in ("hub", "practice"):
            self.foe = "hub"
        if self.total not in TOTALS:
            self.total = "2"
        self._load_board()
        self._seq += 1
        token = self.router.session.client_token
        room = rooms.of(token)
        if room is None and (code := self.router.url.query_parameters.get("r", "")):
            self._join(code.strip().upper(), token)
        elif room is None:
            self.phase, self.code = "lobby", ""
        return [Game.check_opponent, Game.watch]

    def _load_board(self) -> None:
        t = TEXT.get(self.lang, TEXT["zh"])
        self.board = history.board(history.load(), {k: t[k] for k in ("practice", "mode", "mode_people")})

    @rx.event
    def switch_lang(self):
        self.lang = "en" if self.lang == "zh" else "zh"
        self._load_board()

    @rx.event
    def set_name(self, name: str):
        self.name = name.strip()[:16]
        if (room := rooms.of(self.router.session.client_token)) is not None and room.phase == "open":
            room.players[self.router.session.client_token].name = self.name

    def _set(self, **changes: str):
        for key, value in changes.items():
            setattr(self, key, value)
        room = rooms.of(self.router.session.client_token)
        if room is not None and room.host == self.router.session.client_token and room.phase == "open":
            rooms.set_up(room, **{k: (int(v) if k == "total" else v) for k, v in changes.items()})

    @rx.event
    def set_speed(self, speed: str):
        if speed in SPEEDS:
            self._set(speed=speed)

    @rx.event
    def set_length(self, length: str):
        if length in LENGTHS:
            self._set(length=length)

    @rx.event
    def set_foe(self, foe: str):
        if foe in ("hub", "practice"):
            self._set(foe=foe)

    @rx.event
    def set_total(self, total: str):
        if total in TOTALS:
            self._set(total=total)

    @rx.event(background=True)
    async def check_opponent(self):
        async with self:
            self.hub_state = "asking"
        status = await ai.status(brain.ROLE)
        async with self:
            if status is None:
                self.hub_state, self.opponent = "none", ""
            elif status.get("ok"):
                self.hub_state, self.opponent = "ok", str(status.get("model") or "")
                self.opponent_local = bool(status.get("local"))
            else:
                self.hub_state, self.opponent = "error", ""
                self.hub_error = str(status.get("error") or "")

    # ------------------------------------------------------------ rooms

    def _open(self, listed: bool) -> rooms.Room:
        token = self.router.session.client_token
        if (old := rooms.of(token)) is not None:
            rooms.leave(old, token)
        return rooms.open_room(
            token,
            self.name,
            self.lang if self.lang in TEXT else "zh",
            self.foe,
            self.speed,
            self.length,
            int(self.total),
            listed=listed,
            model=self.opponent if self.foe == "hub" else "",
        )

    @rx.event
    def play_alone(self):
        """A room of one that nobody is invited to, played at once."""
        if not self.can_start:
            return
        room = self._open(listed=False)
        self.join_error = ""
        rooms.start(room, warm=self.opponent_local)
        self._mirror(room, room.host)

    @rx.event
    def host_room(self):
        """A room other people can join from the lobby or by its link."""
        if not self.can_start:
            return
        room = self._open(listed=True)
        self.join_error = ""
        rooms.ensure_task(room)
        self._mirror(room, room.host)

    @rx.event
    def join_room(self, code: str):
        self._join(code, self.router.session.client_token)

    def _join(self, code: str, token: str) -> None:
        room = rooms.get(code)
        t = self.t
        if room is None:
            self.join_error = t["no_room"]
        elif room.full:
            self.join_error = t["room_full"]
        elif room.phase != "open":
            self.join_error = t["room_playing"]
        elif rooms.join(room, token, self.name):
            self.join_error = ""
            self.foe, self.speed, self.length = room.foe, room.speed, room.length
            self.total = str(room.total)
            self._mirror(room, token)
            return
        self.phase, self.code = "lobby", ""

    @rx.event
    def start_match(self):
        """The host begins: everyone here takes a seat and AI snakes fill the rest."""
        token = self.router.session.client_token
        room = rooms.of(token)
        if room is None or room.host != token or room.playing:
            return
        rooms.start(room, warm=self.foe == "hub" and self.opponent_local)
        self._mirror(room, token)

    @rx.event
    def leave_room(self):
        """Back to the lobby (a match left halfway isn't yours any more)."""
        token = self.router.session.client_token
        if (room := rooms.of(token)) is not None:
            rooms.leave(room, token)
        self._clear()
        self._load_board()
        self.cards = rooms.listing()
        return Game.check_opponent

    def _clear(self) -> None:
        self.phase, self.code, self.is_host, self.me = "lobby", "", False, ""
        self.room_people, self.room_foe, self.room_speed, self.room_length = [], "", "", ""
        self.frame, self.chips, self.ais, self.said = "", [], [], []
        self.places, self.rep, self.outcome, self.outcome_tone = [], {}, "", ""

    @rx.event
    def key(self, key: str):
        if (way := KEYS.get(key)) and self.phase in ("countdown", "play"):
            token = self.router.session.client_token
            if (room := rooms.of(token)) is not None:
                rooms.turn(room, token, way)

    @rx.event
    def turn(self, way: str):
        if way in KEYS.values():
            return Game.key(way)

    # ------------------------------------------------------------ watching the room

    @rx.event(background=True)
    async def watch(self):
        """Tells the room this tab is still here and copies what it shows."""
        async with self:
            seq, token = self._seq, self.router.session.client_token
        gone_since = None
        cards_at = 0.0
        while True:
            room = rooms.of(token)
            await asyncio.sleep(WATCH_PLAY if room is not None and room.playing else WATCH_IDLE)
            now = time.monotonic()
            if not _watching(token):
                gone_since = gone_since or now
                if now - gone_since > GONE:
                    return  # the room drops the player a few seconds later
                continue
            gone_since = None
            room = rooms.of(token)
            if room is not None:
                rooms.touch(room, token)
            async with self:
                if self._seq != seq:
                    return
                if room is None:
                    if self.phase != "lobby":
                        self._clear()
                        self._load_board()
                    if now - cards_at >= CARDS_EVERY:
                        cards_at = now
                        cards = rooms.listing()
                        if cards != self.cards:
                            self.cards = cards
                else:
                    ended = self.phase != "result" and room.phase == "result"
                    self._mirror(room, token)
                    if ended:
                        self._load_board()

    def _mirror(self, room: rooms.Room, token: str) -> None:
        """Copies the room into this tab's view (only what changed)."""
        phase = "room" if room.phase == "open" else room.phase
        if phase != self.phase:
            self.phase = phase
        if room.id != self.code:
            self.code = room.id
        if (host := room.host == token) != self.is_host:
            self.is_host = host
        people = [Person(p.name, p.token == token, p.token == room.host) for p in room.people]
        if people != self.room_people:
            self.room_people = people
        if room.total != self.room_total:
            self.room_total = room.total
        for key in ("foe", "speed", "length"):
            if getattr(room, key) != getattr(self, f"room_{key}"):
                setattr(self, f"room_{key}", getattr(room, key))
        player = room.players.get(token)
        if (me := player.seat if player else "") != self.me:
            self.me = me
        if room.frame != self.frame:
            self.frame = room.frame
        if room.count != self.count:
            self.count = room.count
        if room.left != self.left:
            self.left = room.left
        if room.model and room.model != self.model:
            self.model = room.model
        if room.chips != self.chips:
            self.chips = room.chips
        if (cards := [self._card(look) for look in room.ais]) != self.ais:
            self.ais = cards
        if room.said != self.said:
            self.said = room.said
        if room.rep != self.rep:
            self.rep = room.rep
        if room.places != self.places:
            self.places = room.places
            self._outcome()

    def _card(self, look: rooms.AiLook) -> AiCard:
        t = self.t
        status = ""
        if look.state == "thinking":
            status = f"{t['st_thinking']} {look.think} {t['sec']}" if look.think else t["st_thinking"]
        elif look.state:
            status = t[f"st_{look.state}"]
        aim = f"{look.aim} · {t['gold'] if look.gold else t['apple']}" if len(look.aim) == 1 else look.aim
        return AiCard(
            id=look.id,
            name=look.name,
            left=look.left,
            state=look.state,
            status=status,
            slow=look.slow,
            aim=aim,
            words=look.words,
            note=look.note,
        )

    def _outcome(self) -> None:
        t = self.t
        mine = next((place for place in self.places if place.id == self.me), None)
        if mine is None or not self.places:
            self.outcome, self.outcome_tone = "", ""
            return
        tied = sum(1 for place in self.places if place.rank == mine.rank) > 1
        self.outcome_tone = "ai" if mine.rank > 1 else "draw" if tied else "you"
        if len(self.places) == 2:
            self.outcome = {"you": t["you_win"], "ai": t["ai_win"], "draw": t["draw"]}[self.outcome_tone]
        elif mine.rank == 1:
            self.outcome = t["crowd_tie"] if tied else t["crowd_first"]
        else:
            self.outcome = t["crowd_place"].format(n=mine.rank)
