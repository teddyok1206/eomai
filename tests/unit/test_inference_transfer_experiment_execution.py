"""Temporary files and fake owner/CPU ports only; no actual model or publication."""

from __future__ import annotations

import ast
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import (
    InferenceTransferExperimentRequest,
    InferenceTransferExperimentResult,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.file_set_control_artifacts import PublishedControlFileSet
from eom_orchestrator.inference_transfer_experiment_artifacts import (
    InferenceTransferExperimentArtifactStore,
    compose_inference_transfer_experiment,
)
from eom_orchestrator.inference_transfer_experiment_execution import (
    ExperimentExecutionError,
    InferenceTransferExperimentExecution,
)
from eom_orchestrator.inference_transfer_experiment_ports import (
    CpuExperimentRunError,
    LocalExperimentInput,
    LocalExperimentPublication,
    PublishedExperimentResult,
)
from eom_orchestrator.inference_transfer_experiment_workspace import (
    MAX_EXPERIMENT_MEMBER_BYTES,
    RESULT_SCHEMA,
    ExperimentWorkspaceError,
    ProtectedExperimentWorkspace,
)
from eom_orchestrator.inference_transfer_snapshot_staging import (
    SnapshotReadFailure,
    SnapshotStagingError,
)
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_inference_transfer_experiment import FakeMeasuredBackend, run
from tests.unit.test_inference_transfer_snapshot_staging import ACTOR, Owner, command

EXECUTION = "embeddingexecution_" + "f" * 32


def pinned_result(
    request: InferenceTransferExperimentRequest,
    identity: str = EXECUTION,
    **updates: Any,
) -> InferenceTransferExperimentResult:
    # A fake CPU response fixture for validation tests, NOT genuine model evidence.
    # Nothing from this fixture is persisted or used to report a model/corpus PASS.
    body = run(request).model_dump(mode="json", exclude={"result_sha256"})
    body.update(
        backend_kind="PINNED_MODEL",
        actual_model_manifest_sha256=request.model_spec.manifest_sha256,
        execution_id=identity,
    )
    body.update(updates)
    return InferenceTransferExperimentResult.model_validate(
        body | {"result_sha256": content_sha256(body)}
    )


class Cpu:
    def __init__(self) -> None:
        self.calls: list[LocalExperimentInput] = []
        self.failure: Exception | None = None
        self.payload: Callable[[InferenceTransferExperimentRequest, str], bytes] = (
            lambda req, execution: (
                canonical_json_bytes(pinned_result(req, execution).model_dump(mode="json")) + b"\n"
            )
        )
        self.before_output: Callable[[LocalExperimentInput], None] | None = None

    def run(self, prepared: LocalExperimentInput) -> None:
        self.calls.append(prepared)
        if self.before_output is not None:
            self.before_output(prepared)
        if self.failure is not None:
            raise self.failure
        request = InferenceTransferExperimentRequest.model_validate_json(
            (prepared.workspace / "request.json").read_bytes()
        )
        target = prepared.workspace / "result.json"
        target.write_bytes(self.payload(request, prepared.execution_id))
        target.chmod(0o600)


class Commit:
    def __init__(self) -> None:
        self.calls: list[LocalExperimentPublication] = []
        self.failure: Exception | None = None
        self.mutate: Callable[[PublishedExperimentResult], PublishedExperimentResult] = (
            lambda value: value
        )

    def publish(self, prepared: LocalExperimentPublication) -> PublishedExperimentResult:
        self.calls.append(prepared)
        if self.failure is not None:
            raise self.failure
        assert prepared.member_sha256 == sha256_bytes(prepared.source.read_bytes())
        assert prepared.member_bytes == prepared.source.stat().st_size
        return self.mutate(
            PublishedExperimentResult(
                job_id="job_" + "1" * 32,
                result=ArtifactMemberPointer(
                    artifact_id="artifact_" + "2" * 32,
                    artifact_revision_id="rev_" + "3" * 32,
                    member_path="result.json",
                    schema_ref=RESULT_SCHEMA,
                    media_type="application/json",
                    sha256=prepared.member_sha256,
                ),
                manifest_sha256=sha("4"),
            )
        )


def execution(
    tmp_path: Path,
) -> tuple[InferenceTransferExperimentExecution, Owner, Cpu, Commit]:
    owner, cpu, commit = Owner(), Cpu(), Commit()
    return (
        InferenceTransferExperimentExecution(
            snapshot=owner,
            workspace=ProtectedExperimentWorkspace(tmp_path),
            cpu=cpu,
            commit=commit,
        ),
        owner,
        cpu,
        commit,
    )


def execute(app: InferenceTransferExperimentExecution, owner: Owner):
    return app.execute(ACTOR, command(owner), execution_id=EXECUTION, created_at=NOW)


def test_exact_stage_cpu_final_authorization_commit_and_completed_replay(tmp_path: Path) -> None:
    app, owner, cpu, commit = execution(tmp_path)

    def before_commit(value: PublishedExperimentResult) -> PublishedExperimentResult:
        assert owner.calls[-1][1].phase == "AUTHORIZE"
        return value

    commit.mutate = before_commit
    first = execute(app, owner)
    second = execute(app, owner)
    assert first.cpu_launch_count == 1 and second.cpu_launch_count == 0
    assert len(cpu.calls) == 1 and len(commit.calls) == 2
    assert first.published == second.published
    assert [request.phase for _, request in owner.calls] == ["PREPARE", "READ", "AUTHORIZE"] * 2
    publication = commit.calls[0]
    result = InferenceTransferExperimentResult.model_validate_json(publication.source.read_bytes())
    assert first.result_sha256 == result.result_sha256
    assert first.result_sha256 != first.published.result.sha256
    assert result.current_authorization == "NOT_VERIFIED_BY_HARNESS"
    assert result.human_transfer_review == "NOT_EVALUATED"
    assert result.production_activation == "NOT_PERFORMED"
    assert publication.source.name == "publication-result.json"
    assert not publication.source.read_bytes().endswith(b"\n")
    assert (tmp_path / EXECUTION).stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (tmp_path / EXECUTION).iterdir())


