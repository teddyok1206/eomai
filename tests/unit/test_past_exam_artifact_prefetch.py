"""Synthetic caller-root metadata; real typed provenance decoding, no DB/NAS/model."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from eom_catalog_contracts import AssessmentLayoutObservation
from eom_catalog_service import knowledge_analysis_sources as sources
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.past_exam_artifact_prefetch import prefetch_past_exam_artifact_closure
from eom_catalog_service.past_exam_source_provenance import PastExamProvenanceMember
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
    artifact_identity_hints,
)

from tests.unit.test_past_exam_source_provenance import _source_fixture


class ClosedMetadataReader:
    MAX_REVISIONS = 4096

    def __init__(self, session, delegate, expected_metadata):
        self.session, self.delegate = session, delegate
        self.expected_metadata = expected_metadata
        self.known = {(key[0], key[1]) for key in expected_metadata}
        layout = AssessmentLayoutObservation.model_validate_json(delegate.payloads["layout.json"])
        for page in layout.pages:
            self.known.update(
                (pointer.artifact_id, pointer.artifact_revision_id)
                for pointer in (page.page.source, page.page.image)
            )
        self.settings = delegate.settings
        self.captured: set[tuple[str, str]] = set()
        self.batches: list[tuple[tuple[str, str], ...]] = []

    def require_session(self, session):
        if session is not self.session:
            raise PinnedArtifactResolutionError("different root")

    def prefetch(self, identities):
        if not set(identities).issubset(self.known):
            raise PinnedArtifactResolutionError("unregistered metadata identity")
        self.batches.append(identities)
        self.captured.update(identities)
        assert len(self.captured) <= self.MAX_REVISIONS

    def read_member(self, **kwargs):
        if (kwargs["artifact_id"], kwargs["revision_id"]) not in self.captured:
            raise PinnedArtifactResolutionError("pinned Artifact metadata was not captured")
        expected = self.expected_metadata[
            (kwargs["artifact_id"], kwargs["revision_id"], kwargs["member_path"])
        ]
        if (kwargs["schema_ref"], kwargs["media_type"]) != expected:
            raise PinnedArtifactResolutionError("pinned Artifact member descriptor differs")
        return self.delegate.read_member(**kwargs)

    def verify_member(self, **kwargs):
        assert (kwargs["artifact_id"], kwargs["revision_id"]) in self.captured


@pytest.fixture
def closure(monkeypatch):
    session, original, state = _source_fixture(monkeypatch)
    fake = cast(Any, session)
    queries = []
    previous = fake.scalars

    def scalars(statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity in {
            LegacyItemExtractionAcceptanceRecord,
            LegacyItemExtractionBatchRecord,
            AssessmentLayoutObservationRecord,
            AssessmentSourceBundleRevisionRecord,
        }:
            queries.append(statement)
            return (fake.records[entity],)
        if entity is LegacyItemExtractionBatchWorkUnitRecord:
            queries.append(statement)
            return (fake.unit,)
        return previous(statement)

    fake.scalars = scalars
    expected = {}
    for model, prefix in (
        (LegacyItemExtractionBatchRecord, "manifest_artifact_"),
        (LegacyItemExtractionAcceptanceRecord, "acceptance_artifact_"),
        (LegacyItemExtractionAcceptanceRecord, "result_artifact_"),
        (AssessmentLayoutObservationRecord, "artifact_"),
    ):
        row = fake.records[model]
        expected[
            (
                getattr(row, prefix + "id"),
                getattr(row, prefix + "revision_id"),
                getattr(row, prefix + "member_path"),
            )
        ] = (getattr(row, prefix + "schema_ref"), getattr(row, prefix + "media_type"))
    reader = ClosedMetadataReader(session, original, expected)
    return session, reader, state, queries


def prepare(case, count=1):
    session, reader, state, _queries = case
    prefetch_past_exam_artifact_closure(
        session,
        (cast(ItemRevisionRecord, state["revision"]),) * count,
        cast(PinnedArtifactReadContext, reader),
    )


def resolve(case):
    session, reader, state, _queries = case
    return sources.resolve_historically_approved_item_source(
        session,
        artifacts=reader,
        item_revision_id=state["item_revision_id"],
        source_class="PAST_EXAM",
    )


@pytest.mark.parametrize("count", [1, 520])
def test_exact_extraction_closure_fixes_missing_metadata_with_five_fresh_set_queries(
    closure, count
):
    _session, reader, _state, queries = closure
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve(closure)
    queries.clear()
    prepare(closure, count)
    assert len(queries) == 5
    assert queries[2].column_descriptions[0]["entity"] is AssessmentSourceBundleRevisionRecord
    assert queries[2].get_execution_options()["populate_existing"]
    assert len(reader.batches) == 3
    assert "ACCEPTED" in queries[1].compile().params.values()
    assert all(batch == tuple(sorted(set(batch))) for batch in reader.batches)
    assert resolve(closure).page_image_count >= 1


def test_preparation_is_not_source_approval_or_a_current_decision_cache(closure):
    prepare(closure)
    closure[2]["decision"].decision = "REJECT"
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve(closure)


def test_exact_bundle_batch_refresh_prevents_first_materialization_from_held_stale_bundle(closure):
    session, _reader, _state, queries = closure
    current = session.records[AssessmentSourceBundleRevisionRecord]
    held = deepcopy(current)
    held.state = "WITHDRAWN"
    session.records[AssessmentSourceBundleRevisionRecord] = held
    previous = session.scalars

    def fresh(statement):
        if statement.column_descriptions[0]["entity"] is AssessmentSourceBundleRevisionRecord:
            assert statement.get_execution_options()["populate_existing"]
            session.records[AssessmentSourceBundleRevisionRecord] = current
        return previous(statement)

    session.scalars = fresh
    prepare(closure)
    assert len(queries) == 5
    assert resolve(closure).page_image_count >= 1


def test_wrong_root_fails_before_any_metadata_or_bytes(closure):
    session, reader, state, queries = closure
    reader.session = object()
    with pytest.raises(PinnedArtifactResolutionError, match="different root"):
        prepare(closure)
    assert not queries and not reader.delegate.calls and not reader.batches
    reader.session = session
    assert state["revision"].metadata_json["source_kind"] == "PAST_EXAM"


def test_no_past_exam_revisions_need_no_extra_metadata_read(closure):
    _session, reader, state, queries = closure
    state["revision"].metadata_json["source_kind"] = "GENERATED"
    prepare(closure)
    assert not queries and not reader.delegate.calls


def test_changed_member_hash_is_not_ignored_or_replaced_with_latest(closure):
    reader = closure[1]
    reader.delegate.payloads["batch.json"] += b" "
    with pytest.raises(ValueError, match="hash/size"):
        prepare(closure)
    assert len(reader.delegate.calls) == 1


def test_source_member_values_are_keyword_only_to_prevent_string_field_swaps():
    with pytest.raises(TypeError):
        PastExamProvenanceMember("a", "b", "c", "d", "e", "f", 1)


def test_closed_reader_reproduces_schema_media_swap_even_with_correct_hash(closure):
    prepare(closure)
    reader = closure[1]
    arguments = dict(reader.delegate.calls[0])
    arguments["schema_ref"], arguments["media_type"] = (
        arguments["media_type"],
        arguments["schema_ref"],
    )
    with pytest.raises(PinnedArtifactResolutionError, match="descriptor differs"):
        reader.read_member(**arguments)


def test_preparation_does_not_admit_or_eagerly_decode_draft_proposal_content(closure):
    reader = closure[1]
    # Raw acceptance/result bytes are for the canonical resolver, not the
    # metadata preparation adapter. Corruption is still rejected by that owner.
    reader.delegate.payloads["result.json"] += b"untrusted draft"
    prepare(closure)
    assert {call["member_path"] for call in reader.delegate.calls} == {"batch.json", "layout.json"}
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve(closure)


def test_missing_canonical_page_reference_is_not_skipped(closure):
    reader = closure[1]
    page_id = next(iter(reader.known - {(k[0], k[1]) for k in reader.expected_metadata}))
    reader.known.remove(page_id)
    with pytest.raises(PinnedArtifactResolutionError, match="unregistered"):
        prepare(closure)


def test_hint_collection_is_deduplicated_and_not_a_permission_contract():
    pointer = {"artifact_id": "not-a-valid-artifact", "artifact_revision_id": "not-a-revision"}
    assert artifact_identity_hints({"a": pointer, "b": [pointer], "text": "secret"}) == {
        ("not-a-valid-artifact", "not-a-revision")
    }
    assert artifact_identity_hints({"artifact_id": "x", "artifact_revision_id": None}) == set()
