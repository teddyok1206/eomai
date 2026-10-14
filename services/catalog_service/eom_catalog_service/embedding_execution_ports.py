"""Native encoding ports; installed runtime verification stays in the launch adapter."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal, Protocol

from eom_catalog_contracts.embedding_reference_query import EmbeddingReferenceQueryResult
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingNumericalDevice,
    EmbeddingNumericLibraryPin,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingExecutionRuntime,
    IncrementalEmbeddingResult,
)

from eom_catalog_service.inference_transfer_ports import LocalTextEmbeddingBackend


class BenchmarkHostObservationError(ValueError):
    """Stable host-observation failure; never permission or evidence of safe cleanup."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BenchmarkHostOomObserver(Protocol):
    def observe_delta(self) -> int:
        """Actual own-unit memory.events oom delta from a pre-entry baseline.

        Capture/membership/epochs are mandatory. Kill events must not be double-counted
        or hidden when the local-limit oom counter stays zero. No default is supplied.
        """
        ...


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


def _observation_hash(value: str) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@dataclass(frozen=True, slots=True)
class NativeTokenRowObservation:
    """Actual padded CPU token read-back; never a tensor or source authority."""

    input_text_sha256: str
    input_ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    token_type_ids: tuple[int, ...] | None
    unpadded_token_count: int
    token_ids_sha256: str

    def __post_init__(self) -> None:
        if (
            not _observation_hash(self.input_text_sha256)
            or not _observation_hash(self.token_ids_sha256)
            or type(self.input_ids) is not tuple
            or not 1 <= len(self.input_ids) <= 2048
            or type(self.attention_mask) is not tuple
            or len(self.attention_mask) != len(self.input_ids)
            or any(type(value) is not int or not 0 <= value < 2**31 for value in self.input_ids)
            or any(type(value) is not int or value not in (0, 1) for value in self.attention_mask)
            or type(self.unpadded_token_count) is not int
            or not 1 <= self.unpadded_token_count <= 2048
            or sum(self.attention_mask) != self.unpadded_token_count
            or (
                self.token_type_ids is not None
                and (
                    type(self.token_type_ids) is not tuple
                    or len(self.token_type_ids) != len(self.input_ids)
                    or any(
                        type(value) is not int or not 0 <= value < 2**31
                        for value in self.token_type_ids
                    )
                )
            )
        ):
            raise ValueError("native token row observation invalid")


@dataclass(frozen=True, slots=True)
class NativeTokenBatchObservation:
    purpose: Literal["QUERY", "DOCUMENT"]
    pad_token_id: int
    padding_side: Literal["left", "right"]
    rows: tuple[NativeTokenRowObservation, ...]

    def __post_init__(self) -> None:
        if (
            type(self.purpose) is not str
            or self.purpose not in ("QUERY", "DOCUMENT")
            or type(self.pad_token_id) is not int
            or not 0 <= self.pad_token_id < 2**31
            or type(self.padding_side) is not str
            or self.padding_side not in ("left", "right")
            or type(self.rows) is not tuple
            or not 1 <= len(self.rows) <= 4
            or any(type(row) is not NativeTokenRowObservation for row in self.rows)
        ):
            raise ValueError("native token batch observation invalid")
        for row in self.rows:
            row.__post_init__()
        if len({row.token_type_ids is None for row in self.rows}) != 1:
            raise ValueError("native token batch mixes token-type observations")
        maximum = max(row.unpadded_token_count for row in self.rows)
        for row in self.rows:
            padding = maximum - row.unpadded_token_count
            mask = (0,) * padding + (1,) * row.unpadded_token_count
            if self.padding_side == "right":
                mask = tuple(reversed(mask))
            if (
                len(row.input_ids) != maximum
                or row.attention_mask != mask
                or any(
                    not used
                    and (
                        token != self.pad_token_id
                        or (row.token_type_ids is not None and row.token_type_ids[index] != 0)
                    )
                    for index, (token, used) in enumerate(zip(row.input_ids, mask, strict=True))
                )
            ):
                raise ValueError("native token padding observation invalid")


