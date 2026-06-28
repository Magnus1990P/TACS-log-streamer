import asyncio
from contextlib import asynccontextmanager


class Broadcaster:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue] = set()
        self._closing = asyncio.Event()

    @asynccontextmanager
    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._clients.add(queue)
        try:
            yield queue
        finally:
            self._clients.discard(queue)

    def publish(self, event: dict) -> None:
        for queue in list(self._clients):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def close(self) -> None:
        self._closing.set()

    @property
    def closing(self) -> asyncio.Event:
        return self._closing

    @property
    def connection_count(self) -> int:
        return len(self._clients)
