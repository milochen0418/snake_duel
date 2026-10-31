"""The page: who is here, the lobby, the room people wait in, the arena with the scores and what
each AI snake is doing, and the result."""

from __future__ import annotations

import reflex as rx
from reflex_ddns_auth import AuthState

from snake_duel.call import CallState
from snake_duel.history import ModelRow
from snake_duel.match import NAME_LEN, TOTALS, Decision
from snake_duel.rooms import Card, Chip, Place
from snake_duel.state import AiCard, Friend, Game, Person

T = Game.t

CARD = "rounded-2xl border border-slate-800 bg-slate-900/70 p-4 sm:p-5"
YOU = "text-amber-300"
AI = "text-cyan-300"
SMALL_BUTTON = "flex items-center gap-1.5 rounded-full border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:border-slate-500"
# Each seat's colour; the canvas draws the snakes the same (assets/snake_duel/arena.js).
TEXT_COLORS = {"s1": YOU, "s2": AI, "s3": "text-violet-300", "s4": "text-lime-300", "s5": "text-pink-300"}
DOT_COLORS = {"s1": "bg-amber-400", "s2": "bg-cyan-400", "s3": "bg-violet-400", "s4": "bg-lime-400", "s5": "bg-pink-400"}


def _color(sid: rx.Var, colors: dict[str, str], extra: str = "") -> rx.Var:
    return rx.match(sid, *[(k, f"{v} {extra}".strip()) for k, v in colors.items()], f"text-slate-300 {extra}".strip())


def _dot(sid: rx.Var) -> rx.Component:
    return rx.el.span(class_name=_color(sid, DOT_COLORS, "inline-block h-2.5 w-2.5 shrink-0 rounded-full"))


def _face(avatar: rx.Var, name: rx.Var, size: str = "h-6 w-6 text-[11px]") -> rx.Component:
    """Someone's picture, or the first letter of their name."""
    return rx.cond(
        avatar != "",
        rx.el.img(src=avatar, alt=name, title=name, referrer_policy="no-referrer", class_name=f"{size} shrink-0 rounded-full object-cover"),
        rx.el.span(name[0], title=name, class_name=f"{size} flex shrink-0 items-center justify-center rounded-full bg-slate-700 font-medium text-slate-100"),
    )


def _chip(label: rx.Var | str | rx.Component, active: rx.Var | bool, on_click: rx.EventHandler, test_id: str) -> rx.Component:
    return rx.el.button(
        label,
        on_click=on_click,
        data_testid=test_id,
        class_name=rx.cond(
            active,
            "rounded-full border border-amber-300 bg-amber-300/15 px-3.5 py-1.5 text-sm font-medium text-amber-200",
            "rounded-full border border-slate-700 px-3.5 py-1.5 text-sm text-slate-300 hover:border-slate-500",
        ),
    )


def account() -> rx.Component:
    return rx.cond(
        AuthState.is_logged_in,
        rx.el.div(
            _face(AuthState.user_avatar, AuthState.user_name),
            rx.el.span(AuthState.user_name, data_testid="me-name", class_name="hidden max-w-[10rem] truncate text-sm text-slate-200 sm:inline"),
            rx.el.a(T["sign_out"], href=AuthState.logout_url, class_name="text-sm text-slate-400 hover:text-slate-200"),
            class_name="flex items-center gap-2",
        ),
        rx.el.a(T["sign_in"], href=Game.login_link, data_testid="sign-in", class_name="text-sm text-amber-300 hover:underline"),
    )


def header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.icon("worm", size=22, class_name="text-amber-300"),
            rx.el.span(T["app"], class_name="text-lg font-semibold tracking-wide"),
            class_name="flex items-center gap-2",
        ),
        rx.el.div(
            account(),
            rx.el.button(
                rx.icon("languages", size=16),
                T["lang_other"],
                on_click=Game.switch_lang,
                data_testid="lang",
                class_name="flex items-center gap-1.5 rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:border-slate-500",
            ),
            class_name="flex items-center gap-3",
        ),
        class_name="flex items-center justify-between gap-3 py-4",
    )


def notice_bar() -> rx.Component:
    return rx.cond(
        Game.notice != "",
        rx.el.p(Game.notice, data_testid="notice", class_name="mb-3 rounded-xl border border-rose-400/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-200"),
    )


def invite_bar() -> rx.Component:
    """Someone invited this person, or they opened a link in the middle of a match: they choose."""
    return rx.cond(
        Game.invite_code != "",
        rx.el.div(
            rx.icon("mail", size=18, class_name="shrink-0 text-amber-300"),
            rx.el.span(Game.invite_text, data_testid="invite-text", class_name="min-w-0 flex-1 text-sm text-slate-100"),
            rx.el.button(
                rx.cond(Game.mid_match, T["invite_mid"], T["invite_yes"]),
                on_click=Game.accept_invite,
                data_testid="invite-accept",
                class_name="rounded-full bg-amber-400 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-amber-300",
            ),
            rx.el.button(T["invite_no"], on_click=Game.decline_invite, data_testid="invite-decline", class_name=SMALL_BUTTON),
            data_testid="invite",
            class_name="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-amber-300/50 bg-amber-300/10 px-3 py-2",
        ),
    )