@pytest.mark.parametrize("missing", ["cpu", "commit"])
def test_missing_ports_fail_before_any_snapshot_or_file_work(tmp_path: Path, missing: str) -> None:
    app, owner, _cpu, _commit = execution(tmp_path)
    setattr(app, missing, None)
    with pytest.raises(ExperimentExecutionError, match="EXECUTION_UNAVAILABLE"):
        execute(app, owner)
    assert owner.calls == [] and list(tmp_path.iterdir()) == []


def test_public_composition_does_not_invent_missing_installed_cpu_or_owner(tmp_path: Path) -> None:
    owner = Owner()
    app = compose_inference_transfer_experiment(
        snapshot=owner, cpu=None, publisher=None, workspace_root=tmp_path, source_commit="a" * 40
    )
    with pytest.raises(ExperimentExecutionError, match="EXECUTION_UNAVAILABLE"):
        execute(app, owner)
    assert owner.calls == [] and list(tmp_path.iterdir()) == []


def test_insufficient_token_coverage_stays_explicit_diagnostic_not_quality_pass(
    tmp_path: Path,
) -> None:
    app, owner, cpu, _commit = execution(tmp_path)

    def overflow(request: InferenceTransferExperimentRequest, identity: str) -> bytes:
        backend = FakeMeasuredBackend()
        backend.count = lambda _text: 513
        body = run(request, backend).model_dump(mode="json", exclude={"result_sha256"})
        body.update(
            backend_kind="PINNED_MODEL",
            actual_model_manifest_sha256=request.model_spec.manifest_sha256,
            execution_id=identity,
        )
        result = InferenceTransferExperimentResult.model_validate(
            body | {"result_sha256": content_sha256(body)}
        )
        return canonical_json_bytes(result.model_dump(mode="json"))

    cpu.payload = overflow
    published = execute(app, owner)
    observed = InferenceTransferExperimentResult.model_validate_json(
        (tmp_path / EXECUTION / "publication-result.json").read_bytes()
    )
    assert published.cpu_launch_count == 1
    assert observed.status == "INSUFFICIENT_ENCODING_COVERAGE"
    assert observed.measurements.encoding_requests_started == 0
    assert observed.measurements.encoded_text_count == 0
    assert observed.query_results == () and observed.human_transfer_review == "NOT_EVALUATED"


