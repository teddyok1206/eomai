"""Fixed protected CPU1 failure proof; no source grant, SQL, dispatch, cleanup or NAS."""

from __future__ import annotations

import os
import pwd
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    MAX_PRELAUNCH_FAILURE_BYTES,
    BenchmarkFailedControllerPin,
    BenchmarkPrelaunchObservation,
    benchmark_prelaunch_failure_bytes,
    parse_benchmark_prelaunch_failure,
)
from eom_catalog_contracts.embedding_device_benchmark import (
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
    read_protected_cpu_handoff_member,
)
from eom_workflow.embedding_benchmark_launch_control import (
    MAX_LAUNCH_CONTROL_BYTES,
    BenchmarkLaunchAssociation,
    BenchmarkLaunchUncertain,
    parse_benchmark_launch_control_bytes,
    validate_benchmark_control_reply,
)

from eom_catalog_service.embedding_benchmark_launch_workspace import BENCHMARK_OWNER_ROOT
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_HANDOFF_ROOT
from eom_catalog_service.embedding_benchmark_prelaunch_os import CapturedBenchmarkPrelaunchMachine
from eom_catalog_service.embedding_device_benchmark_files import BenchmarkRootStagedFiles

_PROOF_ROOT = Path("/run/eom-incremental-embeddings/benchmark-recovery")
_ROOT_UID = 0
_ROOT_GID = 0
_ACL_NAMES = frozenset(("system.posix_acl_access", "system.posix_acl_default"))
_ABSENT = ("launch.env", "root-prepared.json", "root-completion.json", "control.sock")


class BenchmarkPrelaunchInspectionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = "BENCHMARK_PRELAUNCH_" + code
        super().__init__(self.code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BenchmarkPrelaunchInspectionError(code)


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
    _require(not _ACL_NAMES.intersection(os.listxattr(path)), "ACL_INVALID")


def _execution(value: str) -> None:
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None, "ID_INVALID")


def _read_control_member(
    directory: int,
    name: str,
    *,
    uid: int,
    gid: int,
    mode: int,
) -> tuple[bytes, tuple[int, ...]]:
    before = os.stat(name, dir_fd=directory, follow_symlinks=False)
    raw = read_protected_cpu_handoff_member(
        directory, name, uid=uid, gid=gid, mode=mode, maximum_bytes=MAX_LAUNCH_CONTROL_BYTES
    )
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    try:
        _no_acl(descriptor)
        _require(
            _epoch(before)
            == _epoch(os.fstat(descriptor))
            == _epoch(os.stat(name, dir_fd=directory, follow_symlinks=False)),
            "CONTROL_CHANGED",
        )
    finally:
        os.close(descriptor)
    return raw, _epoch(before)


@dataclass(frozen=True, slots=True)
class _Control:
    association: BenchmarkLaunchAssociation
    uncertainty: BenchmarkLaunchUncertain
    uncertainty_raw_sha256: str
    association_epoch: tuple[int, ...]
    uncertainty_epoch: tuple[int, ...]


