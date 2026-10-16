"""Private start acceptance with real temporary storage and synthetic Catalog/control owners.

SQLite checks atomic application metadata, not PostgreSQL constraints or live IAM.
The numerical QUERY, source Evidence/control admission and resolver's final record
owner remain explicit synthetic seams. No production database or model is used.
"""

from __future__ import annotations

import os
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.services import command_adapter as module
from eom_api.services.command_adapter import CommandAdapter
from eom_api.services.item_similarity_preparation import ItemSimilarityStartPreparationService
from eom_api.services.item_similarity_publication_client import (
    CatalogItemSimilarityPublicationClient,
)
from eom_api.services.item_similarity_start import (
    SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
    check_similarity_start,
)
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_service import item_similarity_publication_service as publication_module
from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from eom_orchestrator import execution_resolver as resolver_module
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_workflow.similarity_control import parse_post_registration_grounded_plan
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.similarity_role_preparation import SIMILARITY_QUERY_CONTEXT_KEY
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, Table, event, func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.item_similarity_start_fixtures import start_source
from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_item_similarity_preparation import prepare
from tests.unit.test_knowledge_backed_execution import _Session
from tests.unit.test_similarity_context_artifact import SOURCE

ROOT = Path(__file__).resolve().parents[2]
KEY = "api:" + "7" * 64


@pytest.fixture
def start_case(tmp_path, monkeypatch, request):
    data = start_source(tmp_path, monkeypatch, ordinary=getattr(request, "param", False))
    source, api_request = data.source, data.request
    prepared = prepare(source)
    actor, runtime, definition = data.actor, data.runtime, data.definition
    engine, sessions = source.publisher.engine, source.publisher.sessions
    for model in (
        WorkflowDefinitionRecord,
        WorkflowInstanceRecord,
        WorkflowEventRecord,
        WorkflowCommandRecord,
    ):
        model.__table__.create(engine)
    # Source checks use PostgreSQL-only constraints in their actual gate. This
    # temporary metadata table is explicitly not that persistence acceptance.
    metadata = MetaData()
    Table(
        ResolvedExecutionPlanRecord.__tablename__,
        metadata,
        *(
            Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
            for c in ResolvedExecutionPlanRecord.__table__.columns
        ),
    )
    metadata.create_all(engine)
    with sessions.begin() as session:
        session.add(definition)

    # Keep nested SAVEPOINTs inside a real outer transaction for rollback tests.
    # Only this new temporary engine is changed, after source publication completes.
    engine.dispose()

    @event.listens_for(engine, "connect")
    def explicit_transactions(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    client = SimpleNamespace(create_item_production_evidence=Mock(return_value=source.evidence))
    adapter = CommandAdapter(engine, catalog_application=client)
    adapter.catalog = SimpleNamespace(
        bind_request=Mock(side_effect=lambda *a, **kw: deepcopy(runtime))
    )
    adapter._resolve_past_exam_source_material_requirement = Mock(return_value=None)
    monkeypatch.setattr(module, "current_knowledge_backed_preset", lambda *a, **kw: source.preset)
    real_resolve = module.resolve_knowledge_backed_execution_plan
    current_sessions, records = [], []

    def record(_synthetic_controls, *, document, dependencies):
        actual = current_sessions[-1]
        plan = parse_post_registration_grounded_plan(document)
        assert plan.workflow_id == dependencies.workflow_id
        row = ResolvedExecutionPlanRecord(
            **{
                c.name: getattr(plan, c.name)
                for c in ResolvedExecutionPlanRecord.__table__.columns
                if c.name not in {"canonical_document", "graph_snapshot_revision_id"}
            },
            canonical_document=document,
            graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        )
        actual.add(row)
        actual.flush()
        records.append((plan.schema_version, actual, actual.get_transaction()))
        return row

    def resolve(actual, **kwargs):
        current_sessions.append(actual)
        return real_resolve(_Session(source.preset), **kwargs)

    monkeypatch.setattr(module, "resolve_knowledge_backed_execution_plan", resolve)
    monkeypatch.setattr(resolver_module, "record_knowledge_backed_execution_plan", record)
    return SimpleNamespace(
        source=source,
        prepared=prepared,
        actor=actor,
        request=api_request,
        runtime=runtime,
        definition=definition,
        adapter=adapter,
        engine=engine,
        sessions=sessions,
        client=client,
        records=records,
    )


def start(value, *, prepared=True, key=KEY):
    return value.adapter.start_workflow(
        value.request,
        value.actor,
        idempotency_key=key,
        prepared_similarity=value.prepared if prepared else None,
    )


def row_counts(value):
    with value.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                WorkflowInstanceRecord,
                ResolvedExecutionPlanRecord,
                WorkflowCommandRecord,
            )
        )


