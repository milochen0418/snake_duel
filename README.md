# Snake Duel 雙蛇搶食 🐍⚔️

Snake against an AI: **two snakes on one board, after the same food**. You steer the orange snake with the arrow keys (or by swiping); the AI plays the blue one. Every match is kept **per model**, so you can switch the AI's model and compare.

Built with [Reflex](https://reflex.dev/) for the [re-ddns](https://github.com/milochen0418/re_ddns) Agentic App Store. The opponent is whatever model the [AI Hub](https://github.com/milochen0418/ai_hub) sets for this app: Snake Duel holds no model and no key.

## 🎮 How a match goes

1. The lobby shows your opponent (the model the AI Hub answers with, or the practice snake), the speed (slow, normal, fast: 210, 160 or 120 ms a step) and the length (1 or 2 minutes).
2. A 3-second countdown over the starting board: the snakes face each other from opposite corners, with three apples as far from one as from the other. You can already turn.
3. Both snakes move at the same moment, step after step. An apple is worth 1 point, a gold one 3: it shows up every so often, about as far from both heads, and vanishes after 8 seconds. Eating makes a snake one cell longer.
4. Hitting a wall, yourself or the other snake costs 3 points and 2 seconds off the board; the snake comes back somewhere roomy, far from the other head. When the heads meet, both lose.
5. When time is up the higher score wins. The result shows both sides' apples, gold ones and crashes, and how the AI did: how many decisions it made, how long each took, how many gave nothing and how many were off the format. The match goes onto the lobby's scoreboard.

## 🧠 How the AI plays

A language model takes a second or more to answer, while the snakes move several times a second, so the AI can't steer each step. It plays like a person thinking ahead instead: it is shown the board (the score, both snakes, every food with how many steps each head is from it, and a map with coordinates) and answers in two lines:

```
目標：B, D, A          (Target: the food to go for, in order — or a cell, to block)
說：那顆金果是我的！    (Say: a few words to you, shown in a speech bubble)
```

Its snake's body then takes the shortest safe way there by itself: around walls and bodies, keeping off the cell your head could move into, and never into a pocket too small for it. Once a target is eaten it goes on to the next. The AI is asked again whenever its list runs out, a gold one shows up, or a moment after its last answer; only one question is out at a time, and the snakes don't wait for it. **Without an answer the snake only dodges: it never goes after food by itself**, so the model's decisions (and how fast they come) are what make it play well.

On the page you see where it is heading (a dashed ring and a dotted line on the board), what it said, its last decisions with their seconds, and how long it has been thinking. A model that thinks before it answers (such as `qwen3.5:9b`) takes most of a minute per decision, so its snake mostly dodges: give Snake Duel a quick model (such as `qwen2.5:7b`) on the AI Hub.

The **practice snake** needs no AI: about once a second it picks, by one simple rule, the nearest food it gets to first. It is there for warming up, for playing without an AI Hub, and as a baseline for the models.

## 🏆 Comparing models

The scoreboard keeps every finished match per opponent: matches, your wins / the AI's / draws, the AI's mean score, its crashes per match and its mean seconds per decision. To try another model, change it on the AI Hub's page (*What each app's AI uses* → `snake-duel`), reload the lobby and play again.

## 🛠️ How it is built

- `snake_duel/engine.py`: the rules, in plain Python: a tick moves both snakes at once and settles crashes, food and comebacks; `pilot()` is the AI snake's body (the shortest safe way to a goal, or the most room without one); `greedy()` is the practice snake's rule.
- `snake_duel/brain.py`: what the AI is told (the rules and the board as text) and `parse()`, which reads its two lines; it asks the AI Hub for the role `fast` through `reflex_ddns_auth.ai`.
- `snake_duel/match.py`: one match as it is played: the AI's plan, when to ask again, what each answer did.
- `snake_duel/state.py`: one background task per match ticks the world, puts the board on the page as JSON and starts the asks; a closed tab calls the match off after a few seconds (a reload keeps it).
- `assets/snake_duel/arena.js`: draws the board on a canvas, gliding the snakes between steps, with little bursts for food and crashes; turns swipes and the on-screen pad into arrow keys.
- `snake_duel/history.py`: finished matches as JSON lines in `SNAKE_DUEL_DATA_DIR` (default `~/.local/share/snake_duel`), summed per opponent.
- `snake_duel/views.py`, `snake_duel/i18n.py`: the page, in 繁體中文 and English.

## 🚀 Running it

**On re-ddns:** install *Snake Duel* from the App Store (and the AI Hub, to play an AI). Then on the AI Hub's page pick a quick model for `snake-duel` and open `https://snake-duel.reflex-ddns.com`.

**Running it on its own** (for development): the practice snake works without anything else. To play an AI, run an AI Hub (see its README) and point the game at it with the same secret:

```bash
poetry env use python3.15
poetry install
DDNS_AI_HUB_URL=http://127.0.0.1:8182 DDNS_AUTH_SECRET=<the hub's secret> SERVICE_SUBDOMAIN=snake-duel \
  SNAKE_DUEL_DATA_DIR=/tmp/snake_duel REFLEX_API_URL=http://localhost:8181 \
  poetry run reflex run --frontend-port 3181 --backend-port 8181
```

## 🧪 Tests

```bash
poetry run pytest                                  # rules, the AI snake's body, the AI's replies, a match, the scoreboard
poetry run ./run_test_suite.sh smoke_home          # the lobby
poetry run ./run_test_suite.sh play_match          # a whole match against the practice snake
DDNS_AI_HUB_URL=… DDNS_AUTH_SECRET=… SERVICE_SUBDOMAIN=snake-duel \
  poetry run ./run_test_suite.sh play_ai           # a whole match against the hub's model
```

See [testcases/README.md](testcases/README.md).

## License

MIT
