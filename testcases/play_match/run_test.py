"""A whole one-minute duel at the fast speed against the practice snake (no AI Hub needed): the
countdown over the starting board drawn on the canvas, a turn pressed before the start, the
person's snake steered with the arrow keys by the little bot of ``common.choose``, the practice
snake's aim and decisions on the page, the result's places with points that add up, and the
scoreboard's row."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import check_places, choose, drawn, finish, frame, launch, log, new_page, number, open_lobby, places, shot, snake, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors)
    open_lobby(page)
    page.click("[data-testid=foe-practice]")
    page.click("[data-testid=mode-duel]")
    page.click("[data-testid=speed-fast]")
    page.click("[data-testid=length-60]")
    page.click("[data-testid=start]")

    page.wait_for_selector("[data-testid=countdown]")
    wait_for(lambda: frame(page).get("t") == 0 and snake(frame(page), "you")["body"], "the starting board")
    f = frame(page)
    assert (f["w"], f["h"]) == (24, 16) and [s["id"] for s in f["snakes"]] == ["you", "ai1"]
    wait_for(lambda: drawn(page) > 6, "the board drawn on the canvas", 5)
    assert number(page, "left") == 60 and number(page, "my-score") == 0
    assert page.locator("[data-testid=ai-card]").count() == 1
    shot(page, "1_countdown")
    page.keyboard.press("ArrowDown")  # turns can be given before the start
    wait_for(lambda: page.locator("[data-testid=countdown]").count() == 0, "the start", 10)
    wait_for(lambda: frame(page)["t"] >= 3, "the snakes moving", 5)
    assert snake(frame(page), "you")["dir"] == "down", snake(frame(page), "you")

    deadline = time.time() + 90
    last, keys, aims, rows, scores, shots = -1, 0, 0, 0, set(), 0
    while page.locator("[data-testid=result]").count() == 0:
        assert time.time() < deadline, "the match didn't end"
        f = frame(page)
        if f.get("t", -1) != last:
            last = f["t"]
            if key := choose(f):
                page.keyboard.press(key)
                keys += 1
            aims += bool(f.get("aims"))
            if page.locator("[data-testid=said] tbody tr").count():
                rows = page.locator("[data-testid=said] tbody tr").count()
                scores.add(number(page, "my-score"))
            if not shots and last > 150:
                shot(page, "2_playing")
                assert "練習蛇" in page.inner_text("[data-testid=match]")
                shots = 1
        page.wait_for_timeout(30)
    log(f"ticks seen up to {last}, keys pressed {keys}, frames with the AI's aim {aims}, decision rows {rows}")
    assert keys > 10 and aims > 50 and rows == 6
    assert max(scores) > 0, "the person's snake never ate"

    shot(page, "3_result")
    table = places(page)
    log("places:", table)
    check_places(table)
    assert [r["name"] for r in sorted(table, key=lambda r: r["name"] != "你")] == ["你", "AI"]
    mine = next(r for r in table if r["name"] == "你")
    theirs = next(r for r in table if r["name"] == "AI")
    assert mine["points"] == number(page, "my-score") and theirs["points"] == number(page, "ai-score")
    outcome = page.inner_text("[data-testid=outcome]")
    assert outcome == ("你贏了！" if mine["points"] > theirs["points"] else "AI 贏了" if mine["points"] < theirs["points"] else "平手"), outcome
    assert theirs["apples"] + theirs["golds"] > 0, "the practice snake never ate"
    assert page.locator("[data-testid=arena]").count() == 1  # the last board stays

    page.click("[data-testid=to-lobby]")
    page.wait_for_selector("[data-testid=board]")
    board = page.inner_text("[data-testid=board]")
    assert "練習蛇" in board and "1 對 1" in board, board
    shot(page, "4_board")
    browser.close()
finish(errors)
