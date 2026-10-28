"""A whole one-minute match at the fast speed against the practice snake (no AI Hub needed): the
countdown over the starting board drawn on the canvas, a turn pressed before the start, the
person's snake steered with the arrow keys by a little bot here, the practice snake's plan and
decisions on the page, scores that add up in the result, and the scoreboard's row."""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import choose, drawn, finish, frame, launch, log, new_page, number, open_lobby, shot, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors)
    open_lobby(page)
    page.click("[data-testid=foe-practice]")
    page.click("[data-testid=speed-fast]")
    page.click("[data-testid=length-60]")
    page.click("[data-testid=start]")

    page.wait_for_selector("[data-testid=countdown]")
    wait_for(lambda: frame(page).get("t") == 0 and frame(page)["you"]["body"], "the starting board")
    wait_for(lambda: drawn(page) > 6, "the board drawn on the canvas", 5)
    assert number(page, "left") == 60 and number(page, "my-score") == 0
    shot(page, "1_countdown")
    page.keyboard.press("ArrowDown")  # turns can be given before the start
    wait_for(lambda: page.locator("[data-testid=countdown]").count() == 0, "the start", 10)
    wait_for(lambda: frame(page)["t"] >= 3, "the snakes moving", 5)
    assert frame(page)["you"]["dir"] == "down", frame(page)["you"]

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
            aims += bool(f.get("aim"))
            if page.locator("[data-testid=said] tbody tr").count():
                rows = page.locator("[data-testid=said] tbody tr").count()
                scores.add(number(page, "my-score"))
            if not shots and last > 150:
                shot(page, "2_playing")
                assert "練習蛇" in page.inner_text("[data-testid=match]")
                shots = 1
        page.wait_for_timeout(30)
    log(f"ticks seen up to {last}, keys pressed {keys}, frames with the AI's aim {aims}, decision rows {rows}")
    assert keys > 10 and aims > 50 and rows == 5
    assert max(scores) > 0, "the person's snake never ate"

    shot(page, "3_result")
    mine, theirs = number(page, "my-score"), number(page, "ai-score")
    text = page.inner_text("[data-testid=result]")
    log("result:", text.replace("\n", " "))
    cells = [int(n.replace("−", "-")) for n in re.findall(r"[−-]?\d+", text.split("AI 的表現")[0])]
    # rows: points, apples, golds, crashes; each with the person's number, then the AI's
    points, apples, golds, crashes = cells[0:2], cells[2:4], cells[4:6], cells[6:8]
    assert points == [mine, theirs], (points, mine, theirs)
    for side in (0, 1):
        assert points[side] == apples[side] + 3 * golds[side] - 3 * crashes[side], cells
    assert apples[1] + golds[1] > 0, "the practice snake never ate"
    assert page.locator("[data-testid=arena]").count() == 1  # the last board stays

    page.click("[data-testid=to-lobby]")
    page.wait_for_selector("[data-testid=board]")
    board = page.inner_text("[data-testid=board]")
    assert "練習蛇" in board, board
    shot(page, "4_board")
    browser.close()
finish(errors)
