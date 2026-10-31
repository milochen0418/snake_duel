"""An invite link must work whatever anyone is doing (no AI Hub needed). Each part is something
that really went wrong once:

1. Someone in the middle of their own match opens the link in the same tab: they are asked.
2. The link is opened while the room is playing: they watch, take an AI snake over, or wait.
3. The host's connection drops while they wait (a phone switching apps to paste the link): the
   room and the link live on, and they are still the host when they come back.
4. A connection lost in the middle of a match: an AI stands in and the snake comes back.
5. Leaving a room and reloading stays out; a dead link says so and doesn't stick to the address.
6. Joining doesn't touch your own settings, and nobody is a blank line.
7. Inviting someone who has the game open, and joining by typing the code.
8. Two people and no AI: nothing about an AI on the page.
9. More people than the seats the host picks: the room shows what it really has.
10. A match that ends with someone watching: they are told who won and get a seat in the next.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from common import BASE_URL, finish, frame, launch, log, new_page, open_lobby, shot, wait_for  # noqa: E402


def host_room(page: Page, name: str, total: int, speed: str = "fast") -> str:
    open_lobby(page, name=name)
    for key in ("foe-practice", f"total-{total}", f"speed-{speed}", "length-60", "host"):
        page.click(f"[data-testid={key}]")
    page.wait_for_selector("[data-testid=room]")
    return page.inner_text("[data-testid=code]").strip()


def alone(page: Page, name: str) -> None:
    open_lobby(page, name=name)
    for key in ("foe-practice", "total-2", "speed-slow", "length-120", "start"):
        page.click(f"[data-testid={key}]")
    page.wait_for_selector("[data-testid=countdown]")


def by_link(page: Page, code: str) -> None:
    page.goto(f"{BASE_URL}/?r={code}", wait_until="domcontentloaded")


def people(page: Page) -> str:
    return page.inner_text("[data-testid=room-people]")


def on(page: Page, test_id: str) -> bool:
    return page.locator(f"[data-testid={test_id}]").count() > 0


def ticking(page: Page) -> bool:
    before = frame(page).get("t", -1)
    page.wait_for_timeout(1200)
    return frame(page).get("t", -1) > before


def active(page: Page, test_id: str) -> bool:
    return "amber" in (page.get_attribute(f"[data-testid={test_id}]", "class") or "")


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)

    log("1. in the middle of their own match, the link in the same tab")
    me = new_page(browser, errors)
    code = host_room(me, "我", 4)
    friend = new_page(browser, errors)
    alone(friend, "朋友")
    wait_for(lambda: frame(friend).get("t", 0) >= 0 and not on(friend, "countdown"), "their match going", 15)
    by_link(friend, code)
    friend.wait_for_selector("[data-testid=invite]")
    assert on(friend, "match") and "我" in friend.inner_text("[data-testid=invite-text]")
    assert ticking(friend), "their match stopped"
    assert "/?r=" in friend.url and code not in friend.url  # the address says where they are
    shot(friend, "1_asked")
    friend.click("[data-testid=invite-decline]")
    wait_for(lambda: not on(friend, "invite"), "the question gone")
    assert on(friend, "match") and "朋友" not in people(me)
    by_link(friend, code)
    friend.wait_for_selector("[data-testid=invite]")
    friend.click("[data-testid=invite-accept]")
    friend.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "朋友" in people(me), "the host sees them")
    assert code in friend.url
    log("   asked, declined, asked again, joined")

    log("2. the link while the room is playing")
    host = new_page(browser, errors)
    code2 = host_room(host, "主人", 3)
    host.click("[data-testid=start]")
    host.wait_for_selector("[data-testid=countdown]")
    late = new_page(browser, errors)
    by_link(late, code2)
    late.wait_for_selector("[data-testid=watching]")
    wait_for(lambda: late.locator("[data-testid=take-over]").count() == 2, "two AI snakes to take over")
    assert late.locator("[data-testid=my-score]").count() == 0
    assert not late.get_by_text("WASD").first.is_visible()  # no keys to press without a snake
    wait_for(lambda: frame(late).get("t", 0) > 2, "the board moving for someone watching", 15)
    shot(late, "2_watching")
    wait_for(lambda: "主人" in late.inner_text("[data-testid=room-people]"), "who is in")
    late.locator("[data-testid=take-over]").first.click()
    wait_for(lambda: on(late, "my-score") and not on(late, "take-over"), "a snake of their own")
    me_seat = late.get_attribute("#arena", "data-me")
    assert me_seat == "s2", me_seat
    assert next(s for s in frame(late)["snakes"] if s["id"] == "s2")["k"] == "person"
    steered = False
    for _ in range(20):  # it may crash while nobody steers it: press when it is on the board
        snake = next(s for s in frame(late)["snakes"] if s["id"] == "s2")
        if snake["body"]:
            want = "up" if snake["dir"] in ("left", "right") else "left"
            late.keyboard.press("Arrow" + want.capitalize())
            late.wait_for_timeout(500)
            steered = next(s for s in frame(late)["snakes"] if s["id"] == "s2")["dir"] == want
            if steered:
                break
        late.wait_for_timeout(300)
    assert steered, "their keys don't steer it"
    log("   watched, took an AI snake over, steered it")

    log("3. the host's connection drops while waiting")
    phone = new_page(browser, errors)
    code3 = host_room(phone, "手機主人", 4)
    phone.context.set_offline(True)
    time.sleep(13)
    invited = new_page(browser, errors)
    by_link(invited, code3)
    invited.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "離線中" in people(invited), "the host shown as away")
    phone.context.set_offline(False)
    wait_for(lambda: on(phone, "room") and "離線中" not in people(invited), "the host back", 25)
    assert phone.inner_text("[data-testid=code]").strip() == code3 and on(phone, "start")
    assert "手機主人" in people(invited) and "朋友" not in people(invited)
    log("   the link worked, the host came back to their room")

    log("4. a connection lost in the middle of a match")
    lost = new_page(browser, errors)
    alone(lost, "斷線的人")
    wait_for(lambda: not on(lost, "countdown"), "the match going", 15)
    wait_for(lambda: frame(lost).get("t", 0) > 5, "the snakes moving", 15)
    lost.context.set_offline(True)
    time.sleep(10)
    lost.context.set_offline(False)
    wait_for(lambda: ticking(lost), "the board moving again", 25)
    assert on(lost, "my-score") and next(s for s in frame(lost)["snakes"] if s["id"] == "s1")["k"] == "person"
    assert not on(lost, "take-over")
    lost.reload()
    lost.wait_for_selector("[data-testid=arena]")
    wait_for(lambda: ticking(lost), "a reload keeps the match", 15)
    log("   back in the same match, with the snake")

    log("5. leaving, reloading, and a dead link")
    stays = new_page(browser, errors)
    code5 = host_room(stays, "留下的人", 4)
    goes = new_page(browser, errors)
    by_link(goes, code5)
    goes.wait_for_selector("[data-testid=room]")
    goes.click("[data-testid=leave-room]")
    goes.wait_for_selector("[data-testid=lobby]")
    assert "?r=" not in goes.url, goes.url
    goes.reload()
    goes.wait_for_selector("[data-testid=lobby]")
    goes.wait_for_timeout(1500)
    assert on(goes, "lobby") and "訪客" not in people(stays)
    by_link(goes, "ZZZZ")
    goes.wait_for_selector("[data-testid=notice]")
    assert "已經結束" in goes.inner_text("[data-testid=notice]") and on(goes, "lobby")
    wait_for(lambda: "?r=" not in goes.url, "the dead code gone from the address")
    log("   stayed out; a dead link says so")

    log("6. your own settings, and a guest's name")
    guest = new_page(browser, errors)
    open_lobby(guest)
    for key in ("foe-practice", "speed-slow", "length-120", "total-5"):
        guest.click(f"[data-testid={key}]")
    wait_for(lambda: active(guest, "total-5"), "their settings chosen")
    nameless = new_page(browser, errors)
    code6 = host_room(nameless, "", 3)
    assert "訪客" in people(nameless), people(nameless)
    by_link(guest, code6)
    guest.wait_for_selector("[data-testid=room]")
    wait_for(lambda: people(nameless).count("訪客") == 2, "both listed with a name")
    guest.wait_for_timeout(600)
    saved = guest.evaluate("['speed','length','total'].map(k => localStorage.getItem('snake_duel_' + k))")
    assert [s.strip('"') for s in saved] == ["slow", "120", "5"], saved
    guest.click("[data-testid=leave-room]")
    guest.wait_for_selector("[data-testid=lobby]")
    assert active(guest, "total-5") and active(guest, "speed-slow")
    log("   settings kept:", saved)

    log("7. inviting someone online, and typing the code")
    inviter = new_page(browser, errors)
    code7 = host_room(inviter, "邀請人", 4)
    online = new_page(browser, errors)
    open_lobby(online, name="線上朋友")
    wait_for(lambda: inviter.locator("[data-testid=friend]", has_text="線上朋友").count() == 1, "them in the list of people online", 15)
    inviter.locator("[data-testid=friend]", has_text="線上朋友").locator("[data-testid=friend-invite]").click()
    online.wait_for_selector("[data-testid=invite]", timeout=10000)
    assert "邀請人" in online.inner_text("[data-testid=invite-text]") and code7 in online.inner_text("[data-testid=invite-text]")
    shot(online, "7_invited")
    online.click("[data-testid=invite-accept]")
    online.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "線上朋友" in people(inviter), "they came")
    typed = new_page(browser, errors)
    open_lobby(typed, name="打房號的人")
    wait_for(lambda: typed.locator(f"[data-testid=room-row][data-room=\"{code7}\"]").count() == 1, "the room offered, with a picture")
    assert typed.locator(f"[data-testid=room-row][data-room=\"{code7}\"] img").get_attribute("src").startswith("data:image/png")
    shot(typed, "7_lobby_list")
    typed.fill("[data-testid=code-box]", code7.lower())
    typed.keyboard.press("Enter")
    typed.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "打房號的人" in people(inviter), "typed in")
    log("   invited from the room, typed the code")

    log("8. two people and no AI")
    one = new_page(browser, errors)
    code8 = host_room(one, "甲", 2)
    two = new_page(browser, errors)
    by_link(two, code8)
    two.wait_for_selector("[data-testid=room]")
    wait_for(lambda: "2 個人" in one.inner_text("[data-testid=total-note]"), "both in")
    one.click("[data-testid=start]")
    one.wait_for_selector("[data-testid=countdown]")
    wait_for(lambda: not on(one, "countdown"), "the start", 15)
    assert not on(one, "ai-panel") and not on(two, "ai-panel")
    one.click("[data-testid=leave]")
    two.click("[data-testid=leave]")
    log("   no AI panel")

    log("9. more people than the seats the host picks")
    many = new_page(browser, errors)
    code9 = host_room(many, "主", 3)
    for _ in range(2):
        other = new_page(browser, errors)
        by_link(other, code9)
        other.wait_for_selector("[data-testid=room]")
    wait_for(lambda: many.locator("[data-testid=room-people] [data-testid=person]").count() == 3, "three in")
    many.click("[data-testid=total-2]")
    many.wait_for_timeout(700)
    assert active(many, "total-3") and not active(many, "total-2"), "the chips don't show the room"
    log("   the room's own number is lit")

    log("10. the end of a match with someone watching")
    host.wait_for_selector("[data-testid=result]", timeout=90000)
    late_seat = late.get_attribute("#arena", "data-me")
    assert late_seat == "s2"
    viewer = new_page(browser, errors)
    by_link(viewer, code2)
    viewer.wait_for_selector("[data-testid=result]")
    wait_for(lambda: viewer.locator("[data-testid=places] tbody tr").count() == 3, "the places")
    assert viewer.locator("[data-testid=again]").count() == 0
    text = viewer.inner_text("[data-testid=outcome]")
    assert "贏了" in text or "平手" in text, text
    log("   someone arriving now reads:", text)
    host.click("[data-testid=again]")
    viewer.wait_for_selector("[data-testid=countdown]", timeout=15000)
    wait_for(lambda: viewer.get_attribute("#arena", "data-me") == "s3", "a seat in the next match")
    f = frame(viewer)
    assert [s["k"] for s in f["snakes"]] == ["person", "person", "person"], f["snakes"]
    log("   a seat in the next match; all three seats are people, no AI filled in")
    shot(viewer, "10_next_match")
    browser.close()
finish(errors)
