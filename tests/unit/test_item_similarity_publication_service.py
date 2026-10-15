"""Real temporary Artifact/IAM rows; QUERY selector/current source observations synthetic."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from eom_catalog_contracts.item_similarity_publication import ItemSimilarityPublicationRequest
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service import item_similarity_publication_service as module
from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identity_service.models import RolePermissionRecord
from eom_orchestrator.control_service import ControlPlaneError

from tests.unit.test_item_similarity_preparation import counts, preparation_case, prepare
from tests.unit.test_similarity_context_artifact import SOURCE


def service_case(tmp_path, monkeypatch):
    value = preparation_case(tmp_path, monkeypatch)
    query = value.value.query
    query.owner.catalog.engine = value.publisher.engine
    # The original QUERY/capture are synthetic in this shared fixture. Keep the
    # actual shared preparation/publisher/root/Artifact checks, not a fake publisher.
    select_original = Mock(return_value=query.request)
    monkeypatch.setattr(module, "select_completed_reference_query_request", select_original)
    monkeypatch.setattr(module, "CatalogCompletedReferenceQueryRead", Mock(return_value=query))
    service = CatalogItemSimilarityPublicationService(
        query.owner, value.publisher, source_commit=SOURCE
    )
    request = ItemSimilarityPublicationRequest(
        schema_version="system-rag-item-similarity-publication-request/1.0",
        operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
        actor_id=value.caller.operator_id,
        selection=CompletedSimilarityQuerySelection(
            workflow_id=query.workflow_id,
            workflow_request_sha256=query.request.request_sha256,
            context_request_sha256=query.request.context_request.request_sha256,
        ),
    )
    return value, service, request, select_original


def test_transport_service_and_checked_local_entry_reuse_one_canonical_publication(
    tmp_path, monkeypatch
):
    case, service, request, selected = service_case(tmp_path, monkeypatch)
    first = service.publish(request)
    original = prepare(case)
    repeated = service.publish(request)
    assert first == repeated
    assert first.owner_job_id == original.publication.owner_job_id
    assert first.delivery == original.plan.delivery
    assert first.manifest_sha256 == original.publication.manifest_sha256
    assert counts(case) == (1, 1)
    assert selected.call_count == 2
    assert all(
        call.args[2:] == (case.caller, request.selection) for call in selected.call_args_list
    )
    assert case.calls[0] is case.calls[1]
    assert case.calls[2] is case.calls[3]
    assert case.calls[4] is case.calls[5]
    assert case.calls[0] is not case.calls[2]


def test_selector_denial_precedes_any_publication_or_current_context(tmp_path, monkeypatch):
    case, service, request, selected = service_case(tmp_path, monkeypatch)
    selected.side_effect = SimilarityContextReadError("QUERY_RESULT_INVALID")
    with pytest.raises(SimilarityContextReadError):
        service.publish(request)
    assert case.calls == [] and counts(case) == (0, 0)


def test_replay_still_requires_current_start_permission(tmp_path, monkeypatch):
    case, service, request, _ = service_case(tmp_path, monkeypatch)
    first = service.publish(request)
    with case.publisher.sessions.begin() as session:
        session.delete(
            session.get(RolePermissionRecord, ("role_" + "a" * 32, "permission_" + "0" * 32))
        )
    with pytest.raises(ControlPlaneError) as caught:
        service.publish(request)
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
    assert counts(case) == (1, 1)
    with case.publisher.sessions.begin() as session:
        session.add(
            RolePermissionRecord(role_id="role_" + "a" * 32, permission_id="permission_" + "0" * 32)
        )
    assert service.publish(request) == first and counts(case) == (1, 1)


def test_wrong_operator_cannot_reuse_another_queries_publication(tmp_path, monkeypatch):
    case, service, request, _ = service_case(tmp_path, monkeypatch)
    changed = ItemSimilarityPublicationRequest.model_validate(
        request.model_dump(mode="json") | {"actor_id": "operator_" + "9" * 32}
    )
    with pytest.raises(ControlPlaneError):
        service.publish(changed)
    assert case.calls == [] and counts(case) == (0, 0)
