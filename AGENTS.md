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

- **The rules** are plain Python in `snake_duel/engine.py`: `step()` moves both snakes at once and settles crashes, food and comebacks; `pilot()` is the AI snake's body (shortest safe way to a goal, the most room without one, never next to the other head when it can help it, never into a pocket too small for it); `greedy()` is the practice snake's whole mind.
- **The AI** is the AI Hub's role `fast` (`snake_duel/brain.py`, through `reflex_ddns_auth.ai`): the game holds no model, key or hub address. `ai.uses` in `snake_duel.py` puts the game's row on the hub's page, where the model is chosen. The AI is shown the board as text and answers in two lines (targets in order, a few words), read by `brain.parse`. It never steers a step: without an answer its snake only dodges.
- **A match** (`snake_duel/match.py`) holds the world and the AI's plan and says when to ask again (plan ran out, a gold one appeared, `REASK` seconds after an answer; one ask at a time).
- **One background task per match** (`Game.run_match` in `snake_duel/state.py`) ticks it, sends the board to the page as JSON (`frame`), starts the asks without waiting for them, and stops when `_seq` changes or the tab has been gone for `STALE` seconds (cancelling the ask, which stops the model). The person's turns queue up in `_turns` (key listener → `Game.key`).
- **The arena** is a canvas drawn by `assets/snake_duel/arena.js` from the canvas's `data-frame`; it also turns swipes and the on-screen pad into arrow keys and keeps arrows from scrolling the page. A new file under `assets/` needs a container restart in the dev-mode install; edits to it hot-reload.
- **Finished matches** are one JSON line each in `SNAKE_DUEL_DATA_DIR/matches.jsonl` (`snake_duel/history.py`), summed per opponent for the lobby's scoreboard.
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
