"""One in-process CPU command, never another queue or source/claim authority."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eom_workflow_runner.local_indexing_routed_namespace import (
        RoutedLocalIndexingNamespaceRuntime,
    )
    from eom_workflow_runner.models import WorkflowCommandRecord


class LocalIndexingCpuLane:
    """Only one live future; the existing Runner still owns all durable work."""

    def __init__(
        self,
        executor: ThreadPoolExecutor,
        namespaces: tuple[RoutedLocalIndexingNamespaceRuntime, ...],
        stop: Event,
        observe: Callable[[str, WorkflowCommandRecord, int], None],
    ) -> None:
        self.executor, self.namespaces, self.stop, self.observe = (
            executor,
            namespaces,
            stop,
            observe,
        )
        self._future: Future[tuple[WorkflowCommandRecord | None, int]] | None = None
        self._cursor = 0
        self._view = ""

    def poll(self, *, wait: bool = False) -> None:
        future = self._future
        if future is None or (not wait and not future.done()):
            return
        # Clear before result(): a failed command must not be observed twice or
        # silently retried in a finally block. The exception reaches the owner.
        self._future = None
        command, elapsed_ms = future.result()
        if command is not None:
            self.observe(self._view, command, elapsed_ms)

    def drain(self) -> None:
        # A future not yet started has not claimed a command. Only that pending
        # Python call may be cancelled; live work always finishes naturally.
        if self._future is not None and self._future.cancel():
            self._future = None
        self.poll(wait=True)

    def start_next(self) -> None:
        if self.stop.is_set() or self._future is not None:
            return
        namespace = self.namespaces[self._cursor]
        self._cursor = (self._cursor + 1) % len(self.namespaces)
        self._view = namespace.namespace.view

        def run() -> tuple[WorkflowCommandRecord | None, int]:
            # A stop can arrive between submit and the worker actually starting.
            started = time.monotonic()
            command = None if self.stop.is_set() else namespace.run_once()
            return command, int((time.monotonic() - started) * 1000)

        self._future = self.executor.submit(run)