# ------------------------------------------------------------ the call


def call_button() -> rx.Component:
    """Call everyone in the room, or join its call while one is in progress."""
    return rx.cond(
        Game.call_count > 0,
        rx.el.button(
            rx.icon("phone-call", size=16),
            T["call_join"],
            " · ",
            Game.call_count,
            on_click=CallState.join_call,
            data_testid="call-join",
            class_name="flex items-center gap-1.5 rounded-full bg-emerald-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-emerald-400",
        ),
        rx.el.button(rx.icon("phone", size=16), T["call_everyone"], on_click=CallState.join_call, title=T["call_tip"], data_testid="call-everyone", class_name=SMALL_BUTTON),
    )


def incoming_call() -> rx.Component:
    """Someone called everyone in the room: accept or decline. Above the dialogs (z-index 1000)."""
    return rx.cond(
        Game.call_from != "",
        rx.el.div(
            rx.el.div(rx.icon("phone-incoming", size=20), class_name="flex h-10 w-10 shrink-0 animate-pulse items-center justify-center rounded-full bg-emerald-500 text-slate-950"),
            rx.el.div(
                rx.el.div(T["call_in"], class_name="text-xs font-semibold uppercase tracking-wider text-emerald-300"),
                rx.el.div(Game.call_from, class_name="truncate font-semibold text-slate-100"),
                rx.el.div(T["call_ringing"], class_name="text-xs text-slate-400"),
                class_name="min-w-0 flex-1",
            ),
            rx.el.button(
                rx.icon("phone-off", size=16),
                on_click=CallState.decline_call,
                title=T["call_decline"],
                aria_label="Decline",
                data_testid="call-decline",
                class_name="flex rounded-full bg-rose-500/20 p-2.5 text-rose-300 hover:bg-rose-500/30",
            ),
            rx.el.button(
                rx.icon("phone", size=16),
                on_click=CallState.join_call,
                title=T["call_accept"],
                aria_label="Accept",
                data_testid="call-accept",
                class_name="flex rounded-full bg-emerald-500 p-2.5 text-slate-950 hover:bg-emerald-400",
            ),
            role="alertdialog",
            aria_label="Incoming call",
            data_testid="incoming-call",
            class_name="fixed bottom-5 right-5 z-[1001] flex w-80 max-w-[calc(100vw-2rem)] items-center gap-3 rounded-2xl border border-slate-700 bg-slate-900 p-3 shadow-2xl",
        ),
    )


_CALL_HEARTBEAT_JS = """
if (window.__snakeCallBeat) clearInterval(window.__snakeCallBeat);
window.__snakeCallBeat = setInterval(function () {
    var el = document.getElementById('call-heartbeat-trigger');
    if (!el) { clearInterval(window.__snakeCallBeat); window.__snakeCallBeat = null; return; }
    el.click();
}, 3000);
"""


@rx.memo
def call_keepalive() -> rx.Component:
    """While in a call, keep its heartbeat going (the call runs in the app-wide intent dialogs)."""
    return rx.cond(
        CallState.current_room != "",
        rx.el.button(
            id="call-heartbeat-trigger",
            on_click=CallState.heartbeat,
            on_mount=rx.call_script(_CALL_HEARTBEAT_JS),
            tab_index=-1,
            aria_hidden="true",
            class_name="sr-only",
        ),
    )


# ------------------------------------------------------------ the settings, shared by both views


def _setting(label: rx.Var, *chips: rx.Component, first: bool = False) -> rx.Component:
    return rx.el.div(
        rx.el.div(label, class_name="mb-2 text-sm text-slate-400"),
        rx.el.div(*chips, class_name="flex flex-wrap gap-2"),
        class_name="" if first else "mt-4",
    )


def total_setting() -> rx.Component:
    return rx.el.div(
        _setting(
            T["total"],
            *[_chip(rx.fragment(n, T["total_n"]), Game.shown_total == n, Game.set_total(n), f"total-{n}") for n in TOTALS],
            first=True,
        ),
        rx.el.p(Game.total_note, data_testid="total-note", class_name="mt-2 text-sm text-slate-400"),
    )


def speed_and_length() -> rx.Component:
    return rx.fragment(
        _setting(
            T["speed"],
            _chip(T["speed_slow"], Game.shown_speed == "slow", Game.set_speed("slow"), "speed-slow"),
            _chip(T["speed_normal"], Game.shown_speed == "normal", Game.set_speed("normal"), "speed-normal"),
            _chip(T["speed_fast"], Game.shown_speed == "fast", Game.set_speed("fast"), "speed-fast"),
        ),
        _setting(
            T["length"],
            _chip(T["length_60"], Game.shown_length == "60", Game.set_length("60"), "length-60"),
            _chip(T["length_120"], Game.shown_length == "120", Game.set_length("120"), "length-120"),
        ),
    )


