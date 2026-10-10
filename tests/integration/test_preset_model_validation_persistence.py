"""Opt-in owner/API/Orchestrator queue tests in a marker-guarded disposable DB only."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import pytest
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.artifacts import commit_file_set_artifact
from eom_orchestrator.control_commands import (
    _terminalize_record,
    build_codex_control_command,
    claim_next_codex_control_command,
    enqueue_codex_control_command,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetValidationRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    publish_execution_preset_revision,
    record_capability_snapshot,
    record_execution_preset_revision,
)
from eom_orchestrator.database import build_engine
from eom_orchestrator.models import ArtifactRevisionRecord, JobEventRecord, JobRecord
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    release_execution_preset,
)
from eom_orchestrator.preset_model_validation import (
    enqueue_preset_model_validation,
    validation_status,
)
from eom_orchestrator.preset_model_validation_processor import PresetModelValidationProcessor
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_usage_exec import (
    _catalog_snapshot,
    _normalized_model,
    _observation_document,
)
from eom_workflow import CodexUsageObservationV2
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import (
    TestDatabaseManifest as DisposableDatabaseManifest,
)
from scripts.api.testdb_guard import (
    validate_application_schema_metadata,
    validate_state_directory,
)
from tests.integration import test_control_plane_persistence as control_fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def guarded_engine(integration_engine: Engine) -> Engine:
    # EOM_DATABASE_URL alone is deliberately insufficient authority to mutate a DB.
    state_path = os.environ.get("EOM_API_TEST_STATE")
    if not state_path:
        pytest.fail("preset persistence requires a marker-guarded disposable EOM_API_TEST_STATE")
    state = validate_state_directory(Path(state_path))
    manifest = DisposableDatabaseManifest.load(state / "manifest.json")
    assert integration_engine.url.database == manifest.database
    assert integration_engine.url.username == manifest.owner_role
    with integration_engine.connect() as connection:
        owner, marker = connection.execute(
            text(
                "SELECT owner.rolname, obj_description(namespace.oid, 'pg_namespace') "
                "FROM pg_namespace namespace JOIN pg_roles owner ON owner.oid = namespace.nspowner "
                "WHERE namespace.nspname = 'app'"
            )
        ).one()
        path, usage, create = connection.execute(
            text(
                "SELECT current_schemas(false),has_schema_privilege(current_user,'app','USAGE'),"
                "has_schema_privilege(current_user,'app','CREATE')"
            )
        ).one()
        validate_application_schema_metadata(
            manifest,
            schema_owner=owner,
            schema_comment=marker,
            effective_search_path=tuple(path),
            has_usage=usage,
            has_create=create,
        )
        assert (
            connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            == "20261009_0050"
        )
    return integration_engine


@pytest.fixture
def seed(guarded_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(control_fixture, "NOW", datetime.now(UTC) - timedelta(seconds=3))
    with Session(guarded_engine, expire_on_commit=False) as session, session.begin():
        plan_id, _workflow_id, _bundle_revision = control_fixture._complete_control_plane(session)
        plan = session.get(ResolvedExecutionPlanRecord, plan_id)
        assert plan is not None
        base = session.get(ExecutionPresetRevisionRecord, plan.preset_revision_id)
        assert base is not None
        logical = session.get(ExecutionPresetRecord, base.preset_id)
        assert logical is not None
        operator_id = "operator_" + uuid4().hex
        session.add(
            OperatorRecord(
                operator_id=operator_id,
                username="preset-" + uuid4().hex[:12],
                normalized_username="preset-" + uuid4().hex,
                display_name="Disposable preset evaluator",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="disposable-test",
            )
        )
        policies = deepcopy(base.canonical_document["role_policies"])
        policies[0]["model_candidates"][0]["reasoning_effort"] = "medium"
        draft = create_execution_preset_draft(
            session,
            preset_key=logical.preset_key,
            display_name="Disposable medium candidate",
            description="No inference, no production changes.",
            role_policies=policies,
            capacity_policy_revision_id=base.capacity_policy_revision_id,
            general_knowledge_policy=base.general_knowledge_policy,
            compatible_workflow_protocols=base.compatible_workflow_protocols,
            created_by=operator_id,
            created_at=datetime.now(UTC),
        )
        binding = session.scalar(
            select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
        )
        assert binding is not None
        snapshot = control_fixture._self_hash(
            {
                "schema_version": "codex-capability-snapshot/1.0",
                "capability_snapshot_id": "capsnap_" + uuid4().hex,
                "binding_id": binding.binding_id,
                "codex_cli_version": binding.codex_cli_version,
                "source": "LOCAL_OBSERVATION",
                "snapshot_sha256": "sha256:" + "0" * 64,
                "capabilities": [
                    {
                        "model": "gpt-5.6-terra",
                        "reasoning_efforts": ["medium", "high"],
                        "state": "AVAILABLE",
                    }
                ],
                "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "valid_until": (datetime.now(UTC) + timedelta(minutes=30))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            "snapshot_sha256",
        )
        record_capability_snapshot(session, document=snapshot)
        command = enqueue_codex_control_command(
            session,
            document=build_codex_control_command(
                command_type="OBSERVE",
                binding_id=binding.binding_id,
                expected_resource_version=binding.resource_version,
                requested_by_operator_id=operator_id,
                requested_at=datetime.now(UTC),
                reason_code=None,
            ),
            idempotency_key="native-fixture:" + uuid4().hex,
        )
        assert (
            claim_next_codex_control_command(
                session,
                lease_owner="disposable-native-fixture",
                claimed_at=datetime.now(UTC),
                lease_ttl=timedelta(minutes=1),
            )
            is command
        )
        catalog = _catalog_snapshot(
            cli_version=binding.codex_cli_version,
            models=(
                _normalized_model(
                    {
                        "id": "gpt-5.6-terra",
                        "model": "gpt-5.6-terra",
                        "displayName": "Disposable fixture",
                        "hidden": False,
                        "isDefault": True,
                        "defaultReasoningEffort": "high",
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": "medium"},
                            {"reasoningEffort": "high"},
                        ],
                        "inputModalities": ["text", "image"],
                    }
                ),
            ),
            reason_code=None,
        )
        usage = _observation_document(
            command_id=command.command_id,
            binding_id=binding.binding_id,
            slot_id="01",
            account_result={"account": {"type": "chatgpt", "planType": "plus"}},
            usage_result={"rateLimits": {"primary": {"usedPercent": 1}}},
            model_catalog=catalog,
        )
        _terminalize_record(
            command,
            outcome="SUCCEEDED",
            result_resource_version=binding.resource_version,
            binding_state="READY",
            reason_code=None,
            processed_at=datetime.now(UTC),
            usage_observation=CodexUsageObservationV2.model_validate(usage),
        )
        return {
            "base": base.preset_revision_id,
            "draft": draft.preset_revision_id,
            "actor": operator_id,
            "preset": base.preset_id,
            "key": logical.preset_key,
        }


def _enqueue(
    session: Session, seed: dict[str, str], key: str | None = None
) -> ExecutionPresetValidationRecord:
    return enqueue_preset_model_validation(
        session,
        draft_revision_id=seed["draft"],
        base_revision_id=seed["base"],
        expected_version=2,
        requested_by=seed["actor"],
        request_key=key or uuid4().hex,
        requested_at=datetime.now(UTC),
    )


def _processor(
    engine: Engine, directory: Path, source: str | None = "a" * 40
) -> PresetModelValidationProcessor:
    staging = directory / "staging"
    staging.mkdir(exist_ok=True)
    artifacts = directory / "artifacts"
    artifacts.mkdir(exist_ok=True)
    return PresetModelValidationProcessor(
        engine,
        Settings(
            staging_root=staging,
            nas_artifact_root=artifacts,
            runtime_source_commit=source,
        ),
    )


def test_concurrent_transport_replay_creates_one_intent_and_no_api_job(
    guarded_engine: Engine,
    seed: dict[str, str],
    tmp_path: Path,
) -> None:
    barrier = Barrier(4)
    key = uuid4().hex

    def submit() -> str:
        barrier.wait(timeout=10)
        with Session(guarded_engine) as session, session.begin():
            return _enqueue(session, seed, key).validation_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = tuple(pool.map(lambda _: submit(), range(4)))
    assert len(set(identities)) == 1
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetValidationRecord)
                .where(ExecutionPresetValidationRecord.preset_revision_id == seed["draft"])
            )
            == 1
        )
        assert session.get(JobRecord, identities[0]) is None
    # Finish this test-only intent through the supported owner, not a direct state UPDATE.
    assert _processor(guarded_engine, tmp_path, source=None).process_once() == identities[0]


def test_restricted_api_role_enqueues_metadata_without_job_or_protocol_insert(
    guarded_engine: Engine,
    seed: dict[str, str],
    tmp_path: Path,
) -> None:
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableDatabaseManifest.load(state / "manifest.json")
    environment = state / "runtime.env"
    assert not environment.is_symlink() and environment.stat().st_mode & 0o077 == 0
    values = dict(
        line.split("=", 1) for line in environment.read_text(encoding="ascii").splitlines()
    )
    runtime = build_engine(values["EOM_API_DATABASE_URL"])
    assert (
        runtime.url.database == manifest.database and runtime.url.username == manifest.runtime_role
    )
    try:
        with Session(runtime) as session, session.begin():
            identity = _enqueue(session, seed).validation_id
        with Session(guarded_engine) as session:
            assert session.get(JobRecord, identity) is None
            assert session.get(ExecutionPresetValidationRecord, identity) is not None
    finally:
        runtime.dispose()
    assert _processor(guarded_engine, tmp_path, source=None).process_once() == identity


def test_two_orchestrator_processors_do_not_claim_or_publish_one_intent_twice(
    guarded_engine: Engine,
    seed: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(guarded_engine) as session, session.begin():
        first = _enqueue(session, seed).validation_id
        following = _enqueue(session, seed).validation_id
    primary, secondary = _processor(guarded_engine, tmp_path), _processor(guarded_engine, tmp_path)
    entered, proceed = Event(), Event()
    original = primary._process

    def hold_claim(identity: str) -> None:
        entered.set()
        assert proceed.wait(timeout=10)
        original(identity)

    monkeypatch.setattr(primary, "_process", hold_claim)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(primary.process_once)
        try:
            assert entered.wait(timeout=10)
            assert secondary.process_once() is None
        finally:
            proceed.set()
        assert future.result(timeout=10) == first
    assert secondary.process_once() == following
    with Session(guarded_engine) as session:
        for identity in (first, following):
            job = session.get(JobRecord, identity)
            assert job is not None and job.status == "SUCCEEDED"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ExecutionPresetEvaluationRecord)
                    .where(
                        ExecutionPresetEvaluationRecord.report_artifact_revision_id
                        == job.revision_id
                    )
                )
                == 1
            )


@pytest.mark.parametrize("mutation", ["request", "direct_success", "delete", "terminal_rewrite"])
def test_database_enforces_immutable_request_and_terminal_history(
    guarded_engine: Engine,
    seed: dict[str, str],
    mutation: str,
) -> None:
    with guarded_engine.connect() as connection:
        outer = connection.begin()
        with Session(bind=connection) as session:
            command = _enqueue(session, seed)
            identity = command.validation_id
            if mutation == "terminal_rewrite":
                command.state = "PROCESSING"
                session.flush()
                command.state = "SUCCEEDED"
                command.completed_at = datetime.now(UTC)
                session.flush()
            with pytest.raises(IntegrityError), session.begin_nested():
                if mutation == "request":
                    command.canonical_request = command.canonical_request | {"extra": "altered"}
                elif mutation == "direct_success":
                    command.state = "SUCCEEDED"
                    command.completed_at = datetime.now(UTC)
                elif mutation == "delete":
                    session.delete(command)
                else:
                    command.error_code = "ALTERED_HISTORY"
                session.flush()
            assert session.get(ExecutionPresetValidationRecord, identity) is not None
        outer.rollback()


def test_processor_commits_one_exact_report_then_release_changes_only_future_pointer(
    guarded_engine: Engine,
    seed: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(guarded_engine) as session, session.begin():
        identity = _enqueue(session, seed).validation_id
    processor = _processor(guarded_engine, tmp_path)
    errors: list[str] = []
    original_process = processor._process

    def capture_failure(identity: str) -> None:
        try:
            original_process(identity)
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
            raise

    monkeypatch.setattr(processor, "_process", capture_failure)
    assert processor.process_once() == identity
    assert processor.process_once() is None
    with Session(guarded_engine) as session, session.begin():
        command = session.get(ExecutionPresetValidationRecord, identity)
        job = session.get(JobRecord, identity)
        assert command is not None and job is not None, errors
        assert command.state == "SUCCEEDED", errors
        assert command.state == job.status == "SUCCEEDED"
        revision = session.get(ArtifactRevisionRecord, job.revision_id)
        assert revision is not None and revision.approved
        assert {member["file_name"] for member in revision.manifest["files"]} == {
            "preset-evaluation.json",
            "acceptance-cases.json",
        }
        status = validation_status(session, identity)
        assert status["quality_evaluated"] is False and status["scope"] == "NON_LIVE"
        assert status["cases_passed"] == status["cases_total"] == 11
        evaluation = session.get(ExecutionPresetEvaluationRecord, status["evaluation_id"])
        assert evaluation is not None and evaluation.quality_score_permille is None
        assert evaluation.report_artifact_revision_id == job.revision_id
        before = session.get(ExecutionPresetRevisionRecord, seed["base"])
        assert before is not None
        original = deepcopy(before.canonical_document)
        released = release_execution_preset(
            session,
            draft_revision_id=seed["draft"],
            released_by=seed["actor"],
            released_at=datetime.now(UTC),
        )
        logical = session.get(ExecutionPresetRecord, seed["preset"])
        assert logical is not None and logical.current_revision_id == released.preset_revision_id
        assert released.preset_revision_id != seed["draft"]
        assert before.canonical_document == original


def test_uncertain_nas_commit_recovers_same_job_artifact_and_checkpoint(
    guarded_engine: Engine,
    seed: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(guarded_engine) as session, session.begin():
        identity = _enqueue(session, seed).validation_id
    committed: list[Path] = []

    def lost_commit_response(*args: Any, **kwargs: Any) -> Path:
        path = commit_file_set_artifact(*args, **kwargs)
        committed.append(path)
        if len(committed) == 1:
            raise OSError("disposable simulated response lost after commit")
        return path

    monkeypatch.setattr(
        "eom_orchestrator.preset_model_validation_processor.commit_file_set_artifact",
        lost_commit_response,
    )
    processor = _processor(guarded_engine, tmp_path)
    assert processor.process_once() is None
    with Session(guarded_engine) as session:
        command = session.get(ExecutionPresetValidationRecord, identity)
        job = session.get(JobRecord, identity)
        assert command is not None and job is not None
        assert command.state == "PROCESSING" and job.status == "COMMITTING"
        assert command.completed_at is None
        pins = (job.logical_artifact_id, job.revision_id, job.request_hash)
        assert session.get(ArtifactRevisionRecord, job.revision_id) is None
        assert committed[0].is_dir()
    processor._retry_after = 0
    assert processor.process_once() == identity
    assert committed[0] == committed[1]
    with Session(guarded_engine) as session:
        job = session.get(JobRecord, identity)
        assert job is not None and job.status == "SUCCEEDED"
        assert (job.logical_artifact_id, job.revision_id, job.request_hash) == pins
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == identity,
                    JobEventRecord.event == "PRESET_MODEL_ACCEPTANCE_STAGED",
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetEvaluationRecord)
                .where(
                    ExecutionPresetEvaluationRecord.report_artifact_revision_id == job.revision_id
                )
            )
            == 1
        )


def test_permanent_bad_checkpoint_does_not_block_next_command(
    guarded_engine: Engine,
    seed: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(guarded_engine) as session, session.begin():
        oldest = _enqueue(session, seed).validation_id
        following = _enqueue(session, seed).validation_id
    processor = _processor(guarded_engine, tmp_path)
    committed: list[Path] = []

    def invalid_after_commit(*args: Any, **kwargs: Any) -> Path:
        path = commit_file_set_artifact(*args, **kwargs)
        committed.append(path)
        if len(committed) == 1:
            raise ControlPlaneError(
                "CONTROL_VALIDATION_CHECKPOINT_INVALID", "disposable permanent rejection"
            )
        return path

    monkeypatch.setattr(
        "eom_orchestrator.preset_model_validation_processor.commit_file_set_artifact",
        invalid_after_commit,
    )
    assert processor.process_once() == oldest
    assert processor.process_once() == following
    with Session(guarded_engine) as session:
        first = session.get(ExecutionPresetValidationRecord, oldest)
        second = session.get(ExecutionPresetValidationRecord, following)
        assert first is not None and first.state == "FAILED"
        assert first.error_code == "CONTROL_VALIDATION_CHECKPOINT_INVALID"
        assert second is not None and second.state == "SUCCEEDED"
        job = session.get(JobRecord, oldest)
        assert job is not None and job.status == "FAILED"
        assert session.get(ArtifactRevisionRecord, job.revision_id) is None
        assert committed[0].is_dir()  # Preserve rejected candidate bytes, never approve them.


def test_release_rejects_baseline_changed_after_successful_acceptance(
    guarded_engine: Engine,
    seed: dict[str, str],
    tmp_path: Path,
) -> None:
    with Session(guarded_engine) as session, session.begin():
        identity = _enqueue(session, seed).validation_id
    assert _processor(guarded_engine, tmp_path).process_once() == identity
    with Session(guarded_engine) as session, session.begin():
        base = session.get(ExecutionPresetRevisionRecord, seed["base"])
        assert base is not None
        competitor = deepcopy(base.canonical_document)
        competitor.update(
            {"preset_revision_id": "execpresetrev_" + uuid4().hex, "revision_number": 3}
        )
        control_fixture._self_hash(competitor, "content_sha256")
        new_base = record_execution_preset_revision(
            session,
            preset_key=seed["key"],
            document=competitor,
            created_by="disposable-competing-release",
        )
        publish_execution_preset_revision(
            session,
            preset_id=seed["preset"],
            preset_revision_id=new_base.preset_revision_id,
        )
        with pytest.raises(ControlPlaneError) as failure:
            release_execution_preset(
                session,
                draft_revision_id=seed["draft"],
                released_by=seed["actor"],
                released_at=datetime.now(UTC),
            )
        assert failure.value.code == "CONTROL_PRESET_BASE_STALE"


def test_pending_keyset_is_index_backed(guarded_engine: Engine) -> None:
    with guarded_engine.connect() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = str(
            connection.execute(
                text(
                    "EXPLAIN SELECT validation_id FROM execution_preset_validations "
                    "WHERE state IN ('PENDING','PROCESSING') "
                    "ORDER BY requested_at,validation_id LIMIT 1"
                )
            ).all()
        )
        assert "ix_preset_validation_pending" in plan
