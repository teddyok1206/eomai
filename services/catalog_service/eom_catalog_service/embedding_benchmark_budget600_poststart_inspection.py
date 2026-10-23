"""Seal and reread the original budget600 CPU timeout without retrying the worker."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_catalog_contracts.embedding_benchmark_budget600_failure import (
    BenchmarkBudget600PoststartObservation,
    BenchmarkBudget600TerminalProof,
    benchmark_budget600_failure_bytes,
    parse_benchmark_budget600_failure,
)
from eom_catalog_contracts.embedding_benchmark_poststart_failure import MAX_POSTSTART_FAILURE_BYTES
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import BenchmarkFailedControllerPin
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    benchmark_timeout_seconds,
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
    BenchmarkLaunchUncertain,
    parse_benchmark_launch_control_bytes,
)

from eom_catalog_service.embedding_benchmark_budget600_poststart_os import (
    CapturedBudget600PoststartMachine,
)
from eom_catalog_service.embedding_benchmark_budget600_window_evidence import (
    capture_budget600_window,
)
from eom_catalog_service.embedding_benchmark_layout import BENCHMARK_HANDOFF_ROOT
from eom_catalog_service.embedding_benchmark_poststart_inspection import (
    _PROOF_ROOT,
    _capture,
    _Inspection,
    _Member,
    _member,
    _no_acl,
    _require,
    _selection,
)
from eom_catalog_service.embedding_benchmark_poststart_os import read_root_poststart_retirement


def _uncertain(stack: ExitStack, invocation: BenchmarkWorkerInvocation) -> _Member:
    owner = fixed_owner_identity()
    member = _member(
        stack,
        BENCHMARK_HANDOFF_ROOT / invocation.execution_id / "root-uncertain.json",
        directory_uid=0,
        directory_mode=0o750,
        uid=0,
        gid=owner.owner_gid,
        mode=0o640,
        maximum=MAX_LAUNCH_CONTROL_BYTES,
    )
    record = parse_benchmark_launch_control_bytes(member.raw)
    _require(isinstance(record, BenchmarkLaunchUncertain), "UNCERTAINTY_KIND_INVALID")
    assert isinstance(record, BenchmarkLaunchUncertain)
    _require(
        (record.job_id, record.execution_id, record.invocation_sha256)
        == (invocation.job_id, invocation.execution_id, invocation.invocation_sha256),
        "UNCERTAINTY_LINK_INVALID",
    )
    return member


def _snapshot(state: _Inspection, uncertain: _Member) -> tuple[str, str]:
    boot, base = state.snapshot()
    uncertain.assert_current()
    return boot, content_sha256(
        {
            "base_snapshot_sha256": base,
            "uncertain_raw_sha256": uncertain.sha256,
            "terminal": state.terminal.model_dump(mode="json"),
        }
    )


def _validate(
    observation: BenchmarkBudget600PoststartObservation,
    state: _Inspection,
    uncertain: _Member,
) -> None:
    boot, snapshot = _snapshot(state, uncertain)
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
            observation.uncertain_raw_sha256,
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
            uncertain.sha256,
            completed.started_ns,
            completed.completed_ns,
            state.outputs,
            state.terminal,
            boot,
            snapshot,
        ),
        "PROOF_STALE",
    )
    record = parse_benchmark_launch_control_bytes(uncertain.raw)
    _require(isinstance(record, BenchmarkLaunchUncertain), "UNCERTAINTY_KIND_INVALID")
    assert isinstance(record, BenchmarkLaunchUncertain)
    _require(
        record.association_sha256 == state.association.association_sha256,
        "UNCERTAINTY_ASSOCIATION_INVALID",
    )


def _proof(
    stack: ExitStack, execution_id: str, expected_sha256: str | None
) -> tuple[_Member, BenchmarkBudget600PoststartObservation]:
    owner = fixed_owner_identity()
    path = _PROOF_ROOT / (execution_id + ".json")
    path.lstat()
    member = _member(
        stack,
        path,
        directory_uid=0,
        directory_mode=0o750,
        uid=0,
        gid=owner.owner_gid,
        mode=0o440,
        maximum=MAX_POSTSTART_FAILURE_BYTES,
    )
    _require(expected_sha256 is None or member.sha256 == expected_sha256, "PROOF_HASH_INVALID")
    observation = parse_benchmark_budget600_failure(member.raw)
    _require(isinstance(observation, BenchmarkBudget600PoststartObservation), "PROOF_KIND_INVALID")
    assert isinstance(observation, BenchmarkBudget600PoststartObservation)
    _require(observation.execution_id == execution_id, "PROOF_ID_INVALID")
    return member, observation


@dataclass(frozen=True, slots=True)
class MintedBudget600PoststartProof:
    observation: BenchmarkBudget600PoststartObservation
    raw_sha256: str
    created: bool


class CapturedBudget600PoststartInspection:
    def __init__(
        self,
        record: _Member,
        observation: BenchmarkBudget600PoststartObservation,
        state: _Inspection,
        uncertain: _Member,
    ) -> None:
        self._record = record
        self._observation = observation
        self._state = state
        self._uncertain = uncertain
        self._active = True

    @property
    def observation(self) -> BenchmarkBudget600PoststartObservation:
        return self._observation

    def assert_current(self) -> None:
        _require(self._active, "CAPTURE_CLOSED")
        self._record.assert_current()
        _validate(self._observation, self._state, self._uncertain)
        self._record.assert_current()


@dataclass(frozen=True, slots=True)
class FixedBudget600PoststartInspection:
    execution_id: str
    expected_raw_sha256: str

    def __post_init__(self) -> None:
        _require(
            re.fullmatch(r"[0-9a-f]{32}", self.execution_id) is not None
            and re.fullmatch(r"sha256:[0-9a-f]{64}", self.expected_raw_sha256) is not None,
            "PROOF_PIN_INVALID",
        )

    @contextmanager
    def capture(
        self, request: BenchmarkOwnerRequest, invocation: BenchmarkWorkerInvocation
    ) -> Iterator[CapturedBudget600PoststartInspection]:
        _selection(request, invocation)
        _require(benchmark_timeout_seconds(request.execution_policy) == 600, "POLICY_INVALID")
        _require(invocation.execution_id == self.execution_id, "PROOF_ID_INVALID")
        owner = fixed_owner_identity()
        _require(
            (os.getresuid(), os.getresgid())
            in (((0,) * 3, (0,) * 3), ((owner.owner_uid,) * 3, (owner.owner_gid,) * 3)),
            "INSPECTOR_INVALID",
        )
        try:
            with ExitStack() as stack:
                proof, observation = _proof(stack, self.execution_id, self.expected_raw_sha256)
                uncertain = _uncertain(stack, invocation)
                state = _capture(
                    stack,
                    request,
                    invocation,
                    observation.controller,
                    observation.terminal,
                    machine_factory=lambda association: CapturedBudget600PoststartMachine(
                        observation.controller,
                        execution_id=invocation.execution_id,
                        native_invocation_id=observation.terminal.native_invocation_id,
                        owner_pid=association.owner_pid,
                        expires_ns=association.expires_ns,
                    ),
                )
                captured = CapturedBudget600PoststartInspection(
                    proof, observation, state, uncertain
                )
                captured.assert_current()
                try:
                    yield captured
                finally:
                    captured._active = False
        except (OSError, CpuHandoffError):
            raise ValueError("BENCHMARK_BUDGET600_PROOF_UNAVAILABLE") from None


def mint_budget600_poststart_observation(
    request: BenchmarkOwnerRequest,
    invocation: BenchmarkWorkerInvocation,
    *,
    controller: BenchmarkFailedControllerPin,
) -> MintedBudget600PoststartProof:
    """Root-only immutable proof; never starts an owner, model or another Job."""
    _require(os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0), "ROOT_REQUIRED")
    _selection(request, invocation)
    _require(benchmark_timeout_seconds(request.execution_policy) == 600, "POLICY_INVALID")
    owner = fixed_owner_identity()
    with ExitStack() as stack:
        local = _member(
            stack,
            BENCHMARK_HANDOFF_ROOT / invocation.execution_id / "invocation.json",
            directory_uid=0,
            directory_mode=0o750,
            uid=0,
            gid=owner.owner_gid,
            file_gid=0,
            mode=0o600,
            maximum=MAX_LAUNCH_CONTROL_BYTES,
        )
        _require(local.raw == embedding_device_benchmark_bytes(invocation), "INVOCATION_INVALID")
        uncertain = _uncertain(stack, invocation)
        retired = read_root_poststart_retirement(request, invocation)
        window = capture_budget600_window(
            request, controller_invocation_id=controller.invocation_id
        )
        terminal = BenchmarkBudget600TerminalProof(
            native_service="eom-embedding-benchmark-cpu-budget600@"
            + invocation.execution_id
            + ".service",
            native_socket="eom-embedding-benchmark-cpu-budget600@"
            + invocation.execution_id
            + ".socket",
            native_invocation_id=retired.native_invocation_id,
            retirement_raw_sha256=retired.raw_sha256,
            main_pid=0,
            control_pid=0,
            descriptor_store_count=0,
            cgroup_empty=True,
            socket_inactive=True,
            retirement="CONFIRMED",
            retired_service_template_sha256=window.retired_service_template_sha256,
            retired_socket_template_sha256=window.retired_socket_template_sha256,
            window_before_raw_sha256=window.before_raw_sha256,
            window_stopped_raw_sha256=window.stopped_raw_sha256,
            window_restored_raw_sha256=window.restored_raw_sha256,
        )
        # The shared bounded capture reads the original association before
        # constructing the actual-machine observer.
        state = _capture(
            stack,
            request,
            invocation,
            controller,
            terminal,
            machine_factory=lambda association: CapturedBudget600PoststartMachine(
                controller,
                execution_id=invocation.execution_id,
                native_invocation_id=retired.native_invocation_id,
                owner_pid=association.owner_pid,
                expires_ns=association.expires_ns,
                window=window,
                retirement=retired,
            ),
        )
        original = retired.retirement.original_terminal
        _require(
            state.completion.started_ns
            <= original.status.exec_main_started_monotonic * 1000
            <= original.exited_monotonic * 1000
            <= state.completion.completed_ns,
            "RETIREMENT_TIME_INVALID",
        )
        boot, snapshot = _snapshot(state, uncertain)
        completion = state.completion
        body = dict(
            schema_version="embedding-benchmark-poststart-failure/1.1",
            kind="ROOT_OBSERVATION",
            job_id=invocation.job_id,
            execution_id=invocation.execution_id,
            request_sha256=request.request_sha256,
            invocation_sha256=invocation.invocation_sha256,
            device="CPU",
            launch_ordinal=1,
            failure_kind="BUDGET600_TIMEOUT",
            association_sha256=state.association.association_sha256,
            prepared_sha256=state.prepared.prepared_sha256,
            completion_sha256=completion.completion_sha256,
            invocation_raw_sha256=sha256_bytes(embedding_device_benchmark_bytes(invocation)),
            completion_raw_sha256=state.records[2].sha256,
            uncertain_raw_sha256=uncertain.sha256,
            original_outcome="FAILED",
            cleanup="CONFIRMED",
            started_ns=completion.started_ns,
            completed_ns=completion.completed_ns,
            controller=controller.model_dump(mode="json"),
            terminal=terminal.model_dump(mode="json"),
            outputs=[member.model_dump(mode="json") for member in state.outputs],
            boot_id=boot,
            snapshot_sha256=snapshot,
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        observation = BenchmarkBudget600PoststartObservation.model_validate(
            body | {"observation_sha256": content_sha256(body)}
        )
        raw = benchmark_budget600_failure_bytes(observation)
        try:
            proof, existing = _proof(stack, invocation.execution_id, None)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            _require(
                existing.controller == controller and existing.terminal == terminal,
                "PROOF_CONFLICT",
            )
            _validate(existing, state, uncertain)
            retired.assert_current()
            window.assert_current()
            local.assert_current()
            proof.assert_current()
            return MintedBudget600PoststartProof(existing, proof.sha256, False)
        _validate(observation, state, uncertain)
        with protected_cpu_handoff_directory(
            _PROOF_ROOT, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
        ) as directory:
            _no_acl(directory)
            descriptor = os.open(
                invocation.execution_id + ".json",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            try:
                os.fchown(descriptor, 0, owner.owner_gid)
                os.fchmod(descriptor, 0o440)
                view = memoryview(raw)
                while view:
                    count = os.write(descriptor, view)
                    _require(0 < count <= len(view), "PROOF_WRITE_FAILED")
                    view = view[count:]
                os.fsync(descriptor)
                _no_acl(descriptor)
                os.fsync(directory)
            finally:
                os.close(descriptor)
        proof, reread = _proof(stack, invocation.execution_id, sha256_bytes(raw))
        _validate(reread, state, uncertain)
        retired.assert_current()
        window.assert_current()
        local.assert_current()
        proof.assert_current()
        return MintedBudget600PoststartProof(reread, proof.sha256, True)