def test_current_source_revocation_after_cpu_prevents_commit_and_replay_cpu(tmp_path: Path) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    cpu.before_output = lambda _prepared: setattr(
        owner, "failure", SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
    )
    owner.failure_phase = "AUTHORIZE"
    with pytest.raises(SnapshotReadFailure):
        execute(app, owner)
    assert len(cpu.calls) == 1 and commit.calls == []
    with pytest.raises(SnapshotReadFailure):
        execute(app, owner)
    assert len(cpu.calls) == 1 and commit.calls == []
    assert (tmp_path / EXECUTION / ".launch-completed").exists()


def test_known_completed_commit_failure_is_replayed_with_fresh_authorization(
    tmp_path: Path,
) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    commit.failure = RuntimeError("private storage exception must not appear in user error")
    with pytest.raises(ExperimentExecutionError, match="COMMIT_UNCERTAIN") as observed:
        execute(app, owner)
    assert str(observed.value) == "INFERENCE_EXPERIMENT_COMMIT_UNCERTAIN"
    commit.failure = None
    result = execute(app, owner)
    assert result.cpu_launch_count == 0 and len(cpu.calls) == 1 and len(commit.calls) == 2
    assert len([request for _, request in owner.calls if request.phase == "AUTHORIZE"]) == 2
    assert commit.calls[0] == commit.calls[1]


@pytest.mark.parametrize(
    "failure,outcome",
    [
        (CpuExperimentRunError("UNCERTAIN"), "UNCERTAIN"),
        (CpuExperimentRunError("KNOWN_FAILED"), "KNOWN_FAILED"),
        (TimeoutError("process could still be running"), "UNCERTAIN"),
    ],
)
def test_unconfirmed_or_failed_cpu_never_auto_resubmits(
    tmp_path: Path, failure: Exception, outcome: str
) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    cpu.failure = failure
    with pytest.raises(ExperimentExecutionError, match="EXECUTION_" + outcome):
        execute(app, owner)
    cpu.failure = None
    with pytest.raises(ExperimentExecutionError, match="EXECUTION_" + outcome):
        execute(app, owner)
    assert len(cpu.calls) == 1 and commit.calls == []
    assert [r.phase for _, r in owner.calls] == ["PREPARE", "READ"] * 2


def test_late_output_does_not_turn_uncertain_launch_into_retry_permission(tmp_path: Path) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    cpu.failure = CpuExperimentRunError("UNCERTAIN")
    with pytest.raises(ExperimentExecutionError, match="UNCERTAIN"):
        execute(app, owner)
    prepared = cpu.calls[0]
    request = InferenceTransferExperimentRequest.model_validate_json(
        (prepared.workspace / "request.json").read_bytes()
    )
    target = prepared.workspace / "result.json"
    target.write_bytes(canonical_json_bytes(pinned_result(request).model_dump(mode="json")))
    target.chmod(0o600)
    with pytest.raises(ExperimentExecutionError, match="UNCERTAIN"):
        execute(app, owner)
    assert len(cpu.calls) == 1 and commit.calls == []


