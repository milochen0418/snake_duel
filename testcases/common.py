"""Helpers shared by the Playwright suites (imported by each run_test.py)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:3000").rstrip("/")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", Path(__file__).resolve().parent / "output"))
HEADLESS = os.environ.get("HEADLESS", "1").strip().lower() not in {"0", "false", "no", "off"}
SLOWMO = int(os.environ.get("PW_SLOWMO_MS", "0") or 0)
TIMEOUT = int(os.environ.get("PW_TIMEOUT_MS", "30000") or 30000)
_T0 = time.time()


def log(*args) -> None:
    print(f"[{time.time() - _T0:6.2f}]", *args, flush=True)


def launch(pw: Playwright) -> Browser:
    args = []
    if BASE_URL.startswith("https://") and ".reflex-ddns.com" in BASE_URL:
        # A Mac may resolve *.reflex-ddns.com to the Docker-internal IP.
        args.append("--host-resolver-rules=MAP *.reflex-ddns.com 127.0.0.1")
    return pw.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, args=args)


def new_page(browser: Browser, errors: list[str], *, locale: str = "zh-TW", width: int = 1280, height: int = 900) -> Page:
    ctx = browser.new_context(viewport={"width": width, "height": height}, locale=locale, ignore_https_errors=True)
    page = ctx.new_page()
    page.set_default_timeout(TIMEOUT)

    def on_console(msg) -> None:  # noqa: ANN001
        if msg.type == "error" and "Outdated Optimize Dep" not in msg.text and "Failed to load resource" not in msg.text:
            errors.append(f"console: {msg.text}")

    page.on("console", on_console)
    page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
    return page


def shot(page: Page, name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT_DIR / f"{name}.png"), full_page=True)


def wait_for(fn, what: str, timeout: float = 30.0) -> None:
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            if fn():
                return
        except Exception as e:  # noqa: BLE001 - keep trying until the deadline
            last = e
        time.sleep(0.2)
    raise AssertionError(f"timed out: {what}" + (f" (last error: {last})" if last else ""))


def open_lobby(page: Page) -> str:
    """Opens the lobby and waits for the AI Hub's answer: the opponent's name ("" without one)."""
    page.goto(BASE_URL + "/", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid=lobby]", timeout=90000)
    page.wait_for_timeout(500)
    wait_for(lambda: page.locator("[data-testid=asking]").count() == 0, "the AI Hub's answer", 30)
    opponent = page.locator("[data-testid=opponent]")
    return opponent.inner_text().strip() if opponent.count() else ""


def frame(page: Page) -> dict:
    """The board the arena draws now (the canvas's data-frame)."""
    raw = page.get_attribute("#arena", "data-frame") or "{}"
    return json.loads(raw) if raw else {}


def drawn(page: Page) -> int:
    """How many distinct colours a coarse sample of the canvas has (a blank one has 1 or 2)."""
    return page.evaluate(
        """() => {
        const c = document.getElementById("arena");
        const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
        const seen = new Set();
        for (let i = 0; i < d.length; i += 4 * 97) seen.add(d[i] + "," + d[i + 1] + "," + d[i + 2]);
        return seen.size;
    }"""
    )


WAYS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


def snake(f: dict, sid: str) -> dict:
    """One snake of a frame, by id ("you", "ai1" …)."""
    return next(s for s in f["snakes"] if s["id"] == sid)


def choose(f: dict) -> str | None:
    """The arrow key that takes the person's snake towards the nearest food without boxing it in
    or meeting another head (None: keep going)."""
    you = snake(f, "you")
    if not you["body"]:
        return None
    head, heading = tuple(you["body"][0]), you["dir"]
    taken = {tuple(c) for s in f["snakes"] for c in s["body"][:-1]}
    for other in f["snakes"]:
        if other["id"] != "you" and other["body"]:
            hx, hy = other["body"][0]
            taken |= {(hx + dx, hy + dy) for dx, dy in WAYS.values()}

    def free(c: tuple[int, int]) -> bool:
        return 0 <= c[0] < f["w"] and 0 <= c[1] < f["h"] and c not in taken

    def room(start: tuple[int, int]) -> int:
        seen, todo = {start}, [start]
        while todo and len(seen) < 60:
            x, y = todo.pop()
            for dx, dy in WAYS.values():
                c = (x + dx, y + dy)
                if c not in seen and free(c):
                    seen.add(c)
                    todo.append(c)
        return len(seen)

    foods = [(fd["x"], fd["y"]) for fd in f["food"]]
    goal = min(foods, key=lambda c: abs(c[0] - head[0]) + abs(c[1] - head[1])) if foods else None
    best = None
    for way, (dx, dy) in WAYS.items():
        nxt = (head[0] + dx, head[1] + dy)
        if way == OPPOSITE[heading] or not free(nxt):
            continue
        space = room(nxt)
        near = -(abs(goal[0] - nxt[0]) + abs(goal[1] - nxt[1])) if goal else 0
        score = (space >= len(you["body"]) + 3, near, space, way == heading)
        if best is None or score > best[0]:
            best = (score, way)
    if best is None or best[1] == heading:
        return None
    return "Arrow" + best[1].capitalize()


def number(page: Page, test_id: str) -> int:
    return int(page.inner_text(f"[data-testid={test_id}]").strip().replace("−", "-"))


def places(page: Page) -> list[dict]:
    """The result's table: a row per snake, best first."""
    rows = []
    for tr in page.locator("[data-testid=places] tbody tr").all():
        cells = [c.inner_text().strip() for c in tr.locator("td").all()]
        rank, name, points, apples, golds, crashes = cells[:6]
        rows.append({"rank": int(rank), "name": name, "points": int(points.replace("−", "-")), "apples": int(apples), "golds": int(golds), "crashes": int(crashes), "asks": cells[6]})
    return rows


def check_places(rows: list[dict]) -> None:
    """Every snake's points add up, and the places go by points."""
    for row in rows:
        assert row["points"] == row["apples"] + 3 * row["golds"] - 3 * row["crashes"], row
    assert [r["points"] for r in rows] == sorted((r["points"] for r in rows), reverse=True), rows
    for a, b in zip(rows, rows[1:]):
        assert (a["rank"] == b["rank"]) == (a["points"] == b["points"]), rows


def finish(errors: list[str]) -> None:
    if errors:
        print("\n".join(errors[:40]))
        raise SystemExit("page errors (see above)")
    log("PASS")
