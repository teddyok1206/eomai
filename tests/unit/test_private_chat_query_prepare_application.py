"""Real caller roots/Runner, declared admission and canonical-read ports; no live model."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_similarity import (
    PRIVATE_CHAT_LIMITATION_ORDER,
    PrivateChatSimilarityContext,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import content_sha256
from eom_workflow_runner import private_chat_query_prepare_application as module
from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.native_query_prepare_driver import NativeQueryPrepareDriver
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_preparation import (
    PrivateChatQueryPreparationUnavailable,
)
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_preparation import initial_selection
from tests.unit.test_private_chat_query_source_owner import source as source
from tests.unit.test_reference_query_prepare_application import NoRoleExecution


def private_runner(source, owner, executor):
    return WorkflowRunner(
        owner.catalog.engine,
        WorkflowSettings(),
        catalog=WorkflowCatalogService(owner.catalog.engine, owner.settings),
        actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(owner.catalog.engine)
        ),
        readiness=NoRoleExecution(),
        available_roles=frozenset(),
        private_chat_query_owner=owner,
        private_chat_query_executor=executor,
        command_families=frozenset({CommandExecutionFamily.PRIVATE_CHAT_QUERY}),
        command_actor_selection=NativeCommandActorSelection(
            "human", source.projection.origin.actor_id
        ),
        runner_config=RunnerConfig(
            version=1,
            poll_interval_seconds=5,
            command_lease_seconds=900,
            command_lease_heartbeat_seconds=30,
            max_commands_per_run=1,
        ),
    )


def empty_completed_context(source):
    request = source.request.context_request
    body = dict(
        schema_version="system-rag-private-chat-similarity-context/1.0",
        request=request.model_dump(mode="json"),
        status="EMPTY",
        population=dict(
            authorized_source_count=0,
            authorized_source_set_sha256=content_sha256([]),
            accepted_profile_count=0,
            accepted_profile_set_sha256=content_sha256([]),
            missing_report_count=0,
            truncated=False,
            views=[
                dict(
                    view="CONTENT_ONLY",
                    status="EMPTY",
                    available_binding_count=0,
                    binding_set_sha256=content_sha256([]),
                    scored_count=0,
                    missing_view_count=0,
                    reason=None,
                )
            ],
        ),
        query_execution=dict(
            job_id="job_" + "1" * 32,
            query_request_id="embeddingquery_" + "2" * 32,
            request_sha256="sha256:" + "a" * 64,
            input_set_sha256="sha256:" + "b" * 64,
            basis_sha256=request.query_basis.basis_sha256,
            result_member=dict(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                member_path="result.json",
                media_type="application/json",
                schema_ref="eom://schemas/knowledge/embedding-private-chat-query-result/1.0",
                sha256="sha256:" + "c" * 64,
            ),
            result_sha256="sha256:" + "d" * 64,
        ),
        candidates=[],
        limitations=[*PRIVATE_CHAT_LIMITATION_ORDER[:3], "NO_RELATED_CANDIDATES"],
        error_code=None,
    )
    return PrivateChatSimilarityContext.model_validate(seal(body, "context_sha256"))


@pytest.fixture
def application(source, monkeypatch):
    owner = CatalogPrivateChatQueryOwnerAdmission(source.owner)
    executor = Mock(spec=PrivateChatQueryNativeExecutor)
    runner = private_runner(source, owner, executor)
    driver = NativeQueryPrepareDriver()
    app = module.NativePrivateChatQueryPreparation(
        owner=owner, executor=executor, runner=runner, driver=driver
    )
    value = SimpleNamespace(
        source=source,
        owner=owner,
        executor=executor,
        runner=runner,
        driver=driver,
        app=app,
        roots=[],
        admitted=[],
        offers=[],
        state="REQUESTED",
        command_failure=None,
        compose_calls=[],
        context=None,
    )
    value.preparation = initial_selection(value)

    def admit(session, **kwargs):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        assert kwargs["caller"].operator_id == source.projection.origin.actor_id
        value.roots.append(session)
        value.admitted.append(kwargs)
        return SimpleNamespace(
            workflow=SimpleNamespace(
                workflow_id="workflow_" + "c" * 32,
                state=value.state,
                initial_request=source.request.model_dump(mode="json"),
            )
        )

    def offer(workflow, actual):
        assert value.roots[-1].get_transaction() is None and actual is runner
        value.offers.append(workflow)
        return "BUSY"  # Busy is still the same durable pending work, not a failed/new request.

    def compose(actual, caller, request):
        assert value.roots[-1].get_transaction() is None
        assert actual.owner.request.context_request == request == source.request.context_request
        assert actual.owner.origin == source.projection.origin
        value.compose_calls.append(request)
        return value.context

    monkeypatch.setattr(module, "prepare_and_start_private_chat_query_selection_in_session", admit)
    monkeypatch.setattr(driver, "offer_private_chat_query", offer)
    monkeypatch.setattr(module.PrivateChatSimilarityApplicationService, "compose", compose)
    original_scalar = app.sessions.class_.scalar

    def scalar(session, statement, *args, **kwargs):
        if statement.column_descriptions[0]["entity"] is WorkflowCommandRecord:
            return value.command_failure
        return original_scalar(session, statement, *args, **kwargs)

    monkeypatch.setattr(app.sessions.class_, "scalar", scalar)
    return value


def prepare(value):
    return value.app.prepare(value.source.projection.origin, value.preparation)


@pytest.mark.parametrize("state", ("REQUESTED", "RUNNING"))
def test_pending_commits_original_before_offering_the_same_finite_driver(application, state):
    value = application
    value.state = state
    first, replay = prepare(value), prepare(value)
    assert first == replay and first.status == "PENDING" and first.context is None
    assert value.offers == [first.workflow_id, first.workflow_id]
    assert all(row["origin"] == first.origin for row in value.admitted)
    assert all(row["preparation"] is value.preparation for row in value.admitted)
    assert not value.compose_calls
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


@pytest.mark.parametrize(
    "state,command", (("FAILED", None), ("CANCELLED", None), ("RUNNING", "failed"))
)
def test_terminal_failure_has_no_drive_read_or_automatic_new_work(application, state, command):
    value = application
    value.state, value.command_failure = state, command
    result = prepare(value)
    assert (
        result.status == "FAILED" and result.failure_code == "PRIVATE_CHAT_QUERY_EXECUTION_FAILED"
    )
    assert not value.offers and not value.compose_calls
    value.executor.execute.assert_not_called()


def test_unknown_workflow_state_is_explicit_failure_not_pending(application):
    value = application
    value.state = "unexpected"
    result = prepare(value)
    assert result.status == "FAILED" and result.failure_code == "QUERY_RESULT_INVALID"
    assert not value.offers and not value.compose_calls


def test_completed_work_is_ready_only_after_canonical_read_outside_admission_root(application):
    value = application
    value.state = "COMPLETED"
    value.context = empty_completed_context(value.source)
    value.command_failure = "historical non-authoritative failed command"
    result = prepare(value)
    assert result.status == "READY" and result.context == value.context
    assert value.compose_calls == [value.source.request.context_request] and not value.offers
    value.executor.execute.assert_not_called()


@pytest.mark.parametrize(
    "code", ("SOURCE_ACCESS_DENIED", "QUERY_RESULT_INVALID", "INDEX_POINTER_INVALID")
)
def test_completed_row_does_not_override_canonical_read_failure(application, code):
    value = application
    value.state = "COMPLETED"
    request = value.source.request.context_request
    value.context = PrivateChatSimilarityContext.model_validate(
        seal(
            dict(
                schema_version="system-rag-private-chat-similarity-context/1.0",
                request=request.model_dump(mode="json"),
                status="FAILED",
                population=None,
                query_execution=None,
                candidates=[],
                limitations=list(PRIVATE_CHAT_LIMITATION_ORDER[:3]),
                error_code=code,
            ),
            "context_sha256",
        )
    )
    with pytest.raises(SimilarityContextReadError) as error:
        prepare(value)
    assert error.value.code == code and not value.offers


def test_initial_missing_index_preserves_known_absence_without_offer(application, monkeypatch):
    value = application
    monkeypatch.setattr(
        module,
        "prepare_and_start_private_chat_query_selection_in_session",
        Mock(side_effect=PrivateChatQueryPreparationUnavailable()),
    )
    with pytest.raises(PrivateChatQueryPreparationUnavailable):
        prepare(value)
    assert not value.offers and not value.compose_calls


def test_completed_row_with_unavailable_query_never_claims_ready_or_restarts(application):
    value = application
    value.state = "COMPLETED"
    body = empty_completed_context(value.source).model_dump(mode="json")
    body.update(
        status="UNAVAILABLE",
        query_execution=None,
        limitations=[
            *PRIVATE_CHAT_LIMITATION_ORDER[:3],
            "VECTOR_NOT_AVAILABLE",
            "NO_RELATED_CANDIDATES",
        ],
    )
    body["population"]["views"][0].update(
        status="UNAVAILABLE",
        available_binding_count=None,
        binding_set_sha256=None,
        missing_view_count=None,
        reason="QUERY_NOT_OFFERED",
    )
    value.context = PrivateChatSimilarityContext.model_validate(seal(body, "context_sha256"))
    with pytest.raises(SimilarityContextReadError) as error:
        prepare(value)
    assert error.value.code == "QUERY_RESULT_INVALID" and not value.offers


@pytest.mark.parametrize("offer", ("STARTED", "ALREADY_ACTIVE", "UNAVAILABLE"))
def test_drive_observation_does_not_replace_or_reclassify_original_pending_work(application, offer):
    value = application

    def observe(workflow, actual):
        assert value.roots[-1].get_transaction() is None and actual is value.runner
        assert workflow == "workflow_" + "c" * 32
        return offer

    value.app.driver = SimpleNamespace(offer_private_chat_query=observe)
    result = prepare(value)
    assert result.status == "PENDING" and len(value.admitted) == 1 and not value.compose_calls
    value.executor.execute.assert_not_called()


@pytest.mark.parametrize("fault", ("family", "actor_type", "owner", "roles", "executor", "engine"))
def test_composition_changes_are_refused_before_admission(application, fault):
    value = application
    if fault == "family":
        value.runner.command_families = frozenset({CommandExecutionFamily.REFERENCE_QUERY})
    elif fault == "actor_type":
        value.runner.command_actor_selection = NativeCommandActorSelection(
            "local_indexing_service", "localindexservice_" + "f" * 32
        )
    elif fault == "owner":
        value.runner.private_chat_query_owner = None
    elif fault == "roles":
        value.runner.available_roles = frozenset({"authoring"})
    elif fault == "executor":
        value.runner.executor = object()
    else:
        value.runner.engine = object()
    with pytest.raises(ValueError, match="PREPARE_RUNNER_INVALID"):
        prepare(value)
    assert not value.admitted and not value.offers


def test_result_cannot_claim_ready_or_pending_with_wrong_materialization(application):
    value = application
    pending = prepare(value)
    with pytest.raises(ValueError, match="PREPARE_RESULT_INVALID"):
        replace(pending, status="READY")
    with pytest.raises(ValueError, match="PREPARE_RESULT_INVALID"):
        replace(pending, context=empty_completed_context(value.source))
    context = empty_completed_context(value.source)
    normalized = replace(pending, status="READY", context=context.model_dump(mode="json"))
    assert isinstance(normalized.context, PrivateChatSimilarityContext)
    assert normalized.context == context


def test_finite_driver_is_shared_with_the_preserved_reference_import():
    from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver

    assert ReferenceQueryPrepareDriver is NativeQueryPrepareDriver


@pytest.mark.parametrize("fault", ("owner", "executor", "driver"))
def test_valid_but_replaced_composition_cannot_mix_admission_and_drive(application, fault):
    value = application
    if fault == "owner":
        value.runner.private_chat_query_owner = CatalogPrivateChatQueryOwnerAdmission(
            value.source.owner
        )
    elif fault == "executor":
        value.runner.private_chat_query_executor = Mock(spec=PrivateChatQueryNativeExecutor)
    else:
        value.app.driver = object()
    with pytest.raises(ValueError, match="PREPARE_COMPOSITION_INVALID"):
        prepare(value)
    assert not value.admitted and not value.offers


@pytest.mark.parametrize("fault", ("origin_actor", "selected_actor", "current_identity"))
def test_real_atomic_entry_rechecks_original_actor_and_current_identity(
    application, monkeypatch, fault
):
    from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
    from eom_identity_service import OperatorAuthorizationFenceError
    from eom_workflow_runner.private_chat_query_preparation import (
        prepare_and_start_private_chat_query_selection_in_session,
    )

    value = application
    monkeypatch.setattr(
        module,
        "prepare_and_start_private_chat_query_selection_in_session",
        prepare_and_start_private_chat_query_selection_in_session,
    )
    origin = value.source.projection.origin
    expected = ValueError
    if fault == "origin_actor":
        origin = ChatPrivateQueryOrigin.model_validate(
            seal(
                origin.model_dump(mode="json") | {"actor_id": "operator_" + "f" * 32},
                "origin_sha256",
            )
        )
    elif fault == "selected_actor":
        value.runner.command_actor_selection = NativeCommandActorSelection(
            "human", "operator_" + "f" * 32
        )
    else:
        value.source.fault.value = "identity"
        expected = OperatorAuthorizationFenceError
    with pytest.raises(expected):
        value.app.prepare(origin, value.preparation)
    assert not value.offers and not value.compose_calls
    value.executor.execute.assert_not_called()
