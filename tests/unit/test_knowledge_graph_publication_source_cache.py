"""Real scalar source resolver and canonical projections; no DB, NAS or model calls."""

from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisWorkerProposal,
    PublishKnowledgeGraphSnapshotCommand,
)
from eom_catalog_service import knowledge_analysis_sources as sources
from eom_catalog_service import knowledge_graph_publication_service as publication
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    build_education_graph_projection,
    serialize_education_graph_projection,
)
from eom_catalog_service.past_exam_source_provenance import PastExamSourceResolutionCache
from eom_identifiers import content_sha256

from tests.unit.test_knowledge_graph_projection import _analysis, _proposal
from tests.unit.test_past_exam_source_provenance import _source_fixture


class ReadPhaseCaptured(RuntimeError):
    pass


def source_case(monkeypatch):
    session, reader, state = _source_fixture(monkeypatch)
    source = sources.resolve_historically_approved_item_source(
        session,
        artifacts=reader,
        item_revision_id=state["item_revision_id"],
        source_class="PAST_EXAM",
    )
    reader.calls.clear()
    owner = object.__new__(publication.KnowledgeGraphPublicationService)
    owner.artifacts = reader
    operations = Counter()
    actual_get, actual_scalars, actual_verify = session.get, session.scalars, reader.verify_member

    def get(model, identity):
        operations[("get", model.__name__)] += 1
        return actual_get(model, identity)

    def scalars(statement):
        operations[("scalars", statement.column_descriptions[0]["entity"].__name__)] += 1
        return actual_scalars(statement)

    def verify(**kwargs):
        operations[("verify_member", kwargs["member_path"])] += 1
        return actual_verify(**kwargs)

    monkeypatch.setattr(session, "get", get)
    monkeypatch.setattr(session, "scalars", scalars)
    monkeypatch.setattr(reader, "verify_member", verify)
    return owner, session, reader, state, source, operations


def resolve(owner, session, source, cache=None):
    return owner._resolve_source_again(
        session,
        SimpleNamespace(source=source),
        past_exam_cache=cache,
    )


def analysis(run_id, source):
    value = _proposal("1").model_dump(mode="json")
    value["anchors"][0].update(
        artifact_revision_id=source.artifact_member.artifact_revision_id,
        member_path=source.artifact_member.member_path,
    )
    return AcceptedAnalysisProposal(
        analysis_run_id=run_id,
        source=source,
        accepted_result=_analysis("1").accepted_result,
        proposal=KnowledgeAnalysisWorkerProposal.model_validate(value),
    )


def test_520_sources_read_shared_provenance_once_with_identical_projection(monkeypatch):
    owner, session, reader, _state, source, operations = source_case(monkeypatch)
    run_ids = tuple(f"analysisrun_{number:032x}" for number in range(520))
    scalar = tuple(analysis(run_id, resolve(owner, session, source)) for run_id in run_ids)
    assert len(reader.calls) == 4 * 520
    scalar_operations = operations.copy()
    reader.calls.clear()
    operations.clear()
    cache = PastExamSourceResolutionCache()
    cached = tuple(analysis(run_id, resolve(owner, session, source, cache)) for run_id in run_ids)
    assert len(reader.calls) == 4
    assert operations == scalar_operations  # Every scalar SQL and page-member check remains.
    assert cached == scalar
    uncached_projection = serialize_education_graph_projection(
        build_education_graph_projection(scalar, None)
    )
    cached_projection = serialize_education_graph_projection(
        build_education_graph_projection(cached, None)
    )
    assert cached_projection == uncached_projection
    assert cached_projection.members == uncached_projection.members
    assert cached_projection.snapshot_sha256 == uncached_projection.snapshot_sha256


@pytest.mark.parametrize(
    "budget", ({"max_members": 0}, {"max_source_bytes": 0}, {"max_index_rows": 0})
)
def test_existing_budget_fallback_still_fully_resolves_every_source(monkeypatch, budget):
    owner, session, reader, _state, source, operations = source_case(monkeypatch)
    scalar = tuple(resolve(owner, session, source) for _ in range(16))
    scalar_operations = operations.copy()
    operations.clear()
    reader.calls.clear()
    cache = PastExamSourceResolutionCache(**budget)
    assert tuple(resolve(owner, session, source, cache) for _ in range(16)) == scalar
    assert len(reader.calls) == 4 * 16 and operations == scalar_operations


