"""Actual API clients/Unix server/Artifact publisher; QUERY and source observations synthetic."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.services.item_similarity_preparation import ItemSimilarityStartPreparationService
from eom_api.services.item_similarity_publication_client import (
    CatalogItemSimilarityPublicationClient,
)
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint

from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_item_similarity_preparation import counts
from tests.unit.test_item_similarity_publication_service import service_case


def actor_for(case):
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=case.caller.operator_id,
        session_id="apisession_" + "8" * 32,
        request_id="request_" + "9" * 32,
        authentication_time=datetime.now(UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )


def prepare(application, case, selection, **changes):
    values = dict(
        workflow_request=case.request,
        expected_resolution=case.resolution,
        evidence=case.evidence,
        preset=case.preset,
    )
    values.update(changes)
    return application.prepare(actor_for(case), selection, **values)


def test_actual_socket_producer_builds_the_checked_private_item_handoff_once(tmp_path, monkeypatch):
    case, publication, request, _selected = service_case(tmp_path, monkeypatch)
    server = _server(tmp_path)
    reads = SimpleNamespace(read=Mock(return_value=case.value.case["context"]))
    server.similarity_context_reads = reads
    server.item_similarity_publications = publication
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        application = ItemSimilarityStartPreparationService(
            CatalogItemSimilarityPublicationClient(endpoint),
            CatalogSimilarityContextClient(endpoint),
        )
        first = prepare(application, case, request.selection)
        assert prepare(application, case, request.selection) == first
        assert first.operator_id == case.caller.operator_id
        assert first.query_selection == request.selection
        assert first.resolution == case.resolution
        assert first.evidence_result_sha256 == case.evidence.result_sha256
        assert first.preset_content_sha256 == case.preset.content_sha256
        assert first.plan.context == case.value.case["context"]
        assert counts(case) == (1, 1)
        assert reads.read.call_count == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_invalid_item_scope_never_becomes_an_accepted_handoff(tmp_path, monkeypatch):
    case, service, request, _selected = service_case(tmp_path, monkeypatch)
    publications = Mock(publish=Mock(side_effect=lambda *_args: service.publish(request)))
    contexts = Mock(read=Mock(return_value=case.value.case["context"]))
    application = ItemSimilarityStartPreparationService(publications, contexts)
    wrong = case.resolution.model_copy(update={"content_pack_version": "1.20.16"})
    with pytest.raises(ApiError) as caught:
        prepare(application, case, request.selection, expected_resolution=wrong)
    assert caught.value.error_code == "CONTROL_SIMILARITY_PREPARATION_INVALID"
    publications.publish.assert_called_once()
    # Authorized auxiliary publication is distinct from accepting a bad item.
    assert counts(case) == (1, 1)


def test_missing_action_permission_is_denied_before_any_transport(tmp_path, monkeypatch):
    case, _service, request, _selected = service_case(tmp_path, monkeypatch)
    publications, contexts = Mock(), Mock()
    application = ItemSimilarityStartPreparationService(publications, contexts)
    actor = actor_for(case).model_copy(update={"permissions": frozenset()})
    with pytest.raises(ApiError) as caught:
        application.prepare(
            actor,
            request.selection,
            workflow_request=case.request,
            expected_resolution=case.resolution,
            evidence=case.evidence,
            preset=case.preset,
        )
    assert caught.value.status == 403
    assert not publications.mock_calls and not contexts.mock_calls


def test_late_context_failure_preserves_publication_and_exact_replay(tmp_path, monkeypatch):
    case, publication, request, _selected = service_case(tmp_path, monkeypatch)
    server = _server(tmp_path)
    context = case.value.case["context"]
    reads = SimpleNamespace(read=Mock(side_effect=SimilarityContextReadError("SOURCE_REVOKED")))
    server.similarity_context_reads = reads
    server.item_similarity_publications = publication
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        application = ItemSimilarityStartPreparationService(
            CatalogItemSimilarityPublicationClient(endpoint),
            CatalogSimilarityContextClient(endpoint),
        )
        with pytest.raises(ApiError) as caught:
            prepare(application, case, request.selection)
        assert caught.value.error_code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
        assert counts(case) == (1, 1) and reads.read.call_count == 1
        (original,) = tuple(case.publisher.settings.nas_artifact_root.rglob("context.json"))
        before = original.stat()
        reads.read.side_effect = None
        reads.read.return_value = context
        assert prepare(application, case, request.selection).plan.context == context
        assert counts(case) == (1, 1) and original.stat() == before
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