def name_box() -> rx.Component:
    """A guest's name; someone signed in goes by their account."""
    return rx.cond(
        AuthState.is_logged_in,
        rx.el.div(
            _face(AuthState.user_avatar, AuthState.user_name, "h-8 w-8 text-sm"),
            rx.el.span(AuthState.user_name, class_name="truncate text-slate-100"),
            class_name="flex items-center gap-2",
        ),
        rx.el.div(
            rx.el.label(T["your_name"], class_name="mb-1 block text-sm text-slate-400"),
            rx.el.input(
                default_value=Game.name,
                placeholder=T["your_name"],
                max_length=NAME_LEN,
                on_blur=Game.set_name,
                data_testid="name",
                class_name="w-full rounded-xl border border-slate-700 bg-slate-950/60 px-3 py-2 text-slate-100 outline-none focus:border-amber-300",
            ),
            rx.el.p(T["name_hint"], class_name="mt-1 text-xs text-slate-500"),
        ),
    )


# ------------------------------------------------------------ the lobby


def opponent_card() -> rx.Component:
    hub = rx.el.div(
        rx.match(
            Game.hub_state,
            ("asking", rx.el.div(T["asking_hub"], data_testid="asking", class_name="text-slate-300")),
            ("ok", rx.el.div(Game.opponent, data_testid="opponent", class_name="font-mono text-lg font-semibold text-cyan-200 break-all")),
            ("none", rx.el.div(T["no_hub"], class_name="text-rose-300")),
            rx.el.div(T["hub_error"], " ", Game.hub_error, class_name="text-rose-300 break-words"),
        ),
        rx.cond(
            (Game.hub_state == "ok") | (Game.hub_state == "error"),
            rx.fragment(
                rx.el.p(T["change_model_help"], class_name="mt-3 text-sm leading-relaxed text-slate-400"),
                rx.cond(
                    Game.hub_page != "",
                    rx.el.a(
                        T["change_model"],
                        rx.icon("external-link", size=14),
                        href=Game.hub_page,
                        target="_blank",
                        class_name="mt-2 inline-flex items-center gap-1 text-sm text-cyan-300 hover:underline",
                    ),
                ),
            ),
        ),
    )
    return rx.el.div(
        rx.el.div(
            rx.icon("bot", size=28, class_name=AI),
            rx.el.div(
                rx.el.div(T["opponent"], class_name="text-xs uppercase tracking-wider text-slate-400"),
                rx.el.div(
                    _chip(T["foe_hub"], Game.foe == "hub", Game.set_foe("hub"), "foe-hub"),
                    _chip(T["foe_practice"], Game.foe == "practice", Game.set_foe("practice"), "foe-practice"),
                    class_name="mt-2 flex flex-wrap gap-2",
                ),
                class_name="min-w-0",
            ),
            class_name="flex items-start gap-3",
        ),
        rx.el.div(
            rx.cond(Game.foe == "practice", rx.el.p(T["practice_note"], class_name="text-sm leading-relaxed text-slate-400"), hub),
            class_name="mt-4",
        ),
        class_name=CARD,
    )


def settings_card() -> rx.Component:
    return rx.el.div(
        name_box(),
        rx.el.div(total_setting(), class_name="mt-4"),
        speed_and_length(),
        rx.el.div(
            rx.el.button(
                rx.icon("play", size=18),
                T["start_alone"],
                on_click=Game.play_alone,
                disabled=~Game.can_start,
                data_testid="start",
                class_name="flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 py-3 text-base font-semibold text-slate-950 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40",
            ),
            rx.el.button(
                rx.icon("users", size=18),
                T["start_room"],
                on_click=Game.host_room,
                disabled=~Game.can_start,
                data_testid="host",
                class_name="flex flex-1 items-center justify-center gap-2 rounded-xl border border-amber-300/60 py-3 text-base font-semibold text-amber-200 hover:border-amber-300 disabled:cursor-not-allowed disabled:opacity-40",
            ),
            class_name="mt-5 flex flex-col gap-2 sm:flex-row",
        ),
        class_name=CARD,
    )


def _room_row(card: Card) -> rx.Component:
    return rx.el.button(
        rx.el.img(src=card.thumb, alt=card.id, class_name="h-14 w-[84px] shrink-0 rounded-lg border border-slate-800 object-cover"),
        rx.el.div(
            rx.el.div(
                rx.el.span(card.id, class_name="font-mono text-lg font-semibold tracking-widest text-amber-200"),
                rx.el.span(card.people, " / ", card.total, class_name="text-sm text-slate-400"),
                class_name="flex items-baseline justify-between gap-2",
            ),
            rx.el.div(card.who, class_name="truncate text-sm text-slate-300"),
            rx.el.div(rx.match(card.status, ("open", T["status_open"]), ("play", T["status_play"]), T["status_result"]), class_name="text-xs text-slate-500"),
            class_name="min-w-0 flex-1",
        ),
        on_click=Game.join_room(card.id),
        data_testid="room-row",
        data_room=card.id,
        class_name="flex w-full items-center gap-3 rounded-xl border border-slate-800 p-2 text-left hover:border-amber-300/60",
    )


