class Seat:
    def __init__(self, seat_id, tier, price):
        self.seat_id = seat_id
        self.tier = tier
        self.price = price

    def priority_key(self):
        return (self.tier, self.price, self.seat_id)

    def __repr__(self):
        return "Seat(" + self.seat_id + ", tier=" + str(self.tier) + ", price=" + str(self.price) + ")"


class EventSeatHeap:
    def __init__(self):
        self.heap = []

    def parent_index(self, i):
        return (i - 1) // 2

    def left_child_index(self, i):
        return 2 * i + 1

    def right_child_index(self, i):
        return 2 * i + 2

    def swap(self, i, j):
        self.heap[i], self.heap[j] = self.heap[j], self.heap[i]

    def sift_up(self, i):
        while i > 0:
            parent = self.parent_index(i)
            if self.heap[i].priority_key() < self.heap[parent].priority_key():
                self.swap(i, parent)
                i = parent
            else:
                break

    def sift_down(self, i):
        size = len(self.heap)
        while True:
            left = self.left_child_index(i)
            right = self.right_child_index(i)
            smallest = i

            if left < size and self.heap[left].priority_key() < self.heap[smallest].priority_key():
                smallest = left
            if right < size and self.heap[right].priority_key() < self.heap[smallest].priority_key():
                smallest = right

            if smallest == i:
                break

            self.swap(i, smallest)
            i = smallest

    def push_seat_back(self, seat):
        self.heap.append(seat)
        self.sift_up(len(self.heap) - 1)

    def peek(self):
        if len(self.heap) == 0:
            return None
        return self.heap[0]

    def pop_best_seat(self):
        if len(self.heap) == 0:
            return None

        best_seat = self.heap[0]
        last_seat = self.heap.pop()

        if len(self.heap) > 0:
            self.heap[0] = last_seat
            self.sift_down(0)

        return best_seat

    def bulk_insert(self, list_of_seats):
        self.heap = list(list_of_seats)
        n = len(self.heap)
        last_parent = n // 2 - 1
        for i in range(last_parent, -1, -1):
            self.sift_down(i)

    def is_empty(self):
        return len(self.heap) == 0

    def size(self):
        return len(self.heap)


if __name__ == "__main__":
    event_heap = EventSeatHeap()

    seats = [
        Seat("A1", tier=1, price=150),
        Seat("B4", tier=2, price=80),
        Seat("C2", tier=3, price=40),
        Seat("A2", tier=1, price=150),
        Seat("B1", tier=2, price=90),
        Seat("C9", tier=3, price=35),
    ]

    event_heap.bulk_insert(seats)
    print("Best seat right now:", event_heap.peek())

    print("Popping every seat (best first, worst last):")
    while not event_heap.is_empty():
        print(" ", event_heap.pop_best_seat())

    event_heap.push_seat_back(Seat("D1", tier=2, price=100))
    event_heap.push_seat_back(Seat("D2", tier=1, price=200))
    print("Best seat:", event_heap.peek())

    held_seat = event_heap.pop_best_seat()
    print("Took this seat for a customer:", held_seat)
    print("New best seat:", event_heap.peek())

    event_heap.push_seat_back(held_seat)
    print("Best seat again:", event_heap.peek())
