import pytest

from snake_duel.call import RING_SECONDS, STALE_SECONDS, CallStore, Member, view


@pytest.fixture(autouse=True)
def no_calls_left():
    CallStore.calls.clear()
    yield
    CallStore.calls.clear()


def start(now: float = 1000.0) -> dict:
    return CallStore.join("ABCD", "tab-ming", Member(id="ming", name="小明"), now, "livekit", invited=["ming", "mei", "hua"])


def test_a_call_rings_the_others_not_the_caller(monkeypatch):
    monkeypatch.setattr("snake_duel.call.time.time", lambda: 1001.0)
    start()
    assert view("ABCD", "mei") == (1, "小明")
    assert view("ABCD", "ming") == (1, "")
    assert view("ABCD", "came-later") == (1, "")  # only those in the room when it started


def test_answering_or_declining_stops_the_ringing_for_them(monkeypatch):
    monkeypatch.setattr("snake_duel.call.time.time", lambda: 1001.0)
    call = start()
    CallStore.join("ABCD", "tab-mei", Member(id="mei", name="阿美"), 1001.0, "other-app")
    CallStore.decline("ABCD", "hua")
    assert view("ABCD", "mei") == (2, "") and view("ABCD", "hua") == (2, "")
    assert call["app"] == "livekit"  # everyone joins the app it started in


def test_the_ringing_ends(monkeypatch):
    start()
    monkeypatch.setattr("snake_duel.call.time.time", lambda: 1000.0 + RING_SECONDS + 1)
    assert view("ABCD", "mei") == (1, "")


def test_the_call_ends_with_its_last_member():
    start()
    CallStore.join("ABCD", "tab-mei", Member(id="mei", name="阿美"), 1000.0, "")
    CallStore.leave("ABCD", "tab-ming")
    assert "ABCD" in CallStore.calls
    CallStore.leave("ABCD", "tab-mei")
    assert "ABCD" not in CallStore.calls


def test_a_silent_member_is_dropped(monkeypatch):
    start()
    monkeypatch.setattr("snake_duel.call.time.time", lambda: 1000.0 + STALE_SECONDS + 1)
    assert view("ABCD", "mei") == (0, "") and "ABCD" not in CallStore.calls


def test_no_room_no_call():
    assert view("", "mei") == (0, "")


def test_a_call_put_back_does_not_ring_again(monkeypatch):
    monkeypatch.setattr("snake_duel.call.time.time", lambda: 1001.0)
    CallStore.join("ABCD", "tab-ming", Member(id="ming", name="小明"), 1000.0, "livekit", invited=["mei"], call_id="kept")
    assert view("ABCD", "mei") == (1, "") and CallStore.calls["ABCD"]["call_id"] == "kept"
