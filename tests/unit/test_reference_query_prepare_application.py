"""Real roots/owner/Runner composition; admission/status and IAM/source are synthetic seams."""

import ast
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    parse_supported_reference_query_prepare_request,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identity_service import OperatorAuthorizationFenceError
from eom_workflow_runner import reference_query_prepare_application as module
from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.reference_query_preparation import ReferenceQueryPreparationUnavailable
from eom_workflow_runner.reference_query_prepare_application import (
    NativeReferenceQueryPreparation,
    reference_query_prepare_identity,
)
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_owner_admission import source as source


class NoRoleExecution:
    def evaluate(self):
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "role_execution", ReadinessStatus.FAIL, "ROLE_DISABLED", "native QUERY only"
                ),
            )
        )


def query_runner(owner, executor):
    return WorkflowRunner(
        owner.catalog.engine,
        WorkflowSettings(),
        catalog=WorkflowCatalogService(owner.catalog.engine, owner.settings),
        actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(owner.catalog.engine)
        ),
        readiness=NoRoleExecution(),
        available_roles=frozenset(),
        reference_query_owner=owner,
        reference_query_executor=executor,
        command_families=frozenset({CommandExecutionFamily.REFERENCE_QUERY}),
        command_actor_selection=NativeCommandActorSelection(
            "human", owner.identity.capture.operator_id
        ),
        runner_config=RunnerConfig(
            version=1,
            poll_interval_seconds=5,
            command_lease_seconds=900,
            command_lease_heartbeat_seconds=30,
            max_commands_per_run=1,
        ),
    )


def wire_request(source, *, key="synthetic-native-preparation:one", operation="a"):
    context = source.request.context_request
    body = {
        "schema_version": "system-rag-reference-query-prepare-request/1.0",
        "operation": "PREPARE_REFERENCE_QUERY",
        "operation_id": "queryprepare_" + operation * 32,
        "idempotency_key": key,
        "source_item_revision_id": context.anchor.source.item_revision_id,
        "graph_snapshot": context.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": context.policy_revision_id,
        "policy_sha256": context.policy_sha256,
    }
    if context.consumer_purpose != "PAST_EXAM_VARIATION":
        body.update(
            schema_version="system-rag-reference-query-prepare-request/1.1",
            consumer_purpose=context.consumer_purpose,
        )
    return parse_supported_reference_query_prepare_request(seal(body, "request_sha256"))


@pytest.fixture
def application(source, monkeypatch):
    return make_application(source, monkeypatch)


def make_application(source, monkeypatch):
    executor = Mock(spec=ReferenceQueryNativeExecutor)
    runner = query_runner(source.owner, executor)
    driver = ReferenceQueryPrepareDriver()
    app = NativeReferenceQueryPreparation(
        owner=source.owner,
        executor=executor,
        runner=runner,
        driver=driver,
        spaces=source.policy.spaces,
    )
    value = SimpleNamespace(
        source=source,
        app=app,
        runner=runner,
        executor=executor,
        driver=driver,
        roots=[],
        admitted=[],
        offers=[],
        state="REQUESTED",
        failed_command=None,
    )

    def admit(session, **kwargs):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        value.roots.append(session)
        value.admitted.append(kwargs)
        return SimpleNamespace(
            workflow=SimpleNamespace(
                workflow_id="workflow_" + "c" * 32,
                state=value.state,
                initial_request=source.request.model_dump(mode="json"),
            )
        )

    def offer(workflow_id, actual):
        assert value.roots[-1].get_transaction() is None
        assert actual is runner
        value.offers.append(workflow_id)
        return "STARTED"

    monkeypatch.setattr(module, "prepare_and_start_reference_query_selection_in_session", admit)
    monkeypatch.setattr(driver, "offer", offer)
    original_scalar = app.sessions.class_.scalar

    def scalar(session, statement, *args, **kwargs):
        if statement.column_descriptions[0]["entity"] is WorkflowCommandRecord:
            return value.failed_command
        return original_scalar(session, statement, *args, **kwargs)

    monkeypatch.setattr(app.sessions.class_, "scalar", scalar)
    return value


@pytest.mark.parametrize("purpose", ("ITEM_AUTHORING", "ITEM_REVIEW"))
def test_explicit_new_purpose_reaches_existing_preparation_without_new_native_key(
    tmp_path, monkeypatch, purpose
):
    from tests.unit.test_reference_query_owner_admission import make_source_case

    value = make_application(
        make_source_case(tmp_path, monkeypatch, consumer_purpose=purpose), monkeypatch
    )
    request = wire_request(value.source)
    reply = value.app.prepare(request)
    assert reply.status == "PENDING"
    received = value.admitted[0]
    key, context_id = reference_query_prepare_identity(
        value.source.owner.identity.capture.operator_id, request.idempotency_key
    )
    assert received["preparation"].consumer_purpose == purpose
    assert received["preparation"].request_id == context_id
    assert received["idempotency_key"] == key
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


def test_pending_is_original_work_and_only_offers_driver_after_root_commit(application):
    value = application
    request = wire_request(value.source)
    reply = value.app.prepare(request)
    assert reply.status == "PENDING" and reply.selection is None
    assert value.offers == [reply.workflow_id]
    received = value.admitted[0]
    key, logical = reference_query_prepare_identity(
        value.source.owner.identity.capture.operator_id, request.idempotency_key
    )
    assert received["idempotency_key"] == key
    assert received["preparation"].request_id == logical
    assert received["preparation"].selection.source_revision_ids == (
        request.source_item_revision_id,
    )
    assert received["preparation"].views == ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY")
    assert received["preparation"].top_k == 8
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


