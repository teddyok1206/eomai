"""Existing fixed CPU handoff behind the common document numerical port."""

from __future__ import annotations

from typing import Literal

from eom_orchestrator.native_embedding_index_handoff import (
    PreparedNativeIndex,
    mark_native_index_launch_started,
    stage_native_index,
)
from eom_orchestrator.native_embedding_index_systemd import (
    FixedNativeIndexLauncher,
    NativeIndexLaunchError,
)
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import SupportedLocalEmbeddingRequest

from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingOutput,
    DocumentExecutionState,
    OwnedDocumentEmbedding,
)
from eom_workflow_runner.local_embedding_encoding_admission import CatalogEncodingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction


class FixedCpuDocumentEmbeddingExecution:
    def __init__(self, launcher: FixedNativeIndexLauncher) -> None:
        self.launcher = launcher

    @property
    def device(self) -> Literal["CPU"]:
        return "CPU"

    def assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> None:
        if request.space.runtime.device != self.device:
            raise ValueError("LOCAL_EMBEDDING_CPU_SPACE_INVALID")
        self.launcher.assert_current_runtime()

    def observe(self, intent: SupportedEmbeddingIntent) -> DocumentExecutionState:
        units = self.launcher.observe(intent.native_launch_job_id.removeprefix("job_"))
        if len(units) != 2:
            return DocumentExecutionState.UNCERTAIN
        if all(row.fresh for row in units):
            return DocumentExecutionState.NOT_STARTED
        if all(row.succeeded for row in units):
            return DocumentExecutionState.SUCCEEDED
        return DocumentExecutionState.UNCERTAIN

    def execute(
        self,
        work: OwnedDocumentEmbedding,
        *,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> DocumentEmbeddingOutput | None:
        prepared = PreparedNativeIndex(
            work.association.intent.native_launch_job_id.removeprefix("job_"),
            work.association,
            work.request,
        )
        with transaction() as session:
            if source.resolve_launch(session, work.association).owned_input != work.request:
                raise ValueError("LOCAL_EMBEDDING_CPU_INPUT_CHANGED")
            stage_native_index(prepared)
            mark_native_index_launch_started(prepared)
        try:
            result = self.launcher.run(prepared)
        except NativeIndexLaunchError as error:
            if error.code not in {"NATIVE_INDEX_BUSY", "NATIVE_INDEX_UNCERTAIN"}:
                raise
            return None
        return DocumentEmbeddingOutput(result, prepared.workspace)
