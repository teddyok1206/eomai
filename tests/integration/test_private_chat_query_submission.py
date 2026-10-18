"""Guarded PostgreSQL atomic submission; current source/Chat/IAM are synthetic.

The exact static admission predicate is real; Chat/IAM/source and executor ports
remain declared fixtures. No private step/native model/unit/activation.
Original retained rows are not deleted, repaired or reinterpreted on retry.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, local
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    PrivateChatContextPreparation,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.models import JobRecord
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition, compile_definition_data
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    private_chat_query_submission_key,
)
from eom_workflow_runner import native_start_command
from eom_workflow_runner import private_chat_query_preparation as preparation_module
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_submission import start_private_chat_query_in_session
from eom_workflow_runner.repository import (
    CommandType,
    admitted_workflow_definition,
    create_workflow_instance,
    import_workflow_definition,
)
from eom_workflow_runner.state_machine import WorkflowState, transition_workflow
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_query_source_owner import owned as owned
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import definition_body

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def submission(owned):
    compiled = compile_definition_data(definition_body(), "synthetic-private-atomic-start", set())
    assert owned.request.workflow_definition_sha256 == compiled.sha256
    with owned.publisher.sessions.begin() as session:
        definition = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == compiled.definition.definition_key,
                WorkflowDefinitionRecord.definition_version
                == compiled.definition.definition_version,
            )
        )
        if definition is None:
            definition = WorkflowDefinitionRecord(
                definition_id="wfdef_" + uuid4().hex,
                definition_key=compiled.definition.definition_key,
                definition_version=compiled.definition.definition_version,
                schema_version=compiled.definition.schema_version,
                canonical_definition=compiled.as_dict(),
                definition_hash=compiled.sha256,
                active=True,
                source_path="synthetic/declared-private-atomic-start",
            )
            session.add(definition)
            session.flush()
        assert definition.active is True and definition.definition_hash == compiled.sha256
        definition_id = definition.definition_id
    assert workflow_definition_is_admitted(compiled.definition.definition_key, "1.0.0")
    return SimpleNamespace(
        source=owned,
        publisher=owned.publisher,
        request=owned.request,
        context=build_private_chat_query_submission_context(owned.request, owned.origin),
        owner=CatalogPrivateChatQueryOwnerAdmission(owned.owner),
        executor=Mock(spec=PrivateChatQueryNativeExecutor),
        definition_id=definition_id,
    )


def submit(value, session):
    return start_private_chat_query_in_session(
        session,
        definition=session.get(WorkflowDefinitionRecord, value.definition_id),
        request=value.request,
        context=value.context,
        actor_type="human",
        actor_id=value.context.origin.actor_id,
        owner=value.owner,
        executor=value.executor,
    )


def retained_rows(value):
    with value.publisher.sessions.begin() as session:
        workflows = tuple(
            session.scalars(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.idempotency_key
                    == private_chat_query_submission_key(value.context)
                )
            )
        )
        identities = tuple(row.workflow_id for row in workflows)
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id.in_(identities)
                )
            )
        )
        return workflows, commands


def test_postgres_original_private_start_is_atomic_replayable_and_text_free(submission):
    value = submission
    with value.publisher.sessions.begin() as session:
        jobs = session.scalar(select(func.count()).select_from(JobRecord))
        first = submit(value, session)
        ids = first.workflow.workflow_id, first.command.command_id
        assert first.workflow_created and first.command_created
        assert first.workflow.state == "REQUESTED" and first.command.state == "PENDING"
        assert first.workflow.stage == "LOCAL_EMBEDDING"
        assert first.workflow.runtime_context == value.context.model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(JobRecord)) == jobs
        stored = {
            "request": first.workflow.initial_request,
            "context": first.workflow.runtime_context,
            "command": first.command.payload,
        }
        assert TEXT.encode() not in canonical_json_bytes(stored)
    with value.publisher.sessions.begin() as session:
        replay = submit(value, session)
        assert (replay.workflow.workflow_id, replay.command.command_id) == ids
        assert not replay.workflow_created and not replay.command_created
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == ids[0])
            )
            == 1
        )
    workflows, commands = retained_rows(value)
    assert len(workflows) == len(commands) == 1
    assert value.executor.mock_calls == []


def test_postgres_private_preparation_constructs_first_request_and_reuses_original_pins(
    submission, monkeypatch
):
    value = submission
    arguments = dict(
        caller=EmbeddingRegistryCaller(value.context.origin.actor_id),
        origin=value.context.origin,
        context=value.request.context_request,
        owner=value.owner,
        executor=value.executor,
    )
    with value.publisher.sessions.begin() as session:
        first = preparation_module.prepare_and_start_private_chat_query_in_session(
            session, **arguments
        )
        ids = first.workflow.workflow_id, first.command.command_id
        initial = first.workflow.initial_request
        assert first.workflow_created and first.command_created
        assert TEXT.encode() not in canonical_json_bytes(initial)
    monkeypatch.setattr(
        preparation_module,
        "read_pinned_private_chat_query_controls",
        Mock(side_effect=AssertionError("rebuilding original preparation controls")),
    )
    monkeypatch.setattr(
        preparation_module,
        "effective_permissions",
        Mock(side_effect=AssertionError("rebuilding original audit")),
    )
    with value.publisher.sessions.begin() as session:
        replay = preparation_module.prepare_and_start_private_chat_query_in_session(
            session, **arguments
        )
        assert (replay.workflow.workflow_id, replay.command.command_id) == ids
        assert replay.workflow.initial_request == initial
        assert not replay.workflow_created and not replay.command_created
    assert value.executor.mock_calls == []


def test_postgres_private_selection_captures_official_initial_index_then_replays_without_recapture(
    submission, monkeypatch
):
    value = submission
    config = value.owner.configuration.registry
    context = value.request.context_request
    selection = PrivateChatContextPreparation(
        context.request_id,
        context.query_basis,
        EmbeddingRegistryLookup(
            config.corpus_id,
            config.namespace,
            context.graph_snapshot,
            context.policy_revision_id,
            context.policy_sha256,
            context.maximum_sources,
        ),
        value.source.policy.spaces,
        context.top_k,
    )
    arguments = dict(
        caller=EmbeddingRegistryCaller(value.context.origin.actor_id),
        origin=value.context.origin,
        preparation=selection,
        owner=value.owner,
        executor=value.executor,
    )
    with value.publisher.sessions.begin() as session:
        first = preparation_module.prepare_and_start_private_chat_query_selection_in_session(
            session, **arguments
        )
        ids = first.workflow.workflow_id, first.command.command_id
        initial = first.workflow.initial_request
        assert first.workflow_created and first.command_created
        assert initial["context_request"] == context.model_dump(mode="json")
        assert "anchor" not in initial["context_request"]
    monkeypatch.setattr(
        value.owner.catalog,
        "prepare_private_chat_context_in_session",
        Mock(side_effect=AssertionError("recapturing an original private context")),
    )
    with value.publisher.sessions.begin() as session:
        replay = preparation_module.prepare_and_start_private_chat_query_selection_in_session(
            session, **arguments
        )
        assert (replay.workflow.workflow_id, replay.command.command_id) == ids
        assert replay.workflow.initial_request == initial
        assert not replay.workflow_created and not replay.command_created
    assert value.executor.mock_calls == []


@pytest.mark.parametrize("deny_at", [2, 3, 4])
def test_postgres_late_current_authority_denial_discards_released_submission_savepoints(
    submission, monkeypatch, deny_at
):
    value = submission
    original = value.owner.resolve_submission
    calls = []

    def resolve(session, request, context):
        assert not session.in_nested_transaction()
        assert not session.new and not session.dirty and not session.deleted
        calls.append(session.get_transaction())
        if len(calls) == deny_at:
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return original(session, request, context)

    monkeypatch.setattr(value.owner, "resolve_submission", resolve)
    with pytest.raises(SimilarityContextReadError), value.publisher.sessions.begin() as session:
        submit(value, session)
    assert len(calls) == deny_at and all(root is calls[0] for root in calls)
    assert retained_rows(value) == ((), ())
    assert value.executor.mock_calls == []


def test_postgres_start_persistence_failure_rolls_back_the_workflow_and_initial_audit(
    submission, monkeypatch
):
    value = submission
    monkeypatch.setattr(
        native_start_command,
        "enqueue_command",
        Mock(side_effect=ValueError("SYNTHETIC_START_STORAGE_FAILED")),
    )
    with (
        pytest.raises(ValueError, match="SYNTHETIC_START_STORAGE_FAILED"),
        value.publisher.sessions.begin() as session,
    ):
        submit(value, session)
    assert retained_rows(value) == ((), ())
    assert value.executor.mock_calls == []


def test_postgres_concurrent_original_private_submissions_reuse_one_workflow_and_start(
    submission, monkeypatch
):
    value = submission
    barrier, per_thread = Barrier(2), local()
    original = value.owner.resolve_submission

    def resolve(session, request, context):
        result = original(session, request, context)
        if not getattr(per_thread, "arrived", False):
            per_thread.arrived = True
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(value.owner, "resolve_submission", resolve)

    def run(_ordinal):
        with value.publisher.sessions.begin() as session:
            result = submit(value, session)
            return (
                result.workflow.workflow_id,
                result.command.command_id,
                result.workflow_created,
                result.command_created,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run, (0, 1)))
    assert len({row[:2] for row in results}) == 1
    assert sorted(row[2:] for row in results) == [(False, False), (True, True)]
    workflows, commands = retained_rows(value)
    assert len(workflows) == len(commands) == 1
    assert value.executor.mock_calls == []


def test_postgres_failed_original_workflow_is_not_replaced_or_revived(submission):
    value = submission
    with value.publisher.sessions.begin() as session:
        initial = submit(value, session)
        ids = initial.workflow.workflow_id, initial.command.command_id
        transition_workflow(
            session,
            ids[0],
            WorkflowState.FAILED,
            "SYNTHETIC_PRIVATE_FAILURE",
            actor_type="human",
            actor_id=value.context.origin.actor_id,
            command_id=ids[1],
        )
    with value.publisher.sessions.begin() as session:
        replay = submit(value, session)
        assert (replay.workflow.workflow_id, replay.command.command_id) == ids
        assert replay.workflow.state == "FAILED"
        assert not replay.workflow_created and not replay.command_created
    assert value.executor.mock_calls == []


def test_postgres_missing_original_start_is_not_synthesized_on_replay(submission):
    value = submission
    with value.publisher.sessions.begin() as session:
        workflow, created = create_workflow_instance(
            session,
            definition=session.get(WorkflowDefinitionRecord, value.definition_id),
            request=value.request,
            idempotency_key=private_chat_query_submission_key(value.context),
            actor_type="human",
            actor_id=value.context.origin.actor_id,
            private_chat_query_context=value.context,
            private_chat_query_owner=value.owner,
            private_chat_query_executor=value.executor,
        )
        assert created
        identity = workflow.workflow_id
    with (
        pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_SUBMISSION_REPLAY_INVALID"),
        value.publisher.sessions.begin() as session,
    ):
        submit(value, session)
    workflows, commands = retained_rows(value)
    assert tuple(row.workflow_id for row in workflows) == (identity,) and commands == ()
    assert value.executor.mock_calls == []


def test_postgres_submission_rejects_unrelated_pending_writes_before_autoflush(submission):
    value = submission
    with pytest.raises(SimilarityContextReadError), value.publisher.sessions.begin() as session:
        definition = session.get(WorkflowDefinitionRecord, value.definition_id)
        session.add(JobRecord(job_id="job_" + uuid4().hex))
        start_private_chat_query_in_session(
            session,
            definition=definition,
            request=value.request,
            context=value.context,
            actor_type="human",
            actor_id=value.context.origin.actor_id,
            owner=value.owner,
            executor=value.executor,
        )
    assert retained_rows(value) == ((), ())
    assert value.executor.mock_calls == []


def preparation_application(value):
    from eom_workflow_runner.private_chat_query_prepare_application import (
        NativePrivateChatQueryPreparation,
    )

    from tests.unit.test_private_chat_query_preparation import initial_selection
    from tests.unit.test_private_chat_query_prepare_application import private_runner

    offers = []

    def offer(workflow_id, _runner):
        # Independent connection proves original Workflow/START commit precedes
        # dispatch; seeing ORM objects in the same root would not prove this.
        workflows, commands = retained_rows(value)
        assert tuple(row.workflow_id for row in workflows) == (workflow_id,)
        assert len(commands) == 1 and commands[0].command_type == CommandType.START_WORKFLOW.value
        offers.append(workflow_id)
        return "BUSY"

    runner = private_runner(value.source, value.owner, value.executor)
    app = NativePrivateChatQueryPreparation(
        owner=value.owner,
        executor=value.executor,
        runner=runner,
        driver=SimpleNamespace(offer_private_chat_query=offer),
    )
    return app, initial_selection(value), offers


def test_postgres_private_application_commits_before_offer_and_replays_without_recapture(
    submission, monkeypatch
):
    value = submission
    app, selection, offers = preparation_application(value)
    first = app.prepare(value.context.origin, selection)
    assert first.status == "PENDING"
    monkeypatch.setattr(
        value.owner.catalog,
        "prepare_private_chat_context_in_session",
        Mock(side_effect=AssertionError("recapturing original private context")),
    )
    replay = app.prepare(value.context.origin, selection)
    assert first == replay and offers == [first.workflow_id, first.workflow_id]
    workflows, commands = retained_rows(value)
    assert len(workflows) == len(commands) == 1
    assert TEXT not in canonical_json_bytes(workflows[0].runtime_context).decode()
    assert value.executor.mock_calls == []


def test_postgres_private_application_late_source_denial_preserves_original_without_new_offer(
    submission,
):
    value = submission
    app, selection, offers = preparation_application(value)
    first = app.prepare(value.context.origin, selection)
    value.source.fault.value = "public_during_private_auth"
    with pytest.raises(SimilarityContextReadError):
        app.prepare(value.context.origin, selection)
    workflows, commands = retained_rows(value)
    assert tuple(row.workflow_id for row in workflows) == (first.workflow_id,)
    assert workflows[0].state == "REQUESTED" and len(commands) == 1
    assert offers == [first.workflow_id] and value.executor.mock_calls == []


@pytest.mark.parametrize("existing", ["absent", "inactive", "conflicting_hash"])
def test_postgres_real_static_private_import_is_exact_and_does_not_repair_history(
    guarded_engine, registered, existing
):
    """Real PostgreSQL in pg_temp only; no operator/source/native authority fixture."""
    compiled = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v1.yaml",
        set(),
    )
    assert workflow_definition_is_admitted(compiled.definition.definition_key, "1.0.0")
    with guarded_engine.connect() as connection, connection.begin():
        connection.execute(
            text(
                "CREATE TEMP TABLE workflow_definitions "
                "(LIKE app.workflow_definitions INCLUDING ALL) ON COMMIT DROP"
            )
        )
        translated = connection.execution_options(schema_translate_map={None: "pg_temp"})
        with Session(translated, autoflush=False) as session:
            if existing != "absent":
                row = WorkflowDefinitionRecord(
                    definition_id="wfdef_" + uuid4().hex,
                    definition_key=compiled.definition.definition_key,
                    definition_version=compiled.definition.definition_version,
                    schema_version=compiled.definition.schema_version,
                    canonical_definition=compiled.as_dict(),
                    definition_hash=compiled.sha256
                    if existing == "inactive"
                    else "sha256:" + "f" * 64,
                    active=existing != "inactive",
                    source_path="declared-retained-private-snapshot",
                )
                session.add(row)
                session.flush()
            if existing == "conflicting_hash":
                from eom_workflow_runner.errors import WorkflowError

                with pytest.raises(WorkflowError, match="different hash"):
                    import_workflow_definition(session, compiled)
                assert (
                    connection.scalar(
                        text("SELECT definition_hash FROM pg_temp.workflow_definitions")
                    )
                    == "sha256:" + "f" * 64
                )
                return
            record, created = import_workflow_definition(session, compiled)
            assert created is (existing == "absent")
            assert record.active is (existing == "absent")
            assert connection.scalar(text("SELECT active FROM pg_temp.workflow_definitions")) is (
                existing == "absent"
            )
            replay, replay_created = import_workflow_definition(session, compiled)
            assert replay.definition_id == record.definition_id and replay_created is False
            selected = admitted_workflow_definition(
                session,
                definition_key=compiled.definition.definition_key,
                definition_version=compiled.definition.definition_version,
            )
            assert (selected is not None) is (existing == "absent")


def test_postgres_private_application_failed_history_is_not_replaced_or_driven(submission):
    value = submission
    app, selection, offers = preparation_application(value)
    first = app.prepare(value.context.origin, selection)
    _, commands = retained_rows(value)
    with value.publisher.sessions.begin() as session:
        transition_workflow(
            session,
            first.workflow_id,
            WorkflowState.FAILED,
            "SYNTHETIC_PRIVATE_FAILURE",
            actor_type="human",
            actor_id=value.context.origin.actor_id,
            command_id=commands[0].command_id,
        )
    replay = app.prepare(value.context.origin, selection)
    assert replay.status == "FAILED" and replay.workflow_id == first.workflow_id
    assert replay.failure_code == "PRIVATE_CHAT_QUERY_EXECUTION_FAILED"
    workflows, commands = retained_rows(value)
    assert len(workflows) == len(commands) == 1 and workflows[0].state == "FAILED"
    assert offers == [first.workflow_id] and value.executor.mock_calls == []


def test_postgres_private_read_missing_never_creates_work_or_offers_driver(submission):
    from eom_workflow_runner.private_chat_query_prepare_application import (
        PrivateChatQueryNotPrepared,
    )

    value = submission
    app, selection, offers = preparation_application(value)
    with pytest.raises(PrivateChatQueryNotPrepared):
        app.read(value.context.origin, selection)
    assert retained_rows(value) == ((), ())
    assert not offers and value.executor.mock_calls == []


def test_postgres_private_read_preserves_original_pending_without_start_or_head_selection(
    submission, monkeypatch
):
    value = submission
    app, selection, offers = preparation_application(value)
    first = app.prepare(value.context.origin, selection)
    with value.publisher.sessions.begin() as session:
        jobs_before = session.scalar(select(func.count()).select_from(JobRecord))
        events_before = session.scalar(
            select(func.count())
            .select_from(WorkflowEventRecord)
            .where(WorkflowEventRecord.workflow_id == first.workflow_id)
        )
    monkeypatch.setattr(
        value.owner.catalog,
        "prepare_private_chat_context_in_session",
        Mock(side_effect=AssertionError("a read cannot select the current head")),
    )
    observed = app.read(value.context.origin, selection)
    assert observed == first and offers == [first.workflow_id]
    workflows, commands = retained_rows(value)
    assert len(workflows) == len(commands) == 1
    assert commands[0].state == "PENDING" and commands[0].attempts == 0
    assert commands[0].lease_generation == 0 and commands[0].lease_owner is None
    with value.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == jobs_before
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == first.workflow_id)
            )
            == events_before
        )
    assert value.executor.mock_calls == []


def test_postgres_private_read_revoked_origin_never_reprepares_or_drives(submission):
    value = submission
    app, selection, offers = preparation_application(value)
    first = app.prepare(value.context.origin, selection)
    value.source.fault.value = "claim"
    with pytest.raises(SimilarityContextReadError) as error:
        app.read(value.context.origin, selection)
    assert error.value.code == "AUTHORITY_UNAVAILABLE"
    workflows, commands = retained_rows(value)
    assert tuple(row.workflow_id for row in workflows) == (first.workflow_id,)
    assert len(commands) == 1 and commands[0].attempts == 0
    assert offers == [first.workflow_id] and value.executor.mock_calls == []


def test_postgres_private_read_failed_history_never_drives_or_reinterprets_success(submission):
    value = submission
    app, selection, offers = preparation_application(value)
    first = app.prepare(value.context.origin, selection)
    _, commands = retained_rows(value)
    with value.publisher.sessions.begin() as session:
        transition_workflow(
            session,
            first.workflow_id,
            WorkflowState.FAILED,
            "SYNTHETIC_PRIVATE_FAILURE",
            actor_type="human",
            actor_id=value.context.origin.actor_id,
            command_id=commands[0].command_id,
        )
    observed = app.read(value.context.origin, selection)
    assert observed.status == "FAILED" and observed.workflow_id == first.workflow_id
    workflows, commands = retained_rows(value)
    assert len(workflows) == len(commands) == 1 and workflows[0].state == "FAILED"
    assert offers == [first.workflow_id] and value.executor.mock_calls == []


@pytest.mark.parametrize("field", ("request_hash", "definition_hash", "request_payload"))
def test_postgres_private_read_retains_original_after_database_rejects_mutation(submission, field):
    value = submission
    app, selection, offers = preparation_application(value)
    first = app.prepare(value.context.origin, selection)
    workflows, _ = retained_rows(value)
    original = getattr(workflows[0], field)
    corrupted = {"invalid": True} if field == "request_payload" else "sha256:" + "f" * 64
    # The existing PostgreSQL immutability triggers must remain enabled. A failed
    # attempted mutation rolls back; the application then reads the same original.
    with (
        pytest.raises((IntegrityError, ProgrammingError)) as error,
        value.publisher.sessions.begin() as session,
    ):
        row = session.get(WorkflowInstanceRecord, first.workflow_id)
        setattr(row, field, corrupted)
    expected = (
        "PRIVATE_CHAT_QUERY_ORIGIN_IMMUTABLE"
        if field == "request_payload"
        else "workflow instance snapshot fields are immutable"
    )
    assert expected in str(error.value.orig)
    assert app.read(value.context.origin, selection) == first
    workflows, commands = retained_rows(value)
    assert len(workflows) == len(commands) == 1
    assert getattr(workflows[0], field) == original
    assert offers == [first.workflow_id] and value.executor.mock_calls == []