def test_new_operation_id_reuses_native_scope_and_actual_operator_is_in_key(application):
    value = application
    first, second = wire_request(value.source), wire_request(value.source, operation="b")
    assert first.request_sha256 != second.request_sha256
    assert value.app.prepare(first).workflow_id == value.app.prepare(second).workflow_id
    assert value.admitted[0]["idempotency_key"] == value.admitted[1]["idempotency_key"]
    assert value.admitted[0]["preparation"] == value.admitted[1]["preparation"]
    assert reference_query_prepare_identity("operator_" + "f" * 32, first.idempotency_key) != (
        value.admitted[0]["idempotency_key"],
        value.admitted[0]["preparation"].request_id,
    )


@pytest.mark.parametrize("code", ("ANCHOR_REPORT_MISSING", "INDEX_NOT_PREPARED"))
def test_known_absence_rolls_back_and_never_offers_work(application, monkeypatch, code):
    value = application
    monkeypatch.setattr(
        module,
        "prepare_and_start_reference_query_selection_in_session",
        Mock(side_effect=ReferenceQueryPreparationUnavailable(code)),
    )
    reply = value.app.prepare(wire_request(value.source))
    assert reply.status == "UNAVAILABLE" and reply.error_code == code
    assert reply.workflow_id is None and reply.selection is None and value.offers == []


@pytest.mark.parametrize(
    "exception,code",
    (
        (EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN"), "SOURCE_ACCESS_DENIED"),
        (
            EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH"),
            "SOURCE_POINTER_INVALID",
        ),
        (OperatorAuthorizationFenceError("synthetic"), "AUTHORITY_UNAVAILABLE"),
        (SimilarityContextReadError("SOURCE_REVOKED"), "SOURCE_REVOKED"),
    ),
)
def test_denial_or_corruption_is_failure_not_auxiliary_absence(
    application, monkeypatch, exception, code
):
    value = application
    monkeypatch.setattr(
        module,
        "prepare_and_start_reference_query_selection_in_session",
        Mock(side_effect=exception),
    )
    reply = value.app.prepare(wire_request(value.source))
    assert reply.status == "FAILED" and reply.error_code == code and reply.selection is None
    assert value.offers == []


@pytest.mark.parametrize(
    "reason,logged",
    (
        (
            "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID",
            "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID",
        ),
        ("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN", "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"),
        ("secret-do-not-echo", "UNCLASSIFIED"),
    ),
)
def test_identity_diagnostics_are_closed_and_do_not_change_the_public_failure(
    application, monkeypatch, caplog, reason, logged
):
    value = application
    error = OperatorAuthorizationFenceError(reason)
    monkeypatch.setattr(
        module,
        "prepare_and_start_reference_query_selection_in_session",
        Mock(side_effect=error),
    )
    reply = value.app.prepare(wire_request(value.source))
    assert reply.status == "FAILED" and reply.error_code == "AUTHORITY_UNAVAILABLE"
    assert reply.workflow_id is None and reply.selection is None and value.offers == []
    messages = [record.getMessage() for record in caplog.records if record.name == module.__name__]
    assert messages == [f"REFERENCE_QUERY_PREPARATION_REJECTED boundary=IDENTITY reason={logged}"]
    assert "secret-do-not-echo" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("state", ("FAILED", "CANCELLED", "failed_command"))
def test_terminal_failed_history_is_not_retried(application, state):
    value = application
    if state == "failed_command":
        value.failed_command = "wfcmd_" + "d" * 32
    else:
        value.state = state
    reply = value.app.prepare(wire_request(value.source))
    assert reply.status == "FAILED" and reply.error_code == "REFERENCE_QUERY_EXECUTION_FAILED"
    assert reply.workflow_id is not None and value.offers == []


def test_foreign_workflow_stage_never_becomes_pending_executable_work(application):
    value = application
    value.state = "AWAITING_HUMAN_APPROVAL"
    reply = value.app.prepare(wire_request(value.source))
    assert reply.status == "FAILED" and reply.error_code == "QUERY_RESULT_INVALID"
    assert value.offers == []


def test_completed_state_requires_canonical_reader_before_ready(application, monkeypatch):
    value = application
    value.state = "COMPLETED"
    verify = Mock()
    reader = Mock(return_value=SimpleNamespace(resolve_reference_query_in_session=verify))
    monkeypatch.setattr(module, "CatalogCompletedReferenceQueryRead", reader)
    reply = value.app.prepare(wire_request(value.source))
    assert reply.status == "READY" and reply.selection.workflow_id == reply.workflow_id
    assert verify.call_count == 1 and value.offers == []
    verify.side_effect = SimilarityContextReadError("QUERY_RESULT_INVALID")
    failed = value.app.prepare(wire_request(value.source))
    assert failed.status == "FAILED" and failed.selection is None
    assert value.offers == []


def test_untrusted_extras_fail_before_admission(application):
    value = application
    request = wire_request(value.source).model_copy(update={"actor_id": "operator_" + "f" * 32})
    with pytest.raises((ValueError, SchemaError)):
        value.app.prepare(request)
    assert value.admitted == [] and value.offers == []


def test_application_owns_drive_port_without_thread_adapter_dependency():
    tree = ast.parse(inspect.getsource(module))
    modules = {value.module for value in ast.walk(tree) if isinstance(value, ast.ImportFrom)} | {
        name.name
        for value in ast.walk(tree)
        if isinstance(value, ast.Import)
        for name in value.names
    }
    assert "threading" not in modules
    assert "eom_workflow_runner.reference_query_prepare_driver" not in modules
    assert hasattr(module.ReferenceQueryPrepareDrivePort, "offer")
