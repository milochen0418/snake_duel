"""A whole one-minute match at the fast speed, played alone with the arena set to four snakes:
you and three practice snakes (no AI Hub needed) on the big board. Four snakes drawn from their
starting places round the middle, a card and a score for each AI snake, every AI snake heading
somewhere of its own, their decisions listed by name, the person's snake steered by the little
bot of ``common.choose``, places for all four with points that add up and the person's place in
the final word, and the scoreboard's row."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import check_places, choose, drawn, finish, frame, launch, log, mine, new_page, number, open_lobby, places, shot, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors)
    open_lobby(page, name="小明")
    page.click("[data-testid=foe-practice]")
    page.click("[data-testid=total-4]")
    page.click("[data-testid=speed-fast]")
    page.click("[data-testid=length-60]")
    shot(page, "1_lobby")
    page.click("[data-testid=start]")

    page.wait_for_selector("[data-testid=countdown]")
    wait_for(lambda: frame(page).get("t") == 0, "the starting board")
    f = frame(page)
    assert (f["w"], f["h"]) == (30, 20) and [s["id"] for s in f["snakes"]] == ["s1", "s2", "s3", "s4"]
    assert [s["n"] for s in f["snakes"]] == ["小明", "AI 1", "AI 2", "AI 3"] and len(f["food"]) == 5  # one apple more than snakes
    assert [s["k"] for s in f["snakes"]] == ["person", "ai", "ai", "ai"]
    wait_for(lambda: drawn(page) > 10, "four snakes drawn on the canvas", 5)
    assert page.locator("[data-testid=ai-card]").count() == 3 and page.locator("[data-testid=chip]").count() == 3
    shot(page, "2_countdown")
    page.keyboard.press("ArrowRight")  # the person starts on the left, going up
    wait_for(lambda: page.locator("[data-testid=countdown]").count() == 0, "the start", 10)
    wait_for(lambda: frame(page)["t"] >= 3, "the snakes moving", 5)
    assert mine(frame(page), page)["dir"] == "right"

    deadline = time.time() + 90
    last, aimed, named, shots = -1, set(), set(), 0
    while page.locator("[data-testid=result]").count() == 0:
        assert time.time() < deadline, "the match didn't end"
        f = frame(page)
        if f.get("t", -1) != last:
            last = f["t"]
            if key := choose(f):
                page.keyboard.press(key)
            aimed |= {a["id"] for a in f.get("aims", [])}
            if last % 25 == 0:
                named |= {t.split(" ")[0] + " " + t.split(" ")[1] for t in page.locator("[data-testid=said] tbody tr td:nth-child(2)").all_inner_texts() if t.startswith("AI ")}
            if not shots and last > 200:
                shot(page, "3_playing")
                shots = 1
        page.wait_for_timeout(30)
    log(f"ticks seen up to {last}; AI snakes that headed somewhere: {sorted(aimed)}; named in the decisions: {sorted(named)}")
    assert aimed == {"s2", "s3", "s4"} and named == {"AI 1", "AI 2", "AI 3"}

    shot(page, "4_result")
    table = places(page)
    log("places:", table)
    assert sorted(r["name"] for r in table) == ["AI 1", "AI 2", "AI 3", "小明"]
    check_places(table)
    yours = next(r for r in table if r["name"] == "小明")
    assert yours["points"] == number(page, "my-score")
    tied = sum(1 for r in table if r["rank"] == yours["rank"]) > 1
    want = ("你並列第一" if tied else "你拿第一！") if yours["rank"] == 1 else f"你第 {yours['rank']} 名"
    assert page.inner_text("[data-testid=outcome]") == want
    assert all(r["asks"].isdigit() and int(r["asks"]) > 5 for r in table if r["name"] != "小明")
    assert sum(r["apples"] + r["golds"] for r in table if r["name"] != "小明") > 5

    page.click("[data-testid=to-lobby]")
    page.wait_for_selector("[data-testid=board]")
    board = page.inner_text("[data-testid=board]")
    assert "練習蛇" in board and "4 隻蛇" in board, board
    shot(page, "5_board")
    browser.close()
finish(errors)