def rooms_card() -> rx.Component:
    return rx.el.div(
        rx.el.div(T["rooms_title"], class_name="mb-3 font-semibold"),
        rx.cond(
            Game.cards.length() > 0,
            rx.el.div(rx.foreach(Game.cards, _room_row), class_name="space-y-2"),
            rx.el.p(T["rooms_empty"], class_name="text-sm leading-relaxed text-slate-500"),
        ),
        rx.el.form(
            rx.el.input(
                name="code",
                placeholder=T["code_box"],
                max_length=4,
                auto_complete="off",
                data_testid="code-box",
                class_name="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950/60 px-3 py-2 font-mono uppercase tracking-widest text-slate-100 outline-none focus:border-amber-300",
            ),
            rx.el.button(T["code_go"], type="submit", data_testid="code-go", class_name="rounded-xl border border-slate-700 px-4 py-2 text-slate-200 hover:border-slate-500"),
            on_submit=Game.join_code,
            reset_on_submit=True,
            class_name="mt-3 flex gap-2",
        ),
        data_testid="rooms",
        class_name=CARD,
    )


def rules_card() -> rx.Component:
    return rx.el.div(
        rx.el.div(T["rules_title"], class_name="mb-2 font-semibold"),
        rx.el.ol(
            *[rx.el.li(T[f"rule_{i}"]) for i in range(1, 8)],
            class_name="list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-slate-300",
        ),
        class_name=CARD,
    )


def _board_row(row: ModelRow) -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.div(row.model, class_name="font-mono text-cyan-200"),
            rx.el.div(row.arena, class_name="text-xs text-slate-400"),
            class_name="max-w-[14rem] break-all py-2 pr-3",
        ),
        rx.el.td(row.matches, class_name="py-2 pr-3 text-right font-mono"),
        rx.el.td(
            rx.el.span(row.you_won, class_name=YOU),
            " / ",
            rx.el.span(row.ai_won, class_name=AI),
            " / ",
            row.draws,
            class_name="whitespace-nowrap py-2 pr-3 text-right font-mono",
        ),
        rx.el.td(row.ai_points, class_name="py-2 pr-3 text-right font-mono"),
        rx.el.td(row.ai_crashes, class_name="py-2 pr-3 text-right font-mono"),
        rx.el.td(row.ai_secs, class_name="py-2 text-right font-mono"),
        class_name="border-t border-slate-800 align-top",
    )


def board_card() -> rx.Component:
    head = "pb-2 pr-3 text-right text-xs font-normal text-slate-400"
    return rx.el.div(
        rx.el.div(T["board_title"], class_name="mb-3 font-semibold"),
        rx.cond(
            Game.board.length() > 0,
            rx.el.div(
                rx.el.table(
                    rx.el.thead(
                        rx.el.tr(
                            rx.el.th(T["col_model"], class_name="pb-2 pr-3 text-left text-xs font-normal text-slate-400"),
                            rx.el.th(T["col_matches"], class_name=head),
                            rx.el.th(T["col_record"], class_name=head),
                            rx.el.th(T["col_ai_points"], class_name=head),
                            rx.el.th(T["col_ai_crashes"], class_name=head),
                            rx.el.th(T["col_ai_secs"], class_name="pb-2 text-right text-xs font-normal text-slate-400"),
                        )
                    ),
                    rx.el.tbody(rx.foreach(Game.board, _board_row)),
                    class_name="w-full text-sm",
                ),
                class_name="overflow-x-auto",
            ),
            rx.el.p(T["board_empty"], class_name="text-sm text-slate-500"),
        ),
        data_testid="board",
        class_name=CARD,
    )


def lobby() -> rx.Component:
    return rx.el.div(
        rx.el.p(T["tagline"], class_name="mb-5 text-slate-300"),
        rx.el.div(
            rx.el.div(opponent_card(), settings_card(), class_name="flex flex-col gap-4"),
            rx.el.div(rooms_card(), rules_card(), board_card(), class_name="flex min-w-0 flex-col gap-4"),
            class_name="grid gap-4 lg:grid-cols-2",
        ),
        data_testid="lobby",
    )


# ------------------------------------------------------------ who is here, sharing the room


def share_button() -> rx.Component:
    """Shares the room's address: the phone's share sheet, else the clipboard (arena.js)."""
    return rx.el.button(
        rx.icon("share-2", size=16),
        rx.el.span(T["room_link"]),
        data_share=Game.share_link,
        data_title=T["app"],
        data_done=T["room_copied"],
        data_failed=T["room_copy_failed"],
        data_testid="share",
        class_name=SMALL_BUTTON,
    )


def _tag(label: rx.Var) -> rx.Component:
    return rx.el.span(label, class_name="rounded-full bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300")


