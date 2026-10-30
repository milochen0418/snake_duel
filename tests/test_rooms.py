import time

import pytest

from snake_duel import engine, rooms


@pytest.fixture(autouse=True)
def empty_rooms():
    rooms.rooms.clear()
    yield
    rooms.rooms.clear()


def a_room(total: int = 5, **changes) -> rooms.Room:
    return rooms.open_room("t1", "小明", "zh", "practice", "fast", "60", total, **changes)


def test_a_room_has_a_code_and_its_host():
    room = a_room()
    assert len(room.id) == rooms.CODE_LEN and rooms.get(room.id.lower()) is room
    assert rooms.of("t1") is room and room.host == "t1"
    assert [p.name for p in room.people] == ["小明"]
    assert rooms.listing()[0].who == "小明"


def test_a_room_nobody_is_invited_to_is_not_listed():
    a_room(listed=False)
    assert rooms.listing() == []


def test_people_join_until_the_seats_are_full():
    room = a_room(total=3)
    assert rooms.join(room, "t2", "阿美") and rooms.join(room, "t3", "小華")
    assert room.full and not rooms.join(room, "t4", "太晚了")
    assert rooms.listing() == []  # a full room is not offered any more
    assert [p.name for p in room.people] == ["小明", "阿美", "小華"]


def test_the_host_cannot_leave_fewer_seats_than_there_are_people():
    room = a_room(total=5)
    rooms.join(room, "t2", "阿美")
    rooms.set_up(room, total=2, speed="slow", length="120", foe="hub")
    assert room.total == 2 and room.speed == "slow" and room.length == "120" and room.foe == "hub"
    rooms.join(room, "t3", "小華")  # the room is full at 2
    assert len(room.players) == 2
    rooms.set_up(room, total=1)
    assert room.total == 2


def test_the_people_take_the_first_seats_and_ai_snakes_fill_the_rest():
    room = a_room(total=5)
    rooms.join(room, "t2", "阿美")
    rooms.start(room)
    game = room.match
    assert game is not None and len(game.world.snakes) == 5
    assert [seat.kind for seat in game.seats.values()] == ["person", "person", "ai", "ai", "ai"]
    assert [seat.name for seat in game.seats.values()] == ["小明", "阿美", "AI 1", "AI 2", "AI 3"]
    assert [room.players[t].seat for t in ("t1", "t2")] == ["s1", "s2"]
    assert room.phase == "countdown" and len(room.chips) == 5
    assert (game.world.w, game.world.h) == engine.CROWD


def test_two_snakes_is_one_person_and_one_ai():
    room = a_room(total=2)
    rooms.start(room)
    game = room.match
    assert [seat.kind for seat in game.seats.values()] == ["person", "ai"]
    assert game.seats["s2"].name == "AI" and (game.world.w, game.world.h) == engine.DUEL


def test_someone_who_joins_without_a_name_is_numbered():
    room = a_room(total=3)
    rooms.join(room, "t2", "   ")
    rooms.start(room)
    assert [seat.name for seat in room.match.seats.values()] == ["小明", "P2", "AI"]


def test_turns_wait_for_the_snake():
    room = a_room(total=2)
    rooms.turn(room, "t1", "up")  # nothing to steer yet
    assert room.players["t1"].turns == []
    rooms.start(room)
    rooms.turn(room, "t1", "up")
    rooms.turn(room, "t1", "up")  # the same way twice is one turn
    rooms.turn(room, "t1", "left")
    assert room.players["t1"].turns == ["up", "left"]
    rooms.turn(room, "t9", "down")  # not in this room


def test_leaving_mid_match_hands_the_snake_to_an_ai():
    room = a_room(total=3)
    rooms.join(room, "t2", "阿美")
    rooms.start(room)
    rooms.leave(room, "t2")
    seat = room.match.seats["s2"]
    assert seat.kind == "ai" and seat.left and seat.name == "阿美"
    assert "t2" not in room.players and room.id in rooms.rooms


def test_the_host_passes_on_and_the_last_one_out_closes_the_room():
    room = a_room(total=3)
    rooms.join(room, "t2", "阿美")
    rooms.leave(room, "t1")
    assert room.host == "t2" and room.id in rooms.rooms
    rooms.leave(room, "t2")
    assert rooms.rooms == {}


def test_a_room_nobody_looks_at_is_not_offered():
    room = a_room()
    room.players["t1"].seen = time.monotonic() - rooms.STALE - 1
    assert rooms.listing() == []
    rooms.touch(room, "t1")
    assert len(rooms.listing()) == 1


def test_people_who_went_away_are_dropped_and_their_snakes_handed_over():
    room = a_room(total=4)
    rooms.join(room, "t2", "阿美")
    rooms.start(room)
    room.players["t2"].seen = time.monotonic() - rooms.STALE - 1
    rooms._drop_absent(room, time.monotonic())
    assert "t2" not in room.players and room.match.seats["s2"].kind == "ai"
    assert room.host == "t1"


def test_a_match_only_counts_the_people_who_are_there():
    room = a_room(total=4)
    rooms.join(room, "t2", "阿美")
    room.players["t2"].seen = time.monotonic() - rooms.STALE - 1
    rooms.start(room)
    assert room.match.people == 1 and room.players["t2"].seat == ""
    assert [seat.kind for seat in room.match.seats.values()] == ["person", "ai", "ai", "ai"]
