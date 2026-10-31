from snake_duel import brain, engine, history
from snake_duel.brain import Target
from snake_duel.match import MIN_GAP, REASK, RETRY, Asked, Match


def duel(**changes) -> Match:
    return Match("hub", "zh", "normal", 60, ["小明"], 2, seed=1, **changes)


def test_asks_at_once_then_waits_for_the_answer():
    m = duel()
    assert list(m.seats) == ["s1", "s2"] and list(m.ai_seats) == ["s2"]
    assert m.due("s2", 0.0) and not m.due("s1", 0.0)  # a person is never asked
    system, messages = m.ask("s2", 0.0)
    assert "雙蛇搶食" in system and messages[0]["content"].startswith("剩 60 秒")
    assert not m.due("s2", 10.0)  # one ask at a time


def test_an_answer_becomes_the_plan():
    m = duel()
    seat, label = m.seats["s2"], m.world.foods[0].label
    m.ask("s2", 0.0)
    d = m.take("s2", Asked(text=f"目標：{label}\n說：我來了", model="Ollama (qwen2.5:7b)", stop="end_turn", secs=1.2), 1.2)
    assert seat.plan == [Target(label=label)] and m.target("s2") == m.world.foods[0].cell
    assert seat.aim == m.world.foods[0].cell and seat.way[0] == m.world.snakes["s2"].head
    assert (d.who, d.name, d.aim, d.words, d.secs, d.tone) == ("s2", "AI", label, "我來了", "1.2", "ok")
    assert m.model == "Ollama (qwen2.5:7b)" and seat.words == "我來了" and seat.asks == 1
    assert not m.due("s2", 1.2 + REASK - 0.1)
    assert m.due("s2", 1.2 + REASK)


def test_asks_again_when_the_plan_runs_out_or_a_gold_shows_up():
    m = duel()
    m.ask("s2", 0.0)
    m.take("s2", Asked(text="目標：Q", secs=1.0), 1.0)  # no food Q: nothing to go for
    assert m.target("s2") is None and m.due("s2", 1.0 + MIN_GAP)
    label = m.world.foods[0].label
    m.ask("s2", 2.0)
    m.take("s2", Asked(text=f"目標：{label}", secs=1.0), 3.0)
    assert not m.due("s2", 3.5)
    m.seats["s2"].gold_new = True
    assert m.due("s2", 3.5)


def test_a_failed_ask_keeps_the_plan_and_waits_before_the_next():
    m = Match("hub", "en", "normal", 60, ["P"], 2, seed=1)
    seat, label = m.seats["s2"], m.world.foods[0].label
    m.ask("s2", 0.0)
    m.take("s2", Asked(text=f"Target: {label}", secs=1.0), 1.0)
    m.ask("s2", 5.0)
    d = m.take("s2", Asked(error="the AI Hub didn't answer", secs=0.1), 5.1)
    assert d.tone == "failed" and seat.note == "the AI Hub didn't answer" and seat.failed == 1
    assert seat.plan == [Target(label=label)]
    seat.plan = []
    assert not m.due("s2", 5.1 + RETRY - 0.1) and m.due("s2", 5.1 + RETRY)
    m.ask("s2", 9.0)
    m.take("s2", Asked(text="", stop="max_tokens", secs=30.0), 39.0)
    assert seat.failed == 2 and "ran out of words" in seat.note
    assert seat.secs == [1.0]  # only real answers count for the time to decide


def test_an_answer_off_format_still_counts_but_is_marked():
    m = duel()
    label = m.world.foods[1].label
    m.ask("s2", 0.0)
    d = m.take("s2", Asked(text=f"我覺得 {label} 最好", secs=2.0), 2.0)
    assert d.tone == "odd" and m.seats["s2"].bad == 1 and m.seats["s2"].plan == [Target(label=label)]


def test_each_persons_turns_are_taken_one_a_tick():
    m = Match("practice", "zh", "normal", 60, ["小明", "阿美"], 3, seed=1)
    you = m.world.snakes["s1"]
    own = you.heading
    side = "left" if own in ("up", "down") else "up"
    turns = {"s1": [own, engine.OPPOSITE[own], side, own]}  # its own way and straight back are no turns
    m.step(turns)
    assert you.heading == side and turns["s1"] == [own]
    m.step(turns)
    assert you.heading == own and turns["s1"] == []


