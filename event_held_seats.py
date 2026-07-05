"""
WHAT THIS COMPONENT IS RESPONSIBLE FOR
---------------------------------------
This is the middle phase of the booking flow:

    Owner 2 (heap)  --pop seat-->  [THIS COMPONENT]  --confirm-->  Owner 4 (HashSet)
                                     holds it under a
                                     token, with a TTL

Concretely:
  1. A secondary HashMap: token -> Hold(seat, event_id, expiry).
     This is a real data structure requirement in its own right
     (separate from Owner 1's event HashMap) -- it exists so we can
     check/expire ONE specific hold in O(1) without ever touching the
     seat heap.
  2. Token generation (holdSeat()).
  3. A background sweep algorithm that walks the held-seats map on a
     timer, finds expired holds, and pushes those seats back onto
     Owner 2's heap via a callback -- this is the "lazy TTL scan"
     algorithm referenced in the report.

WHY A DICT (HASHMAP) AND NOT A LIST
------------------------------------
The natural operations here are "does this token exist, and if so what
does it point to" and "delete this token." Both are O(1) average with
a dict/HashMap. A list would force an O(n) scan every time a client
confirmed or cancelled a booking, which doesn't scale once many seats
are held concurrently during a busy on-sale window.

WHY A SEPARATE MAP FROM OWNER 1'S EVENT REGISTRY
--------------------------------------------------
Owner 1's HashMap answers "what is event X." This HashMap answers "what
seat is token Y currently holding, and when does that hold expire."
Different key space (token vs event id), different lifetime (seconds
to minutes vs the life of the event), different owner. Keeping them
separate means Owner 1 and I never touch the same map, which avoids
merge conflicts and lock contention.

WHY A TTL / EXPIRY SWEEP INSTEAD OF EXPIRING ON READ ONLY
-----------------------------------------------------------
We do both:
  - Lazy check on read: get_hold() / confirm() / cancel() all check
    is_expired() before doing anything, so a stale hold can never be
    confirmed even if the sweep hasn't run yet.
  - Active sweep on a timer: without this, a seat whose holder simply
    closes their browser tab would stay "held" (and therefore
    unavailable) forever, since nothing would ever read that token
    again to trigger the lazy check. The background sweep guarantees
    abandoned holds are returned to the heap within one sweep
    interval, which is the real-world UX behaviour we wanted
    ("payment window expires, seat becomes available again").

THREAD SAFETY
--------------
This module keeps its own `threading.Lock` around every mutation of
the held-seats dict. That is a narrower, component-local lock than
Owner 5's system-wide mutex, which will additionally wrap the full
"pop from heap THEN insert into held-seats map" sequence so those two
steps happen atomically together. This component's internal lock just
guarantees the held-seats map itself is never corrupted by two threads
writing to it at once, independent of how Owner 5 wires the rest of
the pipeline together.

INTEGRATION CONTRACT (for Owners 2, 4, 5)
--------------------------------------------
Owner 2 (heap) provides a callback: `on_seat_expired(event_id, seat)`.
This component calls it whenever a hold expires (via sweep or via
cancel_hold()), so Owner 2's heap can push the seat back on. This
component never imports or depends on Owner 2's heap class directly --
it only calls whatever callable Owner 2/Owner 5 wire up. That keeps
this component testable and mergeable before the heap is finished
(see tests/test_held_seats.py, which uses a fake callback).

Owner 4 (HashSet/confirm) calls `confirm_hold(token)`, which removes
the hold from this map and hands back the seat + event_id for Owner 4
to insert into the confirmed-bookings HashSet. This component does not
know what a "confirmed booking" looks like -- that's Owner 4's data
structure, not this one.
"""

import secrets
import threading
import time
from typing import Any, Callable, Optional



"""
Data model for a single held seat.

Kept deliberately tiny and dependency-free so Owner 1 (Event/Seat model)
and Owner 2 (Min-Heap) can plug their real objects in without needing to
import anything from this file except this one dataclass (or not even
that -- see the `seat` field below, which is intentionally left as
`Any` so it can hold whichever Seat object Owner 1/Owner 2 settle on).
"""

from dataclasses import dataclass, field

