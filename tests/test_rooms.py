import time

import pytest

from snake_duel import engine, rooms


@pytest.fixture(autouse=True)
def nothing_left_behind():
    for store in (rooms.rooms, rooms.online, rooms.invites):
        store.clear()
    yield
    for store in (rooms.rooms, rooms.online, rooms.invites):
        store.clear()


def a_room(total: int = 5, **changes) -> rooms.Room:
    return rooms.open_room("ming", "小明", "", "zh", "practice", "fast", "60", total, **changes)


def away(room: rooms.Room, uid: str, seconds: float = rooms.STALE + 1) -> None:
    room.players[uid].seen = time.monotonic() - seconds


def test_a_room_has_a_code_and_its_host():
    room = a_room()
    assert len(room.id) == rooms.CODE_LEN and rooms.get(room.id.lower()) is room
    assert rooms.of("ming") is room and room.host == "ming"
    card = rooms.listing()[0]
    assert (card.who, card.people, card.total, card.status) == ("小明", 1, 5, "open")
    assert card.thumb.startswith("data:image/png;base64,")


def test_a_room_of_one_is_not_offered_but_its_link_works():
    room = a_room(listed=False)
    assert rooms.listing() == []
    assert rooms.enter(room, "mei", "阿美")


def test_the_lobby_offers_rooms_in_play_too_the_waiting_ones_first():
    playing, waiting = a_room(), rooms.open_room("mei", "阿美", "", "zh", "practice", "fast", "60", 3)
    rooms.start(playing)
    assert [card.id for card in rooms.listing()] == [waiting.id, playing.id]
    assert rooms.listing()[1].status == "play"


def test_a_link_works_whatever_the_room_is_doing():
    room = a_room(total=3)
    assert rooms.enter(room, "mei", "阿美") and room.players["mei"].seat == ""
    rooms.start(room)
    assert rooms.enter(room, "hua", "小華")  # in the middle of a match: they watch
    assert room.players["hua"].seat == ""
    room.phase = "result"
    assert rooms.enter(room, "qiang", "阿強")  # just after it, too
    assert list(room.players) == ["ming", "mei", "hua", "qiang"]


def test_coming_in_twice_is_one_person():
    room = a_room()
    rooms.enter(room, "mei", "阿美")
    rooms.enter(room, "mei", "阿美二號", "pic")
    assert len(room.players) == 2 and room.players["mei"].name == "阿美二號" and room.players["mei"].avatar == "pic"


def test_a_room_can_hold_only_so_many():
    room = a_room()
    for i in range(rooms.MAX_PEOPLE - 1):
        assert rooms.enter(room, f"p{i}", "人")
    assert not rooms.enter(room, "one-more", "人")


def test_the_host_cannot_leave_fewer_seats_than_there_are_people():
    room = a_room(total=5)
    rooms.enter(room, "mei", "阿美")
    rooms.enter(room, "hua", "小華")
    rooms.set_up(room, total=2, speed="slow", length="120")
    assert room.total == 3 and room.speed == "slow" and room.length == "120"
    rooms.set_up(room, total=4)
    assert room.total == 4


def test_the_people_take_the_first_seats_and_ai_snakes_fill_the_rest():
    room = a_room(total=5)
    rooms.enter(room, "mei", "阿美", "pic")
    rooms.start(room)
    game = room.match
    assert game is not None and len(game.world.snakes) == 5
    assert [seat.kind for seat in game.seats.values()] == ["person", "person", "ai", "ai", "ai"]
    assert [seat.name for seat in game.seats.values()] == ["小明", "阿美", "AI 1", "AI 2", "AI 3"]
    assert [room.players[uid].seat for uid in ("ming", "mei")] == ["s1", "s2"]
    assert room.phase == "countdown" and len(room.chips) == 5 and room.chips[1].avatar == "pic"
    assert room.faces == '{"s2":"pic"}'
    assert (game.world.w, game.world.h) == engine.CROWD


def test_people_beyond_the_seats_watch():
    room = a_room(total=5)
    for i in range(5):
        rooms.enter(room, f"p{i}", f"人{i}")
    rooms.start(room)
    assert room.match.people == 5 and room.players["p3"].seat == "s5" and room.players["p4"].seat == ""


def test_only_the_people_here_get_a_seat():
    room = a_room(total=4)
    rooms.enter(room, "mei", "阿美")
    away(room, "mei")
    rooms.start(room)
    assert room.match.people == 1 and room.players["mei"].seat == ""
    assert [seat.kind for seat in room.match.seats.values()] == ["person", "ai", "ai", "ai"]


