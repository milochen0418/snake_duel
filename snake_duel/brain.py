"""The AI snakes' minds: what an AI is told about the board, and what it answers.

Snake Duel holds no model and no key. It asks the AI Hub for the role ``fast``
(``reflex_ddns_auth.ai``), and the hub answers with whatever model its page sets for this
app's snakes: switching models there is how one model is tried against another. Every AI snake
of a match asks for itself, each from where it is, with the same model.

A model takes a second or more to answer, while the snakes move several times a second, so the
AI doesn't steer each step. It says where to go, in order: food by its letter, or a cell to
stand in another snake's way. Its snake's body (:func:`snake_duel.engine.pilot`) takes it there,
and it is asked again when the plan runs out, a gold one shows up, or a few seconds have gone
by. It writes two lines, which :func:`parse` reads::

    Target: B, D
    Say: That gold one is mine!

Every snake has a number (its seat ``s3`` is "3"), which the board's text and its map use, so an
AI can tell the others apart whether they are people or AI snakes.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Mapping

from snake_duel import engine
from snake_duel.engine import Cell, World

if TYPE_CHECKING:
    from snake_duel.match import Seat

ROLE = "fast"
# What the hub's page says this app asks the role for (reflex_ddns_auth.ai.uses).
USES = {ROLE: "The AI snakes' minds: where each one goes next, asked every few seconds during a match"}
# Thinking models (qwen3.5, say) spend most of these thinking; a quick model needs a few dozen.
MAX_TOKENS = 3000
MAX_TARGETS = 3

SYSTEM = {
    "zh": (
        "你在玩「雙蛇搶食」：{intro}\n"
        "規則：\n"
        "- 蘋果 +{apple} 分；金果 +{gold} 分，出現幾秒後就會消失。吃到東西身體變長一格。\n"
        "- 撞到牆、自己或別的蛇的身體扣 {crash} 分，離場 {out:g} 秒後從別處重來；兩個頭撞在一起，兩邊都扣。\n"
        "- 時間到時分數最高的贏。\n"
        "你只決定要去哪裡：你的蛇會自己走最短的安全路線、避開牆和身體，不用管每一步。"
        "你回答要花時間，這段時間蛇照你上一次說的走，吃完一個目標就直接去下一個。\n"
        "要贏就要吃得比別的蛇多：挑你比別的蛇先到的食物；來得及在金果消失前到，就先去金果。\n"
        "座標寫成 (x,y)：x 由左到右是 0 到 {w1}，y 由上到下是 0 到 {h1}。\n\n"
        "只回覆兩行，不要寫別的：\n"
        "目標：（照先後寫 2 到 3 個食物的字母，例如「B, D, A」；只有在擋住別的蛇比吃東西更划算時，才改寫一個座標，例如「(12,5)」）\n"
        "說：（用繁體中文對別的蛇說的一句話，15 個字以內）"
    ),
    "en": (
        "You are playing Snake Duel: {intro}\n"
        "Rules:\n"
        "- An apple is worth {apple} point; a gold one is worth {gold} and vanishes a few seconds after it appears. "
        "Eating makes a snake one cell longer.\n"
        "- Hitting a wall, yourself or another snake's body costs {crash} points and takes you off the board for "
        "{out:g} seconds, then you come back somewhere else; when two heads meet, both lose.\n"
        "- Whoever has the most points when time is up wins.\n"
        "You only decide where to go: your snake takes the shortest safe way there by itself, around walls and "
        "bodies, so you don't steer each step. Answering takes you time, and meanwhile your snake keeps to what "
        "you said last, going straight on to the next target once it has eaten one.\n"
        "To win, eat more than the other snakes: pick food you reach before them, and go for a gold one first if "
        "you can get there before it vanishes.\n"
        "Cells are (x,y): x from 0 to {w1} left to right, y from 0 to {h1} top to bottom.\n\n"
        "Reply with exactly these two lines and nothing else:\n"
        "Target: (2 to 3 food letters in the order to go for them, e.g. \"B, D, A\"; only when blocking another "
        "snake is worth more than eating, one cell instead, e.g. \"(12,5)\")\n"
        "Say: (one short sentence to the other snakes, at most 8 words)"
    ),
}
INTRO = {
    "zh": {
        "duel": "你是 AI 蛇，對手是一個人，兩條蛇在同一塊 {w}×{h} 的場地上搶同一批食物。",
        "crowd": (
            "場上一共 {total} 條蛇：{people} 個人和 {ais} 條 AI 蛇，你是其中一條 AI 蛇"
            "（是哪一條寫在局面裡），大家在同一塊 {w}×{h} 的場地上搶同一批食物，各自為戰。"
        ),
        "ais": "場上一共 {total} 條 AI 蛇，沒有人，你是其中一條（是哪一條寫在局面裡），大家在同一塊 {w}×{h} 的場地上搶同一批食物，各自為戰。",
    },
    "en": {
        "duel": "you are the AI snake, your opponent is a person, and both snakes are after the same food on one {w}×{h} board.",
        "crowd": (
            "there are {total} snakes in the arena, {people} of them people and {ais} AI snakes, and you are one of "
            "the AI snakes (which one is in the board you are shown); all of you are after the same food on one "
            "{w}×{h} board, each for themselves."
        ),
        "ais": (
            "there are {total} AI snakes in the arena and no people; you are one of them (which one is in the board "
            "you are shown), all after the same food on one {w}×{h} board, each for themselves."
        ),
    },
}

_WAYS = {
    "zh": {"up": "上", "down": "下", "left": "左", "right": "右"},
    "en": {"up": "up", "down": "down", "left": "left", "right": "right"},
}
_TARGET = re.compile(r"^(?:目標|目标|target|targets|goal)\s*[:：]\s*(.*)$", re.IGNORECASE)
_SAY = re.compile(r"^(?:說|说|say|says)\s*[:：]\s*(.*)$", re.IGNORECASE)
_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# A cell "(12,5)" (brackets optional), or a food's capital letter standing on its own.
_PICK = re.compile(r"[(（]?\s*(\d{1,2})\s*[,，]\s*(\d{1,2})\s*[)）]?|(?<![A-Za-z])([A-Z])(?![A-Za-z])")


@dataclasses.dataclass
class Target:
    """One place the AI wants to go: a food by its letter, or a cell."""

    label: str = ""
    cell: Cell | None = None


@dataclasses.dataclass
class Move:
    """What the AI answered to one ask."""

    targets: list[Target]
    say: str
    well_formed: bool  # it kept to the two lines and named somewhere to go


def mark(sid: str) -> str:
    """A snake's number on the map and in the text: seat ``s3`` is "3"."""
    return sid.removeprefix("s")


