"""Public private handoff, exact replay metadata and real UDS framing; source/QUERY synthetic."""

import os
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.services.item_similarity_preparation import ItemSimilarityStartPreparationService
from eom_api.services.item_similarity_publication_client import (
    CatalogItemSimilarityPublicationClient,
)
from eom_api.services.item_similarity_start import (
    PUBLIC_SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
    SIMILARITY_PREPARATION_ACCEPTANCE_KEY,
    check_similarity_start,
    require_similarity_start_replay,
    similarity_start_context,
)
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_catalog_contracts.item_similarity_publication import ItemSimilarityPublicationV2
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_workflow.public_similarity_control import bind_public_similarity_execution_plan
from eom_workflow_runner.item_similarity_preparation import PreparedPublicItemSimilarity

from tests.unit.public_item_start_fixtures import public_start_source
from tests.unit.test_catalog_application_boundary import _server


@pytest.fixture(params=(False, True))
def public_source(tmp_path, monkeypatch, request):
    return public_start_source(tmp_path, monkeypatch, ordinary=request.param, registered=True)


def test_actual_public_api_clients_reuse_exact_publication_and_context_without_legacy_transport(
    public_source, tmp_path
):
    value = public_source
    publication = ItemSimilarityPublicationV2(
        owner_job_id=value.publication.owner_job_id,
        delivery=value.publication.delivery,
        manifest_sha256=value.publication.manifest_sha256,
    )
    owner = SimpleNamespace(publish_public=Mock(return_value=publication), publish=Mock())
    reads = SimpleNamespace(read=Mock(return_value=value.case["context"]))
    server = _server(tmp_path)
    server.item_similarity_publications, server.similarity_context_reads = owner, reads
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        api = ItemSimilarityStartPreparationService(
            CatalogItemSimilarityPublicationClient(endpoint),
            CatalogSimilarityContextClient(endpoint),
        )
        for _ in range(2):
            result = api.prepare(
                value.data.actor,
                value.selection,
                workflow_request=value.source.request,
                expected_resolution=value.source.resolution,
                evidence=value.source.evidence,
                preset=value.source.preset,
            )
            assert type(result) is PreparedPublicItemSimilarity and result == value.prepared
        assert owner.publish_public.call_count == reads.read.call_count == 2
        owner.publish.assert_not_called()
        assert all(
            call.args[0].schema_version == "system-rag-similarity-read-request/4.0"
            for call in reads.read.call_args_list
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_new_acceptance_keeps_v1_separate_and_replays_exact_original_metadata(public_source):
    value = public_source
    checked = check_similarity_start(value.prepared, value.source.request, value.data.actor)
    plan = bind_public_similarity_execution_plan(
        value.case["base"], value.publication.delivery, value.case["context"]
    )
    runtime = similarity_start_context({}, checked, plan)
    assert runtime[PUBLIC_SIMILARITY_PREPARATION_ACCEPTANCE_KEY] == checked.fingerprint
    assert SIMILARITY_PREPARATION_ACCEPTANCE_KEY not in runtime
    require_similarity_start_replay(runtime, checked)
    with pytest.raises(ApiError):
        require_similarity_start_replay(
            runtime | {SIMILARITY_PREPARATION_ACCEPTANCE_KEY: checked.fingerprint}, checked
        )


@pytest.mark.parametrize("fault", ("actor", "version", "delivery", "request"))
def test_public_private_preparation_cannot_be_rebound_or_accepted_as_a_legacy_family(
    public_source, fault
):
    value = public_source
    prepared, actor = value.prepared, value.data.actor
    if fault == "actor":
        actor = actor.model_copy(update={"operator_id": "operator_" + "0" * 32})
    elif fault == "version":
        prepared = replace(
            prepared,
            resolution=prepared.resolution.model_copy(update={"content_pack_version": "1.20.17"}),
        )
    elif fault == "delivery":
        prepared = replace(
            prepared, publication=replace(prepared.publication, manifest_sha256="invalid")
        )
    else:
        prepared = replace(prepared, workflow_request_sha256="sha256:" + "0" * 64)
    with pytest.raises(ApiError):
        check_similarity_start(prepared, value.source.request, actor)
