"""Real local index bytes; explicit synthetic source/IAM/current-head metadata, no launch."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service import embedding_registry_catalog_adapter as module
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    PrivateChatContextPreparation,
    RegisteredEmbeddingIndexRead,
)
from eom_catalog_service.private_chat_context_preparation import (
    validate_private_chat_context_preparation,
)
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_private_chat_query_basis import TEXT, basis


@pytest.fixture
def initial(owner, monkeypatch):
    verifier, session, command, index, _binding, _scope, _root = owner
    session.get_bind = lambda: verifier.engine
    query = type(index.space).model_validate(
        seal(index.space.model_dump(mode="json") | {"purpose": "QUERY"}, "space_sha256")
    )
    request = PrivateChatContextPreparation(
        "similarityrequest_" + "a" * 32,
        basis(),
        EmbeddingRegistryLookup(
            command.corpus_id,
            command.namespace,
            command.graph_snapshot,
            command.policy_revision_id,
            command.policy_sha256,
        ),
        ReferenceQuerySpaces(query=query, document=index.space),
        8,
    )
    registered = RegisteredEmbeddingIndexRead(
        command.corpus_id,
        command.namespace,
        index.index_id,
        index.index_revision_id,
        command.index_manifest,
        index.index_sha256,
        command.graph_snapshot.graph_snapshot_revision_id,
        command.policy_revision_id,
        command.policy_sha256,
        len(index.bindings),
        command.binding_set_sha256,
    )
    value = SimpleNamespace(
        verifier=verifier,
        session=session,
        command=command,
        index=index,
        request=request,
        current=registered,
        reads=[],
        captures=[],
        denied_at=None,
        advance_head=False,
        fail_producer=False,
    )

    class Repository:
        def __init__(self, current):
            assert current is session

        def current_namespace_revision(self, corpus_id, namespace):
            assert corpus_id == command.corpus_id and namespace == command.namespace
            value.reads.append(namespace)
            return None if value.current is None else (value.current, 1)

    monkeypatch.setattr(module, "EmbeddingRegistryRepository", Repository)
    original = verifier.sources.capture_in_session.side_effect

    def capture(*args, **options):
        value.captures.append(options["phase"])
        if value.denied_at == len(value.captures):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
        result = original(*args, **options)
        if len(value.captures) == 2:
            if value.advance_head:
                value.current = replace(
                    registered, index_revision_id="embeddingindexrev_" + "f" * 32
                )
            if value.fail_producer:
                revision = session.get(
                    ArtifactRevisionRecord, command.index_manifest.artifact_revision_id
                )
                session.get(JobRecord, revision.job_id).status = "FAILED"
        return result

    monkeypatch.setattr(verifier.sources, "capture_in_session", Mock(side_effect=capture))
    monkeypatch.setattr(
        verifier, "_iter_numerical_shards", Mock(side_effect=AssertionError("numeric read"))
    )
    return value


pytestmark = pytest.mark.parametrize("owner", ["CONTENT_ONLY"], indirect=True)


def prepare(value, **overrides):
    return value.verifier.prepare_private_chat_context_in_session(
        value.session,
        **(
            dict(caller=EmbeddingRegistryCaller("operator_" + "1" * 32), preparation=value.request)
            | overrides
        ),
    )


def test_initial_private_request_pins_official_index_without_invented_item(initial):
    value = initial
    result = prepare(value)
    assert result == PrivateChatSimilarityRequest.model_validate(result.model_dump(mode="json"))
    assert result.consumer_purpose == "GENERAL_CHAT_READ" and result.query_basis == basis()
    assert result.views[0].index.index_revision_id == value.index.index_revision_id
    assert result.views[0].index.index_manifest == value.command.index_manifest
    assert result.views[0].recipe == value.verifier.configuration.recipe
    assert result.graph_snapshot == value.command.graph_snapshot
    assert "anchor" not in result.model_dump(
        mode="json"
    ) and TEXT.encode() not in canonical_json_bytes(result)
    assert len(value.reads) == 1 and len(value.captures) == 2
    validate_private_chat_context_preparation(value.request, value.verifier.configuration, result)


def test_absent_initial_index_stays_absent_without_another_view_or_numeric_fallback(initial):
    value = initial
    value.current = None
    result = prepare(value)
    assert result.views[0].index is None and result.vector_mode == "REQUIRED"
    assert len(value.reads) == 1 and len(value.captures) == 2
    assert value.session.statements == []


def test_late_head_advance_preserves_the_one_initial_revision(initial):
    value = initial
    value.advance_head = True
    result = prepare(value)
    assert result.views[0].index.index_revision_id == value.index.index_revision_id
    assert result.views[0].index.index_revision_id != value.current.index_revision_id
    assert len(value.reads) == 1


@pytest.mark.parametrize("when", [1, 2])
def test_current_actual_authority_denial_is_not_missing_index(initial, when):
    value = initial
    value.denied_at = when
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        prepare(value)
    assert len(value.captures) == when
    if when == 1:
        assert value.reads == [] and value.session.statements == []


def test_index_producer_failure_during_final_authorization_refuses_pins(initial):
    value = initial
    value.fail_producer = True
    with pytest.raises(EmbeddingRegistryError):
        prepare(value)
    assert len(value.captures) == 2 and len(value.reads) == 1


@pytest.mark.parametrize(
    "field,changed",
    [("top_k", True), ("top_k", 0), ("request_id", "bad"), ("query_basis", {"text": TEXT})],
)
def test_malformed_preparation_is_rejected_without_question_in_error(initial, field, changed):
    with pytest.raises(EmbeddingRegistryError) as error:
        replace(initial.request, **{field: changed})
    assert TEXT not in str(error.value)
    assert initial.reads == initial.captures == []


@pytest.mark.parametrize("field", ["top_k", "request_id", "basis", "policy", "graph"])
def test_replay_intent_mismatch_never_selects_a_new_head(initial, field):
    value = initial
    original = prepare(value)
    if field == "top_k":
        changed = replace(value.request, top_k=9)
    elif field == "request_id":
        changed = replace(value.request, request_id="similarityrequest_" + "f" * 32)
    elif field == "basis":
        data = basis().model_dump(mode="json")
        data["turn_id"] = "chatturn_" + "f" * 32
        changed = replace(
            value.request, query_basis=type(basis()).model_validate(seal(data, "basis_sha256"))
        )
    elif field == "policy":
        changed = replace(
            value.request, scope=replace(value.request.scope, policy_sha256="sha256:" + "f" * 64)
        )
    else:
        graph = value.request.scope.graph_snapshot.model_copy(
            update={"graph_id": "graph_" + "f" * 32}
        )
        changed = replace(value.request, scope=replace(value.request.scope, graph_snapshot=graph))
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        validate_private_chat_context_preparation(changed, value.verifier.configuration, original)
    assert len(value.reads) == 1


@pytest.mark.parametrize("kind", ["raw", "copied"])
def test_untrusted_replay_extras_cannot_leak_private_text_or_select_new_head(initial, kind):
    value = initial
    original = prepare(value)
    invalid = (
        original.model_dump(mode="json") | {"question": TEXT}
        if kind == "raw"
        else original.model_copy(update={"question": TEXT})
    )
    with pytest.raises(EmbeddingRegistryError) as error:
        validate_private_chat_context_preparation(
            value.request, value.verifier.configuration, invalid
        )
    assert str(error.value) == "EMBEDDING_REGISTRY_REQUEST_INVALID"
    assert TEXT not in str(error.value) and len(value.reads) == 1
