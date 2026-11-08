"""Bounded creative source pipeline over existing Workflow and Graph applications.

There are no worker subprocesses or persistent queues here. A single Graph future
keeps expensive publication off the source-submission loop; Orchestrator owns all
purpose-bounded model claims. Restart reconstructs state from original immutable pins.
"""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace

from eom_catalog_contracts.creative_learning_continuation import (
    CreativeLearningOfficeContinuation,
    ParallelReportContinuation,
)
from eom_orchestrator.background_storage import BackgroundStoragePressure
from eom_orchestrator.database import recoverable_database_error_code
from sqlalchemy.exc import DBAPIError

from eom_catalog_service.creative_cohort_execution import (
    CreativeCohortExecutionService,
    CreativeCohortProgress,
    CreativeSourceExecution,
    CreativeSourceTerminalFailure,
)
from eom_catalog_service.creative_item_registration import CreativeItemContentUnavailable
from eom_catalog_service.creative_preview_preparation import CreativeSourcePreviewDeferred


class CreativeCohortParallelExecutionService:
    def __init__(
        self,
        owner: CreativeCohortExecutionService,
        *,
        verified_limit: int,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        continuation = owner.scope.continuation
        if not isinstance(continuation, ParallelReportContinuation):
            raise ValueError("CREATIVE_PARALLEL_CONTINUATION_REQUIRED")
        if not 1 <= verified_limit <= len(owner.targets):
            raise ValueError("CREATIVE_COHORT_EXECUTION_LIMIT_INVALID")
        self.owner = owner
        self.stop_requested = stop_requested
        self.targets = (
            owner.pending_first_targets()
            if verified_limit == len(owner.targets)
            else owner.targets[:verified_limit]
        )
        self._targets_by_id = {target.source_id: target for target in self.targets}
        self.window_limit = continuation.max_in_flight_sources
        self.batch_size = continuation.graph_publication_batch_size
        self.next_target = 0
        self.verified_count = 0
        self.window: dict[str, CreativeSourceExecution] = {}
        self.blocked: dict[str, tuple[str, str]] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="creative-graph")
        self.publication: Future[None] | None = None
        self.publishing: tuple[CreativeSourceExecution, ...] = ()

    def advance_once(self) -> CreativeCohortProgress:
        completed: CreativeSourceExecution | None = None
        if self.publication is not None and self.publication.done():
            try:
                self.publication.result()
            except (BackgroundStoragePressure, DBAPIError) as error:
                if not isinstance(
                    error, BackgroundStoragePressure
                ) and not recoverable_database_error_code(error):
                    raise
                # Publication may have committed before the connection failed.
                # Same accepted sources reenter membership/authorization checks;
                # never regenerate reports or count partial verification success.
                for source in self.publishing:
                    source.state = "READY_TO_PUBLISH"
                self.publication, self.publishing = None, ()
                raise
            for source in self.publishing:
                if source.state != "VERIFIED":
                    raise ValueError("CREATIVE_COHORT_PUBLICATION_MISMATCH")
                completed = self.window.pop(source.target.source_id)
                self.verified_count += 1
            self.publication, self.publishing = None, ()
        while (
            not self.stop_requested()
            and len(self.window) < self.window_limit
            and self.next_target < len(self.targets)
        ):
            target = self.targets[self.next_target]
            if target.source_id in self.window:
                raise ValueError("CREATIVE_COHORT_TARGET_REPEATED")
            self.window[target.source_id] = CreativeSourceExecution(target)
            self.next_target += 1
        publishing_ids = {source.target.source_id for source in self.publishing}
        for source_id, source in tuple(self.window.items()):
            if self.stop_requested():
                break
            if source_id not in publishing_ids and source.state != "READY_TO_PUBLISH":
                try:
                    self.owner.advance_report(source)
                except CreativeSourcePreviewDeferred as error:
                    result = error.result
                    if (result.source_id, result.source_revision_id, result.edition) != (
                        source.target.source_id,
                        source.target.source_revision_id,
                        source.target.selected_edition,
                    ) or result.error_code is None:
                        raise ValueError("CREATIVE_PREVIEW_RESULT_IDENTITY_MISMATCH") from error
                    self.blocked[source_id] = (source.target.external_number, result.error_code)
                    del self.window[source_id]
                except CreativeItemContentUnavailable as error:
                    if error.target != source.target or error.selection != source.selection:
                        raise ValueError("CREATIVE_CONTENT_RESULT_IDENTITY_MISMATCH") from error
                    self.blocked[source_id] = (source.target.external_number, error.code)
                    del self.window[source_id]
                except CreativeSourceTerminalFailure as error:
                    # Only the explicit native successor continues past a proven
                    # historical failure. Old drivers still stop; no retry or
                    # successful registration is inferred from this scheduling.
                    if not isinstance(
                        self.owner.scope.continuation, CreativeLearningOfficeContinuation
                    ):
                        raise
                    if error.target != source.target or error.selection != source.selection:
                        raise ValueError("CREATIVE_TERMINAL_RESULT_IDENTITY_MISMATCH") from error
                    self.blocked[source_id] = (source.target.external_number, error.code)
                    del self.window[source_id]
        ready = tuple(
            source
            for source_id, source in self.window.items()
            if source_id not in publishing_ids and source.state == "READY_TO_PUBLISH"
        )
        if (
            self.publication is None
            and not self.stop_requested()
            and ready
            and (len(ready) >= self.batch_size or len(ready) == len(self.window))
        ):
            self.publishing = ready[: self.batch_size]
            self.publication = self.executor.submit(self.owner.publish_sources, self.publishing)
            publishing_ids = {source.target.source_id for source in self.publishing}
        activities = tuple(
            (source.target.external_number, "PUBLISHING" if key in publishing_ids else source.state)
            for key, source in self.window.items()
        )
        state = "VERIFIED" if completed else "PROCESSING"
        if not self.window and self.next_target == len(self.targets):
            state = (
                "BLOCKED_SOURCES"
                if self.blocked
                else "COMPLETED"
                if self.verified_count == len(self.owner.targets)
                else "VERIFIED"
            )
        representative = completed or next(iter(self.window.values()), None)
        progress = self.owner.progress(
            state, representative, self.verified_count, active_sources=activities
        )
        return replace(progress, blocked_sources=tuple(self.blocked.values()))

    def refresh_blocked_source_readiness(self) -> None:
        """Recheck only original held sources; never reset/recreate failed children.

        The caller waits between checks. Completed targets are not replayed and
        accepted reports retain their canonical pointers and verification count.
        """
        if self.window or self.publication is not None or self.next_target != len(self.targets):
            raise ValueError("CREATIVE_COHORT_SOURCE_REFRESH_NOT_QUIESCENT")
        self.targets = tuple(self._targets_by_id[source_id] for source_id in self.blocked)
        self.next_target = 0
        self.blocked.clear()

    def close(self) -> None:
        # Never release the cohort fence while a canonical publication is still
        # committing. Submitted platform jobs survive a graceful owner stop.
        self.executor.shutdown(wait=True, cancel_futures=False)
        if self.publication is not None:
            self.publication.result()
