"""The lobby: the opponent from the AI Hub (or the note that there is none, with the buttons off
for it but on for the practice snake), how many snakes the arena holds and what fills the seats,
the name box, speed, length and opponent kept in the browser over a reload, the room list when
nobody is waiting, the English switch, the scoreboard, no sideways scrolling on a phone."""

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
    start, host = page.locator("[data-testid=start]"), page.locator("[data-testid=host]")
    assert active(page, "foe-hub")
    for button in (start, host):
        assert button.is_enabled() if opponent else button.is_disabled()
    assert page.locator("[data-testid=board]").count() == 1
    assert "沒有人開房間" in page.inner_text("[data-testid=rooms]")
    shot(page, "1_lobby")

    page.click("[data-testid=foe-practice]")
    wait_for(start.is_enabled, "the buttons on for the practice snake")
    assert "練習蛇不問 AI" in page.inner_text("[data-testid=lobby]")
    page.click("[data-testid=total-5]")
    wait_for(lambda: "4" in page.inner_text("[data-testid=total-note]"), "five seats: you and four AI snakes")
    page.click("[data-testid=total-2]")
    wait_for(lambda: "1" in page.inner_text("[data-testid=total-note]"), "two seats: you and one AI snake")
    page.click("[data-testid=total-4]")
    page.click("[data-testid=speed-fast]")
    page.click("[data-testid=length-120]")
    page.fill("[data-testid=name]", "小明")
    page.locator("[data-testid=name]").blur()
    wait_for(lambda: active(page, "length-120") and active(page, "total-4"), "the choices made")
    page.reload()
    page.wait_for_selector("[data-testid=lobby]")
    wait_for(
        lambda: all(active(page, k) for k in ("speed-fast", "length-120", "foe-practice", "total-4")),
        "the choices kept",
    )
    assert page.input_value("[data-testid=name]") == "小明"
    shot(page, "2_practice")

    page.click("[data-testid=lang]")
    wait_for(lambda: "Snake Duel" in page.inner_text("header"), "English")
    assert "Play alone" in page.inner_text("[data-testid=start]")
    assert "How to play" in page.inner_text("[data-testid=lobby]")
    shot(page, "3_english")
    page.click("[data-testid=lang]")
    wait_for(lambda: "雙蛇搶食" in page.inner_text("header"), "back to Chinese")
    page.click("[data-testid=foe-hub]")
    page.click("[data-testid=speed-normal]")
    page.click("[data-testid=length-60]")
    page.click("[data-testid=total-2]")

    phone = new_page(browser, errors, width=390, height=844)
    open_lobby(phone)
    wide = phone.evaluate("document.documentElement.scrollWidth")
    assert wide <= 390, f"the page is {wide} px wide on a 390 px phone"
    shot(phone, "4_phone")
    browser.close()
finish(errors)
