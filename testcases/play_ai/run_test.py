"""(Needs an AI Hub; skipped without one.) A one-minute duel at the slow speed against the model
the hub sets for this app, the person's snake steered by the little bot of ``common.choose``:
the AI's decisions come in (a row each, with where it said to go, its words and its seconds),
its snake heads for a food it named, the result counts its decisions, and the model's row is on
the scoreboard. Give it a model that answers quickly (a thinking one only dodges)."""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import check_places, choose, finish, frame, launch, log, new_page, open_lobby, places, shot, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors)
    opponent = open_lobby(page)
    if not opponent:
        log("SKIP: no AI Hub opponent here")
        raise SystemExit(0)
    log("opponent:", opponent)
    page.click("[data-testid=total-2]")
    page.click("[data-testid=speed-slow]")
    page.click("[data-testid=length-60]")
    page.click("[data-testid=start]")
    wait_for(lambda: page.locator("[data-testid=countdown]").count() == 1, "the countdown (after the warm-up)", 120)
    wait_for(lambda: page.locator("[data-testid=countdown]").count() == 0, "the start", 10)

    card = "[data-testid=ai-card][data-ai=s2]"
    deadline = time.time() + 100
    last, followed, words, statuses, shots = -1, 0, set(), set(), 0
    while page.locator("[data-testid=result]").count() == 0:
        assert time.time() < deadline, "the match didn't end"
        f = frame(page)
        if f.get("t", -1) != last:
            last = f["t"]
            if key := choose(f):
                page.keyboard.press(key)
            # The panel gives way to the result the moment the match ends, so read it if it is there.
            status = page.locator(f"{card} [data-testid=ai-status]")
            if status.count():
                statuses.add(status.inner_text())
            aim = page.locator(f"{card} [data-testid=ai-aim]")
            mine = next((a for a in f.get("aims", []) if a["id"] == "s2"), None)
            if aim.count() and mine:
                label = aim.inner_text().split("·")[0].strip()
                food = next((fd for fd in f["food"] if fd["l"] == label), None)
                followed += bool(food and [food["x"], food["y"]] == mine["aim"])
            said = page.locator(f"{card} [data-testid=ai-words]")
            if said.count():
                words.add(said.inner_text())
            if not shots and last > 120:
                shot(page, "1_playing")
                shots = 1
        page.wait_for_timeout(40)
    log(f"statuses: {sorted(statuses)[:8]}")
    log(f"frames where the AI headed for the food it named: {followed}; its words: {sorted(words)[:6]}")
    assert followed > 20, "the AI's snake never headed for the food it named"
    assert any(s.startswith("思考中") for s in statuses)

    shot(page, "2_result")
    check_places(places(page))
    report = page.inner_text("[data-testid=report]")
    log("report:", report.replace("\n", " "))
    asks = re.search(r"做了幾個決定\s+(\d+)", report).group(1)
    secs = re.search(r"每次平均想幾秒\s+([\d.]+)", report).group(1)
    assert int(asks) >= 5 and float(secs) < 10

    page.click("[data-testid=to-lobby]")
    page.wait_for_selector("[data-testid=board]")
    wait_for(lambda: opponent.split(" (")[0] in page.inner_text("[data-testid=board]"), "the model's row")
    shot(page, "3_board")
    browser.close()
finish(errors)
