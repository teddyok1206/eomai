from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identifiers import sha256_file
from eom_orchestrator import codex_runtime_compatibility as application
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import PublishedControlFileSet
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker import CodexWorkerAdapter, PreparedWorkerWorkspace, WorkerRun
from eom_orchestrator.worker_registry import WorkerRegistry
from eom_workflow.codex_compatibility import (
    CodexCompatibilityCase,
    CodexCompatibilityRequest,
    CodexCompatibilityRuntime,
)
from eom_workflow.control_plane import ReasoningEffort
from sqlalchemy import Engine

NOW = datetime(2026, 10, 10, 5, 0, tzinfo=UTC)
COMMIT = "a" * 40


def _request(*, slots: tuple[str, ...] = ("01", "02")) -> CodexCompatibilityRequest:
    return CodexCompatibilityRequest(
        run_id="codexcompat_" + "1" * 32,
        source_commit=COMMIT,
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        max_model_calls=len(slots),
        cases=tuple(
            CodexCompatibilityCase(
                case_id="compatcase_" + f"{index + 2:032x}",
                slot_id=slot,  # type: ignore[arg-type]
                binding_id="authbinding_" + f"{int(slot):032x}",
                assignment_revision_id=None,
                expected_resource_version=1,
                model="gpt-6.1-sol",
                reasoning_effort=ReasoningEffort.HIGH,
            )
            for index, slot in enumerate(slots)
        ),
    )


class _Session:
    def __init__(self, harness: _Harness) -> None:
        self.harness = harness

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def get(self, _model: object, identity: str) -> Any:
        self.harness.events.append("binding")
        return self.harness.bindings.get(identity)

    def scalars(self, _query: object) -> tuple[Any, ...]:
        return tuple(self.harness.bindings.values())


class _Fence:
    def __init__(self, harness: _Harness) -> None:
        self.harness = harness

    def __enter__(self) -> _Fence:
        self.harness.events.append("fence-enter")
        return self

    def __exit__(self, *_: object) -> None:
        self.harness.events.append("fence-exit")

    def assert_quiescent(self) -> None:
        self.harness.events.append("fence")
        if self.harness.fence_error:
            raise self.harness.fence_error


class _Guard:
    def __init__(self, harness: _Harness) -> None:
        self.harness = harness
        self.runtime = CodexCompatibilityRuntime(
            cli_version="0.160.0",
            cli_launcher_sha256="sha256:" + "2" * 64,
            cli_binary_sha256="sha256:" + "3" * 64,
            worker_exec_sha256="sha256:" + "4" * 64,
            contract_sha256="sha256:" + "5" * 64,
        )

    def assert_current(self) -> None:
        self.harness.events.append("runtime")


class _Worker:
    def __init__(self, harness: _Harness) -> None:
        self.harness = harness
        self.calls: list[dict[str, Any]] = []
        self.preparations: list[dict[str, Any]] = []
        self.exit_code = 0
        self.overrides: dict[str, object] = {}
        self.interrupt = False
        self.expire_after_first = False

    def prepare_structured_workspace(self, **kwargs: Any) -> PreparedWorkerWorkspace:
        self.preparations.append(kwargs)
        workspace = self.harness.settings.workspace_root / kwargs["job_id"]
        workspace.mkdir()
        (workspace / "worker-input.json").write_text(json.dumps(kwargs["input_document"]))
        schema = workspace / "worker-result.schema.json"
        schema.write_text(json.dumps(kwargs["output_schema"]))
        prompt = workspace / "prompt.txt"
        prompt.write_text(kwargs["prompt_text"])
        return PreparedWorkerWorkspace(kwargs["job_id"], workspace, schema, prompt)

    def run_prepared(self, **kwargs: Any) -> WorkerRun:
        self.harness.events.append("run")
        self.calls.append(kwargs)
        if self.interrupt:
            raise RuntimeError("simulated uncertain worker handoff")
        prepared = kwargs["prepared"]
        inputs = json.loads((prepared.workspace / "worker-input.json").read_text())
        document = {
            "schema_version": "codex-compatibility-probe-result/1.0",
            **{key: inputs[key] for key in ("run_id", "case_id", "request_sha256")},
            "arithmetic_sum": 43,
            "rectangle_count": 1,
            "outline_circle_count": 1,
            "left_shape": "square",
            "right_shape": "circle",
            **self.overrides,
        }
        result = prepared.workspace / "result.json"
        result.write_text(json.dumps(document))
        if self.expire_after_first:
            self.harness.now = NOW + timedelta(hours=1)
        return WorkerRun(
            self.exit_code,
            result,
            prepared.workspace / "stdout.log",
            prepared.workspace / "stderr.log",
            "synthetic-no-systemd.service",
        )


