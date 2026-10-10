"""Fake publication and control-owner transactions only, never DB/NAS/models."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator import inference_transfer_bootstrap as bootstrap
from eom_orchestrator.control_artifacts import PublishedControlArtifact
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, ProtocolVersionRecord
from eom_orchestrator.preset_lifecycle import create_execution_preset_draft
from eom_workflow import compile_definition
from eom_workflow.control_plane import (
    ControlArtifactPointer,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
    InstructionBundleManifest,
)
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import WorkflowDefinitionRecord

from tests.unit.inference_transfer_bootstrap_fixtures import (
    PLATFORM_BYTES,
    RUBRIC_BYTES,
    bootstrap_manifest,
)


class FakeSession:
    def __init__(self) -> None:
        self.records: dict[tuple[type[object], str], Any] = {}
        self.artifacts: dict[tuple[type[object], str], Any] = {}
        self.logical: Any = None
        self.revisions: list[Any] = []
        self.definition: Any = None
        self.statements: list[Any] = []
        self.protocol_additions: list[ProtocolVersionRecord] = []
        self.flushes = 0

    def get(self, model: type[object], key: str) -> Any:
        return self.artifacts.get((model, key), self.records.get((model, key)))

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        model = statement.column_descriptions[0]["entity"]
        if model is ExecutionPresetRecord:
            return self.logical
        if model is WorkflowDefinitionRecord:
            return self.definition
        raise AssertionError("unexpected bootstrap lookup")

    def scalars(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        assert statement.column_descriptions[0]["entity"] is ExecutionPresetRevisionRecord
        return self.revisions[:3]

    def execute(self, statement: Any) -> None:
        self.statements.append(statement)
        assert "pg_advisory_xact_lock" in str(statement)

    def add(self, record: ProtocolVersionRecord) -> None:
        assert isinstance(record, ProtocolVersionRecord)
        key = (ProtocolVersionRecord, record.version)
        assert key not in self.records
        self.records[key] = record
        self.protocol_additions.append(record)

    def flush(self) -> None:
        self.flushes += 1


class FakeSessions:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def begin(self) -> Iterator[FakeSession]:
        snapshot = deepcopy((self.session.records, self.session.logical, self.session.revisions))
        try:
            yield self.session
        except Exception:
            self.session.records, self.session.logical, self.session.revisions = snapshot
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


class FakePublisher:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.history: dict[str, tuple[dict[str, Any], PublishedControlArtifact]] = {}
        self.calls: list[dict[str, Any]] = []
        self.fail_after_commit: int | None = None

    def publish_bytes(self, **kwargs: Any) -> PublishedControlArtifact:
        self.calls.append(kwargs)
        key = kwargs["idempotency_key"]
        if key in self.history:
            prior, result = self.history[key]
            assert prior == kwargs, "exact publisher history must be reused"
            return result
        number = len(self.history) + 1
        pointer = ControlArtifactPointer(
            artifact_id=f"artifact_{number:032x}",
            artifact_revision_id=f"rev_{number:032x}",
            sha256=sha256_bytes(kwargs["payload"]),
            logical_name=kwargs["logical_name"],
            schema_ref=kwargs["schema_ref"],
            media_type=kwargs["media_type"],
        )
        result = PublishedControlArtifact(f"job_{number:032x}", pointer, "sha256:" + "1" * 64)
        self.history[key] = (kwargs, result)
        self.session.artifacts[(ArtifactRecord, pointer.artifact_id)] = SimpleNamespace(
            approved=True
        )
        self.session.artifacts[(ArtifactRevisionRecord, pointer.artifact_revision_id)] = (
            SimpleNamespace(
                approved=True,
                logical_artifact_id=pointer.artifact_id,
                content_hash=pointer.sha256,
                manifest={
                    "files": [
                        {
                            "file_name": pointer.logical_name,
                            "sha256": pointer.sha256,
                            "schema_ref": pointer.schema_ref,
                            "media_type": pointer.media_type,
                        }
                    ]
                },
                result={
                    "source_commit": kwargs["source_commit"],
                    "created_at_utc": kwargs["created_at"].isoformat().replace("+00:00", "Z"),
                },
            )
        )
        if self.fail_after_commit == number:
            self.fail_after_commit = None
            raise OSError("synthetic interrupted publication acknowledgement")
        return result


def fixture(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    compiled = compile_definition(
        Path("config/workflows/item-inference-transfer-comparison.v1.yaml"), {"support"}
    )
    manifest = bootstrap_manifest(workflow_definition_sha256=compiled.sha256)
    session = FakeSession()
    session.definition = SimpleNamespace(
        canonical_definition=compiled.as_dict(),
        source_path="installed://synthetic-definition",
        definition_hash=compiled.sha256,
    )
    session.records[(ProtocolVersionRecord, manifest.workflow_role_schema_version)] = (
        SimpleNamespace(
            schema_sha256=role_schema_bundle_hash(manifest.workflow_role_schema_version)
        )
    )
    session.records[
        (WorkerCapacityPolicyRevisionRecord, manifest.capacity.capacity_policy_revision_id)
    ] = SimpleNamespace(
        capacity_policy_id=manifest.capacity.capacity_policy_id,
        schema_version=manifest.capacity.schema_version,
        state="RELEASED",
        content_sha256=manifest.capacity.content_sha256,
    )
    session.records[(WorkerCapacityPolicyRecord, manifest.capacity.capacity_policy_id)] = (
        SimpleNamespace(
            state="ACTIVE", current_revision_id=manifest.capacity.capacity_policy_revision_id
        )
    )
    value = SimpleNamespace(
        session=session,
        sessions=FakeSessions(session),
        publisher=FakePublisher(session),
        manifest=manifest,
        operator="operator_" + "9" * 32,
        observations=[],
        authorizations=[],
        draft_creations=0,
        release_calls=0,
        evaluations=[],
        available=True,
        revoked=False,
    )

    def authorize(operator: str, action: str) -> None:
        value.authorizations.append((operator, action))
        if value.revoked:
            raise ControlPlaneError("CONTROL_OPERATOR_FORBIDDEN", "synthetic revoked operator")

    value.authorize = authorize

    def options(actual_session: Any, **kwargs: Any) -> Any:
        assert actual_session is session
        assert (
            kwargs["capacity_policy_revision_id"] == manifest.capacity.capacity_policy_revision_id
        )
        assert kwargs["worker_pool_key"] == "customer-support" and kwargs["role"] == "support"
        value.observations.append(kwargs["observed_at"])
        return (manifest.model_candidate,) if value.available else ()

    def record_bundle(actual_session: Any, **kwargs: Any) -> Any:
        assert actual_session is session
        instruction = InstructionBundleManifest.model_validate(kwargs["document"])
        pointer = kwargs["manifest_artifact"]
        row = SimpleNamespace(
            **instruction.model_dump(),
            canonical_document=instruction.model_dump(mode="json"),
            bundle_kind="INSTRUCTION",
            manifest_artifact_id=pointer.artifact_id,
            manifest_artifact_revision_id=pointer.artifact_revision_id,
            manifest_sha256=pointer.sha256,
        )
        prior = session.records.get((ExecutionBundleRevisionRecord, instruction.bundle_revision_id))
        if prior is not None:
            assert prior.canonical_document == row.canonical_document
            return prior
        session.records[(ExecutionBundleRevisionRecord, instruction.bundle_revision_id)] = row
        return row

    def publish_bundle(actual_session: Any, **kwargs: Any) -> Any:
        assert actual_session is session
        return session.get(ExecutionBundleRevisionRecord, kwargs["bundle_revision_id"])

    def draft(actual_session: Any, **kwargs: Any) -> Any:
        assert actual_session is session
        value.draft_creations += 1
        body = {
            "schema_version": "execution-preset-revision/1.0",
            "preset_id": "execpreset_" + "1" * 32,
            "preset_revision_id": "execpresetrev_" + "1" * 32,
            "revision_number": 1,
            "state": "DRAFT",
            "display_name": kwargs["display_name"],
            "description": kwargs["description"],
            "role_policies": kwargs["role_policies"],
            "capacity_policy_revision_id": kwargs["capacity_policy_revision_id"],
            "general_knowledge_policy": kwargs["general_knowledge_policy"],
            "compatible_workflow_protocols": kwargs["compatible_workflow_protocols"],
            "created_at": kwargs["created_at"].isoformat().replace("+00:00", "Z"),
        }
        model = ExecutionPresetRevision.model_validate(
            body | {"content_sha256": content_sha256(body)}
        )
        row = SimpleNamespace(
            **model.model_dump(), canonical_document=model.model_dump(mode="json")
        )
        session.records[(ExecutionPresetRevisionRecord, model.preset_revision_id)] = row
        session.revisions.append(row)
        session.logical = SimpleNamespace(
            preset_id=model.preset_id,
            preset_key=kwargs["preset_key"],
            state="ACTIVE",
            current_revision_id=None,
        )
        return row

    def evaluation(actual_session: Any, **kwargs: Any) -> Any:
        assert actual_session is session
        report = ExecutionPresetEvaluationReport.model_validate(kwargs["document"])
        value.evaluations.append(report)
        return SimpleNamespace(evaluation_id="preseteval_" + "2" * 32)

    def release(actual_session: Any, **kwargs: Any) -> Any:
        assert actual_session is session
        value.release_calls += 1
        if session.logical.current_revision_id is not None:
            return session.get(ExecutionPresetRevisionRecord, session.logical.current_revision_id)
        body = deepcopy(session.revisions[0].canonical_document)
        body.update(
            state="RELEASED",
            revision_number=2,
            preset_revision_id="execpresetrev_" + "2" * 32,
            created_at=kwargs["released_at"].isoformat().replace("+00:00", "Z"),
        )
        body["content_sha256"] = content_sha256(
            {key: item for key, item in body.items() if key != "content_sha256"}
        )
        model = ExecutionPresetRevision.model_validate(body)
        row = SimpleNamespace(
            **model.model_dump(), canonical_document=model.model_dump(mode="json")
        )
        session.records[(ExecutionPresetRevisionRecord, model.preset_revision_id)] = row
        session.revisions.append(row)
        session.logical.current_revision_id = model.preset_revision_id
        return row

    monkeypatch.setattr(bootstrap, "capacity_pool_model_options", options)
    monkeypatch.setattr(bootstrap, "record_bundle_revision", record_bundle)
    monkeypatch.setattr(bootstrap, "publish_bundle_revision", publish_bundle)
    monkeypatch.setattr(bootstrap, "create_execution_preset_draft", draft)
    monkeypatch.setattr(bootstrap, "record_execution_preset_evaluation", evaluation)
    monkeypatch.setattr(bootstrap, "release_execution_preset", release)
    return value


def prepare(value: SimpleNamespace, **overrides: Any) -> Any:
    return bootstrap.prepare_inference_transfer_controls(
        value.sessions,
        value.publisher,
        **(
            {
                "manifest": value.manifest,
                "platform_payload": PLATFORM_BYTES,
                "rubric_payload": RUBRIC_BYTES,
                "operator_id": value.operator,
                "observed_at": value.manifest.source.reviewed_at + timedelta(minutes=1),
                "authorize_control_change": value.authorize,
            }
            | overrides
        ),
    )


def release(value: SimpleNamespace, prepared: Any, **overrides: Any) -> Any:
    return bootstrap.release_inference_transfer_controls(
        value.sessions,
        value.publisher,
        **(
            {
                "prepared": prepared,
                "operator_id": value.operator,
                "released_at": value.manifest.source.reviewed_at + timedelta(minutes=2),
                "authorize_control_change": value.authorize,
            }
            | overrides
        ),
    )


def test_prepare_publishes_exact_nested_members_and_draft_without_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    prepared = prepare(value)
    assert prepared.draft.state == "DRAFT" and value.session.logical.current_revision_id is None
    assert value.release_calls == 0 and not value.evaluations
    assert len(value.publisher.history) == 4 and value.draft_creations == 1
    members = {call["logical_name"]: call for call in value.publisher.calls}
    assert members["instructions/transfer-rubric.md"]["payload"] == RUBRIC_BYTES
    assert members["instructions/platform.md"]["payload"] == PLATFORM_BYTES
    assert all(
        call["source_commit"] == value.manifest.source.source_commit for call in members.values()
    )
    policy = prepared.draft.role_policies[0]
    assert policy.model_candidates == (value.manifest.model_candidate,)
    assert policy.worker_pool_key == "customer-support" and policy.reference_bundle is None
    assert prepared.draft.general_knowledge_policy == "DENY"
    assert prepared.draft.compatible_workflow_protocols == ("workflow-role/1.29.0",)
    assert value.observations and value.authorizations


def test_exact_prepare_replay_keeps_ids_and_publisher_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    first = prepare(value)
    second = prepare(value)
    assert first == second and value.draft_creations == 1
    assert len(value.publisher.history) == 4


def test_authorized_initial_prepare_registers_exact_protocol_once_then_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    key = (ProtocolVersionRecord, value.manifest.workflow_role_schema_version)
    del value.session.records[key]
    original = bootstrap.ensure_protocol_version
    observations: list[tuple[int, int]] = []

    def ensure(session: Any, version: str, digest: str) -> None:
        assert session is value.session
        assert version == value.manifest.workflow_role_schema_version
        assert digest == role_schema_bundle_hash(version)
        assert value.authorizations[-1] == (value.operator, "PREPARE")
        assert value.observations and value.session.statements
        observations.append((len(value.authorizations), len(value.publisher.history)))
        original(session, version, digest)

    monkeypatch.setattr(bootstrap, "ensure_protocol_version", ensure)
    first = prepare(value)
    record = value.session.records[key]
    assert record.schema_sha256 == role_schema_bundle_hash(
        value.manifest.workflow_role_schema_version
    )
    assert len(value.session.protocol_additions) == 1
    second = prepare(value)
    assert second == first and value.session.records[key] is record
    assert len(value.session.protocol_additions) == 1 and len(observations) == 2
    assert observations[0][1] == 0 and observations[1][1] == 4
    assert value.session.flushes == 2 and value.draft_creations == 1


@pytest.mark.parametrize(
    "failure", ["candidate", "definition", "capacity", "history", "authorization"]
)
def test_missing_protocol_is_not_registered_after_invalid_prepare_admission(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = fixture(monkeypatch)
    key = (ProtocolVersionRecord, value.manifest.workflow_role_schema_version)
    del value.session.records[key]
    if failure == "candidate":
        value.available = False
    elif failure == "definition":
        value.session.definition.definition_hash = "sha256:" + "f" * 64
    elif failure == "capacity":
        value.session.records[
            (WorkerCapacityPolicyRecord, value.manifest.capacity.capacity_policy_id)
        ].current_revision_id = "capacityrev_" + "f" * 32
    elif failure == "history":
        value.session.logical = SimpleNamespace(state="RETIRED")
    else:
        value.revoked = True
    with pytest.raises(ControlPlaneError):
        prepare(value)
    assert key not in value.session.records
    assert not value.session.protocol_additions and value.session.flushes == 0
    assert not value.publisher.calls and value.draft_creations == 0


def test_conflicting_existing_protocol_hash_is_rejected_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    key = (ProtocolVersionRecord, value.manifest.workflow_role_schema_version)
    value.session.records[key].schema_sha256 = "sha256:" + "f" * 64
    with pytest.raises(ControlPlaneError) as error:
        prepare(value)
    assert error.value.code == "CONTROL_PROTOCOL_POINTER_MISSING"
    assert value.session.records[key].schema_sha256 == "sha256:" + "f" * 64
    assert not value.session.protocol_additions and value.session.flushes == 0
    assert not value.publisher.calls and value.draft_creations == 0


def test_release_does_not_repair_a_missing_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    prepared = prepare(value)
    key = (ProtocolVersionRecord, value.manifest.workflow_role_schema_version)
    del value.session.records[key]
    with pytest.raises(ControlPlaneError) as error:
        release(value, prepared)
    assert error.value.code == "CONTROL_PROTOCOL_POINTER_MISSING"
    assert key not in value.session.records and not value.session.protocol_additions
    assert value.release_calls == 0 and not value.evaluations
    assert len(value.publisher.history) == 4


def test_initial_prepare_reauthorizes_inside_transaction_before_protocol_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    key = (ProtocolVersionRecord, value.manifest.workflow_role_schema_version)
    del value.session.records[key]
    calls = 0

    def revoked_at_transaction(operator: str, action: str) -> None:
        nonlocal calls
        calls += 1
        assert operator == value.operator and action == "PREPARE"
        if calls == 2:
            raise ControlPlaneError("CONTROL_OPERATOR_FORBIDDEN", "synthetic revoked operator")

    with pytest.raises(ControlPlaneError) as error:
        prepare(value, authorize_control_change=revoked_at_transaction)
    assert error.value.code == "CONTROL_OPERATOR_FORBIDDEN" and calls == 2
    assert key not in value.session.records
    assert not value.session.protocol_additions and not value.session.statements
    assert not value.publisher.calls and value.sessions.rollbacks == 1


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_partial_artifact_commit_recovers_exact_history_without_deleted_artifacts(
    monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    value = fixture(monkeypatch)
    value.publisher.fail_after_commit = stage
    with pytest.raises(OSError):
        prepare(value)
    prior = dict(value.publisher.history)
    assert len(prior) == stage and value.draft_creations == 0
    result = prepare(value)
    assert result.draft.state == "DRAFT" and value.draft_creations == 1
    assert all(value.publisher.history[key] == saved for key, saved in prior.items())
    assert len(value.publisher.history) == 4


def test_later_control_transaction_failure_preserves_publication_then_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    original = getattr(bootstrap, "create_execution_preset_draft", create_execution_preset_draft)
    monkeypatch.setattr(
        bootstrap,
        "create_execution_preset_draft",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic owner failure")),
    )
    with pytest.raises(ValueError, match="synthetic owner"):
        prepare(value)
    assert len(value.publisher.history) == 4 and value.session.logical is None
    assert not value.session.revisions and value.sessions.rollbacks == 1
    monkeypatch.setattr(bootstrap, "create_execution_preset_draft", original)
    assert prepare(value).draft.state == "DRAFT"
    assert len(value.publisher.history) == 4


@pytest.mark.parametrize(
    "failure", ["candidate", "protocol", "definition", "capacity", "authorization"]
)
def test_preflight_failures_have_zero_publication(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = fixture(monkeypatch)
    if failure == "candidate":
        value.available = False
    elif failure == "protocol":
        value.session.records[
            (ProtocolVersionRecord, value.manifest.workflow_role_schema_version)
        ].schema_sha256 = "sha256:" + "f" * 64
    elif failure == "definition":
        value.session.definition.definition_hash = "sha256:" + "f" * 64
    elif failure == "capacity":
        value.session.records[
            (WorkerCapacityPolicyRecord, value.manifest.capacity.capacity_policy_id)
        ].current_revision_id = "capacityrev_" + "f" * 32
    else:
        value.revoked = True
    with pytest.raises(ControlPlaneError):
        prepare(value)
    assert not value.publisher.calls and value.draft_creations == 0


def test_release_is_explicit_real_argv_non_live_only_not_model_or_human_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    prepared = prepare(value)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("technical bootstrap must not launch a model")

    monkeypatch.setattr("eom_orchestrator.worker_exec.subprocess.run", forbidden)
    result = release(value, prepared)
    assert result.preset.state == "RELEASED" and value.release_calls == 1
    assert result.scientific_evaluation == result.human_transfer_evaluation == "NOT_EVALUATED"
    report = value.evaluations[0]
    assert report.scope == "NON_LIVE" and report.outcome == "PASS"
    assert report.quality_score_permille is None and report.cases_total == len(
        result.executed_cases
    )
    assert (
        "support:0:MODEL_PIN" in result.executed_cases
        and "support:0:SCHEMA_OUTPUT_PIN" in result.executed_cases
    )
    payload = value.publisher.calls[-1]["payload"]
    assert json.loads(payload)["quality_score_permille"] is None
    assert result.evaluation_artifact.sha256 == sha256_bytes(payload)
    assert prepare(value) == prepared  # Original DRAFT survives the immutable release successor.
    assert release(value, prepared).preset == result.preset
    assert len(value.publisher.history) == 5


def test_argv_regression_fails_without_report_or_release(monkeypatch: pytest.MonkeyPatch) -> None:
    value = fixture(monkeypatch)
    prepared = prepare(value)
    from eom_orchestrator.worker_exec import codex_command

    def drifted(workspace: Path, invocation: dict[str, str]) -> tuple[str, ...]:
        args = list(codex_command(workspace, invocation))
        args[args.index("--model") + 1] = "wrong-model"
        return tuple(args)

    monkeypatch.setattr("eom_orchestrator.preset_model_selection.codex_command", drifted)
    with pytest.raises(ControlPlaneError, match="non-live"):
        release(value, prepared)
    assert value.release_calls == 0 and not value.evaluations
    assert len(value.publisher.history) == 4 and value.session.logical.current_revision_id is None


@pytest.mark.parametrize(
    "failure", ["candidate", "authorization", "rubric_source", "draft", "member_lifecycle"]
)
def test_release_rechecks_current_authority_and_exact_source_policy(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = fixture(monkeypatch)
    prepared = prepare(value)
    if failure == "candidate":
        value.available = False
    elif failure == "authorization":
        value.revoked = True
    elif failure == "rubric_source":
        pointer = prepared.instruction_bundle.manifest_artifact
        value.session.artifacts[(ArtifactRevisionRecord, pointer.artifact_revision_id)].result[
            "source_commit"
        ] = "f" * 40
    elif failure == "member_lifecycle":
        value.session.artifacts[
            (ArtifactRevisionRecord, prepared.bootstrap_artifact.artifact_revision_id)
        ].approved = False
    else:
        prepared = replace(
            prepared,
            draft=prepared.draft.model_copy(
                update={"general_knowledge_policy": "ALLOW_WITH_PROVENANCE"}
            ),
        )
    with pytest.raises((ControlPlaneError, ValueError)):
        release(value, prepared)
    assert value.release_calls == 0 and not value.evaluations and len(value.publisher.history) == 4


def test_different_reviewed_manifest_is_not_an_automatic_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    prepare(value)
    changed = bootstrap_manifest(
        workflow_definition_sha256=value.manifest.workflow_definition_sha256, timeout_seconds=301
    )
    with pytest.raises(ControlPlaneError, match="history differs"):
        prepare(value, manifest=changed)
    assert value.draft_creations == 1 and len(value.publisher.history) == 4


@pytest.mark.parametrize(
    "failure", ["schema_copy", "raw_bytes", "missing_authorizer", "naive_time"]
)
def test_untrusted_bootstrap_inputs_fail_before_protected_lookup_or_publication(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = fixture(monkeypatch)
    key = (ProtocolVersionRecord, value.manifest.workflow_role_schema_version)
    del value.session.records[key]
    overrides: dict[str, Any] = {}
    if failure == "schema_copy":
        overrides["manifest"] = value.manifest.model_copy(
            update={"workflow_role_schema_version": "workflow-role/1.28.0"}
        )
    elif failure == "raw_bytes":
        overrides["rubric_payload"] = b"foreign reviewed bytes"
    elif failure == "missing_authorizer":
        overrides["authorize_control_change"] = None
    else:
        overrides["observed_at"] = value.manifest.source.reviewed_at.replace(tzinfo=None)
    with pytest.raises(ControlPlaneError):
        prepare(value, **overrides)
    assert not value.session.statements and not value.publisher.calls
    assert key not in value.session.records and not value.session.protocol_additions


@pytest.mark.parametrize("failure", ["authorization", "candidate"])
def test_post_report_release_gate_keeps_draft_and_committed_report_history(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = fixture(monkeypatch)
    prepared = prepare(value)
    original = value.publisher.publish_bytes

    def change_after_report(**kwargs: Any) -> Any:
        result = original(**kwargs)
        if kwargs["logical_name"] == "inference-transfer-preset-evaluation.json":
            if failure == "authorization":
                value.revoked = True
            else:
                value.available = False
        return result

    monkeypatch.setattr(value.publisher, "publish_bytes", change_after_report)
    with pytest.raises(ControlPlaneError):
        release(value, prepared)
    assert len(value.publisher.history) == 5
    assert value.session.logical.current_revision_id is None
    assert value.release_calls == 0 and not value.evaluations
    assert prepared.draft.state == "DRAFT"
    value.revoked = False
    value.available = True
    monkeypatch.setattr(value.publisher, "publish_bytes", original)
    assert release(value, prepared).preset.state == "RELEASED"
    assert len(value.publisher.history) == 5


def test_dangling_logical_preset_does_not_become_an_implicit_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fixture(monkeypatch)
    prepared = prepare(value)
    value.session.logical = None
    with pytest.raises(ControlPlaneError, match="policy differs"):
        release(value, prepared)
    assert value.release_calls == 0 and len(value.publisher.history) == 4
