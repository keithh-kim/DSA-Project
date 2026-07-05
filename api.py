"""
api.py
Owner 5 (Mohammed Osman): Concurrency & Integration/API

This wires together the REAL components your teammates wrote:
    event_registry.py    Keith  - EventRegistry / Event / Seat
    seat_heap.py          Trent  - EventSeatHeap (manual sift-up/down)
    event_held_seats.py   Evans  - HeldSeatsManager (token -> Hold, TTL sweep)
    confirmation.py       Wilson - ConfirmationManager (confirmed HashSet)

--------------------------------------------------------------------------
INTEGRATION ISSUES FOUND, AND HOW THEY'RE RESOLVED
--------------------------------------------------------------------------
1. TWO Seat CLASSES.
   Keith's event_registry.Seat is the one actually stored in the system
   (created by Event.add_seat_tier). Trent's seat_heap.EventSeatHeap
   requires whatever object it holds to expose `.priority_key()`, but
   Trent wrote that method on HIS OWN Seat class, not Keith's. Rather
   than duplicate seats into a second object, we attach a `priority_key`
   method onto Keith's Seat class (Keith's dataclass Seat has no method
   of that name, so this is additive, not a conflict) so Trent's heap can
   order Keith's real Seat objects directly. This is a one-line fix Keith
   could also make himself in event_registry.py.

2. Event STORES SEATS AS A PLAIN LIST, NOT A HEAP.
   Keith's Event.available_seats is a list built by add_seat_tier(); his
   comment says Trent will "wrap/replace this array." Integration glue
   here builds one EventSeatHeap per event from that list (bulk_insert)
   and attaches it as `event.seat_heap`, so Owner 5 (and the API) always
   pop/push through the heap, never the raw list.

3. WILSON'S ConfirmationManager EXPECTS A DIFFERENT SHAPE THAN WHAT
   EVANS AND TRENT ACTUALLY BUILT.
   Wilson's class was written and tested against his own Fake stubs:
     - held_seats_store.get(token) -> (seat_id, event_id, expiry_time)
     - held_seats_store.remove(token)
     - heap.push_seat_back(event_id, seat_id)
   Evans's real HeldSeatsManager instead returns a `Hold` dataclass
   (with the full seat OBJECT, not just an id) from get_hold(), and has
   no bare remove() (only confirm_hold()/cancel_hold(), which both
   remove-and-return). Trent's real heap is per-event and takes the full
   seat object, not an id, and doesn't take an event_id at all (each
   heap instance IS one event's heap).
   Fix: two small adapter classes below (`HeldSeatsAdapter`,
   `ConfirmationHeapAdapter`) translate between the two shapes so
   Wilson's class runs unmodified against the real components. The
   adapters cache the real Seat object by (event_id, seat_id) the moment
   Wilson's code reads a hold, so that when he later calls
   `heap.push_seat_back(event_id, seat_id)` with just the id, we can
   still push the *original* Seat object (with its real tier/price) back
   onto the correct event's heap.

4. THE MUTEX.
   Keith already added `self.lock = threading.Lock()` to Event, with a
   comment flagging it as "Osman's Concurrency Layer." We use exactly
   that per-event lock to wrap the one operation that isn't already
   protected anywhere: pop-from-heap + create-hold together (the
   "select" phase). Confirm/cancel are protected by Wilson's own
   `ConfirmationManager.lock`; the background sweep is protected by
   Evans's own `HeldSeatsManager._lock`. Owner 5's job is making sure
   the one gap between components (select) is also race-free, and that
   the three locks are always acquired in a single consistent order
   (event.lock, if held, is only ever acquired from within this file,
   never from inside Wilson's or Evans's lock) so there's no deadlock
   risk from lock ordering.
--------------------------------------------------------------------------
"""

from flask import Flask, jsonify

from event_registry import EventRegistry, Seat as ModelSeat
from event_seat_heap import EventSeatHeap
from event_held_seats import HeldSeatsManager
from event_confirmation import ConfirmationManager

# --------------------------------------------------------------------------
# Issue 1 fix: give Keith's Seat the method Trent's heap requires.
# --------------------------------------------------------------------------
if not hasattr(ModelSeat, "priority_key"):
    def _priority_key(self):
        return (self.tier, self.price, self.seat_id)


    ModelSeat.priority_key = _priority_key


# --------------------------------------------------------------------------
# Issue 3 fix: adapters between Wilson's expected interface and the real
# Evans/Trent components.
# --------------------------------------------------------------------------
class HeldSeatsAdapter:
    """Makes Evans's HeldSeatsManager look like the (seat_id, event_id,
    expiry_time) tuple store Wilson's ConfirmationManager was built against."""

    def __init__(self, manager: HeldSeatsManager, seat_cache: dict):
        self._manager = manager
        self._seat_cache = seat_cache

    def get(self, token):
        hold = self._manager.get_hold(token)  # None if missing OR expired
        if hold is None:
            return None
        # Remember the real Seat object -- Wilson's tuple only carries the
        # id string, which would otherwise lose tier/price on the way back.
        self._seat_cache[(hold.event_id, hold.seat.seat_id)] = hold.seat
        return (hold.seat.seat_id, hold.event_id, hold.expires_at)

    def remove(self, token):
        # confirm_hold() is a pure removal (no callback side effects) --
        # exactly what both Wilson's confirm and cancel paths need, since
        # pushing the seat back to the heap is handled separately by
        # whichever of his methods decides to call heap.push_seat_back().
        self._manager.confirm_hold(token)


