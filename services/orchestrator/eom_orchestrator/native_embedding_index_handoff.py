"""Fixed native INDEX staging and three-file root handoff; no source or launch authority."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    IncrementalEmbeddingInput,
    IncrementalEmbeddingResult,
    parse_incremental_embedding_input,
    parse_incremental_embedding_result,
    validate_incremental_embedding_result,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.local_embedding_encoding_job import (
    LocalEmbeddingLaunchAssociation,
    parse_embedding_encoding_job_message,
)

from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    create_native_cpu_descriptor_handoff,
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
    write_protected_cpu_owner_member,
)

OWNER_ROOT = Path("/var/lib/eom-workflow-runner/incremental-embeddings/index")
RUNTIME_ROOT = Path("/run/eom-embedding-native-index")
MAX_BINARY_BYTES = 16 * 1024**2
_EXECUTION = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)


class NativeIndexHandoffError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_native_index_execution_id(value: str) -> str:
    if type(value) is not str or _EXECUTION.fullmatch(value) is None:
        raise NativeIndexHandoffError("NATIVE_INDEX_EXECUTION_ID_INVALID")
    return value


def _canonical_value(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise NativeIndexHandoffError("NATIVE_INDEX_CANONICAL_INPUT_INVALID")
    return value


def validate_native_index_original_input(
    association: LocalEmbeddingLaunchAssociation, request: IncrementalEmbeddingInput
) -> tuple[LocalEmbeddingLaunchAssociation, IncrementalEmbeddingInput]:
    """Revalidate the exact original association/input, without choosing a device."""
    association_value = parse_embedding_encoding_job_message(
        raw_similarity_contract_value(association)
    )
    request = parse_incremental_embedding_input(raw_similarity_contract_value(request))
    if not isinstance(association_value, LocalEmbeddingLaunchAssociation):
        raise NativeIndexHandoffError("NATIVE_INDEX_ASSOCIATION_INVALID")
    association = association_value
    if (
        request.batch_size != 4
        or request.threads != 4
        or request.job_id != association.intent.native_launch_job_id
        or request.space != association.owned_jobs[0].request.space
        or tuple(row.encoding for row in request.rows)
        != tuple(job.request.encoding for job in association.owned_jobs)
        or request.request_sha256 != association.owned_input_request_sha256
        or request.input_set_sha256 != association.owned_input_set_sha256
        or sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
        != association.owned_input.sha256
    ):
        raise NativeIndexHandoffError("NATIVE_INDEX_ASSOCIATION_INPUT_MISMATCH")
    return association, request


def _checked_batch(
    association: LocalEmbeddingLaunchAssociation, request: IncrementalEmbeddingInput
) -> tuple[LocalEmbeddingLaunchAssociation, IncrementalEmbeddingInput]:
    association, request = validate_native_index_original_input(association, request)
    if request.space.runtime.device != "CPU":
        raise NativeIndexHandoffError("NATIVE_INDEX_ASSOCIATION_INPUT_MISMATCH")
    return association, request


@dataclass(frozen=True, slots=True)
class PreparedNativeIndex:
    """Explicit local materialization, not source permission or a launch grant."""

    execution_id: str
    association: LocalEmbeddingLaunchAssociation
    request: IncrementalEmbeddingInput

    def __post_init__(self) -> None:
        validate_native_index_execution_id(self.execution_id)
        association, request = _checked_batch(self.association, self.request)
        object.__setattr__(self, "association", association)
        object.__setattr__(self, "request", request)

    @property
    def workspace(self) -> Path:
        return OWNER_ROOT / self.execution_id


def _owner() -> CpuHandoffIdentity:
    owner = fixed_owner_identity()
    if os.geteuid() != owner.owner_uid:
        raise NativeIndexHandoffError("NATIVE_INDEX_OWNER_REQUIRED")
    return owner


def _write_owner_member(
    directory: int, name: str, payload: bytes, owner: CpuHandoffIdentity
) -> None:
    try:
        write_protected_cpu_owner_member(directory, name, payload, owner=owner)
    except CpuHandoffError as error:
        raise NativeIndexHandoffError(error.code.replace("NATIVE_CPU_", "NATIVE_INDEX_")) from None


def ensure_native_index_owner_workspace(execution_id: str) -> Path:
    """Durable owner-local workspace; canonical bytes still belong to Artifact storage."""
    execution_id = validate_native_index_execution_id(execution_id)
    return ensure_protected_cpu_owner_workspace(OWNER_ROOT, execution_id, owner=_owner())


def stage_native_index(prepared: PreparedNativeIndex) -> None:
    prepared = PreparedNativeIndex(prepared.execution_id, prepared.association, prepared.request)
    owner = _owner()
    ensure_native_index_owner_workspace(prepared.execution_id)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(
            directory,
            "input.json",
            canonical_json_bytes(prepared.request.model_dump(mode="json")),
            owner,
        )
        _write_owner_member(
            directory,
            "association.json",
            canonical_json_bytes(prepared.association.model_dump(mode="json")),
            owner,
        )


def _read_prepared(execution_id: str, owner: CpuHandoffIdentity) -> PreparedNativeIndex:
    execution_id = validate_native_index_execution_id(execution_id)
    with protected_cpu_handoff_directory(
        OWNER_ROOT / execution_id, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        request = parse_incremental_embedding_input(
            _canonical_value(
                read_protected_cpu_handoff_member(
                    directory, "input.json", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
                )
            )
        )
        association = parse_embedding_encoding_job_message(
            _canonical_value(
                read_protected_cpu_handoff_member(
                    directory,
                    "association.json",
                    uid=owner.owner_uid,
                    gid=owner.owner_gid,
                    mode=0o600,
                )
            )
        )
        if not isinstance(association, LocalEmbeddingLaunchAssociation):
            raise NativeIndexHandoffError("NATIVE_INDEX_ASSOCIATION_INVALID")
    return PreparedNativeIndex(execution_id, association, request)


def mark_native_index_launch_started(prepared: PreparedNativeIndex) -> None:
    """Caller must first bind the launch and commit its fresh command/source fence."""
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativeIndexHandoffError("NATIVE_INDEX_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(
            directory,
            ".launch-started",
            prepared.association.association_sha256.encode("ascii"),
            owner,
        )


def prepare_native_index_handoff(execution_id: str) -> None:
    """Root prepare checks trusted staging provenance, never a DTO-supplied actor."""
    if os.geteuid() != 0:
        raise NativeIndexHandoffError("NATIVE_INDEX_ROOT_REQUIRED")
    owner = fixed_owner_identity()
    prepared = _read_prepared(execution_id, owner)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        marker = read_protected_cpu_handoff_member(
            directory, ".launch-started", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
        if marker != prepared.association.association_sha256.encode("ascii"):
            raise NativeIndexHandoffError("NATIVE_INDEX_LAUNCH_MARKER_INVALID")
    try:
        create_native_cpu_descriptor_handoff(
            RUNTIME_ROOT,
            prepared.execution_id,
            canonical_json_bytes(prepared.request.model_dump(mode="json")),
            owner=owner,
        )
    except CpuHandoffError as error:
        raise NativeIndexHandoffError(error.code.replace("NATIVE_CPU_", "NATIVE_INDEX_")) from None


def materialize_native_index_output(prepared: PreparedNativeIndex) -> IncrementalEmbeddingResult:
    """Call only after exact-unit termination; validate before owner Artifact publication."""
    owner = _owner()
    if _read_prepared(prepared.execution_id, owner) != prepared:
        raise NativeIndexHandoffError("NATIVE_INDEX_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        RUNTIME_ROOT / prepared.execution_id, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
    ) as directory:
        result_raw = read_protected_cpu_handoff_member(
            directory, "result.json", uid=0, gid=owner.owner_gid, mode=0o640
        )
        vectors = read_protected_cpu_handoff_member(
            directory,
            "vectors.f32",
            uid=0,
            gid=owner.owner_gid,
            mode=0o640,
            maximum_bytes=MAX_BINARY_BYTES,
        )
    if len(result_raw) > MAX_EMBEDDING_INPUT_BYTES or len(vectors) > MAX_BINARY_BYTES:
        raise NativeIndexHandoffError("NATIVE_INDEX_OUTPUT_TOO_LARGE")
    result = parse_incremental_embedding_result(_canonical_value(result_raw))
    validate_incremental_embedding_result(prepared.request, result)
    read_unit_vectors(
        vectors,
        dimension=result.shard.dimension,
        row_count=result.shard.row_count,
        expected_sha256=result.shard.binary.sha256,
    )
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(directory, "vectors.f32", vectors, owner)
        _write_owner_member(directory, "result.json", result_raw, owner)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id")
    arguments = parser.parse_args()
    try:
        prepare_native_index_handoff(arguments.execution_id)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
