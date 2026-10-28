from snake_duel import brain, engine, history
from snake_duel.brain import Target
from snake_duel.match import MIN_GAP, REASK, RETRY, Asked, Match


def test_asks_at_once_then_waits_for_the_answer():
    m = Match("hub", "zh", "normal", 60, seed=1)
    assert m.due(0.0)
    system, messages = m.ask(0.0)
    assert "雙蛇搶食" in system and messages[0]["content"].startswith("剩 60 秒")
    assert not m.due(10.0)  # one ask at a time


def test_an_answer_becomes_the_plan():
    m = Match("hub", "zh", "normal", 60, seed=1)
    label = m.world.foods[0].label
    m.ask(0.0)
    d = m.take(Asked(text=f"目標：{label}\n說：我來了", model="Ollama (qwen2.5:7b)", stop="end_turn", secs=1.2), 1.2)
    assert m.plan == [Target(label=label)] and m.target() == m.world.foods[0].cell
    assert m.aim == m.world.foods[0].cell and m.way[0] == m.world.snakes["ai"].head
    assert (d.aim, d.words, d.secs, d.tone) == (label, "我來了", "1.2", "ok")
    assert m.model == "Ollama (qwen2.5:7b)" and m.words == "我來了"
    assert not m.due(1.2 + REASK - 0.1)
    assert m.due(1.2 + REASK)


def test_asks_again_when_the_plan_runs_out_or_a_gold_shows_up():
    m = Match("hub", "zh", "normal", 60, seed=1)
    m.ask(0.0)
    m.take(Asked(text="目標：Q", secs=1.0), 1.0)  # no food Q: nothing to go for
    assert m.target() is None and m.due(1.0 + MIN_GAP)
    label = m.world.foods[0].label
    m.ask(2.0)
    m.take(Asked(text=f"目標：{label}", secs=1.0), 3.0)
    assert not m.due(3.5)
    m.gold_new = True
    assert m.due(3.5)


def test_a_failed_ask_keeps_the_plan_and_waits_before_the_next():
    m = Match("hub", "en", "normal", 60, seed=1)
    label = m.world.foods[0].label
    m.ask(0.0)
    m.take(Asked(text=f"Target: {label}", secs=1.0), 1.0)
    m.ask(5.0)
    d = m.take(Asked(error="the AI Hub didn't answer", secs=0.1), 5.1)
    assert d.tone == "failed" and m.note == "the AI Hub didn't answer" and m.failed == 1
    assert m.plan == [Target(label=label)]
    m.plan = []
    assert not m.due(5.1 + RETRY - 0.1) and m.due(5.1 + RETRY)
    m.ask(9.0)
    m.take(Asked(text="", stop="max_tokens", secs=30.0), 39.0)
    assert m.failed == 2 and "ran out of words" in m.note
    assert m.secs == [1.0]  # only real answers count for the time to decide


def test_an_answer_off_format_still_counts_but_is_marked():
    m = Match("hub", "zh", "normal", 60, seed=1)
    label = m.world.foods[1].label
    m.ask(0.0)
    d = m.take(Asked(text=f"我覺得 {label} 最好", secs=2.0), 2.0)
    assert d.tone == "odd" and m.bad == 1 and m.plan == [Target(label=label)]


def test_the_persons_turns_are_taken_one_a_tick():
    m = Match("practice", "zh", "normal", 60, seed=1)
    turns = ["left", "right", "down", "left"]  # heading right: left is no turn, right no change
    m.step(turns)
    assert m.world.snakes["you"].heading == "down" and turns == ["left"]
    m.step(turns)
    assert m.world.snakes["you"].heading == "left" and turns == []


def test_the_practice_snake_plans_at_once():
    m = Match("practice", "en", "normal", 60, seed=1)
    plan = m.ask(0.0)
    assert isinstance(plan, list) and len(plan) == 1 and m.world.food(plan[0].label)
    d = m.take(Asked(plan=plan, secs=0.8), 0.8)
    assert d.tone == "ok" and m.target() == m.world.food(plan[0].label).cell


def test_a_whole_match_against_the_practice_snake():
    """The practice snake plays a match against a person who always turns towards the nearest
    food: the clock runs out, both score, and the summary adds up."""
    m = Match("practice", "zh", "fast", 60, seed=2)
    now, answer_at, pending = 0.0, None, None
    tick = m.world.tick_ms / 1000
    while not m.world.over:
        now += tick
        if pending is not None and now >= answer_at:
            m.take(Asked(plan=pending, secs=0.8), now)
            pending = None
        you = m.world.snakes["you"]
        turns = []
        if you.alive and (plan := engine.greedy(m.world, "you")):
            turns = [engine.pilot(_as_ai(m.world), "ai", m.world.food(plan[0]).cell)[0]]
        m.step(turns)
        if pending is None and m.due(now):
            pending, answer_at = m.ask(now), now + 0.8
    s = m.summary(60)
    assert s["model"] == history.PRACTICE and s["asks"] == len(m.decisions) > 5
    assert s["you"]["score"] == s["you"]["apples"] + 3 * s["you"]["golds"] - 3 * s["you"]["crashes"]
    assert s["ai"]["score"] == s["ai"]["apples"] + 3 * s["ai"]["golds"] - 3 * s["ai"]["crashes"]
    assert s["ai"]["apples"] + s["ai"]["golds"] > 3
    assert s["ask_secs"] == 0.8


def _as_ai(world: engine.World) -> engine.World:
    """The same world with the sides swapped, so the AI's body can steer the person's snake."""
    return engine.World(
        tick_ms=world.tick_ms,
        end=world.end,
        snakes={"ai": world.snakes["you"], "you": world.snakes["ai"]},
        foods=world.foods,
        tick=world.tick,
    )


def test_summary_of_a_match_against_the_hub():
    m = Match("hub", "zh", "slow", 120, seed=1)
    m.ask(0.0)
    m.take(Asked(text="目標：A", model="Claude (claude-haiku-5-5)", secs=1.5), 1.5)
    m.ask(5.0)
    m.take(Asked(text="目標：B", secs=0.5), 5.5)
    s = m.summary(120)
    assert s["model"] == "Claude (claude-haiku-5-5)" and s["speed"] == "slow" and s["seconds"] == 120
    assert s["asks"] == 2 and s["ask_secs"] == 1.0 and s["failed"] == 0 and s["bad"] == 0
    assert brain.ROLE == "fast"
