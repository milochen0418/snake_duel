"""Snake Duel (雙蛇搶食): two snakes after the same food, you against the AI the AI Hub sets for
this app."""

import reflex as rx
from reflex_ddns_auth import ai

from snake_duel import brain
from snake_duel.state import Game
from snake_duel.views import index

# The arena's canvas is drawn by this script (assets/snake_duel/arena.js).
app = rx.App(head_components=[rx.el.script(src="/snake_duel/arena.js", defer=True)])
app.add_page(index, route="/", title="Snake Duel · 雙蛇搶食", on_load=Game.on_load)

# The AI Hub's page lists this app's AI by these words, with the model each answers with.
ai.uses(app, **brain.USES)