@pytest.mark.parametrize(
    "updates",
    [
        {"request_sha256": sha("0")},
        {"model_manifest_sha256": sha("0"), "actual_model_manifest_sha256": sha("0")},
        {"view_recipe_sha256": sha("0")},
        {"execution_id": "embeddingexecution_" + "e" * 32},
        {"backend_kind": "TEST_ONLY", "actual_model_manifest_sha256": None},
        {"data_provenance": "TEST_ONLY_SYNTHETIC"},
    ],
)
def test_wrong_result_closure_or_fake_model_rejected_without_authorize_or_commit(
    tmp_path: Path, updates: dict[str, Any]
) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    cpu.payload = lambda req, identity: canonical_json_bytes(
        pinned_result(req, identity, **updates).model_dump(mode="json")
    )
    with pytest.raises(ExperimentExecutionError, match="RESULT_INVALID"):
        execute(app, owner)
    assert [r.phase for _, r in owner.calls] == ["PREPARE", "READ"] and commit.calls == []
    with pytest.raises(ExperimentExecutionError, match="KNOWN_FAILED"):
        execute(app, owner)
    assert len(cpu.calls) == 1


@pytest.mark.parametrize("shape", ["bad-hash", "duplicate", "pretty", "two-newlines", "array"])
def test_untrusted_result_serialization_rejected(tmp_path: Path, shape: str) -> None:
    app, owner, cpu, commit = execution(tmp_path)

    def payload(req: InferenceTransferExperimentRequest, identity: str) -> bytes:
        body = pinned_result(req, identity).model_dump(mode="json")
        if shape == "bad-hash":
            body["result_sha256"] = sha("0")
        canonical = canonical_json_bytes(body)
        if shape == "duplicate":
            return b'{"execution_id":"duplicate",' + canonical[1:]
        if shape == "pretty":
            return b" " + canonical
        if shape == "two-newlines":
            return canonical + b"\n\n"
        if shape == "array":
            return b"[]"
        return canonical

    cpu.payload = payload
    with pytest.raises(ExperimentExecutionError, match="RESULT_INVALID"):
        execute(app, owner)
    assert commit.calls == [] and owner.calls[-1][1].phase == "READ"


def test_same_execution_cannot_change_request_budget_or_actor(tmp_path: Path) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    execute(app, owner)
    original = (tmp_path / EXECUTION / "request.json").read_bytes()
    changed = replace(command(owner), budget=command(owner, batch_size=2).budget)
    with pytest.raises(ExperimentWorkspaceError, match="INPUT_PIN_MISMATCH"):
        app.execute(ACTOR, changed, execution_id=EXECUTION, created_at=NOW)
    assert len(cpu.calls) == len(commit.calls) == 1
    assert (tmp_path / EXECUTION / "request.json").read_bytes() == original


def test_concurrent_admission_loser_cannot_launch_second_cpu(tmp_path: Path) -> None:
    app, owner, cpu, commit = execution(tmp_path)

    def concurrent(_prepared: LocalExperimentInput) -> None:
        with pytest.raises(ExperimentExecutionError, match="UNCERTAIN"):
            execute(app, owner)

    cpu.before_output = concurrent
    execute(app, owner)
    assert len(cpu.calls) == len(commit.calls) == 1


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "writable", "oversized"])
def test_unsafe_result_member_cannot_reach_owner_commit(tmp_path: Path, attack: str) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    normal = cpu.run

    def unsafe(prepared: LocalExperimentInput) -> None:
        normal(prepared)
        target = prepared.workspace / "result.json"
        if attack in {"symlink", "hardlink"}:
            backing = prepared.workspace / "untrusted-backing.json"
            target.rename(backing)
            if attack == "symlink":
                target.symlink_to(backing)
            else:
                os.link(backing, target)
        elif attack == "writable":
            target.chmod(0o666)
        else:
            with target.open("r+b") as handle:
                handle.truncate(MAX_EXPERIMENT_MEMBER_BYTES + 1)

    cpu.run = unsafe  # type: ignore[method-assign]
    with pytest.raises(ExperimentExecutionError, match="RESULT_INVALID"):
        execute(app, owner)
    assert commit.calls == [] and owner.calls[-1][1].phase == "READ"


