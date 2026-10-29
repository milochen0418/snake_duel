"""The lobby: the opponent from the AI Hub (or the note that there is none, with Start off for it
but on for the practice snake), the mode (how many AI snakes only for a free-for-all), speed,
length, mode and opponent kept in the browser over a reload, the English switch, the
scoreboard, no sideways scrolling on a phone."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import finish, launch, log, new_page, open_lobby, shot, wait_for  # noqa: E402


def active(page, test_id: str) -> bool:
    return "amber" in (page.get_attribute(f"[data-testid={test_id}]", "class") or "")


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors)
    opponent = open_lobby(page)
    log("opponent:", opponent or "(no AI Hub)")
    start = page.locator("[data-testid=start]")
    assert active(page, "foe-hub")
    assert start.is_enabled() if opponent else start.is_disabled()
    assert page.locator("[data-testid=board]").count() == 1
    shot(page, "1_lobby")

    page.click("[data-testid=foe-practice]")
    wait_for(start.is_enabled, "Start on for the practice snake")
    assert "練習蛇不問 AI" in page.inner_text("[data-testid=lobby]")
    page.click("[data-testid=speed-fast]")
    page.click("[data-testid=length-120]")
    assert page.locator("[data-testid=crowd-3]").count() == 0  # how many AI snakes: a free-for-all only
    page.click("[data-testid=mode-crowd]")
    page.click("[data-testid=crowd-4]")
    wait_for(lambda: active(page, "length-120") and active(page, "crowd-4"), "the choices made")
    page.reload()
    page.wait_for_selector("[data-testid=lobby]")
    wait_for(
        lambda: all(active(page, k) for k in ("speed-fast", "length-120", "foe-practice", "mode-crowd", "crowd-4")),
        "the choices kept",
    )
    assert "30×20" in page.inner_text("[data-testid=lobby]")
    shot(page, "2_practice_crowd")
    page.click("[data-testid=mode-duel]")
    wait_for(lambda: page.locator("[data-testid=crowd-4]").count() == 0, "back to one on one")

    page.click("[data-testid=lang]")
    wait_for(lambda: "Snake Duel" in page.inner_text("header"), "English")
    assert "Start the duel" in page.inner_text("[data-testid=start]")
    assert "How to play" in page.inner_text("[data-testid=lobby]")
    shot(page, "3_english")
    page.click("[data-testid=lang]")
    wait_for(lambda: "雙蛇搶食" in page.inner_text("header"), "back to Chinese")
    page.click("[data-testid=foe-hub]")
    page.click("[data-testid=speed-normal]")
    page.click("[data-testid=length-60]")

    phone = new_page(browser, errors, width=390, height=844)
    open_lobby(phone)
    wide = phone.evaluate("document.documentElement.scrollWidth")
    assert wide <= 390, f"the page is {wide} px wide on a 390 px phone"
    shot(phone, "4_phone")
    browser.close()
finish(errors)
