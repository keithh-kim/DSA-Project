"""
Component 4: Confirmation & HashSet
Owner: Wilson Yugi

This module owns the FINAL step of the booking flow:
    held seat (token) --confirm--> confirmed HashSet
    held seat (token) --cancel/expire--> pushed back to the heap

It depends on two things from teammates, which we stub out here so this
file can be built and tested completely on its own:

  1. A "held seats store" (Evans's component) that answers:
       - get(token)          -> (seat, event_id, expiry_time) or None
       - remove(token)       -> deletes the hold
  2. A "heap" (Trent's component) that answers:
       - push_seat_back(event_id, seat) -> puts seat back as available

Once Evans and Trent's real classes exist, we just swap the stubs below
for imports of their actual classes -- nothing else in this file changes,
AS LONG AS they expose the same method names. Agree on that with them.
"""

import time
import threading
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# STUBS -- delete these two classes once the real components exist,
# and import the real ones instead. Everything below the stubs only
# talks to these method names, so swapping them out is a one-line change.
# ---------------------------------------------------------------------------

class FakeHeldSeatsStore:
    """Pretend version of Evans's held-seats HashMap, for testing alone."""

    def __init__(self):
        self._holds = {}  # token -> (seat_id, event_id, expiry_time)

    def add(self, token, seat_id, event_id, hold_seconds=60):
        self._holds[token] = (seat_id, event_id, time.time() + hold_seconds)

    def get(self, token):
        return self._holds.get(token)  # None if not found

    def remove(self, token):
        self._holds.pop(token, None)


class FakeHeap:
    """Pretend version of Trent's Min-Heap, for testing alone."""

    def __init__(self):
        self.returned_seats = []  # just logs what got pushed back

    def push_seat_back(self, event_id, seat_id):
        self.returned_seats.append((event_id, seat_id))
        print(f"[heap] seat {seat_id} for event {event_id} returned to availability")


# ---------------------------------------------------------------------------
# YOUR ACTUAL COMPONENT
# ---------------------------------------------------------------------------

@dataclass
class ConfirmResult:
    success: bool
    message: str


class ConfirmationManager:
    """
    Owns the HashSet of confirmed bookings and the confirm/cancel logic.
    This is the class you present and defend in the demo/Q&A.
    """

    def __init__(self, held_seats_store, heap):
        self.held_seats_store = held_seats_store
        self.heap = heap
        self.confirmed = set()          # HashSet: (event_id, seat_id) tuples
        self.lock = threading.Lock()    # protects confirmed + held_seats together

    def confirm_booking(self, token: str) -> ConfirmResult:
        """
        Move a held seat into the confirmed set.
        Steps: lock -> look up hold -> check expiry -> check for conflict
               -> add to confirmed HashSet -> remove hold -> unlock
        """
        with self.lock:
            hold = self.held_seats_store.get(token)
            if hold is None:
                return ConfirmResult(False, "Invalid or already-used token.")

            seat_id, event_id, expiry_time = hold

            if time.time() > expiry_time:
                # Hold expired -- release it and fail the confirmation
                self.held_seats_store.remove(token)
                self.heap.push_seat_back(event_id, seat_id)
                return ConfirmResult(False, "Hold expired before payment completed.")

            key = (event_id, seat_id)
            if key in self.confirmed:
                # Should never happen if locking is correct -- this is
                # exactly the O(1) conflict check the HashSet gives us.
                return ConfirmResult(False, "Seat already confirmed (conflict).")

            self.confirmed.add(key)
            self.held_seats_store.remove(token)
            return ConfirmResult(True, f"Seat {seat_id} confirmed for event {event_id}.")

    def cancel_booking(self, token: str) -> ConfirmResult:
        """
        User-initiated cancel of a held (not yet confirmed) seat.
        Steps: lock -> look up hold -> remove hold -> push seat back to heap -> unlock
        """
        with self.lock:
            hold = self.held_seats_store.get(token)
            if hold is None:
                return ConfirmResult(False, "Invalid or already-used token.")

            seat_id, event_id, _ = hold
            self.held_seats_store.remove(token)
            self.heap.push_seat_back(event_id, seat_id)
            return ConfirmResult(True, f"Hold cancelled, seat {seat_id} returned.")

    def is_confirmed(self, event_id, seat_id) -> bool:
        """O(1) check -- this is the whole point of using a HashSet here."""
        return (event_id, seat_id) in self.confirmed


# ---------------------------------------------------------------------------
# QUICK MANUAL TEST -- run this file directly: `python confirmation.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    store = FakeHeldSeatsStore()
    heap = FakeHeap()
    manager = ConfirmationManager(store, heap)

    # Simulate Evans's component having already held a seat for us
    store.add(token="abc123", seat_id="A1", event_id="EVT001", hold_seconds=60)

    print("--- Confirming a valid hold ---")
    result = manager.confirm_booking("abc123")
    print(result)
    print("Is A1 confirmed?", manager.is_confirmed("EVT001", "A1"))

    print("\n--- Trying to confirm the same token again (should fail) ---")
    result = manager.confirm_booking("abc123")
    print(result)

    print("\n--- Cancelling a fresh hold ---")
    store.add(token="xyz789", seat_id="B2", event_id="EVT001", hold_seconds=60)
    result = manager.cancel_booking("xyz789")
    print(result)
    print("Seats returned to heap:", heap.returned_seats)

    print("\n--- Confirming an EXPIRED hold (should fail and release seat) ---")
    store.add(token="expired1", seat_id="C3", event_id="EVT001", hold_seconds=-5)
    result = manager.confirm_booking("expired1")
    print(result)
    print("Seats returned to heap:", heap.returned_seats)