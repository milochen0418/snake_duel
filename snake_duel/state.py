"""A duel or a free-for-all, per browser tab: the lobby, the countdown, the match and the result.

A match is one background task (``Game.run_match``) that owns a :class:`match.Match`: every tick
it moves all snakes (the person's turns from ``_turns``, each AI snake's from its plan), puts the
arena on the page as JSON for the canvas (``frame``), and starts an ask for each AI snake whenever
the match says so, without waiting for it. Leaving, a new match or a tab that has gone away for
good bump or end ``_seq``, and the task stops (cancelling the asks, which stops the model).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import time
from urllib.parse import urlsplit

import reflex as rx
from reflex_ddns_auth import ai

from snake_duel import brain, history
from snake_duel.i18n import TEXT
from snake_duel.match import CROWDS, LENGTHS, PRACTICE_SECS, SLOW, SPEEDS, Asked, Decision, Match, Seat

COUNTDOWN = 3
ASK_TIMEOUT = 60.0  # an answer this late is about a board long gone
WARMUP_TIMEOUT = 90.0
STALE = 6.0  # seconds without the tab before a match is called off
LOG_ROWS = 6
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


def _watching(token: str) -> bool:
    """Whether the tab that plays is still connected (True when it can't be told)."""
    try:
        from reflex.utils import prerequisites

        return token in prerequisites.get_app().app.event_namespace.token_to_sid
    except Exception:  # noqa: BLE001
        return True


@dataclasses.dataclass
class AiCard:
    """An AI snake as the page shows it during a match."""

    id: str
    name: str
    score: int = 0
    state: str = ""  # thinking, plan, idle or out
    status: str = ""  # the state in words, with the seconds it has been thinking
    slow: bool = False  # it has been thinking long enough to say why
    aim: str = ""
    words: str = ""
    note: str = ""


@dataclasses.dataclass
class Place:
    """A snake's line in the result."""

    rank: int
    id: str
    name: str
    score: int
    apples: int
    golds: int
    crashes: int
    asks: str  # "" for the person
    secs: str


class Game(rx.State):
    lang: str = rx.LocalStorage("", name="snake_duel_lang")
    speed: str = rx.LocalStorage("normal", name="snake_duel_speed")
    length: str = rx.LocalStorage("60", name="snake_duel_length")
    foe: str = rx.LocalStorage("hub", name="snake_duel_foe")  # hub or practice
    mode: str = rx.LocalStorage("duel", name="snake_duel_mode")  # duel or crowd
    crowd: str = rx.LocalStorage("3", name="snake_duel_crowd")  # AI snakes in a free-for-all

    # the lobby
    hub_state: str = "asking"  # asking, ok, none (no hub) or error
    hub_error: str = ""
    opponent: str = ""  # what answers, e.g. "Ollama (qwen2.5:7b)"
    opponent_local: bool = False
    board: list[history.ModelRow] = []

    # the match
    phase: str = "lobby"  # lobby, warmup, countdown, play or result
    playing_crowd: bool = False  # this match is a free-for-all
    frame: str = ""  # the arena, as JSON for the canvas
    count: int = 0
    left: int = 0
    my_score: int = 0
    my_out: str = ""  # seconds until the person's snake is back, after a crash
    model: str = ""
    ais: list[AiCard] = []
    said: list[Decision] = []

    # the result
    places: list[Place] = []
    outcome: str = ""
    outcome_tone: str = ""  # you, ai or draw
    rep: dict[str, str] = {}

    _seq: int = 0  # a new number for every match: an older task sees it and stops
    _turns: list[str] = []
    _beat: float = 0.0

    # ------------------------------------------------------------ words

    @rx.var
    def t(self) -> dict[str, str]:
        return TEXT.get(self.lang, TEXT["zh"])

    @rx.var
    def can_start(self) -> bool:
        return self.foe == "practice" or self.hub_state == "ok"

    @rx.var
    def foe_name(self) -> str:
        return self.t["practice"] if self.foe == "practice" else (self.model or self.opponent)

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
        if self.mode not in ("duel", "crowd"):
            self.mode = "duel"
        if self.crowd not in CROWDS:
            self.crowd = "3"
        # A restart of the server (a hot reload) ends the task that ran the match.
        if self.phase in ("warmup", "countdown", "play") and time.time() - self._beat > STALE:
            self._seq += 1
            self.phase = "lobby"
        self._load_board()
        if self.phase in ("lobby", "result"):
            return Game.check_opponent

    def _load_board(self) -> None:
        t = TEXT.get(self.lang, TEXT["zh"])
        self.board = history.board(history.load(), {"practice": t["practice"], "mode_duel": t["mode_duel_short"], "mode_crowd": t["mode_crowd_short"]})

    @rx.event
    def switch_lang(self):
        self.lang = "en" if self.lang == "zh" else "zh"
        self._load_board()

    @rx.event
    def set_speed(self, speed: str):
        if speed in SPEEDS:
            self.speed = speed

    @rx.event
    def set_length(self, length: str):
        if length in LENGTHS:
            self.length = length

    @rx.event
    def set_foe(self, foe: str):
        if foe in ("hub", "practice"):
            self.foe = foe

    @rx.event
    def set_mode(self, mode: str):
        if mode in ("duel", "crowd"):
            self.mode = mode

    @rx.event
    def set_crowd(self, crowd: str):
        if crowd in CROWDS:
            self.crowd = crowd

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

    # ------------------------------------------------------------ a match

    @rx.event
    def start(self):
        if self.phase not in ("lobby", "result") or not self.can_start:
            return
        ais = int(self.crowd) if self.mode == "crowd" else 1
        self._seq += 1
        self._turns, self._beat = [], time.time()
        self.count, self.left, self.my_score, self.my_out = COUNTDOWN, int(self.length), 0, ""
        self.model = self.opponent if self.foe == "hub" else ""
        self.playing_crowd = ais > 1
        self.ais = [AiCard(id=f"ai{i}", name=brain.ai_name(f"ai{i}", ais)) for i in range(1, ais + 1)]
        self.said, self.places, self.rep, self.outcome, self.outcome_tone = [], [], {}, "", ""
        self.phase = "warmup" if self.foe == "hub" and self.opponent_local else "countdown"
        return Game.run_match

    @rx.event
    def key(self, key: str):
        if way := KEYS.get(key):
            self._turn(way)

    @rx.event
    def turn(self, way: str):
        self._turn(way)

    def _turn(self, way: str) -> None:
        if self.phase not in ("countdown", "play") or way not in KEYS.values():
            return
        if not self._turns or self._turns[-1] != way:
            self._turns = [*self._turns, way][-3:]

    @rx.event(background=True)
    async def run_match(self):
        async with self:
            if self.phase not in ("warmup", "countdown"):
                return
            seq, token = self._seq, self.router.session.client_token
            seconds = int(self.length)
            game = Match(self.foe, self.lang if self.lang in TEXT else "zh", self.speed, seconds, ais=len(self.ais), model=self.model)
            self.frame = json.dumps(game.frame(), separators=(",", ":"))
            warm = self.phase == "warmup"
            if warm:  # a reload while the model loads is no sign the task has gone
                self._beat = time.time() + WARMUP_TIMEOUT
        if warm:
            # Loads a local model before the countdown, so its loading isn't counted as thinking.
            try:
                await asyncio.wait_for(ai.complete(brain.ROLE, "Reply with OK.", [{"role": "user", "content": "OK?"}], max_tokens=1), WARMUP_TIMEOUT)
            except Exception:  # noqa: BLE001 - the first ask will say what is wrong
                pass
            async with self:
                if self._seq != seq:
                    return
                self.phase, self._beat = "countdown", time.time()
        tick = game.world.tick_ms / 1000
        go_at = time.monotonic() + COUNTDOWN
        next_at = go_at
        away = None
        asking: dict[str, asyncio.Task[Asked]] = {}
        try:
            while True:
                now = time.monotonic()
                if now < go_at:
                    await asyncio.sleep(min(0.1, go_at - now))
                else:
                    next_at += tick
                    if (wait := next_at - time.monotonic()) > 0:
                        await asyncio.sleep(wait)
                    else:
                        next_at = time.monotonic()  # fell behind: go on from now, don't rush
                now = time.monotonic()
                away = None if _watching(token) else (away or now)
                async with self:
                    if self._seq != seq:
                        return
                    if away is not None and now - away > STALE:
                        self._seq += 1
                        self.phase = "lobby"
                        return
                    self._beat = time.time()
                    for sid, task in list(asking.items()):
                        if task.done():
                            self._take(game, sid, task.result(), now)
                            del asking[sid]
                    if self.phase == "countdown":
                        if now >= go_at:
                            self.phase, self.count = "play", 0
                        elif (count := math.ceil(go_at - now)) != self.count:
                            self.count = count
                    if self.phase == "play":
                        turns = list(self._turns)
                        game.step(turns)
                        self._turns = turns
                        self.frame = json.dumps(game.frame(), separators=(",", ":"))
                        if game.world.over:
                            self._finish(game, seconds)
                            return
                    self._show(game, now)
                    for sid in game.seats:
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

    def _take(self, game: Match, sid: str, asked: Asked, now: float) -> None:
        decision = game.take(sid, asked, now)
        if game.model:
            self.model = game.model
        self.said = [decision, *self.said][:LOG_ROWS]

    def _show(self, game: Match, now: float) -> None:
        """The scores, the clock and what each AI snake is doing, where they changed."""
        world = game.world
        you = world.snakes["you"]
        if (left := math.ceil(world.left)) != self.left:
            self.left = left
        if you.score != self.my_score:
            self.my_score = you.score
        out = "" if you.alive else f"{max(0.0, world.seconds(you.back_at - world.tick)):.1f}"
        if out != self.my_out:
            self.my_out = out
        cards = [self._card(game, seat, now) for seat in game.seats.values()]
        if cards != self.ais:
            self.ais = cards

    def _card(self, game: Match, seat: Seat, now: float) -> AiCard:
        t = self.t
        snake = game.world.snakes[seat.id]
        state = "out" if not snake.alive else "thinking" if seat.asking else "plan" if seat.aim else "idle"
        think = int(game.thinking(seat.id, now))
        status = f"{t['st_thinking']} {think} {t['sec']}" if state == "thinking" and think else t[f"st_{state}"]
        aim = ""
        if seat.aim and seat.plan:
            first = seat.plan[0]
            if first.label and (food := game.world.food(first.label)):
                aim = f"{food.label} · {t['gold'] if food.kind == 'gold' else t['apple']}"
            else:
                aim = f"({seat.aim[0]},{seat.aim[1]})"
        return AiCard(
            id=seat.id,
            name=seat.name,
            score=snake.score,
            state=state,
            status=status,
            slow=state == "thinking" and think >= SLOW,
            aim=aim,
            words=seat.words,
            note=seat.note,
        )

    def _finish(self, game: Match, seconds: int) -> None:
        summary = game.summary(seconds)
        history.save(summary)
        t = self.t
        lines = [("you", t["you"], summary["you"], "", "")]
        for seat, side in zip(game.seats.values(), summary["ais"]):
            secs = side["ask_secs"]
            lines.append((seat.id, seat.name, side, str(side["asks"]), f"{secs:.1f}" if secs is not None else "–"))
        lines.sort(key=lambda line: -line[2]["score"])
        places, rank, last = [], 0, None
        for i, (sid, name, side, asks, secs) in enumerate(lines):
            if side["score"] != last:
                rank, last = i + 1, side["score"]
            places.append(Place(rank, sid, name, side["score"], side["apples"], side["golds"], side["crashes"], asks, secs))
        self.places = places
        mine = next(p for p in places if p.id == "you")
        tied = sum(1 for p in places if p.rank == mine.rank) > 1
        self.outcome_tone = "ai" if mine.rank > 1 else "draw" if tied else "you"
        if not game.crowd:
            self.outcome = {"you": t["you_win"], "ai": t["ai_win"], "draw": t["draw"]}[self.outcome_tone]
        elif mine.rank == 1:
            self.outcome = t["crowd_tie"] if tied else t["crowd_first"]
        else:
            self.outcome = t["crowd_place"].format(n=mine.rank)
        self.my_score, self.left = summary["you"]["score"], 0
        secs = summary["ask_secs"]
        self.rep = {
            "asks": str(summary["asks"]),
            "secs": f"{secs:.1f}" if secs is not None else "–",
            "failed": str(summary["failed"]),
            "bad": str(summary["bad"]),
        }
        self.ais = [AiCard(id=seat.id, name=seat.name, score=side["score"], words=seat.words) for seat, side in zip(game.seats.values(), summary["ais"])]
        self.phase = "result"
        self._load_board()

    @rx.event
    def leave(self):
        """Back to the lobby (a match left halfway isn't kept)."""
        self._seq += 1
        self.phase = "lobby"
        self._load_board()
        return Game.check_opponent