class _Publisher:
    def __init__(self, harness: _Harness) -> None:
        self.harness = harness

    def publish(self, **kwargs: Any) -> PublishedControlFileSet:
        self.harness.publications.append(kwargs)
        members = kwargs["members"]
        names = tuple(member.file_name for member in members)
        assert names == tuple(sorted(set(names))), "real publisher requires sorted unique members"
        assert kwargs["artifact_type"].startswith("control_")
        assert kwargs["primary_file"] == "report.json"
        for member in members:
            assert member.sha256 == sha256_file(member.source)
            assert member.bytes == member.source.stat().st_size
            assert member.media_type == "application/json"
        root = self.harness.settings.staging_root / self.harness.request.run_id
        return PublishedControlFileSet(
            "job_" + "a" * 32,
            "artifact_" + "b" * 32,
            "artrev_" + "c" * 32,
            "report.json",
            sha256_file(root / "report.json"),
            "sha256:" + "d" * 64,
            "/not-a-real-nas-path",
        )


@dataclass
class _Harness:
    settings: Settings
    request: CodexCompatibilityRequest
    engine: Engine = field(default_factory=lambda: cast(Engine, object()))
    events: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)
    publications: list[dict[str, Any]] = field(default_factory=list)
    fence_error: ControlPlaneError | None = None
    now: datetime = NOW
    worker: _Worker = field(init=False)
    guard: _Guard = field(init=False)

    def __post_init__(self) -> None:
        self.worker = _Worker(self)
        self.guard = _Guard(self)
        self.bindings = {
            case.binding_id: SimpleNamespace(
                binding_id=case.binding_id,
                worker_slot_id=case.slot_id,
                current_assignment_revision_id=case.assignment_revision_id,
                resource_version=case.expected_resource_version,
                state="READY",
            )
            for case in self.request.cases
        }

    @property
    def root(self) -> Path:
        return self.settings.staging_root / self.request.run_id

    def run(self) -> application.PublishedCodexCompatibility:
        return application.run_codex_compatibility(
            self.engine,
            self.request,
            settings=self.settings,
            worker=cast(CodexWorkerAdapter, self.worker),
        )


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Harness:
    staging, workspace = tmp_path / "staging", tmp_path / "workspace"
    staging.mkdir()
    workspace.mkdir()
    value = _Harness(
        Settings(staging_root=staging, workspace_root=workspace, runtime_source_commit=COMMIT),
        _request(),
    )

    class _Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> _Clock:
            assert tz is UTC
            return cls.fromisoformat(value.now.isoformat())

    slots = tuple(SimpleNamespace(slot_id=f"{index:02d}", enabled=True) for index in range(1, 7))
    monkeypatch.setattr(application, "datetime", _Clock)
    monkeypatch.setattr(application, "build_session_factory", lambda _: lambda: _Session(value))
    monkeypatch.setattr(application, "CodexCompatibilityMaintenance", lambda _: _Fence(value))
    monkeypatch.setattr(application, "observe_compatibility_runtime_guard", lambda: value.guard)
    monkeypatch.setattr(
        WorkerRegistry,
        "load",
        lambda _: SimpleNamespace(config=SimpleNamespace(slots=slots)),
    )
    monkeypatch.setattr(application, "ControlFileSetPublisher", lambda *_: _Publisher(value))
    return value


