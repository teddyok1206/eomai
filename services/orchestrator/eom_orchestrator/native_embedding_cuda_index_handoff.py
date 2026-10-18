"""Original CUDA INDEX input staging and root descriptors, never completion authority."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
)
from eom_identifiers import canonical_json_bytes
from eom_workflow.local_embedding_encoding_job import (
    LocalEmbeddingLaunchAssociation,
    parse_embedding_encoding_job_message,
)

from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    create_native_cpu_descriptor_handoff,
    create_protected_cpu_handoff_member,
    ensure_protected_cpu_owner_workspace,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
    write_protected_cpu_owner_member,
)
from eom_orchestrator.native_embedding_index_handoff import (
    OWNER_ROOT,
    validate_native_index_execution_id,
    validate_native_index_original_input,
)

RUNTIME_ROOT = Path("/run/eom-native-embedding-cuda-index")


class NativeCudaIndexHandoffError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PreparedNativeCudaIndex:
    """Validated original local input; not source permission, ACK or a launch grant."""

    execution_id: str
    association: LocalEmbeddingLaunchAssociation
    request: IncrementalEmbeddingInput

    def __post_init__(self) -> None:
        validate_native_index_execution_id(self.execution_id)
        association, request = validate_native_index_original_input(self.association, self.request)
        if request.space.runtime.device != "CUDA":
            raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_DEVICE_INVALID")
        object.__setattr__(self, "association", association)
        object.__setattr__(self, "request", request)

    @property
    def workspace(self) -> Path:
        return OWNER_ROOT / self.execution_id


def _owner() -> CpuHandoffIdentity:
    owner = fixed_owner_identity()
    if os.geteuid() != owner.owner_uid:
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_REQUIRED")
    return owner


def _write_owner_member(
    directory: int, name: str, payload: bytes, owner: CpuHandoffIdentity
) -> None:
    try:
        write_protected_cpu_owner_member(directory, name, payload, owner=owner)
    except CpuHandoffError as error:
        raise NativeCudaIndexHandoffError(
            error.code.replace("NATIVE_CPU_", "NATIVE_CUDA_INDEX_")
        ) from None


def _canonical_value(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_CANONICAL_INPUT_INVALID")
    return value


def stage_native_cuda_index(prepared: PreparedNativeCudaIndex) -> None:
    """Materialize only the existing canonical owner input/association, exactly once."""
    prepared = PreparedNativeCudaIndex(
        prepared.execution_id, prepared.association, prepared.request
    )
    owner = _owner()
    ensure_protected_cpu_owner_workspace(OWNER_ROOT, prepared.execution_id, owner=owner)
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


def read_prepared_native_cuda_index(execution_id: str) -> PreparedNativeCudaIndex:
    """Read one fixed owner workspace for owner/root linkage checks, never latest."""
    execution_id = validate_native_index_execution_id(execution_id)
    owner = fixed_owner_identity()
    if os.geteuid() not in (0, owner.owner_uid):
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_OR_ROOT_REQUIRED")
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
            raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_ASSOCIATION_INVALID")
    return PreparedNativeCudaIndex(execution_id, association, request)


def mark_native_cuda_index_launch_started(prepared: PreparedNativeCudaIndex) -> None:
    """Caller first binds the real launch and commits its current command/source fence."""
    prepared = PreparedNativeCudaIndex(
        prepared.execution_id, prepared.association, prepared.request
    )
    owner = _owner()
    if read_prepared_native_cuda_index(prepared.execution_id) != prepared:
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_STAGED_INPUT_CHANGED")
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(
            directory,
            ".launch-started",
            prepared.association.association_sha256.encode("ascii"),
            owner,
        )


def prepare_native_cuda_index_handoff(execution_id: str) -> None:
    """Root-only exclusive runtime boundary; this does not dispatch or accept READY."""
    if os.geteuid() != 0:
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_ROOT_REQUIRED")
    owner = fixed_owner_identity()
    prepared = read_prepared_native_cuda_index(execution_id)
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        marker = read_protected_cpu_handoff_member(
            directory, ".launch-started", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
        if marker != prepared.association.association_sha256.encode("ascii"):
            raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_LAUNCH_MARKER_INVALID")
    try:
        # This public primitive is filesystem-only: its three descriptors contain
        # no CPU runtime admission. CUDA adds READY without changing those files.
        create_native_cpu_descriptor_handoff(
            RUNTIME_ROOT,
            prepared.execution_id,
            canonical_json_bytes(prepared.request.model_dump(mode="json")),
            owner=owner,
        )
        with protected_cpu_handoff_directory(
            RUNTIME_ROOT / prepared.execution_id,
            owner=owner,
            uid=0,
            gid=owner.owner_gid,
            mode=0o750,
        ) as directory:
            create_protected_cpu_handoff_member(
                directory, "ready.json", b"", owner_gid=owner.owner_gid, mode=0o640
            )
            os.fsync(directory)
    except CpuHandoffError as error:
        raise NativeCudaIndexHandoffError(
            error.code.replace("NATIVE_CPU_", "NATIVE_CUDA_INDEX_")
        ) from None
