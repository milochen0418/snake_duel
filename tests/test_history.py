from snake_duel import history


def match(model: str, you: int, ai: int, crashes: int = 0, secs: float | None = 1.0) -> dict:
    return {
        "at": 1,
        "model": model,
        "speed": "normal",
        "seconds": 60,
        "lang": "zh",
        "you": {"score": you, "apples": you, "golds": 0, "crashes": 0},
        "ai": {"score": ai, "apples": ai, "golds": 0, "crashes": crashes},
        "asks": 10,
        "ask_secs": secs,
        "failed": 0,
        "bad": 0,
    }


def test_saved_matches_come_back(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAKE_DUEL_DATA_DIR", str(tmp_path))
    assert history.load() == []
    history.save(match("m1", 5, 3))
    (tmp_path / "matches.jsonl").open("a").write("not json\n{}\n")
    history.save(match("m2", 1, 2))
    assert [m["model"] for m in history.load()] == ["m1", "m2"]


def test_board_sums_up_each_opponent():
    rows = history.board(
        [match("m1", 5, 3, crashes=1, secs=1.0), match("m1", 2, 4, secs=2.0), match("m1", 3, 3, secs=None), match(history.PRACTICE, 1, 6)],
        practice_label="練習蛇",
    )
    assert [r.model for r in rows] == ["m1", "練習蛇"]
    m1 = rows[0]
    assert (m1.matches, m1.you_won, m1.ai_won, m1.draws) == (3, 1, 1, 1)
    assert (m1.ai_points, m1.ai_crashes, m1.ai_secs) == ("3.3", "0.3", "1.5")
    assert rows[1].ai_won == 1
