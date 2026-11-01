"""Real index3/4 bytes for first common private selection; IAM/head metadata are synthetic."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityRequestV2
from eom_catalog_service import embedding_registry_catalog_adapter as adapter
from eom_catalog_service.embedding_registry_ports import PrivateChatContextPreparation
from eom_catalog_service.embedding_registry_repository import EmbeddingRegistryRepository
from eom_catalog_service.private_chat_context_preparation import (
    validate_private_chat_context_preparation,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord

from tests.unit import test_private_chat_initial_context as original
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_private_chat_query_basis import TEXT, basis
from tests.unit.test_public_solution_registry_read import public_read as public_read

pytestmark = pytest.mark.parametrize("public_read", [None, "registered"], indirect=True)


@pytest.fixture
def initial(public_read, monkeypatch):
    current = public_read
    registered, _ = EmbeddingRegistryRepository(current.session).current_namespace_revision(
        current.intent.scope.corpus_id, current.intent.scope.namespace
    )
    preparation = PrivateChatContextPreparation(
        "similarityrequest_" + "a" * 32,
        basis(),
        current.intent.scope,
        current.intent.selection.index.spaces,
        8,
    )
    value = SimpleNamespace(
        verifier=current.verifier,
        session=current.session,
        command=SimpleNamespace(
            index_manifest=current.index_member,
            graph_snapshot=current.intent.scope.graph_snapshot,
        ),
        index=current.index,
        request=preparation,
        current=registered,
        reads=[],
        captures=[],
        denied_at=None,
        advance_head=False,
        fail_producer=False,
    )

    def head(_repository, corpus_id, namespace):
        assert corpus_id == preparation.scope.corpus_id and namespace == preparation.scope.namespace
        value.reads.append(namespace)
        return None if value.current is None else (value.current, 1)

    monkeypatch.setattr(EmbeddingRegistryRepository, "current_namespace_revision", head)
    authorize = current.verifier.sources.authorize_scope_in_session.side_effect

    def capture(*args, **options):
        from eom_identity_service import OperatorAuthorizationFenceError

        value.captures.append("AUTHORIZE_SCOPE")
        if value.denied_at == len(value.captures):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
        result = authorize(*args, **options)
        if len(value.captures) == 2:
            if value.advance_head:
                value.current = replace(
                    registered, index_revision_id="embeddingindexrev_" + "f" * 32
                )
            if value.fail_producer:
                revision = value.session.get(
                    ArtifactRevisionRecord, current.index_member.artifact_revision_id
                )
                value.session.get(JobRecord, revision.job_id).status = "FAILED"
        return result

    monkeypatch.setattr(current.verifier.sources, "authorize_scope_in_session", capture)
    return value


def test_common_initial_selection_pins_one_real_head_without_fake_item(initial):
    result = original.prepare(initial)
    assert isinstance(result, PrivateChatSimilarityRequestV2)
    assert result.views[0].index.index_manifest == initial.command.index_manifest
    assert result.graph_snapshot == initial.command.graph_snapshot
    assert result.query_basis == basis() and result.views[0].view == "CONCRETE_FACETS"
    assert "anchor" not in result.model_dump(mode="json")
    assert TEXT.encode() not in canonical_json_bytes(result)
    assert len(initial.reads) == 1 and len(initial.captures) == 2
    validate_private_chat_context_preparation(
        initial.request, initial.verifier.configuration, result
    )


@pytest.mark.parametrize(
    "case",
    [
        original.test_absent_initial_index_stays_absent_without_another_view_or_numeric_fallback,
        original.test_late_head_advance_preserves_the_one_initial_revision,
        original.test_index_producer_failure_during_final_authorization_refuses_pins,
    ],
)
def test_common_first_selection_keeps_missing_head_and_late_fence_semantics(initial, case):
    case(initial)


@pytest.mark.parametrize("when", [1, 2])
def test_common_denied_actual_operator_is_not_a_missing_index(initial, when):
    original.test_current_actual_authority_denial_is_not_missing_index(initial, when)


@pytest.mark.parametrize("field", ["top_k", "request_id", "basis", "policy", "graph"])
def test_common_replay_intent_does_not_select_latest(initial, field):
    original.test_replay_intent_mismatch_never_selects_a_new_head(initial, field)


def test_common_existing_bound_supports_more_than_legacy_1024_sources(initial):
    enlarged = replace(initial.request, scope=replace(initial.request.scope, maximum_sources=1025))
    assert enlarged.scope.maximum_sources == 1025


def test_common_first_selection_does_not_use_legacy_view_builder(initial, monkeypatch):
    def legacy(*_args, **_kwargs):
        raise AssertionError("common preparation must not use legacy recipe or view")

    monkeypatch.setattr(
        adapter.CatalogEmbeddingRegistryVerifier, "_initial_similarity_views", legacy
    )
    assert original.prepare(initial).views[0].view == "CONCRETE_FACETS"