def test_first_start_commits_one_plan23_selector_acceptance_and_start_together(start_case):
    value = start_case
    receipt = start(value)
    assert row_counts(value) == (1, 1, 1)
    assert [schema for schema, _, _ in value.records] == ["resolved-execution-plan/23.0"]
    with value.sessions() as session:
        item = session.get(WorkflowInstanceRecord, receipt[1])
        pin = item.runtime_context["execution_plan"]
        record = session.get(ResolvedExecutionPlanRecord, pin["plan_id"])
        command = session.get(WorkflowCommandRecord, receipt[0])
        assert record.workflow_id == item.workflow_id == command.workflow_id
        assert command.state == "PENDING"
        assert item.runtime_context[
            SIMILARITY_QUERY_CONTEXT_KEY
        ] == value.prepared.query_selection.model_dump(mode="json")
        checked = check_similarity_start(value.prepared, value.source.request, value.actor)
        assert item.runtime_context[SIMILARITY_PREPARATION_ACCEPTANCE_KEY] == checked.fingerprint
        assert "candidates" not in canonical_json_bytes(item.runtime_context).decode()
        assert "query_execution" not in canonical_json_bytes(item.runtime_context).decode()


def test_socket_preparation_producer_is_accepted_as_the_first_and_only_plan23(
    start_case, tmp_path, monkeypatch
):
    value = start_case
    query = value.source.value.query
    query.owner.catalog.engine = value.engine
    # This fixture's original native QUERY/current sources are deliberately synthetic.
    # Keep real Unix framing, API preparation, publisher and item-start/plan owners.
    monkeypatch.setattr(
        publication_module,
        "select_completed_reference_query_request",
        Mock(return_value=query.request),
    )
    monkeypatch.setattr(
        publication_module, "CatalogCompletedReferenceQueryRead", Mock(return_value=query)
    )
    server = _server(tmp_path)
    server.item_similarity_publications = CatalogItemSimilarityPublicationService(
        query.owner, value.source.publisher, source_commit=SOURCE
    )
    server.similarity_context_reads = SimpleNamespace(
        read=Mock(return_value=value.prepared.plan.context)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        producer = ItemSimilarityStartPreparationService(
            CatalogItemSimilarityPublicationClient(endpoint),
            CatalogSimilarityContextClient(endpoint),
        )
        produced = producer.prepare(
            value.actor,
            value.prepared.query_selection,
            workflow_request=value.source.request,
            expected_resolution=value.source.resolution,
            evidence=value.source.evidence,
            preset=value.source.preset,
        )
        assert produced == value.prepared
        receipt = value.adapter.start_workflow(
            value.request, value.actor, idempotency_key=KEY, prepared_similarity=produced
        )
        assert receipt == start(value)
        assert row_counts(value) == (1, 1, 1)
        assert [schema for schema, _, _ in value.records] == ["resolved-execution-plan/23.0"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("with_preparation", (False, True))
def test_exact_receipt_replay_uses_no_current_controls_or_catalog(start_case, with_preparation):
    value = start_case
    original = start(value)
    value.client.create_item_production_evidence.side_effect = AssertionError("no new Catalog work")
    value.adapter.catalog.bind_request.side_effect = AssertionError("no current pack resolution")
    assert start(value, prepared=with_preparation) == original
    assert row_counts(value) == (1, 1, 1) and len(value.records) == 1


def test_changed_private_preparation_cannot_replace_original_or_active_equivalent(start_case):
    value = start_case
    original = start(value)
    value.prepared = replace(value.prepared, evidence_result_sha256="sha256:" + "0" * 64)
    for key in (KEY, "api:" + "6" * 64):
        with pytest.raises(ApiError) as caught:
            start(value, key=key)
        assert caught.value.error_code == "CONTROL_SIMILARITY_PREPARATION_CONFLICT"
    assert row_counts(value) == (1, 1, 1) and len(value.records) == 1
    with value.sessions() as session:
        assert session.get(WorkflowCommandRecord, original[0]).state == "PENDING"


def test_exact_active_equivalent_keeps_the_first_selector_plan_and_command(start_case):
    value = start_case
    original = start(value)
    assert start(value, key="api:" + "6" * 64) == original
    assert row_counts(value) == (1, 1, 1) and len(value.records) == 1


def test_other_actual_operator_cannot_accept_the_first_operators_auxiliary_binding(start_case):
    value = start_case
    original = start(value)
    operator_id = "operator_" + "0" * 32
    value.actor = value.actor.model_copy(update={"operator_id": operator_id})
    value.prepared = replace(value.prepared, operator_id=operator_id)
    with pytest.raises(ApiError) as caught:
        start(value, key="api:" + "6" * 64)
    assert caught.value.error_code == "CONTROL_SIMILARITY_PREPARATION_CONFLICT"
    assert row_counts(value) == (1, 1, 1) and len(value.records) == 1
    with value.sessions() as session:
        assert session.get(WorkflowInstanceRecord, original[1]).created_actor_id != operator_id


def test_original_metadata_receipt_survives_canonical_source_withdrawal_without_source_read(
    start_case,
):
    from eom_orchestrator.models import ArtifactRecord

    value = start_case
    original = start(value)
    with value.sessions.begin() as session:
        session.scalar(select(ArtifactRecord)).approved = False
    value.client.create_item_production_evidence.side_effect = AssertionError(
        "no current source read"
    )
    assert start(value) == original
    assert start(value, prepared=False) == original
    assert row_counts(value) == (1, 1, 1)


def test_acceptance_fingerprint_is_deterministic_and_not_a_source_or_permission_cache(start_case):
    from eom_api.services.item_similarity_start import require_similarity_start_replay
    from eom_identifiers import content_sha256

    value = start_case
    checked = check_similarity_start(value.prepared, value.source.request, value.actor)
    expected = {
        "purpose": "ITEM_SIMILARITY_PREPARATION_V1",
        "operator_id": value.prepared.operator_id,
        "workflow_request_sha256": value.prepared.workflow_request_sha256,
        "evidence_result_sha256": value.prepared.evidence_result_sha256,
        "preset_content_sha256": value.prepared.preset_content_sha256,
        "resolution": value.prepared.resolution.model_dump(mode="json"),
        "query_selection": value.prepared.query_selection.model_dump(mode="json"),
        "delivery": value.prepared.plan.delivery.model_dump(mode="json"),
        "context_sha256": value.prepared.plan.context.context_sha256,
        "publication": {
            "owner_job_id": value.prepared.publication.owner_job_id,
            "manifest_sha256": value.prepared.publication.manifest_sha256,
        },
    }
    assert checked.fingerprint == content_sha256(expected)
    assert check_similarity_start(value.prepared, value.source.request, value.actor) == checked
    with pytest.raises(ApiError, match="CONTROL_SIMILARITY_PREPARATION_CONFLICT"):
        require_similarity_start_replay(
            {SIMILARITY_PREPARATION_ACCEPTANCE_KEY: checked.fingerprint}, checked
        )


def test_legacy_plan19_never_acquires_preparation_on_replay_or_equivalent_start(start_case):
    value = start_case
    original = start(value, prepared=False)
    assert [schema for schema, _, _ in value.records] == ["resolved-execution-plan/19.0"]
    for key in (KEY, "api:" + "6" * 64):
        with pytest.raises(ApiError) as caught:
            start(value, key=key)
        assert caught.value.error_code == "CONTROL_SIMILARITY_PREPARATION_CONFLICT"
    assert start(value, prepared=False) == original
    assert row_counts(value) == (1, 1, 1)


@pytest.mark.parametrize("fault", ("pack", "preset", "evidence", "enqueue"))
def test_invalid_or_failed_first_acceptance_rolls_back_all_workflow_metadata(
    start_case, monkeypatch, fault
):
    value = start_case
    if fault == "pack":
        value.runtime["content_pack"]["source_tree_sha256"] = "sha256:" + "0" * 64
    elif fault == "preset":
        body = value.source.preset.model_dump(mode="json")
        body["display_name"] = "different synthetic released preset"
        value.source.preset = type(value.source.preset).model_validate(seal(body, "content_sha256"))
    elif fault == "evidence":
        body = value.source.evidence.model_dump(mode="json")
        body["requester_permissions_sha256"] = "sha256:" + "0" * 64
        value.client.create_item_production_evidence.return_value = type(
            value.source.evidence
        ).model_validate(seal(body, "result_sha256"))
    else:
        monkeypatch.setattr(
            module, "enqueue_command", Mock(side_effect=RuntimeError("synthetic-enqueue-failure"))
        )
    with pytest.raises((ApiError, RuntimeError)):
        start(value)
    assert row_counts(value) == (0, 0, 0)
    # Independently published context survives; no model/Artifact deletion/retry.
    assert value.source.publisher.settings.nas_artifact_root.exists()
    assert len(tuple(value.source.publisher.settings.nas_artifact_root.rglob("context.json"))) == 1


@pytest.mark.parametrize(
    "fault",
    (
        "caller",
        "permission",
        "request_hash",
        "selector_extra",
        "resolution_extra",
        "producer",
        "context",
    ),
)
def test_malformed_private_handoff_is_rejected_before_catalog_or_workflow_work(start_case, fault):
    value = start_case
    if fault == "caller":
        value.actor = value.actor.model_copy(update={"operator_id": "operator_" + "0" * 32})
    elif fault == "permission":
        value.actor = value.actor.model_copy(
            update={"permissions": frozenset({PermissionKey.ITEM_READ})}
        )
    elif fault == "request_hash":
        value.prepared = replace(value.prepared, workflow_request_sha256="sha256:" + "0" * 64)
    elif fault == "selector_extra":
        value.prepared = replace(
            value.prepared,
            query_selection=value.prepared.query_selection.model_copy(update={"role": "ADMIN"}),
        )
    elif fault == "resolution_extra":
        value.prepared = replace(
            value.prepared, resolution=value.prepared.resolution.model_copy(update={"latest": True})
        )
    elif fault == "producer":
        value.prepared = replace(
            value.prepared,
            publication=replace(value.prepared.publication, owner_job_id="not-a-job"),
        )
    else:
        # Deliberately bypass frozen construction: the API must validate even an
        # already-instantiated internal result, not trust its Python type alone.
        object.__setattr__(
            value.prepared.plan,
            "context",
            value.prepared.plan.context.model_copy(update={"context_sha256": "sha256:" + "0" * 64}),
        )
    with pytest.raises((ApiError, ValueError)) as caught:
        start(value)
    if isinstance(caught.value, ApiError):
        assert caught.value.status == (403 if fault in {"caller", "permission"} else 409)
    value.client.create_item_production_evidence.assert_not_called()
    assert row_counts(value) == (0, 0, 0)


def test_public_request_cannot_supply_the_private_preparation_or_query_selector(start_case):
    document = start_case.request.model_dump(mode="json")
    for key in ("prepared_similarity", SIMILARITY_QUERY_CONTEXT_KEY):
        with pytest.raises(ValidationError):
            WorkflowStartRequest.model_validate(document | {key: {"role": "ADMIN"}})
