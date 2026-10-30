"""Canonical QUERY composition with explicitly synthetic authentication and owner leaves."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.request_context import RequestContext
from eom_api.services.item_db_similarity import ItemDbSimilarityApplicationService
from eom_api.services.pagination import PageResult
from eom_api.services.query_adapter import QueryAdapter
from eom_api_contracts.item_bank import ProductionItemCandidateView
from eom_api_contracts.item_db_similarity import ItemDbSimilarityInput
from eom_catalog_contracts.item_db_similarity_selection import ItemDbSimilaritySelectionReply
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV4,
    routed_reference_query_error_reply,
)
from eom_catalog_service.curriculum_graph_structure import integrated_science_curriculum_units
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey

from tests.api.test_hwpx_endpoints import _authentication
from tests.unit.test_item_db_similarity_selection import selected_case


def candidate_view(source):
    unit = integrated_science_curriculum_units()[0]
    past = (
        dict(
            graph_placement_node_id="knode_" + "1" * 32,
            assessment_occurrence_id="occurrence_" + "2" * 32,
            assessment_occurrence_revision_id="occurrev_" + "3" * 32,
            assessment_occurrence_revision_sha256="sha256:" + "4" * 64,
            occurrence_display_label="합성 검증 시험",
            administration_year=2025,
            administration_month=6,
            target_school_level="HIGH_SCHOOL",
            target_grade=1,
            subject_key="integrated-science",
            item_number=1,
            placement_sha256="sha256:" + "5" * 64,
        )
        if source.source_class == "PAST_EXAM"
        else None
    )
    member = source.artifact_member
    return ProductionItemCandidateView(
        graph_snapshot_revision_id="graphrev_" + "6" * 32,
        snapshot_sha256="sha256:" + "7" * 64,
        analysis_run_id="analysisrun_" + "8" * 32,
        graph_item_node_id="knode_" + "9" * 32,
        source_class=source.source_class,
        source_display_label="합성 검증 문항",
        past_exam_context=past,
        item_id=source.item_id,
        item_revision_id=source.item_revision_id,
        item_revision_state="APPROVED",
        item_lifecycle_state="ACTIVE",
        item_current_revision=True,
        item_type_key="multiple-choice",
        difficulty_band=None,
        item_manifest_sha256="sha256:" + "a" * 64,
        curriculum_units=[
            dict(
                curriculum_unit_id=unit.curriculum_unit_id,
                unit_key=unit.unit_key,
                unit_code=unit.unit_code,
                label=unit.label,
                unit_level=unit.unit_level,
                parent_unit_id=unit.parent_unit_id,
            )
        ],
        content_profile="LEGACY_ITEM_CONTENT_V1",
        content_component=dict(
            item_component_id="itemcomponent_" + "b" * 32,
            artifact_id=member.artifact_id,
            artifact_revision_id=member.artifact_revision_id,
            sha256=member.sha256,
            schema_ref=member.schema_ref,
            media_type=member.media_type,
            logical_name=member.logical_name,
        ),
        mock_exam_assembly_eligible=False,
        hwpx_exam_eligible=False,
        ineligibility_reasons=("CONTENT_TEAM_ITEM_V2_REQUIRED",),
    )


def query_reply(value, *, ready):
    selection = (
        dict(
            workflow_id="workflow_" + "c" * 32,
            workflow_request_sha256="sha256:" + "d" * 64,
            context_request_sha256=value.context.request.request_sha256,
        )
        if ready
        else None
    )
    return ReferenceQueryPrepareReplyV4.model_validate(
        dict(
            schema_version="system-rag-reference-query-prepare-reply/4.0",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=value.query.operation_id,
            request_sha256=value.query.request_sha256,
            request_schema_version=value.query.schema_version,
            status="READY" if ready else "PENDING",
            preparation=dict(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                member_path="preparation.json",
                sha256="sha256:" + "3" * 64,
                schema_ref="eom://schemas/workflow/reference-query-routed-preparation/2.0",
                media_type="application/json",
            ),
            parent_request_sha256="sha256:" + "4" * 64,
            device="CUDA" if ready else None,
            children=[
                dict(
                    ordinal=0,
                    source_item_revision_id=value.source.item_revision_id,
                    workflow_id=selection["workflow_id"] if ready else None,
                    state="COMPLETED" if ready else "PENDING",
                    selection=selection,
                )
            ],
            workflow_id=selection["workflow_id"] if ready else None,
            selection=selection,
            error_code=None,
        )
    )


@pytest.fixture
def flow():
    value = selected_case()
    authentication = replace(_authentication(admin=True), authenticated_at=datetime.now(UTC))
    context = RequestContext(
        "synthetic-db-search",
        datetime.now(UTC),
        "/item-db/similarity",
        "POST",
        None,
        None,
        None,
        authentication=authentication,
    )

    def resolve(request):
        return ItemDbSimilaritySelectionReply(
            schema_version="item-db-similarity-selection-reply/1.0",
            operation="RESOLVE_ITEM_DB_SIMILARITY",
            status="READY",
            actor_id=request.actor_id,
            request_sha256=content_sha256(request),
            result=value.result,
            error_code=None,
        )

    selector = NS(resolve=Mock(side_effect=resolve))
    queries = NS(prepare=Mock(return_value=query_reply(value, ready=True)))
    results = NS(read_public=Mock(return_value=value.context))
    metadata = NS(
        selected_production_item_candidates=Mock(
            return_value=tuple(
                candidate_view(candidate.source) for candidate in value.context.candidates
            )
        )
    )
    app = ItemDbSimilarityApplicationService(selector, queries, results, metadata)
    body = ItemDbSimilarityInput(selection=value.selection)
    return NS(**locals())


def test_actual_context_and_same_source_go_through_official_query_and_read_in_rank_order(flow):
    result = flow.app.search(flow.context, flow.body, idempotency_key=flow.value.key)
    assert result.status == "READY" and result.pinned_query == flow.value.query
    assert (
        result.candidates[0].entry.item_revision_id
        == flow.value.context.candidates[0].source.item_revision_id
    )
    assert (
        result.candidates[0].cosine_millionths
        == flow.value.context.candidates[0].observation.cosine_millionths
    )
    flow.queries.prepare.assert_called_once_with(
        flow.context, flow.value.query, idempotency_key=flow.value.key
    )
    assert flow.results.read_public.call_args.args[0] is flow.authentication
    assert (
        flow.selector.resolve.call_args.args[0].actor_id == flow.authentication.operator.operator_id
    )
    flow.metadata.selected_production_item_candidates.assert_called_once_with(
        tuple(candidate.source for candidate in flow.value.context.candidates)
    )


def test_pending_and_repeat_keep_original_key_and_query_without_new_authentication(flow):
    flow.queries.prepare.return_value = query_reply(flow.value, ready=False)
    one = flow.app.search(flow.context, flow.body, idempotency_key=flow.value.key)
    assert one.status == "PENDING" and one.phase == "WAITING_FOR_RESOURCE"
    again = ItemDbSimilarityInput(selection=flow.value.selection, pinned_query=one.pinned_query)
    two = flow.app.search(flow.context, again, idempotency_key=flow.value.key)
    assert one == two
    assert flow.selector.resolve.call_args.args[0].pinned_query == flow.value.query
    assert {call.kwargs["idempotency_key"] for call in flow.queries.prepare.call_args_list} == {
        flow.value.key
    }
    flow.results.read_public.assert_not_called()
    flow.metadata.selected_production_item_candidates.assert_not_called()


def test_different_key_cannot_reinterpret_the_original_pinned_search(flow):
    body = ItemDbSimilarityInput(selection=flow.value.selection, pinned_query=flow.value.query)
    with pytest.raises(ApiError) as raised:
        flow.app.search(flow.context, body, idempotency_key="other-query-key")
    assert raised.value.error_code == "ITEM_DB_SIMILARITY_REQUEST_CONFLICT"
    flow.selector.resolve.assert_not_called()


@pytest.mark.parametrize(
    "permission",
    (
        PermissionKey.CONTENT_INTAKE_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
    ),
)
def test_permissions_are_not_inferred_from_a_valid_pointer(flow, permission):
    flow.context.authentication = replace(
        flow.authentication, permissions=flow.authentication.permissions - {permission}
    )
    with pytest.raises(ApiError):
        flow.app.search(flow.context, flow.body, idempotency_key=flow.value.key)
    flow.selector.resolve.assert_not_called()
    flow.queries.prepare.assert_not_called()


def test_unavailable_search_does_not_encode_or_synthesize_zero_vectors(flow):
    flow.queries.prepare.return_value = routed_reference_query_error_reply(
        flow.value.query,
        status="UNAVAILABLE",
        error_code="INDEX_NOT_PREPARED",
    )
    result = flow.app.search(flow.context, flow.body, idempotency_key=flow.value.key)
    assert result.status == "UNAVAILABLE" and result.candidates == ()
    flow.results.read_public.assert_not_called()
    flow.metadata.selected_production_item_candidates.assert_not_called()


def test_navigation_is_one_indexed_batch_and_cannot_change_the_original_content_hash(flow):
    source = flow.value.context.candidates[0].source
    view = flow.metadata.selected_production_item_candidates.return_value[0]
    adapter = object.__new__(QueryAdapter)
    adapter.production_item_candidates = Mock(return_value=PageResult((view,), None, False))
    assert adapter.selected_production_item_candidates((source,)) == (view,)
    assert adapter.production_item_candidates.call_args.kwargs["selected_item_revisions"] == (
        source,
    )
    assert adapter.production_item_candidates.call_count == 1
    broken = view.model_copy(
        update={
            "content_component": view.content_component.model_copy(
                update={"sha256": "sha256:" + "f" * 64}
            )
        }
    )
    adapter.production_item_candidates.return_value = PageResult((broken,), None, False)
    with pytest.raises(ApiError) as raised:
        adapter.selected_production_item_candidates((source,))
    assert raised.value.error_code == "ITEM_DB_SIMILARITY_RESULT_STALE"
