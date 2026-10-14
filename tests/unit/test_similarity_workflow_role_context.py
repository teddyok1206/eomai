"""Real concurrent SQLite metadata reads; Identity/source/numerical admission is synthetic.

The plan metadata table deliberately omits PostgreSQL-only DDL constraints. These
are selector/application tests, not PostgreSQL persistence or live IAM acceptance.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_workflow.compiler import compile_definition_data
from eom_workflow.models import WorkflowRequest
from eom_workflow.reference_query_execution import ReferenceQueryWorkflowRequest
from eom_workflow.similarity_control import (
    parse_post_registration_grounded_plan,
    parse_similarity_execution_plan,
)
from eom_workflow_runner import similarity_role_preparation as module
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import workflow_business_fingerprint
from eom_workflow_runner.similarity_role_preparation import (
    SIMILARITY_QUERY_CONTEXT_KEY,
    CatalogWorkflowSimilarityRoleContextProvider,
)
from sqlalchemy import Column, MetaData, Table, create_engine, event
from sqlalchemy.orm import object_session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_execution_contracts import case as query_case
from tests.unit.test_reference_query_workflow_contracts import definition_body
from tests.unit.test_similarity_role_composition import provider_case


@pytest.fixture
def workflows(tmp_path, monkeypatch):
    template = provider_case(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "object_session", object_session)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'role-metadata.sqlite'}")
    for model in (WorkflowDefinitionRecord, WorkflowInstanceRecord, WorkflowStepRunRecord):
        model.__table__.create(engine)
    plan_metadata = MetaData()
    Table(
        ResolvedExecutionPlanRecord.__tablename__,
        plan_metadata,
        *(
            Column(
                column.name, column.type, primary_key=column.primary_key, nullable=column.nullable
            )
            for column in ResolvedExecutionPlanRecord.__table__.columns
        ),
    )
    plan_metadata.create_all(engine)
    sessions = build_session_factory(engine)
    native = compile_definition_data(definition_body(), "synthetic-stored-query", set())
    native_template = query_case(definition_sha256=native.sha256).request
    # The older role fixture intentionally has no vector index. A genuine QUERY
    # request must instead pin an index/runtime; construct coherent synthetic
    # control values without pretending to have executed or published that QUERY.
    context_body = template.case["context"].model_dump(mode="json")
    context_body["request"]["views"] = [
        view.model_dump(mode="json") for view in native_template.context_request.views
    ]
    context_body["request"] = seal(context_body["request"], "request_sha256")
    for view in context_body["population"]["views"]:
        view["reason"] = "QUERY_NOT_OFFERED"
    context = parse_similarity_context(seal(context_body, "context_sha256"))
    delivery_body = template.case["plan"].similarity_delivery.model_dump(mode="json")
    delivery_body["request_sha256"] = context.request.request_sha256
    delivery_body["context_sha256"] = context.context_sha256
    delivery_body["context_member"]["sha256"] = sha256_bytes(
        canonical_json_bytes(context.model_dump(mode="json"))
    )
    pointers, requests, observations = [], {}, []
    definition = WorkflowDefinitionRecord(
        definition_id=template.workflow.definition_id,
        definition_key=template.workflow.definition_key,
        definition_version=template.workflow.definition_version,
        definition_hash=template.workflow.definition_hash,
        schema_version="1.0",
        canonical_definition={},
        source_path="synthetic-role-metadata",
        active=True,
    )
    with sessions.begin() as session:
        session.add(definition)
        session.add(
            WorkflowDefinitionRecord(
                definition_id="wfdef_" + "1" * 32,
                definition_key=native.definition.definition_key,
                definition_version=native.definition.definition_version,
                definition_hash=native.sha256,
                schema_version=native.definition.schema_version,
                canonical_definition=native.as_dict(),
                source_path="synthetic-stored-query",
                active=True,
            )
        )
        for index, (seed, role) in enumerate((("e", "authoring"), ("f", "review")), 1):
            operator_id = "operator_" + seed * 32
            item_id, query_id = "workflow_" + seed * 32, "workflow_" + str(index) * 32
            raw_query = native_template.model_dump(mode="json")
            raw_query["context_request"] = context.request.model_dump(mode="json")
            raw_query["operator_audit"]["operator_id"] = operator_id
            original = ReferenceQueryWorkflowRequest.model_validate(
                seal(raw_query, "request_sha256")
            )
            selection = CompletedSimilarityQuerySelection(
                workflow_id=query_id,
                workflow_request_sha256=original.request_sha256,
                context_request_sha256=original.context_request.request_sha256,
            )
            raw_request = template.request.model_dump(mode="json")
            raw_request["item_brief"]["topic"] = f"합성 출제 요청 {index}"
            raw_request["item_brief"]["original_request_sha256"] = str(index) * 64
            request = WorkflowRequest.model_validate(raw_request)
            raw_plan = template.record.canonical_document | {
                "workflow_id": item_id,
                "plan_id": "execplan_" + seed * 32,
                "similarity_delivery": delivery_body,
            }
            plan = parse_similarity_execution_plan(seal(raw_plan, "plan_sha256"))
            runtime = deepcopy(template.workflow.runtime_context)
            runtime["execution_plan"] = {
                key: getattr(plan, key)
                for key in ("plan_id", "plan_sha256", "preset_id", "preset_revision_id")
            }
            runtime[SIMILARITY_QUERY_CONTEXT_KEY] = selection.model_dump(mode="json")
            session.add(
                WorkflowInstanceRecord(
                    workflow_id=item_id,
                    definition_id=definition.definition_id,
                    definition_key=definition.definition_key,
                    definition_version=definition.definition_version,
                    definition_hash=definition.definition_hash,
                    protocol_version="1.0.1",
                    role_schema_version="workflow-role/1.24.0",
                    state="RUNNING",
                    stage="AUTHORING" if role == "authoring" else "REVIEWING",
                    current_step_key=role,
                    initial_request=request.model_dump(mode="json"),
                    request_payload=request.model_dump(mode="json"),
                    runtime_context=runtime,
                    request_hash=workflow_business_fingerprint(definition, request),
                    idempotency_key=f"synthetic-item-{index}",
                    created_actor_type="human",
                    created_actor_id=operator_id,
                )
            )
            session.add(
                WorkflowInstanceRecord(
                    workflow_id=query_id,
                    definition_id="wfdef_" + "1" * 32,
                    definition_key=original.workflow_definition_key,
                    definition_version=original.workflow_definition_version,
                    definition_hash=original.workflow_definition_sha256,
                    protocol_version="1.0.1",
                    role_schema_version="reference-query/1.0",
                    state="COMPLETED",
                    stage="COMPLETED",
                    current_step_key="complete",
                    initial_request=original.model_dump(mode="json"),
                    request_payload=original.model_dump(mode="json"),
                    request_hash=original.request_sha256,
                    idempotency_key=f"synthetic-query-{index}",
                    created_actor_type="human",
                    created_actor_id=operator_id,
                )
            )
            session.add(
                ResolvedExecutionPlanRecord(
                    **{
                        column.name: getattr(plan, column.name)
                        for column in ResolvedExecutionPlanRecord.__table__.columns
                        if column.name not in {"canonical_document", "graph_snapshot_revision_id"}
                    },
                    graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
                    canonical_document=plan.model_dump(mode="json"),
                )
            )
            step_id = "steprun_" + seed * 32
            session.add(
                WorkflowStepRunRecord(
                    step_run_id=step_id,
                    workflow_id=item_id,
                    step_key=role,
                    attempt=1,
                    step_type="agent",
                    worker_role=role,
                    result_schema=f"{role}-result@12.0",
                    state="RUNNING",
                    input_pointer_manifest={},
                )
            )
            pointers.append(
                SimpleNamespace(
                    item_id=item_id,
                    query_id=query_id,
                    step_id=step_id,
                    operator_id=operator_id,
                    selection=selection,
                )
            )
            requests[item_id] = request

    def fence(session, operator_id):
        root = session.get_transaction()
        assert root is not None and root.is_active and not session.in_nested_transaction()
        observations.append((operator_id, session, root))

    owner = SimpleNamespace(
        identity=SimpleNamespace(fence_current_operator=Mock(side_effect=fence)),
        catalog=SimpleNamespace(engine=engine, read_similarity_materials_in_session=Mock()),
        settings=CatalogSettings(nas_artifact_root=tmp_path / "unused-artifact-root"),
        resolve_completed_sources=Mock(side_effect=AssertionError("source read not offered here")),
    )
    return SimpleNamespace(
        template=template,
        engine=engine,
        sessions=sessions,
        owner=owner,
        provider=CatalogWorkflowSimilarityRoleContextProvider(owner),
        pointers=tuple(pointers),
        requests=requests,
        observations=observations,
    )


def prepare(value, pointer):
    with value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, pointer.item_id)
        step = session.get(WorkflowStepRunRecord, pointer.step_id)
        root = session.get_transaction()
        result = value.provider.prepare(
            session,
            workflow=workflow,
            step=step,
            request=value.requests[pointer.item_id].worker_request(),
        )
        assert session.get_transaction() is root and not session.dirty and not session.new
        return result


def test_one_shared_provider_keeps_concurrent_creators_query_ids_and_roots_separate(workflows):
    value = workflows
    barrier = Barrier(2)
    original = value.owner.identity.fence_current_operator.side_effect

    def synchronized(session, operator_id):
        original(session, operator_id)
        barrier.wait(timeout=10)

    value.owner.identity.fence_current_operator.side_effect = synchronized
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda pointer: prepare(value, pointer), value.pointers))
    for pointer, result in zip(value.pointers, results, strict=True):
        assert result.workflow_id == pointer.item_id and result.operator_id == pointer.operator_id
        assert result.reader.reader.query.workflow_id == pointer.query_id
        assert result.reader.reader.query.request.operator_audit.operator_id == pointer.operator_id
    assert {actor for actor, _, _ in value.observations} == {p.operator_id for p in value.pointers}
    assert value.observations[0][1] is not value.observations[1][1]
    assert value.observations[0][2] is not value.observations[1][2]
    value.owner.resolve_completed_sources.assert_not_called()
    value.owner.catalog.read_similarity_materials_in_session.assert_not_called()
    assert vars(value.provider) == {"owner": value.owner}


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "extra_authority",
        "context_hash",
        "workflow_hash",
        "foreign_query",
        "query_pending",
        "query_changed",
        "item_plan",
    ),
)
def test_invalid_per_item_selection_cannot_fall_back_to_a_previous_query(workflows, fault):
    value = workflows
    first, second = value.pointers
    assert prepare(value, first) is not None
    value.owner.identity.fence_current_operator.reset_mock()
    with value.sessions.begin() as session:
        item = session.get(WorkflowInstanceRecord, first.item_id)
        runtime = deepcopy(item.runtime_context)
        selection = runtime[SIMILARITY_QUERY_CONTEXT_KEY]
        if fault == "missing":
            del runtime[SIMILARITY_QUERY_CONTEXT_KEY]
        elif fault == "extra_authority":
            selection["actor_id"] = second.operator_id
        elif fault in {"context_hash", "workflow_hash"}:
            selection[
                "context_request_sha256" if fault == "context_hash" else "workflow_request_sha256"
            ] = "sha256:" + "0" * 64
        elif fault == "foreign_query":
            runtime[SIMILARITY_QUERY_CONTEXT_KEY] = second.selection.model_dump(mode="json")
        elif fault == "item_plan":
            runtime["execution_plan"]["plan_sha256"] = "sha256:" + "0" * 64
        else:
            query = session.get(WorkflowInstanceRecord, first.query_id)
            if fault == "query_pending":
                query.state = "REQUESTED"
            else:
                query.request_payload = {"invalid": "do not silently repair"}
        item.runtime_context = runtime
    with pytest.raises(ControlPlaneError) as error:
        prepare(value, first)
    assert error.value.code == (
        "CONTROL_SIMILARITY_AUTHORITY_DENIED"
        if fault == "foreign_query"
        else "CONTROL_SIMILARITY_CONTEXT_INVALID"
    )
    if fault in {"missing", "extra_authority", "context_hash", "item_plan"}:
        value.owner.identity.fence_current_operator.assert_not_called()
    value.owner.resolve_completed_sources.assert_not_called()
    value.owner.catalog.read_similarity_materials_in_session.assert_not_called()


def test_current_identity_failure_does_not_use_previous_user_or_captured_query(workflows):
    value = workflows
    first, second = value.pointers
    assert prepare(value, first) is not None
    value.owner.identity.fence_current_operator.side_effect = OperatorAuthorizationFenceError(
        "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
    )
    with pytest.raises(ControlPlaneError) as error:
        prepare(value, second)
    assert error.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
    value.owner.resolve_completed_sources.assert_not_called()


def test_metadata_lookup_count_is_bounded_and_no_write_occurs(workflows):
    value = workflows
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(value.engine, "before_cursor_execute", capture)
    try:
        for pointer in value.pointers:
            assert prepare(value, pointer) is not None
    finally:
        event.remove(value.engine, "before_cursor_execute", capture)
    assert len(statements) == 14  # two caller loads + five indexed provider reads per item
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


@pytest.mark.parametrize("legacy", ("no_plan", "plan19"))
def test_original_execution_without_similarity_never_invents_a_query(workflows, legacy):
    value = workflows
    pointer = value.pointers[0]
    with value.sessions.begin() as session:
        item = session.get(WorkflowInstanceRecord, pointer.item_id)
        runtime = deepcopy(item.runtime_context)
        del runtime[SIMILARITY_QUERY_CONTEXT_KEY]
        if legacy == "no_plan":
            del runtime["execution_plan"]
        else:
            record = session.get(ResolvedExecutionPlanRecord, runtime["execution_plan"]["plan_id"])
            raw = deepcopy(record.canonical_document)
            raw.pop("similarity_delivery")
            raw.update(schema_version="resolved-execution-plan/19.0", resolver_version="19.0.0")
            original = parse_post_registration_grounded_plan(seal(raw, "plan_sha256"))
            record.canonical_document = original.model_dump(mode="json")
            record.plan_sha256 = original.plan_sha256
            runtime["execution_plan"]["plan_sha256"] = original.plan_sha256
        item.runtime_context = runtime
    assert prepare(value, pointer) is None
    value.owner.identity.fence_current_operator.assert_not_called()
    value.owner.resolve_completed_sources.assert_not_called()


@pytest.mark.parametrize("attempt", (2, 3))
def test_review_feedback_attempts_reuse_the_exact_original_query_selection(workflows, attempt):
    value = workflows
    pointer = value.pointers[1]
    with value.sessions.begin() as session:
        step = session.get(WorkflowStepRunRecord, pointer.step_id)
        item = session.get(WorkflowInstanceRecord, pointer.item_id)
        step.attempt = attempt
        item.rework_cycle_count = attempt - 1
    result = prepare(value, pointer)
    assert result.reader.reader.query.workflow_id == pointer.query_id
    assert (
        result.reader.reader.query.request.request_sha256
        == pointer.selection.workflow_request_sha256
    )
    value.owner.resolve_completed_sources.assert_not_called()