def test_ordered_passes_pin_inputs_hashes_and_publish_only_small_canonical_members(
    harness: _Harness,
) -> None:
    result = harness.run()

    assert result.report.model_calls == 2
    assert result.report.quality_evaluated is False
    assert result.report.scope == "LIVE_EXECUTION_SMOKE"
    assert tuple(case.case_id for case in result.report.cases) == tuple(
        case.case_id for case in harness.request.cases
    )
    assert all(case.status == "PASS" for case in result.report.cases)
    assert len(harness.worker.calls) == 2
    assert [call["timeout_seconds"] for call in harness.worker.calls] == [1800, 1800]
    assert harness.events == [
        "fence-enter",
        "fence",
        "runtime",
        "binding",
        "run",
        "fence",
        "runtime",
        "binding",
        "run",
        "fence-exit",
    ]
    for case in result.report.cases:
        assert case.result_sha256 == sha256_file(harness.root / f"{case.case_id}.output.json")
        marker = json.loads((harness.root / f"{case.case_id}.started.json").read_text())
        assert marker["invocation_sha256"] == case.invocation_sha256
        assert marker["job_id"] == case.job_id
    assert result.artifact.primary_sha256 == sha256_file(harness.root / "report.json")
    assert harness.publications[0]["source_commit"] == COMMIT


@pytest.mark.parametrize(
    ("exit_code", "override", "error_code"),
    [
        (9, {}, "WORKER_EXEC_FAILED"),
        (0, {"arithmetic_sum": 44}, "RESULT_CONTENT_MISMATCH"),
        (0, {"left_shape": "circle"}, "RESULT_CONTENT_MISMATCH"),
        (0, {"request_sha256": "sha256:" + "f" * 64}, "RESULT_CONTENT_MISMATCH"),
        (0, {"arithmetic_sum": "43"}, "WORKER_RESULT_INVALID"),
        (0, {"untrusted_extra": "not retained"}, "WORKER_RESULT_INVALID"),
    ],
)
def test_first_failure_stops_remaining_cases_and_counts_one_actual_call(
    harness: _Harness, exit_code: int, override: dict[str, object], error_code: str
) -> None:
    harness.worker.exit_code = exit_code
    harness.worker.overrides = override

    report = harness.run().report

    assert report.model_calls == len(harness.worker.calls) == 1
    assert report.cases[0].status == "FAIL" and report.cases[0].error_code == error_code
    assert report.cases[1].status == "NOT_RUN" and report.cases[1].error_code == "PREVIOUS_FAILURE"
    assert report.cases[1].invocation_sha256 is None


def test_complete_report_replay_never_reenters_execution_fence(harness: _Harness) -> None:
    first = harness.run()
    events = tuple(harness.events)

    second = harness.run()

    assert second.report == first.report
    assert len(harness.worker.calls) == 2
    assert tuple(harness.events) == events
    assert len(harness.publications) == 2  # Publication's own idempotent replay boundary.


def test_completed_checkpoints_resume_without_extra_model_calls(harness: _Harness) -> None:
    first = harness.run()
    (harness.root / "report.json").unlink()

    second = harness.run()

    assert second.report.cases == first.report.cases
    assert second.report.model_calls == 2
    assert len(harness.worker.calls) == 2


def test_started_marker_without_checkpoint_is_uncertain_and_never_reexecuted(
    harness: _Harness,
) -> None:
    harness.worker.interrupt = True
    with pytest.raises(RuntimeError, match="uncertain"):
        harness.run()
    assert len(harness.worker.calls) == 1
    harness.worker.interrupt = False

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_EXECUTION_UNCERTAIN"
    assert len(harness.worker.calls) == 1
    assert not harness.publications


def test_replay_refuses_changed_runtime_epoch_without_inference(harness: _Harness) -> None:
    harness.run()
    (harness.root / "report.json").unlink()
    harness.guard.runtime = harness.guard.runtime.model_copy(
        update={"cli_binary_sha256": "sha256:" + "f" * 64}
    )

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_CHANGED"
    assert len(harness.worker.calls) == 2


def test_changed_binding_refuses_before_launch_after_fence_and_runtime_checks(
    harness: _Harness,
) -> None:
    harness.bindings[harness.request.cases[0].binding_id].resource_version = 2

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_BINDING_CHANGED"
    assert harness.events == ["fence-enter", "fence", "runtime", "binding", "fence-exit"]
    assert not harness.worker.calls
    assert not tuple(harness.root.glob("*.started.json"))


