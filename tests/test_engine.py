import random

from snake_duel import engine
from snake_duel.engine import Food, Snake, World


def world(you: list, ai: list, you_heading: str = "right", ai_heading: str = "left", foods: list | None = None, tick_ms: int = 100) -> World:
    """A world with the snakes and food just as given (nothing placed at random)."""
    w = World(tick_ms=tick_ms, end=10_000, snakes={"you": Snake(body=you, heading=you_heading), "ai": Snake(body=ai, heading=ai_heading)}, rng=random.Random(0))
    w.foods = foods or []
    w.next_gold = 10**9
    return w


def no_apples(monkeypatch) -> None:
    monkeypatch.setattr(engine, "APPLES", 0)


def test_new_world_is_fair():
    w = engine.new_world(160, 60, seed=1)
    you, ai = w.snakes["you"], w.snakes["ai"]
    assert len(you.body) == len(ai.body) == engine.START_LEN
    assert ai.head == (w.w - 1 - you.head[0], w.h - 1 - you.head[1])
    assert len(w.foods) == engine.APPLES
    assert len({f.label for f in w.foods}) == engine.APPLES
    for f in w.foods:
        assert engine._steps(you.head, f.cell) == engine._steps(ai.head, f.cell)
    assert w.end == round(60 * 1000 / 160)


def test_moving_and_turning(monkeypatch):
    no_apples(monkeypatch)
    w = world([(5, 5), (4, 5), (3, 5)], [(15, 10), (16, 10), (17, 10)])
    engine.step(w, {})
    assert w.snakes["you"].body == [(6, 5), (5, 5), (4, 5)]
    engine.step(w, {"you": "left"})  # straight back is not a turn
    assert w.snakes["you"].head == (7, 5)
    engine.step(w, {"you": "down", "ai": "up"})
    assert w.snakes["you"].body == [(7, 6), (7, 5), (6, 5)]
    assert w.snakes["ai"].head == (13, 9)


def test_eating_grows_and_scores(monkeypatch):
    no_apples(monkeypatch)
    w = world([(5, 5), (4, 5), (3, 5)], [(15, 10), (16, 10), (17, 10)], foods=[Food("A", (6, 5), "apple"), Food("B", (14, 10), "gold")])
    events = engine.step(w, {})
    you, ai = w.snakes["you"], w.snakes["ai"]
    assert you.body == [(6, 5), (5, 5), (4, 5), (3, 5)]
    assert (you.score, you.apples, ai.score, ai.golds) == (1, 1, 3, 1)
    assert {e["label"] for e in events if e["kind"] == "eat"} == {"A", "B"}
    assert w.foods == []


def test_apples_are_put_back():
    w = world([(5, 5), (4, 5), (3, 5)], [(15, 10), (16, 10), (17, 10)], foods=[Food("A", (6, 5), "apple")])
    engine.step(w, {})
    assert sum(1 for f in w.foods if f.kind == "apple") == engine.APPLES
    assert all(engine._steps(w.snakes["you"].head, f.cell) >= engine.NEAR for f in w.foods)


def test_wall_crash_costs_points_and_comes_back(monkeypatch):
    no_apples(monkeypatch)
    w = world([(23, 5), (22, 5), (21, 5)], [(5, 10), (6, 10), (7, 10)])
    events = engine.step(w, {})
    you = w.snakes["you"]
    assert not you.alive and you.score == -engine.CRASH_POINTS and you.crashes == 1
    assert events[0]["kind"] == "crash" and events[0]["how"] == "wall" and events[0]["cell"] == (23, 5)
    for _ in range(w.ticks(engine.OUT_SECONDS) - 1):
        engine.step(w, {})
        assert not you.alive
    events = engine.step(w, {})
    assert you.alive and len(you.body) == 1 and you.grow == engine.START_LEN - 1
    assert any(e["kind"] == "back" and e["who"] == "you" for e in events)
    for _ in range(engine.START_LEN - 1):
        engine.step(w, {})
    assert len(you.body) == engine.START_LEN