def test_result_fd_named_inode_replacement_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, owner, _cpu, commit = execution(tmp_path)
    old_read = os.read
    replaced = False

    def read(fd: int, length: int) -> bytes:
        nonlocal replaced
        data = old_read(fd, length)
        target = tmp_path / EXECUTION / "result.json"
        if data.startswith(b'{"actual_model_manifest_sha256"') and not replaced:
            replaced = True
            target.rename(target.with_name("original-result.json"))
            target.write_bytes(data)
            target.chmod(0o600)
        return data

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(ExperimentExecutionError, match="RESULT_INVALID"):
        execute(app, owner)
    assert replaced and commit.calls == []


def test_completed_result_replacement_fails_without_model_or_publication(tmp_path: Path) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    execute(app, owner)
    target = tmp_path / EXECUTION / "result.json"
    target.write_bytes(target.read_bytes().removesuffix(b"\n"))
    with pytest.raises(ExperimentExecutionError, match="RESULT_INVALID"):
        execute(app, owner)
    assert len(cpu.calls) == len(commit.calls) == 1


def test_cpu_cannot_rewrite_the_canonical_local_input_even_without_semantic_change(
    tmp_path: Path,
) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    normal = cpu.run

    def write_input(prepared: LocalExperimentInput) -> None:
        normal(prepared)
        target = prepared.workspace / "request.json"
        target.write_bytes(target.read_bytes() + b"\n")

    cpu.run = write_input  # type: ignore[method-assign]
    with pytest.raises(ExperimentExecutionError, match="RESULT_INVALID"):
        execute(app, owner)
    assert commit.calls == [] and owner.calls[-1][1].phase == "READ"


@pytest.mark.parametrize(
    "attack", ["absent-start", "both-terminal", "completed-hash", "private-mode"]
)
def test_tampered_completion_state_never_reexecutes_cpu(tmp_path: Path, attack: str) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    execute(app, owner)
    path = tmp_path / EXECUTION
    if attack == "absent-start":
        (path / ".launch-started").unlink()
    elif attack == "both-terminal":
        (path / ".launch-failed").write_bytes(b"")
        (path / ".launch-failed").chmod(0o600)
    elif attack == "completed-hash":
        (path / ".launch-completed").write_bytes(b"invalid")
    else:
        path.chmod(0o755)
    with pytest.raises(ExperimentWorkspaceError):
        execute(app, owner)
    assert len(cpu.calls) == len(commit.calls) == 1


def test_existing_input_named_inode_replacement_fails_before_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    execute(app, owner)
    old_read = os.read
    replaced = False

    def read(fd: int, size: int) -> bytes:
        nonlocal replaced
        data = old_read(fd, size)
        if b'"schema_version":"inference-transfer-experiment-request/1.0"' in data and not replaced:
            replaced = True
            target = tmp_path / EXECUTION / "request.json"
            target.rename(target.with_name("historical-request.json"))
            target.write_bytes(data)
            target.chmod(0o600)
        return data

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(ExperimentWorkspaceError, match="MEMBER_CHANGED"):
        execute(app, owner)
    assert replaced and len(cpu.calls) == len(commit.calls) == 1


def test_partial_publication_write_never_records_completed_and_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, owner, _cpu, commit = execution(tmp_path)
    old_write = app.workspace._write

    def write(path: Path, name: str, data: bytes) -> None:
        if name == "publication-result.json":
            raise ExperimentWorkspaceError("INFERENCE_EXPERIMENT_MEMBER_WRITE_FAILED")
        old_write(path, name, data)

    monkeypatch.setattr(app.workspace, "_write", write)
    with pytest.raises(ExperimentExecutionError, match="RESULT_INVALID"):
        execute(app, owner)
    assert not (tmp_path / EXECUTION / ".launch-completed").exists()
    assert (tmp_path / EXECUTION / ".launch-failed").exists() and commit.calls == []


