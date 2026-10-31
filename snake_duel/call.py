"""Calls for everyone in a room, carried out by a call app through the DDNS Intent ``call.join``
(the same way as ReflexGrid and CoDoc in MD).

Snake Duel keeps who is in each room's call and rings the people in the room; the call itself
runs in the call app, opened in the intent dialog:

    Intent.start(<call app>, "call.join", private={"room": <call id>}, keep_alive=True,
                 single=True, title=..., user=..., name=...)

- Anyone in a room can call everyone in it: the others get an incoming call (Accept / Decline)
  for RING_SECONDS.
- While the call is on, everyone in the room (also people who come later) sees "Join call" with
  the number of people in it.
- The call dialog is keep-alive (it can sit in the tray, still talking, while you play) and
  single (joining another call closes it).

Whoever starts a call chooses its app among the installed apps that provide ``call.join``, through
``Intent.choose_app``, which asks only when there are several. The call keeps that app, so
everyone who answers or joins later opens the same call without being asked. The call id is
private: anyone holding it can join, so it stays out of the iframe URL and out of what pages show.

The calls live in this process's memory (``CallStore``). Each page reads how its room's call
stands when it looks at the room (``view``), so it reaches all of them within a moment.
"""

from __future__ import annotations

import secrets
import time
from typing import Dict, List, TypedDict

import reflex as rx
from reflex_ddns_auth.intent import Intent, IntentState

CALL_ACTION = "call.join"
RING_SECONDS = 45  # how long a new call rings the people in the room
TOUCH_SECONDS = 15  # a tab in a call refreshes its entry this often...
STALE_SECONDS = 150  # ...and is dropped after this long without it (background tabs are slowed)
OPENING_GRACE_SECONDS = 10  # the dialog opens one event after joining: not a closed dialog


class Member(TypedDict):
    id: str
    name: str


class RoomCall(TypedDict):
    call_id: str
    app: str  # the call app chosen by whoever started it: everyone joins through it
    started_by_name: str
    started_at: float
    ringing: bool
    members: Dict[str, Member]  # client token -> who: a person may be in it from several tabs
    last_seen: Dict[str, float]
    responded: List[str]  # uids who joined or declined: they are not rung (again)
    invited: List[str]  # uids in the room when the call started: the people it rings


class CallStore:
    """The call of each room, at most one."""

    calls: Dict[str, RoomCall] = {}

    @classmethod
    def cleanup(cls, code: str, now: float) -> None:
        """Drop members gone silent, stop ringing after RING_SECONDS, end an empty call."""
        call = cls.calls.get(code)
        if call is None:
            return
        for token, seen in list(call["last_seen"].items()):
            if now - seen > STALE_SECONDS:
                call["members"].pop(token, None)
                call["last_seen"].pop(token, None)
        if call["ringing"] and now - call["started_at"] > RING_SECONDS:
            call["ringing"] = False
        if not call["members"]:
            del cls.calls[code]

    @classmethod
    def join(cls, code: str, token: str, member: Member, now: float, app: str, invited: List[str] | None = None, call_id: str = "") -> RoomCall:
        """Join the room's call, starting it in ``app`` (ringing ``invited``) if there is none."""
        call = cls.calls.get(code)
        if call is None:
            call = RoomCall(
                call_id=call_id or secrets.token_urlsafe(12),
                app=app,
                started_by_name=member["name"],
                started_at=now,
                ringing=not call_id,  # a call put back after being dropped doesn't ring again
                members={},
                last_seen={},
                responded=[],
                invited=list(invited or []),
            )
            cls.calls[code] = call
        call["members"][token] = member
        call["last_seen"][token] = now
        if member["id"] not in call["responded"]:
            call["responded"].append(member["id"])
        return call

    @classmethod
    def leave(cls, code: str, token: str) -> None:
        """Take a tab out of the room's call; the call ends with its last member."""
        call = cls.calls.get(code)
        if call is None:
            return
        call["members"].pop(token, None)
        call["last_seen"].pop(token, None)
        if not call["members"]:
            del cls.calls[code]

    @classmethod
    def decline(cls, code: str, uid: str) -> None:
        call = cls.calls.get(code)
        if call is not None and uid not in call["responded"]:
            call["responded"].append(uid)


