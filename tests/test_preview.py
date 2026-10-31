import re
import struct
import zlib

import pytest

from snake_duel import preview, rooms
from snake_duel.engine import APPLE_POINTS
from snake_duel.match import Match


@pytest.fixture(autouse=True)
def no_rooms_left():
    rooms.rooms.clear()
    yield
    rooms.rooms.clear()


def decode(png: bytes) -> tuple[int, int, bytes, list[bytes]]:
    """Width, height, palette and pixel rows of one of our PNGs."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(png):
        size, kind = struct.unpack(">I4s", png[pos : pos + 8])
        data = png[pos + 8 : pos + 8 + size]
        assert struct.unpack(">I", png[pos + 8 + size : pos + 12 + size])[0] == zlib.crc32(kind + data)
        chunks[kind] = data
        pos += 12 + size
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    raw = zlib.decompress(chunks[b"IDAT"])
    rows = [raw[y * (width + 1) + 1 : (y + 1) * (width + 1)] for y in range(height)]
    return width, height, chunks[b"PLTE"], rows


def colour(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    _, _, palette, rows = decode(png)
    i = rows[y][x]
    return palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]


def frame() -> dict:
    game = Match("practice", "zh", "normal", 60, ["小明"], 3, seed=1)
    return game.frame()


def test_the_picture_is_a_real_png_of_the_board():
    f = frame()
    png = preview.board_png(f, 900)
    width, height, _, rows = decode(png)
    assert (width, height) == (900, 600) and len(rows) == 600 and all(len(r) == 900 for r in rows)
    food = f["food"][0]
    assert colour(png, food["x"] * 30 + 15, food["y"] * 30 + 16) == (0xf4, 0x3f, 0x5e)  # an apple
    x, y = f["snakes"][1]["body"][2]  # the second seat's body: cyan
    assert colour(png, x * 30 + 15, y * 30 + 15)[2] > 0xdd


def test_the_little_picture_is_small():
    assert len(preview.board_png(frame(), preview.THUMB_WIDTH)) < 2000


def test_a_room_still_waiting_shows_its_starting_places():
    room = rooms.open_room("ming", "小明", "", "zh", "practice", "fast", "60", 4)
    assert decode(preview.picture(room))[:2] == (900, 600)
    assert preview.thumb(room).startswith("data:image/png;base64,")
    assert decode(preview.picture(None))[:2] == (900, 600)  # a room that is over


def test_the_card_of_a_waiting_room_says_who_is_in():
    room = rooms.open_room("ming", "小明", "", "zh", "practice", "fast", "60", 5)
    rooms.enter(room, "mei", "阿美")
    title, text = preview.describe(room)
    assert title == "小明 邀你來玩雙蛇搶食"
    assert f"房間 {room.id}" in text and "5 條蛇" in text and "小明、阿美" in text and "補 3 條 AI 蛇" in text


def test_the_card_of_a_match_says_how_it_stands():
    room = rooms.open_room("ming", "Milo", "", "en", "practice", "fast", "60", 2)
    rooms.start(room)
    room.chips[1].score = 5 * APPLE_POINTS
    room.phase = "play"
    title, text = preview.describe(room)
    assert title == "Milo invites you to Snake Duel"
    assert text.startswith(f"Room {room.id} is playing, 60 s left: AI 5, Milo 0.")
    room.phase = "result"
    assert "just finished" in preview.describe(room)[1]


def test_the_page_carries_the_tags_and_moves_on():
    room = rooms.open_room("ming", '小"明<b>', "", "zh", "practice", "fast", "60", 3)
    html = preview.page(room, room.id, "https://snake-duel.reflex-ddns.com")
    assert f'content="0; url=/?r={room.id}"' in html
    assert f'property="og:url" content="https://snake-duel.reflex-ddns.com/r/{room.id}"' in html
    assert re.search(rf'property="og:image" content="https://snake-duel.reflex-ddns.com/r/{room.id}/board.png\?t=0"', html)
    assert "<b>" not in html and "&lt;b&gt;" in html and "&quot;" in html


def test_a_room_that_is_over_keeps_a_card():
    html = preview.page(None, "ABCD", "https://x.reflex-ddns.com")
    assert "這個房間已經結束了" in html and 'url=/?r=ABCD' in html and "board.png" in html