def system(lang: str, world: World, people: int, ais: int) -> str:
    """The rules, the same for every AI snake of a match (so a model can reuse what it read)."""
    kind = "duel" if people == 1 and ais == 1 else "ais" if people == 0 else "crowd"
    intro = INTRO[lang][kind].format(total=people + ais, people=people, ais=ais, w=world.w, h=world.h)
    return SYSTEM[lang].format(
        intro=intro,
        w1=world.w - 1,
        h1=world.h - 1,
        apple=engine.APPLE_POINTS,
        gold=engine.GOLD_POINTS,
        crash=engine.CRASH_POINTS,
        out=engine.OUT_SECONDS,
    )


def prompt(world: World, me: str, lang: str, seats: Mapping[str, "Seat"]) -> str:
    """The board as AI snake ``me`` sees it: the scores, every snake with its number, every food
    with how many steps it and the nearest other snake are from it, and with only two snakes the
    map. More snakes leave the map out: several of them asking one local model in turn would
    wait half as long again for it (the steps already go round the bodies)."""
    zh = lang == "zh"
    mine = world.snakes[me]
    others = world.others(me)
    ways = _WAYS[lang]

    def tag(sid: str) -> str:
        seat = seats[sid]
        if seat.left:
            what = f"{seat.name}，AI 接手" if zh else f"{seat.name}, taken over by an AI"
        elif seat.kind == "person":
            what = f"人：{seat.name}" if zh else f"a person: {seat.name}"
        else:
            what = seat.name
        return f"{mark(sid)} 號（{what}）" if zh else f"#{mark(sid)} ({what})"

    def back_in(snake: engine.Snake) -> float:
        return max(0.0, world.seconds(snake.back_at - world.tick))

    def where(snake: engine.Snake) -> str:
        (x, y), size = snake.head, len(snake.body) + snake.grow
        if zh:
            return f"頭在 ({x},{y})，正往{ways[snake.heading]}，長 {size}。"
        return f"head at ({x},{y}), moving {ways[snake.heading]}, length {size}."

    left = round(world.left)
    scores = [f"{mark(sid)} 號 {s.score}" if zh else f"#{mark(sid)} {s.score}" for sid, s in others.items()]
    lines = [
        f"剩 {left} 秒。分數：你 {mine.score}，{'，'.join(scores)}。" if zh else f"{left} s left. Scores: you {mine.score}, {', '.join(scores)}.",
    ]
    if mine.alive:
        lines.append(f"你是 {tag(me)}：{where(mine)}" if zh else f"You are {tag(me)}: {where(mine)}")
    else:
        lines.append(
            f"你是 {tag(me)}，剛撞到，{back_in(mine):.1f} 秒後回到場上。" if zh else f"You are {tag(me)}, just crashed, back in {back_in(mine):.1f} s."
        )
    for sid, snake in others.items():
        if snake.alive:
            lines.append(f"{tag(sid)}：{where(snake)}" if zh else f"{tag(sid)}: {where(snake)}")
        else:
            lines.append(f"{tag(sid)}剛撞到，{back_in(snake):.1f} 秒後回來。" if zh else f"{tag(sid)} just crashed, back in {back_in(snake):.1f} s.")

    lines.append("食物（步數是照現在的蛇身算的最短路）：" if zh else "Food (steps: the shortest way past the bodies as they are now):")
    for food in sorted(world.foods, key=lambda f: f.label):
        x, y = food.cell
        own = engine.distance(world, me, food.cell)
        near = min(((d, sid) for sid in others if (d := engine.distance(world, sid, food.cell)) is not None), default=None)
        if zh:
            kind = f"金果 +{food.points}" if food.kind == "gold" else f"蘋果 +{food.points}"
            gone = f"，{world.seconds(food.until - world.tick):.0f} 秒後消失" if food.until else ""
            yours = f"{own} 步" if own is not None else "到不了"
            theirs = f"別的蛇最快是 {mark(near[1])} 號，{near[0]} 步" if near else "別的蛇都到不了"
            lines.append(f"{food.label} {kind} 在 ({x},{y}){gone}：你 {yours}；{theirs}")
        else:
            kind = f"gold +{food.points}" if food.kind == "gold" else f"apple +{food.points}"
            gone = f", vanishes in {world.seconds(food.until - world.tick):.0f} s" if food.until else ""
            yours = f"{own} steps" if own is not None else "can't get there"
            theirs = f"the nearest other snake is #{mark(near[1])}, {near[0]} steps" if near else "no other snake can get there"
            lines.append(f"{food.label} {kind} at ({x},{y}){gone}: you {yours}; {theirs}")
    if len(world.snakes) == 2:
        lines.append(
            "地圖（Y 你的頭，y 你的身體，數字是別的蛇的頭（號碼同上），o 別的蛇的身體，字母是食物，. 是空地）："
            if zh
            else "Map (Y your head, y your body, digits the other snakes' heads (numbers as above), o their bodies, letters are food, . is free):"
        )
        lines.extend(_map(world, me))
    return "\n".join(lines)