@pytest.mark.parametrize("attack", ["symlink", "writable", "relative", "nas"])
def test_unprotected_workspace_fails_before_cpu(tmp_path: Path, attack: str) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    if attack == "symlink":
        child = tmp_path / "safe"
        child.mkdir(mode=0o700)
        root = tmp_path / "link"
        root.symlink_to(child, target_is_directory=True)
    elif attack == "writable":
        root = tmp_path / "writable"
        root.mkdir(mode=0o777)
        root.chmod(0o777)
    elif attack == "relative":
        root = Path("relative")
    else:
        root = Path("/mnt/nas/eom/no-experiment-write")
    app.workspace = ProtectedExperimentWorkspace(root)
    with pytest.raises(ExperimentWorkspaceError):
        execute(app, owner)
    assert cpu.calls == commit.calls == []


def test_declared_input_budget_enforced_before_cpu(tmp_path: Path) -> None:
    app, owner, cpu, commit = execution(tmp_path)
    with pytest.raises(SnapshotStagingError, match="BUDGET_EXCEEDED"):
        app.execute(
            ACTOR, command(owner, maximum_input_bytes=1024), execution_id=EXECUTION, created_at=NOW
        )
    assert cpu.calls == commit.calls == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "field", ["sha256", "schema_ref", "member_path", "job_id", "manifest_sha256"]
)
def test_owner_commit_receipt_is_not_trusted_without_typed_exact_closure(
    tmp_path: Path, field: str
) -> None:
    app, owner, cpu, commit = execution(tmp_path)

    def mutate(value: PublishedExperimentResult) -> PublishedExperimentResult:
        if field in {"job_id", "manifest_sha256"}:
            return replace(value, **{field: "invalid"})
        changed = {"sha256": sha("0"), "schema_ref": "eom://wrong/1", "member_path": "other.json"}
        return replace(value, result=value.result.model_copy(update={field: changed[field]}))

    commit.mutate = mutate
    with pytest.raises(ExperimentExecutionError, match="COMMIT_RECEIPT_INVALID"):
        execute(app, owner)
    assert len(cpu.calls) == len(commit.calls) == 1


def test_reuses_single_existing_file_set_owner_with_exact_member_and_key(tmp_path: Path) -> None:
    app, owner, _cpu, commit = execution(tmp_path)
    execute(app, owner)
    observed: dict[str, Any] = {}

    class Publisher:
        def publish(self, **kwargs: Any) -> PublishedControlFileSet:
            observed.update(kwargs)
            return PublishedControlFileSet(
                job_id="job_" + "1" * 32,
                artifact_id="artifact_" + "2" * 32,
                artifact_revision_id="rev_" + "3" * 32,
                primary_file="result.json",
                primary_sha256=kwargs["members"][0].sha256,
                manifest_sha256=sha("4"),
                nas_path="NOT_WRITTEN_FAKE_OWNER",
            )

    adapter = InferenceTransferExperimentArtifactStore(Publisher(), source_commit="a" * 40)  # type: ignore[arg-type]
    pointer = adapter.publish(commit.calls[0])
    assert len(observed["members"]) == 1
    member = observed["members"][0]
    assert (
        member.file_name == observed["primary_file"] == pointer.result.member_path == "result.json"
    )
    assert member.source == commit.calls[0].source and member.schema_ref == RESULT_SCHEMA
    assert observed["idempotency_key"] == "inference-transfer-experiment:" + "f" * 32
    assert observed["source_commit"] == "a" * 40 and observed["created_at"] == NOW
    assert observed["artifact_type"] == "control_inference_transfer_experiment"


def test_application_and_contract_ports_do_not_import_cpu_sql_nas_or_subprocess() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("ports", "execution", "workspace"):
        tree = ast.parse(
            (
                root
                / "services/orchestrator/eom_orchestrator"
                / f"inference_transfer_experiment_{name}.py"
            ).read_text()
        )
        imports = {
            (node.module if isinstance(node, ast.ImportFrom) else alias.name).split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
            if not isinstance(node, ast.ImportFrom) or node.module is not None
        }
        assert not imports & {
            "torch",
            "transformers",
            "numpy",
            "sqlalchemy",
            "subprocess",
            "eom_catalog_service",
        }