def _person_row(person: Person) -> rx.Component:
    return rx.el.div(
        rx.el.div(_face(person.avatar, person.name), class_name=rx.cond(person.away, "opacity-40", "")),
        rx.cond(person.seat != "", _dot(person.seat)),
        rx.el.span(person.name, class_name=rx.cond(person.me, "truncate font-medium text-amber-300", "truncate text-slate-200")),
        rx.cond(person.me, rx.el.span(T["room_you"], class_name="text-xs text-slate-400")),
        rx.cond(person.host, _tag(T["room_host"])),
        rx.cond(person.away, _tag(T["room_away"])),
        rx.cond((person.seat == "") & (Game.phase != "room"), _tag(T["room_watching"])),
        data_testid="person",
        class_name="flex items-center gap-2",
    )


def _friend_row(friend: Friend) -> rx.Component:
    return rx.el.div(
        _face(friend.avatar, friend.name),
        rx.el.span(friend.name, class_name="min-w-0 flex-1 truncate text-sm text-slate-200"),
        rx.cond(friend.busy, _tag(T["friend_busy"])),
        rx.cond(
            friend.invited,
            rx.el.span(T["friend_invited"], class_name="text-xs text-slate-400"),
            rx.el.button(T["friend_invite"], on_click=Game.invite_person(friend.key), data_testid="friend-invite", class_name="rounded-full border border-amber-300/60 px-2.5 py-0.5 text-xs text-amber-200 hover:border-amber-300"),
        ),
        data_testid="friend",
        class_name="flex items-center gap-2",
    )


def people_block() -> rx.Component:
    return rx.fragment(
        rx.el.div(
            rx.el.div(T["room_who"], class_name="mb-2 text-xs uppercase tracking-wider text-slate-400"),
            rx.el.div(rx.foreach(Game.room_people, _person_row), class_name="space-y-1.5", data_testid="room-people"),
        ),
        rx.cond(
            Game.friends.length() > 0,
            rx.el.div(
                rx.el.div(T["friends_title"], class_name="mb-2 text-xs uppercase tracking-wider text-slate-400"),
                rx.el.div(rx.foreach(Game.friends, _friend_row), class_name="space-y-1.5", data_testid="friends"),
                class_name="mt-4",
            ),
        ),
    )


def code_block() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(T["room_code"], class_name="text-xs uppercase tracking-wider text-slate-400"),
            rx.el.div(Game.code, data_testid="code", class_name="font-mono text-2xl font-bold tracking-[0.25em] text-amber-200"),
            class_name="min-w-0",
        ),
        rx.el.div(share_button(), call_button(), class_name="flex flex-wrap items-center justify-end gap-2"),
        class_name="flex flex-wrap items-start justify-between gap-3",
    )


def room_view() -> rx.Component:
    guest_settings = rx.el.div(
        rx.el.div(T["room_settings"], class_name="text-sm text-slate-400"),
        rx.el.div(
            rx.el.span(Game.room_total, " ", T["total_n"]),
            rx.el.span(" · "),
            rx.el.span(rx.match(Game.room_speed, ("slow", T["speed_slow"]), ("fast", T["speed_fast"]), T["speed_normal"])),
            rx.el.span(" · "),
            rx.el.span(rx.cond(Game.room_length == "120", T["length_120"], T["length_60"])),
            rx.el.span(" · "),
            rx.el.span(Game.foe_name),
            class_name="mt-1 text-slate-200",
        ),
        rx.el.p(Game.total_note, data_testid="total-note", class_name="mt-2 text-sm text-slate-400"),
    )
    return rx.el.div(
        code_block(),
        rx.el.p(Game.share_link, data_testid="share-link", class_name="mt-2 select-all break-all rounded-lg bg-slate-950/60 px-2 py-1 font-mono text-xs text-slate-400"),
        rx.el.div(people_block(), class_name="mt-5"),
        # Someone who came by the link has not been past the lobby, so they name themselves here.
        rx.el.div(name_box(), class_name="mt-4"),
        rx.el.div(
            rx.cond(Game.lead, rx.el.div(total_setting(), speed_and_length()), guest_settings),
            class_name="mt-5 border-t border-slate-800 pt-4",
        ),
        rx.el.div(
            rx.cond(
                Game.lead,
                rx.el.button(
                    rx.icon("play", size=18),
                    T["start"],
                    on_click=Game.start_match,
                    data_testid="start",
                    class_name="flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 py-3 text-base font-semibold text-slate-950 hover:bg-amber-300",
                ),
                rx.el.div(T["room_wait"], data_testid="waiting", class_name="flex flex-1 items-center justify-center rounded-xl border border-slate-800 py-3 text-slate-400"),
            ),
            rx.el.button(
                T["leave_room"],
                on_click=Game.leave_room,
                data_testid="leave-room",
                class_name="rounded-xl border border-slate-700 px-4 py-3 text-slate-200 hover:border-slate-500",
            ),
            class_name="mt-5 flex gap-2",
        ),
        data_testid="room",
        class_name=CARD + " mx-auto max-w-xl",
    )


# ------------------------------------------------------------ the match