def _map(world: World, me: str) -> list[str]:
    """The grid with its x numbers above (tens, then ones) and its y numbers on the left."""
    pad = "    "
    tens = "".join(str(x // 10) for x in range(world.w))
    ones = "".join(str(x % 10) for x in range(world.w))
    rows = engine.grid(world, me, {sid: mark(sid) for sid in world.snakes})
    return [pad + tens, pad + ones, *(f"{y:>2}  {row}" for y, row in enumerate(rows))]


def messages(world: World, me: str, lang: str, seats: Mapping[str, "Seat"]) -> list[dict[str, str]]:
    return [{"role": "user", "content": prompt(world, me, lang, seats)}]


def parse(text: str, labels: set[str] | None = None, w: int = engine.CROWD[0], h: int = engine.CROWD[1]) -> Move:
    """The places the AI named, in order, and what it said, read as leniently as is fair: without
    a target line, the cells and the letters of food on the board (``labels``) anywhere else in
    the answer count. Cells off a ``w × h`` board are left out."""
    text = _THINKING.sub("", text or "").strip()
    target_text: str | None = None
    say = ""
    rest = []
    for raw in text.splitlines():
        line = raw.strip().strip("*`#>-").strip().replace("**", "")
        if not line:
            continue
        if (m := _TARGET.match(line)) and target_text is None:
            target_text = m.group(1)
        elif m := _SAY.match(line):
            say = say or m.group(1).strip().strip("「」\"'")
        else:
            rest.append(line)
    if target_text is not None:
        targets = _targets(target_text, None, w, h)
    else:
        targets = _targets("\n".join(rest), labels, w, h)
    return Move(targets=targets, say=say[:60], well_formed=target_text is not None and bool(targets))


def _targets(text: str, labels: set[str] | None, w: int, h: int) -> list[Target]:
    out: list[Target] = []
    for m in _PICK.finditer(text):
        if m.group(3):
            if labels is not None and m.group(3) not in labels:
                continue
            target = Target(label=m.group(3))
        else:
            x, y = int(m.group(1)), int(m.group(2))
            if not (0 <= x < w and 0 <= y < h):
                continue
            target = Target(cell=(x, y))
        if target not in out:
            out.append(target)
        if len(out) == MAX_TARGETS:
            break
    return out
