"""Ordinary caller/optional absence; actual temporary Item storage, synthetic IAM/native/source.

No operating DB, real model or current-user acceptance is claimed by these cases.
"""

import os
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.errors import ApiError
from eom_api.services.authoring_reference_client import (
    AuthoringReferenceClientError,
    CatalogAuthoringReferenceClient,
)
from eom_api.services.idempotency_service import IdempotencyClaim
from eom_api.services.item_similarity_preparation import ItemSimilarityStartPreparationService
from eom_api.services.item_similarity_publication_client import (
    CatalogItemSimilarityPublicationClient,
)
from eom_api.services.item_similarity_start import (
    SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
    check_similarity_not_offered,
)
from eom_api.services.reference_item_preparation import HttpReferenceItemStartPreparation
from eom_api.services.reference_item_start_ports import (
    ReferenceItemSimilarityNotOffered,
    ReferenceItemStartPending,
)
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_catalog_contracts import EducationalRetrievalRequirementV2, PastExamVariationRequest
from eom_catalog_contracts.authoring_reference import AuthoringReferenceSelection
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareReply
from eom_catalog_service import item_similarity_publication_service as publication_module
from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_identifiers import content_sha256
from eom_identity_service import tokens as token_module
from eom_identity_service.tokens import SessionTokenService
from eom_operator_identity import PermissionKey, RoleKey
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_workflow_runner.item_similarity_preparation import validate_item_similarity_start_inputs
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.api.helpers import disconnected_services
from tests.api.test_item_similarity_start import start_case as start_case
from tests.api.test_reference_item_async_start import application_case as application_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.item_similarity_start_fixtures import start_source
from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_item_similarity_preparation import prepare
from tests.unit.test_reference_query_prepare_transport import api_context
from tests.unit.test_similarity_context_artifact import SOURCE


@pytest.fixture
def ordinary(tmp_path, monkeypatch):
    _owner, context = api_context(monkeypatch)
    source = start_source(tmp_path, monkeypatch, ordinary=True).source
    prepared = prepare(source)
    anchor = prepared.plan.context.request.anchor
    reference = AuthoringReferenceSelection(
        evidence_id="evidenceitem_" + "a" * 32,
        source_item_revision_id=anchor.source.item_revision_id,
        source_sha256=anchor.source.artifact_member.sha256,
        solution_pointer_sha256=anchor.solution_evidence.pointer_sha256,
    )
    refs, queries, items, audit = Mock(), Mock(), Mock(), Mock()
    refs.select.return_value = reference
    items.prepare.return_value = prepared

    def reply(_context, request, *, idempotency_key):
        assert _context is context and request.consumer_purpose == "ITEM_AUTHORING"
        assert request.source_item_revision_id == reference.source_item_revision_id
        assert idempotency_key == request.idempotency_key
        return native_reply(request, prepared)

    queries.prepare.side_effect = reply
    value = HttpReferenceItemStartPreparation(context, queries, items, references=refs, audit=audit)
    return SimpleNamespace(
        source=source,
        context=context,
        prepared=prepared,
        reference=reference,
        references=refs,
        queries=queries,
        items=items,
        audit=audit,
        value=value,
    )


def native_reply(request, prepared, *, status="READY", error_code=None):
    return ReferenceQueryPrepareReply(
        schema_version="system-rag-reference-query-prepare-reply/1.0",
        operation="PREPARE_REFERENCE_QUERY",
        operation_id=request.operation_id,
        request_sha256=request.request_sha256,
        status=status,
        workflow_id=prepared.query_selection.workflow_id
        if status in {"READY", "PENDING"}
        else None,
        selection=prepared.query_selection if status == "READY" else None,
        error_code=error_code,
    )


def run(value):
    return value.value.prepare(
        value.context.actor(),
        workflow_request=value.source.request,
        expected_resolution=value.source.resolution,
        evidence=value.source.evidence,
        preset=value.source.preset,
        idempotency_key="api:" + "d" * 64,
    )


