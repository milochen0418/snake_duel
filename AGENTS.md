# AGENTS.md

This file describes how an AI coding agent (and humans) should work in this repository.

## 0) Always read the docs first

Before making changes or running commands, **read all README.md files in this repo** and follow them.

- Repo overview & dev workflow: `README.md`
- E2E test runner conventions: `testcases/README.md`

If you already read them earlier in the session, **re-check** when unsure.

## 1) Python / Poetry requirements (strict)

This project is developed on **Python 3.15**; the range allows 3.11 too, the Python of the
re_ddns App Store image (python:3.11).

- Prefer Poetry-managed environments.
- If Poetry selected another Python, switch it:

```bash
poetry env use python3.15
poetry env info
poetry install
```

If `python3.15` is not available on PATH, use an absolute path to the 3.15 executable.

## 2) Default rule: use `poetry run` for scripts

When running any repo scripts, prefer:

- `poetry run <command>`

This ensures the correct virtualenv + dependencies are used.

## 3) Running the app: prefer `reflex_rerun.sh`

When you need to start/restart the Reflex app during development, **prefer the repo helper script**.

Typical usage:

```bash
poetry run ./reflex_rerun.sh
```

Notes:
- Prefer `poetry run ./reflex_rerun.sh` over `poetry run reflex run`.
- It runs on the expected ports: frontend `3000`, backend `8000` (it kills whatever holds them).
- Other apps on this machine may own 3000/8000. Then run on other ports and point the frontend at the backend: `REFLEX_API_URL=http://localhost:8181 poetry run reflex run --frontend-port 3181 --backend-port 8181`.
- The AI opponent comes from an AI Hub: outside re-ddns, point the app at one with `DDNS_AI_HUB_URL` and the same `DDNS_AUTH_SECRET` (see README, "Running it on its own"); the practice snake needs none.
- Set `SNAKE_DUEL_DATA_DIR` to a scratch folder when trying things, so test matches don't land on the real scoreboard.

## 4) Running E2E suites: prefer `run_test_suite.sh`

E2E suites live under `testcases/<suite_name>/run_test.py`.

Do **not** run Playwright suites by starting/stopping the server manually unless you have to.
Use the repo runner, which starts/stops the Reflex server, sets `OUTPUT_DIR` and `SNAKE_DUEL_DATA_DIR`, and collects artifacts:

```bash
poetry run ./run_test_suite.sh smoke_home
```

Optional environment variables (see `testcases/README.md`): `BASE_URL`,
`FRONTEND_PORT` / `BACKEND_PORT`, `HEADLESS=0`.

Unit tests: `poetry run pytest`.

## 4.5) How Snake Duel is put together

