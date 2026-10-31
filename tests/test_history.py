from snake_duel import history

WORDS = {"practice": "練習蛇", "people_only": "只有真人", "mode": "{n} 隻蛇", "mode_people": "{n} 隻蛇（{p} 人）"}


def side(score: int, kind: str = "ai", crashes: int = 0) -> dict:
    out = {"name": kind, "kind": kind, "score": score, "apples": score, "golds": 0, "crashes": crashes}
    if kind == "ai":
        out |= {"asks": 10, "ask_secs": 1.0, "failed": 0, "bad": 0, "left": False}
    return out


def match(model: str, people: list[int], ais: list[int], crashes: int = 0, secs: float | None = 1.0) -> dict:
    return {
        "at": 1,
        "model": model,
        "snakes": len(people) + len(ais),
        "people": len(people),
        "speed": "normal",
        "seconds": 60,
        "lang": "zh",
        "sides": [side(s, "person") for s in people] + [side(s, "ai", crashes) for s in ais],
        "asks": 10,
        "ask_secs": secs,
        "failed": 0,
        "bad": 0,
    }


def test_saved_matches_come_back(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAKE_DUEL_DATA_DIR", str(tmp_path))
    assert history.load() == []
    history.save(match("m1", [5], [3]))
    (tmp_path / "matches.jsonl").open("a").write("not json\n{}\n")
    history.save(match("m2", [1, 2], [2, 4]))
    assert [m["model"] for m in history.load()] == ["m1", "m2"]


def test_board_sums_up_each_opponent_and_arena():
    rows = history.board(
        [
            match("m1", [5], [3], crashes=1, secs=1.0),
            match("m1", [2], [4], secs=2.0),
            match("m1", [3], [3], secs=None),  # a person and an AI share first place
            match(history.PRACTICE, [1], [6]),
            match("m1", [9, 1], [2, 4], secs=1.0),
            match("m1", [1, 1], [2, 9], secs=1.0),
            match("m1", [9, 2], [9, 4], secs=1.0),
        ],
        WORDS,
    )
    assert [(r.model, r.arena) for r in rows] == [("m1", "2 隻蛇"), ("m1", "4 隻蛇（2 人）"), ("練習蛇", "2 隻蛇")]
    duel, crowd = rows[0], rows[1]
    assert (duel.matches, duel.you_won, duel.ai_won, duel.draws) == (3, 1, 1, 1)
    assert (duel.ai_points, duel.ai_crashes, duel.ai_secs) == ("3.3", "0.3", "1.5")
    assert (crowd.matches, crowd.you_won, crowd.ai_won, crowd.draws) == (3, 1, 1, 1)
    assert crowd.ai_points == f"{(2 + 4 + 2 + 9 + 9 + 4) / 6:.1f}"
    assert rows[2].ai_won == 1


def test_a_match_of_people_only_has_a_row_of_its_own():
    rows = history.board([match(history.PEOPLE, [5, 3], [])], WORDS)
    assert (rows[0].model, rows[0].arena, rows[0].ai_points, rows[0].you_won) == ("只有真人", "2 隻蛇（2 人）", "–", 1)


def test_matches_kept_before_people_could_play_together_still_count():
    old_duel = {"at": 1, "model": "m1", "you": side(5, "person"), "ai": side(3), "ask_secs": 1.0}
    old_crowd = {"at": 1, "model": "m1", "you": side(1, "person"), "ais": [side(3), side(9), side(2)], "ask_secs": 2.0}
    rows = history.board([old_duel, old_crowd], WORDS)
    assert [(r.model, r.arena, r.matches) for r in rows] == [("m1", "2 隻蛇", 1), ("m1", "4 隻蛇", 1)]
    assert (rows[0].you_won, rows[0].ai_points) == (1, "3.0")
    assert (rows[1].ai_won, rows[1].ai_secs) == (1, "2.0")
