"""Orchestrator-owned, sequential maintenance diagnostics with immutable checkpoints."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import islice, product
from pathlib import Path
from uuid import uuid4

from eom_identifiers import content_sha256, new_job_id, sha256_bytes, sha256_file
from eom_workflow.codex_compatibility import (
    CodexCompatibilityCase,
    CodexCompatibilityCaseResult,
    CodexCompatibilityInvocation,
    CodexCompatibilityReport,
    CodexCompatibilityRequest,
    CodexCompatibilityRuntime,
    compatibility_request_sha256,
    load_compatibility_report,
    load_compatibility_request,
)
from eom_workflow.codex_compatibility_matrix import (
    CompatibilityMatrix,
    CompatibilitySelection,
    load_compatibility_matrix,
)
from eom_workflow.control_plane import FrozenModel, ReasoningEffort, UtcDatetime
from eom_workflow.control_schemas import validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, select

from eom_orchestrator.codex_compatibility_maintenance import (
    CodexCompatibilityMaintenance,
    assert_codex_slot_compatibility_work_absent,
    assert_codex_workers_quiescent,
)
from eom_orchestrator.codex_compatibility_probe import (
    compatibility_output_schema,
    compatibility_probe_input,
    compatibility_probe_prompt,
    materialize_compatibility_inputs,
    synthetic_probe_png,
    validate_probe_result,
)
from eom_orchestrator.codex_compatibility_runtime import observe_compatibility_runtime_guard
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker import CodexWorkerAdapter, load_worker_result
from eom_orchestrator.worker_registry import WorkerRegistry, WorkerSlot

_MAX_LEDGER_BYTES = 1024 * 1024


class _CaseIdentity(FrozenModel):
    case_id: str = Field(pattern=r"^compatcase_[0-9a-f]{32}$")
    job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")


class _Epoch(FrozenModel):
    request_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    runtime: CodexCompatibilityRuntime
    started_at: UtcDatetime
    executions: tuple[_CaseIdentity, ...] = Field(min_length=1, max_length=64)


@dataclass(frozen=True, slots=True)
class PublishedCodexCompatibility:
    report: CodexCompatibilityReport
    artifact: PublishedControlFileSet


def prepare_codex_compatibility_request(
    engine: Engine,
    *,
    models: tuple[str, ...],
    reasoning_efforts: tuple[ReasoningEffort, ...],
    slot_ids: tuple[str, ...],
    source_commit: str,
    now: datetime,
) -> CodexCompatibilityRequest:
    """Preserve Cartesian presentation while delegating authoritative matrix preparation."""

    try:
        # Materialize at most one over the contract limit, even for a large product.
        matrix = CompatibilityMatrix(
            selections=tuple(
                CompatibilitySelection(
                    slot_id=slot,  # type: ignore[arg-type]
                    model=model,
                    reasoning_effort=effort,
                )
                for model, effort, slot in islice(product(models, reasoning_efforts, slot_ids), 65)
            )
        )
    except ValueError as exc:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_REQUEST_INVALID", "invalid bounded case set"
        ) from exc
    return prepare_codex_compatibility_matrix_request(
        engine, matrix=matrix, source_commit=source_commit, now=now
    )


def prepare_codex_compatibility_matrix_request(
    engine: Engine,
    *,
    matrix: CompatibilityMatrix,
    source_commit: str,
    now: datetime,
) -> CodexCompatibilityRequest:
    """Pin server-owned bindings once for a bounded ordered operator selection set."""

    try:
        matrix = load_compatibility_matrix(matrix.model_dump(mode="json"))
    except (ValueError, JsonSchemaValidationError) as exc:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_REQUEST_INVALID", "invalid bounded case set"
        ) from exc
    slot_ids = {selection.slot_id for selection in matrix.selections}
    sessions = build_session_factory(engine)
    with sessions() as session:
        bindings = {
            binding.worker_slot_id: binding
            for binding in session.scalars(
                select(CodexAuthBindingRecord).where(
                    CodexAuthBindingRecord.worker_slot_id.in_(slot_ids)
                )
            )
        }
        if set(bindings) != slot_ids or any(
            binding.state in {"DISABLED", "DRAINING"} for binding in bindings.values()
        ):
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_BINDING_INVALID", "diagnostic binding is unavailable"
            )
        cases = tuple(
            CodexCompatibilityCase(
                case_id="compatcase_" + uuid4().hex,
                slot_id=selection.slot_id,
                binding_id=bindings[selection.slot_id].binding_id,
                assignment_revision_id=bindings[selection.slot_id].current_assignment_revision_id,
                expected_resource_version=bindings[selection.slot_id].resource_version,
                model=selection.model,
                reasoning_effort=selection.reasoning_effort,
            )
            for selection in matrix.selections
        )
    request = CodexCompatibilityRequest(
        run_id="codexcompat_" + uuid4().hex,
        source_commit=source_commit,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        max_model_calls=len(cases),
        cases=cases,
    )
    return load_compatibility_request(request.model_dump(mode="json"))


def _encode(document: object) -> bytes:
    return (
        json.dumps(
            document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
    )


def _read_document(path: Path) -> object:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= _MAX_LEDGER_BYTES
        ):
            raise ValueError("invalid compatibility checkpoint file")
        return json.loads(stream.read(_MAX_LEDGER_BYTES + 1))


def _write_once(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _ledger_root(settings: Settings, run_id: str) -> Path:
    root = settings.staging_root / run_id
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        created = False
    else:
        created = True
    if created:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.fstat(descriptor).st_uid != os.geteuid():
                raise ValueError("new compatibility ledger has unexpected owner")
            # A private ledger must not inherit setgid from a shared staging parent.
            os.fchmod(descriptor, 0o700)
        finally:
            os.close(descriptor)
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ControlPlaneError("CONTROL_COMPATIBILITY_LEDGER_INVALID", "unsafe diagnostic ledger")
    return root


def load_checkpointed_codex_compatibility_request(
    settings: Settings, run_id: str
) -> CodexCompatibilityRequest | None:
    """Recover the same local request before discovering any new model candidates."""

    if re.fullmatch(r"codexcompat_[0-9a-f]{32}", run_id) is None:
        raise ControlPlaneError("CONTROL_COMPATIBILITY_REQUEST_INVALID", "invalid run identity")
    path = _ledger_root(settings, run_id) / "request.json"
    if not path.exists():
        return None
    request = load_compatibility_request(_read_document(path))
    if request.run_id != run_id:
        raise ControlPlaneError("CONTROL_COMPATIBILITY_REPLAY_CONFLICT", "checkpoint run differs")
    return request


def _require_binding(engine: Engine, case: CodexCompatibilityCase) -> None:
    sessions = build_session_factory(engine)
    with sessions() as session:
        binding = session.get(CodexAuthBindingRecord, case.binding_id)
        if (
            binding is None
            or binding.worker_slot_id != case.slot_id
            or binding.resource_version != case.expected_resource_version
            or binding.current_assignment_revision_id != case.assignment_revision_id
            or binding.state in {"DISABLED", "DRAINING"}
        ):
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_BINDING_CHANGED", "diagnostic binding no longer matches"
            )


def validate_codex_compatibility_preflight(
    engine: Engine,
    request: CodexCompatibilityRequest,
    *,
    settings: Settings,
    now: datetime,
) -> None:
    """Read-only lifecycle/binding checks before an operator stops any producer units."""

    request = load_compatibility_request(request.model_dump(mode="json"))
    if settings.runtime_source_commit != request.source_commit:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_RELEASE_MISMATCH", "request does not pin installed release"
        )
    if now < request.created_at or now >= request.expires_at:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_REQUEST_EXPIRED", "diagnostic request is not currently valid"
        )
    registry = WorkerRegistry.load(settings.worker_config)
    enabled = {slot.slot_id for slot in registry.config.slots if slot.enabled}
    sessions = build_session_factory(engine)
    with sessions() as session:
        bindings = {
            binding.binding_id: binding
            for binding in session.scalars(
                select(CodexAuthBindingRecord).where(
                    CodexAuthBindingRecord.binding_id.in_(
                        {case.binding_id for case in request.cases}
                    )
                )
            )
        }
        for case in request.cases:
            binding = bindings.get(case.binding_id)
            if (
                case.slot_id not in enabled
                or binding is None
                or binding.worker_slot_id != case.slot_id
                or binding.resource_version != case.expected_resource_version
                or binding.current_assignment_revision_id != case.assignment_revision_id
                or binding.state in {"DISABLED", "DRAINING"}
            ):
                raise ControlPlaneError(
                    "CONTROL_COMPATIBILITY_BINDING_CHANGED", "diagnostic binding no longer matches"
                )


def _invocation(
    request: CodexCompatibilityRequest, case: CodexCompatibilityCase, job_id: str, image: bytes
) -> CodexCompatibilityInvocation:
    value = {
        "schema_version": "codex-compatibility-invocation/1.0",
        "run_id": request.run_id,
        "case_id": case.case_id,
        "request_sha256": compatibility_request_sha256(request),
        "job_id": job_id,
        "model": case.model,
        "reasoning_effort": case.reasoning_effort,
        "image_sha256": sha256_bytes(image),
    }
    invocation = CodexCompatibilityInvocation.model_validate(
        {**value, "invocation_sha256": content_sha256(value)}
    )
    validate_control_contract("codex-compatibility-invocation", invocation.model_dump(mode="json"))
    return invocation


def _run_case(
    *,
    adapter: CodexWorkerAdapter,
    case: CodexCompatibilityCase,
    invocation: CodexCompatibilityInvocation,
    slot: WorkerSlot,
    root: Path,
    image: bytes,
) -> CodexCompatibilityCaseResult:
    case_directory = root / case.case_id
    case_directory.mkdir(mode=0o750)
    prepared = adapter.prepare_structured_workspace(
        job_id=invocation.job_id,
        input_document=compatibility_probe_input(invocation),
        output_schema=compatibility_output_schema(invocation),
        prompt_text=compatibility_probe_prompt(invocation),
        slot=slot,
    )
    materialize_compatibility_inputs(prepared.workspace, invocation, image)
    # Persist launch intent first. An interruption from here must not cause re-inference.
    _write_once(root / f"{case.case_id}.started.json", _encode(invocation.model_dump(mode="json")))
    started = time.monotonic()
    run = adapter.run_prepared(
        prepared=prepared,
        slot=slot,
        staging=case_directory,
        timeout_seconds=7200 if slot.slot_id in {"05", "06"} else 1800,
    )
    error: str | None = None
    result_hash: str | None = None
    if run.exit_code != 0:
        error = "WORKER_EXEC_FAILED"
    else:
        try:
            document = load_worker_result(run.result_path, prepared.workspace)
            validate_control_contract("codex-compatibility-probe-result", document)
        except (
            PlatformError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
            OSError,
        ):
            # Do not log untrusted worker output, prompts, credentials, or exception text.
            error = "WORKER_RESULT_INVALID"
        else:
            payload = _encode(document)
            _write_once(root / f"{case.case_id}.output.json", payload)
            result_hash = sha256_bytes(payload)
            try:
                validate_probe_result(document, invocation)
            except ValueError:
                error = "RESULT_CONTENT_MISMATCH"
    result = CodexCompatibilityCaseResult(
        **case.model_dump(mode="json"),
        job_id=invocation.job_id,
        status="PASS" if error is None else "FAIL",
        error_code=error,  # type: ignore[arg-type]
        invocation_sha256=invocation.invocation_sha256,
        result_sha256=result_hash,
        elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
    )
    _write_once(root / f"{case.case_id}.result.json", _encode(result.model_dump(mode="json")))
    return result


def run_codex_compatibility(
    engine: Engine,
    request: CodexCompatibilityRequest,
    *,
    settings: Settings | None = None,
    worker: CodexWorkerAdapter | None = None,
) -> PublishedCodexCompatibility:
    """Execute only inside a held maintenance fence; exact replay never starts a new call."""

    return execute_pinned_codex_compatibility(
        engine,
        request,
        settings=settings or Settings.from_environment(),
        worker=worker,
        fence_factory=lambda: CodexCompatibilityMaintenance(engine),
        require_binding=lambda case: _require_binding(engine, case),
    )


def run_codex_slot_compatibility(
    engine: Engine,
    request: CodexCompatibilityRequest,
    *,
    settings: Settings | None = None,
    worker: CodexWorkerAdapter | None = None,
) -> PublishedCodexCompatibility:
    """Probe idle fixed slots under the host fence while unrelated GPU jobs continue."""

    return execute_pinned_codex_compatibility(
        engine,
        request,
        settings=settings or Settings.from_environment(),
        worker=worker,
        fence_factory=lambda: CodexCompatibilityMaintenance(
            engine,
            host_reader=assert_codex_workers_quiescent,
            database_reader=assert_codex_slot_compatibility_work_absent,
        ),
        require_binding=lambda case: _require_binding(engine, case),
    )


def execute_pinned_codex_compatibility(
    engine: Engine,
    request: CodexCompatibilityRequest,
    *,
    settings: Settings,
    worker: CodexWorkerAdapter | None,
    fence_factory: Callable[[], CodexCompatibilityMaintenance],
    require_binding: Callable[[CodexCompatibilityCase], None],
) -> PublishedCodexCompatibility:
    """Shared checkpoint/probe/publication boundary for maintenance and enrollment.

    The caller owns a real capacity fence and exact binding admission. Neither a
    diagnostic invocation nor a successful file publication grants ordinary work.
    """

    request = load_compatibility_request(request.model_dump(mode="json"))
    if settings.runtime_source_commit != request.source_commit:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_RELEASE_MISMATCH", "request does not pin installed release"
        )
    root = _ledger_root(settings, request.run_id)
    report_path = root / "report.json"
    request_path = root / "request.json"
    request_hash = compatibility_request_sha256(request)
    if request_path.exists():
        recorded = load_compatibility_request(_read_document(request_path))
        if compatibility_request_sha256(recorded) != request_hash:
            raise ControlPlaneError("CONTROL_COMPATIBILITY_REPLAY_CONFLICT", "run identity reused")
    else:
        _write_once(request_path, _encode(request.model_dump(mode="json")))
    if report_path.exists():
        report = load_compatibility_report(_read_document(report_path))
        if report.request_sha256 != request_hash:
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_REPLAY_CONFLICT", "report identity differs"
            )
    else:
        if datetime.now(UTC) >= request.expires_at:
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_REQUEST_EXPIRED",
                "diagnostic request expired before execution",
            )
        registry = WorkerRegistry.load(settings.worker_config)
        slots = {slot.slot_id: slot for slot in registry.config.slots if slot.enabled}
        if any(case.slot_id not in slots for case in request.cases):
            raise ControlPlaneError("CONTROL_COMPATIBILITY_BINDING_INVALID", "disabled worker slot")
        adapter = worker or CodexWorkerAdapter(settings)
        with fence_factory() as fence:
            runtime_guard = observe_compatibility_runtime_guard()
            epoch_path = root / "epoch.json"
            if epoch_path.exists():
                epoch = _Epoch.model_validate(_read_document(epoch_path))
                if epoch.request_sha256 != request_hash or epoch.runtime != runtime_guard.runtime:
                    raise ControlPlaneError(
                        "CONTROL_COMPATIBILITY_RUNTIME_CHANGED",
                        "cannot replay against a new runtime",
                    )
            else:
                epoch = _Epoch(
                    request_sha256=request_hash,
                    runtime=runtime_guard.runtime,
                    started_at=datetime.now(UTC),
                    executions=tuple(
                        _CaseIdentity(case_id=case.case_id, job_id=new_job_id())
                        for case in request.cases
                    ),
                )
                _write_once(epoch_path, _encode(epoch.model_dump(mode="json")))
            if tuple(value.case_id for value in epoch.executions) != tuple(
                case.case_id for case in request.cases
            ) or len({value.job_id for value in epoch.executions}) != len(epoch.executions):
                raise ControlPlaneError(
                    "CONTROL_COMPATIBILITY_LEDGER_INVALID", "execution identities differ"
                )
            results: list[CodexCompatibilityCaseResult] = []
            stopped = False
            image = synthetic_probe_png()
            for case, identity in zip(request.cases, epoch.executions, strict=True):
                checkpoint = root / f"{case.case_id}.result.json"
                if checkpoint.exists():
                    result = CodexCompatibilityCaseResult.model_validate(_read_document(checkpoint))
                    if result.job_id != identity.job_id or any(
                        getattr(result, key) != getattr(case, key)
                        for key in CodexCompatibilityCase.model_fields
                    ):
                        raise ControlPlaneError(
                            "CONTROL_COMPATIBILITY_LEDGER_INVALID", "checkpoint pins differ"
                        )
                elif (root / f"{case.case_id}.started.json").exists():
                    raise ControlPlaneError(
                        "CONTROL_COMPATIBILITY_EXECUTION_UNCERTAIN",
                        "started execution requires explicit reconciliation",
                    )
                elif stopped or datetime.now(UTC) >= request.expires_at:
                    result = CodexCompatibilityCaseResult(
                        **case.model_dump(mode="json"),
                        job_id=identity.job_id,
                        status="NOT_RUN",
                        error_code="PREVIOUS_FAILURE" if stopped else "REQUEST_EXPIRED",
                        invocation_sha256=None,
                        result_sha256=None,
                        elapsed_ms=0,
                    )
                else:
                    fence.assert_quiescent()
                    runtime_guard.assert_current()
                    require_binding(case)
                    invocation = _invocation(request, case, identity.job_id, image)
                    result = _run_case(
                        adapter=adapter,
                        case=case,
                        invocation=invocation,
                        slot=slots[case.slot_id],
                        root=root,
                        image=image,
                    )
                results.append(result)
                stopped = result.status != "PASS"
            report = CodexCompatibilityReport(
                request=request,
                request_sha256=request_hash,
                started_at=epoch.started_at,
                completed_at=datetime.now(UTC),
                runtime=epoch.runtime,
                model_calls=sum(case.status in {"PASS", "FAIL"} for case in results),
                cases=tuple(results),
            )
            load_compatibility_report(report.model_dump(mode="json"))
            _write_once(report_path, _encode(report.model_dump(mode="json")))
    members = [
        ControlFileSetMember(
            name,
            root / name,
            sha256_file(root / name),
            (root / name).stat().st_size,
            schema,
            "application/json",
        )
        for name, schema in (
            ("request.json", "eom://schemas/workflow/codex-compatibility-request/1.0"),
            ("report.json", "eom://schemas/workflow/codex-compatibility-report/1.0"),
        )
    ]
    for result in report.cases:
        expected_invocation = _invocation(request, result, result.job_id, synthetic_probe_png())
        if (
            result.status in {"PASS", "FAIL"}
            and result.invocation_sha256 != expected_invocation.invocation_sha256
        ):
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_LEDGER_INVALID", "invocation checkpoint hash changed"
            )
        name = f"{result.case_id}.output.json"
        if result.result_sha256 is not None:
            path = root / name
            if sha256_file(path) != result.result_sha256:
                raise ControlPlaneError(
                    "CONTROL_COMPATIBILITY_LEDGER_INVALID", "result checkpoint hash changed"
                )
            if result.status == "PASS":
                validate_probe_result(_read_document(path), expected_invocation)
            members.append(
                ControlFileSetMember(
                    name,
                    path,
                    result.result_sha256,
                    path.stat().st_size,
                    "eom://schemas/workflow/codex-compatibility-probe-result/1.0",
                    "application/json",
                )
            )
    artifact = ControlFileSetPublisher(engine, settings).publish(
        members=tuple(sorted(members, key=lambda member: member.file_name)),
        primary_file="report.json",
        artifact_type="control_codex_runtime_compatibility",
        manifest_version="codex-compatibility-file-set/1.0",
        idempotency_key=request.run_id,
        source_commit=request.source_commit,
        created_at=report.completed_at,
    )
    return PublishedCodexCompatibility(report, artifact)