- **The rules** are plain Python in `snake_duel/engine.py`, for 2 to 5 snakes in the seats `s1` … `s5` (two snakes play on 24×16, more on 30×20): `step()` moves all snakes at once and settles crashes, food and comebacks; `pilot()` is an AI snake's body (shortest safe way to a goal, the most room without one, never next to another head when it can help it, never into a pocket too small for it); `greedy()` is the practice snake's whole mind.
- **The AI** is the AI Hub's role `fast` (`snake_duel/brain.py`, through `reflex_ddns_auth.ai`): the game holds no model, key or hub address. `ai.uses` in `snake_duel.py` puts the game's row on the hub's page, where the model is chosen. Each AI snake is shown the board from its side as text (with a map when only two snakes are playing, without when more, to keep the wait down) and answers in two lines (targets in order, a few words), read by `brain.parse`. Every snake is named by its seat number, people and AI snakes alike. The rules text (`brain.system`) is the same for every snake of a match, so a model can reuse it. It never steers a step: without an answer its snake only dodges.
- **A match** (`snake_duel/match.py`) holds the world and a `Seat` per snake — a person's, or an AI's with its plan and asks — and says when to ask each AI again (plan ran out, a gold one appeared, `REASK` seconds after an answer; one ask at a time per snake). The people take the first seats and AI snakes fill the rest up to the chosen total; `hand_to_ai()` gives a leaver's snake to an AI.
- **A room** (`snake_duel/rooms.py`) is the arena people share: a plain object in this process, in `rooms.rooms` by its four-letter code, with one asyncio task (`_run`) for its whole life — waiting, playing, the result — and the board as JSON in `room.frame`. People are `uid`s: the signed-in e-mail (all of a person's tabs are one player) or `guest-<id>` of one tab (a Relack guest has a nickname and no e-mail, so they are one of these, by that nickname). Playing alone opens a room of one that isn't listed. **Nothing hurries to end, so that a link keeps working:** a player whose page goes quiet for `STALE` seconds is away (an AI stands in, `touch` gives the snake back), a host away for `HOST_WAIT` lets anyone here lead, a match with nobody here for `EMPTY_PLAY` is called off, and a room lives `LINGER` seconds after its last person. Anyone may enter at any time: mid-match they watch (`take_over` puts them on an AI snake). Nothing in it is a Reflex state, so the tests step a room by hand (with no event loop, `ensure_task` makes no task).
- **One background task per browser tab** (`Game.watch` in `snake_duel/state.py`) copies what the room shows into that tab's own vars (only what changed) and keeps the lobby's lists fresh; an older task stops when `_seq` changes. **The page's heartbeat** (`Game.beat`, a click on a hidden button every 1.5 s from `arena.js`) is what says someone is here. It is also what restarts the watcher: Reflex rehydrates a tab that reconnects but doesn't run `on_load` again, and may even give it a new token, which is why a guest's id is in `rx.SessionStorage`. Keys go straight into the player's turns (`Game.key` → `rooms.turn`). Words are per tab, so the room keeps language-free snapshots (`Chip`, `AiLook`, `Place`, `verdict`) and the tab turns them into text.
- **Links**: `/r/<code>` (`api.py`, `preview.py`; `backend-paths.txt` sends `/r/` to the backend, which needs a container restart to change) answers with OpenGraph tags and moves on to `/?r=<code>`, which `Game.on_load` reads. `on_load` is where every case of an arriving link is decided. The address bar is kept true with `history.replaceState` (`_address`), so a reload after leaving doesn't pull anyone back in.
- **Calls** (`snake_duel/call.py`, ported from ReflexGrid): `CallStore` keyed by room code, `install_intent_host` + `call_keepalive` in `snake_duel.py`, read by each tab in `_mirror` through `call.view`.
- **The arena** is a canvas drawn by `assets/snake_duel/arena.js` from the canvas's `data-frame` (snakes by seat; their colours match `TEXT_COLORS`/`DOT_COLORS` in `views.py`; `data-me` is this tab's own snake, which it marks and rings; `data-faces` the people's pictures, drawn next to their names); it also turns swipes and the on-screen pad into arrow keys and keeps arrows from scrolling the page. A new file under `assets/` needs a container restart in the dev-mode install; edits to it hot-reload.
- **Finished matches** are one JSON line each in `SNAKE_DUEL_DATA_DIR/matches.jsonl` (`snake_duel/history.py`, with `snakes`, `people` and a `sides` list), summed per opponent and arena for the lobby's scoreboard. `sides_of()` also reads the older records (`you` + `ai`/`ais`), so don't drop that.
- Words of the UI: `snake_duel/i18n.py` (繁體中文, English).

## 4.6) The re-ddns dev-mode install

- `smart-app-snake-duel` bind-mounts this checkout and hot-reloads on **any** file change in it. A reload restarts the backend and ends a match being played. Keep test output outside the checkout (`OUTPUT_DIR=...`) when testing against `https://snake-duel.reflex-ddns.com`.
- `pyproject.toml`, `rxconfig.py`, `poetry.lock` are copied into the container at start: changes to them need `docker restart smart-app-snake-duel`.
- Diagnose with `docker logs smart-app-snake-duel`.

## 5) Expectations when acting as an agent

- Prefer the smallest, focused change set.
- After code changes, run the closest relevant check (at minimum the related suite via `run_test_suite.sh`).
- Report outcomes: what you ran, pass/fail, and where artifacts/logs were written.

## 6) Smart way to help the Agent to debug

```
poetry run ./reflex_rerun.sh --loglevel debug
```
