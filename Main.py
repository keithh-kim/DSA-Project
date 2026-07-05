"""
main.py
Entry point: builds a demo event on top of the real Components 1-4 and
starts the API + background sweep.
"""

from event_registry import EventRegistry
from api import BookingService, create_app


def main():
    registry = EventRegistry()
    service = BookingService(registry, hold_ttl_seconds=120, sweep_interval_seconds=5.0)

    service.create_event(
        "concert-1",
        "Nairobi Live Concert",
        "2026-12-19",
        seat_tiers=[
            ("VIP", 150.0, 2),
            ("Standard", 75.0, 3),
            ("Economy", 40.0, 5),
        ],
    )

    app = create_app(service)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()