def test_no_warm_up_when_no_ai_snake_plays():
    room = rooms.open_room("ming", "小明", "", "zh", "hub", "fast", "60", 2)
    rooms.enter(room, "mei", "阿美")
    rooms.start(room, warm=True)
    assert room.phase == "countdown"
    other = rooms.open_room("hua", "小華", "", "zh", "hub", "fast", "60", 2)
    rooms.start(other, warm=True)
    assert other.phase == "warmup"


def test_turns_wait_for_a_snake():
    room = a_room(total=2)
    rooms.turn(room, "ming", "up")  # nothing to steer yet
    assert room.players["ming"].turns == []
    rooms.enter(room, "hua", "小華")
    room.total = 3
    rooms.start(room)
    rooms.turn(room, "ming", "up")
    rooms.turn(room, "ming", "up")  # the same way twice is one turn
    rooms.turn(room, "ming", "left")
    assert room.players["ming"].turns == ["up", "left"]
    rooms.turn(room, "stranger", "down")


def test_someone_watching_has_no_keys():
    room = a_room(total=2)
    rooms.start(room)
    rooms.enter(room, "hua", "小華")
    rooms.turn(room, "hua", "up")
    assert room.players["hua"].turns == []


def test_someone_away_gets_their_snake_back():
    room = a_room(total=3)
    rooms.enter(room, "mei", "阿美")
    rooms.start(room)
    away(room, "mei")
    rooms._tidy(room, time.monotonic())
    seat = room.match.seats["s2"]
    assert seat.kind == "ai" and seat.left and room.players["mei"].seat == "s2"  # still in the room
    rooms.touch(room, "mei")
    assert seat.kind == "person" and not seat.left


def test_a_host_on_a_phone_keeps_the_room_while_pasting_the_link():
    room = a_room()
    away(room, "ming", 60)
    rooms._tidy(room, time.monotonic())
    assert rooms.get(room.id) is room and room.host == "ming"
    assert rooms.enter(room, "mei", "阿美")  # the friend's link still works
    away(room, "ming", rooms.LINGER + 1)
    rooms._tidy(room, time.monotonic())
    assert room.host == "mei" and "ming" not in room.players


def test_a_room_everyone_left_for_good_closes():
    room = a_room()
    away(room, "ming", rooms.LINGER + 1)
    rooms._tidy(room, time.monotonic())
    assert rooms.get(room.id) is None


def test_a_room_with_nobody_here_is_not_offered():
    room = a_room()
    away(room, "ming")
    assert rooms.listing() == []
    rooms.touch(room, "ming")
    assert len(rooms.listing()) == 1


def test_a_match_with_nobody_here_is_called_off():
    room = a_room(total=3)
    rooms.start(room)
    rooms._call_off(room)
    assert room.phase == "open" and room.match is None and room.notice == "called_off"
    assert room.players["ming"].seat == "" and rooms.get(room.id) is room
    alone = a_room(total=2, listed=False)
    rooms.start(alone)
    rooms._call_off(alone)
    assert rooms.get(alone.id) is None


def test_leaving_hands_the_snake_to_an_ai_for_good():
    room = a_room(total=3)
    rooms.enter(room, "mei", "阿美")
    rooms.start(room)
    rooms.leave(room, "mei")
    seat = room.match.seats["s2"]
    assert seat.kind == "ai" and seat.left and seat.name == "阿美"
    assert "mei" not in room.players and room.id in rooms.rooms
    rooms.enter(room, "mei", "阿美")  # coming back by the link, they watch
    rooms.touch(room, "mei")
    assert seat.kind == "ai" and room.players["mei"].seat == ""


def test_someone_watching_takes_a_snake_from_an_ai():
    room = a_room(total=3)
    rooms.start(room)
    rooms.enter(room, "hua", "小華", "pic")
    assert not rooms.take_over(room, "hua", "s1")  # that one is a person's
    assert rooms.take_over(room, "hua", "s3")
    seat = room.match.seats["s3"]
    assert (seat.kind, seat.name, seat.avatar) == ("person", "小華", "pic") and room.players["hua"].seat == "s3"
    assert not rooms.take_over(room, "hua", "s2")  # one snake each


def test_a_snake_taken_over_is_not_handed_back():
    room = a_room(total=3)
    rooms.enter(room, "mei", "阿美")
    rooms.start(room)
    away(room, "mei")
    rooms._tidy(room, time.monotonic())
    rooms.enter(room, "hua", "小華")
    assert rooms.take_over(room, "hua", "s2")
    rooms.touch(room, "mei")
    assert room.match.seats["s2"].name == "小華" and room.players["mei"].seat == ""


def test_the_host_passes_on_and_the_last_one_out_closes_the_room():
    room = a_room(total=3)
    rooms.enter(room, "mei", "阿美")
    rooms.leave(room, "ming")
    assert room.host == "mei" and room.id in rooms.rooms
    rooms.leave(room, "mei")
    assert rooms.rooms == {}


