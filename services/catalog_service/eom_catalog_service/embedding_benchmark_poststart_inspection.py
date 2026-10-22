"""Root-attested CPU1 timeout proof and fresh owner capture; no compute, SQL or NAS effects."""

from __future__ import annotations

import hashlib
import os
import pwd
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    MAX_POSTSTART_FAILURE_BYTES,
    BenchmarkPoststartObservation,
    BenchmarkPoststartOutputMember,
    BenchmarkPoststartTerminalProof,
    benchmark_poststart_failure_bytes,
    parse_benchmark_poststart_failure,
)
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import BenchmarkFailedControllerPin
from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_workflow.embedding_benchmark_launch_control import (
    MAX_LAUNCH_CONTROL_BYTES,
    BenchmarkLaunchAssociation,
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    parse_benchmark_launch_control_bytes,
    validate_benchmark_control_reply,
)

from eom_catalog_service.embedding_benchmark_launch_workspace import BENCHMARK_OWNER_ROOT
from eom_catalog_service.embedding_benchmark_layout import (
    BENCHMARK_HANDOFF_ROOT,
    benchmark_read_acl,
)
from eom_catalog_service.embedding_benchmark_poststart_os import (
    CapturedBenchmarkPoststartMachine,
    read_root_poststart_retirement,
)

_PROOF_ROOT = Path("/run/eom-incremental-embeddings/benchmark-poststart-recovery")
_ROOT_UID = 0
_ROOT_GID = 0
_ACL_NAMES = frozenset(("system.posix_acl_access", "system.posix_acl_default"))


class BenchmarkPoststartInspectionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = "BENCHMARK_POSTSTART_" + code
        super().__init__(self.code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BenchmarkPoststartInspectionError(code)


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _no_acl(path: Path | int) -> None:
    names = (
        os.listxattr(path) if isinstance(path, int) else os.listxattr(path, follow_symlinks=False)
    )
    _require(not _ACL_NAMES.intersection(names), "ACL_INVALID")


def _directory_acl(path: Path) -> None:
    execution = path.parent if path.name in {"inputs", "outputs"} else path
    if execution.parent == BENCHMARK_HANDOFF_ROOT and re.fullmatch(r"[0-9a-f]{32}", execution.name):
        native = pwd.getpwnam("eom-embedding-index-cpu").pw_uid
        _require(
            set(os.listxattr(path, follow_symlinks=False)) == {"system.posix_acl_access"}
            and os.getxattr(path, "system.posix_acl_access", follow_symlinks=False)
            == benchmark_read_acl(native, "DIRECTORY"),
            "DIRECTORY_ACL_INVALID",
        )
    else:
        _no_acl(path)


@dataclass(frozen=True, slots=True)
class _Member:
    path: Path
    descriptor: int
    parent: int
    epoch: tuple[int, ...]
    ancestors: tuple[tuple[Path, tuple[int, ...]], ...]
    sha256: str
    raw: bytes

    def assert_current(self) -> None:
        for path, expected in self.ancestors:
            _require(_directory_identity(path.lstat()) == expected, "ANCESTOR_CHANGED")
            _directory_acl(path)
        _no_acl(self.descriptor)
        _require(
            self.epoch
            == _epoch(os.fstat(self.descriptor))
            == _epoch(os.stat(self.path.name, dir_fd=self.parent, follow_symlinks=False))
            == _epoch(self.path.lstat()),
            "MEMBER_CHANGED",
        )


def _member(
    stack: ExitStack,
    path: Path,
    *,
    directory_uid: int,
    directory_mode: int,
    uid: int,
    gid: int,
    mode: int,
    maximum: int,
    retain: bool = True,
    allow_empty: bool = False,
    file_gid: int | None = None,
) -> _Member:
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        path.parent, owner=owner, uid=directory_uid, gid=gid, mode=directory_mode
    ) as directory:
        parent = os.dup(directory)
        stack.callback(os.close, parent)
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
        )
        stack.callback(os.close, descriptor)
        value = os.fstat(descriptor)
        _require(
            stat.S_ISREG(value.st_mode)
            and value.st_uid == uid
            and value.st_gid == (gid if file_gid is None else file_gid)
            and stat.S_IMODE(value.st_mode) == mode
            and value.st_nlink == 1
            and (0 if allow_empty else 1) <= value.st_size <= maximum,
            "MEMBER_INVALID",
        )
        ancestors = tuple((p, _directory_identity(p.lstat())) for p in path.parents)
        digest, chunks, count = hashlib.sha256(), [], 0
        while chunk := os.pread(descriptor, min(65536, maximum + 1 - count), count):
            count += len(chunk)
            _require(count <= value.st_size, "MEMBER_CHANGED")
            digest.update(chunk)
            if retain:
                chunks.append(chunk)
        _require(count == value.st_size, "MEMBER_CHANGED")
        result = _Member(
            path,
            descriptor,
            parent,
            _epoch(value),
            ancestors,
            "sha256:" + digest.hexdigest(),
            b"".join(chunks),
        )
        result.assert_current()
    return result


