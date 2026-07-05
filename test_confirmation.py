"""
Unit tests for ConfirmationManager (Component 4: Confirmation & HashSet)
Owner: Wilson Yugi

Run with:  python3 -m pytest test_confirmation.py -v
"""

import time
import threading
import pytest

from confirmation import ConfirmationManager, FakeHeldSeatsStore, FakeHeap


# ---------------------------------------------------------------------------
# Fixtures -- a fresh store/heap/manager for every test, so tests don't
# leak state into each other.
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    return FakeHeldSeatsStore()


@pytest.fixture
def heap():
    return FakeHeap()


@pytest.fixture
def manager(store, heap):
    return ConfirmationManager(store, heap)


# ---------------------------------------------------------------------------
# Basic confirm/cancel behaviour
# ---------------------------------------------------------------------------

def test_confirm_valid_hold_succeeds(manager, store):
    store.add(token="tok1", seat_id="A1", event_id="EVT1", hold_seconds=60)

    result = manager.confirm_booking("tok1")

    assert result.success is True
    assert manager.is_confirmed("EVT1", "A1") is True


def test_confirm_removes_the_hold(manager, store):
    store.add(token="tok1", seat_id="A1", event_id="EVT1", hold_seconds=60)

    manager.confirm_booking("tok1")

    assert store.get("tok1") is None  # hold should be gone after confirming


def test_confirm_same_token_twice_fails(manager, store):
    store.add(token="tok1", seat_id="A1", event_id="EVT1", hold_seconds=60)

    first = manager.confirm_booking("tok1")
    second = manager.confirm_booking("tok1")

    assert first.success is True
    assert second.success is False


def test_confirm_unknown_token_fails(manager):
    result = manager.confirm_booking("no-such-token")

    assert result.success is False
    assert "Invalid" in result.message


def test_confirm_expired_hold_fails_and_returns_seat_to_heap(manager, store, heap):
    store.add(token="tok1", seat_id="A1", event_id="EVT1", hold_seconds=-5)  # already expired

    result = manager.confirm_booking("tok1")

    assert result.success is False
    assert "expired" in result.message.lower()
    assert ("EVT1", "A1") in heap.returned_seats
    assert manager.is_confirmed("EVT1", "A1") is False


def test_cancel_valid_hold_returns_seat_to_heap(manager, store, heap):
    store.add(token="tok1", seat_id="B2", event_id="EVT1", hold_seconds=60)

    result = manager.cancel_booking("tok1")

    assert result.success is True
    assert ("EVT1", "B2") in heap.returned_seats
    assert store.get("tok1") is None


def test_cancel_unknown_token_fails(manager):
    result = manager.cancel_booking("ghost-token")

    assert result.success is False


# ---------------------------------------------------------------------------
# HashSet conflict-check behaviour
# ---------------------------------------------------------------------------

def test_is_confirmed_false_before_confirmation(manager):
    assert manager.is_confirmed("EVT1", "A1") is False


def test_different_seats_dont_collide_in_the_set(manager, store):
    store.add(token="tok1", seat_id="A1", event_id="EVT1", hold_seconds=60)
    store.add(token="tok2", seat_id="A2", event_id="EVT1", hold_seconds=60)

    manager.confirm_booking("tok1")
    manager.confirm_booking("tok2")

    assert manager.is_confirmed("EVT1", "A1") is True
    assert manager.is_confirmed("EVT1", "A2") is True
    assert len(manager.confirmed) == 2


def test_same_seat_id_different_events_are_distinct(manager, store):
    # (event_id, seat_id) tuple means seat "A1" in two different events
    # must be tracked separately -- this is why the HashSet key is a pair.
    store.add(token="tok1", seat_id="A1", event_id="EVT1", hold_seconds=60)
    store.add(token="tok2", seat_id="A1", event_id="EVT2", hold_seconds=60)

    manager.confirm_booking("tok1")
    manager.confirm_booking("tok2")

    assert manager.is_confirmed("EVT1", "A1") is True
    assert manager.is_confirmed("EVT2", "A1") is True


# ---------------------------------------------------------------------------
# Concurrency: the actual race condition your mutex is supposed to prevent
# ---------------------------------------------------------------------------

def test_concurrent_confirm_only_one_thread_wins():
    """
    Simulate two threads racing to confirm the SAME token at the same time.
    Only one should succeed -- this is the scenario to show live in the demo.
    """
    store = FakeHeldSeatsStore()
    heap = FakeHeap()
    manager = ConfirmationManager(store, heap)
    store.add(token="race-token", seat_id="A1", event_id="EVT1", hold_seconds=60)

    results = []

    def try_confirm():
        results.append(manager.confirm_booking("race-token"))

    threads = [threading.Thread(target=try_confirm) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r.success]
    assert len(successes) == 1  # exactly one thread should have won the race
    assert manager.is_confirmed("EVT1", "A1") is True


def test_concurrent_confirm_and_cancel_are_mutually_exclusive():
    """
    One thread tries to confirm while another tries to cancel the same
    token. Exactly one of the two operations should succeed, never both,
    and never a corrupted in-between state.
    """
    store = FakeHeldSeatsStore()
    heap = FakeHeap()
    manager = ConfirmationManager(store, heap)
    store.add(token="tok1", seat_id="A1", event_id="EVT1", hold_seconds=60)

    outcomes = {}

    def do_confirm():
        outcomes["confirm"] = manager.confirm_booking("tok1")

    def do_cancel():
        outcomes["cancel"] = manager.cancel_booking("tok1")

    t1 = threading.Thread(target=do_confirm)
    t2 = threading.Thread(target=do_cancel)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [o for o in outcomes.values() if o.success]
    assert len(successes) == 1  # only one of confirm/cancel should have won


if __name__ == "__main__":
    # Allows `python3 test_confirmation.py` as a fallback if pytest isn't installed
    import sys
    sys.exit(pytest.main([__file__, "-v"]))