# Snake Duel 雙蛇搶食 🐍⚔️

Snake against an AI: **up to five snakes on one board, after the same food**. You steer yours with the arrow keys (or by swiping). Pick how many snakes the arena holds, 2 to 5: **the people playing take the first seats and AI snakes fill the rest**, so two of you in an arena of five means three AI snakes. Play alone against one AI snake, or open a room and send your friends the link. Every match is kept **per model and arena**, so you can switch the AI's model and compare.

Built with [Reflex](https://reflex.dev/) for the [re-ddns](https://github.com/milochen0418/re_ddns) Agentic App Store. The opponent is whatever model the [AI Hub](https://github.com/milochen0418/ai_hub) sets for this app: Snake Duel holds no model and no key.

## 🎮 How a match goes

1. The lobby shows what the AI snakes use (the model the AI Hub answers with, or the practice snake), how many snakes the arena holds (2 to 5), the speed (slow, normal, fast: 210, 160 or 120 ms a step) and the length (1 or 2 minutes). **Play alone** starts at once; **Play with people** opens a room with a four-letter code, listed in everyone's lobby and shareable as a link (`/?r=CODE`). Whoever joins takes a seat, and the host starts when everyone is in.
2. A 3-second countdown over the starting board, every snake with its name; yours has a line under its name and a dashed ring round its head. With two snakes, on a 24×16 board, they face each other from opposite corners; with more, on a 30×20 board, they start evenly round the middle, all going the same way round. There is always one apple more than there are snakes, placed about as far from every head as the board allows. You can already turn.
3. All snakes move at the same moment, step after step. An apple is worth 1 point, a gold one 3: it shows up every so often, about as far from the two nearest heads, and vanishes after 8 seconds. Eating makes a snake one cell longer.
4. Hitting a wall, yourself or another snake costs 3 points and 2 seconds off the board; the snake comes back somewhere roomy, far from the other heads. When heads meet, all of them lose.
5. If someone closes their tab, an AI takes their snake over (name and score and all), so the arena stays as full as it started.
6. When time is up the places go by points, the same list for everyone in the room. The result shows every snake's place, points, apples, gold ones and crashes, each AI snake's decisions and seconds per decision, and how the AIs did together: how many decisions, how long each took, how many gave nothing and how many were off the format. The host can start another match with the same people, and the match goes onto the lobby's scoreboard.

## 🧠 How the AI plays

A language model takes a second or more to answer, while the snakes move several times a second, so the AI can't steer each step. It plays like a person thinking ahead instead: it is shown the board from its snake's side (the scores, every snake, every food with how many steps it and the nearest other snake are from it, and one on one a map with coordinates) and answers in two lines:

```
目標：B, D, A          (Target: the food to go for, in order — or a cell, to block)
說：那顆金果是我的！    (Say: a few words to you, shown in a speech bubble)
```

Its snake's body then takes the shortest safe way there by itself: around walls and bodies, keeping off the cells other heads could move into, and never into a pocket too small for it. Once a target is eaten it goes on to the next. The AI is asked again whenever its list runs out, a gold one shows up, or a moment after its last answer; each snake has at most one question out at a time, and the snakes don't wait for it. **Without an answer the snake only dodges: it never goes after food by itself**, so the model's decisions (and how fast they come) are what make it play well.

**Every AI snake asks for itself**, from where it is, with the same model; the AI snakes are rivals, not a team, and they see the people and each other by number. All of them get the same rules text (so a local model can reuse what it already read), and with more than two snakes their boards leave the map out (the steps already go round the bodies). With three snakes asking one Ollama model in turn, the two together halved the wait (qwen2.5:7b on an M4 Pro: 5.2 s → 2.3 s a decision, against 1.4 s with two snakes).

On the page you see where each AI snake is heading (a dashed ring and a dotted line in its colour: blue, violet, green, pink), what it said, the last decisions with their seconds, and how long each has been thinking. A model that thinks before it answers (such as `qwen3.5:9b`) takes most of a minute per decision, so its snake mostly dodges: give Snake Duel a quick model (such as `qwen2.5:7b`) on the AI Hub.

The **practice snake** needs no AI: about once a second it picks, by one simple rule, the nearest food it gets to first. It is there for warming up, for playing without an AI Hub, and as a baseline for the models.

## 🏆 Comparing models

The scoreboard keeps every finished match per opponent and arena (how many snakes, and how many of them people): matches, wins for the people / for the AI snakes / draws (a match goes to the people when a person alone comes first, and is a draw when a person and an AI snake share first place), an AI snake's mean score and crashes per match, and the mean seconds per decision. To try another model, change it on the AI Hub's page (*What each app's AI uses* → `snake-duel`), reload the lobby and play again.

## 🛠️ How it is built

- `snake_duel/engine.py`: the rules, in plain Python, for 2 to 5 snakes in the seats `s1` … `s5`: a tick moves all snakes at once and settles crashes, food and comebacks; `pilot()` is an AI snake's body (the shortest safe way to a goal, or the most room without one); `greedy()` is the practice snake's rule.
- `snake_duel/brain.py`: what an AI is told (the rules and the board from its snake's side, as text) and `parse()`, which reads its two lines; it asks the AI Hub for the role `fast` through `reflex_ddns_auth.ai`.
- `snake_duel/match.py`: one match as it is played: a seat per snake (a person's, or an AI's with its plan, when to ask again and what each answer did), and `hand_to_ai()` for a person who leaves.
- `snake_duel/rooms.py`: the arenas people share. A room is a plain object in this process, with one task that ticks its match, asks the AIs and keeps the board as JSON; the people in it take the first seats and AI snakes fill the rest.
- `snake_duel/state.py`: one browser tab. Its background task tells the room it is still there, copies the board and the scores into that tab's own view, and keeps the lobby's room list fresh; a tab that stops looking is dropped from its room a few seconds later (a reload keeps the seat).
- `assets/snake_duel/arena.js`: draws the board on a canvas, gliding the snakes between steps, each in its colour, with little bursts for food and crashes; turns swipes and the on-screen pad into arrow keys.
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
poetry run ./run_test_suite.sh play_match          # a whole match of two against the practice snake
poetry run ./run_test_suite.sh play_crowd          # a whole match of four, alone against three practice snakes
poetry run ./run_test_suite.sh play_together       # two people in one room, with AI snakes filling the rest
DDNS_AI_HUB_URL=… DDNS_AUTH_SECRET=… SERVICE_SUBDOMAIN=snake-duel \
  poetry run ./run_test_suite.sh play_ai           # a whole one-on-one match against the hub's model
```

See [testcases/README.md](testcases/README.md).

## License

MIT
