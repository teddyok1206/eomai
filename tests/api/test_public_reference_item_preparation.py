"""Exact public QUERY preparation in existing HTTP use case; owner/actor are synthetic."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.services.reference_item_preparation import HttpReferenceItemStartPreparation
from eom_api.services.reference_item_start_ports import (
    ReferenceItemSimilarityNotOffered,
    ReferenceItemStartPending,
)
from eom_catalog_contracts.authoring_reference import AuthoringReferenceSelection
from eom_catalog_contracts.knowledge import EducationalRetrievalRequirementV2
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV4,
    routed_reference_query_error_reply,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_request,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow_runner.item_similarity_preparation import validate_public_item_similarity_scope

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_item_similarity_api_preparation import public_source as public_source


def setup(value, *, pending=False):
    anchor = value.prepared.plan.context.request.anchor
    reference = AuthoringReferenceSelection(
        evidence_id="evidenceitem_" + "a" * 32,
        source_item_revision_id=anchor.source.item_revision_id,
        source_sha256=anchor.source.artifact_member.sha256,
        solution_pointer_sha256=anchor.evidence.solution.pointer_sha256,
    )
    context = SimpleNamespace(
        actor=lambda: value.data.actor, owner_capture=Mock(return_value=object())
    )
    references = SimpleNamespace(select=Mock(return_value=reference))

    def response(_context, query, **options):
        assert options["idempotency_key"] == query.idempotency_key
        assert query.schema_version == "system-rag-reference-query-prepare-request/4.0"
        assert query.source_item_revision_ids == (reference.source_item_revision_id,)
        assert query.top_k == 5
        assert query.graph_snapshot == value.source.evidence.graph_snapshot
        assert query.policy_sha256 == value.source.evidence.access_policy_sha256
        assert query.consumer_purpose == (
            "PAST_EXAM_VARIATION"
            if isinstance(
                value.source.request.educational_retrieval, EducationalRetrievalRequirementV2
            )
            else "ITEM_AUTHORING"
        )
        return ReferenceQueryPrepareReplyV4(
            schema_version="system-rag-reference-query-prepare-reply/4.0",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=query.operation_id,
            request_sha256=query.request_sha256,
            request_schema_version=query.schema_version,
            status="PENDING" if pending else "READY",
            preparation=dict(
                artifact_id="artifact_" + "a" * 32,
                artifact_revision_id="rev_" + "b" * 32,
                member_path="preparation.json",
                schema_ref="eom://schemas/workflow/reference-query-routed-preparation/2.0",
                media_type="application/json",
                sha256="sha256:" + "c" * 64,
            ),
            parent_request_sha256="sha256:" + "d" * 64,
            device="CUDA",
            children=[
                dict(
                    ordinal=0,
                    source_item_revision_id=reference.source_item_revision_id,
                    workflow_id=None if pending else value.selection.workflow_id,
                    state="PENDING" if pending else "COMPLETED",
                    selection=None if pending else value.selection,
                )
            ],
            workflow_id=None if pending else value.selection.workflow_id,
            selection=None if pending else value.selection,
            error_code=None,
        )

    queries = SimpleNamespace(prepare=Mock(side_effect=response))
    items = SimpleNamespace(prepare=Mock(return_value=value.prepared))
    audit = SimpleNamespace(append=Mock())
    application = HttpReferenceItemStartPreparation(
        context, queries, items, references=references, audit=audit
    )
    return SimpleNamespace(
        application=application,
        queries=queries,
        items=items,
        context=context,
        reference=reference,
        references=references,
        audit=audit,
    )


def prepare(data, value):
    return data.application.prepare(
        value.data.actor,
        workflow_request=value.source.request,
        expected_resolution=value.source.resolution,
        evidence=value.source.evidence,
        preset=value.source.preset,
        idempotency_key="original-public-item-request",
    )


def test_fresh_public_request_uses_existing_prepare4_then_exact_item_handoff(public_source):
    data = setup(public_source)
    assert prepare(data, public_source) == public_source.prepared
    assert data.items.prepare.call_args.args == (public_source.data.actor, public_source.selection)


def test_same_pending_preparation_keeps_parent_pointer_key_and_submits_no_item(public_source):
    data = setup(public_source, pending=True)
    first = prepare(data, public_source)
    assert type(first) is ReferenceItemStartPending and first.reference_query_workflow_id is None
    assert first.preparation.schema_ref.endswith("/2.0")
    assert prepare(data, public_source) == first
    data.items.prepare.assert_not_called()
    one, two = (call.args[1] for call in data.queries.prepare.call_args_list)
    assert one == two and content_sha256(one) == content_sha256(two)


def test_source_denial_is_not_silently_changed_into_optional_absence(public_source):
    data = setup(public_source)
    data.queries.prepare.side_effect = lambda _context, request, **options: (
        routed_reference_query_error_reply(request, error_code="SOURCE_REVOKED")
    )
    with pytest.raises(ApiError):
        prepare(data, public_source)
    data.items.prepare.assert_not_called()
    data.audit.append.assert_not_called()


def test_only_explicit_ordinary_missing_index_can_use_existing_not_offered_meaning(public_source):
    data = setup(public_source)
    data.queries.prepare.side_effect = lambda _context, request, **options: (
        routed_reference_query_error_reply(
            request, status="UNAVAILABLE", error_code="INDEX_NOT_PREPARED"
        )
    )
    if isinstance(
        public_source.source.request.educational_retrieval, EducationalRetrievalRequirementV2
    ):
        with pytest.raises(ApiError):
            prepare(data, public_source)
    else:
        assert type(prepare(data, public_source)) is ReferenceItemSimilarityNotOffered
    data.items.prepare.assert_not_called()


def test_public_start_does_not_prepare_more_references_than_role_material_limit(public_source):
    body = public_source.case["context"].request.model_dump(mode="json") | {"top_k": 9}
    request = parse_supported_public_solution_similarity_request(seal(body, "request_sha256"))
    with pytest.raises(ControlPlaneError) as caught:
        validate_public_item_similarity_scope(
            workflow_request=public_source.source.request,
            expected_resolution=public_source.source.resolution,
            evidence=public_source.source.evidence,
            preset=public_source.source.preset,
            context_request=request,
        )
    assert caught.value.code == "CONTROL_SIMILARITY_PREPARATION_INVALID"
