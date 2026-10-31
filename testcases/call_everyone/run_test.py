"""Call everyone while playing (needs an installed call app; skipped without one, so run it on
re-ddns, where avatar-chat or livekit provide ``call.join``). Two people in a match: one calls
everyone, the other is rung over the game and accepts, both see "Join call · 2" and each other in
the call. With the call minimized to the tray, the keys steer the snake again, whatever was
clicked in the call."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from common import BASE_URL, finish, frame, launch, log, mine, new_page, open_lobby, shot, wait_for  # noqa: E402

MEDIA = ("--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required")


def steers(page: Page) -> bool:
    """Whether this page's arrow keys turn its snake."""
    for _ in range(15):
        you = mine(frame(page), page)
        if you["body"]:
            want = "up" if you["dir"] in ("left", "right") else "left"
            page.keyboard.press("Arrow" + want.capitalize())
            page.wait_for_timeout(500)
            if mine(frame(page), page)["dir"] == want:
                return True
        page.wait_for_timeout(300)
    return False


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw, *MEDIA)
    a = new_page(browser, errors)
    b = new_page(browser, errors)
    for page in (a, b):
        page.context.grant_permissions(["camera", "microphone"])
    open_lobby(a, name="打電話的人")
    for key in ("foe-practice", "total-3", "speed-slow", "length-120", "host"):
        a.click(f"[data-testid={key}]")
    a.wait_for_selector("[data-testid=room]")
    code = a.inner_text("[data-testid=code]").strip()
    open_lobby(b, name="接電話的人", url=f"{BASE_URL}/?r={code}")
    wait_for(lambda: a.locator("[data-testid=room-people] [data-testid=person]").count() == 2, "both in the room")
    a.click("[data-testid=start]")
    for page in (a, b):
        page.wait_for_selector("[data-testid=countdown]", timeout=30000)
    wait_for(lambda: a.locator("[data-testid=countdown]").count() == 0, "the start", 15)

    a.click("[data-testid=call-everyone]")
    a.wait_for_timeout(1500)  # with several call apps installed, the first caller picks one
    if a.locator("text=No installed app").count():
        log("SKIP: no call app here")
        raise SystemExit(0)
    chooser = a.locator("button", has_text="livekit")
    if chooser.count():
        chooser.first.click()
    wait_for(lambda: a.locator("iframe").count() > 0, "the call dialog", 30)
    wait_for(lambda: b.locator("[data-testid=incoming-call]").count() == 1, "the other person is rung", 30)
    assert "打電話的人" in b.inner_text("[data-testid=incoming-call]")
    assert frame(b).get("t", 0) > 0  # over the game, not instead of it
    shot(b, "1_incoming")
    b.click("[data-testid=call-accept]")
    wait_for(lambda: b.locator("iframe").count() > 0, "their call dialog", 30)
    wait_for(lambda: b.locator("[data-testid=incoming-call]").count() == 0, "the ringing stops", 10)
    wait_for(lambda: "2" in a.inner_text("[data-testid=call-join]"), "Join call · 2", 60)
    log("in the call:", a.inner_text("[data-testid=call-join]"))
    for page, other in ((a, "接電話的人"), (b, "打電話的人")):  # really connected to each other
        wait_for(lambda page=page, other=other: other in page.frame_locator("iframe").first.locator("body").inner_text(), "the other person in the call", 30)
    shot(a, "2_in_call")

    for page in (a, b):
        page.frame_locator("iframe").first.locator("body").click(position={"x": 30, "y": 30})  # focus in the call
        page.locator("[aria-label=Minimize]").first.click()
        wait_for(lambda page=page: page.locator("[data-intent-tray-item]").count() == 1, "the call in the tray", 10)
    shot(b, "3_minimized")
    assert steers(a) and steers(b), "the keys don't reach the game with the call in the tray"
    assert "2" in a.inner_text("[data-testid=call-join]")
    log("keys steer the snakes with the call in the tray")
    browser.close()
finish([e for e in errors if "avatar" not in e.lower() and "livekit" not in e.lower()])
