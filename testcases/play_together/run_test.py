"""Two people in one arena (no AI Hub needed): one opens a room of four, the other finds it in
the lobby's list and joins by its link; both see each other, the host starts, and two AI snakes
fill the empty seats. Each page steers its own snake with the arrow keys (the little bot of
``common.choose``) and sees the same board; the result gives four places on both pages, and the
scoreboard keeps the match as four snakes with two people.

Two browser contexts, so the two tabs are two different people to the server.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BASE_URL, check_places, choose, finish, frame, launch, log, new_page, number, open_lobby, places, shot, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    host = new_page(browser, errors)
    open_lobby(host, name="小明")
    host.click("[data-testid=foe-practice]")
    host.click("[data-testid=total-4]")
    host.click("[data-testid=speed-fast]")
    host.click("[data-testid=length-60]")
    host.click("[data-testid=host]")
    host.wait_for_selector("[data-testid=room]")
    code = host.inner_text("[data-testid=code]").strip()
    log("room:", code)
    assert len(code) == 4 and host.locator("[data-testid=waiting]").count() == 0  # the host starts it
    assert "小明" in host.inner_text("[data-testid=room-people]")

    guest = new_page(browser, errors)
    open_lobby(guest, name="阿美")
    wait_for(lambda: guest.locator(f"[data-testid=room-row][data-room=\"{code}\"]").count() == 1, "the room in the lobby's list")
    assert "小明" in guest.inner_text(f"[data-testid=room-row][data-room=\"{code}\"]")
    guest.goto(f"{BASE_URL}/?r={code}", wait_until="domcontentloaded")  # the invite link
    guest.wait_for_selector("[data-testid=room]")
    assert guest.inner_text("[data-testid=code]").strip() == code
    wait_for(lambda: "阿美" in host.inner_text("[data-testid=room-people]"), "the host sees the guest")
    wait_for(lambda: "2" in host.inner_text("[data-testid=total-note]"), "two people, two AI snakes")
    assert "小明" in guest.inner_text("[data-testid=room-people]")
    assert guest.locator("[data-testid=waiting]").count() == 1  # only the host may start
    shot(host, "1_room_host")
    shot(guest, "2_room_guest")

    host.click("[data-testid=start]")
    for page in (host, guest):
        page.wait_for_selector("[data-testid=countdown]", timeout=30000)
    wait_for(lambda: frame(host).get("t") == 0, "the starting board")
    f = frame(host)
    assert [s["id"] for s in f["snakes"]] == ["s1", "s2", "s3", "s4"]
    assert [s["n"] for s in f["snakes"]] == ["小明", "阿美", "AI 1", "AI 2"]
    assert [s["k"] for s in f["snakes"]] == ["person", "person", "ai", "ai"]
    seats = {page.get_attribute("#arena", "data-me") for page in (host, guest)}
    assert seats == {"s1", "s2"}, seats  # each page steers its own snake
    assert host.locator("[data-testid=ai-card]").count() == 2
    shot(host, "3_countdown")

    for page in (host, guest):
        wait_for(lambda page=page: page.locator("[data-testid=countdown]").count() == 0, "the start", 15)
    deadline = time.time() + 90
    last, keys, same, shots = -1, {"s1": 0, "s2": 0}, 0, 0
    while host.locator("[data-testid=result]").count() == 0:
        assert time.time() < deadline, "the match didn't end"
        f = frame(host)
        if f.get("t", -1) != last:
            last = f["t"]
            for page in (host, guest):
                me = page.get_attribute("#arena", "data-me")
                own = frame(page)
                if own.get("t") == last and (key := choose(own, me)):
                    page.keyboard.press(key)
                    keys[me] += 1
            same += frame(guest).get("t", -1) in (last, last + 1)  # both pages draw the one board
            if not shots and last > 150:
                shot(host, "4_playing_host")
                shot(guest, "5_playing_guest")
                shots = 1
        host.wait_for_timeout(30)
    log(f"ticks up to {last}; keys pressed {keys}; frames where both pages agreed: {same}")
    assert keys["s1"] > 5 and keys["s2"] > 5, keys
    assert same > last * 0.5, f"the pages drew different boards ({same} of {last})"

    for page in (host, guest):
        page.wait_for_selector("[data-testid=result]", timeout=15000)
    table = places(host)
    log("places:", table)
    check_places(table)
    assert sorted(r["name"] for r in table) == ["AI 1", "AI 2", "小明", "阿美"]
    assert places(guest) == table  # the same result for both
    for page, name in ((host, "小明"), (guest, "阿美")):
        yours = next(r for r in table if r["name"] == name)
        assert yours["points"] == number(page, "my-score")
        tied = sum(1 for r in table if r["rank"] == yours["rank"]) > 1
        want = ("你並列第一" if tied else "你拿第一！") if yours["rank"] == 1 else f"你第 {yours['rank']} 名"
        assert page.inner_text("[data-testid=outcome]") == want, (name, page.inner_text("[data-testid=outcome]"))
    assert guest.locator("[data-testid=again]").count() == 0  # only the host plays another
    shot(host, "6_result_host")
    shot(guest, "7_result_guest")

    guest.click("[data-testid=to-lobby]")
    guest.wait_for_selector("[data-testid=board]")
    board = guest.inner_text("[data-testid=board]")
    assert "練習蛇" in board and "4 隻蛇（2 人）" in board, board
    shot(guest, "8_board")

    # The host plays on alone: the guest's snake is handed to an AI.
    host.click("[data-testid=again]")
    host.wait_for_selector("[data-testid=countdown]", timeout=30000)
    wait_for(lambda: frame(host).get("t") == 0, "the next board")
    again = frame(host)
    assert [s["k"] for s in again["snakes"]] == ["person", "ai", "ai", "ai"], again["snakes"]
    assert host.get_attribute("#arena", "data-me") == "s1"
    host.click("[data-testid=leave]")
    host.wait_for_selector("[data-testid=lobby]")
    browser.close()
finish(errors)
