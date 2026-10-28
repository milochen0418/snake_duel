"""The AI snake's mind: what the AI is told about the board, and what it answers.

Snake Duel holds no model and no key. It asks the AI Hub for the role ``fast``
(``reflex_ddns_auth.ai``), and the hub answers with whatever model its page sets for this
app's snake: switching models there is how one model is tried against another.

A model takes a second or more to answer, while the snakes move several times a second, so the
AI doesn't steer each step. It says where to go, in order: food by its letter, or a cell to
stand in the person's way. Its snake's body (:func:`snake_duel.engine.pilot`) takes it there,
and it is asked again when the plan runs out, a gold one shows up, or a few seconds have gone
by. It writes two lines, which :func:`parse` reads::

    Target: B, D
    Say: That gold one is mine!
"""

from __future__ import annotations

import dataclasses
import re

from snake_duel import engine
from snake_duel.engine import Cell, World

ROLE = "fast"
# What the hub's page says this app asks the role for (reflex_ddns_auth.ai.uses).
USES = {ROLE: "The AI snake's mind: where it goes next, asked every few seconds during a match"}
# Thinking models (qwen3.5, say) spend most of these thinking; a quick model needs a few dozen.
MAX_TOKENS = 3000
MAX_TARGETS = 3

SYSTEM = {
    "zh": (
        "你在玩「雙蛇搶食」：你是 AI 蛇，對手是一個人，兩條蛇在同一塊 {w}×{h} 的場地上搶同一批食物。\n"
        "規則：\n"
        "- 蘋果 +{apple} 分；金果 +{gold} 分，出現幾秒後就會消失。吃到東西身體變長一格。\n"
        "- 撞到牆、自己或對方的身體扣 {crash} 分，離場 {out:g} 秒後從別處重來；兩個頭撞在一起，兩邊都扣。\n"
        "- 時間到時分數高的贏。\n"
        "你只決定要去哪裡：你的蛇會自己走最短的安全路線、避開牆和身體，不用管每一步。"
        "你回答要花時間，這段時間蛇照你上一次說的走，吃完一個目標就直接去下一個。\n"
        "要贏就要吃得比對手多：挑你比對手先到的食物；來得及在金果消失前到，就先去金果。\n"
        "座標寫成 (x,y)：x 由左到右是 0 到 {w1}，y 由上到下是 0 到 {h1}。\n\n"
        "只回覆兩行，不要寫別的：\n"
        "目標：（照先後寫 2 到 3 個食物的字母，例如「B, D, A」；只有在擋住對手比吃東西更划算時，才改寫一個座標，例如「(12,5)」）\n"
        "說：（用繁體中文對對手說的一句話，15 個字以內）"
    ),
    "en": (
        "You are playing Snake Duel: you are the AI snake, your opponent is a person, and both snakes are after "
        "the same food on one {w}×{h} board.\n"
        "Rules:\n"
        "- An apple is worth {apple} point; a gold one is worth {gold} and vanishes a few seconds after it appears. "
        "Eating makes a snake one cell longer.\n"
        "- Hitting a wall, yourself or the other snake's body costs {crash} points and takes you off the board for "
        "{out:g} seconds, then you come back somewhere else; when the two heads meet, both lose.\n"
        "- Whoever has more points when time is up wins.\n"
        "You only decide where to go: your snake takes the shortest safe way there by itself, around walls and "
        "bodies, so you don't steer each step. Answering takes you time, and meanwhile your snake keeps to what "
        "you said last, going straight on to the next target once it has eaten one.\n"
        "To win, eat more than your opponent: pick food you reach before them, and go for a gold one first if you "
        "can get there before it vanishes.\n"
        "Cells are (x,y): x from 0 to {w1} left to right, y from 0 to {h1} top to bottom.\n\n"
        "Reply with exactly these two lines and nothing else:\n"
        "Target: (2 to 3 food letters in the order to go for them, e.g. \"B, D, A\"; only when blocking your "
        "opponent is worth more than eating, one cell instead, e.g. \"(12,5)\")\n"
        "Say: (one short sentence to your opponent, at most 8 words)"
    ),
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


def system(lang: str) -> str:
    return SYSTEM[lang].format(
        w=engine.W,
        h=engine.H,
        w1=engine.W - 1,
        h1=engine.H - 1,
        apple=engine.APPLE_POINTS,
        gold=engine.GOLD_POINTS,
        crash=engine.CRASH_POINTS,
        out=engine.OUT_SECONDS,
    )


def prompt(world: World, lang: str) -> str:
    """The board as the AI snake sees it: the score, both snakes, every food with how many steps
    each head is from it, and the map."""
    zh = lang == "zh"
    me, them = world.snakes["ai"], world.snakes["you"]
    ways = _WAYS[lang]

    def snake_line(snake: engine.Snake, mine: bool) -> str:
        if not snake.alive:
            secs = max(0.0, world.seconds(snake.back_at - world.tick))
            if zh:
                return f"{'你' if mine else '對手'}剛撞到，{secs:.1f} 秒後回到場上。"
            return f"{'You' if mine else 'Your opponent'} just crashed, back in {secs:.1f} s."
        (x, y), size = snake.head, len(snake.body) + snake.grow
        if zh:
            return f"{'你（AI 蛇）' if mine else '對手（人）'}：頭在 ({x},{y})，正往{ways[snake.heading]}，長 {size}。"
        return f"{'You (the AI snake)' if mine else 'Your opponent (the person)'}: head at ({x},{y}), moving {ways[snake.heading]}, length {size}."

    def steps(n: int | None) -> str:
        if n is None:
            return "到不了" if zh else "can't get there"
        return f"{n} 步" if zh else f"{n} steps"

    left = round(world.left)
    lines = [
        f"剩 {left} 秒。比分：你 {me.score}，對手 {them.score}。" if zh else f"{left} s left. Score: you {me.score}, your opponent {them.score}.",
        snake_line(me, True),
        snake_line(them, False),
        "食物（步數是照現在的蛇身算的最短路）：" if zh else "Food (steps: the shortest way past the bodies as they are now):",
    ]
    for food in sorted(world.foods, key=lambda f: f.label):
        x, y = food.cell
        mine, theirs = engine.distance(world, "ai", food.cell), engine.distance(world, "you", food.cell)
        if zh:
            kind = f"金果 +{food.points}" if food.kind == "gold" else f"蘋果 +{food.points}"
            gone = f"，{world.seconds(food.until - world.tick):.0f} 秒後消失" if food.until else ""
            lines.append(f"{food.label} {kind} 在 ({x},{y}){gone}：你 {steps(mine)}，對手 {steps(theirs)}")
        else:
            kind = f"gold +{food.points}" if food.kind == "gold" else f"apple +{food.points}"
            gone = f", vanishes in {world.seconds(food.until - world.tick):.0f} s" if food.until else ""
            lines.append(f"{food.label} {kind} at ({x},{y}){gone}: you {steps(mine)}, your opponent {steps(theirs)}")
    lines.append(
        "地圖（Y 你的頭，y 你的身體，O 對手的頭，o 對手的身體，字母是食物，. 是空地）："
        if zh
        else "Map (Y your head, y your body, O your opponent's head, o their body, letters are food, . is free):"
    )
    lines.extend(_map(world))
    return "\n".join(lines)


def _map(world: World) -> list[str]:
    """The grid with its x numbers above (tens, then ones) and its y numbers on the left."""
    pad = "    "
    tens = "".join(str(x // 10) for x in range(world.w))
    ones = "".join(str(x % 10) for x in range(world.w))
    rows = engine.grid(world, "ai")
    return [pad + tens, pad + ones, *(f"{y:>2}  {row}" for y, row in enumerate(rows))]


def messages(world: World, lang: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": prompt(world, lang)}]


def parse(text: str, labels: set[str] | None = None, w: int = engine.W, h: int = engine.H) -> Move:
    """The places the AI named, in order, and what it said, read as leniently as is fair: without
    a target line, the cells and the letters of food on the board (``labels``) anywhere else in
    the answer count."""
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
