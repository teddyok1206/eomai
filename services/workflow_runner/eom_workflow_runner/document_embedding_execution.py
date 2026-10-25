"""Numerical leaf of the existing encoding use case, not a second reservation owner."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
)
from eom_orchestrator.native_embedding_index_handoff import validate_native_index_original_input
from eom_workflow.local_embedding_encoding_dispatch import (
    SupportedEmbeddingAssociation,
    SupportedEmbeddingIntent,
)
from eom_workflow.local_embedding_request_v2 import SupportedLocalEmbeddingRequest

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction

if TYPE_CHECKING:
    from eom_workflow_runner.local_embedding_encoding_admission import CatalogEncodingOwnerAdmission


class DocumentExecutionState(StrEnum):
    """OS/batch liveness only; never permission, a completion receipt or a retry grant."""

    NOT_STARTED = "NOT_STARTED"
    SUCCEEDED = "SUCCEEDED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class OwnedDocumentEmbedding:
    association: SupportedEmbeddingAssociation
    request: IncrementalEmbeddingInput

    def __post_init__(self) -> None:
        association, request = validate_native_index_original_input(self.association, self.request)
        object.__setattr__(self, "association", association)
        object.__setattr__(self, "request", request)


@dataclass(frozen=True, slots=True)
class DocumentEmbeddingOutput:
    result: IncrementalEmbeddingResult
    workspace: Path


class DocumentEmbeddingExecution(Protocol):
    """Device-specific bounded compute; common application still owns all DB/NAS writes.

    None means preserve the original pending reservations, not CPU fallback. A
    source, permission, hash or partial-output error must propagate. The route is
    selected before creating requests/reservations, never inside this interface.
    """

    @property
    def device(self) -> Literal["CPU", "CUDA"]: ...

    def assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> None: ...

    def observe(self, intent: SupportedEmbeddingIntent) -> DocumentExecutionState: ...

    def execute(
        self,
        work: OwnedDocumentEmbedding,
        *,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> DocumentEmbeddingOutput | None: ...