def assert_not_offered(value, result, reason):
    assert type(result) is ReferenceItemSimilarityNotOffered and result.reason == reason
    assert result.workflow_request_sha256 == content_sha256(
        value.source.request.model_dump(mode="json")
    )
    assert result.evidence_result_sha256 == value.source.evidence.result_sha256
    args = value.audit.append.call_args.kwargs
    assert args["outcome"] == "NOT_OFFERED" and args["error_code"] == reason
    assert args["target_id"] == value.source.evidence.evidence_bundle_revision_id
    assert args["target_type"] == "evidence_bundle_revision"
    value.items.prepare.assert_not_called()


def test_actual_ordinary_purpose_original_evidence_and_ready_plan_are_passed_without_relabeling(
    ordinary,
):
    assert run(ordinary) == ordinary.prepared
    ordinary.references.select.assert_called_once_with(
        ordinary.context.actor().actor_id, ordinary.source.evidence
    )
    current, sent = ordinary.queries.prepare.call_args.args
    assert current is ordinary.context
    assert sent.schema_version == "system-rag-reference-query-prepare-request/1.1"
    assert sent.graph_snapshot == ordinary.source.evidence.graph_snapshot
    assert sent.policy_revision_id == ordinary.source.evidence.access_policy_revision_id
    assert sent.policy_sha256 == ordinary.source.evidence.access_policy_sha256
    assert ordinary.prepared.plan.context.request.consumer_purpose == "ITEM_AUTHORING"
    ordinary.audit.append.assert_not_called()


def test_legitimate_no_reference_records_exact_evidence_and_does_not_start_query(ordinary):
    ordinary.references.select.return_value = None
    result = run(ordinary)
    assert_not_offered(ordinary, result, "REFERENCE_NOT_OFFERED")
    ordinary.queries.prepare.assert_not_called()


def test_hidden_selector_authority_field_is_invalid_not_absence_or_execution(ordinary):
    ordinary.references.select.return_value = ordinary.reference.model_copy(
        update={"authority": "ADMIN"}
    )
    with pytest.raises(ApiError, match="CONTROL_SIMILARITY_PREPARATION_INVALID"):
        run(ordinary)
    ordinary.queries.prepare.assert_not_called()
    ordinary.items.prepare.assert_not_called()
    ordinary.audit.append.assert_not_called()


@pytest.mark.parametrize("source_class", ("TEXTBOOK", "APPROVED_ITEM"))
def test_nonpast_exam_request_keeps_normal_graph_rag_without_broadening_reference_scope(
    ordinary, source_class
):
    raw = ordinary.source.request.model_dump(mode="json")
    raw["educational_retrieval"]["source_classes"] = [source_class]
    ordinary.source.request = ordinary.source.request.model_validate(raw)
    preset = ordinary.source.preset.model_dump(mode="json")
    preset["retrieval_policy"]["allowed_source_classes"] = sorted(
        {*preset["retrieval_policy"]["allowed_source_classes"], source_class}
    )
    ordinary.source.preset = ordinary.source.preset.model_validate(seal(preset, "content_sha256"))
    ordinary.source.resolution = ordinary.source.resolution.model_copy(
        update={"execution_preset_content_sha256": ordinary.source.preset.content_sha256}
    )
    result = run(ordinary)
    assert_not_offered(ordinary, result, "REFERENCE_NOT_OFFERED")
    ordinary.references.select.assert_not_called()
    ordinary.queries.prepare.assert_not_called()
    with pytest.raises(ControlPlaneError):
        validate_item_similarity_start_inputs(
            workflow_request=ordinary.source.request,
            expected_resolution=ordinary.source.resolution,
            evidence=ordinary.source.evidence,
            preset=ordinary.source.preset,
        )


def test_initial_missing_index_is_optional_but_not_a_fake_query_completion(ordinary):
    ordinary.queries.prepare.side_effect = lambda _c, request, **kw: native_reply(
        request, ordinary.prepared, status="UNAVAILABLE", error_code="INDEX_NOT_PREPARED"
    )
    assert_not_offered(ordinary, run(ordinary), "INDEX_NOT_PREPARED")
    ordinary.queries.prepare.assert_called_once()


