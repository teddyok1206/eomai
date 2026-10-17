"""Real temporary members/root cache, synthetic DB metadata; no live authorization."""

from collections import Counter
from typing import cast

import pytest
from eom_catalog_service import past_exam_source_provenance as provenance
from eom_catalog_service.artifacts import CatalogArtifactReader, CatalogModelArtifactReader
from eom_catalog_service.knowledge_retrieval_service import _RequestScopedArtifactValidationCache
from eom_catalog_service.past_exam_source_provenance import PastExamSourceResolutionCache
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.models import ArtifactRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import ValidationError as SchemaError

from tests.unit.test_past_exam_source_provenance import _documents, _member, _Reader
from tests.unit.test_scoped_artifact_model_decoding import payload_context


@pytest.mark.parametrize("kind", ("batch", "acceptance", "result", "layout"))
@pytest.mark.parametrize("wrapped", (False, True))
def test_all_shared_provenance_models_decode_once_across_fresh_phase_caches(
    tmp_path, monkeypatch, kind, wrapped
):
    documents = _documents()
    name = kind + ".json"
    member = _member(name, documents[name])
    root, session = payload_context(tmp_path, member, canonical_json_bytes(documents[name]))
    validations = Counter()
    original = provenance.validate_contract

    def validate(schema, value):
        validations[schema] += 1
        return original(schema, value)

    monkeypatch.setattr(provenance, "validate_contract", validate)
    values = []
    for _phase in range(4):
        reader = _RequestScopedArtifactValidationCache(root) if wrapped else root
        assert isinstance(reader, CatalogModelArtifactReader)
        cache = PastExamSourceResolutionCache()
        values.append(getattr(cache, kind)(reader, member))
    assert values == [values[0]] * 4
    assert all(value.value is values[0].value for value in values)
    assert sum(validations.values()) == 1
    assert len(session.statements) == 3 and session.get_calls == 0
    # New phase/index caches cannot turn a retained model into an approval grant.
    session.get(ArtifactRecord, member.artifact_id).approved = False
    with pytest.raises(PinnedArtifactResolutionError):
        reader = _RequestScopedArtifactValidationCache(root) if wrapped else root
        getattr(PastExamSourceResolutionCache(), kind)(reader, member)


@pytest.mark.parametrize("budget", ("bytes", "members"))
def test_existing_root_model_budget_falls_back_without_truncating_provenance(
    tmp_path, monkeypatch, budget
):
    document = _documents()["batch.json"]
    member = _member("batch.json", document)
    root, _session = payload_context(tmp_path, member, canonical_json_bytes(document))
    if budget == "bytes":
        root.MAX_DECODED_BYTES = 0
    else:
        root.MAX_DECODED_MEMBERS = 0
    calls = Counter()
    original = provenance.validate_contract

    def validate(schema, value):
        calls[schema] += 1
        return original(schema, value)

    monkeypatch.setattr(provenance, "validate_contract", validate)
    values = [
        PastExamSourceResolutionCache().batch(_RequestScopedArtifactValidationCache(root), member)
        for _phase in range(4)
    ]
    assert values == [values[0]] * 4 and sum(calls.values()) == 4


def test_wrapper_without_model_delegate_preserves_original_validation_path(monkeypatch):
    documents = _documents()
    delegate = _Reader(documents)
    validations = Counter()
    original = provenance.validate_contract

    def validate(schema, value):
        validations[schema] += 1
        return original(schema, value)

    monkeypatch.setattr(provenance, "validate_contract", validate)
    member = _member("batch.json", documents["batch.json"])
    values = [
        PastExamSourceResolutionCache().batch(
            _RequestScopedArtifactValidationCache(cast(CatalogArtifactReader, delegate)), member
        )
        for _phase in range(4)
    ]
    assert values == [values[0]] * 4 and sum(validations.values()) == 4
    assert len(delegate.calls) == 4


@pytest.mark.parametrize("member_budget", (1, 2))
def test_exact_bound_alias_reuses_bytes_without_an_extra_byte_charge(monkeypatch, member_budget):
    from eom_catalog_service import knowledge_retrieval_service as retrieval

    monkeypatch.setattr(retrieval, "MAX_REQUEST_ARTIFACT_CACHE_MEMBERS", member_budget)
    documents = _documents()
    delegate = _Reader(documents)
    wrapper = _RequestScopedArtifactValidationCache(cast(CatalogArtifactReader, delegate))
    member = _member("batch.json", documents["batch.json"])
    value = PastExamSourceResolutionCache().batch(wrapper, member)
    assert value.value.work_units
    assert len(delegate.calls) == (2 if member_budget == 1 else 1)
    assert wrapper._member_bytes_total == len(delegate.payloads["batch.json"])
    assert len(wrapper._verified_members) <= member_budget
    assert len({id(raw) for raw in wrapper._member_bytes.values()}) == 1


@pytest.mark.parametrize("size", (0, -1, True, 10**9))
def test_wrapper_fallback_does_not_decode_wrong_byte_count(size):
    documents = _documents()
    member = _member("batch.json", documents["batch.json"])
    delegate = _Reader(documents)
    wrapper = _RequestScopedArtifactValidationCache(cast(CatalogArtifactReader, delegate))
    pointer = ArtifactMemberPointer(
        artifact_id=member.artifact_id,
        artifact_revision_id=member.artifact_revision_id,
        member_path=member.member_path,
        sha256=member.sha256,
        media_type=member.media_type,
        schema_ref=member.schema_ref,
    )

    def decode(_schema, _raw):
        pytest.fail("invalid byte bound reached decoder")

    with pytest.raises(ValueError):
        wrapper.read_model_member(pointer, expected_bytes=size, decoder=decode)
    if type(size) is not int or size <= 0:
        assert not delegate.calls


def test_wrong_provenance_kind_cannot_reuse_a_different_model(tmp_path):
    document = _documents()["batch.json"]
    member = _member("batch.json", document)
    root, _session = payload_context(tmp_path, member, canonical_json_bytes(document))
    first = PastExamSourceResolutionCache().batch(root, member)
    with pytest.raises((ValueError, SchemaError)):
        PastExamSourceResolutionCache().acceptance(
            _RequestScopedArtifactValidationCache(root), member
        )
    assert PastExamSourceResolutionCache().batch(root, member) == first
