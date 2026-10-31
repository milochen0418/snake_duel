"""One browser tab: who is here, the lobby, the room they are in, the match and the result.

The match itself belongs to the room (:mod:`snake_duel.rooms`), which every tab in it shares.
This state only looks: one background task (``Game.watch``) copies the board and the scores into
this tab's own view, and keeps the lobby's list of rooms fresh. Keys go straight into the
person's turns.

The page says it is still there with a heartbeat (``Game.beat``, every 1.5 s, see
``assets/snake_duel/arena.js``). That is what keeps someone's seat, and what brings the watcher
back after a lost connection: Reflex rehydrates a tab that reconnects, but doesn't load the page
again, so nothing else would start it.

Who someone is comes from the platform's login (``AuthState``, by e-mail, so all of a person's
tabs are one person), else they are a guest of this tab (``guest``, which survives a reload and
a reconnect, even one that gives the tab a new Reflex token).

An invite link (``/r/<code>``, which lands on ``/?r=<code>``) always works: someone arriving in
the middle of a match watches, and someone in the middle of their own match is asked first.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import secrets
import time
from typing import Any
from urllib.parse import quote, urlsplit

import reflex as rx
from reflex_ddns_auth import AuthState, ai
from reflex_ddns_auth.state import RELACK_URL

from snake_duel import brain, call, history, rooms
from snake_duel.i18n import TEXT
from snake_duel.match import LENGTHS, NAME_LEN, SPEEDS, TOTALS, Decision
from snake_duel.rooms import Card, Chip, Place

WATCH_IDLE = 0.3  # seconds between looks at a room that isn't playing (a match wakes it each tick)
CARDS_EVERY = 1.5  # seconds between refreshes of the lists of rooms and of people online
BEAT_GONE = 10.0  # seconds without a heartbeat before this tab's watcher stops
WATCHER_LOST = 2.0  # seconds without a look before a heartbeat starts a new watcher
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


def _address(path: str) -> rx.event.EventSpec:
    """Puts ``path`` in the address bar, so that a reload or a copied address does the right thing."""
    return rx.call_script(f"window.history.replaceState(null, '', {json.dumps(path)})")


@dataclasses.dataclass
class Person:
    """Someone in the room, as the page lists them."""

    name: str
    avatar: str
    me: bool
    host: bool
    away: bool  # their page has gone quiet
    seat: str  # their snake, "" when they watch


@dataclasses.dataclass
class Friend:
    """Someone with the game open who is not in this room."""

    key: str
    name: str
    avatar: str
    busy: bool  # in the middle of a match
    invited: bool  # already asked


@dataclasses.dataclass
class AiCard:
    """An AI snake as this tab shows it during a match."""

    id: str
    name: str
    left: bool  # a person's snake an AI is playing
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
    guest: str = rx.SessionStorage("", name="snake_duel_guest")  # who this tab is, not signed in

    # the lobby
    hub_state: str = "asking"  # asking, ok, none (no hub) or error
    hub_error: str = ""
    opponent: str = ""  # what answers, e.g. "Ollama (qwen2.5:7b)"
    opponent_local: bool = False
    board: list[history.ModelRow] = []
    cards: list[Card] = []  # the rooms on offer
    notice_key: str = ""  # one line at the top of the page: a word of TEXT
    invite_code: str = ""  # the invitation on this screen
    invite_from: str = ""

    # the room
    phase: str = "lobby"  # lobby, room, warmup, countdown, play or result
    code: str = ""
    lead: bool = False  # this person may start the match and set it up
    room_people: list[Person] = []
    room_total: int = 2
    room_foe: str = ""
    room_speed: str = ""
    room_length: str = ""
    friends: list[Friend] = []  # people online who could be invited
    call_count: int = 0
    call_from: str = ""  # who is ringing this person

    # the match
    me: str = ""  # which snake is this tab's ("": it watches)
    frame: str = ""  # the arena, as JSON for the canvas
    faces: str = "{}"  # each person's picture by seat, as JSON for the canvas
    count: int = 0
    left: int = 0
    model: str = ""
    chips: list[Chip] = []
    ais: list[AiCard] = []
    said: list[Decision] = []

    # the result
    places: list[Place] = []
    rep: dict[str, str] = {}

    _uid: str = ""  # who this is, to the rooms
    _my_name: str = ""
    _my_avatar: str = ""
    _seq: int = 0  # a new number for every watcher: an older one sees it and stops
    _beat_at: float = 0.0
    _watched_at: float = 0.0

    # ------------------------------------------------------------ words

    @rx.var
    def t(self) -> dict[str, str]:
        return TEXT.get(self.lang, TEXT["zh"])

    @rx.var
    def can_start(self) -> bool:
        return self.foe == "practice" or self.hub_state == "ok"

    @rx.var
    def notice(self) -> str:
        return self.t.get(self.notice_key, "")

    @rx.var
    def invite_text(self) -> str:
        return self.t["invited_by"].format(name=self.invite_from, code=self.invite_code) if self.invite_code else ""

    @rx.var
    def mid_match(self) -> bool:
        """This person has a snake in a match going on."""
        return self.phase in ("warmup", "countdown", "play") and bool(self.me)

    @rx.var
    def watching(self) -> bool:
        """This tab has no snake in the match on."""
        return self.phase in ("warmup", "countdown", "play") and not self.me

    @rx.var
    def my_score(self) -> int:
        return next((chip.score for chip in self.chips if chip.id == self.me), 0)

    @rx.var
    def my_out(self) -> str:
        return next((chip.out for chip in self.chips if chip.id == self.me), "")

    @rx.var
    def others(self) -> list[Chip]:
        """Every snake but this tab's, for the scoreboard."""
        return [chip for chip in self.chips if chip.id != self.me]

    @rx.var
    def shown_total(self) -> str:
        return str(self.room_total) if self.phase == "room" else self.total

    @rx.var
    def shown_speed(self) -> str:
        return self.room_speed if self.phase == "room" else self.speed

    @rx.var
    def shown_length(self) -> str:
        return self.room_length if self.phase == "room" else self.length

    @rx.var
    def total_note(self) -> str:
        """How the seats are filled, as the lobby or the room has them now."""
        t = self.t
        if self.phase == "room":
            people = sum(1 for person in self.room_people if not person.away)
            ais = self.room_total - people
            if ais < 0:
                return t["total_note_over"].format(people=people, n=-ais)
            return (t["total_note_full"] if ais == 0 else t["total_note_room"]).format(people=people, ais=ais)
        ais = int(self.total) - 1 if self.total in TOTALS else 1
        return t["total_note_solo"].format(n=ais)

    @rx.var
    def foe_name(self) -> str:
        if not self.ais and self.phase != "room":
            return ""
        return self.t["practice"] if (self.room_foe or self.foe) == "practice" else (self.model or self.opponent)

    @rx.var
    def outcome(self) -> str:
        """The final word, as this person reads it."""
        word, values, _ = rooms.verdict(self.places, self.me)
        return self.t[word].format(**values) if word else ""

    @rx.var
    def outcome_tone(self) -> str:
        return rooms.verdict(self.places, self.me)[2]

    @rx.var
    def share_link(self) -> str:
        """The address to give to someone. ``/r/<code>`` answers with a preview card on re-ddns,
        which sends that path to the backend; run on its own, only the page itself is there."""
        if not self.code:
            return ""
        origin = self.router.headers.origin or ""
        host = urlsplit(origin).hostname or ""
        if "." not in host or host.replace(".", "").isdigit():
            return f"{origin}/?r={self.code}"
        return f"{origin}/r/{self.code}"

    @rx.var
    def login_link(self) -> str:
        """Sign in and come back to this very room (``AuthState.login_url`` comes back to the
        top of the site, and the invitation would be lost)."""
        origin = self.router.headers.origin or ""
        back = f"{origin}/?r={self.code}" if self.code else f"{origin}/"
        return f"{RELACK_URL}/auth/google/login?redirect={quote(back, safe='')}"

    @rx.var
    def hub_page(self) -> str:
        """The AI Hub's page, next to this app on the same domain ("" when run on its own)."""
        parts = urlsplit(self.router.headers.origin or "")
        host = parts.hostname or ""
        if "." not in host or host.replace(".", "").isdigit():
            return ""
        return f"{parts.scheme}://ai.{host.split('.', 1)[1]}"

    # ------------------------------------------------------------ who is here

    async def _identify(self) -> None:
        """Who this tab is: the signed-in account, else a guest of this tab."""
        auth = await self.get_state(AuthState)
        if not auth._auth_loaded:
            await auth.load_auth()
        if auth.is_logged_in:
            uid, name, avatar = auth.user_email, auth.user_name or auth.user_email, auth.user_avatar
        else:
            if not self.guest:
                self.guest = secrets.token_hex(6)
            uid, name, avatar = f"guest-{self.guest}", self.name or self._guest_name(), ""
        old, self._uid, self._my_name, self._my_avatar = self._uid, uid, name, avatar
        if old and old != uid:
            rooms.rename(old, uid, name, avatar)
        elif (room := rooms.of(uid)) is not None:
            rooms.enter(room, uid, name, avatar)

    def _guest_name(self) -> str:
        return TEXT.get(self.lang, TEXT["zh"])["guest"].format(n=int(self.guest[:4], 16) % 90 + 10)

    # ------------------------------------------------------------ the lobby

    @rx.event
    async def on_load(self):
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
        await self._identify()
        self._load_board()
        self.notice_key = ""
        self._seq += 1
        self._beat_at = self._watched_at = time.time()
        events: list[Any] = [Game.check_opponent, Game.watch]
        uid = self._uid
        here = rooms.of(uid)
        code = self.router.url.query_parameters.get("r", "").strip().upper()
        wanted = rooms.get(code) if code else None
        if code and wanted is None:
            # The room is over. Whoever is somewhere else stays there.
            self.notice_key = "no_room"
            events.append(_address(f"/?r={here.id}" if here is not None else "/"))
        elif wanted is not None and wanted is not here:
            if here is not None and here.playing and here.players[uid].seat:
                rooms.ask_first(wanted, uid)  # they choose: they are in the middle of a match
                events.append(_address(f"/?r={here.id}"))
            else:
                self._go_to(code)
        if (room := rooms.of(uid)) is not None:
            self._mirror(room)
        else:
            self._clear()
        return events

    def _load_board(self) -> None:
        t = TEXT.get(self.lang, TEXT["zh"])
        self.board = history.board(history.load(), {k: t[k] for k in ("practice", "people_only", "mode", "mode_people")})

    @rx.event
    def switch_lang(self):
        self.lang = "en" if self.lang == "zh" else "zh"
        self._load_board()

    @rx.event
    def set_name(self, name: str):
        """A guest's name (someone signed in goes by their account)."""
        if self._uid and not self._uid.startswith("guest-"):
            return
        self.name = name.strip()[:NAME_LEN]
        self._my_name = self.name or (self._guest_name() if self.guest else "")
        if (room := rooms.of(self._uid)) is not None:
            rooms.enter(room, self._uid, self._my_name, self._my_avatar)

    def _in_my_room(self) -> rooms.Room | None:
        """The room this person sets up, when they do."""
        room = rooms.of(self._uid)
        return room if room is not None and room.phase == "open" and rooms.can_lead(room, self._uid) else None

    @rx.event
    def set_speed(self, speed: str):
        if speed in SPEEDS:
            if (room := self._in_my_room()) is not None:
                rooms.set_up(room, speed=speed)
                self._mirror(room)
            else:
                self.speed = speed

    @rx.event
    def set_length(self, length: str):
        if length in LENGTHS:
            if (room := self._in_my_room()) is not None:
                rooms.set_up(room, length=length)
                self._mirror(room)
            else:
                self.length = length

    @rx.event
    def set_total(self, total: str):
        if total in TOTALS:
            if (room := self._in_my_room()) is not None:
                rooms.set_up(room, total=int(total))
                self._mirror(room)
            else:
                self.total = total

    @rx.event
    def set_foe(self, foe: str):
        if foe in ("hub", "practice"):
            self.foe = foe

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
        if (old := rooms.of(self._uid)) is not None:
            rooms.leave(old, self._uid)
        return rooms.open_room(
            self._uid,
            self._my_name,
            self._my_avatar,
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
        """A room of one that isn't listed, played at once (its link can still be shared)."""
        if not self.can_start or not self._uid:
            return
        room = self._open(listed=False)
        self.notice_key = ""
        rooms.start(room, warm=self.opponent_local)
        self._mirror(room)
        return _address(f"/?r={room.id}")

    @rx.event
    def host_room(self):
        """A room other people can join from the lobby or by its link."""
        if not self.can_start or not self._uid:
            return
        room = self._open(listed=True)
        self.notice_key = ""
        rooms.ensure_task(room)
        self._mirror(room)
        return _address(f"/?r={room.id}")

    def _go_to(self, code: str):
        """Moves this person to a room by its code, from wherever they are (and leaves them
        there when the room can't be had)."""
        room = rooms.get(code)
        here = rooms.of(self._uid)
        if room is None:
            self.notice_key = "no_room"
            return None
        if room is here:
            return None
        if not rooms.enter(room, self._uid, self._my_name, self._my_avatar):
            self.notice_key = "room_full"
            return None
        if here is not None:
            rooms.leave(here, self._uid)
        rooms.ensure_task(room)
        self.notice_key = ""
        self._mirror(room)
        return _address(f"/?r={room.id}")

    @rx.event
    def join_room(self, code: str):
        return self._go_to(code)

    @rx.event
    def join_code(self, form: dict[str, Any]):
        return self._go_to(str(form.get("code") or ""))

    @rx.event
    def accept_invite(self):
        code, self.invite_code, self.invite_from = self.invite_code, "", ""
        rooms.decline(self._uid)
        return self._go_to(code)

    @rx.event
    def decline_invite(self):
        self.invite_code, self.invite_from = "", ""
        rooms.decline(self._uid)

    @rx.event
    def invite_person(self, key: str):
        if (room := rooms.of(self._uid)) is not None:
            rooms.invite(room, self._uid, key)
            self._list_friends(room)

    @rx.event
    def take_seat(self, sid: str):
        """Someone watching takes a snake from an AI."""
        if (room := rooms.of(self._uid)) is not None and rooms.take_over(room, self._uid, sid):
            self._mirror(room)

    @rx.event
    def start_match(self):
        """Everyone here takes a seat and AI snakes fill the rest."""
        room = rooms.of(self._uid)
        if room is None or room.playing or not rooms.can_lead(room, self._uid):
            return
        rooms.start(room, warm=self.opponent_local)
        self._mirror(room)

    @rx.event
    def leave_room(self):
        """Back to the lobby (mid-match an AI plays on for them)."""
        if (room := rooms.of(self._uid)) is not None:
            rooms.leave(room, self._uid)
        self._clear()
        self._load_board()
        self.cards = rooms.listing()
        return [Game.check_opponent, _address("/")]

    def _clear(self) -> None:
        self.phase, self.code, self.lead, self.me = "lobby", "", False, ""
        self.room_people, self.friends, self.room_foe, self.room_speed, self.room_length = [], [], "", "", ""
        self.frame, self.faces, self.chips, self.ais, self.said = "", "{}", [], [], []
        self.places, self.rep, self.model, self.call_count, self.call_from = [], {}, "", 0, ""

    @rx.event
    def key(self, key: str):
        if (way := KEYS.get(key)) and (room := rooms.of(self._uid)) is not None:
            rooms.turn(room, self._uid, way)

    # ------------------------------------------------------------ the page is still there

    @rx.event
    async def beat(self):
        now = time.time()
        self._beat_at = now
        if not self._uid:  # a reconnect that came back as a new tab to the server
            await self._identify()
        room = rooms.of(self._uid)
        rooms.seen_online(self._uid, self._my_name, self._my_avatar, room is not None and room.playing)
        if room is not None:
            rooms.touch(room, self._uid)
        if now - self._watched_at > WATCHER_LOST:
            self._seq += 1
            self._watched_at = now
            return Game.watch

    @rx.event(background=True)
    async def watch(self):
        """Copies what this tab's room shows, and keeps the lobby's lists fresh."""
        async with self:
            seq = self._seq
            uid = self._uid
        listed_at = 0.0
        while True:
            room = rooms.of(uid)
            if room is not None and room.playing:
                try:
                    await asyncio.wait_for(room.changed.wait(), WATCH_IDLE)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(WATCH_IDLE)
            now = time.time()
            async with self:
                if self._seq != seq:
                    return
                if now - self._beat_at > BEAT_GONE:
                    self._watched_at = 0.0
                    return  # the page has gone quiet; its next heartbeat starts a new watcher
                self._watched_at = now
                uid = self._uid
                room = rooms.of(uid)
                lists = now - listed_at >= CARDS_EVERY
                if lists:
                    listed_at = now
                if room is None:
                    if self.phase != "lobby":
                        self._clear()
                        self._load_board()
                        self.notice_key = "room_gone"
                    if lists and (cards := rooms.listing()) != self.cards:
                        self.cards = cards
                else:
                    ended = self.phase != "result" and room.phase == "result"
                    self._mirror(room)
                    if ended:
                        self._load_board()
                    if lists:
                        self._list_friends(room)
                invite = rooms.invitation(uid)
                code, by = (invite.code, invite.by) if invite is not None else ("", "")
                if code != self.invite_code:
                    self.invite_code, self.invite_from = code, by

    def _list_friends(self, room: rooms.Room) -> None:
        friends = [Friend(who.key, who.name, who.avatar, who.busy, rooms.invited(room, who.uid)) for who in rooms.others_online(room)]
        if friends != self.friends:
            self.friends = friends

    def _mirror(self, room: rooms.Room) -> None:
        """Copies the room into this tab's view (only what changed)."""
        uid, now = self._uid, time.monotonic()
        phase = "room" if room.phase == "open" else room.phase
        if phase != self.phase:
            self.phase = phase
        if room.id != self.code:
            self.code = room.id
        if (lead := rooms.can_lead(room, uid)) != self.lead:
            self.lead = lead
        seats_on = room.match is not None and phase != "room"
        people = [Person(p.name, p.avatar, p.uid == uid, p.uid == room.host, not p.here(now), p.seat if seats_on else "") for p in room.people]
        if people != self.room_people:
            self.room_people = people
        if room.total != self.room_total:
            self.room_total = room.total
        for key in ("foe", "speed", "length"):
            if getattr(room, key) != getattr(self, f"room_{key}"):
                setattr(self, f"room_{key}", getattr(room, key))
        player = room.players.get(uid)
        if (me := player.seat if player and seats_on else "") != self.me:
            self.me = me
        if room.frame != self.frame:
            self.frame = room.frame
        if room.faces != self.faces:
            self.faces = room.faces
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
        if room.notice:
            self.notice_key = room.notice
        elif self.notice_key == "called_off":
            self.notice_key = ""
        count, ringing = call.view(room.id, uid)
        if count != self.call_count:
            self.call_count = count
        if ringing != self.call_from:
            self.call_from = ringing

    def _card(self, look: rooms.AiLook) -> AiCard:
        t = self.t
        status = ""
        if look.state == "thinking":
            status = f"{t['st_thinking']} {look.think} {t['sec']}" if look.think else t["st_thinking"]
        elif look.state:
            status = t[f"st_{look.state}"]
        aim = f"{look.aim} · {t['gold'] if look.gold else t['apple']}" if len(look.aim) == 1 else look.aim
        return AiCard(look.id, look.name, look.left, look.state, status, look.slow, aim, look.words, look.note)
