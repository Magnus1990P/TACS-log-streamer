from collections import deque


class EventCache:
    """Ring buffer for the last N log events."""

    def __init__(self, maxlen: int = 200):
        self._events: deque[dict] = deque(maxlen=maxlen)

    def add(self, event: dict) -> None:
        self._events.append(event)

    def snapshot(self) -> list[dict]:
        return list(self._events)
