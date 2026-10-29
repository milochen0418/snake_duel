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
    w = engine.new_world(["you", "ai1"], 160, 60, seed=5)
    text = brain.prompt(w, "ai1", "zh")
    assert text.startswith("剩 60 秒。分數：你 0，人 0。")
    assert "你（AI 蛇）：頭在 (17,11)，正往左，長 4。" in text
    assert "人（0 號）：頭在 (6,4)，正往右，長 4。" in text
    for food in w.foods:
        x, y = food.cell
        mine, theirs = engine.distance(w, "ai1", food.cell), engine.distance(w, "you", food.cell)
        assert f"{food.label} 蘋果 +1 在 ({x},{y})：你 {mine} 步；別的蛇最快是 0 號，{theirs} 步" in text
    rows = _map_rows(text, "地圖")
    assert len(rows) == w.h + 2  # the two rows of x numbers, then the board
    assert rows[1] == "    " + "0123456789" * 2 + "0123"
    assert rows[2 + 11][4 + 17] == "Y" and rows[2 + 4][4 + 6] == "0"
    en = brain.prompt(w, "ai1", "en")
    assert en.startswith("60 s left.") and "You (the AI snake): head at (17,11), moving left, length 4." in en
    assert "the person (#0): head at (6,4)" in en


def test_prompt_in_a_free_for_all():
    w = engine.new_world(["you", "ai1", "ai2", "ai3"], 160, 60, seed=1)
    text = brain.prompt(w, "ai2", "zh")
    assert text.startswith("剩 60 秒。分數：你 0，人 0，AI 1 0，AI 3 0。")
    assert "你（AI 2）：頭在 (24,9)，正往下，長 4。" in text
    assert "人（0 號）：" in text and "AI 1（1 號）：頭在 (14,4)" in text and "AI 3（3 號）：" in text
    assert "地圖" not in text  # left out of a free-for-all
    system = brain.system("zh", w)
    assert "多蛇混戰" in system and "3 條 AI 蛇" in system and "30×20" in system and "AI 2" not in system
    en = brain.prompt(w, "ai2", "en")
    assert "You (AI 2): head at (24,9)" in en and "AI 1 (#1): head at (14,4)" in en


def test_prompt_after_a_crash():
    w = engine.new_world(["you", "ai1"], 100, 60, seed=5)
    ai = w.snakes["ai1"]
    ai.body, ai.back_at = [], w.tick + 15
    text = brain.prompt(w, "ai1", "zh")
    assert "你剛撞到，1.5 秒後回到場上。" in text
    assert "你 到不了" in text


def test_system_has_the_rules():
    w = engine.new_world(["you", "ai1"], 160, 60)
    for lang in ("zh", "en"):
        text = brain.system(lang, w)
        assert "24" in text and "{" not in text


def test_names_and_marks():
    assert brain.ai_name("ai1", 1) == "AI" and brain.ai_name("ai3", 4) == "AI 3"
    assert brain.mark("you") == "0" and brain.mark("ai2") == "2"