def _selection(request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation) -> None:
    embedding_device_benchmark_bytes(request)
    embedding_device_benchmark_bytes(invocation)
    _require(
        invocation.device == "CPU"
        and invocation.launch_ordinal == 1
        and invocation.runtime == request.cpu
        and invocation.owner_request_sha256 == request.request_sha256
        and invocation.benchmark_id == request.benchmark_id
        and invocation.benchmark_revision_id == request.benchmark_revision_id,
        "SELECTION_INVALID",
    )


@dataclass(frozen=True, slots=True)
class _Inspection:
    request: BenchmarkOwnerRequest
    invocation: BenchmarkWorkerInvocation
    association: BenchmarkLaunchAssociation
    prepared: BenchmarkLaunchPrepared
    completion: BenchmarkLaunchCompleted
    records: tuple[_Member, ...]
    outputs: tuple[BenchmarkPoststartOutputMember, ...]
    terminal: BenchmarkPoststartTerminalProof
    machine: CapturedBenchmarkPoststartMachine
    invocation_epoch: tuple[int, ...]

    def snapshot(self) -> tuple[str, str]:
        for member in self.records:
            member.assert_current()
        invocation_path = BENCHMARK_HANDOFF_ROOT / self.invocation.execution_id / "invocation.json"
        _require(_epoch(invocation_path.lstat()) == self.invocation_epoch, "INVOCATION_CHANGED")
        _no_acl(invocation_path)
        output_root = invocation_path.parent / "outputs"
        _require(
            set(os.listdir(output_root)) == set(benchmark_local_output_members(1)),
            "OUTPUT_MEMBERS_INVALID",
        )
        machine = self.machine.observe()
        controller = dict(machine.controller)
        # Same-source failed controllers are not interchangeable with this original launch.
        _require(
            int(controller["ExecMainStartTimestampMonotonic"]) * 1000
            <= self.completion.started_ns
            < self.completion.completed_ns
            <= int(controller["ExecMainExitTimestampMonotonic"]) * 1000,
            "CONTROLLER_TIME_INVALID",
        )
        value = {
            "owner_recomputed": {
                "files": tuple(
                    (str(member.path), member.epoch, member.sha256) for member in self.records
                ),
                "invocation_metadata": self.invocation_epoch,
                "machine": machine.snapshot_value(),
            },
            # Root-private700 retirement is read by mint only. Owner never claims a reread.
            "root_attested_retirement": {
                "native_invocation_id": self.terminal.native_invocation_id,
                "raw_sha256": self.terminal.retirement_raw_sha256,
            },
        }
        for member in self.records:
            member.assert_current()
        return machine.boot_id, content_sha256(value)