class ConfirmationHeapAdapter:
    """Makes Trent's per-event EventSeatHeap look like the single global
    heap.push_seat_back(event_id, seat_id) Wilson's class expects."""

    def __init__(self, registry: EventRegistry, seat_cache: dict):
        self._registry = registry
        self._seat_cache = seat_cache

    def push_seat_back(self, event_id, seat_id):
        seat = self._seat_cache.pop((event_id, seat_id), None)
        event = self._registry.get_event(event_id)
        if seat is None or event is None:
            return
        seat.is_available = True
        with event.lock:
            event.seat_heap.push_seat_back(seat)


# --------------------------------------------------------------------------
# BookingService: the actual integration + mutex layer
# --------------------------------------------------------------------------
class BookingService:
    def __init__(self, registry: EventRegistry, hold_ttl_seconds: int = 120,
                 sweep_interval_seconds: float = 5.0):
        self.registry = registry
        self._seat_cache: dict = {}  # (event_id, seat_id) -> Seat, shared with adapters

        self.held_seats = HeldSeatsManager(
            on_expire=self._on_seat_expired,
            ttl_seconds=hold_ttl_seconds,
        )
        self.confirmation = ConfirmationManager(
            held_seats_store=HeldSeatsAdapter(self.held_seats, self._seat_cache),
            heap=ConfirmationHeapAdapter(registry, self._seat_cache),
        )
        self.held_seats.start_background_sweep(interval_seconds=sweep_interval_seconds)

    def _on_seat_expired(self, event_id, seat):
        """Background-sweep callback (Evans's on_expire): an abandoned hold
        timed out with nobody reading it, so push it back proactively."""
        event = self.registry.get_event(event_id)
        if event is not None:
            seat.is_available = True
            with event.lock:
                event.seat_heap.push_seat_back(seat)
        self._seat_cache.pop((event_id, seat.seat_id), None)

    # ---- setup helper ------------------------------------------------------
    def create_event(self, event_id, name, date, seat_tiers):
        """seat_tiers: list of (tier_name, price, capacity) tuples.
        Wires Issue 2's fix: builds the per-event heap from Keith's list."""
        event = self.registry.create_event(event_id, name, date)
        for tier_name, price, capacity in seat_tiers:
            event.add_seat_tier(tier_name, price, capacity)
        event.seat_heap = EventSeatHeap()
        event.seat_heap.bulk_insert(event.available_seats)
        return event

    # ---- SELECT (the gap Owner 5 is responsible for protecting) --------
    def select_seat(self, event_id: str) -> dict:
        event = self.registry.get_event(event_id)
        if event is None:
            raise ValueError(f"Event '{event_id}' not found")

        with event.lock:  # Keith's per-event mutex
            seat = event.seat_heap.pop_best_seat()  # Trent: O(log n)
            if seat is None:
                raise ValueError(f"No seats available for event '{event_id}'")
            seat.is_available = False
            token = self.held_seats.hold_seat(seat=seat, event_id=event_id)  # Evans: O(1)

        self._seat_cache[(event_id, seat.seat_id)] = seat
        hold = self.held_seats.get_hold(token)
        return {
            "token": token,
            "seat_id": seat.seat_id,
            "tier": seat.tier,
            "price": seat.price,
            "expires_at": hold.expires_at if hold is not None else None,
        }

    # ---- CONFIRM / CANCEL: delegate straight to Wilson's real class ----
    def confirm_booking(self, token: str) -> dict:
        pre = self.held_seats.get_hold(token)  # for a richer response only
        result = self.confirmation.confirm_booking(token)
        if not result.success:
            raise ValueError(result.message)
        response = {"status": "confirmed", "message": result.message}
        if pre is not None:
            response["seat_id"] = pre.seat.seat_id
            response["event_id"] = pre.event_id
        return response

    def cancel_booking(self, token: str) -> dict:
        pre = self.held_seats.get_hold(token)
        result = self.confirmation.cancel_booking(token)
        if not result.success:
            raise ValueError(result.message)
        response = {"status": "cancelled", "message": result.message}
        if pre is not None:
            response["seat_id"] = pre.seat.seat_id
        return response


# --------------------------------------------------------------------------
# Flask API layer
# --------------------------------------------------------------------------
def create_app(service: BookingService) -> Flask:
    import os
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    app = Flask(__name__, static_folder=static_dir, static_url_path="")

    index_path = os.path.join(static_dir, "index.html")
    print(f"[startup] Looking for frontend at: {index_path}")
    print(f"[startup] Found: {os.path.exists(index_path)}")

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.post("/events/<event_id>/select")
    def select(event_id):
        try:
            return jsonify(service.select_seat(event_id)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 409

    @app.post("/bookings/<token>/confirm")
    def confirm(token):
        try:
            return jsonify(service.confirm_booking(token)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 409

    @app.post("/bookings/<token>/cancel")
    def cancel(token):
        try:
            return jsonify(service.cancel_booking(token)), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 409

    @app.get("/events/<event_id>")
    def get_event(event_id):
        event = service.registry.get_event(event_id)
        if event is None:
            return jsonify({"error": "event not found"}), 404
        return jsonify({
            "event_id": event.event_id,
            "name": event.name,
            "date": event.date,
            "seats_remaining": event.seat_heap.size(),
            "total_seats": len(event.available_seats),
        }), 200

    @app.get("/events/<event_id>/next-seat")
    def next_seat(event_id):
        """Read-only peek at the best available seat, WITHOUT holding it.
        Lets the UI show 'next up: VIP-2, $150' before the user commits."""
        event = service.registry.get_event(event_id)
        if event is None:
            return jsonify({"error": "event not found"}), 404
        seat = event.seat_heap.peek()  # Trent's O(1) peek -- does not pop
        if seat is None:
            return jsonify({"seat": None}), 200
        return jsonify({
            "seat": {"seat_id": seat.seat_id, "tier": seat.tier, "price": seat.price}
        }), 200

    return app
