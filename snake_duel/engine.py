"""The rules of the arena: snakes on one board after the same food, all moving at the same moment.

Pure Python, no Reflex. :class:`World` is a whole match, two snakes (a duel) or up to five (a
free-for-all); :func:`step` moves it on by one tick with each snake's turn, and says what
happened (who ate what, who crashed, who came back).

An AI snake has a "body", :func:`pilot`: told where its AI wants to go, it takes the shortest
safe way there, steering clear of walls, bodies and the other heads; told nothing, it only dodges
and never goes after food by itself. Where to go is the AI's choice (:mod:`snake_duel.brain`).

Snakes are known by an id (``you`` for the person, ``ai1``, ``ai2`` … for the AI snakes). The
board is ``w × h`` cells (:func:`board_size`); ``(0, 0)`` is the top left, x grows to the right,
y downwards.
"""

from __future__ import annotations

import collections
import dataclasses
import math
import random
import string
from typing import Any

Cell = tuple[int, int]

DUEL = (24, 16)  # the board for two snakes
CROWD = (30, 20)  # the board for three to five
MAX_SNAKES = 5
DIRS: dict[str, Cell] = {"up": (0, -1), "right": (1, 0), "down": (0, 1), "left": (-1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}

START_LEN = 4
APPLE_POINTS = 1
GOLD_POINTS = 3
CRASH_POINTS = 3  # lost on a crash
OUT_SECONDS = 2.0  # off the board after a crash
FIRST_GOLD_SECONDS = 10.0
GOLD_EVERY_SECONDS = 12.0  # after the last one was eaten or vanished
GOLD_LASTS_SECONDS = 8.0
NEAR = 3  # new food lands at least this many steps from every head


def board_size(snakes: int) -> tuple[int, int]:
    return DUEL if snakes <= 2 else CROWD


@dataclasses.dataclass
class Snake:
    body: list[Cell]  # head first; empty while it is off the board after a crash
    heading: str  # the way it last moved
    score: int = 0
    grow: int = 0  # cells still to grow (a snake coming back grows out of one cell)
    back_at: int = 0  # the tick it comes back after a crash
    apples: int = 0
    golds: int = 0
    crashes: int = 0

    @property
    def alive(self) -> bool:
        return bool(self.body)

    @property
    def head(self) -> Cell:
        return self.body[0]


@dataclasses.dataclass
class Food:
    label: str  # A to Z: how the AI names it
    cell: Cell
    kind: str  # apple or gold
    until: int = 0  # the tick a gold one vanishes (0: it stays)

    @property
    def points(self) -> int:
        return GOLD_POINTS if self.kind == "gold" else APPLE_POINTS


@dataclasses.dataclass
class World:
    tick_ms: int
    end: int  # the last tick of the match
    snakes: dict[str, Snake]
    foods: list[Food] = dataclasses.field(default_factory=list)
    tick: int = 0
    next_gold: int = 0
    labels: int = 0  # where the next label is looked for
    apples: int = 3  # apples on the board at all times
    rng: random.Random = dataclasses.field(default_factory=random.Random)
    w: int = DUEL[0]
    h: int = DUEL[1]

    def ticks(self, seconds: float) -> int:
        return max(1, round(seconds * 1000 / self.tick_ms))

    def seconds(self, ticks: int) -> float:
        return ticks * self.tick_ms / 1000

    @property
    def left(self) -> float:
        """Seconds left in the match."""
        return max(0.0, self.seconds(self.end - self.tick))

    @property
    def over(self) -> bool:
        return self.tick >= self.end

    def inside(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.w and 0 <= cell[1] < self.h

    def food(self, label: str) -> Food | None:
        return next((f for f in self.foods if f.label == label), None)

    def others(self, who: str) -> dict[str, Snake]:
        return {k: s for k, s in self.snakes.items() if k != who}


def ahead(cell: Cell, way: str) -> Cell:
    dx, dy = DIRS[way]
    return (cell[0] + dx, cell[1] + dy)


def way_to(a: Cell, b: Cell) -> str:
    """The direction of a step from ``a`` to the next cell ``b``."""
    return next(d for d, (dx, dy) in DIRS.items() if (a[0] + dx, a[1] + dy) == b)


def new_world(ids: list[str], tick_ms: int, seconds: int, seed: int | None = None) -> World:
    """The snakes at their starting places, and the first apples (one more than there are
    snakes), as near to one head as to the others as the board allows."""
    if not 2 <= len(ids) <= MAX_SNAKES:
        raise ValueError(f"2 to {MAX_SNAKES} snakes, not {len(ids)}")
    w, h = board_size(len(ids))
    snakes = {}
    for who, (head, way) in zip(ids, _starts(len(ids), w, h)):
        dx, dy = DIRS[way]
        snakes[who] = Snake(body=[(head[0] - dx * i, head[1] - dy * i) for i in range(START_LEN)], heading=way)
    world = World(tick_ms=tick_ms, end=0, snakes=snakes, apples=len(ids) + 1, rng=random.Random(seed), w=w, h=h)
    world.end = world.ticks(seconds)
    world.next_gold = world.ticks(FIRST_GOLD_SECONDS)
    heads = [s.head for s in snakes.values()]
    cells = [c for c in _free(world) if _far(world, c)]
    spread = {c: max(_steps(hd, c) for hd in heads) - min(_steps(hd, c) for hd in heads) for c in cells}
    fair = sorted(cells, key=lambda c: spread[c])
    least = spread[fair[0]]
    fair = [c for c in fair if spread[c] <= least + (0 if len(ids) == 2 else 2)] or fair
    for cell in world.rng.sample(fair, min(world.apples, len(fair))):
        world.foods.append(Food(_label(world), cell, "apple"))
    return world


def _starts(n: int, w: int, h: int) -> list[tuple[Cell, str]]:
    """Where each snake's head starts, and its way. Two face each other across the board (the
    second's place is the first's turned half way round); three to five start evenly round the
    middle, all going the same way round, so none runs into another at once."""
    if n == 2:
        first = (6, 4)
        return [(first, "right"), ((w - 1 - first[0], h - 1 - first[1]), "left")]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    out = []
    for k in range(n):
        a = math.pi + 2 * math.pi * k / n  # the first one (the person) on the left
        x, y = round(cx + w * 0.32 * math.cos(a)), round(cy + h * 0.3 * math.sin(a))
        tx, ty = -math.sin(a), math.cos(a)  # clockwise on the screen
        way = ("right" if tx > 0 else "left") if abs(tx) >= abs(ty) else ("down" if ty > 0 else "up")
        out.append(((x, y), way))
    return out


# ------------------------------------------------------------ a tick


def step(world: World, turns: dict[str, str | None]) -> list[dict[str, Any]]:
    """Moves the world on by one tick: each snake turns (or not) and all move at once; then
    crashes, food and comebacks are settled. Returns what happened, for the page's effects."""
    world.tick += 1
    events: list[dict[str, Any]] = []
    moving = {who: s for who, s in world.snakes.items() if s.alive}
    heads: dict[str, Cell] = {}
    for who, snake in moving.items():
        turn = turns.get(who)
        if turn in DIRS and turn != OPPOSITE[snake.heading]:
            snake.heading = turn
        heads[who] = ahead(snake.head, snake.heading)
    food_at = {f.cell: f for f in world.foods}
    # Where each body will be once all have moved: a tail moves on unless the snake grows.
    bodies = {}
    for who, snake in moving.items():
        keeps_tail = snake.grow > 0 or heads[who] in food_at
        bodies[who] = [heads[who], *(snake.body if keeps_tail else snake.body[:-1])]

    crashed: dict[str, str] = {}
    for who, snake in moving.items():
        head = heads[who]
        if not world.inside(head):
            crashed[who] = "wall"
        elif head in bodies[who][1:]:
            crashed[who] = "self"
        else:
            for other, theirs in moving.items():
                if other == who:
                    continue
                swapped = head == theirs.head and heads[other] == snake.head
                if head == heads[other] or swapped:
                    crashed[who] = "head"
                    break
                if head in bodies[other]:
                    crashed[who] = "body"

    for who, snake in moving.items():
        if who in crashed:
            cell = heads[who] if world.inside(heads[who]) else snake.head
            snake.body, snake.grow = [], 0
            snake.back_at = world.tick + world.ticks(OUT_SECONDS)
            snake.score -= CRASH_POINTS
            snake.crashes += 1
            events.append({"kind": "crash", "who": who, "cell": cell, "how": crashed[who]})
            continue
        food = food_at.get(heads[who])
        if snake.grow > 0 and food is None:
            snake.grow -= 1
        snake.body = bodies[who]
        if food is not None:
            world.foods.remove(food)
            snake.score += food.points
            if food.kind == "gold":
                snake.golds += 1
                world.next_gold = world.tick + world.ticks(GOLD_EVERY_SECONDS)
            else:
                snake.apples += 1
            events.append({"kind": "eat", "who": who, "cell": food.cell, "food": food.kind, "label": food.label, "points": food.points})

    for who, snake in world.snakes.items():
        if not snake.alive and snake.back_at <= world.tick and _come_back(world, who):
            events.append({"kind": "back", "who": who, "cell": snake.head})

    for food in [f for f in world.foods if f.until and f.until <= world.tick]:
        world.foods.remove(food)
        world.next_gold = world.tick + world.ticks(GOLD_EVERY_SECONDS)
        events.append({"kind": "gone", "label": food.label, "cell": food.cell})
    if not any(f.kind == "gold" for f in world.foods) and world.tick >= world.next_gold:
        if gold := _place(world, "gold"):
            events.append({"kind": "gold", "label": gold.label, "cell": gold.cell})
    while sum(1 for f in world.foods if f.kind == "apple") < world.apples and _place(world, "apple"):
        pass
    return events


def _come_back(world: World, who: str) -> bool:
    """Puts a crashed snake back as one cell that grows out to its starting length, where it has
    room ahead and is far from the other heads."""
    heads = [s.head for s in world.others(who).values() if s.alive]
    taken = _taken(world)
    best: list[tuple[int, Cell, str]] = []
    for cell in _free(world):
        for way in DIRS:
            run = [ahead(cell, way)]
            for _ in range(3):
                run.append(ahead(run[-1], way))
            if all(world.inside(c) and c not in taken for c in run):
                best.append((min((_steps(cell, hd) for hd in heads), default=99), cell, way))
    if not best:
        return False
    best.sort(reverse=True)
    _, cell, way = world.rng.choice(best[: max(1, len(best) // 5)])
    snake = world.snakes[who]
    snake.body, snake.heading, snake.grow = [cell], way, START_LEN - 1
    return True


def _place(world: World, kind: str) -> Food | None:
    cells = [c for c in _free(world) if _far(world, c)]
    if kind == "gold":
        # a race: the two nearest heads about as far from it
        heads = [s.head for s in world.snakes.values() if s.alive]
        if len(heads) >= 2:

            def gap(cell: Cell) -> int:
                near = sorted(_steps(hd, cell) for hd in heads)
                return near[1] - near[0]

            cells = [c for c in cells if gap(c) <= 4] or cells
    if not cells:
        return None
    food = Food(_label(world), world.rng.choice(cells), kind)
    if kind == "gold":
        food.until = world.tick + world.ticks(GOLD_LASTS_SECONDS)
    world.foods.append(food)
    return food


def _label(world: World) -> str:
    """The next letter not on the board: letters go round A to Z, so one the AI was told about
    isn't given to another food for a good while."""
    used = {f.label for f in world.foods}
    for i in range(26):
        letter = string.ascii_uppercase[(world.labels + i) % 26]
        if letter not in used:
            world.labels += i + 1
            return letter
    raise RuntimeError("no free label")  # never: there are only a few foods at a time


def _taken(world: World) -> set[Cell]:
    return {c for s in world.snakes.values() for c in s.body}


def _free(world: World) -> list[Cell]:
    taken = _taken(world) | {f.cell for f in world.foods}
    return [(x, y) for y in range(world.h) for x in range(world.w) if (x, y) not in taken]


def _far(world: World, cell: Cell) -> bool:
    return all(_steps(s.head, cell) >= NEAR for s in world.snakes.values() if s.alive)


def _steps(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# ------------------------------------------------------------ finding the way


def blocked(world: World, who: str = "") -> set[Cell]:
    """The cells bodies may hold on the next tick, as ``who`` sees them: its own tail moves on
    and leaves its cell free (unless it grows); the others' tails may not (they may eat)."""
    cells: set[Cell] = set()
    for side, snake in world.snakes.items():
        if snake.alive:
            moves_on = side == who and snake.grow == 0 and len(snake.body) > 1
            cells.update(snake.body[:-1] if moves_on else snake.body)
    return cells


def path(world: World, start: Cell, goal: Cell, walls: set[Cell]) -> list[Cell]:
    """The shortest way from ``start`` to ``goal`` (both in it) not through ``walls``; [] when
    there is none."""
    if start == goal:
        return [start]
    came: dict[Cell, Cell] = {start: start}
    queue = collections.deque([start])
    while queue:
        cell = queue.popleft()
        for way in DIRS:
            nxt = ahead(cell, way)
            if nxt in came or not world.inside(nxt) or (nxt in walls and nxt != goal):
                continue
            came[nxt] = cell
            if nxt == goal:
                out = [goal]
                while out[-1] != start:
                    out.append(came[out[-1]])
                return out[::-1]
            queue.append(nxt)
    return []


def room(world: World, start: Cell, walls: set[Cell], cap: int) -> int:
    """How many cells can be reached from ``start`` (itself included), counted up to ``cap``."""
    if not world.inside(start) or start in walls:
        return 0
    seen = {start}
    queue = collections.deque([start])
    while queue and len(seen) < cap:
        cell = queue.popleft()
        for way in DIRS:
            nxt = ahead(cell, way)
            if nxt not in seen and world.inside(nxt) and nxt not in walls:
                seen.add(nxt)
                queue.append(nxt)
    return min(len(seen), cap)


def distance(world: World, who: str, cell: Cell) -> int | None:
    """Steps from ``who``'s head to ``cell`` the way the board is now (None: it can't get there)."""
    snake = world.snakes[who]
    if not snake.alive:
        return None
    way = path(world, snake.head, cell, blocked(world, who))
    return len(way) - 1 if way else None


def pilot(world: World, who: str, goal: Cell | None) -> tuple[str, list[Cell]]:
    """An AI snake's body: the way it turns next, and the way it means to take to ``goal``.

    It goes the shortest safe way, unless that step would leave it less room than it needs or
    could meet another head; with no goal, or no way to it, it turns where there is the most
    room (straight on when that is as good)."""
    snake = world.snakes[who]
    if not snake.alive:
        return snake.heading, []
    walls = blocked(world, who)
    danger = {ahead(s.head, w) for s in world.others(who).values() if s.alive for w in DIRS}
    options = [w for w in DIRS if w != OPPOSITE[snake.heading] and world.inside(ahead(snake.head, w)) and ahead(snake.head, w) not in walls]
    if not options:
        return snake.heading, []
    need = len(snake.body) + snake.grow
    cap = need * 2 + 8
    space = {w: room(world, ahead(snake.head, w), walls | {snake.head}, cap) for w in options}
    best_space = max(space.values())
    calm = [w for w in options if ahead(snake.head, w) not in danger] or options
    if goal is not None and goal != snake.head:
        way = path(world, snake.head, goal, walls)
        if len(way) >= 2:
            turn = way_to(snake.head, way[1])
            if turn in calm and space[turn] >= min(need, best_space):
                return turn, way
    order = list(DIRS)
    turn = max(calm, key=lambda w: (min(space[w], cap), w == snake.heading, -order.index(w)))
    return turn, []


def greedy(world: World, who: str) -> list[str]:
    """The practice snake's whole mind: the food it gets to first for the fewest steps per point."""
    best: list[tuple[int, float, str]] = []
    for food in world.foods:
        mine = distance(world, who, food.cell)
        if mine is None:
            continue
        if food.until and world.tick + mine > food.until:
            continue  # gone before it could get there
        theirs = [d for d in (distance(world, other, food.cell) for other in world.others(who)) if d is not None]
        first = not theirs or mine <= min(theirs)
        best.append((0 if first else 1, mine / food.points, food.label))
    best.sort()
    return [label for _, _, label in best[:1]]


# ------------------------------------------------------------ for the page and the AI


def grid(world: World, me: str, marks: dict[str, str]) -> list[str]:
    """The board as rows of characters from ``me``'s side: ``Y``/``y`` its own head and body,
    the others' heads by their ``marks`` and their bodies ``o``, food by label, ``.`` free."""
    rows = [["."] * world.w for _ in range(world.h)]
    for who, snake in world.snakes.items():
        mine = who == me
        for i, (x, y) in enumerate(snake.body):
            rows[y][x] = ("Y" if mine else marks.get(who, "O")) if i == 0 else ("y" if mine else "o")
    for food in world.foods:
        rows[food.cell[1]][food.cell[0]] = food.label
    return ["".join(r) for r in rows]


def frame(world: World, names: dict[str, str], aims: dict[str, tuple[Cell | None, list[Cell]]], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the page's arena draws for one tick: each snake (by id, with its name), the
    food, where each AI snake is heading and the way it means to take, and what just happened."""

    def snake(who: str, s: Snake) -> dict[str, Any]:
        out = max(0.0, world.seconds(s.back_at - world.tick)) if not s.alive else 0.0
        return {"id": who, "n": names.get(who, who), "body": [list(c) for c in s.body], "dir": s.heading, "out": round(out, 1)}

    return {
        "w": world.w,
        "h": world.h,
        "t": world.tick,
        "ms": world.tick_ms,
        "snakes": [snake(who, s) for who, s in world.snakes.items()],
        "food": [
            {"l": f.label, "x": f.cell[0], "y": f.cell[1], "k": f.kind, "ttl": round(world.seconds(f.until - world.tick), 1) if f.until else 0}
            for f in world.foods
        ],
        "aims": [{"id": who, "aim": list(aim), "way": [list(c) for c in way[1:]]} for who, (aim, way) in aims.items() if aim],
        "fx": [{**e, "cell": list(e["cell"])} for e in events if "cell" in e],
    }
