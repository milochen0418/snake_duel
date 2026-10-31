"""Snake Duel (雙蛇搶食): up to five snakes after the same food, people and the AI the AI Hub sets
for this app."""

import reflex as rx
from reflex_ddns_auth import AuthState, ai
from reflex_ddns_auth.intent import install_intent_host

from snake_duel import brain
from snake_duel.api import api
from snake_duel.state import Game
from snake_duel.views import call_keepalive, index

app = rx.App(
    # The arena's canvas is drawn by this script (assets/snake_duel/arena.js).
    head_components=[rx.el.script(src="/snake_duel/arena.js", defer=True)],
    # What a shared link answers with, next to Reflex's routes.
    api_transformer=api,
)
app.add_page(index, route="/", title="Snake Duel · 雙蛇搶食", description="Up to five snakes after the same food: people, and AI snakes filling the rest", on_load=[AuthState.load_auth, Game.on_load])

# Calls run in the app-wide intent dialogs, so a call goes on whatever the page shows.
install_intent_host(app)
app.extra_app_wraps[(8, "SnakeCallKeepalive")] = lambda stateful: rx.fragment(call_keepalive())

# The AI Hub's page lists this app's AI by these words, with the model each answers with.
ai.uses(app, **brain.USES)