def _other_chip(chip: Chip) -> rx.Component:
    return rx.el.div(
        rx.cond(chip.kind == "person", _face(chip.avatar, chip.name, "h-5 w-5 text-[10px]"), _dot(chip.id)),
        rx.el.span(chip.name, class_name="max-w-[7rem] truncate text-xs text-slate-300"),
        rx.el.span(chip.score, data_testid="chip-score", class_name=_color(chip.id, TEXT_COLORS, "font-mono text-lg font-bold tabular-nums")),
        data_testid="chip",
        data_snake=chip.id,
        class_name="flex items-center gap-1.5",
    )


def scoreboard() -> rx.Component:
    return rx.el.div(
        rx.cond(
            Game.watching,
            rx.el.div(T["watching_title"], data_testid="watching", class_name="text-sm font-medium text-slate-300"),
            rx.el.div(
                rx.el.div(T["you"], class_name=_color(Game.me, TEXT_COLORS, "text-xs uppercase tracking-wider opacity-80")),
                rx.el.div(Game.my_score, data_testid="my-score", class_name=_color(Game.me, TEXT_COLORS, "font-mono text-3xl font-bold tabular-nums")),
                rx.cond(
                    Game.my_out != "",
                    rx.el.div(T["you_out"], " ", Game.my_out, " ", T["sec"], data_testid="my-out", class_name="text-xs text-rose-300"),
                ),
                class_name="min-w-0",
            ),
        ),
        rx.el.div(
            rx.el.div(Game.left, data_testid="left", class_name="font-mono text-2xl font-semibold tabular-nums text-slate-100"),
            rx.el.div(T["sec"], class_name="text-xs text-slate-400"),
            class_name="text-center",
        ),
        rx.el.div(
            rx.el.div(rx.foreach(Game.others, _other_chip), class_name="flex flex-wrap justify-end gap-x-3 gap-y-1"),
            rx.el.div(Game.foe_name, class_name="mt-0.5 truncate font-mono text-xs text-slate-400"),
            class_name="min-w-0 text-right",
        ),
        class_name="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-4 py-2",
    )


def _overlay() -> rx.Component:
    """The countdown, the warm-up and the final word, over the board."""
    box = "pointer-events-none absolute inset-0 flex items-center justify-center rounded-xl"
    return rx.match(
        Game.phase,
        ("warmup", rx.el.div(rx.el.div(T["warmup"], class_name="rounded-xl bg-slate-950/80 px-4 py-3 text-cyan-200"), data_testid="warmup", class_name=box)),
        (
            "countdown",
            rx.el.div(rx.el.div(Game.count, class_name="text-7xl font-black text-amber-200 drop-shadow-lg"), data_testid="countdown", class_name=box + " bg-slate-950/30"),
        ),
        (
            "result",
            rx.el.div(
                rx.el.div(
                    Game.outcome,
                    data_testid="outcome",
                    class_name=rx.match(
                        Game.outcome_tone,
                        ("you", "text-center text-5xl font-black text-amber-300 drop-shadow-lg"),
                        ("ai", "text-center text-5xl font-black text-cyan-300 drop-shadow-lg"),
                        "text-center text-5xl font-black text-slate-200 drop-shadow-lg",
                    ),
                ),
                class_name=box + " bg-slate-950/50",
            ),
        ),
        rx.fragment(),
    )


def arena() -> rx.Component:
    return rx.el.div(
        rx.el.canvas(
            id="arena",
            data_frame=Game.frame,
            data_phase=Game.phase,
            data_me=Game.me,
            data_faces=Game.faces,
            data_testid="arena",
            class_name="block aspect-[3/2] w-full touch-none select-none rounded-xl",
        ),
        _overlay(),
        class_name="relative w-full",
    )


def _pad_button(icon: str, key: str) -> rx.Component:
    return rx.el.button(
        rx.icon(icon, size=22),
        data_key=key,
        aria_label=key,
        class_name="flex h-12 w-12 touch-manipulation items-center justify-center rounded-xl border border-slate-700 bg-slate-800/80 text-slate-200 active:bg-amber-400 active:text-slate-950",
    )


def pad() -> rx.Component:
    """Arrow buttons for phones (the page's script turns a press into an arrow key)."""
    return rx.el.div(
        rx.el.div(_pad_button("chevron-up", "ArrowUp"), class_name="col-start-2"),
        rx.el.div(_pad_button("chevron-left", "ArrowLeft"), class_name="col-start-1 row-start-2"),
        rx.el.div(_pad_button("chevron-down", "ArrowDown"), class_name="col-start-2 row-start-2"),
        rx.el.div(_pad_button("chevron-right", "ArrowRight"), class_name="col-start-3 row-start-2"),
        class_name="mx-auto grid w-max grid-cols-3 grid-rows-2 gap-2 md:hidden",
        data_testid="pad",
    )


