from snake_duel import history

WORDS = {"practice": "練習蛇", "mode_duel": "1 對 1", "mode_crowd": "{n} 條蛇混戰"}


def side(score: int, crashes: int = 0) -> dict:
    return {"score": score, "apples": score, "golds": 0, "crashes": crashes}


def match(model: str, you: int, *ais: int, crashes: int = 0, secs: float | None = 1.0) -> dict:
    return {
        "at": 1,
        "model": model,
        "mode": "crowd" if len(ais) > 1 else "duel",
        "snakes": 1 + len(ais),
        "speed": "normal",
        "seconds": 60,
        "lang": "zh",
        "you": side(you),
        "ais": [side(a, crashes) for a in ais],
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
    history.save(match("m2", 1, 2, 4))
    assert [m["model"] for m in history.load()] == ["m1", "m2"]


def test_board_sums_up_each_opponent_and_mode():
    rows = history.board(
        [
            match("m1", 5, 3, crashes=1, secs=1.0),
            match("m1", 2, 4, secs=2.0),
            match("m1", 3, 3, secs=None),
            match(history.PRACTICE, 1, 6),
            match("m1", 9, 2, 9, 4),  # a tie at the top
            match("m1", 9, 2, 3, 4),
            match("m1", 1, 2, 3, 4),
        ],
        WORDS,
    )
    assert [(r.model, r.mode) for r in rows] == [("m1", "1 對 1"), ("m1", "4 條蛇混戰"), ("練習蛇", "1 對 1")]
    duel, crowd = rows[0], rows[1]
    assert (duel.matches, duel.you_won, duel.ai_won, duel.draws) == (3, 1, 1, 1)
    assert (duel.ai_points, duel.ai_crashes, duel.ai_secs) == ("3.3", "0.3", "1.5")
    assert (crowd.matches, crowd.you_won, crowd.ai_won, crowd.draws) == (3, 1, 1, 1)
    assert crowd.ai_points == f"{(2 + 9 + 4 + 2 + 3 + 4 + 2 + 3 + 4) / 9:.1f}"
    assert rows[2].ai_won == 1


def test_matches_kept_before_the_free_for_all_still_count():
    old = {"at": 1, "model": "m1", "you": side(5), "ai": side(3), "ask_secs": 1.0}
    rows = history.board([old], WORDS)
    assert (rows[0].mode, rows[0].you_won, rows[0].ai_points) == ("1 對 1", 1, "3.0")
