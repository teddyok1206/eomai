"""One shared snapshot poller with bounded latest-value client queues."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from eom_observe_contracts import ObserveSnapshot

from eom_observe.errors import ObserveError, ObserveErrorCode
from eom_observe.snapshot import SnapshotBuilder


@dataclass(frozen=True)
class StreamMessage:
    event_id: str
    event: str
    data: dict[str, Any]
    retry: int = 1000


def format_sse(message: StreamMessage) -> str:
    payload = json.dumps(message.data, sort_keys=True, separators=(",", ":"))
    return (
        f"id: {message.event_id}\n"
        f"event: {message.event}\n"
        f"retry: {message.retry}\n"
        f"data: {payload}\n\n"
    )


class SubscriptionHub:
    def __init__(self, max_clients: int) -> None:
        self.max_clients = max_clients
        self._clients: dict[str, asyncio.Queue[StreamMessage]] = {}
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def subscribe(self) -> tuple[str, asyncio.Queue[StreamMessage]]:
        async with self._lock:
            if len(self._clients) >= self.max_clients:
                raise ObserveError(
                    ObserveErrorCode.OBSERVE_STREAM_LIMIT_REACHED,
                    "maximum stream client count reached",
                )
            client_id = f"stream_{secrets.token_hex(8)}"
            queue: asyncio.Queue[StreamMessage] = asyncio.Queue(maxsize=1)
            self._clients[client_id] = queue
            logging.getLogger("eom_observe.stream").info(
                "stream client connected",
                extra={
                    "event": "STREAM_CONNECTED",
                    "stream_client_id": client_id,
                    "client_count": len(self._clients),
                },
            )
            return client_id, queue

    async def unsubscribe(self, client_id: str) -> None:
        async with self._lock:
            self._clients.pop(client_id, None)
            logging.getLogger("eom_observe.stream").info(
                "stream client disconnected",
                extra={
                    "event": "STREAM_DISCONNECTED",
                    "stream_client_id": client_id,
                    "client_count": len(self._clients),
                },
            )

    async def publish(self, message: StreamMessage) -> None:
        async with self._lock:
            for queue in self._clients.values():
                if queue.full():
                    with suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                    logging.getLogger("eom_observe.stream").warning(
                        "slow stream client snapshot replaced",
                        extra={
                            "event": "STREAM_CLIENT_SLOW",
                            "client_count": len(self._clients),
                            "error_code": ObserveErrorCode.OBSERVE_CLIENT_SLOW.value,
                        },
                    )
                queue.put_nowait(message)


class SharedSnapshotPoller:
    def __init__(
        self,
        builder: SnapshotBuilder,
        hub: SubscriptionHub,
        *,
        poll_interval_seconds: float,
    ) -> None:
        self.builder = builder
        self.hub = hub
        self.poll_interval_seconds = poll_interval_seconds
        self.current: ObserveSnapshot | None = None
        self.last_good: ObserveSnapshot | None = None
        self.degraded = False
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._build_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="eom-observe-snapshot-poller")

    async def stop(self) -> None:
        self._stopping.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def ensure_snapshot(self) -> ObserveSnapshot:
        if self.current is not None:
            return self.current
        async with self._build_lock:
            if self.current is None:
                await self._poll_once()
        if self.current is None:
            raise ObserveError(
                ObserveErrorCode.OBSERVE_SNAPSHOT_FAILED, "no observability snapshot available"
            )
        return self.current

    async def _poll_once(self) -> None:
        try:
            snapshot = await asyncio.to_thread(self.builder.build)
        except Exception:
            if self.last_good is not None:
                self.current = self.builder.stale_copy(self.last_good)
            if not self.degraded:
                self.degraded = True
                logging.getLogger("eom_observe.poller").warning(
                    "snapshot poller degraded",
                    extra={
                        "event": "SNAPSHOT_DEGRADED",
                        "client_count": self.hub.client_count,
                        "error_code": ObserveErrorCode.OBSERVE_DATABASE_UNAVAILABLE.value,
                    },
                )
                await self.hub.publish(
                    StreamMessage(
                        event_id=f"degraded_{int(datetime.now(UTC).timestamp())}",
                        event="degraded",
                        data={"status": "STALE", "error_code": "OBSERVE_DATABASE_UNAVAILABLE"},
                    )
                )
            return
        was_degraded = self.degraded
        previous_hash = self.current.content_hash if self.current else None
        self.current = snapshot
        self.last_good = snapshot
        self.degraded = False
        if was_degraded:
            logging.getLogger("eom_observe.poller").info(
                "snapshot poller recovered",
                extra={
                    "event": "SNAPSHOT_RECOVERED",
                    "snapshot_id": snapshot.snapshot_id,
                    "client_count": self.hub.client_count,
                },
            )
            await self.hub.publish(
                StreamMessage(
                    event_id=f"recovered_{snapshot.snapshot_id}",
                    event="recovered",
                    data={"status": "FRESH", "snapshot_id": snapshot.snapshot_id},
                )
            )
        elif previous_hash != snapshot.content_hash:
            await self.hub.publish(
                StreamMessage(
                    event_id=snapshot.snapshot_id,
                    event="delta" if previous_hash else "snapshot",
                    data=snapshot.model_dump(mode="json"),
                )
            )

    async def _run(self) -> None:
        while not self._stopping.is_set():
            await self._poll_once()
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_interval_seconds)
            except TimeoutError:
                continue