def view(code: str, uid: str) -> tuple[int, str]:
    """How this room's call stands for this person: how many are in it, and who is ringing them
    ("" when nobody is)."""
    if not code:
        return 0, ""
    CallStore.cleanup(code, time.time())
    call = CallStore.calls.get(code)
    if call is None:
        return 0, ""
    rung = call["ringing"] and uid in call["invited"] and uid not in call["responded"]
    return len(call["members"]), call["started_by_name"] if rung else ""


class CallState(rx.State):
    """This tab's side of a room's call."""

    current_room: str = ""  # the room whose call this tab is in
    _call_id: str = ""
    _call_app: str = ""  # to put the call back as it was
    _joined_at: float = 0.0
    _starting_room: str = ""  # the room of the call this tab starts, while it chooses the app

    async def _me(self) -> tuple[str, str, str, str]:
        """(room on screen, uid, display name, language) of this tab."""
        from snake_duel.state import Game

        game = await self.get_state(Game)
        return game.code, game._uid, game._my_name, game.lang

    @rx.event
    async def join_call(self):
        """Call everyone in the room, or join its call, and open it in the dialog."""
        return await self._join("")

    @rx.event
    async def start_call(self, data: dict):
        """The caller chose the call app: call everyone in the room with it."""
        code, self._starting_room = self._starting_room, ""
        on_screen, _, _, _ = await self._me()
        if code and code == on_screen and data.get("app"):
            # Joins instead if someone called everyone in the room meanwhile.
            return await self._join(data["app"])

    async def _join(self, app: str):
        """Join the room's call in its app, or start the call in ``app``. Without ``app``, a new
        call first lets the caller choose it (``start_call`` comes back here with it)."""
        from snake_duel import rooms

        code, uid, name, lang = await self._me()
        room = rooms.get(code)
        if room is None or not uid:
            return
        dialog = await self.get_state(IntentState)
        if self.current_room == code and CALL_ACTION in dialog.open_actions:
            return Intent.show(CALL_ACTION)  # already in it, maybe minimized
        if code not in CallStore.calls and not app:
            self._starting_room = code
            return Intent.choose_app(CALL_ACTION, on_result=CallState.start_call)
        now = time.time()
        token = self.router.session.client_token
        if self.current_room and self.current_room != code:
            CallStore.leave(self.current_room, token)
        call = CallStore.join(code, token, Member(id=uid, name=name), now, app, invited=sorted(room.players))
        self.current_room = code
        self._call_id = call["call_id"]
        self._call_app = call["app"]
        self._joined_at = now
        title = f"雙蛇搶食 · 房間 {code}" if lang == "zh" else f"Snake Duel · room {code}"
        return Intent.start(
            call["app"],
            CALL_ACTION,
            on_result=CallState.call_closed,
            on_cancel=CallState.call_closed,
            private={"room": call["call_id"]},
            keep_alive=True,
            single=True,
            label=f"Call · {code}",
            title=title,
            user=uid,
            name=name,
        )

    @rx.event
    async def decline_call(self):
        code, uid, _, _ = await self._me()
        CallStore.decline(code, uid)

    @rx.event
    async def call_closed(self, data: dict):
        """The call dialog closed (hung up or closed): leave the call. Being replaced means
        another call took its place: ``_join`` already moved us."""
        if data.get("reason") == "replaced" and data.get("by") == CALL_ACTION:
            return
        code, self.current_room, self._call_id = self.current_room, "", ""
        if code:
            CallStore.leave(code, self.router.session.client_token)

    @rx.event
    async def heartbeat(self):
        """Keep this tab in its call while the call dialog runs (in front or minimized)."""
        if not self.current_room:
            return
        now = time.time()
        token = self.router.session.client_token
        code = self.current_room
        dialog = await self.get_state(IntentState)
        if CALL_ACTION not in dialog.open_actions and now - self._joined_at > OPENING_GRACE_SECONDS:
            CallStore.leave(code, token)
            self.current_room, self._call_id = "", ""
            return
        CallStore.cleanup(code, now)
        call = CallStore.calls.get(code)
        if call is not None and call["call_id"] != self._call_id:
            self.current_room, self._call_id = "", ""
            return
        if call is None or token not in call["members"] or now - call["last_seen"][token] > TOUCH_SECONDS:
            # Touch our entry, or put the call back if it was dropped while the dialog still runs it.
            _, uid, name, _ = await self._me()
            CallStore.join(code, token, Member(id=uid, name=name), now, self._call_app, call_id=self._call_id)
