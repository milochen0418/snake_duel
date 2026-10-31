"""Who is who with the platform's login (skipped without ``DDNS_AUTH_SECRET``, the server's own:
the suite signs its own test cookies with it, so it is for a local server, not a live one).

Two accounts in one room go by their names and pictures in the room, on the scoreboard, on the
board and in the result's table, with no name box. All of an account's tabs are one person: a
second tab of the same account is the same snake, not another seat. A guest who signs in keeps
their place, and the sign-in link comes back to the room.
"""

import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jwt  # noqa: E402
from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

from common import BASE_URL, finish, frame, launch, log, new_page, open_lobby, shot, wait_for  # noqa: E402

SECRET = os.environ.get("DDNS_AUTH_SECRET", "")
COOKIE = os.environ.get("DDNS_AUTH_COOKIE", "ddns_auth")
# A 1×1 picture, so that the canvas can still be read by the test.
PICTURE = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c636060f80f0001040100" "5a0dd1a10000000049454e44ae426082")
).decode("ascii")


def sign_in(page: Page, email: str, name: str) -> None:
    token = jwt.encode({"email": email, "name": name, "picture": PICTURE, "approved": True, "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    page.context.add_cookies([{"name": COOKIE, "value": token, "url": BASE_URL}])


def person(browser: Browser, errors: list[str], email: str, name: str) -> Page:
    page = new_page(browser, errors)
    sign_in(page, email, name)
    return page


def people(page: Page) -> str:
    return page.inner_text("[data-testid=room-people]")


if not SECRET:
    log("SKIP: no DDNS_AUTH_SECRET here")
    raise SystemExit(0)

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)

    log("two accounts in one room")
    milo = person(browser, errors, "milo@example.com", "Milo Chen")
    open_lobby(milo)
    assert milo.inner_text("[data-testid=me-name]") == "Milo Chen" and milo.locator("[data-testid=name]").count() == 0
    for key in ("foe-practice", "total-4", "speed-fast", "length-60", "host"):
        milo.click(f"[data-testid={key}]")
    milo.wait_for_selector("[data-testid=room]")
    code = milo.inner_text("[data-testid=code]").strip()
    gap = person(browser, errors, "gap@example.com", "Gap Lin")
    gap.goto(f"{BASE_URL}/?r={code}", wait_until="domcontentloaded")
    gap.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "Gap Lin" in people(milo) and "Milo Chen" in people(gap), "both see each other")
    assert milo.locator("[data-testid=room-people] img").count() == 2
    shot(milo, "1_room")

    log("the second tab of an account is the same person")
    again = person(browser, errors, "gap@example.com", "Gap Lin")
    again.goto(f"{BASE_URL}/?r={code}", wait_until="domcontentloaded")
    again.wait_for_selector("[data-testid=room]")
    again.wait_for_timeout(800)
    assert milo.locator("[data-testid=room-people] [data-testid=person]").count() == 2, people(milo)

    log("a guest who signs in keeps their place")
    guest = new_page(browser, errors)
    guest.goto(f"{BASE_URL}/?r={code}", wait_until="domcontentloaded")
    guest.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "訪客" in people(milo), "the guest in the room")
    link = guest.get_attribute("[data-testid=sign-in]", "href") or ""
    assert f"%2F%3Fr%3D{code}" in link, link  # the sign-in comes back to this room
    sign_in(guest, "amy@example.com", "Amy Wu")
    guest.reload()
    guest.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "Amy Wu" in people(milo) and "訪客" not in people(milo), "the same place under their account")
    assert milo.locator("[data-testid=room-people] [data-testid=person]").count() == 3

    log("names and pictures in the match")
    milo.click("[data-testid=start]")
    for page in (milo, gap, again, guest):
        page.wait_for_selector("[data-testid=countdown]", timeout=30000)
    wait_for(lambda: frame(milo).get("t") == 0, "the starting board")
    f = frame(milo)
    assert [s["n"] for s in f["snakes"]][:3] == ["Milo Chen", "Gap Lin", "Amy Wu"] and f["snakes"][3]["k"] == "ai", f["snakes"]
    assert gap.get_attribute("#arena", "data-me") == again.get_attribute("#arena", "data-me") == "s2"
    assert "s1" in (milo.get_attribute("#arena", "data-faces") or "")
    assert milo.locator("[data-testid=chip] img").count() == 2
    wait_for(lambda: milo.locator("[data-testid=countdown]").count() == 0, "the start", 15)
    shot(milo, "2_match")

    log("the second tab steers the same snake")
    steered = False
    for _ in range(15):
        snake = next(s for s in frame(again)["snakes"] if s["id"] == "s2")
        if snake["body"]:
            want = "up" if snake["dir"] in ("left", "right") else "left"
            again.keyboard.press("Arrow" + want.capitalize())
            gap.wait_for_timeout(500)
            steered = next(s for s in frame(gap)["snakes"] if s["id"] == "s2")["dir"] == want
            if steered:
                break
        gap.wait_for_timeout(300)
    assert steered

    log("the result")
    milo.wait_for_selector("[data-testid=result]", timeout=90000)
    assert milo.locator("[data-testid=places] img").count() == 3
    assert "Amy Wu" in milo.inner_text("[data-testid=places]")
    shot(milo, "3_result")
    browser.close()
finish(errors)