def test_crash_into_self(monkeypatch):
    no_apples(monkeypatch)
    w = world([(5, 5), (5, 6), (4, 6), (4, 5), (4, 4)], [(15, 10), (16, 10), (17, 10)], you_heading="up")
    events = engine.step(w, {"you": "left"})
    assert events[0]["how"] == "self" and not w.snakes["you"].alive


def test_following_a_tail_is_safe(monkeypatch):
    no_apples(monkeypatch)
    # The person's head moves into the cell the AI's tail leaves this very tick.
    w = world([(9, 5), (8, 5)], [(10, 4), (10, 5), (11, 5)], ai_heading="up")
    w.snakes["ai"].body = [(10, 4), (10, 5)]
    w.snakes["you"].heading = "right"
    engine.step(w, {})
    assert w.snakes["you"].alive and w.snakes["you"].head == (10, 5)


def test_heads_meeting_crash_both(monkeypatch):
    no_apples(monkeypatch)
    w = world([(5, 5), (4, 5), (3, 5)], [(7, 5), (8, 5), (9, 5)])
    events = engine.step(w, {})
    assert {e["who"]: e["how"] for e in events} == {"you": "head", "ai": "head"}
    assert w.snakes["you"].score == w.snakes["ai"].score == -engine.CRASH_POINTS


def test_heads_swapping_crash_both(monkeypatch):
    no_apples(monkeypatch)
    w = world([(5, 5), (4, 5), (3, 5)], [(6, 5), (7, 5), (8, 5)])
    engine.step(w, {})
    assert not w.snakes["you"].alive and not w.snakes["ai"].alive


def test_running_into_the_other_body(monkeypatch):
    no_apples(monkeypatch)
    w = world([(5, 4), (4, 4), (3, 4)], [(8, 5), (7, 5), (6, 5), (5, 5), (4, 5)], you_heading="right", ai_heading="right")
    events = engine.step(w, {"you": "down"})
    assert events[0]["who"] == "you" and events[0]["how"] == "body"
    assert w.snakes["ai"].alive


def test_gold_comes_and_goes(monkeypatch):
    no_apples(monkeypatch)
    w = world([(5, 5), (4, 5), (3, 5)], [(15, 10), (16, 10), (17, 10)], tick_ms=500)
    w.next_gold = 2
    engine.step(w, {})
    assert not any(f.kind == "gold" for f in w.foods)
    events = engine.step(w, {})
    golds = [f for f in w.foods if f.kind == "gold"]
    assert len(golds) == 1 and any(e["kind"] == "gold" for e in events)
    gold = golds[0]
    assert gold.until == w.tick + w.ticks(engine.GOLD_LASTS_SECONDS)
    heads = [s.head for s in w.snakes.values()]
    assert abs(engine._steps(heads[0], gold.cell) - engine._steps(heads[1], gold.cell)) <= 4  # a race
    for snake in w.snakes.values():  # both off the board, so nobody eats it
        snake.body, snake.back_at = [], 10**9
    while w.tick < gold.until - 1:
        assert not any(e["kind"] == "gone" for e in engine.step(w, {}))
    events = engine.step(w, {})
    assert any(e["kind"] == "gone" and e["label"] == gold.label for e in events)
    assert not any(f.kind == "gold" for f in w.foods)
    assert w.next_gold == w.tick + w.ticks(engine.GOLD_EVERY_SECONDS)


def test_labels_go_round_and_skip_the_ones_in_use():
    w = world([(5, 5)], [(15, 10)])
    w.foods = [Food("C", (1, 1), "apple")]
    w.labels = 2
    assert engine._label(w) == "D"
    w.labels = 25
    assert engine._label(w) == "Z"
    assert engine._label(w) == "A"


def test_own_tail_moves_on_but_not_the_others():
    w = world([(5, 5), (4, 5), (3, 5)], [(15, 10), (16, 10), (17, 10)])
    assert (3, 5) not in engine.blocked(w, "you") and (17, 10) in engine.blocked(w, "you")
    assert (3, 5) in engine.blocked(w, "ai") and (17, 10) not in engine.blocked(w, "ai")
    w.snakes["ai"].grow = 1
    assert (17, 10) in engine.blocked(w, "ai")


