"""A duel, per browser tab: the lobby, the countdown, the match and the result.

A match is one background task (``Game.run_match``) that owns a :class:`match.Match`: every tick
it moves both snakes (the person's turns from ``_turns``, the AI's from its plan), puts the arena
on the page as JSON for the canvas (``frame``), and starts an ask whenever the match says so,
without waiting for it. Leaving, a new match or a tab that has gone away for good bump or end
``_seq``, and the task stops (cancelling the ask, which stops the model).
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from urllib.parse import urlsplit

import reflex as rx
from reflex_ddns_auth import ai

from snake_duel import brain, history
from snake_duel.i18n import TEXT
from snake_duel.match import LENGTHS, PRACTICE_SECS, SLOW, SPEEDS, Asked, Decision, Match

COUNTDOWN = 3
ASK_TIMEOUT = 60.0  # an answer this late is about a board long gone
WARMUP_TIMEOUT = 90.0
STALE = 6.0  # seconds without the tab before a match is called off
LOG_ROWS = 5
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


class Game(rx.State):
    lang: str = rx.LocalStorage("", name="snake_duel_lang")
    speed: str = rx.LocalStorage("normal", name="snake_duel_speed")
    length: str = rx.LocalStorage("60", name="snake_duel_length")
    foe: str = rx.LocalStorage("hub", name="snake_duel_foe")  # hub or practice

    # the lobby
    hub_state: str = "asking"  # asking, ok, none (no hub) or error
    hub_error: str = ""
    opponent: str = ""  # what answers, e.g. "Ollama (qwen2.5:7b)"
    opponent_local: bool = False
    board: list[history.ModelRow] = []

    # the match
    phase: str = "lobby"  # lobby, warmup, countdown, play or result
    frame: str = ""  # the arena, as JSON for the canvas
    count: int = 0
    left: int = 0
    my_score: int = 0
    ai_score: int = 0
    my_out: str = ""  # seconds until the person's snake is back, after a crash
    model: str = ""
    ai_state: str = ""  # thinking, plan, idle or out
    ai_think: int = 0  # seconds the ask that is out has taken
    ai_aim: str = ""
    ai_words: str = ""
    ai_note: str = ""
    said: list[Decision] = []

    # the result
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
    def ai_status(self) -> str:
        t = self.t
        if self.ai_state == "thinking":
            return f"{t['ai_thinking']} {self.ai_think} {t['sec']}" if self.ai_think else t["ai_thinking"]
        return t.get(f"ai_{self.ai_state}", "")

    @rx.var
    def ai_slow(self) -> bool:
        return self.ai_state == "thinking" and self.ai_think >= SLOW

    @rx.var
    def winner(self) -> str:
        return "you" if self.my_score > self.ai_score else "ai" if self.ai_score > self.my_score else "draw"

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
        # A restart of the server (a hot reload) ends the task that ran the match.
        if self.phase in ("warmup", "countdown", "play") and time.time() - self._beat > STALE:
            self._seq += 1
            self.phase = "lobby"
        self._load_board()
        if self.phase in ("lobby", "result"):
            return Game.check_opponent

    def _load_board(self) -> None:
        self.board = history.board(history.load(), TEXT.get(self.lang, TEXT["zh"])["practice"])

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
        self._seq += 1
        self._turns, self._beat = [], time.time()
        self.count, self.left, self.my_score, self.ai_score, self.my_out = COUNTDOWN, int(self.length), 0, 0, ""
        self.model = self.opponent if self.foe == "hub" else ""
        self.ai_state, self.ai_think, self.ai_aim, self.ai_words, self.ai_note = "", 0, "", "", ""
        self.said, self.rep = [], {}
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
            game = Match(self.foe, self.lang if self.lang in TEXT else "zh", self.speed, int(self.length))
            seconds = int(self.length)
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
        asking: asyncio.Task[Asked] | None = None
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
                    if asking is not None and asking.done():
                        self._take(game, asking.result(), now)
                        asking = None
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
                    if asking is None and game.due(now):
                        question = game.ask(now)
                        if isinstance(question, list):
                            asking = asyncio.create_task(_practice(question, now))
                        else:
                            asking = asyncio.create_task(_ask(*question, now, game.lang))
        finally:
            if asking is not None and not asking.done():
                asking.cancel()  # ends the hub's request, so the model stops too

    def _take(self, game: Match, asked: Asked, now: float) -> None:
        decision = game.take(asked, now)
        if game.model:
            self.model = game.model
        self.said = [decision, *self.said][:LOG_ROWS]
        if game.words != self.ai_words:
            self.ai_words = game.words
        self.ai_note = game.note

    def _show(self, game: Match, now: float) -> None:
        """The scores, the clock and what the AI is doing, where they changed."""
        world = game.world
        you, them = world.snakes["you"], world.snakes["ai"]
        if (left := math.ceil(world.left)) != self.left:
            self.left = left
        if you.score != self.my_score:
            self.my_score = you.score
        if them.score != self.ai_score:
            self.ai_score = them.score
        out = "" if you.alive else f"{max(0.0, world.seconds(you.back_at - world.tick)):.1f}"
        if out != self.my_out:
            self.my_out = out
        state = "out" if not them.alive else "thinking" if game.asking else "plan" if game.aim else "idle"
        if state != self.ai_state:
            self.ai_state = state
        if (think := int(game.thinking(now))) != self.ai_think:
            self.ai_think = think
        aim = self._aim_words(game)
        if aim != self.ai_aim:
            self.ai_aim = aim

    def _aim_words(self, game: Match) -> str:
        if not game.aim or not game.plan:
            return ""
        first = game.plan[0]
        t = self.t
        if first.label and (food := game.world.food(first.label)):
            return f"{food.label} · {t['gold'] if food.kind == 'gold' else t['apple']}"
        return f"({game.aim[0]},{game.aim[1]})"

    def _finish(self, game: Match, seconds: int) -> None:
        summary = game.summary(seconds)
        history.save(summary)
        you, them = summary["you"], summary["ai"]
        self.my_score, self.ai_score = you["score"], them["score"]
        self.left = 0
        secs = summary["ask_secs"]
        self.rep = {
            "you_apples": str(you["apples"]),
            "you_golds": str(you["golds"]),
            "you_crashes": str(you["crashes"]),
            "ai_apples": str(them["apples"]),
            "ai_golds": str(them["golds"]),
            "ai_crashes": str(them["crashes"]),
            "asks": str(summary["asks"]),
            "secs": f"{secs:.1f}" if secs is not None else "–",
            "failed": str(summary["failed"]),
            "bad": str(summary["bad"]),
        }
        self.ai_state, self.ai_think = "", 0
        self.phase = "result"
        self._load_board()

    @rx.event
    def leave(self):
        """Back to the lobby (a match left halfway isn't kept)."""
        self._seq += 1
        self.phase = "lobby"
        self._load_board()
        return Game.check_opponent