@pytest.mark.parametrize("fault", ("revision", "decision", "acceptance", "artifact", "lineage"))
def test_warm_cache_does_not_cache_current_source_admission(monkeypatch, fault):
    owner, session, reader, state, source, _operations = source_case(monkeypatch)
    cache = PastExamSourceResolutionCache()
    assert resolve(owner, session, source, cache) == source
    if fault == "revision":
        state["revision"].revision_state = "DRAFT"
    elif fault == "decision":
        state["decision"].decision = "REJECT"
    elif fault == "acceptance":
        state["acceptance"].coverage_state = "INCOMPLETE"
    elif fault == "artifact":
        state["approved"]["value"] = False
    else:
        state["unit"].request_sha256 = "sha256:" + "0" * 64
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve(owner, session, source, cache)
    assert len(reader.calls) == 4


def test_a_new_read_phase_revalidates_changed_immutable_bytes(monkeypatch):
    owner, session, reader, _state, source, _operations = source_case(monkeypatch)
    assert resolve(owner, session, source, PastExamSourceResolutionCache()) == source
    reader.payloads["batch.json"] = b"changed untrusted bytes"
    for _ in range(2):
        with pytest.raises(sources.KnowledgeAnalysisSourceError) as failed:
            resolve(owner, session, source, PastExamSourceResolutionCache())
        assert failed.value.code == "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH"
    assert len(reader.calls) == 6


def test_publish_shares_only_one_read_phase_cache_and_creates_a_fresh_next_one(monkeypatch):
    owner, session, reader, _state, source, _operations = source_case(monkeypatch)
    run_ids = tuple(f"analysisrun_{number:032x}" for number in range(16))
    value = {
        "schema_version": "knowledge-graph-publication/1.0",
        "corpus_key": "synthetic-past-exam-source-cache",
        "display_name": "Synthetic source cache",
        "accepted_analysis_run_ids": run_ids,
        "structure_manifest": None,
        "expected_current_snapshot_revision_id": None,
        "publisher_version": "1.0.0",
        "published_by_operator_id": "operator_" + "1" * 32,
        "idempotency_key": "synthetic-source-cache",
        "requested_at": "2026-11-14T00:00:00Z",
    }
    command = PublishKnowledgeGraphSnapshotCommand.model_validate(
        value | {"request_sha256": content_sha256(value)}
    )
    outer_session = SimpleNamespace(
        get=lambda *_args: SimpleNamespace(status="ACTIVE"), scalar=lambda *_args: None
    )
    owner.sessions = lambda: nullcontext(outer_session)
    owner._existing_publication = Mock(return_value=None)
    owner._load_structure_manifest = Mock(side_effect=ReadPhaseCaptured)
    seen = []

    def load(current, run_id, *, document_source_cache=None, past_exam_cache=None):
        assert current is outer_session and document_source_cache is not None
        assert isinstance(past_exam_cache, PastExamSourceResolutionCache)
        seen.append(past_exam_cache)
        return analysis(run_id, resolve(owner, session, source, past_exam_cache))

    owner._load_accepted_analysis = load
    for _ in range(2):
        with pytest.raises(ReadPhaseCaptured):
            owner.publish(command)
    assert len(reader.calls) == 8
    assert all(cache is seen[0] for cache in seen[:16])
    assert all(cache is seen[16] for cache in seen[16:])
    assert seen[0] is not seen[16]
    assert not any(
        isinstance(value, PastExamSourceResolutionCache) for value in vars(owner).values()
    )


def test_load_accepted_analysis_forwards_cache_without_skipping_state_gate(monkeypatch):
    owner, _session, _reader, _state, source, _operations = source_case(monkeypatch)
    cache = PastExamSourceResolutionCache()
    request = SimpleNamespace(source=source)
    monkeypatch.setattr(
        KnowledgeAnalysisRequestV9,
        "model_validate",
        classmethod(lambda _cls, _value: request),
    )
    run = SimpleNamespace(
        state="ACCEPTED",
        accepted_result_artifact_id="present",
        accepted_result_artifact_revision_id="present",
        accepted_result_sha256="present",
        proposal_artifact_id="present",
        proposal_artifact_revision_id="present",
        proposal_content_set_sha256="present",
        canonical_request={"schema_version": "knowledge-analysis-request/9.0"},
    )
    session = SimpleNamespace(get=lambda *_args: run)
    owner._resolve_source_again = Mock(side_effect=ReadPhaseCaptured)
    with pytest.raises(ReadPhaseCaptured):
        owner._load_accepted_analysis(session, "synthetic-run", past_exam_cache=cache)
    assert owner._resolve_source_again.call_args.kwargs["past_exam_cache"] is cache
    run.state = "REJECTED"
    owner._resolve_source_again.reset_mock()
    with pytest.raises(publication.KnowledgeGraphPublicationError) as ineligible:
        owner._load_accepted_analysis(session, "synthetic-run", past_exam_cache=cache)
    assert ineligible.value.code == "KNOWLEDGE_GRAPH_ANALYSIS_INELIGIBLE"
    owner._resolve_source_again.assert_not_called()