def test_path_and_room():
    w = world([(0, 0)], [(23, 15)])
    walls = {(1, y) for y in range(0, 15)}
    way = engine.path(w, (0, 0), (2, 0), walls)
    assert way[0] == (0, 0) and way[-1] == (2, 0)
    assert len(way) - 1 == 15 + 1 + 15 + 1  # down the wall, round its end, back up
    assert engine.path(w, (0, 0), (2, 0), walls | {(1, 15)}) == []
    assert engine.room(w, (0, 0), walls | {(1, 15)}, cap=1000) == 16


def test_pilot_takes_the_shortest_way():
    w = world([(2, 2), (1, 2), (0, 2)], [(10, 10), (11, 10), (12, 10)])
    turn, way = engine.pilot(w, "ai", (10, 5))
    assert turn == "up" and way[-1] == (10, 5) and len(way) == 6


def test_pilot_without_a_goal_keeps_room():
    # Heading up along the left wall at the top: up is the wall, so it turns right.
    w = world([(20, 14), (19, 14)], [(0, 0), (0, 1), (0, 2)], ai_heading="up")
    turn, way = engine.pilot(w, "ai", None)
    assert turn == "right" and way == []


def test_pilot_stays_off_the_cell_next_to_the_other_head():
    # The food is right between both heads: the AI turns away rather than meet the person's head.
    w = world([(10, 4), (9, 4), (8, 4)], [(12, 4), (13, 4), (14, 4)], foods=[Food("A", (11, 4), "apple")])
    turn, _ = engine.pilot(w, "ai", (11, 4))
    assert turn in ("up", "down")


def corridor(ai_len: int) -> World:
    """The top row from x=0 to 10 is a dead end, closed by the person's (growing) body along
    y=1; the AI's head is at its mouth, the food inside."""
    you = [(0, 5), (0, 4), (0, 3), (0, 2), *[(x, 1) for x in range(0, 11)]]
    ai = [(11 + i, 0) for i in range(min(ai_len, 13))] + [(23, y) for y in range(1, ai_len - 12)]
    w = world(you, ai, you_heading="down", foods=[Food("A", (2, 0), "apple")])
    w.snakes["you"].grow = 1  # its tail stays put: the dead end stays closed
    return w


def test_pilot_does_not_crawl_into_a_dead_end():
    w = corridor(14)
    assert engine.room(w, (10, 0), engine.blocked(w, "ai") | {(11, 0)}, cap=100) == 11
    assert engine.pilot(w, "ai", (2, 0))[0] == "down"  # 11 cells can't hold 14


def test_pilot_goes_into_a_dead_end_it_fits_in():
    assert engine.pilot(corridor(4), "ai", (2, 0))[0] == "left"


def test_greedy_goes_for_food_it_gets_to_first():
    w = world([(2, 2), (1, 2)], [(20, 10), (21, 10)], foods=[Food("A", (4, 2), "apple"), Food("B", (16, 10), "apple")])
    assert engine.greedy(w, "ai") == ["B"]
    assert engine.greedy(w, "you") == ["A"]


def test_greedy_skips_gold_it_cannot_reach_in_time():
    w = world([(2, 2), (1, 2)], [(20, 10), (21, 10)], foods=[Food("G", (5, 10), "gold", until=3), Food("B", (16, 2), "apple")])
    assert engine.greedy(w, "ai") == ["B"]


def test_frame_has_what_the_page_draws():
    w = engine.new_world(160, 60, seed=3)
    f = engine.frame(w, (3, 4), [(17, 11), (16, 11)], [{"kind": "eat", "cell": (1, 2), "who": "you", "food": "apple", "points": 1}])
    assert f["you"]["body"][0] == [6, 4] and f["ai"]["dir"] == "left"
    assert f["aim"] == [3, 4] and f["way"] == [[16, 11]]
    assert f["fx"][0]["cell"] == [1, 2]
    assert len(f["food"]) == engine.APPLES
