"""Root-only read of one original failed/retired invocation, never a unit effect or grant."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from eom_identifiers import canonical_json_bytes
from eom_workflow.embedding_encoding_recovery import RetiredEmbeddingRootFailure
from pydantic import TypeAdapter

from eom_catalog_service.embedding_gpu_batch_launch import (
    GPU_BATCH_TEMPLATE,
    native_embedding_gpu_batch_unit,
)
from eom_catalog_service.embedding_gpu_batch_lifetime import (
    GPU_BATCH_LIFETIME_ROOT,
    EmbeddingGpuBatchRetirement,
)
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.gpu_unit_terminal_observation import (
    gpu_unit_terminal_outcome,
    observe_stopped_gpu_unit,
)


@dataclass(frozen=True, slots=True)
class ResolvedRetiredEmbeddingFailure:
    proof: RetiredEmbeddingRootFailure
    allocation_request_sha256: str


@contextmanager
def read_retired_embedding_failure(
    proof: RetiredEmbeddingRootFailure,
) -> Iterator[ResolvedRetiredEmbeddingFailure]:
    """Keep this window inside the caller's short maintenance transaction.

    Only the exact old unit is observed. An unrelated active image, trainer or
    embedding allocation is allowed and never queried/stopped/acquired here.
    A claimed proof/FAILED DB row alone cannot satisfy the root file/OS checks.
    """
    if os.getresuid() != (0, 0, 0):
        raise ValueError("EMBEDDING_FAILURE_ROOT_OWNER_REQUIRED")
    proof = RetiredEmbeddingRootFailure.model_validate(proof)
    unit = native_embedding_gpu_batch_unit(
        proof.allocation_attempt_id.removeprefix("embeddingallocation_")
    )
    reader = NumericalRuntimeFileSnapshots()
    path = GPU_BATCH_LIFETIME_ROOT / unit / proof.invocation_id / "retirement/result.json"
    raw = reader.read(path, sha256=proof.retirement_sha256, maximum=256 * 1024)
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"event", "observation"}
        or value["event"] != "EMBEDDING_GPU_BATCH_RETIRED_NOT_PUBLISHED"
        or canonical_json_bytes(value) != raw
    ):
        raise ValueError("EMBEDDING_FAILURE_RETIREMENT_INVALID")
    codec = TypeAdapter(EmbeddingGpuBatchRetirement)
    retired = codec.validate_python(value["observation"])
    terminal = retired.original_terminal
    ready = terminal.ready
    if (
        canonical_json_bytes(codec.dump_python(retired, mode="json"))
        != canonical_json_bytes(value["observation"])
        or terminal.original_outcome != "FAILED"
        or gpu_unit_terminal_outcome(terminal.terminal_unit) != "FAILED"
        or terminal.terminal_unit.main_pid != 0
        or terminal.terminal_unit.invocation_id != proof.invocation_id
        or ready.unit.invocation_id != proof.invocation_id
        or ready.readiness.allocation_attempt_id != proof.allocation_attempt_id
        or retired.retired_unit.stored_descriptors != 0
        or retired.retired_unit.invocation_id != proof.invocation_id
        or proof.stored_descriptors != 0
        or proof.original_outcome != "FAILED"
        or datetime.fromisoformat(retired.observed_at_utc) != proof.retired_at
    ):
        raise ValueError("EMBEDDING_FAILURE_RETIREMENT_INVALID")
    stopped = observe_stopped_gpu_unit(
        unit, template=GPU_BATCH_TEMPLATE, invocation=proof.invocation_id
    )
    if stopped.stored_descriptors != 0:
        raise ValueError("EMBEDDING_FAILURE_RETIREMENT_INVALID")
    yield ResolvedRetiredEmbeddingFailure(proof, ready.readiness.allocation_request_sha256)
    reader.assert_unchanged()
    if (
        observe_stopped_gpu_unit(unit, template=GPU_BATCH_TEMPLATE, invocation=proof.invocation_id)
        != stopped
    ):
        raise ValueError("EMBEDDING_FAILURE_RETIREMENT_CHANGED")
