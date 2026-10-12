"""Native encoding ports; installed runtime verification stays in the launch adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingNumericalDevice,
    EmbeddingNumericLibraryPin,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingExecutionRuntime,
    IncrementalEmbeddingResult,
)

from eom_catalog_service.inference_transfer_ports import LocalTextEmbeddingBackend


class NativeEmbeddingBackend(LocalTextEmbeddingBackend, Protocol):
    @property
    def batch_size(self) -> int:
        """Exact batch recipe used by this verified backend, not a request override."""
        ...

    @property
    def threads(self) -> int:
        """Actual admitted numerical thread count, independently read back."""
        ...

    @property
    def execution_runtime(self) -> EmbeddingExecutionRuntime:
        """Report independently verified device/runtime, never echo request claims."""
        ...


@dataclass(frozen=True, slots=True)
class InstalledEmbeddingRuntimeObservation:
    """Verified installation evidence, not a worker claim or inferred wheel hash.

    The owner observer checks protected archive receipts/RECORD and physical device/
    driver identity. The backend separately checks imports and numeric read-back.
    """

    python_version: str
    libraries: tuple[EmbeddingNumericLibraryPin, ...]
    device: EmbeddingNumericalDevice
    torch_build_cuda_version: str | None


class InstalledEmbeddingRuntimeObserver(Protocol):
    def observe(self) -> InstalledEmbeddingRuntimeObservation:
        """Observe current protected installation; takes no expected/request descriptor."""
        ...


class CudaEmbeddingOwnership(Protocol):
    def assert_owned(self) -> None:
        """Revalidate a held physical lease and the owner's exact admitted device mapping."""
        ...


@dataclass(frozen=True, slots=True)
class EncodedEmbeddingBatch:
    """One temporary local-output materialization; binary bytes are never DB values."""

    result: IncrementalEmbeddingResult
    vectors: bytes