def test_the_people_take_the_first_seats_and_ai_snakes_fill_the_rest():
    m = Match("practice", "zh", "normal", 60, ["小明", "阿美"], 5, seed=1)
    assert m.people == 2 and m.total == 5
    assert [s.kind for s in m.seats.values()] == ["person", "person", "ai", "ai", "ai"]
    assert [s.name for s in m.seats.values()] == ["小明", "阿美", "AI 1", "AI 2", "AI 3"]
    assert list(m.ai_seats) == ["s3", "s4", "s5"]
    assert [s["k"] for s in m.frame()["snakes"]] == ["person", "person", "ai", "ai", "ai"]
    more = Match("practice", "zh", "normal", 60, ["a", "b", "c", "d", "e", "f"], 9, seed=1)
    assert more.total == engine.MAX_SNAKES and more.people == 5 and more.ai_seats == {}


def test_a_snake_handed_to_an_ai_keeps_its_name_and_is_asked():
    m = Match("practice", "zh", "normal", 60, ["小明", "阿美"], 3, seed=1)
    assert not m.due("s2", 1.0)
    m.hand_to_ai("s2")
    seat = m.seats["s2"]
    assert seat.kind == "ai" and seat.left and seat.name == "阿美"
    assert m.due("s2", 1.0) and list(m.ai_seats) == ["s2", "s3"]
    assert m.frame()["snakes"][1]["k"] == "ai"


def test_a_person_takes_a_snake_from_an_ai():
    m = Match("practice", "zh", "normal", 60, ["小明"], 3, seed=1)
    m.seats["s2"].plan = [Target(label="A")]
    m.hand_to_person("s2", "阿美", "pic")
    seat = m.seats["s2"]
    assert (seat.kind, seat.name, seat.avatar, seat.plan) == ("person", "阿美", "pic", [])
    assert not m.due("s2", 1.0) and m.frame()["snakes"][1]["k"] == "person" and m.frame()["snakes"][1]["n"] == "阿美"
    m.step({"s2": ["down"]})  # steered by keys now


def test_someone_coming_back_keeps_their_name():
    m = Match("practice", "zh", "normal", 60, ["小明", "阿美"], 3, seed=1)
    m.hand_to_ai("s2")
    m.hand_to_person("s2")
    assert (m.seats["s2"].kind, m.seats["s2"].name, m.seats["s2"].left) == ("person", "阿美", False)


def test_a_match_of_people_only_is_kept_as_that():
    m = Match("hub", "zh", "normal", 60, ["小明", "阿美"], 2, seed=1, model="Ollama (x)")
    assert m.summary(60)["model"] == history.PEOPLE and m.summary(60)["people"] == 2
    m.hand_to_ai("s2")
    assert m.summary(60)["model"] == "Ollama (x)" and m.summary(60)["people"] == 2  # an AI played too


def test_a_person_who_took_a_snake_over_counts():
    m = Match("practice", "zh", "normal", 60, ["小明"], 3, seed=1)
    m.hand_to_person("s2", "阿美")
    assert m.summary(60)["people"] == 2


def test_the_practice_snake_plans_at_once():
    m = Match("practice", "en", "normal", 60, ["P"], 2, seed=1)
    plan = m.ask("s2", 0.0)
    assert isinstance(plan, list) and len(plan) == 1 and m.world.food(plan[0].label)
    d = m.take("s2", Asked(plan=plan, secs=0.8), 0.8)
    assert d.tone == "ok" and m.target("s2") == m.world.food(plan[0].label).cell


