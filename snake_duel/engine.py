"""The rules of the arena: two snakes on one board after the same food, moving at the same moment.

Pure Python, no Reflex. :class:`World` is a whole match; :func:`step` moves it on by one tick,
with each side's turn, and says what happened (who ate what, who crashed, who came back).

The AI's snake has a "body", :func:`pilot`: told where the AI wants to go, it takes the shortest
safe way there, steering clear of walls, bodies and the other head; told nothing, it only dodges
and never goes after food by itself. Where to go is the AI's choice (:mod:`snake_duel.brain`).

The board is ``W × H`` cells; ``(0, 0)`` is the top left, x grows to the right, y downwards.
"""

from __future__ import annotations

import collections
import dataclasses
import random
import string
from typing import Any

Cell = tuple[int, int]

W, H = 24, 16
DIRS: dict[str, Cell] = {"up": (0, -1), "right": (1, 0), "down": (0, 1), "left": (-1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
SIDES = ("you", "ai")

START_LEN = 4
APPLES = 3  # apples on the board at all times
APPLE_POINTS = 1
GOLD_POINTS = 3
CRASH_POINTS = 3  # lost on a crash
OUT_SECONDS = 2.0  # off the board after a crash
FIRST_GOLD_SECONDS = 10.0
GOLD_EVERY_SECONDS = 12.0  # after the last one was eaten or vanished
GOLD_LASTS_SECONDS = 8.0
NEAR = 3  # new food lands at least this many steps from either head


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
    rng: random.Random = dataclasses.field(default_factory=random.Random)
    w: int = W
    h: int = H

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

    def other(self, who: str) -> Snake:
        return self.snakes["ai" if who == "you" else "you"]


def ahead(cell: Cell, way: str) -> Cell:
    dx, dy = DIRS[way]
    return (cell[0] + dx, cell[1] + dy)


def way_to(a: Cell, b: Cell) -> str:
    """The direction of a step from ``a`` to the next cell ``b``."""
    return next(d for d, (dx, dy) in DIRS.items() if (a[0] + dx, a[1] + dy) == b)


def new_world(tick_ms: int, seconds: int, seed: int | None = None) -> World:
    """Both snakes at their starting places, facing each other across the board (the AI's place
    is the person's turned half way round), and the first apples, as near to one as the other."""
    you = Snake(body=[(6 - i, 4) for i in range(START_LEN)], heading="right")
    ai = Snake(body=[(W - 1 - x, H - 1 - y) for x, y in you.body], heading="left")
    world = World(tick_ms=tick_ms, end=0, snakes={"you": you, "ai": ai}, rng=random.Random(seed))
    world.end = world.ticks(seconds)
    world.next_gold = world.ticks(FIRST_GOLD_SECONDS)
    fair = [c for c in _free(world) if _far(world, c) and _steps(you.head, c) == _steps(ai.head, c)]
    for cell in world.rng.sample(fair, APPLES):
        world.foods.append(Food(_label(world), cell, "apple"))
    return world


# ------------------------------------------------------------ a tick


def step(world: World, turns: dict[str, str | None]) -> list[dict[str, Any]]:
    """Moves the world on by one tick: each snake turns (or not) and both move at once; then
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
    # Where each body will be once both have moved: a tail moves on unless the snake grows.
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
                elif head in bodies[other]:
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
    while sum(1 for f in world.foods if f.kind == "apple") < APPLES and _place(world, "apple"):
        pass
    return events


def _come_back(world: World, who: str) -> bool:
    """Puts a crashed snake back as one cell that grows out to its starting length, where it has
    room ahead and is far from the other head."""
    other = world.other(who)
    taken = _taken(world)
    best: list[tuple[int, Cell, str]] = []
    for cell in _free(world):
        for way in DIRS:
            run = [ahead(cell, way)]
            for _ in range(3):
                run.append(ahead(run[-1], way))
            if all(world.inside(c) and c not in taken for c in run):
                far = _steps(cell, other.head) if other.alive else 99
                best.append((far, cell, way))
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
        # a race: about as far from one head as from the other
        heads = [s.head for s in world.snakes.values() if s.alive]
        fair = [c for c in cells if len(heads) < 2 or abs(_steps(heads[0], c) - _steps(heads[1], c)) <= 4]
        cells = fair or cells
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
    and leaves its cell free (unless it grows); the other's tail may not (it may eat)."""
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
    """The AI snake's body: the way it turns next, and the way it means to take to ``goal``.

    It goes the shortest safe way, unless that step would leave it less room than it needs or
    could meet the other head; with no goal, or no way to it, it turns where there is the most
    room (straight on when that is as good)."""
    snake = world.snakes[who]
    if not snake.alive:
        return snake.heading, []
    walls = blocked(world, who)
    other = world.other(who)
    danger = {ahead(other.head, w) for w in DIRS} if other.alive else set()
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
    other = "ai" if who == "you" else "you"
    best: list[tuple[int, float, str]] = []
    for food in world.foods:
        mine = distance(world, who, food.cell)
        if mine is None:
            continue
        theirs = distance(world, other, food.cell)
        first = theirs is None or mine <= theirs
        if food.until and world.tick + mine > food.until:
            continue  # gone before it could get there
        best.append((0 if first else 1, mine / food.points, food.label))
    best.sort()
    return [label for _, _, label in best[:1]]


# ------------------------------------------------------------ for the page and the AI


def grid(world: World, me: str) -> list[str]:
    """The board as rows of characters from ``me``'s side: ``Y``/``y`` its own head and body,
    ``O``/``o`` the other's, food by label, ``.`` free."""
    rows = [["."] * world.w for _ in range(world.h)]
    for who, snake in world.snakes.items():
        mine = who == me
        for i, (x, y) in enumerate(snake.body):
            rows[y][x] = ("Y" if mine else "O") if i == 0 else ("y" if mine else "o")
    for food in world.foods:
        rows[food.cell[1]][food.cell[0]] = food.label
    return ["".join(r) for r in rows]


def frame(world: World, aim: Cell | None, way: list[Cell], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the page's arena draws for one tick."""

    def side(snake: Snake) -> dict[str, Any]:
        out = max(0.0, world.seconds(snake.back_at - world.tick)) if not snake.alive else 0.0
        return {"body": [list(c) for c in snake.body], "dir": snake.heading, "out": round(out, 1)}

    return {
        "w": world.w,
        "h": world.h,
        "t": world.tick,
        "ms": world.tick_ms,
        "you": side(world.snakes["you"]),
        "ai": side(world.snakes["ai"]),
        "food": [
            {"l": f.label, "x": f.cell[0], "y": f.cell[1], "k": f.kind, "ttl": round(world.seconds(f.until - world.tick), 1) if f.until else 0}
            for f in world.foods
        ],
        "aim": list(aim) if aim else None,
        "way": [list(c) for c in way[1:]],
        "fx": [{**e, "cell": list(e["cell"])} for e in events if "cell" in e],
    }
