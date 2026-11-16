"""Bounded process-local wake-ups; the export owner retains all durable state/claims."""

import threading
from collections import deque
from dataclasses import dataclass
from typing import Literal

from eom_operator_identity import ActorContext

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_pdf_delivery import KakaoPdfDelivery


@dataclass(frozen=True, slots=True)
class _Wakeup:
    actor: ActorContext
    binding: str
    export_id: str


class KakaoPdfCoordinator:
    def __init__(self, delivery: KakaoPdfDelivery, *, capacity: int = 200) -> None:
        if type(capacity) is not int or not 1 <= capacity <= 200:
            raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
        self._delivery, self._capacity = delivery, capacity
        self._queue: deque[_Wakeup] = deque()
        self._keys: set[tuple[str | None, str, str]] = set()
        self._lock, self._tick = threading.Lock(), threading.Lock()

    def submit(self, actor: ActorContext, binding: str, export_id: str) -> None:
        key = (actor.operator_id, binding, export_id)
        with self._lock:
            if key in self._keys:
                return
            if len(self._keys) >= self._capacity:
                # The PENDING DB export remains resumable by the original request;
                # no new identity, bypass or unbounded memory is created here.
                raise KakaoArchiveError("KAKAO_ARCHIVE_PDF_CAPACITY_BUSY")
            self._keys.add(key)
            self._queue.append(_Wakeup(actor, binding, export_id))

    def advance_once(self) -> Literal["IDLE", "WAITING", "COMPLETED", "REVIEW", "ERROR"]:
        if not self._tick.acquire(blocking=False):
            return "WAITING"
        wakeup = None
        try:
            with self._lock:
                if not self._queue:
                    return "IDLE"
                wakeup = self._queue.popleft()
            result = self._delivery.run(wakeup.actor, wakeup.binding, wakeup.export_id)
            return (
                "COMPLETED"
                if result.state == "COMPLETED"
                else "REVIEW"
                if result.state == "NEEDS_LAYOUT_REVIEW"
                else "ERROR"
            )
        except Exception:
            # Exact RUNNING command/output remain recoverable after uncertain I/O;
            # neither this dispatcher nor logs claim a failure became success.
            return "ERROR"
        finally:
            if wakeup is not None:
                with self._lock:
                    self._keys.discard((wakeup.actor.operator_id, wakeup.binding, wakeup.export_id))
            self._tick.release()