def _capture(
    stack: ExitStack,
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    controller: BenchmarkFailedControllerPin,
    terminal: BenchmarkPoststartTerminalProof,
) -> _Inspection:
    owner = fixed_owner_identity()
    root = BENCHMARK_HANDOFF_ROOT / invocation.execution_id
    associated = _member(
        stack,
        BENCHMARK_OWNER_ROOT / invocation.execution_id / "inputs/association.json",
        directory_uid=owner.owner_uid,
        directory_mode=0o700,
        uid=owner.owner_uid,
        gid=owner.owner_gid,
        mode=0o600,
        maximum=MAX_LAUNCH_CONTROL_BYTES,
    )
    prepared_raw, completed_raw = (
        _member(
            stack,
            root / name,
            directory_uid=_ROOT_UID,
            directory_mode=0o750,
            uid=_ROOT_UID,
            gid=owner.owner_gid,
            mode=0o640,
            maximum=MAX_LAUNCH_CONTROL_BYTES,
        )
        for name in ("root-prepared.json", "root-completion.json")
    )
    association = parse_benchmark_launch_control_bytes(associated.raw)
    prepared = parse_benchmark_launch_control_bytes(prepared_raw.raw)
    completion = parse_benchmark_launch_control_bytes(completed_raw.raw)
    _require(
        isinstance(association, BenchmarkLaunchAssociation)
        and isinstance(prepared, BenchmarkLaunchPrepared)
        and isinstance(completion, BenchmarkLaunchCompleted),
        "CONTROL_KIND_INVALID",
    )
    assert isinstance(association, BenchmarkLaunchAssociation)
    assert isinstance(prepared, BenchmarkLaunchPrepared)
    assert isinstance(completion, BenchmarkLaunchCompleted)
    validate_benchmark_control_reply(association, prepared)
    validate_benchmark_control_reply(association, completion, prepared=prepared)
    request_raw, invocation_raw = (
        embedding_device_benchmark_bytes(v) for v in (request, invocation)
    )
    _require(
        (
            association.job_id,
            association.execution_id,
            association.device,
            association.launch_ordinal,
            association.owner_request_sha256,
            association.invocation_sha256,
            association.request.sha256,
            association.request.byte_count,
            association.invocation.sha256,
            association.invocation.byte_count,
            association.inputs.sha256,
            association.inputs.byte_count,
        )
        == (
            invocation.job_id,
            invocation.execution_id,
            "CPU",
            1,
            request.request_sha256,
            invocation.invocation_sha256,
            sha256_bytes(request_raw),
            len(request_raw),
            sha256_bytes(invocation_raw),
            len(invocation_raw),
            invocation.local_input.sha256,
            invocation.local_input.byte_count,
        ),
        "ASSOCIATION_INVALID",
    )
    _require(
        prepared.controller_release == controller.source_commit
        and completion.original_outcome == "FAILED"
        and completion.cleanup == "CONFIRMED"
        and completion.completed_ns > completion.started_ns,
        "COMPLETION_INVALID",
    )
    native_uid = pwd.getpwnam("eom-embedding-index-cpu").pw_uid
    output_root = root / "outputs"
    names = benchmark_local_output_members(1)
    _require(set(os.listdir(output_root)) == set(names), "OUTPUT_MEMBERS_INVALID")
    total = sum((output_root / name).lstat().st_size for name in names)
    _require(0 < total <= MAX_BENCHMARK_OUTPUT_BYTES, "OUTPUT_SIZE_INVALID")
    output_records = tuple(
        _member(
            stack,
            root / "outputs" / name,
            directory_uid=_ROOT_UID,
            directory_mode=0o750,
            uid=native_uid,
            gid=owner.owner_gid,
            mode=0o640,
            maximum=MAX_BENCHMARK_OUTPUT_BYTES,
            retain=False,
            allow_empty=True,
        )
        for name in benchmark_local_output_members(1)
    )
    _require(
        len({(r.epoch[0], r.epoch[1]) for r in output_records}) == len(output_records),
        "OUTPUT_ALIAS_INVALID",
    )
    outputs = tuple(
        BenchmarkPoststartOutputMember.model_validate(
            {
                "member_name": member.path.name,
                "byte_count": member.epoch[6],
                "raw_sha256": member.sha256,
            }
        )
        for member in output_records
    )
    metadata = (root / "invocation.json").lstat()
    _require(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == _ROOT_UID
        and metadata.st_gid == _ROOT_GID
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1
        and metadata.st_size == len(invocation_raw),
        "INVOCATION_INVALID",
    )
    state = _Inspection(
        request,
        invocation,
        association,
        prepared,
        completion,
        (associated, prepared_raw, completed_raw, *output_records),
        outputs,
        terminal,
        CapturedBenchmarkPoststartMachine(
            controller,
            execution_id=invocation.execution_id,
            native_invocation_id=terminal.native_invocation_id,
            owner_pid=association.owner_pid,
            expires_ns=association.expires_ns,
        ),
        _epoch(metadata),
    )
    state.snapshot()
    return state


def _validate(observation: BenchmarkPoststartObservation, state: _Inspection) -> None:
    boot, digest = state.snapshot()
    completed = state.completion
    _require(
        (
            observation.job_id,
            observation.execution_id,
            observation.request_sha256,
            observation.invocation_sha256,
            observation.invocation_raw_sha256,
            observation.association_sha256,
            observation.prepared_sha256,
            observation.completion_sha256,
            observation.completion_raw_sha256,
            observation.started_ns,
            observation.completed_ns,
            observation.outputs,
            observation.terminal,
            observation.boot_id,
            observation.snapshot_sha256,
        )
        == (
            state.invocation.job_id,
            state.invocation.execution_id,
            state.request.request_sha256,
            state.invocation.invocation_sha256,
            sha256_bytes(embedding_device_benchmark_bytes(state.invocation)),
            state.association.association_sha256,
            state.prepared.prepared_sha256,
            completed.completion_sha256,
            state.records[2].sha256,
            completed.started_ns,
            completed.completed_ns,
            state.outputs,
            state.terminal,
            boot,
            digest,
        ),
        "PROOF_STALE",
    )


