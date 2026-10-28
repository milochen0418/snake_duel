"""The page: the lobby, the arena with both scores and what the AI is doing, and the result."""

from __future__ import annotations

import reflex as rx

from snake_duel.history import ModelRow
from snake_duel.match import Decision
from snake_duel.state import Game

T = Game.t

CARD = "rounded-2xl border border-slate-800 bg-slate-900/70 p-4 sm:p-5"
YOU = "text-amber-300"
AI = "text-cyan-300"


def _chip(label: rx.Var | str, active: rx.Var | bool, on_click: rx.EventHandler, test_id: str) -> rx.Component:
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


def header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.icon("worm", size=22, class_name="text-amber-300"),
            rx.el.span(T["app"], class_name="text-lg font-semibold tracking-wide"),
            class_name="flex items-center gap-2",
        ),
        rx.el.button(
            rx.icon("languages", size=16),
            T["lang_other"],
            on_click=Game.switch_lang,
            data_testid="lang",
            class_name="flex items-center gap-1.5 rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:border-slate-500",
        ),
        class_name="flex items-center justify-between py-4",
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
        rx.el.div(
            rx.el.div(T["speed"], class_name="mb-2 text-sm text-slate-400"),
            rx.el.div(
                _chip(T["speed_slow"], Game.speed == "slow", Game.set_speed("slow"), "speed-slow"),
                _chip(T["speed_normal"], Game.speed == "normal", Game.set_speed("normal"), "speed-normal"),
                _chip(T["speed_fast"], Game.speed == "fast", Game.set_speed("fast"), "speed-fast"),
                class_name="flex flex-wrap gap-2",
            ),
        ),
        rx.el.div(
            rx.el.div(T["length"], class_name="mb-2 text-sm text-slate-400"),
            rx.el.div(
                _chip(T["length_60"], Game.length == "60", Game.set_length("60"), "length-60"),
                _chip(T["length_120"], Game.length == "120", Game.set_length("120"), "length-120"),
                class_name="flex flex-wrap gap-2",
            ),
            class_name="mt-4",
        ),
        rx.el.button(
            rx.icon("play", size=18),
            T["start"],
            on_click=Game.start,
            disabled=~Game.can_start,
            data_testid="start",
            class_name="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-amber-400 py-3 text-base font-semibold text-slate-950 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40",
        ),
        class_name=CARD,
    )


def rules_card() -> rx.Component:
    return rx.el.div(
        rx.el.div(T["rules_title"], class_name="mb-2 font-semibold"),
        rx.el.ol(
            *[rx.el.li(T[f"rule_{i}"]) for i in range(1, 6)],
            class_name="list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-slate-300",
        ),
        class_name=CARD,
    )


def _board_row(row: ModelRow) -> rx.Component:
    return rx.el.tr(
        rx.el.td(row.model, class_name="max-w-[14rem] break-all py-2 pr-3 font-mono text-cyan-200"),
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
        class_name="border-t border-slate-800",
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
            rx.el.div(rules_card(), board_card(), class_name="flex min-w-0 flex-col gap-4"),
            class_name="grid gap-4 lg:grid-cols-2",
        ),
        data_testid="lobby",
    )


# ------------------------------------------------------------ the match


def _score(who: str, label: rx.Var, score: rx.Var, color: str, test_id: str, sub: rx.Component) -> rx.Component:
    return rx.el.div(
        rx.el.div(label, class_name=f"text-xs uppercase tracking-wider {color} opacity-80"),
        rx.el.div(score, data_testid=test_id, class_name=f"font-mono text-3xl font-bold {color} tabular-nums"),
        sub,
        class_name="min-w-0 " + ("text-left" if who == "you" else "text-right"),
    )


def scoreboard() -> rx.Component:
    return rx.el.div(
        _score(
            "you",
            T["you"],
            Game.my_score,
            YOU,
            "my-score",
            rx.cond(Game.my_out != "", rx.el.div(T["you_out"], " ", Game.my_out, " ", T["sec"], data_testid="my-out", class_name="text-xs text-rose-300"), rx.el.div()),
        ),
        rx.el.div(
            rx.el.div(Game.left, data_testid="left", class_name="font-mono text-2xl font-semibold tabular-nums text-slate-100"),
            rx.el.div(T["sec"], class_name="text-xs text-slate-400"),
            class_name="text-center",
        ),
        _score("ai", T["ai"], Game.ai_score, AI, "ai-score", rx.el.div(Game.foe_name, class_name="truncate font-mono text-xs text-slate-400")),
        class_name="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-4 py-2",
    )


