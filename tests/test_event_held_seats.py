"""
Tests for HeldSeatsManager.

These use a fake `on_expire` callback instead of Owner 2's real heap,
so this component can be built, tested, and demoed independently of
whether Component 2 (Min-Heap) is finished yet -- that's the "stub
Owner 2's interface" step mentioned in the work-split doc's Phase 2.
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from event_held_seats import HeldSeatsManager  # noqa: E402


class FakeHeap:
    """Stands in for Owner 2's per-event Min-Heap during testing."""
    def __init__(self):
        self.pushed_back = []  # list of (event_id, seat) tuples

    def push_seat_back(self, event_id, seat):
        self.pushed_back.append((event_id, seat))


def test_hold_and_confirm():
    heap = FakeHeap()
    mgr = HeldSeatsManager(on_expire=heap.push_seat_back, ttl_seconds=60)

    token = mgr.hold_seat(seat="A1", event_id="concert-1")
    assert mgr.active_hold_count() == 1

    hold = mgr.confirm_hold(token)
    assert hold is not None
    assert hold.seat == "A1"
    assert hold.event_id == "concert-1"
    assert mgr.active_hold_count() == 0
    # Confirmed normally -> heap should NOT have gotten the seat back
    assert heap.pushed_back == []
    print("test_hold_and_confirm passed")


def test_confirm_unknown_token_returns_none():
    mgr = HeldSeatsManager()
    assert mgr.confirm_hold("does-not-exist") is None
    print("test_confirm_unknown_token_returns_none passed")


def test_cancel_returns_seat_to_heap_immediately():
    heap = FakeHeap()
    mgr = HeldSeatsManager(on_expire=heap.push_seat_back, ttl_seconds=60)

    token = mgr.hold_seat(seat="B2", event_id="concert-1")
    mgr.cancel_hold(token)

    assert mgr.active_hold_count() == 0
    assert heap.pushed_back == [("concert-1", "B2")]
    print("test_cancel_returns_seat_to_heap_immediately passed")


def test_expired_hold_cannot_be_confirmed():
    mgr = HeldSeatsManager(ttl_seconds=0)  # expires immediately
    token = mgr.hold_seat(seat="C3", event_id="concert-1")
    time.sleep(0.01)
    assert mgr.get_hold(token) is None       # lazy check on read
    assert mgr.confirm_hold(token) is None   # lazy check on confirm
    print("test_expired_hold_cannot_be_confirmed passed")


def test_background_sweep_reclaims_expired_holds():
    heap = FakeHeap()
    mgr = HeldSeatsManager(on_expire=heap.push_seat_back, ttl_seconds=0.2)

    mgr.hold_seat(seat="D4", event_id="concert-2")
    assert mgr.active_hold_count() == 1

    mgr.start_background_sweep(interval_seconds=0.1)
    time.sleep(0.5)
    mgr.stop_background_sweep()

    assert mgr.active_hold_count() == 0
    assert heap.pushed_back == [("concert-2", "D4")]
    print("test_background_sweep_reclaims_expired_holds passed")


def test_concurrent_holds_do_not_corrupt_map():
    """
    Simulates many threads holding seats at once (a smaller version of
    the concurrency demo mentioned in the report: prove the shared
    structure survives simultaneous access).
    """
    mgr = HeldSeatsManager(ttl_seconds=60)
    tokens = []
    tokens_lock = threading.Lock()

    def worker(i):
        t = mgr.hold_seat(seat=f"seat-{i}", event_id="concert-3")
        with tokens_lock:
            tokens.append(t)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert mgr.active_hold_count() == 50
    assert len(set(tokens)) == 50  # every token unique, none dropped/overwritten
    print("test_concurrent_holds_do_not_corrupt_map passed")


if __name__ == "__main__":
    test_hold_and_confirm()
    test_confirm_unknown_token_returns_none()
    test_cancel_returns_seat_to_heap_immediately()
    test_expired_hold_cannot_be_confirmed()
    test_background_sweep_reclaims_expired_holds()
    test_concurrent_holds_do_not_corrupt_map()
    print("\nAll tests passed.")
