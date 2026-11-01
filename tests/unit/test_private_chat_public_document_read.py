"""Real shared index4/file reader; source/IAM/ledger leaves remain synthetic."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityRequestV2
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
from eom_catalog_service.public_solution_similarity_read import CatalogPublicSolutionSimilarityRead
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.models import ArtifactRecord

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_private_chat_query_basis import basis
from tests.unit.test_public_solution_registry_read import public_read as public_read


def private_request(value):
    body = value.original_request.model_dump(mode="json")
    del body["anchor"]
    body.update(
        schema_version="system-rag-private-chat-similarity-request/2.0",
        consumer_purpose="GENERAL_CHAT_READ",
        query_basis=basis().model_dump(mode="json"),
        vector_mode="REQUIRED",
        views=[value.intent.selection.model_dump(mode="json")],
    )
    return PrivateChatSimilarityRequestV2.model_validate(seal(body, "request_sha256"))


def read(value, request=None, caller=None):
    return CatalogPublicSolutionSimilarityRead(value.verifier).read_private_documents_in_session(
        value.session,
        caller or EmbeddingRegistryCaller("operator_" + "1" * 32),
        request or private_request(value),
    )


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_private_actual_document_reader_uses_one_common_index_for_all_report_families(
    public_read, monkeypatch
):
    latest = Mock(side_effect=AssertionError("private continuation must not choose latest"))
    monkeypatch.setattr(
        "eom_catalog_service.embedding_registry_repository.EmbeddingRegistryRepository.current_namespace_revision",
        latest,
    )
    captures = Mock(wraps=public_read.verifier.resolve_lookup)
    monkeypatch.setattr(public_read.verifier, "resolve_lookup", captures)
    capture, document = read(public_read)
    assert len(capture.entries) == len(document.profiles) == 3
    assert {entry.evidence.kind for entry in capture.entries} == {
        "ACCEPTED_SOLUTION_ANALYSIS",
        "REGISTERED_CREATIVE_SOURCE_REPORT",
        "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
    }
    assert len(document.numerical_rows) == 1
    assert document.intent.selection == public_read.intent.selection
    assert captures.call_count == 2
    assert captures.call_args_list[0] == captures.call_args_list[1]
    assert public_read.verifier.sources.authorize_scope_in_session.call_count >= 2
    latest.assert_not_called()


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
@pytest.mark.parametrize("fault", ["binary", "revoked", "report", "foreign_index"])
def test_private_document_read_rejects_changed_files_lifecycle_and_source_proofs(
    public_read, monkeypatch, fault
):
    value = public_read
    request = private_request(value)
    if fault == "binary":
        (
            value.root / value.shard.artifact_id / value.shard.artifact_revision_id / "vectors.f32"
        ).write_bytes(b"invalid")
    elif fault == "revoked":
        value.session.get(ArtifactRecord, value.shard.artifact_id).approved = False
    elif fault == "foreign_index":
        selection = request.views[0]
        request = request.model_copy(
            update={
                "views": (
                    selection.model_copy(
                        update={
                            "index": selection.index.model_copy(
                                update={"index_revision_id": "embeddingindexrev_" + "f" * 32}
                            )
                        }
                    ),
                )
            }
        )
    else:
        original = value.verifier._captured_lookup

        def changed(*args):
            capture = original(*args)
            return replace(
                capture,
                entries=tuple(
                    entry.model_copy(update={"permission_override": True})
                    for entry in capture.entries
                ),
            )

        monkeypatch.setattr(value.verifier, "_captured_lookup", changed)
    with pytest.raises((EmbeddingRegistryError, SimilarityContextReadError)):
        read(value, request)


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_private_document_read_rechecks_sources_after_index_materialization(
    public_read, monkeypatch
):
    original = public_read.verifier.resolve_lookup
    calls = 0

    def capture(*args):
        nonlocal calls
        calls += 1
        current = original(*args)
        return current if calls == 1 else replace(current, truncated=not current.truncated)

    monkeypatch.setattr(public_read.verifier, "resolve_lookup", capture)
    with pytest.raises(SimilarityContextReadError, match="SOURCE_REVOKED"):
        read(public_read)
    assert calls == 2


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
@pytest.mark.parametrize("fault", ["no_identity", "indexing_service", "pending_write"])
def test_private_document_read_requires_independent_actual_operator_and_clean_root(
    public_read, fault
):
    if fault == "no_identity":
        public_read.verifier.identity_fence = None
    elif fault == "indexing_service":
        public_read.verifier._indexing_source_authority = object()
    else:
        public_read.session.new.append(object())
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        read(public_read)
    public_read.verifier.sources.authorize_scope_in_session.assert_not_called()


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_private_document_read_rejects_untrusted_question_extras_without_echo(public_read):
    request = private_request(public_read).model_copy(update={"question": "DO_NOT_DISCLOSE"})
    with pytest.raises(SimilarityContextReadError) as error:
        read(public_read, request)
    assert "DO_NOT_DISCLOSE" not in str(error.value)
    public_read.verifier.sources.authorize_scope_in_session.assert_not_called()


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_private_document_read_denies_revoked_operator_before_returning_data(public_read):
    public_read.verifier.identity_fence.fence_current_operator.side_effect = (
        OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
    )
    with pytest.raises(SimilarityContextReadError, match="SOURCE_ACCESS_DENIED"):
        read(public_read)


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_private_document_read_does_not_invent_missing_index(public_read):
    request = private_request(public_read)
    body = request.model_dump(mode="json")
    body["views"][0]["index"] = None
    request = PrivateChatSimilarityRequestV2.model_validate(seal(body, "request_sha256"))
    with pytest.raises(SimilarityContextReadError, match="INDEX_POINTER_INVALID"):
        read(public_read, request)
    public_read.verifier.sources.authorize_scope_in_session.assert_not_called()


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
@pytest.mark.parametrize("fault", ["new", "dirty", "deleted"])
def test_private_document_read_refuses_source_adapter_side_effects(public_read, monkeypatch, fault):
    original = public_read.verifier.resolve_lookup
    calls = 0

    def capture(*args):
        nonlocal calls
        calls += 1
        current = original(*args)
        if calls == 2:
            getattr(public_read.session, fault).append(object())
        return current

    monkeypatch.setattr(public_read.verifier, "resolve_lookup", capture)
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        read(public_read)


@pytest.mark.parametrize("public_read", ["registered"], indirect=True)
def test_private_document_read_rejects_non_operator_caller_before_source_capture(public_read):
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        read(public_read, caller=object())
    public_read.verifier.sources.authorize_scope_in_session.assert_not_called()