@pytest.mark.parametrize("old_assignment", [None, "authassignrev_" + "d" * 32])
def test_assignment_change_with_same_binding_and_resource_version_denies_launch(
    harness: _Harness, old_assignment: str | None
) -> None:
    case = harness.request.cases[0].model_copy(update={"assignment_revision_id": old_assignment})
    harness.request = harness.request.model_copy(
        update={"cases": (case, *harness.request.cases[1:])}
    )
    binding = harness.bindings[case.binding_id]
    binding.current_assignment_revision_id = "authassignrev_" + "e" * 32
    assert binding.binding_id == case.binding_id
    assert binding.resource_version == case.expected_resource_version

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_BINDING_CHANGED"
    assert harness.events == ["fence-enter", "fence", "runtime", "binding", "fence-exit"]
    assert not harness.worker.calls
    assert not tuple(harness.root.glob("*.started.json"))


def test_busy_fence_refuses_before_binding_or_worker(harness: _Harness) -> None:
    harness.fence_error = ControlPlaneError("CODEX_COMPATIBILITY_JOB_BUSY", "busy")

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CODEX_COMPATIBILITY_JOB_BUSY"
    assert "binding" not in harness.events and not harness.worker.calls


def test_expiration_during_run_leaves_remaining_case_unexecuted(harness: _Harness) -> None:
    harness.worker.expire_after_first = True

    report = harness.run().report

    assert report.model_calls == len(harness.worker.calls) == 1
    assert report.cases[0].status == "PASS"
    assert report.cases[1].status == "NOT_RUN"
    assert report.cases[1].error_code == "REQUEST_EXPIRED"


def test_already_expired_request_never_starts_inference(harness: _Harness) -> None:
    harness.now = NOW + timedelta(hours=1)

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_REQUEST_EXPIRED"
    assert not harness.worker.calls and not harness.publications


def test_conflicting_request_with_same_run_id_refuses(harness: _Harness) -> None:
    harness.run()
    changed = harness.request.model_dump(mode="python")
    changed["cases"] = tuple(
        case.model_copy(update={"model": "gpt-6-sol"}) for case in harness.request.cases
    )
    harness.request = CodexCompatibilityRequest.model_validate(changed)

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_REPLAY_CONFLICT"
    assert len(harness.worker.calls) == 2


def test_tampered_output_hash_refuses_publication_on_replay(harness: _Harness) -> None:
    harness.run()
    output = harness.root / f"{harness.request.cases[0].case_id}.output.json"
    output.write_bytes(b"tampered")

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_LEDGER_INVALID"
    assert len(harness.publications) == 1 and len(harness.worker.calls) == 2


def test_replay_revalidates_pass_facts_even_when_tampered_hashes_are_self_consistent(
    harness: _Harness,
) -> None:
    harness.run()
    output = harness.root / f"{harness.request.cases[0].case_id}.output.json"
    document = json.loads(output.read_text())
    document["arithmetic_sum"] = 44
    output.write_text(json.dumps(document))
    report_path = harness.root / "report.json"
    report = json.loads(report_path.read_text())
    report["cases"][0]["result_sha256"] = sha256_file(output)
    report_path.write_text(json.dumps(report))

    with pytest.raises(ValueError, match="incorrect"):
        harness.run()

    assert len(harness.publications) == 1 and len(harness.worker.calls) == 2


def test_replay_recomputes_invocation_hash_from_exact_request_pins(harness: _Harness) -> None:
    harness.run()
    report_path = harness.root / "report.json"
    report = json.loads(report_path.read_text())
    report["cases"][0]["invocation_sha256"] = "sha256:" + "f" * 64
    report_path.write_text(json.dumps(report))

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_LEDGER_INVALID"
    assert len(harness.publications) == 1 and len(harness.worker.calls) == 2


def test_partial_checkpoint_cannot_change_execution_identity(harness: _Harness) -> None:
    harness.run()
    (harness.root / "report.json").unlink()
    checkpoint = harness.root / f"{harness.request.cases[0].case_id}.result.json"
    document = json.loads(checkpoint.read_text())
    document["job_id"] = "job_" + "f" * 32
    checkpoint.write_text(json.dumps(document))

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_LEDGER_INVALID"
    assert len(harness.worker.calls) == 2


def test_checkpoint_permission_change_refuses_replay(harness: _Harness) -> None:
    harness.run()
    (harness.root / "request.json").chmod(0o640)

    with pytest.raises(ValueError, match="checkpoint"):
        harness.run()

    assert len(harness.worker.calls) == 2


