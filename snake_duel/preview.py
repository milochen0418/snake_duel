"""What a shared link shows before anyone opens it: a picture of the arena and a few words.

An invite link is ``/r/<code>``. re-ddns sends that path to the backend (``backend-paths.txt``),
and the answer is a small page: OpenGraph tags for whatever fetches the link to make a card
(Relack, chat apps), and a redirect into the game for a person. The lobby's room list uses the
same picture, smaller.

The picture is drawn here, cell by cell, into an indexed PNG (no imaging library): the board as
it is now, or the starting places while the room is still waiting.
"""

from __future__ import annotations

import base64
import html
import json
import math
import struct
import zlib
from typing import TYPE_CHECKING, Any

from snake_duel import engine

if TYPE_CHECKING:
    from snake_duel.rooms import Room

CARD_WIDTH = 900  # 3:2, the shape of Relack's card
THUMB_WIDTH = 240
SEATS = ("s1", "s2", "s3", "s4", "s5")

_GROUND, _CHECK, _EDGE, _APPLE, _LEAF, _GOLD, _EYE, _PUPIL, _FIRST_SEAT = range(9)
# Each seat's dark, body and light colours, as the page draws them (assets/snake_duel/arena.js).
_SEAT_COLORS = (
    ("#92400e", "#f59e0b", "#fde68a"),
    ("#155e75", "#22d3ee", "#a5f3fc"),
    ("#5b21b6", "#a78bfa", "#ddd6fe"),
    ("#3f6212", "#a3e635", "#d9f99d"),
    ("#9d174d", "#f472b6", "#fbcfe8"),
)
_PALETTE = ["#0b1220", "#121b2c", "#3b4a63", "#f43f5e", "#4ade80", "#fde047", "#f8fafc", "#0f172a", *(c for seat in _SEAT_COLORS for c in seat)]
_WORDS = {
    "zh": {
        "app": "雙蛇搶食",
        "invite": "{host} 邀你來玩雙蛇搶食",
        "gone": "這個房間已經結束了。打開連結可以開新的房間，跟朋友和 AI 搶食物。",
        "open": "房間 {code} · {total} 條蛇 · 現在 {people} 人（{who}）{ais}。打開連結就能加入。",
        "ais": "，開打時補 {n} 條 AI 蛇",
        "play": "房間 {code} 比賽中，剩 {left} 秒：{scores}。打開連結可以觀戰，下一場一起打。",
        "done": "房間 {code} 剛打完：{scores}。打開連結，下一場一起打。",
        "scores": "{name} {score} 分",
        "sep": "、",
    },
    "en": {
        "app": "Snake Duel",
        "invite": "{host} invites you to Snake Duel",
        "gone": "This room is over. Open the link to start a new one: you, your friends and AI snakes after the same food.",
        "open": "Room {code} · {total} snakes · {people} in so far ({who}){ais}. Open the link to join.",
        "ais": "; {n} AI snakes fill the rest",
        "play": "Room {code} is playing, {left} s left: {scores}. Open the link to watch and join the next match.",
        "done": "Room {code} just finished: {scores}. Open the link and join the next match.",
        "scores": "{name} {score}",
        "sep": ", ",
    },
}


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _png(rows: list[bytearray]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    palette = b"".join(bytes(_rgb(c)) for c in _PALETTE)
    header = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 3, 0, 0, 0)
    pixels = zlib.compress(b"".join(b"\0" + bytes(row) for row in rows), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"PLTE", palette) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


class _Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        self.rows = [bytearray([_GROUND]) * width for _ in range(height)]

    def rect(self, x0: float, y0: float, x1: float, y1: float, color: int) -> None:
        left, right = max(0, round(x0)), min(self.w, round(x1))
        if right <= left:
            return
        span = bytes([color]) * (right - left)
        for y in range(max(0, round(y0)), min(self.h, round(y1))):
            self.rows[y][left:right] = span

    def disc(self, cx: float, cy: float, r: float, color: int) -> None:
        for y in range(max(0, math.floor(cy - r)), min(self.h, math.ceil(cy + r) + 1)):
            dy = y + 0.5 - cy
            if abs(dy) >= r:
                continue
            half = math.sqrt(r * r - dy * dy)
            left, right = max(0, round(cx - half)), min(self.w, round(cx + half))
            if right > left:
                self.rows[y][left:right] = bytes([color]) * (right - left)


def _snake(canvas: _Canvas, snake: dict[str, Any], cell: float, seat: int) -> None:
    dark, body, light = _FIRST_SEAT + seat * 3, _FIRST_SEAT + seat * 3 + 1, _FIRST_SEAT + seat * 3 + 2
    centres = [((x + 0.5) * cell, (y + 0.5) * cell) for x, y in snake["body"]]

    def tube(color: int, half: float) -> None:
        for (ax, ay), (bx, by) in zip(centres, centres[1:]):
            canvas.rect(min(ax, bx) - half, min(ay, by) - half, max(ax, bx) + half, max(ay, by) + half, color)
        for cx, cy in centres:
            canvas.disc(cx, cy, half, color)

    tube(dark, cell * 0.39)
    tube(body, cell * 0.31)
    tube(light, cell * 0.07)
    hx, hy = centres[0]
    canvas.disc(hx, hy, cell * 0.45, dark)
    canvas.disc(hx, hy, cell * 0.39, body)
    dx, dy = engine.DIRS.get(snake.get("dir", "right"), (1, 0))
    for side in (-1, 1):
        ex, ey = hx + (dx * 0.16 - dy * side * 0.2) * cell, hy + (dy * 0.16 + dx * side * 0.2) * cell
        canvas.disc(ex, ey, cell * 0.12, _EYE)
        canvas.disc(ex + dx * cell * 0.05, ey + dy * cell * 0.05, cell * 0.06, _PUPIL)


