"""Guarded PostgreSQL/public index/private canonical read; Chat/IAM/numerics synthetic."""

import pytest
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    PrivateChatContextPreparation,
)
from eom_catalog_service.private_chat_similarity_ports import VerifiedPrivateChatQueryRead
from eom_catalog_service.private_chat_similarity_service import (
    PrivateChatSimilarityApplicationService,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.models import JobRecord
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_query_source_owner import make_owned_private_source
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_similarity_read import make_private_similarity_read_case

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def completed_read(registered, guarded_engine, tmp_path, monkeypatch):
    source = make_owned_private_source(
        registered,
        guarded_engine,
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )
    return make_private_similarity_read_case(source, tmp_path, monkeypatch)


def test_postgres_private_consumer_reads_original_history_terminal_and_committed_vector(
    completed_read,
):
    value = completed_read
    with value.native.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    result = value.read.resolve_private_chat_query(value.caller, value.request, prepared)
    assert type(result) is VerifiedPrivateChatQueryRead
    assert result.request.row.text == TEXT and TEXT not in repr(result)
    assert (
        len(value.read.read_private_chat_similarity_index(value.caller, value.request, prepared))
        == 1
    )
    value.read.reauthorize_private_chat_similarity(value.caller, value.request, prepared)
    with value.native.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
    assert value.native.encodes == 1


def test_postgres_concrete_private_provider_composes_official_candidate_and_truthful_limits(
    completed_read,
):
    value = completed_read
    context = PrivateChatSimilarityApplicationService(value.read).compose(
        value.caller, value.request
    )
    assert context.status in {"READY", "PARTIAL"}, context.error_code
    assert len(context.candidates) == 1
    assert context.query_execution is not None
    assert "PRIVATE_QUERY_IS_NOT_SOURCE_EVIDENCE" in context.limitations
    assert "SCORES_ARE_NOT_SOLUTION_EQUALITY_OR_APPROVAL" in context.limitations
    assert TEXT not in str(context.model_dump(mode="json"))
    assert value.native.encodes == 1


@pytest.mark.parametrize("fault", ["claim", "public_during_private_auth"])
def test_postgres_private_consumer_refuses_current_chat_or_mid_read_public_revocation(
    completed_read, fault
):
    value = completed_read
    prepared = value.read.prepare_private_chat_similarity(value.caller, value.request)
    value.source.fault.value = fault
    value.source.fault.final_authorization_reached = False
    with pytest.raises(SimilarityContextReadError):
        value.read.resolve_private_chat_query(value.caller, value.request, prepared)
    assert value.source.fault.final_authorization_reached
    assert value.native.encodes == 1


def test_postgres_initial_private_context_pins_the_registered_index_without_item_anchor(
    completed_read,
):
    value = completed_read
    config = value.source.owner.configuration.registry
    current = value.request
    selection = PrivateChatContextPreparation(
        current.request_id,
        current.query_basis,
        EmbeddingRegistryLookup(
            config.corpus_id,
            config.namespace,
            current.graph_snapshot,
            current.policy_revision_id,
            current.policy_sha256,
            current.maximum_sources,
        ),
        value.source.policy.spaces,
        current.top_k,
    )
    with value.native.publisher.sessions.begin() as session:
        captured = value.source.owner.catalog.prepare_private_chat_context_in_session(
            session, value.caller, selection
        )
        assert captured == current and "anchor" not in captured.model_dump(mode="json")
        assert not session.new and not session.dirty
    assert value.native.encodes == 1