def _proof(
    stack: ExitStack, execution: str, expected: str | None
) -> tuple[_Member, BenchmarkPoststartObservation]:
    owner = fixed_owner_identity()
    # Preserve absence as absence before a yielded-directory wrapper normalizes OS errors.
    (_PROOF_ROOT / (execution + ".json")).lstat()
    record = _member(
        stack,
        _PROOF_ROOT / (execution + ".json"),
        directory_uid=_ROOT_UID,
        directory_mode=0o750,
        uid=_ROOT_UID,
        gid=owner.owner_gid,
        mode=0o440,
        maximum=MAX_POSTSTART_FAILURE_BYTES,
    )
    _require(expected is None or expected == record.sha256, "PROOF_HASH_INVALID")
    observation = parse_benchmark_poststart_failure(record.raw)
    _require(isinstance(observation, BenchmarkPoststartObservation), "PROOF_KIND_INVALID")
    assert isinstance(observation, BenchmarkPoststartObservation)
    _require(observation.execution_id == execution, "PROOF_ID_INVALID")
    return record, observation


class CapturedBenchmarkPoststartInspection:
    def __init__(
        self, record: _Member, observation: BenchmarkPoststartObservation, state: _Inspection
    ) -> None:
        self._record, self._observation, self._state, self._active = (
            record,
            observation,
            state,
            True,
        )

    @property
    def observation(self) -> BenchmarkPoststartObservation:
        return self._observation

    def assert_current(self) -> None:
        _require(self._active, "CAPTURE_CLOSED")
        self._record.assert_current()
        _validate(self.observation, self._state)
        self._record.assert_current()


@dataclass(frozen=True, slots=True)
class FixedBenchmarkPoststartInspection:
    execution_id: str
    expected_raw_sha256: str

    def __post_init__(self) -> None:
        _require(
            type(self.execution_id) is str
            and re.fullmatch(r"[0-9a-f]{32}", self.execution_id) is not None,
            "ID_INVALID",
        )
        _require(
            type(self.expected_raw_sha256) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", self.expected_raw_sha256) is not None,
            "PROOF_PIN_INVALID",
        )

    @contextmanager
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> Iterator[CapturedBenchmarkPoststartInspection]:
        _selection(request, invocation)
        _require(invocation.execution_id == self.execution_id, "PROOF_ID_INVALID")
        owner = fixed_owner_identity()
        _require(
            (os.getresuid(), os.getresgid())
            in (
                ((_ROOT_UID,) * 3, (_ROOT_GID,) * 3),
                ((owner.owner_uid,) * 3, (owner.owner_gid,) * 3),
            ),
            "INSPECTOR_INVALID",
        )
        try:
            with ExitStack() as stack:
                record, observation = _proof(stack, self.execution_id, self.expected_raw_sha256)
                state = _capture(
                    stack, request, invocation, observation.controller, observation.terminal
                )
                captured = CapturedBenchmarkPoststartInspection(record, observation, state)
                captured.assert_current()
                try:
                    yield captured
                finally:
                    # The application owns final checks inside its transaction, never after commit.
                    captured._active = False
        except (OSError, CpuHandoffError):
            raise BenchmarkPoststartInspectionError("PROOF_UNAVAILABLE") from None


@dataclass(frozen=True, slots=True)
class MintedBenchmarkPoststartProof:
    observation: BenchmarkPoststartObservation
    raw_sha256: str
    created: bool