def ai_card(card: AiCard) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.span(_dot(card.id), class_name=rx.cond(card.state == "thinking", "flex animate-pulse", "flex")),
            rx.el.span(card.name, class_name=_color(card.id, TEXT_COLORS, "max-w-[8rem] truncate text-sm font-semibold")),
            rx.cond(card.left, _tag(T["ai_took_over"])),
            rx.el.span(card.status, data_testid="ai-status", class_name="text-sm text-slate-300"),
            rx.cond(
                Game.watching,
                rx.el.button(
                    T["take_over"],
                    on_click=Game.take_seat(card.id),
                    data_testid="take-over",
                    class_name="ml-auto rounded-full bg-amber-400 px-2.5 py-0.5 text-xs font-semibold text-slate-950 hover:bg-amber-300",
                ),
            ),
            class_name="flex flex-wrap items-center gap-2",
        ),
        rx.cond(card.slow, rx.el.p(T["slow_note"], data_testid="slow-note", class_name="mt-2 text-sm leading-relaxed text-amber-200")),
        rx.cond(
            card.aim != "",
            rx.el.div(
                rx.el.span(T["ai_goes"], class_name="text-slate-400"),
                rx.el.span(card.aim, data_testid="ai-aim", class_name=_color(card.id, TEXT_COLORS, "font-mono")),
                class_name="mt-1.5 flex items-center gap-2 text-sm",
            ),
        ),
        rx.cond(
            card.words != "",
            rx.el.div("「", card.words, "」", data_testid="ai-words", class_name="mt-2 rounded-xl rounded-tl-sm bg-slate-800/80 px-3 py-1.5 text-sm text-slate-100"),
        ),
        rx.cond(card.note != "", rx.el.p(T["ai_failed"], " ", card.note, class_name="mt-1.5 break-words text-xs text-rose-300")),
        data_testid="ai-card",
        data_ai=card.id,
        class_name="border-t border-slate-800 pt-3 first:border-t-0 first:pt-0",
    )


def _said_row(d: Decision) -> rx.Component:
    return rx.el.tr(
        rx.el.td(d.at, class_name="py-1 pr-2 text-right font-mono text-slate-400"),
        rx.el.td(
            rx.cond(Game.ais.length() > 1, rx.el.span(d.name, " ", class_name=_color(d.who, TEXT_COLORS, "font-sans"))),
            d.aim,
            class_name="whitespace-nowrap py-1 pr-2 font-mono text-slate-200",
        ),
        rx.el.td(
            d.words,
            class_name=rx.match(d.tone, ("failed", "py-1 pr-2 text-rose-300"), ("odd", "py-1 pr-2 text-amber-200"), "py-1 pr-2 text-slate-300"),
        ),
        rx.el.td(d.secs, class_name="py-1 text-right font-mono text-slate-400"),
        class_name="border-t border-slate-800 align-top",
    )


def room_panel() -> rx.Component:
    """The room during a match: its code, sharing it, the call, and who is who."""
    return rx.el.div(
        code_block(),
        rx.el.div(people_block(), class_name="mt-3"),
        rx.cond(Game.watching, rx.el.p(T["watching_note"], class_name="mt-3 text-sm text-amber-200")),
        data_testid="room-panel",
        class_name=CARD + " min-w-0",
    )


def ai_panel() -> rx.Component:
    head = "pb-1 pr-2 text-[11px] font-normal text-slate-500 whitespace-nowrap"
    return rx.cond(
        Game.ais.length() > 0,
        rx.el.div(
            rx.el.div(rx.foreach(Game.ais, ai_card), class_name="space-y-3"),
            rx.el.div(
                rx.el.div(T["log_title"], class_name="mb-1 text-xs uppercase tracking-wider text-slate-400"),
                rx.el.table(
                    rx.el.thead(
                        rx.el.tr(
                            rx.el.th(T["log_at"], class_name=f"{head} text-right"),
                            rx.el.th(T["log_aim"], class_name=f"{head} text-left"),
                            rx.el.th(T["log_words"], class_name=f"{head} text-left"),
                            rx.el.th(T["log_secs"], class_name="pb-1 text-right text-[11px] font-normal text-slate-500 whitespace-nowrap"),
                        )
                    ),
                    rx.el.tbody(rx.foreach(Game.said, _said_row)),
                    class_name="w-full text-xs",
                ),
                class_name="mt-4",
                data_testid="said",
            ),
            class_name=CARD + " min-w-0",
            data_testid="ai-panel",
        ),
    )


def _place_row(p: Place) -> rx.Component:
    num = "py-1.5 pr-1.5 text-right font-mono"
    return rx.el.tr(
        rx.el.td(p.rank, class_name=num + " text-slate-400"),
        rx.el.td(
            rx.el.span(
                rx.cond(p.kind == "person", _face(p.avatar, p.name, "h-5 w-5 text-[10px]"), _dot(p.id)),
                rx.el.span(p.name, data_testid="place-name"),
                rx.cond(p.id == Game.me, rx.el.span(T["room_you"], class_name="text-xs text-slate-400")),
                class_name="flex items-center gap-1.5",
            ),
            class_name=_color(p.id, TEXT_COLORS, "whitespace-nowrap py-1.5 pr-1.5"),
        ),
        rx.el.td(p.score, class_name=_color(p.id, TEXT_COLORS, num + " font-bold")),
        rx.el.td(p.apples, class_name=num),
        rx.el.td(p.golds, class_name=num),
        rx.el.td(p.crashes, class_name=num),
        rx.el.td(p.asks, class_name=num + " text-slate-400"),
        rx.el.td(p.secs, class_name="py-1.5 text-right font-mono text-slate-400"),
        class_name=rx.cond(p.id == Game.me, "border-t border-slate-800 bg-slate-800/40", "border-t border-slate-800"),
    )