def test_pending_never_becomes_absence_or_an_item(ordinary):
    ordinary.queries.prepare.side_effect = lambda _c, request, **kw: native_reply(
        request, ordinary.prepared, status="PENDING"
    )
    assert run(ordinary) == ReferenceItemStartPending(ordinary.prepared.query_selection.workflow_id)
    ordinary.items.prepare.assert_not_called()
    ordinary.audit.append.assert_not_called()


@pytest.mark.parametrize(
    "code",
    (
        "SOURCE_ACCESS_DENIED",
        "SOURCE_REVOKED",
        "AUTHORITY_UNAVAILABLE",
        "SOURCE_HASH_MISMATCH",
        "AUTHORING_REFERENCE_UNAVAILABLE",
    ),
)
def test_selector_failure_or_denial_cannot_be_treated_as_optional_absence(ordinary, code):
    ordinary.references.select.side_effect = AuthoringReferenceClientError(code)
    with pytest.raises(ApiError) as caught:
        run(ordinary)
    assert caught.value.error_code == code
    ordinary.queries.prepare.assert_not_called()
    ordinary.items.prepare.assert_not_called()
    ordinary.audit.append.assert_not_called()


@pytest.mark.parametrize(
    "status,code",
    (
        ("UNAVAILABLE", "ANCHOR_REPORT_MISSING"),
        ("FAILED", "SOURCE_ACCESS_DENIED"),
        ("FAILED", "SOURCE_REVOKED"),
        ("FAILED", "REFERENCE_QUERY_EXECUTION_FAILED"),
    ),
)
def test_query_failures_and_contradictory_missing_report_do_not_bypass_selected_report(
    ordinary, status, code
):
    ordinary.queries.prepare.side_effect = lambda _c, request, **kw: native_reply(
        request, ordinary.prepared, status=status, error_code=code
    )
    with pytest.raises(ApiError) as caught:
        run(ordinary)
    assert caught.value.error_code == code
    ordinary.items.prepare.assert_not_called()
    ordinary.audit.append.assert_not_called()


@pytest.mark.parametrize(
    "field", ("source_item_revision_id", "source_sha256", "solution_pointer_sha256")
)
def test_late_selected_source_or_report_change_never_accepts_prepared_item(ordinary, field):
    ordinary.references.select.return_value = ordinary.reference.model_copy(
        update={
            field: "itemrev_" + "f" * 32
            if field == "source_item_revision_id"
            else "sha256:" + "f" * 64
        }
    )
    ordinary.queries.prepare.side_effect = lambda _c, request, **kw: native_reply(
        request, ordinary.prepared
    )
    with pytest.raises(ApiError, match="CONTROL_SIMILARITY_PREPARATION_INVALID"):
        run(ordinary)
    ordinary.items.prepare.assert_called_once()
    ordinary.audit.append.assert_not_called()


@pytest.mark.parametrize("reason", ("REFERENCE_NOT_OFFERED", "INDEX_NOT_PREPARED"))
@pytest.mark.parametrize("fault", ("none", "request", "evidence", "variation", "reason"))
def test_absence_handoff_cannot_escape_original_ordinary_request_evidence_or_reason(
    ordinary, reason, fault
):
    result = ReferenceItemSimilarityNotOffered(
        reason,
        content_sha256(ordinary.source.request.model_dump(mode="json")),
        ordinary.source.evidence.result_sha256,
    )
    if fault in {"request", "evidence"}:
        result = replace(
            result,
            **{
                "workflow_request_sha256"
                if fault == "request"
                else "evidence_result_sha256": "sha256:" + "f" * 64
            },
        )
    elif fault == "reason":
        object.__setattr__(result, "reason", "SOURCE_REVOKED")
    request = ordinary.source.request
    if fault == "variation":
        request = request.model_copy(
            update={
                "educational_retrieval": EducationalRetrievalRequirementV2(
                    corpus_key=request.educational_retrieval.corpus_key,
                    required_item_elements=("choice",),
                    past_exam_variation=PastExamVariationRequest(
                        source_item_revision_id=ordinary.reference.source_item_revision_id,
                        variation_axes=("CONTEXT",),
                    ),
                )
            }
        )
        result = replace(
            result, workflow_request_sha256=content_sha256(request.model_dump(mode="json"))
        )
    arguments = dict(
        request=request,
        expected_resolution=ordinary.source.resolution,
        evidence=ordinary.source.evidence,
        preset=ordinary.source.preset,
    )
    if fault == "none":
        check_similarity_not_offered(result, **arguments)
    else:
        with pytest.raises(ApiError, match="CONTROL_SIMILARITY_PREPARATION_INVALID"):
            check_similarity_not_offered(result, **arguments)


