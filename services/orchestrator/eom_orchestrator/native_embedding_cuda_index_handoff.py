"""Original CUDA INDEX input staging and root descriptors, never completion authority."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from eom_catalog_contracts.embedding_native_cuda_index_owner_binding import (
    MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES,
    NativeCudaIndexOwnerBinding,
    native_cuda_index_owner_binding_bytes,
    parse_native_cuda_index_owner_binding,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
)
from eom_identifiers import canonical_json_bytes, content_sha256
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


def _read_owner_process_member(
    pid: int, name: Literal["stat", "status"], owner: CpuHandoffIdentity
) -> bytes:
    if type(pid) is not int or not 0 < pid <= 2147483647 or name not in {"stat", "status"}:
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")
    maximum = 65536 if name == "stat" else 128 * 1024
    with protected_cpu_handoff_directory(
        Path("/proc") / str(pid), owner=owner, uid=owner.owner_uid, mode=0o555
    ) as directory:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            initial = os.fstat(descriptor)
            if (
                not stat.S_ISREG(initial.st_mode)
                or initial.st_uid != owner.owner_uid
                or initial.st_nlink != 1
                or initial.st_mode & 0o6022
            ):
                raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")
            chunks: list[bytes] = []
            count = 0
            while chunk := os.read(descriptor, min(65536, maximum + 1 - count)):
                count += len(chunk)
                if count > maximum:
                    raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")
                chunks.append(chunk)
            if count == 0 or any(
                (
                    value.st_dev,
                    value.st_ino,
                    value.st_uid,
                    value.st_gid,
                    value.st_mode,
                    value.st_nlink,
                )
                != (
                    initial.st_dev,
                    initial.st_ino,
                    initial.st_uid,
                    initial.st_gid,
                    initial.st_mode,
                    initial.st_nlink,
                )
                for value in (
                    os.fstat(descriptor),
                    os.stat(name, dir_fd=directory, follow_symlinks=False),
                )
            ):
                raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")
            return b"".join(chunks)
        finally:
            os.close(descriptor)


def _owner_start_ticks(pid: int, owner: CpuHandoffIdentity) -> int:
    def read(name: Literal["stat", "status"]) -> bytes:
        try:
            return _read_owner_process_member(pid, name, owner)
        except (OSError, CpuHandoffError):
            raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED") from None

    def parse(raw: bytes) -> int:
        # A tiny Linux stat projection stays in this infrastructure adapter instead
        # of creating an Orchestrator -> Catalog infrastructure dependency.
        text = raw.decode("ascii", errors="strict")
        _comm, separator, tail = text.rpartition(") ")
        fields = tail.split()
        if (
            not text.startswith(f"{pid} (")
            or not separator
            or len(fields) < 20
            or fields[0] not in {"R", "S", "D", "I"}
            or re.fullmatch(r"[0-9]{1,20}", fields[19]) is None
            or not 0 < int(fields[19]) <= 2**64 - 1
        ):
            raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")
        return int(fields[19])

    def born() -> int:
        return parse(read("stat"))

    first = born()
    raw = read("status")
    fields: dict[bytes, tuple[bytes, ...]] = {}
    for line in raw.splitlines():
        name, separator, value = line.partition(b":")
        if name in {b"Uid", b"Gid"}:
            if not separator or name in fields:
                raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")
            fields[name] = tuple(value.split())
    if (
        fields
        != {
            b"Uid": (str(owner.owner_uid).encode(),) * 4,
            b"Gid": (str(owner.owner_gid).encode(),) * 4,
        }
        or first != born()
    ):
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")
    return first


def require_native_cuda_index_owner_current(binding: NativeCudaIndexOwnerBinding) -> None:
    """Fresh kernel UID/GID/birth check only; the caller first reads protected linkage."""
    binding = NativeCudaIndexOwnerBinding.model_validate(binding)
    owner = fixed_owner_identity()
    if os.geteuid() not in (0, owner.owner_uid):
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_OR_ROOT_REQUIRED")
    if _owner_start_ticks(binding.owner_pid, owner) != binding.owner_start_ticks:
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_CHANGED")


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


def read_native_cuda_index_owner_binding(execution_id: str) -> NativeCudaIndexOwnerBinding:
    """Protected original linkage, still readable after owner death for cleanup."""
    prepared = read_prepared_native_cuda_index(execution_id)
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        binding = parse_native_cuda_index_owner_binding(
            read_protected_cpu_handoff_member(
                directory,
                "owner-binding.json",
                uid=owner.owner_uid,
                gid=owner.owner_gid,
                mode=0o600,
                maximum_bytes=MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES,
            )
        )
        marker = read_protected_cpu_handoff_member(
            directory, ".launch-started", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
    if (
        binding.execution_id != prepared.execution_id
        or binding.launch_association_sha256 != prepared.association.association_sha256
        or marker != prepared.association.association_sha256.encode("ascii")
    ):
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_OWNER_BINDING_MISMATCH")
    return binding


def mark_native_cuda_index_launch_started(prepared: PreparedNativeCudaIndex) -> None:
    """Caller first binds the real launch and commits its current command/source fence."""
    prepared = PreparedNativeCudaIndex(
        prepared.execution_id, prepared.association, prepared.request
    )
    owner = _owner()
    if read_prepared_native_cuda_index(prepared.execution_id) != prepared:
        raise NativeCudaIndexHandoffError("NATIVE_CUDA_INDEX_STAGED_INPUT_CHANGED")
    pid = os.getpid()
    body = {
        "schema_version": "embedding-native-cuda-index-owner-binding/1.0",
        "execution_id": prepared.execution_id,
        "launch_association_sha256": prepared.association.association_sha256,
        "owner_pid": pid,
        "owner_start_ticks": _owner_start_ticks(pid, owner),
    }
    binding = NativeCudaIndexOwnerBinding.model_validate(
        body | {"binding_sha256": content_sha256(body)}
    )
    with protected_cpu_handoff_directory(
        prepared.workspace, owner=owner, uid=owner.owner_uid, gid=owner.owner_gid, mode=0o700
    ) as directory:
        _write_owner_member(
            directory, "owner-binding.json", native_cuda_index_owner_binding_bytes(binding), owner
        )
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
    binding = read_native_cuda_index_owner_binding(execution_id)
    require_native_cuda_index_owner_current(binding)
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
