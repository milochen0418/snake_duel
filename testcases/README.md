# E2E testcases

Playwright end-to-end suites, one per folder:

- `testcases/<suite_name>/run_test.py`
- `testcases/<suite_name>/output/` (screenshots and logs, ignored by git)

Each `run_test.py` exits `0` on success and non-zero on failure, and writes its screenshots into
`OUTPUT_DIR` (provided by the runner). Shared helpers (opening a browser, the lobby, reading the
board the canvas draws, a little bot that steers the person's snake) are in `common.py`. The
runner points `SNAKE_DUEL_DATA_DIR` at a fresh folder in `OUTPUT_DIR`, so the matches a suite
plays don't land on your scoreboard.

## Suites

| Suite | What it checks |
|-------|----------------|
| `smoke_home` | The lobby: the opponent from the AI Hub (or the note that there is none, with Start off for it but on for the practice snake), the mode (the number of AI snakes only for a free-for-all), speed, length, mode and opponent kept in the browser over a reload, the English switch, no sideways scrolling on a phone. |
| `play_match` | A whole one-minute duel at the fast speed against the practice snake (no AI Hub needed): the countdown over the starting board drawn on the canvas, a turn pressed before the start, the person's snake steered with the arrow keys by the bot, the practice snake's aim and decisions, places with points that add up (apples + 3 × gold − 3 × crashes), the final word, the scoreboard's row. About 70 s. |
| `play_crowd` | A whole one-minute free-for-all at the fast speed against three practice snakes on the 30×20 board: four named snakes, a card and a score per AI snake, each of them heading somewhere of its own and listed by name in the decisions, four places that add up, the person's place in the final word, the scoreboard's free-for-all row. About 70 s. |
| `play_ai` | (Needs an AI Hub; skipped without one.) A whole one-minute duel at the slow speed against the hub's model: its decisions come in with words and seconds, its snake heads for the food it named, the result counts its decisions, the model's row on the scoreboard. Give it a quick model (a thinking one only dodges, and the suite fails). |

## Running

Use the repo-level runner (it starts and stops the Reflex server and collects artifacts):

```bash
poetry run ./run_test_suite.sh smoke_home
poetry run ./run_test_suite.sh play_match
poetry run ./run_test_suite.sh play_crowd
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
