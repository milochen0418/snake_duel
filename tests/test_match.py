from snake_duel import brain, engine, history
from snake_duel.brain import Target
from snake_duel.match import MIN_GAP, REASK, RETRY, Asked, Match


def test_asks_at_once_then_waits_for_the_answer():
    m = Match("hub", "zh", "normal", 60, seed=1)
    assert list(m.seats) == ["ai1"] and not m.crowd
    assert m.due("ai1", 0.0)
    system, messages = m.ask("ai1", 0.0)
    assert "雙蛇搶食" in system and messages[0]["content"].startswith("剩 60 秒")
    assert not m.due("ai1", 10.0)  # one ask at a time


def test_an_answer_becomes_the_plan():
    m = Match("hub", "zh", "normal", 60, seed=1)
    seat, label = m.seats["ai1"], m.world.foods[0].label
    m.ask("ai1", 0.0)
    d = m.take("ai1", Asked(text=f"目標：{label}\n說：我來了", model="Ollama (qwen2.5:7b)", stop="end_turn", secs=1.2), 1.2)
    assert seat.plan == [Target(label=label)] and m.target("ai1") == m.world.foods[0].cell
    assert seat.aim == m.world.foods[0].cell and seat.way[0] == m.world.snakes["ai1"].head
    assert (d.who, d.name, d.aim, d.words, d.secs, d.tone) == ("ai1", "AI", label, "我來了", "1.2", "ok")
    assert m.model == "Ollama (qwen2.5:7b)" and seat.words == "我來了"
    assert not m.due("ai1", 1.2 + REASK - 0.1)
    assert m.due("ai1", 1.2 + REASK)


def test_asks_again_when_the_plan_runs_out_or_a_gold_shows_up():
    m = Match("hub", "zh", "normal", 60, seed=1)
    m.ask("ai1", 0.0)
    m.take("ai1", Asked(text="目標：Q", secs=1.0), 1.0)  # no food Q: nothing to go for
    assert m.target("ai1") is None and m.due("ai1", 1.0 + MIN_GAP)
    label = m.world.foods[0].label
    m.ask("ai1", 2.0)
    m.take("ai1", Asked(text=f"目標：{label}", secs=1.0), 3.0)
    assert not m.due("ai1", 3.5)
    m.seats["ai1"].gold_new = True
    assert m.due("ai1", 3.5)


def test_a_failed_ask_keeps_the_plan_and_waits_before_the_next():
    m = Match("hub", "en", "normal", 60, seed=1)
    seat, label = m.seats["ai1"], m.world.foods[0].label
    m.ask("ai1", 0.0)
    m.take("ai1", Asked(text=f"Target: {label}", secs=1.0), 1.0)
    m.ask("ai1", 5.0)
    d = m.take("ai1", Asked(error="the AI Hub didn't answer", secs=0.1), 5.1)
    assert d.tone == "failed" and seat.note == "the AI Hub didn't answer" and seat.failed == 1
    assert seat.plan == [Target(label=label)]
    seat.plan = []
    assert not m.due("ai1", 5.1 + RETRY - 0.1) and m.due("ai1", 5.1 + RETRY)
    m.ask("ai1", 9.0)
    m.take("ai1", Asked(text="", stop="max_tokens", secs=30.0), 39.0)
    assert seat.failed == 2 and "ran out of words" in seat.note
    assert seat.secs == [1.0]  # only real answers count for the time to decide


def test_an_answer_off_format_still_counts_but_is_marked():
    m = Match("hub", "zh", "normal", 60, seed=1)
    label = m.world.foods[1].label
    m.ask("ai1", 0.0)
    d = m.take("ai1", Asked(text=f"我覺得 {label} 最好", secs=2.0), 2.0)
    assert d.tone == "odd" and m.seats["ai1"].bad == 1 and m.seats["ai1"].plan == [Target(label=label)]


def test_the_persons_turns_are_taken_one_a_tick():
    m = Match("practice", "zh", "normal", 60, seed=1)
    turns = ["left", "right", "down", "left"]  # heading right: left is no turn, right no change
    m.step(turns)
    assert m.world.snakes["you"].heading == "down" and turns == ["left"]
    m.step(turns)
    assert m.world.snakes["you"].heading == "left" and turns == []


def test_the_practice_snake_plans_at_once():
    m = Match("practice", "en", "normal", 60, seed=1)
    plan = m.ask("ai1", 0.0)
    assert isinstance(plan, list) and len(plan) == 1 and m.world.food(plan[0].label)
    d = m.take("ai1", Asked(plan=plan, secs=0.8), 0.8)
    assert d.tone == "ok" and m.target("ai1") == m.world.food(plan[0].label).cell