@pytest.mark.parametrize("start_case", (True,), indirect=True)
def test_ordinary_no_offer_uses_original_evidence_only_plan_and_replay_never_reprepares(start_case):
    value = start_case
    preparation = Mock()
    preparation.prepare.return_value = ReferenceItemSimilarityNotOffered(
        "REFERENCE_NOT_OFFERED",
        content_sha256(value.source.request.model_dump(mode="json")),
        value.source.evidence.result_sha256,
    )
    kwargs = dict(idempotency_key="synthetic-ordinary-no-offer", preparation=preparation)
    result = value.adapter.start_reference_workflow(value.request, value.actor, **kwargs)
    assert isinstance(result, tuple) and len(value.records) == 1
    assert value.records[0][0] == "resolved-execution-plan/19.0"
    with value.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, result[1])
        assert SIMILARITY_PREPARATION_ACCEPTANCE_KEY not in workflow.runtime_context
        assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == 1
    preparation.prepare.side_effect = AssertionError(
        "accepted replay cannot select another reference"
    )
    value.client.create_item_production_evidence.side_effect = AssertionError(
        "no Evidence reselection"
    )
    assert value.adapter.start_reference_workflow(value.request, value.actor, **kwargs) == result


@pytest.mark.parametrize("application_case", (True,), indirect=True)
def test_ordinary_public_application_uses_same_current_capture_claim_and_pending_protocol(
    application_case,
):
    value = application_case
    value.service.references = Mock()
    value.commands.start_reference_workflow.return_value = ReferenceItemStartPending(
        "workflow_" + "b" * 32
    )
    result = value.service.start(
        value.context, value.data.request, idempotency_key="original-ordinary-key"
    )
    assert result.status == "PENDING" and result.command is None
    value.idempotency.claim.assert_called_once()
    value.idempotency.defer.assert_called_once()
    value.idempotency.complete.assert_not_called()
    value.idempotency.fail_final.assert_not_called()
    args = value.commands.start_reference_workflow.call_args
    assert args.args == (value.data.request, value.context.actor())
    prep = args.kwargs["preparation"]
    assert prep.context is value.context and prep.references is value.service.references
    assert prep.audit is value.audit