def mint_benchmark_poststart_observation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    *,
    controller: BenchmarkFailedControllerPin,
) -> MintedBenchmarkPoststartProof:
    """Root-only proof publication; preserve original partial files and all history."""
    _require(
        os.getresuid() == (_ROOT_UID,) * 3 and os.getresgid() == (_ROOT_GID,) * 3, "ROOT_REQUIRED"
    )
    _selection(request, invocation)
    controller = BenchmarkFailedControllerPin.model_validate(controller)
    owner = fixed_owner_identity()
    try:
        with ExitStack() as stack:
            local = _member(
                stack,
                BENCHMARK_HANDOFF_ROOT / invocation.execution_id / "invocation.json",
                directory_uid=_ROOT_UID,
                directory_mode=0o750,
                uid=_ROOT_UID,
                gid=owner.owner_gid,
                file_gid=_ROOT_GID,
                mode=0o600,
                maximum=MAX_LAUNCH_CONTROL_BYTES,
            )
            _require(
                local.raw == embedding_device_benchmark_bytes(invocation), "INVOCATION_INVALID"
            )
            retired = read_root_poststart_retirement(request, invocation)
            service = "eom-embedding-benchmark-cpu@" + invocation.execution_id
            terminal = BenchmarkPoststartTerminalProof(
                native_service=service + ".service",
                native_socket=service + ".socket",
                native_invocation_id=retired.native_invocation_id,
                retirement_raw_sha256=retired.raw_sha256,
                main_pid=0,
                control_pid=0,
                descriptor_store_count=0,
                cgroup_empty=True,
                socket_inactive=True,
                retirement="CONFIRMED",
            )
            state = _capture(stack, request, invocation, controller, terminal)
            original = retired.retirement.original_terminal
            _require(
                state.completion.started_ns
                <= original.status.exec_main_started_monotonic * 1000
                <= original.exited_monotonic * 1000
                <= state.completion.completed_ns,
                "RETIREMENT_TIME_INVALID",
            )
            try:
                proof, existing = _proof(stack, invocation.execution_id, None)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                _require(existing.controller == controller, "PROOF_CONFLICT")
                _validate(existing, state)
                retired.assert_current()
                local.assert_current()
                proof.assert_current()
                return MintedBenchmarkPoststartProof(existing, proof.sha256, False)
            boot, snapshot = state.snapshot()
            completed = state.completion
            body = dict(
                schema_version="embedding-benchmark-poststart-failure/1.0",
                kind="ROOT_OBSERVATION",
                job_id=invocation.job_id,
                execution_id=invocation.execution_id,
                request_sha256=request.request_sha256,
                invocation_sha256=invocation.invocation_sha256,
                device="CPU",
                launch_ordinal=1,
                association_sha256=state.association.association_sha256,
                prepared_sha256=state.prepared.prepared_sha256,
                completion_sha256=completed.completion_sha256,
                completion_raw_sha256=state.records[2].sha256,
                invocation_raw_sha256=sha256_bytes(embedding_device_benchmark_bytes(invocation)),
                original_outcome="FAILED",
                cleanup="CONFIRMED",
                started_ns=completed.started_ns,
                completed_ns=completed.completed_ns,
                controller=controller.model_dump(mode="json"),
                terminal=terminal.model_dump(mode="json"),
                outputs=[member.model_dump(mode="json") for member in state.outputs],
                boot_id=boot,
                snapshot_sha256=snapshot,
                observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            observation = BenchmarkPoststartObservation.model_validate(
                body | {"observation_sha256": content_sha256(body)}
            )
            raw = benchmark_poststart_failure_bytes(observation)
            retired.assert_current()
            local.assert_current()
            _validate(observation, state)
            with protected_cpu_handoff_directory(
                _PROOF_ROOT, owner=owner, uid=_ROOT_UID, gid=owner.owner_gid, mode=0o750
            ) as directory:
                _no_acl(directory)
                try:
                    descriptor = os.open(
                        invocation.execution_id + ".json",
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                        0o600,
                        dir_fd=directory,
                    )
                except FileExistsError:
                    proof, existing = _proof(stack, invocation.execution_id, None)
                    _require(existing.controller == controller, "PROOF_CONFLICT")
                    _validate(existing, state)
                    retired.assert_current()
                    local.assert_current()
                    proof.assert_current()
                    return MintedBenchmarkPoststartProof(existing, proof.sha256, False)
                try:
                    os.fchown(descriptor, _ROOT_UID, owner.owner_gid)
                    os.fchmod(descriptor, 0o440)
                    remaining = memoryview(raw)
                    while remaining:
                        count = os.write(descriptor, remaining)
                        _require(0 < count <= len(remaining), "PROOF_WRITE_FAILED")
                        remaining = remaining[count:]
                    os.fsync(descriptor)
                    _require(os.pread(descriptor, len(raw) + 1, 0) == raw, "PROOF_WRITE_FAILED")
                    _no_acl(descriptor)
                    os.fsync(directory)
                finally:
                    os.close(descriptor)
            proof, existing = _proof(stack, invocation.execution_id, sha256_bytes(raw))
            _validate(existing, state)
            retired.assert_current()
            local.assert_current()
            proof.assert_current()
            return MintedBenchmarkPoststartProof(existing, proof.sha256, True)
    except (OSError, CpuHandoffError):
        raise BenchmarkPoststartInspectionError("MINT_UNAVAILABLE") from None
