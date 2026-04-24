from __future__ import annotations

import asyncio
import threading
from typing import Any


class JobEventHub:
    def __init__(self, max_clients: int = 5) -> None:
        self._max_clients = max_clients
        self._clients: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    @property
    def max_clients(self) -> int:
        return self._max_clients

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            if len(self._clients) >= self._max_clients:
                raise RuntimeError("too_many_clients")
            self._clients.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._clients:
                self._clients.remove(queue)

    def broadcast(self, event: dict[str, Any]) -> None:
        with self._lock:
            loop = self._loop
            clients = list(self._clients)
        if loop is None or loop.is_closed():
            return
        for queue in clients:
            loop.call_soon_threadsafe(queue.put_nowait, event)
