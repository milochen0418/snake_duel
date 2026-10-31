"""The backend's own HTTP routes (next to Reflex's): what a shared link answers with.

``GET /r/<code>``: the page behind an invite link (:func:`snake_duel.preview.page`), and
``GET /r/<code>/board.png``: its picture. The paths are listed in ``backend-paths.txt``, so
re-ddns sends them here instead of to the frontend. A room that is over still gets an answer: an
old link in a chat keeps its card, and whoever opens it lands in the lobby.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from snake_duel import preview, rooms

_FRESH = {"Cache-Control": "no-store"}


def _base(request: Request) -> str:
    """This site's address as the visitor sees it (behind re-ddns the request itself says http)."""
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"


async def invite_page(request: Request) -> Response:
    code = request.path_params["code"].strip().upper()
    return HTMLResponse(preview.page(rooms.get(code), code, _base(request)), headers=_FRESH)


async def board_image(request: Request) -> Response:
    return Response(preview.picture(rooms.get(request.path_params["code"])), media_type="image/png", headers=_FRESH)


api = Starlette(routes=[Route("/r/{code}", invite_page), Route("/r/{code}/board.png", board_image)])
