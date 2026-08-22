import threading


class DeduplicatedSet:
    """Thread-safe set for in-memory subdomain deduplication."""

    def __init__(self) -> None:
        self._data: set[str] = set()
        self._lock = threading.Lock()

    def add(self, item: str) -> bool:
        """Add a single item. Returns True if the item was not already present."""
        with self._lock:
            if item not in self._data:
                self._data.add(item)
                return True
            return False

    def update(self, items: set[str]) -> set[str]:
        """Add multiple items. Returns the set of newly added items."""
        new_items: set[str] = set()
        with self._lock:
            for item in items:
                if item not in self._data:
                    self._data.add(item)
                    new_items.add(item)
        return new_items

    def as_set(self) -> set[str]:
        with self._lock:
            return set(self._data)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