def test_a_host_away_for_a_while_lets_others_start():
    room = a_room(total=3)
    rooms.enter(room, "mei", "阿美")
    assert rooms.can_lead(room, "ming") and not rooms.can_lead(room, "mei")
    away(room, "ming", rooms.HOST_WAIT - 5)
    assert not rooms.can_lead(room, "mei")
    away(room, "ming", rooms.HOST_WAIT + 1)
    assert rooms.can_lead(room, "mei") and not rooms.can_lead(room, "stranger")


def test_signing_in_keeps_the_seat():
    room = a_room(total=3)
    rooms.enter(room, "guest-1", "訪客 12")
    room.host = "guest-1"
    rooms.start(room)
    rooms.rename("guest-1", "mei@x", "阿美", "pic")
    player = room.players["mei@x"]
    assert "guest-1" not in room.players and list(room.players) == ["ming", "mei@x"]
    assert room.host == "mei@x" and player.seat == "s2"
    assert room.match.seats["s2"].name == "阿美" and room.match.seats["s2"].avatar == "pic"


def test_an_account_already_in_a_room_wins_over_its_new_guest():
    room = a_room(total=3)
    other = rooms.open_room("guest-2", "訪客", "", "zh", "practice", "fast", "60", 3)
    rooms.rename("guest-2", "ming", "小明", "")
    assert rooms.of("ming") is room and rooms.get(other.id) is None


def test_who_else_is_online_and_inviting_them():
    room = a_room()
    rooms.seen_online("ming", "小明", "", True)
    rooms.seen_online("mei@x", "阿美", "pic", False)
    rooms.seen_online("hua", "小華", "", True)
    around = rooms.others_online(room)
    assert [who.name for who in around] == ["阿美", "小華"]  # free ones first, and not those in it
    assert "mei@x" not in around[0].key
    rooms.invite(room, "ming", around[0].key)
    invite = rooms.invitation("mei@x")
    assert invite is not None and (invite.code, invite.by) == (room.id, "小明") and rooms.invited(room, "mei@x")
    rooms.enter(room, "mei@x", "阿美")
    assert rooms.invitation("mei@x") is None


def test_an_invitation_ends():
    room = a_room()
    rooms.seen_online("mei", "阿美", "", False)
    rooms.invite(room, "ming", rooms.others_online(room)[0].key)
    rooms.invites["mei"].at -= rooms.INVITE_SECONDS + 1
    assert rooms.invitation("mei") is None
    rooms.invite(room, "ming", rooms._key("mei"))
    rooms.decline("mei")
    assert rooms.invitation("mei") is None
    rooms.invite(room, "ming", rooms._key("mei"))
    rooms.close(room)
    assert rooms.invitation("mei") is None


def test_opening_a_link_in_the_middle_of_a_match_asks_first():
    room = a_room()
    rooms.ask_first(room, "mei")
    invite = rooms.invitation("mei")
    assert invite is not None and invite.by == "小明" and rooms.of("mei") is None


def test_people_online_go_quiet():
    room = a_room()
    rooms.seen_online("mei", "阿美", "", False)
    rooms.online["mei"].seen -= rooms.ONLINE_SECONDS + 1
    assert rooms.others_online(room) == []


def places(*rows: tuple[str, int, str]) -> list[rooms.Place]:
    return [rooms.Place(rank, sid, name, "person", 0, 0, 0, 0, "", "") for sid, rank, name in rows]


def test_the_final_word_of_two():
    two = places(("s1", 1, "小明"), ("s2", 2, "阿美"))
    assert rooms.verdict(two, "s1") == ("you_win", {}, "you")
    assert rooms.verdict(two, "s2") == ("won_by", {"name": "小明"}, "ai")  # not "the AI won"
    assert rooms.verdict(places(("s1", 1, "小明"), ("s2", 1, "AI")), "s2") == ("draw", {}, "draw")


def test_the_final_word_of_many():
    five = places(("s3", 1, "AI 1"), ("s1", 1, "小明"), ("s2", 3, "阿美"), ("s4", 4, "AI 2"))
    assert rooms.verdict(five, "s1") == ("crowd_tie", {}, "draw")
    assert rooms.verdict(five, "s2") == ("crowd_place", {"n": 3}, "ai")


def test_the_final_word_for_someone_watching():
    assert rooms.verdict(places(("s1", 1, "小明"), ("s2", 2, "阿美"), ("s3", 3, "AI")), "") == ("won_by", {"name": "小明"}, "draw")
    assert rooms.verdict(places(("s1", 1, "小明"), ("s2", 1, "阿美")), "") == ("draw", {}, "draw")
    assert rooms.verdict([], "s1") == ("", {}, "")
