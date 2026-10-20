"""Real local Artifact bytes, synthetic current source/IAM and indexed metadata only."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service import embedding_registry_catalog_adapter as catalog_module
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
from eom_catalog_service.embedding_registry_repository import EmbeddingRegistryRepository
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    InferenceTransferSessionCapturePhase,
)
from eom_identifiers import content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.models import ArtifactRecord
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.orm import Session

from tests.unit.test_embedding_registry_catalog_adapter import _read_selection
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner


@pytest.fixture
def pinned(owner, monkeypatch):
    verifier, session, command, index, binding, _scope, root = owner
    session.get_bind = lambda: verifier.engine
    intent, registered = _read_selection(command, index)
    body = {
        "schema_version": "system-rag-similarity-request/1.0",
        "request_id": "similarityrequest_" + "e" * 32,
        "consumer_purpose": "PAST_EXAM_VARIATION",
        "anchor": {
            "basis": "APPROVED_REFERENCE_ITEM",
            "source": binding.source.model_dump(mode="json"),
            "profile": binding.profile.model_dump(mode="json"),
            "solution_evidence": binding.solution_evidence.model_dump(mode="json"),
        },
        "graph_snapshot": command.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": command.policy_revision_id,
        "policy_sha256": command.policy_sha256,
        "source_classes": ["PAST_EXAM"],
        "topics": [],
        "unit_ids": [],
        "views": [intent.selection.model_dump(mode="json")],
        "vector_mode": "REQUIRED",
        "maximum_sources": 1024,
        "top_k": 8,
    }
    request = parse_similarity_context_request(body | {"request_sha256": content_sha256(body)})
    value = SimpleNamespace(
        verifier=verifier,
        session=session,
        intent=intent,
        registered=registered,
        request=request,
        root=root,
        command=command,
        binding=binding,
        rows={(registered.index_id, registered.index_revision_id): registered},
        reads=[],
    )

    def read(repository, identities):
        assert repository.session is session
        value.reads.append(identities)
        return value.rows

    monkeypatch.setattr(EmbeddingRegistryRepository, "read_pinned_revisions", read)
    monkeypatch.setattr(
        EmbeddingRegistryRepository,
        "current_namespace_revision",
        Mock(side_effect=AssertionError("historical read must not select a current head")),
    )
    return value


def select(value):
    return value.verifier.for_pinned_similarity_request_in_session(
        value.session, EmbeddingRegistryCaller("operator_" + "1" * 32), value.request
    )


def test_repeated_actual_pinned_reads_decode_once_but_recheck_current_authority(
    pinned, monkeypatch
):
    value = pinned
    parse = Mock(wraps=catalog_module.parse_supported_embedding_index)
    monkeypatch.setattr(catalog_module, "parse_supported_embedding_index", parse)
    first = select(value)
    before = value.verifier.sources.capture_in_session.call_count
    assert select(value) is first
    assert parse.call_count == 1
    assert value.verifier.sources.capture_in_session.call_count > before
    value.session.get(ArtifactRecord, value.registered.index_manifest.artifact_id).approved = False
    with pytest.raises(EmbeddingRegistryError):
        select(value)
    assert parse.call_count == 1


def test_stored_no_vector_request_preserves_absence_and_never_selects_a_head(pinned):
    body = pinned.request.model_dump(mode="json")
    body["vector_mode"] = "OPTIONAL"
    body["views"][0]["index"] = None
    body.pop("request_sha256")
    pinned.request = parse_similarity_context_request(
        body | {"request_sha256": content_sha256(body)}
    )
    original = pinned.request
    assert select(pinned) is pinned.verifier
    assert pinned.request == original and pinned.request.views[0].index is None
    assert pinned.reads == []
    assert pinned.verifier.sources.capture_in_session.call_count == 1


def test_mixed_pinned_populations_fail_before_materializing_any_artifact(pinned, monkeypatch):
    value = pinned
    body = value.request.model_dump(mode="json")
    first = body["views"][0]
    first = first | {
        "view": "CONTENT_ONLY",
        "index": first["index"] | {"index_revision_id": "embeddingindexrev_" + "f" * 32},
    }
    body["views"] = [first, body["views"][0]]
    body.pop("request_sha256")
    value.request = parse_similarity_context_request(
        body | {"request_sha256": content_sha256(body)}
    )
    first_row = replace(
        value.registered,
        index_revision_id=first["index"]["index_revision_id"],
        namespace=EmbeddingIndexNamespace.model_validate(
            value.registered.namespace.model_dump(mode="json") | {"view": "CONTENT_ONLY"}
        ),
    )
    last_row = replace(
        value.registered,
        namespace=EmbeddingIndexNamespace.model_validate(
            value.registered.namespace.model_dump(mode="json")
            | {"population_scope": "OCCURRENCE_BACKED_PAST_EXAM"}
        ),
    )
    value.rows = {(row.index_id, row.index_revision_id): row for row in (first_row, last_row)}
    read = Mock(side_effect=AssertionError("mixed namespaces fail before Artifact reads"))
    monkeypatch.setattr(value.verifier, "_read_index", read)
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        select(value)
    read.assert_not_called()


@pytest.mark.parametrize("historical", (False, True))
def test_exact_original_namespace_and_real_artifact_read_under_current_all(pinned, historical):
    value = pinned
    original_config = value.verifier.configuration
    if historical:
        namespace = EmbeddingIndexNamespace.model_validate(
            value.registered.namespace.model_dump(mode="json")
            | {"population_scope": "OCCURRENCE_BACKED_PAST_EXAM"}
        )
        value.registered = replace(value.registered, namespace=namespace)
        value.rows = {
            (value.registered.index_id, value.registered.index_revision_id): value.registered
        }
    selected = select(value)
    assert selected.configuration.namespace == value.registered.namespace
    assert selected.configuration.source_classes == ("PAST_EXAM",)
    assert selected.identity_fence is value.verifier.identity_fence
    assert selected.sources is value.verifier.sources
    assert value.verifier.configuration is original_config
    assert (selected is value.verifier) is (not historical)
    assert value.reads == [((value.registered.index_id, value.registered.index_revision_id),)]
    capture_commands = [call.args[1] for call in selected.sources.capture_in_session.call_args_list]
    assert len(capture_commands) == 2
    assert capture_commands[0].population_scope.value == "ALL_ADMITTED_GRAPH_ITEMS"
    assert capture_commands[1].population_scope.value == value.registered.namespace.population_scope
    intent = replace(
        value.intent, scope=replace(value.intent.scope, namespace=value.registered.namespace)
    )
    actual = selected.resolve_pinned_read(
        value.session, EmbeddingRegistryCaller("operator_" + "1" * 32), intent, value.registered
    )
    assert actual.bindings == (value.binding,)
    assert actual.available_binding_count == 1 and actual.numerical_rows
    assert all(source.source_class == "PAST_EXAM" for source in actual.sources)


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "corpus",
        "partition",
        "space",
        "recipe",
        "projection",
        "scope",
        "hash",
        "stale",
        "policy",
    ),
)
def test_foreign_or_stale_registered_pin_fails_without_latest_or_fallback(pinned, fault):
    value = pinned
    registered = value.registered
    if fault == "missing":
        value.rows = {}
    elif fault == "corpus":
        registered = replace(registered, corpus_id="corpus_" + "f" * 32)
    elif fault in {"partition", "space", "recipe", "projection", "scope"}:
        fields = {
            "partition": ("storage_partition", "corpus_" + "f" * 32),
            "space": ("space_sha256", "sha256:" + "f" * 64),
            "recipe": ("recipe_sha256", "sha256:" + "f" * 64),
            "projection": ("projection_version", "foreign/1.0"),
            "scope": ("population_scope", "UNSUPPORTED"),
        }
        name, replacement = fields[fault]
        registered = replace(
            registered, namespace=registered.namespace.model_copy(update={name: replacement})
        )
    elif fault == "hash":
        registered = replace(registered, index_sha256="sha256:" + "f" * 64)
    elif fault == "policy":
        registered = replace(registered, policy_sha256="sha256:" + "f" * 64)
    else:
        registered = replace(
            registered,
            index_manifest=registered.index_manifest.model_copy(
                update={"artifact_revision_id": "rev_" + "f" * 32}
            ),
        )
    if fault != "missing":
        value.rows = {(registered.index_id, registered.index_revision_id): registered}
    with pytest.raises(EmbeddingRegistryError):
        select(value)
    assert value.verifier.configuration.namespace.population_scope == "ALL_ADMITTED_GRAPH_ITEMS"


@pytest.mark.parametrize("late", (False, True))
def test_actual_source_fence_revocation_never_returns_a_selected_owner(pinned, late):
    calls = 0

    def fence(*_):
        nonlocal calls
        calls += 1
        if calls == (2 if late else 1):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    pinned.verifier.identity_fence.fence_current_operator.side_effect = fence
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        select(pinned)
    assert len(pinned.reads) == (1 if late else 0)


@pytest.mark.parametrize("late", (False, True))
def test_canonical_artifact_withdrawal_is_checked_before_and_after_selection(pinned, late):
    pointer = pinned.registered.index_manifest
    artifact = pinned.session.records[(ArtifactRecord, pointer.artifact_id)]
    if late:
        original = pinned.verifier.sources.capture_in_session.side_effect
        count = 0

        def capture(*args, **kwargs):
            nonlocal count
            result = original(*args, **kwargs)
            assert kwargs["phase"] is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            count += 1
            if count == 2:
                artifact.approved = False
            return result

        pinned.verifier.sources.capture_in_session.side_effect = capture
    else:
        artifact.approved = False
    with pytest.raises(EmbeddingRegistryError, match="POINTER_INVALID"):
        select(pinned)


def test_three_registered_revision_keys_use_one_indexed_read_and_no_current_head():
    session = Mock(spec=Session)
    session.execute.return_value.all.return_value = []
    identities = tuple(
        ("embeddingindex_" + value * 32, "embeddingindexrev_" + value * 32)
        for value in ("1", "2", "3")
    )
    assert EmbeddingRegistryRepository(session).read_pinned_revisions(identities) == {}
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
    assert "JOIN embedding_indexes" in sql and " IN ((" in sql
    assert "current_index_revision_id" not in sql and "FOR UPDATE" not in sql
    assert "eligible_source_count" not in sql and session.execute.call_count == 1


@pytest.mark.parametrize("identities", ((), (("a", "b"),) * 2, (("a", "b"),) * 4))
def test_unbounded_or_duplicate_index_keys_fail_before_sql(identities):
    session = Mock(spec=Session)
    with pytest.raises(EmbeddingRegistryError, match="POINTER_INVALID"):
        EmbeddingRegistryRepository(session).read_pinned_revisions(identities)
    session.execute.assert_not_called()
