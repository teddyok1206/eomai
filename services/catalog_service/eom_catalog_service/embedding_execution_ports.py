"""Native encoding ports; installed runtime verification stays in the launch adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingExecutionRuntime,
    IncrementalEmbeddingResult,
)

from eom_catalog_service.inference_transfer_ports import LocalTextEmbeddingBackend


class NativeEmbeddingBackend(LocalTextEmbeddingBackend, Protocol):
    @property
    def execution_runtime(self) -> EmbeddingExecutionRuntime:
        """Report independently verified device/runtime, never echo request claims."""
        ...


@dataclass(frozen=True, slots=True)
class EncodedEmbeddingBatch:
    """One temporary local-output materialization; binary bytes are never DB values."""

    result: IncrementalEmbeddingResult
    vectors: bytes