def _read_control(
    request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
) -> _Control:
    owner = fixed_owner_identity()
    with protected_cpu_handoff_directory(
        BENCHMARK_OWNER_ROOT / invocation.execution_id / "inputs",
        owner=owner,
        uid=owner.owner_uid,
        gid=owner.owner_gid,
        mode=0o700,
    ) as directory:
        association_raw, association_epoch = _read_control_member(
            directory, "association.json", uid=owner.owner_uid, gid=owner.owner_gid, mode=0o600
        )
        association = parse_benchmark_launch_control_bytes(association_raw)
    _require(isinstance(association, BenchmarkLaunchAssociation), "ASSOCIATION_INVALID")
    assert isinstance(association, BenchmarkLaunchAssociation)
    request_raw = embedding_device_benchmark_bytes(request)
    invocation_raw = embedding_device_benchmark_bytes(invocation)
    _require(
        (
            association.job_id,
            association.execution_id,
            association.device,
            association.launch_ordinal,
            association.invocation_sha256,
            association.owner_request_sha256,
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
            invocation.invocation_sha256,
            request.request_sha256,
            sha256_bytes(request_raw),
            len(request_raw),
            sha256_bytes(invocation_raw),
            len(invocation_raw),
            invocation.local_input.sha256,
            invocation.local_input.byte_count,
        ),
        "ASSOCIATION_INVALID",
    )
    with protected_cpu_handoff_directory(
        BENCHMARK_HANDOFF_ROOT / invocation.execution_id,
        owner=owner,
        uid=_ROOT_UID,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        uncertain_raw, uncertainty_epoch = _read_control_member(
            directory, "root-uncertain.json", uid=_ROOT_UID, gid=owner.owner_gid, mode=0o640
        )
    uncertain = parse_benchmark_launch_control_bytes(uncertain_raw)
    _require(isinstance(uncertain, BenchmarkLaunchUncertain), "UNCERTAINTY_INVALID")
    assert isinstance(uncertain, BenchmarkLaunchUncertain)
    validate_benchmark_control_reply(association, uncertain)
    return _Control(
        association,
        uncertain,
        sha256_bytes(uncertain_raw),
        association_epoch,
        uncertainty_epoch,
    )


def _validate_selection(
    request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
) -> None:
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


def _layout_snapshot(
    invocation: BenchmarkWorkerInvocation,
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Owner-recomputable metadata only; never opens invocation/input text as the owner."""
    owner = fixed_owner_identity()
    native_uid = pwd.getpwnam("eom-embedding-index-cpu").pw_uid
    entries: list[tuple[str, tuple[int, ...]]] = []
    with protected_cpu_handoff_directory(
        BENCHMARK_HANDOFF_ROOT / invocation.execution_id,
        owner=owner,
        uid=_ROOT_UID,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        entries.append(("execution", _epoch(os.fstat(directory))))
        for absent in _ABSENT:
            try:
                os.stat(absent, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise BenchmarkPrelaunchInspectionError("START_EVIDENCE_PRESENT")
        for name, mode, uid in (
            ("invocation.json", 0o600, _ROOT_UID),
            ("root-uncertain.json", 0o640, _ROOT_UID),
        ):
            value = os.stat(name, dir_fd=directory, follow_symlinks=False)
            _require(
                stat.S_ISREG(value.st_mode)
                and value.st_uid == uid
                and value.st_gid == (_ROOT_GID if name == "invocation.json" else owner.owner_gid)
                and stat.S_IMODE(value.st_mode) == mode
                and value.st_nlink == 1,
                "LAYOUT_INVALID",
            )
            entries.append((name, _epoch(value)))
        for name in ("inputs", "outputs"):
            value = os.stat(name, dir_fd=directory, follow_symlinks=False)
            _require(
                stat.S_ISDIR(value.st_mode)
                and value.st_uid == _ROOT_UID
                and value.st_gid == owner.owner_gid
                and stat.S_IMODE(value.st_mode) == 0o750,
                "LAYOUT_INVALID",
            )
            entries.append((name, _epoch(value)))
    with protected_cpu_handoff_directory(
        BENCHMARK_HANDOFF_ROOT / invocation.execution_id / "outputs",
        owner=owner,
        uid=_ROOT_UID,
        gid=owner.owner_gid,
        mode=0o750,
    ) as directory:
        names = benchmark_local_output_members(1)
        _require(set(os.listdir(directory)) == set(names), "MEMBERS_INVALID")
        identities: set[tuple[int, int]] = set()
        for name in names:
            value = os.stat(name, dir_fd=directory, follow_symlinks=False)
            _require(
                stat.S_ISREG(value.st_mode)
                and value.st_uid == native_uid
                and value.st_gid == owner.owner_gid
                and stat.S_IMODE(value.st_mode) == 0o640
                and value.st_nlink == 1
                and value.st_size == 0
                and (value.st_dev, value.st_ino) not in identities,
                "OUTPUT_INVALID",
            )
            identities.add((value.st_dev, value.st_ino))
            entries.append(("outputs/" + name, _epoch(value)))
    association = BENCHMARK_OWNER_ROOT / invocation.execution_id / "inputs" / "association.json"
    entries.extend(
        (
            ("association-directory", _epoch(association.parent.lstat())),
            ("association.json", _epoch(association.lstat())),
        )
    )
    return tuple(entries)


@dataclass(frozen=True, slots=True)
class _InspectionState:
    request: BenchmarkOwnerRequest
    invocation: BenchmarkWorkerInvocation
    control: _Control
    machine: CapturedBenchmarkPrelaunchMachine


def _capture_state(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    controller: BenchmarkFailedControllerPin,
) -> _InspectionState:
    control = _read_control(request, invocation)
    machine = CapturedBenchmarkPrelaunchMachine(
        controller,
        execution_id=invocation.execution_id,
        owner_pid=control.association.owner_pid,
        expires_ns=control.association.expires_ns,
    )
    return _InspectionState(request, invocation, control, machine)


def _snapshot(state: _InspectionState) -> tuple[_Control, str, str]:
    request, invocation = state.request, state.invocation
    control = _read_control(request, invocation)
    _require(control == state.control, "CONTROL_CHANGED")
    layout = _layout_snapshot(invocation)
    machine = state.machine.observe()
    digest = content_sha256(
        {
            "layout": layout,
            "required_absences": _ABSENT,
            "machine": machine.snapshot_value(),
        }
    )
    _require(layout == _layout_snapshot(invocation), "SNAPSHOT_CHANGED")
    return control, machine.boot_id, digest


class _ProofHandle:
    def __init__(
        self, stack: ExitStack, execution_id: str, expected_raw_sha256: str | None
    ) -> None:
        owner = fixed_owner_identity()
        self._ancestors: list[tuple[int, int | None, str, Path, tuple[int, ...]]] = []
        parent: int | None = None
        location = Path("/")
        for index, component in enumerate(_PROOF_ROOT.parts):
            leaf = index == len(_PROOF_ROOT.parts) - 1
            descriptor = os.open(
                component,
                (os.O_RDONLY if leaf else os.O_PATH)
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                dir_fd=parent,
            )
            stack.callback(os.close, descriptor)
            location = location / component
            value = os.fstat(descriptor)
            synthetic_tmp = (
                _ROOT_UID != 0 and component == "tmp" and bool(value.st_mode & stat.S_ISVTX)
            )
            _require(
                stat.S_ISDIR(value.st_mode)
                and value.st_uid in (0, _ROOT_UID)
                and (not value.st_mode & 0o022 or synthetic_tmp),
                "PROOF_ANCESTOR_INVALID",
            )
            _no_acl(location)
            if leaf:
                _require(
                    value.st_uid == _ROOT_UID
                    and value.st_gid == owner.owner_gid
                    and stat.S_IMODE(value.st_mode) == 0o750,
                    "PROOF_ROOT_INVALID",
                )
            self._ancestors.append(
                (descriptor, parent, component, location, _directory_identity(value))
            )
            parent = descriptor
        assert parent is not None
        self.parent, self.name = parent, execution_id + ".json"
        self.descriptor = os.open(
            self.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
        )
        stack.callback(os.close, self.descriptor)
        value = os.fstat(self.descriptor)
        _require(
            stat.S_ISREG(value.st_mode)
            and value.st_uid == _ROOT_UID
            and value.st_gid == owner.owner_gid
            and stat.S_IMODE(value.st_mode) == 0o440
            and value.st_nlink == 1
            and 0 < value.st_size <= MAX_PRELAUNCH_FAILURE_BYTES,
            "PROOF_FILE_INVALID",
        )
        _no_acl(self.descriptor)
        self.epoch = _epoch(value)
        raw = os.pread(self.descriptor, MAX_PRELAUNCH_FAILURE_BYTES + 1, 0)
        self.raw_sha256 = sha256_bytes(raw)
        _require(
            expected_raw_sha256 is None or self.raw_sha256 == expected_raw_sha256,
            "PROOF_HASH_INVALID",
        )
        observation = parse_benchmark_prelaunch_failure(raw)
        _require(isinstance(observation, BenchmarkPrelaunchObservation), "PROOF_KIND_INVALID")
        assert isinstance(observation, BenchmarkPrelaunchObservation)
        _require(observation.execution_id == execution_id, "PROOF_ID_INVALID")
        self.observation = observation
        self.assert_current()

    def assert_current(self) -> None:
        for descriptor, parent, name, location, expected in self._ancestors:
            _require(
                _directory_identity(os.fstat(descriptor))
                == expected
                == _directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                "PROOF_ANCESTOR_CHANGED",
            )
            _no_acl(location)
        _no_acl(self.descriptor)
        _require(
            self.epoch
            == _epoch(os.fstat(self.descriptor))
            == _epoch(os.stat(self.name, dir_fd=self.parent, follow_symlinks=False)),
            "PROOF_CHANGED",
        )


def _validate_observation(
    observation: BenchmarkPrelaunchObservation,
    state: _InspectionState,
) -> None:
    request, invocation = state.request, state.invocation
    control, boot_id, snapshot_sha256 = _snapshot(state)
    _require(
        (
            observation.job_id,
            observation.execution_id,
            observation.request_sha256,
            observation.invocation_sha256,
            observation.invocation_raw_sha256,
            observation.association_sha256,
            observation.uncertainty_sha256,
            observation.uncertainty_raw_sha256,
            observation.boot_id,
            observation.snapshot_sha256,
        )
        == (
            invocation.job_id,
            invocation.execution_id,
            request.request_sha256,
            invocation.invocation_sha256,
            sha256_bytes(embedding_device_benchmark_bytes(invocation)),
            control.association.association_sha256,
            control.uncertainty.uncertainty_sha256,
            control.uncertainty_raw_sha256,
            boot_id,
            snapshot_sha256,
        ),
        "PROOF_STALE",
    )


class CapturedBenchmarkPrelaunchInspection:
    """Live protected-proof capture; constructed only by the fixed concrete adapter."""

    def __init__(
        self,
        proof: _ProofHandle,
        state: _InspectionState,
    ) -> None:
        self._proof, self._state, self._active = proof, state, True

    @property
    def observation(self) -> BenchmarkPrelaunchObservation:
        return self._proof.observation

    def assert_current(self) -> None:
        _require(self._active, "CAPTURE_CLOSED")
        self._proof.assert_current()
        _validate_observation(self.observation, self._state)
        self._proof.assert_current()


@dataclass(frozen=True, slots=True)
class FixedBenchmarkPrelaunchInspection:
    """Only a fixed execution and expected root-proof raw hash, never a report/path override."""

    execution_id: str
    expected_raw_sha256: str

    def __post_init__(self) -> None:
        _execution(self.execution_id)
        _require(
            type(self.expected_raw_sha256) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", self.expected_raw_sha256) is not None,
            "PROOF_PIN_INVALID",
        )

    @contextmanager
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> Iterator[CapturedBenchmarkPrelaunchInspection]:
        _validate_selection(request, invocation)
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
                proof = _ProofHandle(stack, self.execution_id, self.expected_raw_sha256)
                state = _capture_state(request, invocation, proof.observation.controller)
                captured = CapturedBenchmarkPrelaunchInspection(proof, state)
                captured.assert_current()
                try:
                    yield captured
                finally:
                    # The application fences inside its SQL transaction. Revalidating here
                    # could report post-commit drift as a failed/uncertain database outcome.
                    captured._active = False
        except (OSError, CpuHandoffError):
            raise BenchmarkPrelaunchInspectionError("PROOF_UNAVAILABLE") from None


@dataclass(frozen=True, slots=True)
class MintedBenchmarkPrelaunchProof:
    observation: BenchmarkPrelaunchObservation
    raw_sha256: str
    created: bool


def mint_benchmark_prelaunch_observation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    *,
    controller: BenchmarkFailedControllerPin,
) -> MintedBenchmarkPrelaunchProof:
    """Root-only create-once local proof; preserve the entire original handoff and history."""
    _require(
        os.getresuid() == (_ROOT_UID,) * 3 and os.getresgid() == (_ROOT_GID,) * 3,
        "ROOT_REQUIRED",
    )
    _validate_selection(request, invocation)
    controller = BenchmarkFailedControllerPin.model_validate(controller)
    owner = fixed_owner_identity()
    try:
        with ExitStack() as stack:
            # This intentionally reads invocation only: no source question/input bytes are copied.
            descriptor = os.open(
                BENCHMARK_HANDOFF_ROOT / invocation.execution_id / "invocation.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            stack.callback(os.close, descriptor)
            local = stack.enter_context(
                BenchmarkRootStagedFiles(
                    descriptor,
                    profile=invocation.runtime.profile,
                    execution_id=invocation.execution_id,
                    invocation_raw_sha256=sha256_bytes(
                        embedding_device_benchmark_bytes(invocation)
                    ),
                )
            )
            _require(local.read_invocation() == invocation, "INVOCATION_INVALID")
            state = _capture_state(request, invocation, controller)
            try:
                existing = _ProofHandle(stack, invocation.execution_id, None)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                _require(existing.observation.controller == controller, "PROOF_CONFLICT")
                _validate_observation(existing.observation, state)
                local.assert_current()
                existing.assert_current()
                return MintedBenchmarkPrelaunchProof(
                    existing.observation, existing.raw_sha256, False
                )
            control, boot_id, snapshot_sha256 = _snapshot(state)
            body = dict(
                schema_version="embedding-benchmark-prelaunch-failure/1.0",
                kind="ROOT_OBSERVATION",
                job_id=invocation.job_id,
                execution_id=invocation.execution_id,
                request_sha256=request.request_sha256,
                invocation_sha256=invocation.invocation_sha256,
                device="CPU",
                launch_ordinal=1,
                association_sha256=control.association.association_sha256,
                uncertainty_sha256=control.uncertainty.uncertainty_sha256,
                invocation_raw_sha256=sha256_bytes(embedding_device_benchmark_bytes(invocation)),
                uncertainty_raw_sha256=control.uncertainty_raw_sha256,
                controller=controller.model_dump(mode="json"),
                boot_id=boot_id,
                snapshot_sha256=snapshot_sha256,
                output_count=16,
                disposition="PREPARATION_FAILED_BEFORE_NATIVE_START",
                observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            observation = BenchmarkPrelaunchObservation.model_validate(
                body | {"observation_sha256": content_sha256(body)}
            )
            raw = benchmark_prelaunch_failure_bytes(observation)
            local.assert_current()
            _validate_observation(observation, state)
            # Provision this parent separately; never mkdir inside the original handoff.
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
                    proof = _ProofHandle(stack, invocation.execution_id, None)
                    _require(proof.observation.controller == controller, "PROOF_CONFLICT")
                    _validate_observation(proof.observation, state)
                    local.assert_current()
                    proof.assert_current()
                    return MintedBenchmarkPrelaunchProof(proof.observation, proof.raw_sha256, False)
                try:
                    os.fchown(descriptor, _ROOT_UID, owner.owner_gid)
                    os.fchmod(descriptor, 0o440)
                    _no_acl(descriptor)
                    remaining = memoryview(raw)
                    while remaining:
                        count = os.write(descriptor, remaining)
                        _require(0 < count <= len(remaining), "PROOF_WRITE_FAILED")
                        remaining = remaining[count:]
                    os.fsync(descriptor)
                    _require(os.pread(descriptor, len(raw) + 1, 0) == raw, "PROOF_WRITE_FAILED")
                    os.fsync(directory)
                finally:
                    os.close(descriptor)
            proof = _ProofHandle(stack, invocation.execution_id, sha256_bytes(raw))
            local.assert_current()
            _validate_observation(proof.observation, state)
            proof.assert_current()
            return MintedBenchmarkPrelaunchProof(proof.observation, proof.raw_sha256, True)
    except (OSError, CpuHandoffError):
        raise BenchmarkPrelaunchInspectionError("MINT_UNAVAILABLE") from None
