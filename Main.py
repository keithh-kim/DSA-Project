"""
main.py
Entry point for the Ticket Booking System.

Wires together everyone's components through Mohammed's BookingService/Api
layer, and gives you two ways to run the project:

    python3 main.py            -> runs a scripted terminal demo (good for
                                   showing the marking-scheme scenarios live:
                                   select -> confirm, select -> cancel,
                                   expired hold, and the concurrency race)

    python3 main.py --serve    -> starts the real Flask API on
                                   http://127.0.0.1:5000 so you can hit it
                                   with curl/Postman during the demo instead
                                   of just printing to the terminal
"""

import sys
import threading
import time

from event_registry import EventRegistry
from api import BookingService, create_app


def seed_demo_event(service: BookingService) -> str:
    """Creates one event with a small number of seats so the demo is
    easy to follow (few seats = easy to exhaust and show edge cases)."""
    event = service.create_event(
        event_id="E2026-F1",
        name="Sol Fest Live",
        date="2026-12-19",
        seat_tiers=[
            ("VIP", 150.0, 2),   # 2 VIP seats at 150
            ("REG", 50.0, 3),    # 3 Regular seats at 50
        ],
    )
    print(f"Seeded event: {event}\n")
    return event.event_id


# ---------------------------------------------------------------------------
# Terminal demo -- walks through every scenario the marking scheme cares
# about: normal booking, cancel, expiry, and a concurrency race.
# ---------------------------------------------------------------------------

def run_terminal_demo():
    registry = EventRegistry()
    # Short TTL and fast sweep so the "expired hold" scenario doesn't
    # require actually waiting the full 120-second default in a demo.
    service = BookingService(registry, hold_ttl_seconds=2, sweep_interval_seconds=1.0)
    event_id = seed_demo_event(service)

    print("=" * 60)
    print("1) SELECT then CONFIRM (the normal happy path)")
    print("=" * 60)
    selection = service.select_seat(event_id)
    print("Selected:", selection)
    confirmation = service.confirm_booking(selection["token"])
    print("Confirmed:", confirmation)

    print("\n" + "=" * 60)
    print("2) SELECT then CANCEL (seat should return to the heap)")
    print("=" * 60)
    selection = service.select_seat(event_id)
    print("Selected:", selection)
    cancellation = service.cancel_booking(selection["token"])
    print("Cancelled:", cancellation)
    reselection = service.select_seat(event_id)
    print("Selected again (proves the cancelled seat came back):", reselection)
    service.cancel_booking(reselection["token"])  # put it back for the next section

    print("\n" + "=" * 60)
    print("3) SELECT then let the HOLD EXPIRE (nobody confirms in time)")
    print("=" * 60)
    selection = service.select_seat(event_id)
    print("Selected:", selection, "-- waiting for the hold to expire...")
    time.sleep(3)  # longer than hold_ttl_seconds=2, so the background sweep catches it
    try:
        service.confirm_booking(selection["token"])
    except ValueError as e:
        print("Confirm correctly rejected:", e)
    reselection = service.select_seat(event_id)
    print("Selected again (proves the expired seat was reclaimed):", reselection)
    service.confirm_booking(reselection["token"])

    print("\n" + "=" * 60)
    print("4) CONCURRENCY: 10 threads race to select+confirm the LAST seat")
    print("=" * 60)
    # Drain every remaining seat except one, so all 10 threads are
    # genuinely fighting over a single seat.
    event = registry.get_event(event_id)
    while event.seat_heap.size() > 1:
        service.select_seat(event_id)  # hold and never confirm -- just draining

    results = []
    results_lock = threading.Lock()

    def try_book():
        try:
            sel = service.select_seat(event_id)
            conf = service.confirm_booking(sel["token"])
            with results_lock:
                results.append(("success", conf))
        except ValueError as e:
            with results_lock:
                results.append(("failed", str(e)))

    threads = [threading.Thread(target=try_book) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r[0] == "success"]
    failures = [r for r in results if r[0] == "failed"]
    print(f"{len(successes)} thread(s) succeeded, {len(failures)} failed (expected: 1 success)")
    for outcome, detail in results:
        print(" ", outcome, "-", detail)

    service.held_seats.stop_background_sweep()
    print("\nDemo complete.")


# ---------------------------------------------------------------------------
# Flask server mode
# ---------------------------------------------------------------------------

def run_server():
    registry = EventRegistry()
    service = BookingService(registry)
    seed_demo_event(service)

    app = create_app(service)
    print("Starting API on http://127.0.0.1:5000")
    print("Try:")
    print('  curl -X POST http://127.0.0.1:5000/events/E2026-F1/select')
    print('  curl -X POST http://127.0.0.1:5000/bookings/<token>/confirm')
    print('  curl http://127.0.0.1:5000/events/E2026-F1')
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        run_server()
    else:
        run_terminal_demo()