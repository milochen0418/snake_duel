from snake_duel import brain, engine
from snake_duel.brain import Target


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
    move = brain.parse("Target: (30,2), (2,16), A, B, C, D")
    assert move.targets == [Target(label="A"), Target(label="B"), Target(label="C")]


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


def test_prompt_tells_steps_and_draws_the_map():
    w = engine.new_world(160, 60, seed=5)
    text = brain.prompt(w, "zh")
    lines = text.splitlines()
    assert lines[0].startswith("剩 60 秒")
    assert "你（AI 蛇）：頭在 (17,11)，正往左，長 4。" in text
    for food in w.foods:
        assert f"{food.label} 蘋果 +1 在 ({food.cell[0]},{food.cell[1]})" in text
    rows = [line for line in lines if len(line) == 4 + engine.W]
    assert len(rows) == engine.H + 2  # the two rows of x numbers, then the board
    assert rows[1].endswith("0123456789" * 2 + "0123")
    assert "Y" in lines[-5] and "O" in lines[-12]  # the AI's head on row 11, the person's on row 4
    en = brain.prompt(w, "en")
    assert en.startswith("60 s left.") and "You (the AI snake): head at (17,11), moving left, length 4." in en


def test_prompt_after_a_crash():
    w = engine.new_world(100, 60, seed=5)
    ai = w.snakes["ai"]
    ai.body, ai.back_at = [], w.tick + 15
    text = brain.prompt(w, "zh")
    assert "你剛撞到，1.5 秒後回到場上。" in text
    assert "你 到不了" in text


def test_system_has_the_rules():
    for lang in ("zh", "en"):
        text = brain.system(lang)
        assert "24" in text and "{" not in text
