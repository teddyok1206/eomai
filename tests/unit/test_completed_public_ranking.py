"""Saved metadata/source fences with explicit synthetic SQL and full-read leaves."""

from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.completed_public_ranking import CompletedPublicSimilarityRanking
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service import completed_public_ranking_read as module
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.completed_public_ranking_artifact import SAVED_PUBLIC_RANKING_SCHEMA_REF
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)


def values(version=3):
    original = (
        public_workflow_case()
        if version == 3
        else registered_public_workflow_case(registered_anchor=False)
    ).request
    _, context, *_ = (public_similarity_case if version == 3 else registered_similarity_case)()
    if version == 5:
        body = original.model_dump(mode="json")
        body["schema_version"] = "reference-query-workflow-request/5.0"
        body["context_request"]["schema_version"] = "system-rag-similarity-request/5.0"
        body["context_request"] = seal(body["context_request"], "request_sha256")
        original = parse_supported_reference_query_workflow_request(seal(body, "request_sha256"))
    raw = context.model_dump(mode="json") | {
        "request": original.context_request.model_dump(mode="json")
    }
    if version == 5:
        raw["schema_version"] = "system-rag-similarity-context/5.0"
    context = parse_supported_public_solution_similarity_context(seal(raw, "context_sha256"))
    selection = CompletedSimilarityQuerySelection(
        workflow_id="workflow_" + "2" * 32,
        workflow_request_sha256=original.request_sha256,
        context_request_sha256=original.context_request.request_sha256,
    )
    return original, context, selection


@pytest.mark.parametrize("version", (3, 4, 5))
def test_saved_ranking_roundtrip_uses_existing_context_family_and_exact_hashes(version):
    original, context, selection = values(version)
    body = dict(
        schema_version="completed-public-similarity-ranking/1.0",
        operator_id=original.operator_audit.operator_id,
        context=context.model_dump(mode="json"),
        selection=selection.model_dump(mode="json"),
        dependency_sha256="sha256:" + "a" * 64,
    )
    document = seal(body, "snapshot_sha256")
    parsed = CompletedPublicSimilarityRanking.model_validate(document)
    assert parsed.context == context
    assert CompletedPublicSimilarityRanking.model_validate_json(parsed.model_dump_json()) == parsed
    for field in ("snapshot_sha256", "operator_id"):
        bad = deepcopy(document)
        bad[field] = "sha256:" + "b" * 64 if field == "snapshot_sha256" else "ADMIN"
        with pytest.raises((ValueError, SchemaError)):
            CompletedPublicSimilarityRanking.model_validate(bad)
    bad = deepcopy(document)
    bad["selection"]["context_request_sha256"] = "sha256:" + "b" * 64
    with pytest.raises((ValueError, SchemaError)):
        CompletedPublicSimilarityRanking.model_validate(seal(bad, "snapshot_sha256"))


class Store:
    def __init__(self):
        self.document = None
        self.commits = 0
        self.key = None

    def pointer(self):
        return ArtifactMemberPointer(
            artifact_id="artifact_" + "d" * 32,
            artifact_revision_id="rev_" + "e" * 32,
            member_path="ranking.json",
            schema_ref=SAVED_PUBLIC_RANKING_SCHEMA_REF,
            media_type="application/json",
            sha256=sha256_bytes(canonical_json_bytes(self.document)),
        )

    def find(self, key):
        assert self.key is None or self.key == key
        self.key = key
        return None if self.document is None else self.pointer()

    def commit(self, value, key):
        assert self.key == key and self.document is None
        self.document = value.model_dump(mode="json")
        self.commits += 1
        return self.pointer()


