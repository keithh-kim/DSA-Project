import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, List


# ==========================================
# 1. CORE DATA MODEL & REGISTRY (Keith)
# ==========================================

@dataclass(order=True)
class Seat:
    """
    Represents a single seat in a venue.
    The @dataclass(order=True) decorator automatically implements comparison magic (__lt__, __gt__).
    Because 'price' is the first non-excluded field, Python will naturally compare seats by price,
    which directly assists Trent's Min-Heap implementation.
    """
    seat_id: str = field(compare=False)  # e.g., "VIP-A1", "REG-B20"
    tier: str = field(compare=False)  # e.g., "VIP", "Regular"
    price: float  # Min-Heap sorting priority (lowest price first)[cite: 1]
    is_available: bool = field(default=True, compare=False)

    def __repr__(self):
        return f"Seat(ID: {self.seat_id}, Tier: {self.tier}, Price: {self.price})"


class Event:
    """
    Encapsulates all metadata and structural tracking for a specific event[cite: 1].
    """

    def __init__(self, event_id: str, name: str, date: str):
        self.event_id = event_id
        self.name = name
        self.date = date

        # Trent will wrap/replace this array with his manual Min-Heap structural logic[cite: 1]
        self.available_seats: List[Seat] = []

        # Osman's Concurrency Layer: Dedicated Mutex lock per event to prevent race conditions[cite: 1]
        self.lock = threading.Lock()

    def add_seat_tier(self, tier_name: str, price: float, capacity: int) -> None:
        """
        Bulk seat insertion utility for event creation[cite: 1].
        Generates seats for a given tier and appends them to the availability collection[cite: 1].
        """
        for i in range(1, capacity + 1):
            seat_id = f"{tier_name}-{i}"
            new_seat = Seat(seat_id=seat_id, tier=tier_name, price=price)
            self.available_seats.append(new_seat)

        # Note: Trent will need to call his manual min_heapify() here after bulk insertion[cite: 1]

    def __repr__(self):
        return f"Event({self.event_id}: '{self.name}' on {self.date}, Total Seats Generated: {len(self.available_seats)})"


class EventRegistry:
    """
    Top-level catalog managing events using a Hash Map (Python Dict) to achieve O(1) average lookups[cite: 1].
    """

    def __init__(self):
        self._registry: Dict[str, Event] = {}

    def create_event(self, event_id: str, name: str, date: str) -> Event:
        """
        Creates, registers, and returns a new Event instance[cite: 1].
        Time Complexity: O(1) average lookup and insertion[cite: 1].
        """
        if event_id in self._registry:
            raise ValueError(f"CRITICAL ERROR: Event with ID {event_id} already exists in the system.")

        new_event = Event(event_id, name, date)
        self._registry[event_id] = new_event
        return new_event

    def get_event(self, event_id: str) -> Optional[Event]:
        """
        Retrieves an event by its unique ID[cite: 1].
        Time Complexity: O(1) average lookup[cite: 1].
        """
        return self._registry.get(event_id)

    def delete_event(self, event_id: str) -> None:
        """
        Removes an event from the registry catalog[cite: 1].
        Time Complexity: O(1) average deletion[cite: 1].
        """
        if event_id in self._registry:
            del self._registry[event_id]
        else:
            raise KeyError(f"ERROR: Cannot delete. Event ID {event_id} not found.")


# ==========================================
# TEST RUNNING VERIFICATION
# ==========================================
if __name__ == "__main__":
    print("--- Testing Component 1: Core Registry & Models ---")

    # 1. Initialize your registry
    manager = EventRegistry()

    # 2. Create a simulated event entry
    concert = manager.create_event("E2026-F1", "Sol Fest Live", "2026-12-19")

    # 3. Simulate bulk seat insertions (VIP and Regular tiers)[cite: 1]
    concert.add_seat_tier("VIP", price=150.0, capacity=5)
    concert.add_seat_tier("REG", price=50.0, capacity=10)

    print(concert)
    print("\nVerifying data mapping works cleanly:")
    print(f"First seat details: {concert.available_seats[0]}")
    print(f"Registry lookup verification for 'E2026-F1': {manager.get_event('E2026-F1').name}")