def test_each_snake_of_a_crowd_asks_for_itself():
    m = Match("hub", "zh", "normal", 60, ["小明"], 4, seed=1)
    assert list(m.ai_seats) == ["s2", "s3", "s4"]
    system, messages = m.ask("s3", 0.0)
    assert system == m.ask("s2", 0.0)[0] and "你是 3 號（AI 2）" in messages[0]["content"]  # the same rules for all
    assert not m.due("s3", 1.0) and not m.due("s2", 1.0) and m.due("s4", 1.0)
    label = m.world.foods[0].label
    d = m.take("s3", Asked(text=f"目標：{label}\n說：讓開", secs=1.0), 1.0)
    assert (d.who, d.name) == ("s3", "AI 2") and m.seats["s3"].plan and not m.seats["s4"].plan
    f = m.frame()
    assert [s["id"] for s in f["snakes"]] == ["s1", "s2", "s3", "s4"] and [a["id"] for a in f["aims"]] == ["s3"]


def play(m: Match) -> None:
    """Plays a match to its end: the practice snakes answer 0.8 s after each ask, and every
    person's snake is steered by the same body, towards the food it gets to first."""
    now, pending = 0.0, {}
    tick = m.world.tick_ms / 1000
    while not m.world.over:
        now += tick
        for sid, (plan, at) in list(pending.items()):
            if now >= at:
                m.take(sid, Asked(plan=plan, secs=0.8), now)
                del pending[sid]
        turns = {}
        for sid, seat in m.seats.items():
            if seat.kind == "person" and m.world.snakes[sid].alive and (plan := engine.greedy(m.world, sid)):
                turns[sid] = [engine.pilot(m.world, sid, m.world.food(plan[0]).cell)[0]]
        m.step(turns)
        for sid in m.ai_seats:
            if sid not in pending and m.due(sid, now):
                pending[sid] = (m.ask(sid, now), now + 0.8)


def test_a_whole_match_against_the_practice_snake():
    m = Match("practice", "zh", "fast", 60, ["小明"], 2, seed=2)
    play(m)
    s = m.summary(60)
    assert s["model"] == history.PRACTICE and s["snakes"] == 2 and s["people"] == 1
    assert [side["kind"] for side in s["sides"]] == ["person", "ai"]
    assert s["asks"] == m.seats["s2"].asks > 5
    for side in s["sides"]:
        assert side["score"] == side["apples"] + 3 * side["golds"] - 3 * side["crashes"]
    assert s["sides"][1]["apples"] + s["sides"][1]["golds"] > 3
    assert s["ask_secs"] == 0.8


def test_a_whole_match_of_two_people_and_three_practice_snakes():
    m = Match("practice", "en", "fast", 60, ["小明", "阿美"], 5, seed=3)
    play(m)
    s = m.summary(60)
    assert s["snakes"] == 5 and s["people"] == 2 and len(s["sides"]) == 5
    for side in s["sides"]:
        assert side["score"] == side["apples"] + 3 * side["golds"] - 3 * side["crashes"]
    ais = [side for side in s["sides"] if side["kind"] == "ai"]
    assert all(side["asks"] > 5 and side["apples"] > 0 for side in ais)
    assert s["asks"] == sum(side["asks"] for side in ais)
    assert all(side["apples"] > 0 for side in s["sides"] if side["kind"] == "person")


def test_a_model_that_never_answered_is_still_named():
    m = duel(model="Ollama (qwen3.5:9b)")
    m.ask("s2", 0.0)
    m.take("s2", Asked(text="", stop="max_tokens", secs=50.0), 50.0)
    assert m.summary(60)["model"] == "Ollama (qwen3.5:9b)" and m.summary(60)["ask_secs"] is None


def test_summary_of_a_match_against_the_hub():
    m = Match("hub", "zh", "slow", 120, ["小明"], 2, seed=1)
    m.ask("s2", 0.0)
    m.take("s2", Asked(text="目標：A", model="Claude (claude-haiku-5-5)", secs=1.5), 1.5)
    m.ask("s2", 5.0)
    m.take("s2", Asked(text="目標：B", secs=0.5), 5.5)
    s = m.summary(120)
    assert s["model"] == "Claude (claude-haiku-5-5)" and s["speed"] == "slow" and s["seconds"] == 120
    assert s["asks"] == 2 and s["ask_secs"] == 1.0 and s["failed"] == 0 and s["bad"] == 0
    assert s["sides"][1]["asks"] == 2 and s["sides"][1]["ask_secs"] == 1.0 and s["sides"][1]["left"] is False
    assert "asks" not in s["sides"][0]  # the person
    assert brain.ROLE == "fast"