@dataclass(frozen=True, slots=True)
class NativeObservedEncoding:
    vectors: tuple[tuple[float, ...], ...]
    batches: tuple[NativeTokenBatchObservation, ...]

    def __post_init__(self) -> None:
        if (
            type(self.vectors) is not tuple
            or not 1 <= len(self.vectors) <= 18
            or type(self.batches) is not tuple
            or not 1 <= len(self.batches) <= 5
            or any(type(batch) is not NativeTokenBatchObservation for batch in self.batches)
        ):
            raise ValueError("native observed encoding invalid")
        for batch in self.batches:
            batch.__post_init__()
        if (
            sum(len(batch.rows) for batch in self.batches) != len(self.vectors)
            or len({batch.purpose for batch in self.batches}) != 1
            or any(len(batch.rows) != 4 for batch in self.batches[:-1])
            or any(
                type(row) is not tuple
                or not 1 <= len(row) <= 4096
                or any(type(value) is not float or not isfinite(value) for value in row)
                for row in self.vectors
            )
            or len({len(row) for row in self.vectors}) != 1
        ):
            raise ValueError("native observed encoding invalid")


@dataclass(frozen=True, slots=True)
class NativeTokenRejection:
    """EMPTY has no tokenizer evidence; OVERFLOW exports hashes/counts, never long arrays."""

    reason: Literal["EMPTY", "OVERFLOW"]
    input_text_sha256: tuple[str, ...]
    token_counts: tuple[int, ...] | None
    token_ids_sha256: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if (
            type(self.reason) is not str
            or self.reason not in ("EMPTY", "OVERFLOW")
            or type(self.input_text_sha256) is not tuple
            or not 1 <= len(self.input_text_sha256) <= 4
            or any(not _observation_hash(value) for value in self.input_text_sha256)
        ):
            raise ValueError("native token rejection invalid")
        if self.reason == "EMPTY":
            if self.token_counts is not None or self.token_ids_sha256 is not None:
                raise ValueError("empty rejection cannot claim tokenizer observations")
        elif (
            type(self.token_counts) is not tuple
            or type(self.token_ids_sha256) is not tuple
            or len(self.token_counts) != len(self.input_text_sha256)
            or len(self.token_ids_sha256) != len(self.input_text_sha256)
            or any(type(count) is not int or not 1 <= count <= 4096 for count in self.token_counts)
            or not any(count > 2048 for count in self.token_counts)
            or any(not _observation_hash(value) for value in self.token_ids_sha256)
        ):
            raise ValueError("overflow rejection observation invalid")


@dataclass(frozen=True, slots=True)
class NativeAllocatorPeaks:
    """Cumulative local allocator peaks, not whole-process/device observations."""

    allocated_bytes: int | None
    reserved_bytes: int | None

    def __post_init__(self) -> None:
        if (self.allocated_bytes is None) != (self.reserved_bytes is None) or any(
            value is not None and (type(value) is not int or not 0 <= value <= 64 * 1024**3)
            for value in (self.allocated_bytes, self.reserved_bytes)
        ):
            raise ValueError("native allocator observation invalid")


class BenchmarkNativeEmbeddingBackend(NativeEmbeddingBackend, Protocol):
    def encode_observed(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> NativeObservedEncoding:
        """Run the same encoder with bounded actual-used token read-back."""
        ...

    def synchronize(self) -> None:
        """Fence the current admitted device, with runtime/ownership checks around it."""
        ...

    def allocator_peaks(self) -> NativeAllocatorPeaks:
        """Read cumulative allocator peaks without resetting constructor/load maxima."""
        ...

    def cuda_oom_count(self) -> int | None:
        """Actual cumulative device0 allocator num_ooms; CPU has no CUDA observation."""
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


@dataclass(frozen=True, slots=True)
class EncodedReferenceQueryBatch:
    """Temporary genuine QUERY output, not a corpus binding or native admission receipt."""

    result: EmbeddingReferenceQueryResult
    vectors: bytes