def test_each_snake_of_a_crowd_asks_for_itself():
    m = Match("hub", "zh", "normal", 60, ais=3, seed=1)
    assert m.crowd and list(m.seats) == ["ai1", "ai2", "ai3"] and len(m.world.snakes) == 4
    assert [s.name for s in m.seats.values()] == ["AI 1", "AI 2", "AI 3"]
    system, messages = m.ask("ai2", 0.0)
    assert system == m.ask("ai1", 0.0)[0] and "你（AI 2）" in messages[0]["content"]  # the same rules for all
    assert not m.due("ai2", 1.0) and not m.due("ai1", 1.0) and m.due("ai3", 1.0)
    label = m.world.foods[0].label
    d = m.take("ai2", Asked(text=f"目標：{label}\n說：讓開", secs=1.0), 1.0)
    assert (d.who, d.name) == ("ai2", "AI 2") and m.seats["ai2"].plan and not m.seats["ai1"].plan
    f = m.frame()
    assert [s["id"] for s in f["snakes"]] == ["you", "ai1", "ai2", "ai3"] and [a["id"] for a in f["aims"]] == ["ai2"]


def play(m: Match) -> None:
    """Plays a match to its end: the practice snakes answer 0.8 s after each ask, and the person's
    snake is steered by the same body, towards the food it gets to first."""
    now, pending = 0.0, {}
    tick = m.world.tick_ms / 1000
    while not m.world.over:
        now += tick
        for sid, (plan, at) in list(pending.items()):
            if now >= at:
                m.take(sid, Asked(plan=plan, secs=0.8), now)
                del pending[sid]
        turns = []
        if m.world.snakes["you"].alive and (plan := engine.greedy(m.world, "you")):
            turns = [engine.pilot(m.world, "you", m.world.food(plan[0]).cell)[0]]
        m.step(turns)
        for sid in m.seats:
            if sid not in pending and m.due(sid, now):
                pending[sid] = (m.ask(sid, now), now + 0.8)


def test_a_whole_match_against_the_practice_snake():
    m = Match("practice", "zh", "fast", 60, seed=2)
    play(m)
    s = m.summary(60)
    assert s["model"] == history.PRACTICE and s["mode"] == "duel" and s["snakes"] == 2
    assert s["asks"] == len(m.seats["ai1"].decisions) > 5
    for side in (s["you"], *s["ais"]):
        assert side["score"] == side["apples"] + 3 * side["golds"] - 3 * side["crashes"]
    assert s["ais"][0]["apples"] + s["ais"][0]["golds"] > 3
    assert s["ask_secs"] == 0.8


def test_a_whole_free_for_all_of_practice_snakes():
    m = Match("practice", "en", "fast", 60, ais=4, seed=3)
    play(m)
    s = m.summary(60)
    assert s["mode"] == "crowd" and s["snakes"] == 5 and len(s["ais"]) == 4
    for side in (s["you"], *s["ais"]):
        assert side["score"] == side["apples"] + 3 * side["golds"] - 3 * side["crashes"]
    assert all(a["asks"] > 5 and a["apples"] > 0 for a in s["ais"])
    assert s["asks"] == sum(a["asks"] for a in s["ais"])


def test_a_model_that_never_answered_is_still_named():
    m = Match("hub", "zh", "normal", 60, seed=1, model="Ollama (qwen3.5:9b)")
    m.ask("ai1", 0.0)
    m.take("ai1", Asked(text="", stop="max_tokens", secs=50.0), 50.0)
    assert m.summary(60)["model"] == "Ollama (qwen3.5:9b)" and m.summary(60)["ask_secs"] is None


def test_summary_of_a_match_against_the_hub():
    m = Match("hub", "zh", "slow", 120, seed=1)
    m.ask("ai1", 0.0)
    m.take("ai1", Asked(text="目標：A", model="Claude (claude-haiku-5-5)", secs=1.5), 1.5)
    m.ask("ai1", 5.0)
    m.take("ai1", Asked(text="目標：B", secs=0.5), 5.5)
    s = m.summary(120)
    assert s["model"] == "Claude (claude-haiku-5-5)" and s["speed"] == "slow" and s["seconds"] == 120
    assert s["asks"] == 2 and s["ask_secs"] == 1.0 and s["failed"] == 0 and s["bad"] == 0
    assert s["ais"][0]["asks"] == 2 and s["ais"][0]["ask_secs"] == 1.0
    assert brain.ROLE == "fast"
