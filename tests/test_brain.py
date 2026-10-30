from snake_duel import brain, engine
from snake_duel.brain import Target
from snake_duel.match import Match, Seat


def duel(**changes) -> Match:
    return Match("hub", "zh", "normal", 60, ["小明"], 2, seed=5, **changes)


def test_reads_both_languages():
    move = brain.parse("目標：B, D\n說：那顆金果是我的！")
    assert move.targets == [Target(label="B"), Target(label="D")]
    assert move.say == "那顆金果是我的！" and move.well_formed
    move = brain.parse("Target: C\nSay: Too slow!")
    assert move.targets == [Target(label="C")] and move.say == "Too slow!" and move.well_formed


def test_reads_cells_and_mixed_plans():
    assert brain.parse("目標：(12,5)\n說：擋你").targets == [Target(cell=(12, 5))]
    assert brain.parse("目標：（3，4） → A").targets == [Target(cell=(3, 4)), Target(label="A")]
    assert brain.parse("Target: 7, 9").targets == [Target(cell=(7, 9))]


def test_leaves_out_cells_off_the_board_and_keeps_three():
    move = brain.parse("Target: (24,2), (2,16), A, B, C, D", None, 24, 16)
    assert move.targets == [Target(label="A"), Target(label="B"), Target(label="C")]
    assert brain.parse("Target: (29,19)").targets == [Target(cell=(29, 19))]  # the big board by default


def test_markdown_and_thinking_are_ignored():
    move = brain.parse("<think>A is close but B is gold</think>\n**目標**：**B**\n> 說：「快讓開」")
    assert move.targets == [Target(label="B")] and move.say == "快讓開" and move.well_formed


def test_words_are_not_food():
    move = brain.parse("Target: a cell near B")
    assert move.targets == [Target(label="B")]
    assert brain.parse("Say: I go first").targets == []


def test_without_a_target_line_food_letters_count_but_not_well_formed():
    move = brain.parse("我要去 C，然後 A", {"A", "C"})
    assert move.targets == [Target(label="C"), Target(label="A")]
    assert not move.well_formed
    assert brain.parse("I think B is (4,5) away\nSay: I win", {"B"}).targets == [Target(label="B"), Target(cell=(4, 5))]
    assert not brain.parse("").well_formed


def _map_rows(text: str, legend: str) -> list[str]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(legend))
    return lines[start + 1 :]


def test_prompt_tells_steps_and_draws_the_map():
    game = duel()
    w = game.world
    text = brain.prompt(w, "s2", "zh", game.seats)
    assert text.startswith("剩 60 秒。分數：你 0，1 號 0。")
    assert "你是 2 號（AI）：頭在 (17,11)，正往左，長 4。" in text
    assert "1 號（人：小明）：頭在 (6,4)，正往右，長 4。" in text
    for food in w.foods:
        x, y = food.cell
        mine, theirs = engine.distance(w, "s2", food.cell), engine.distance(w, "s1", food.cell)
        assert f"{food.label} 蘋果 +1 在 ({x},{y})：你 {mine} 步；別的蛇最快是 1 號，{theirs} 步" in text
    rows = _map_rows(text, "地圖")
    assert len(rows) == w.h + 2  # the two rows of x numbers, then the board
    assert rows[1] == "    " + "0123456789" * 2 + "0123"
    assert rows[2 + 11][4 + 17] == "Y" and rows[2 + 4][4 + 6] == "1"
    en = brain.prompt(w, "s2", "en", game.seats)
    assert en.startswith("60 s left.") and "You are #2 (AI): head at (17,11), moving left, length 4." in en
    assert "#1 (a person: 小明): head at (6,4)" in en


def test_prompt_with_several_people_and_ai_snakes():
    game = Match("hub", "zh", "normal", 60, ["小明", "阿美"], 5, seed=1)
    w = game.world
    text = brain.prompt(w, "s4", "zh", game.seats)
    assert text.startswith("剩 60 秒。分數：你 0，1 號 0，2 號 0，3 號 0，5 號 0。")
    assert "你是 4 號（AI 2）：" in text
    assert "1 號（人：小明）：" in text and "2 號（人：阿美）：" in text
    assert "3 號（AI 1）：" in text and "5 號（AI 3）：" in text
    assert "地圖" not in text  # left out when there are more than two snakes
    system = brain.system("zh", w, 2, 3)
    assert "一共 5 條蛇：2 個人和 3 條 AI 蛇" in system and "30×20" in system and "{" not in system
    en = brain.prompt(w, "s4", "en", game.seats)
    assert "You are #4 (AI 2):" in en and "#2 (a person: 阿美):" in en


def test_a_snake_an_ai_took_over_says_so():
    game = Match("hub", "zh", "normal", 60, ["小明", "阿美"], 3, seed=1)
    game.hand_to_ai("s2")
    assert "2 號（阿美，AI 接手）：" in brain.prompt(game.world, "s3", "zh", game.seats)
    assert "#2 (阿美, taken over by an AI):" in brain.prompt(game.world, "s3", "en", game.seats)


def test_prompt_after_a_crash():
    game = Match("hub", "zh", "normal", 100, ["小明"], 2, seed=5)
    w = game.world
    w.tick_ms = 100
    ai = w.snakes["s2"]
    ai.body, ai.back_at = [], w.tick + 15
    text = brain.prompt(w, "s2", "zh", game.seats)
    assert "你是 2 號（AI），剛撞到，1.5 秒後回到場上。" in text
    assert "你 到不了" in text


def test_system_says_who_is_in_the_arena():
    w = engine.new_world(["s1", "s2"], 160, 60)
    assert "對手是一個人" in brain.system("zh", w, 1, 1)
    assert "your opponent is a person" in brain.system("en", w, 1, 1)
    assert "沒有人" in brain.system("zh", w, 0, 2)
    assert "no people" in brain.system("en", w, 0, 2)


def test_a_snakes_number_is_its_seat():
    assert brain.mark("s1") == "1" and brain.mark("s5") == "5"
    assert isinstance(Seat("s1", "小明", "person").name, str)