def board_png(frame: dict[str, Any], width: int) -> bytes:
    """A picture of one frame of the arena (``engine.frame``), ``width`` pixels wide or a little less."""
    cell = max(2, width // frame["w"])
    canvas = _Canvas(cell * frame["w"], cell * frame["h"])
    for y in range(frame["h"]):
        for x in range(y % 2, frame["w"], 2):
            canvas.rect(x * cell, y * cell, (x + 1) * cell, (y + 1) * cell, _CHECK)
    for x0, y0, x1, y1 in ((0, 0, canvas.w, 2), (0, canvas.h - 2, canvas.w, canvas.h), (0, 0, 2, canvas.h), (canvas.w - 2, 0, canvas.w, canvas.h)):
        canvas.rect(x0, y0, x1, y1, _EDGE)
    for food in frame["food"]:
        cx, cy = (food["x"] + 0.5) * cell, (food["y"] + 0.5) * cell
        if food["k"] == "gold":
            canvas.disc(cx, cy, cell * 0.44, _GOLD)
        else:
            canvas.disc(cx, cy + cell * 0.04, cell * 0.34, _APPLE)
            canvas.disc(cx + cell * 0.1, cy - cell * 0.32, cell * 0.1, _LEAF)
    for snake in frame["snakes"]:
        if snake["body"] and snake["id"] in SEATS:
            _snake(canvas, snake, cell, SEATS.index(snake["id"]))
    return _png(canvas.rows)


def _waiting_frame(total: int) -> dict[str, Any]:
    """The starting places of an arena of ``total`` snakes, for a room still waiting."""
    world = engine.new_world(list(SEATS[: max(2, min(total, len(SEATS)))]), 160, 60, seed=total)
    return engine.frame(world, {}, {}, [])


def picture(room: Room | None, width: int = CARD_WIDTH) -> bytes:
    """A room's board as it is now (the starting places of five snakes when there is no room)."""
    frame = json.loads(room.frame) if room is not None and room.frame else _waiting_frame(room.total if room is not None else 5)
    return board_png(frame, width)


def thumb(room: Room) -> str:
    """The lobby's little picture of a room, as a data URL."""
    return "data:image/png;base64," + base64.b64encode(picture(room, THUMB_WIDTH)).decode("ascii")


def describe(room: Room | None, lang: str = "zh") -> tuple[str, str]:
    """A room's card: its title and one or two sentences (who is in it, how it stands)."""
    words = _WORDS["en" if (room.lang if room is not None else lang) == "en" else "zh"]
    if room is None:
        return words["app"], words["gone"]
    host = room.players.get(room.host) or next(iter(room.players.values()), None)
    title = words["invite"].format(host=host.name) if host is not None else words["app"]
    if room.phase == "open":
        ais = max(0, room.total - len(room.players))
        who = words["sep"].join(p.name for p in room.people)
        extra = words["ais"].format(n=ais) if ais else ""
        return title, words["open"].format(code=room.id, total=room.total, people=len(room.players), who=who, ais=extra)
    best = sorted(room.chips, key=lambda chip: -chip.score)[:3]
    scores = words["sep"].join(words["scores"].format(name=chip.name, score=chip.score) for chip in best)
    key = "done" if room.phase == "result" else "play"
    return title, words[key].format(code=room.id, left=room.left, scores=scores)


def page(room: Room | None, code: str, base: str) -> str:
    """The page ``/r/<code>`` answers with: tags for a link card, and on into the game."""
    title, text = describe(room)
    link = f"/?r={code}"
    version = room.match.world.tick if room is not None and room.match is not None else 0
    image = f"{base}/r/{code}/board.png?t={version}"
    tags = {
        "og:type": "website",
        "og:site_name": _WORDS["en" if room is not None and room.lang == "en" else "zh"]["app"],
        "og:title": title,
        "og:description": text,
        "og:url": f"{base}/r/{code}",
        "og:image": image,
        "og:image:width": "900",
        "og:image:height": "600",
    }
    metas = "\n".join(f'<meta property="{k}" content="{html.escape(v, quote=True)}">' for k, v in tags.items())
    return (
        '<!doctype html>\n<html><head><meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n"
        f'<meta name="description" content="{html.escape(text, quote=True)}">\n'
        f'{metas}\n<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta http-equiv="refresh" content="0; url={html.escape(link, quote=True)}">\n'
        f"</head><body><a href=\"{html.escape(link, quote=True)}\">{html.escape(title)}</a></body></html>\n"
    )