@pytest.fixture
def reading(monkeypatch):
    original, context, selection = values()
    owner, scope, session, store = NS(settings=NS()), NS(), NS(), Store()
    reader = NS(
        prefetch=Mock(),
        require_file_set=Mock(),
        read_pinned=lambda **_a: NS(payload=canonical_json_bytes(store.document)),
        revalidate_provenance=Mock(),
    )
    monkeypatch.setattr(module.PinnedArtifactReadContext, "for_session", lambda *_a: reader)
    caller = EmbeddingRegistryCaller(original.operator_audit.operator_id)
    selected = Mock(return_value=original)
    composed = Mock(return_value=context)
    observed = Mock(return_value="sha256:" + "a" * 64)
    monkeypatch.setattr(module, "select_completed_reference_query_request", selected)
    monkeypatch.setattr(
        module, "select_completed_reference_query_read_owner", lambda value, _r: value
    )
    monkeypatch.setattr(module, "read_completed_public_solution_similarity_in_session", composed)
    monkeypatch.setattr(module, "observe_completed_public_ranking_dependencies", observed)
    monkeypatch.setattr(module, "_scope", lambda *_a: scope)
    lock = Mock()
    monkeypatch.setattr(module, "_lock_result", lock)
    return NS(
        original=original,
        context=context,
        selection=selection,
        owner=owner,
        scope=scope,
        session=session,
        store=store,
        reader=reader,
        caller=caller,
        selected=selected,
        composed=composed,
        observed=observed,
        lock=lock,
    )


def read(value):
    return module.read_saved_public_ranking_in_session(
        value.session, value.owner, value.caller, value.selection, store=value.store
    )


def test_second_read_returns_saved_ranking_without_document_decode_vector_or_rank(reading):
    value = reading
    assert read(value) == value.context
    snapshot = deepcopy(value.store.document)
    value.composed.side_effect = AssertionError("completed reread must not compose again")
    assert read(value) == value.context
    assert value.store.commits == 1 and value.composed.call_count == 1
    assert value.selected.call_count == 4 and value.observed.call_count == 5
    assert value.lock.call_count == 1  # Completed cache hits do not serialize readers.
    assert value.store.document == snapshot


@pytest.mark.parametrize("fault", ("hash", "identity", "request", "dependency"))
def test_invalid_saved_result_never_falls_back_to_new_ranking_or_new_query(reading, fault):
    value = reading
    read(value)
    body = value.store.document
    if fault == "hash":
        body["snapshot_sha256"] = "sha256:" + "b" * 64
    elif fault == "identity":
        body["operator_id"] = "operator_" + "f" * 32
    elif fault == "request":
        body["selection"]["workflow_request_sha256"] = "sha256:" + "f" * 64
    else:
        value.observed.return_value = "sha256:" + "f" * 64
    if fault in ("identity", "request"):
        value.store.document = seal(body, "snapshot_sha256")
    value.composed.side_effect = AssertionError("invalid cache is not permission to recompute")
    with pytest.raises(SimilarityContextReadError):
        read(value)
    assert value.composed.call_count == 1 and value.store.commits == 1


def test_revoked_operator_stops_before_cache_or_source_reads(reading):
    value = reading
    read(value)
    value.selected.side_effect = SimilarityContextReadError("SOURCE_ACCESS_DENIED")
    before = value.observed.call_count
    with pytest.raises(SimilarityContextReadError, match="SOURCE_ACCESS_DENIED"):
        read(value)
    assert value.observed.call_count == before and value.store.commits == 1


@pytest.mark.parametrize("stage", ("during_read", "late_authority"))
def test_failed_or_changed_first_read_does_not_publish_a_partial_snapshot(reading, stage):
    value = reading
    if stage == "during_read":
        value.composed.side_effect = SimilarityContextReadError("SOURCE_REVOKED")
    else:
        value.observed.side_effect = ("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    with pytest.raises(SimilarityContextReadError, match="SOURCE_REVOKED"):
        read(value)
    assert value.store.commits == 0 and value.store.document is None


def test_snapshot_binds_full_result_not_display_number(reading):
    value = reading
    read(value)
    body = value.store.document
    assert "external_number" not in body
    assert body["context"]["candidates"][0]["source"]["item_revision_id"].startswith("itemrev_")
    assert body["snapshot_sha256"] == content_sha256(
        {key: val for key, val in body.items() if key != "snapshot_sha256"}
    )


def test_waiting_first_reader_rechecks_publication_under_the_lock(reading):
    value = reading
    read(value)
    value.lock.reset_mock()
    find = value.store.find
    calls = 0

    def another_reader_published(key):
        nonlocal calls
        calls += 1
        return None if calls == 1 else find(key)

    value.store.find = another_reader_published
    value.composed.side_effect = AssertionError("the other reader already published")
    assert read(value) == value.context
    value.lock.assert_called_once()
    assert calls == 2 and value.store.commits == 1