def result_card() -> rx.Component:
    rep = Game.rep
    head = "pb-1 pr-1.5 text-right text-[11px] font-normal text-slate-400 whitespace-nowrap"
    return rx.el.div(
        rx.el.div(
            rx.el.table(
                rx.el.thead(
                    rx.el.tr(
                        rx.el.th(T["col_rank"], class_name=head),
                        rx.el.th(T["col_snake"], class_name="pb-1 pr-1.5 text-left text-[11px] font-normal text-slate-400"),
                        rx.el.th(T["col_points"], class_name=head),
                        rx.el.th(T["col_apples"], class_name=head),
                        rx.el.th(T["col_golds"], class_name=head),
                        rx.el.th(T["col_crashes"], class_name=head),
                        rx.el.th(T["col_asks"], class_name=head),
                        rx.el.th(T["col_secs"], class_name="pb-1 text-right text-[11px] font-normal text-slate-400 whitespace-nowrap"),
                    )
                ),
                rx.el.tbody(rx.foreach(Game.places, _place_row)),
                class_name="w-full text-xs sm:text-sm",
                data_testid="places",
            ),
            class_name="overflow-x-auto",
        ),
        rx.cond(
            rep["asks"] != "0",
            rx.fragment(
                rx.el.div(T["report_title"], class_name="mb-1 mt-4 text-xs uppercase tracking-wider text-slate-400"),
                rx.el.div(
                    *[
                        rx.el.div(rx.el.span(T[f"rep_{k}"], class_name="text-slate-400"), rx.el.span(rep[k], class_name="font-mono text-slate-100"), class_name="flex justify-between gap-3")
                        for k in ("asks", "secs", "failed", "bad")
                    ],
                    class_name="space-y-1 text-sm",
                    data_testid="report",
                ),
            ),
        ),
        rx.el.div(
            rx.cond(
                Game.lead,
                rx.el.button(
                    rx.icon("rotate-ccw", size=16),
                    T["again"],
                    on_click=Game.start_match,
                    data_testid="again",
                    class_name="flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 py-2.5 font-semibold text-slate-950 hover:bg-amber-300",
                ),
                rx.el.div(T["again_wait"], class_name="flex flex-1 items-center justify-center rounded-xl border border-slate-800 py-2.5 text-sm text-slate-400"),
            ),
            rx.el.button(
                T["to_lobby"],
                on_click=Game.leave_room,
                data_testid="to-lobby",
                class_name="flex-1 rounded-xl border border-slate-700 py-2.5 text-slate-200 hover:border-slate-500",
            ),
            class_name="mt-5 flex gap-2",
        ),
        data_testid="result",
        class_name=CARD + " min-w-0",
    )


def match_view() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            scoreboard(),
            arena(),
            rx.cond((Game.phase != "result") & ~Game.watching, pad()),
            rx.cond(
                Game.phase != "result",
                rx.el.div(
                    rx.el.span(
                        rx.el.span(T["keys_hint"], class_name="hidden md:inline"),
                        rx.el.span(T["touch_hint"], class_name="md:hidden"),
                        class_name=rx.cond(Game.watching, "invisible", ""),
                    ),
                    rx.el.button(
                        rx.icon("x", size=14),
                        T["leave"],
                        on_click=Game.leave_room,
                        data_testid="leave",
                        class_name="flex items-center gap-1 rounded-full border border-slate-700 px-3 py-1 text-slate-300 hover:border-slate-500",
                    ),
                    class_name="flex items-center justify-between gap-3 text-xs text-slate-400",
                ),
            ),
            class_name="flex min-w-0 flex-col gap-3",
        ),
        rx.el.div(
            room_panel(),
            rx.cond(Game.phase == "result", result_card(), ai_panel()),
            class_name="flex min-w-0 flex-col gap-4",
        ),
        # Keys go to the server only during a match (the page's script keeps arrows from scrolling).
        rx.cond(Game.phase != "result", rx.window_event_listener(on_key_down=Game.key)),
        class_name="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]",
        data_testid="match",
    )


def index() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            header(),
            notice_bar(),
            invite_bar(),
            rx.match(Game.phase, ("lobby", lobby()), ("room", room_view()), match_view()),
            class_name="mx-auto w-full max-w-6xl px-4 pb-10",
        ),
        incoming_call(),
        # The page's heartbeat (arena.js clicks it): see the state's docstring.
        rx.el.button(id="snake-beat", on_click=Game.beat, tab_index=-1, aria_hidden="true", class_name="hidden"),
        class_name="min-h-screen bg-slate-950 text-slate-100",
    )