def _overlay() -> rx.Component:
    """The countdown, the warm-up and the final word, over the board."""
    box = "pointer-events-none absolute inset-0 flex items-center justify-center rounded-xl"
    return rx.match(
        Game.phase,
        ("warmup", rx.el.div(rx.el.div(T["warmup"], class_name="rounded-xl bg-slate-950/80 px-4 py-3 text-cyan-200"), data_testid="warmup", class_name=box)),
        ("countdown", rx.el.div(rx.el.div(Game.count, class_name="text-7xl font-black text-amber-200 drop-shadow-lg"), data_testid="countdown", class_name=box + " bg-slate-950/30")),
        (
            "result",
            rx.el.div(
                rx.el.div(
                    rx.match(Game.winner, ("you", T["you_win"]), ("ai", T["ai_win"]), T["draw"]),
                    class_name=rx.match(
                        Game.winner,
                        ("you", "text-5xl font-black text-amber-300 drop-shadow-lg"),
                        ("ai", "text-5xl font-black text-cyan-300 drop-shadow-lg"),
                        "text-5xl font-black text-slate-200 drop-shadow-lg",
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
            data_you=T["you"],
            data_ai=T["ai"],
            data_testid="arena",
            class_name="block aspect-[3/2] w-full touch-none select-none rounded-xl",
        ),
        _overlay(),
        class_name="relative w-full",
    )


def _pad_button(icon: str, key: str, extra: str = "") -> rx.Component:
    return rx.el.button(
        rx.icon(icon, size=22),
        data_key=key,
        aria_label=key,
        class_name=f"flex h-12 w-12 items-center justify-center rounded-xl border border-slate-700 bg-slate-800/80 text-slate-200 active:bg-amber-400 active:text-slate-950 {extra}",
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


def _said_row(d: Decision) -> rx.Component:
    return rx.el.tr(
        rx.el.td(d.at, class_name="py-1 pr-2 text-right font-mono text-slate-400"),
        rx.el.td(d.aim, class_name="whitespace-nowrap py-1 pr-2 font-mono text-cyan-200"),
        rx.el.td(
            d.words,
            class_name=rx.match(d.tone, ("failed", "py-1 pr-2 text-rose-300"), ("odd", "py-1 pr-2 text-amber-200"), "py-1 pr-2 text-slate-300"),
        ),
        rx.el.td(d.secs, class_name="py-1 text-right font-mono text-slate-400"),
        class_name="border-t border-slate-800 align-top",
    )


def ai_panel() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.cond(
                Game.ai_state == "thinking",
                rx.el.span(class_name="h-2.5 w-2.5 animate-pulse rounded-full bg-cyan-300"),
                rx.el.span(class_name="h-2.5 w-2.5 rounded-full bg-slate-600"),
            ),
            rx.el.span(Game.ai_status, data_testid="ai-status", class_name="text-sm text-slate-200"),
            class_name="flex items-center gap-2",
        ),
        rx.cond(Game.ai_slow, rx.el.p(T["slow_note"], data_testid="slow-note", class_name="mt-2 text-sm leading-relaxed text-amber-200")),
        rx.cond(
            Game.ai_aim != "",
            rx.el.div(
                rx.el.span(T["ai_goes"], class_name="text-slate-400"),
                rx.el.span(Game.ai_aim, data_testid="ai-aim", class_name="font-mono text-cyan-200"),
                class_name="mt-2 flex items-center gap-2 text-sm",
            ),
        ),
        rx.cond(
            Game.ai_words != "",
            rx.el.div(
                rx.el.div(T["ai_says"], class_name="text-xs text-slate-400"),
                rx.el.div("「", Game.ai_words, "」", data_testid="ai-words", class_name="mt-1 rounded-xl rounded-tl-sm bg-cyan-400/10 px-3 py-2 text-cyan-100"),
                class_name="mt-3",
            ),
        ),
        rx.cond(Game.ai_note != "", rx.el.p(T["ai_failed"], " ", Game.ai_note, class_name="mt-2 break-words text-sm text-rose-300")),
        rx.el.div(
            rx.el.div(T["log_title"], class_name="mb-1 text-xs uppercase tracking-wider text-slate-400"),
            rx.el.table(
                rx.el.thead(
                    rx.el.tr(
                        rx.el.th(T["log_at"], class_name="pb-1 pr-2 text-right text-[11px] font-normal text-slate-500 whitespace-nowrap"),
                        rx.el.th(T["log_aim"], class_name="pb-1 pr-2 text-left text-[11px] font-normal text-slate-500 whitespace-nowrap"),
                        rx.el.th(T["log_words"], class_name="pb-1 pr-2 text-left text-[11px] font-normal text-slate-500 whitespace-nowrap"),
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
    )


def _stat_row(label: rx.Var, mine: rx.Var | int, theirs: rx.Var | int) -> rx.Component:
    return rx.el.tr(
        rx.el.td(label, class_name="py-1.5 pr-3 text-slate-400"),
        rx.el.td(mine, class_name=f"py-1.5 pr-3 text-right font-mono {YOU}"),
        rx.el.td(theirs, class_name=f"py-1.5 text-right font-mono {AI}"),
        class_name="border-t border-slate-800",
    )


def result_card() -> rx.Component:
    rep = Game.rep
    return rx.el.div(
        rx.el.table(
            rx.el.thead(
                rx.el.tr(
                    rx.el.th("", class_name="pb-1"),
                    rx.el.th(T["you"], class_name=f"pb-1 pr-3 text-right text-xs font-normal {YOU}"),
                    rx.el.th(T["ai"], class_name=f"pb-1 text-right text-xs font-normal {AI}"),
                )
            ),
            rx.el.tbody(
                _stat_row(T["stat_points"], Game.my_score, Game.ai_score),
                _stat_row(T["stat_apples"], rep["you_apples"], rep["ai_apples"]),
                _stat_row(T["stat_golds"], rep["you_golds"], rep["ai_golds"]),
                _stat_row(T["stat_crashes"], rep["you_crashes"], rep["ai_crashes"]),
            ),
            class_name="w-full text-sm",
        ),
        rx.el.div(T["report_title"], class_name="mb-1 mt-4 text-xs uppercase tracking-wider text-slate-400"),
        rx.el.div(
            *[
                rx.el.div(rx.el.span(T[f"rep_{k}"], class_name="text-slate-400"), rx.el.span(rep[k], class_name="font-mono text-slate-100"), class_name="flex justify-between gap-3")
                for k in ("asks", "secs", "failed", "bad")
            ],
            class_name="space-y-1 text-sm",
        ),
        rx.el.div(
            rx.el.button(
                rx.icon("rotate-ccw", size=16),
                T["again"],
                on_click=Game.start,
                disabled=~Game.can_start,
                data_testid="again",
                class_name="flex flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 py-2.5 font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-40",
            ),
            rx.el.button(
                T["to_lobby"],
                on_click=Game.leave,
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
            rx.cond(Game.phase != "result", pad()),
            rx.cond(
                Game.phase != "result",
                rx.el.div(
                    rx.el.span(rx.el.span(T["keys_hint"], class_name="hidden md:inline"), rx.el.span(T["touch_hint"], class_name="md:hidden")),
                    rx.el.button(
                        rx.icon("x", size=14),
                        T["leave"],
                        on_click=Game.leave,
                        data_testid="leave",
                        class_name="flex items-center gap-1 rounded-full border border-slate-700 px-3 py-1 text-slate-300 hover:border-slate-500",
                    ),
                    class_name="flex items-center justify-between gap-3 text-xs text-slate-400",
                ),
            ),
            class_name="flex min-w-0 flex-col gap-3",
        ),
        rx.cond(Game.phase == "result", result_card(), ai_panel()),
        # Keys go to the server only during a match (the page's script keeps arrows from scrolling).
        rx.cond(Game.phase != "result", rx.window_event_listener(on_key_down=Game.key)),
        class_name="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]",
        data_testid="match",
    )


def index() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            header(),
            rx.cond(Game.phase == "lobby", lobby(), match_view()),
            class_name="mx-auto w-full max-w-6xl px-4 pb-10",
        ),
        class_name="min-h-screen bg-slate-950 text-slate-100",
    )