@pytest.mark.parametrize("start_case", (True,), indirect=True)
def test_http_ordinary_pending_to_ready_uses_real_catalog_sockets_and_first_plan24(
    start_case, tmp_path, monkeypatch
):
    """Actual HTTP/Unix/publisher/Item transaction; IAM/source/native completion synthetic."""
    from eom_api.services.reference_item_start import ReferenceItemStartApplicationService

    value = start_case
    auth_source, context = api_context(monkeypatch)
    # The transport fixture grants only START. This wider synthetic EDITOR case
    # must explicitly grant its own retrieval/read capabilities before capture.
    permissions = frozenset(
        {
            PermissionKey.WORKFLOW_START,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
            PermissionKey.HWPX_BUILD_CREATE,
            PermissionKey.ITEM_READ,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
            PermissionKey.CONTENT_INTAKE_READ,
        }
    )
    auth_source.permissions = permissions
    projection = context.authentication.operator.model_copy(
        update={
            "roles": (RoleKey.EDITOR,),
            "effective_permissions": tuple(sorted(permissions, key=lambda key: key.value)),
        }
    )
    monkeypatch.setattr(token_module, "operator_projection", lambda *_args: projection)
    access = SessionTokenService(auth_source.codec).authenticate_and_capture_access(
        auth_source, auth_source.raw_token
    )
    context.authentication, context.authenticated_access = access.authentication, access
    query = value.source.value.query
    query.owner.catalog.engine = value.engine
    monkeypatch.setattr(
        publication_module,
        "select_completed_reference_query_request",
        Mock(return_value=query.request),
    )
    monkeypatch.setattr(
        publication_module, "CatalogCompletedReferenceQueryRead", Mock(return_value=query)
    )
    anchor = value.prepared.plan.context.request.anchor
    reference = AuthoringReferenceSelection(
        evidence_id="evidenceitem_" + "a" * 32,
        source_item_revision_id=anchor.source.item_revision_id,
        source_sha256=anchor.source.artifact_member.sha256,
        solution_pointer_sha256=anchor.solution_evidence.pointer_sha256,
    )
    server = _server(tmp_path)
    server.item_similarity_publications = CatalogItemSimilarityPublicationService(
        query.owner, value.source.publisher, source_commit=SOURCE
    )
    server.similarity_context_reads = SimpleNamespace(
        read=Mock(return_value=value.prepared.plan.context)
    )
    server.authoring_reference_selection = SimpleNamespace(select=Mock(return_value=reference))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    services = disconnected_services()
    endpoint = ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
    services.auth = Mock()
    services.auth.authenticate_and_capture_access.return_value = context.authenticated_access
    services.audit = Mock()
    services.idempotency.claim = Mock(
        return_value=IdempotencyClaim("synthetic", lease_owner="current")
    )
    for name in ("defer", "complete", "fail_final"):
        setattr(services.idempotency, name, Mock())
    queries = Mock()
    pending_state = [True]

    def prepare_query(actual, request, *, idempotency_key):
        assert actual.authenticated_access is context.authenticated_access
        assert request.consumer_purpose == "ITEM_AUTHORING"
        return native_reply(
            request, value.prepared, status="PENDING" if pending_state[0] else "READY"
        )

    queries.prepare.side_effect = prepare_query
    services.reference_item_starts = ReferenceItemStartApplicationService(
        enabled=True,
        commands=value.adapter,
        queries=queries,
        items=ItemSimilarityStartPreparationService(
            CatalogItemSimilarityPublicationClient(endpoint),
            CatalogSimilarityContextClient(endpoint),
        ),
        idempotency=services.idempotency,
        audit=services.audit,
        references=CatalogAuthoringReferenceClient(endpoint),
    )
    try:
        with TestClient(create_app(services), base_url="http://localhost") as http:

            def post():
                return http.post(
                    "/api/v1/workflows/reference-starts",
                    json=value.request.model_dump(mode="json"),
                    headers={
                        "Authorization": "Bearer synthetic-only",
                        "Idempotency-Key": "original-ordinary-http-key",
                    },
                )

            first = post()
            assert first.status_code == 202, first.json()
            assert first.json()["data"]["status"] == "PENDING"
            assert (
                first.headers["Retry-After"] == "20"
                and first.headers["Cache-Control"] == "no-store"
            )
            assert value.records == []
            with value.sessions() as session:
                assert session.scalar(select(func.count()).select_from(WorkflowInstanceRecord)) == 0
            pending_state[0] = False
            second = post()
            assert second.status_code == 202 and second.json()["data"]["status"] == "ACCEPTED"
            assert len(value.records) == 1 and value.records[0][0] == "resolved-execution-plan/24.0"
            assert server.authoring_reference_selection.select.call_count == 2
            original = server.authoring_reference_selection.select.call_args.args[0]
            assert original.evidence == value.source.evidence
            assert original.actor_id == context.actor().actor_id
            third = post()
            assert third.status_code == 202 and third.json()["data"] == second.json()["data"]
            assert server.authoring_reference_selection.select.call_count == 2
            assert queries.prepare.call_count == 2
            with value.sessions() as session:
                assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == 1
    finally:
        services.engine.dispose()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