def test_checkpoint_symlink_is_not_dereferenced(harness: _Harness) -> None:
    harness.run()
    request = harness.root / "request.json"
    original = request.read_bytes()
    backup = harness.settings.staging_root / "untrusted-request.json"
    backup.write_bytes(original)
    backup.chmod(0o600)
    request.unlink()
    request.symlink_to(backup)

    with pytest.raises(OSError):
        harness.run()

    assert backup.read_bytes() == original
    assert len(harness.worker.calls) == 2


def test_release_mismatch_refuses_before_creating_ledger(harness: _Harness) -> None:
    harness.request = harness.request.model_copy(update={"source_commit": "b" * 40})

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_RELEASE_MISMATCH"
    assert not harness.root.exists() and not harness.worker.calls


def test_unsafe_ledger_directory_is_rejected_before_model_call(harness: _Harness) -> None:
    harness.root.mkdir(mode=0o755)

    with pytest.raises(ControlPlaneError) as error:
        harness.run()

    assert error.value.code == "CONTROL_COMPATIBILITY_LEDGER_INVALID"
    assert not harness.worker.calls


def test_fresh_ledger_under_setgid_staging_is_private(harness: _Harness) -> None:
    harness.settings.staging_root.chmod(0o2770)

    harness.run()

    assert stat.S_IMODE(harness.root.stat().st_mode) == 0o700
    assert (harness.root / "request.json").stat().st_uid == os.geteuid()


@pytest.mark.parametrize("slot", ["05", "06"])
def test_analysis_slots_keep_existing_fixed_two_hour_execution_ceiling(
    harness: _Harness, slot: str
) -> None:
    harness.request = _request(slots=(slot,))
    harness.__post_init__()

    assert harness.run().report.cases[0].status == "PASS"
    assert harness.worker.calls[0]["timeout_seconds"] == 7200


def test_prepare_request_pins_current_binding_and_preserves_explicit_pair_order(
    harness: _Harness,
) -> None:
    request = application.prepare_codex_compatibility_request(
        harness.engine,
        models=("gpt-6-sol", "gpt-6.1-sol"),
        reasoning_efforts=(ReasoningEffort.MEDIUM, ReasoningEffort.HIGH),
        slot_ids=("02", "01"),
        source_commit=COMMIT,
        now=NOW,
    )

    assert request.max_model_calls == len(request.cases) == 8
    assert [(case.model, case.reasoning_effort, case.slot_id) for case in request.cases] == [
        (model, effort, slot)
        for model in ("gpt-6-sol", "gpt-6.1-sol")
        for effort in ("medium", "high")
        for slot in ("02", "01")
    ]
    assert all(case.expected_resource_version == 1 for case in request.cases)
    assert all(case.assignment_revision_id is None for case in request.cases)
    assert request.source_commit == COMMIT


def test_prepare_request_pins_exact_non_null_account_assignment(harness: _Harness) -> None:
    assignment = "authassignrev_" + "d" * 32
    harness.bindings[
        harness.request.cases[0].binding_id
    ].current_assignment_revision_id = assignment

    request = application.prepare_codex_compatibility_request(
        harness.engine,
        models=("gpt-6.1-sol",),
        reasoning_efforts=(ReasoningEffort.HIGH,),
        slot_ids=("01", "02"),
        source_commit=COMMIT,
        now=NOW,
    )

    assert tuple(case.assignment_revision_id for case in request.cases) == (assignment, None)


@pytest.mark.parametrize("bad_kind", ["duplicate", "missing", "disabled"])
def test_prepare_request_refuses_duplicate_or_unavailable_inputs(
    harness: _Harness, bad_kind: str
) -> None:
    slots = ("01", "01") if bad_kind == "duplicate" else ("01", "02")
    if bad_kind == "missing":
        harness.bindings.pop(harness.request.cases[1].binding_id)
    elif bad_kind == "disabled":
        harness.bindings[harness.request.cases[1].binding_id].state = "DISABLED"

    with pytest.raises(ControlPlaneError):
        application.prepare_codex_compatibility_request(
            harness.engine,
            models=("gpt-6.1-sol",),
            reasoning_efforts=(ReasoningEffort.HIGH,),
            slot_ids=slots,
            source_commit=COMMIT,
            now=NOW,
        )

    assert not harness.worker.calls