@dataclass
class Hold:
    """
    Represents one seat currently "held" during checkout.

    token       - opaque string handed to the client; the only thing
                  the outside world needs to reference this hold.
    seat        - the actual seat object popped from Owner 2's heap.
                  Typed as Any on purpose: this component doesn't need
                  to know Seat's internal shape, only that it exists.
    event_id    - which event the seat belongs to (needed so the sweep
                  can tell Owner 2's heap which per-event heap to push
                  back onto).
    created_at  - epoch seconds when the hold was created.
    expires_at  - epoch seconds after which the hold is considered stale.
    """
    token: str
    seat: Any
    event_id: Any
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def is_expired(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return now >= self.expires_at


# Type alias for readability: called as on_expire(event_id, seat)
ExpireCallback = Callable[[Any, Any], None]

DEFAULT_TTL_SECONDS = 120  # length of the payment/checkout window


class HeldSeatsManager:
    def __init__(
        self,
        on_expire: Optional[ExpireCallback] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self._holds: dict[str, Hold] = {}          # token -> Hold  (the HashMap)
        self._lock = threading.Lock()
        self._on_expire = on_expire
        self._ttl_seconds = ttl_seconds
        self._sweep_thread: Optional[threading.Thread] = None
        self._stop_sweep = threading.Event()

    # ------------------------------------------------------------------
    # Token generation
    # ------------------------------------------------------------------
    @staticmethod
    def _generate_token() -> str:
        """
        secrets.token_urlsafe rather than a counter or uuid4:
        - Must be unguessable (a guessable token would let another user
          confirm/cancel someone else's hold -- this is a security
          boundary, not just an id).
        - secrets is specifically designed for this ("generate secure
          random numbers for tokens"), whereas uuid4 is fine but not
          explicitly documented as cryptographically secure.
        """
        return secrets.token_urlsafe(16)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------
    def hold_seat(self, seat: Any, event_id: Any, ttl_seconds: Optional[int] = None) -> str:
        """
        Register a newly-popped seat as held, under a fresh token.

        Called immediately after Owner 2's heap.popBestSeat(). Owner 5's
        system-wide mutex is expected to wrap "pop from heap" + this
        call together so no other request can pop the same seat in
        between. This method itself only guarantees the held-seats map
        stays consistent; it does not talk to the heap at all.

        Complexity: O(1) average (dict insert).
        """
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        token = self._generate_token()
        now = time.time()
        hold = Hold(token=token, seat=seat, event_id=event_id,
                    created_at=now, expires_at=now + ttl)

        with self._lock:
            # Extremely unlikely collision given 16 random bytes, but
            # cheap to guard against instead of assuming.
            while token in self._holds:
                token = self._generate_token()
                hold.token = token
            self._holds[token] = hold

        return token

    def get_hold(self, token: str) -> Optional[Hold]:
        """
        Look up a hold without removing it. Returns None if the token
        doesn't exist OR has already expired (lazy expiry check).
        Complexity: O(1) average.
        """
        with self._lock:
            hold = self._holds.get(token)
            if hold is None:
                return None
            if hold.is_expired():
                return None
            return hold

    def confirm_hold(self, token: str) -> Optional[Hold]:
        """
        Called by Owner 4 when payment succeeds. Removes the hold from
        this map and returns it so Owner 4 can insert (event_id, seat)
        into the confirmed-bookings HashSet.

        Returns None if the token is missing or already expired --
        Owner 4 should treat that as "payment window closed, seat no
        longer available" and reject the confirmation.

        Complexity: O(1) average.
        """
        with self._lock:
            hold = self._holds.get(token)
            if hold is None or hold.is_expired():
                self._holds.pop(token, None)
                return None
            del self._holds[token]
            return hold

    def cancel_hold(self, token: str) -> Optional[Hold]:
        """
        Explicit client-initiated cancel (as opposed to the background
        sweep catching an abandoned hold). Removes the hold and fires
        the expire callback so the seat goes back on Owner 2's heap
        immediately rather than waiting for the next sweep tick.

        Complexity: O(1) average.
        """
        with self._lock:
            hold = self._holds.pop(token, None)

        if hold is not None and self._on_expire is not None:
            self._on_expire(hold.event_id, hold.seat)
        return hold

    # ------------------------------------------------------------------
    # Background expiry sweep (the "lazy TTL scan" algorithm)
    # ------------------------------------------------------------------
    def sweep_once(self) -> int:
        """
        Single pass over the held-seats map: find every hold whose
        expiry has passed, remove it, and push its seat back onto the
        heap via the callback.

        This is O(k) where k = number of currently held seats (NOT the
        total number of seats in the system) -- we only ever walk
        active holds, never the full seat inventory.
        """
        now = time.time()
        expired: list[Hold] = []

        with self._lock:
            expired_tokens = [t for t, h in self._holds.items() if h.expires_at <= now]
            for t in expired_tokens:
                expired.append(self._holds.pop(t))

        for hold in expired:
            if self._on_expire is not None:
                self._on_expire(hold.event_id, hold.seat)

        return len(expired)

    def start_background_sweep(self, interval_seconds: float = 5.0) -> None:
        """
        Runs sweep_once() on a fixed interval in a daemon thread until
        stop_background_sweep() is called. interval_seconds should be
        noticeably smaller than the TTL (default TTL 120s, default
        sweep every 5s) so an abandoned hold is reclaimed quickly
        without spinning a busy loop.
        """
        if self._sweep_thread is not None and self._sweep_thread.is_alive():
            return  # already running

        self._stop_sweep.clear()

        def _loop():
            while not self._stop_sweep.wait(interval_seconds):
                self.sweep_once()

        self._sweep_thread = threading.Thread(target=_loop, daemon=True)
        self._sweep_thread.start()

    def stop_background_sweep(self) -> None:
        self._stop_sweep.set()
        if self._sweep_thread is not None:
            self._sweep_thread.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Introspection helpers (useful for the demo / debugging)
    # ------------------------------------------------------------------
    def active_hold_count(self) -> int:
        with self._lock:
            return len(self._holds)
