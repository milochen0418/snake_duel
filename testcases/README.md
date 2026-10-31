# E2E testcases

Playwright end-to-end suites, one per folder:

- `testcases/<suite_name>/run_test.py`
- `testcases/<suite_name>/output/` (screenshots and logs, ignored by git)

Each `run_test.py` exits `0` on success and non-zero on failure, and writes its screenshots into
`OUTPUT_DIR` (provided by the runner). Shared helpers (opening a browser, the lobby, reading the
board the canvas draws, a little bot that steers a person's snake, the result's table) are in
`common.py`. The
runner points `SNAKE_DUEL_DATA_DIR` at a fresh folder in `OUTPUT_DIR`, so the matches a suite
plays don't land on your scoreboard.

## Suites

| Suite | What it checks |
|-------|----------------|
| `smoke_home` | The lobby: the opponent from the AI Hub (or the note that there is none, with the buttons off for it but on for the practice snake), how many snakes the arena holds and what fills the seats, the name box, speed, length and opponent kept in the browser over a reload, the empty room list, the English switch, no sideways scrolling on a phone. |
| `play_match` | A whole one-minute match of two at the fast speed, played alone against the practice snake (no AI Hub needed): the countdown over the starting board drawn on the canvas, a turn pressed before the start, the person's snake steered with the arrow keys by the bot, the practice snake's aim and decisions, places with points that add up (apples + 3 × gold − 3 × crashes), the final word, the scoreboard's row. About 70 s. |
| `play_crowd` | The same alone with the arena set to four snakes, on the 30×20 board: four named snakes, a card and a score per AI snake, each of them heading somewhere of its own and listed by name in the decisions, four places that add up, the person's place in the final word, the scoreboard's row. About 70 s. |
| `play_together` | Two people in one room (two browser contexts, no AI Hub needed): one opens a room of four, the other finds it in the lobby's list and joins by its link, both see each other, and two AI snakes fill the empty seats. Each page steers its own snake and draws the same board; both get the same four places, each with their own place in the final word; then the host plays on alone and the guest's snake is handed to an AI. About 90 s. |
| `invite_flows` | A link and a connection, whatever anyone is doing (no AI Hub needed, about 90 s): opened in the middle of your own match, while the room plays, with the host offline, after the room is over; a connection lost mid-match; leaving and reloading; your own settings kept; inviting someone online; typing the code; people only; the end of a match with someone watching. |
| `signed_in` | (Needs `DDNS_AUTH_SECRET`, the server's own: it signs test cookies, so use it on a local server. Skipped without.) Two accounts by their names and pictures, two tabs of an account as one snake, a guest who signs in keeping their place. |
| `call_everyone` | (Needs an installed call app, so run it on re-ddns. Skipped without.) Calling everyone in the middle of a match, the incoming call over the game, Join call · 2, and the keys steering the snake with the call in the tray. |
| `play_ai` | (Needs an AI Hub; skipped without one.) A whole one-minute duel at the slow speed against the hub's model: its decisions come in with words and seconds, its snake heads for the food it named, the result counts its decisions, the model's row on the scoreboard. Give it a quick model (a thinking one only dodges, and the suite fails). |

## Running

Use the repo-level runner (it starts and stops the Reflex server and collects artifacts):

```bash
poetry run ./run_test_suite.sh smoke_home
poetry run ./run_test_suite.sh play_match
poetry run ./run_test_suite.sh play_crowd
poetry run ./run_test_suite.sh play_together
poetry run ./run_test_suite.sh invite_flows
DDNS_AUTH_SECRET=test poetry run ./run_test_suite.sh signed_in
DDNS_AI_HUB_URL=http://127.0.0.1:8182 DDNS_AUTH_SECRET=<the hub's secret> SERVICE_SUBDOMAIN=snake-duel \
  poetry run ./run_test_suite.sh play_ai
```

If ports 3000/8000 belong to another app, use others: `FRONTEND_PORT=3181 BACKEND_PORT=8181`.

To test a deployed instance (e.g. behind re-ddns), run a script directly:

```bash
BASE_URL=https://snake-duel.reflex-ddns.com OUTPUT_DIR=/tmp/snake-duel-e2e \
  poetry run python testcases/play_match/run_test.py
```

Keep `OUTPUT_DIR` outside the repo when the target is a re-ddns **dev-mode** install of this
checkout: that container watches the mounted source, so screenshots written under `testcases/`
hot-reload its backend in the middle of the match. A match played there goes onto that
scoreboard.

Optional env vars:
- `BASE_URL` (default `http://127.0.0.1:3000`)
- `HEADLESS=0` to watch the browser
- `PW_SLOWMO_MS=100` to slow actions down
- `PW_TIMEOUT_MS=60000` to increase Playwright timeouts
