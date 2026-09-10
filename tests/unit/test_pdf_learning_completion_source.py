from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import eom_catalog_service.pdf_learning_completion_source as completion_source_module
import pytest
from eom_catalog_contracts import KnowledgeArtifactMemberPointer, KnowledgeGraphProjections
from eom_catalog_service.models import ItemRevisionRecord
from eom_catalog_service.pdf_learning_completion_service import (
    PdfLearningCompletionError,
    PdfLearningCompletionRequest,
)
from eom_catalog_service.pdf_learning_completion_source import (
    PostgresPdfLearningCompletionSource,
    _analysis_history_scope_is_exact,
    _PinnedCatalogArtifactReader,
)
from eom_identifiers import content_sha256
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy.orm import Session
from test_knowledge_analysis_artifact import _request as _historical_v2_request
from test_past_exam_visual_analysis_contracts import (
    _request as _v9_request,
)
from test_past_exam_visual_analysis_contracts import (
    _source as _v9_source,
)


def _item_manifest_fixture() -> tuple[
    ItemRevisionRecord,
    WorkflowInstanceRecord,
    dict[str, object],
]:
    workflow_created_at = datetime(2026, 9, 1, tzinfo=UTC)
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + "1" * 32,
        definition_key="knowledge-item-production",
        definition_version="1.4.0",
        created_at=workflow_created_at,
    )
    revision = ItemRevisionRecord(
        item_id="item_" + "2" * 32,
        item_revision_id="itemrev_" + "3" * 32,
        revision_number=1,
        content_pack_release_id="packrel_" + "4" * 32,
        workflow_id=workflow.workflow_id,
        workflow_definition_version=workflow.definition_version,
        metadata_sha256="sha256:" + "5" * 64,
        created_at=workflow_created_at + timedelta(seconds=3),
    )
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "item_id": revision.item_id,
        "item_revision_id": revision.item_revision_id,
        "revision_number": revision.revision_number,
        "content_pack": {"release_id": revision.content_pack_release_id},
        "workflow": {
            "workflow_id": workflow.workflow_id,
            "definition_key": workflow.definition_key,
            "definition_version": workflow.definition_version,
        },
        "components": [],
        "metadata": {"sha256": revision.metadata_sha256},
        "created_at": workflow_created_at.isoformat().replace("+00:00", "Z"),
    }
    return revision, workflow, manifest


def test_item_manifest_timestamp_is_pinned_to_producing_workflow() -> None:
    revision, workflow, manifest = _item_manifest_fixture()

    PostgresPdfLearningCompletionSource._validate_item_manifest(
        revision,
        workflow,
        (),
        manifest,
    )

    assert revision.created_at != workflow.created_at


def test_item_manifest_rejects_revision_timestamp_substitution() -> None:
    revision, workflow, manifest = _item_manifest_fixture()
    manifest["created_at"] = revision.created_at.isoformat().replace("+00:00", "Z")

    with pytest.raises(ValueError, match="canonical database rows"):
        PostgresPdfLearningCompletionSource._validate_item_manifest(
            revision,
            workflow,
            (),
            manifest,
        )


def test_graph_snapshot_uses_structure_artifact_member_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semantic_body = {
        "schema_version": "knowledge-graph-structure-manifest/5.0",
        "structure_manifest_id": "graphstructure_" + "1" * 32,
    }
    semantic_self_hash = content_sha256(semantic_body)
    full_member_hash = content_sha256({**semantic_body, "manifest_sha256": semantic_self_hash})
    assert full_member_hash != semantic_self_hash

    def pointer(
        *,
        revision_digit: str,
        hash_digit: str,
        logical_name: str,
        member_path: str,
        schema_ref: str,
        media_type: str,
    ) -> KnowledgeArtifactMemberPointer:
        return KnowledgeArtifactMemberPointer(
            artifact_id="artifact_" + revision_digit * 32,
            artifact_revision_id="rev_" + revision_digit * 32,
            sha256="sha256:" + hash_digit * 64,
            schema_ref=schema_ref,
            media_type=media_type,
            logical_name=logical_name,
            member_path=member_path,
        )

    projection_revision = "6"
    projection_schema = "eom://schemas/knowledge/knowledge-graph-projection/4.0"
    projections = KnowledgeGraphProjections(
        nodes=pointer(
            revision_digit=projection_revision,
            hash_digit="1",
            logical_name="nodes.jsonl",
            member_path="projections/nodes.jsonl",
            schema_ref=projection_schema,
            media_type="application/x-ndjson",
        ),
        edges=pointer(
            revision_digit=projection_revision,
            hash_digit="2",
            logical_name="edges.jsonl",
            member_path="projections/edges.jsonl",
            schema_ref=projection_schema,
            media_type="application/x-ndjson",
        ),
        curriculum_closure=pointer(
            revision_digit=projection_revision,
            hash_digit="3",
            logical_name="curriculum-closure.jsonl",
            member_path="projections/curriculum-closure.jsonl",
            schema_ref=projection_schema,
            media_type="application/x-ndjson",
        ),
        markdown=pointer(
            revision_digit=projection_revision,
            hash_digit="4",
            logical_name="graph.md",
            member_path="projections/graph.md",
            schema_ref="eom://schemas/knowledge/knowledge-graph-markdown/1.0",
            media_type="text/markdown",
        ),
        lexical_index=pointer(
            revision_digit=projection_revision,
            hash_digit="5",
            logical_name="lexical-index.json",
            member_path="projections/lexical-index.json",
            schema_ref=projection_schema,
            media_type="application/json",
        ),
    )
    structure_pointer = KnowledgeArtifactMemberPointer(
        artifact_id="artifact_" + "7" * 32,
        artifact_revision_id="rev_" + "7" * 32,
        sha256=full_member_hash,
        schema_ref="eom://schemas/knowledge/knowledge-graph-structure-manifest/5.0",
        media_type="application/json",
        logical_name="graph-structure-manifest.json",
        member_path="evidence/graph-structure-manifest.json",
    )
    graph_revision_id = "graphrev_" + "8" * 32
    graph_sha256 = "sha256:" + "9" * 64
    corpus_revision_id = "corpusrev_" + "a" * 32
    graph_id = "graph_" + "b" * 32
    created_at = datetime(2026, 9, 10, tzinfo=UTC)
    corpus = SimpleNamespace(
        corpus_id="corpus_" + "c" * 32,
        corpus_key="integrated-science-textbooks",
        lifecycle_state="ACTIVE",
        current_graph_snapshot_revision_id=graph_revision_id,
        current_corpus_revision_id=corpus_revision_id,
        graph_id=graph_id,
    )
    snapshot = SimpleNamespace(
        graph_snapshot_revision_id=graph_revision_id,
        corpus_revision_id=corpus_revision_id,
        graph_id=graph_id,
        state="PUBLISHED",
        snapshot_sha256=graph_sha256,
        ontology_version="education-knowledge-graph/1.1",
        manifest_artifact_id="artifact_" + "d" * 32,
        manifest_artifact_revision_id="rev_" + "d" * 32,
        manifest_sha256="sha256:" + "e" * 64,
        projection_artifact_id=projections.nodes.artifact_id,
        projection_artifact_revision_id=projections.nodes.artifact_revision_id,
        source_count=1,
        node_count=1,
        edge_count=0,
        anchor_count=1,
        created_at=created_at,
    )
    corpus_revision = SimpleNamespace(
        corpus_revision_id=corpus_revision_id,
        corpus_id=corpus.corpus_id,
        source_set_sha256="sha256:" + "f" * 64,
        state="PUBLISHED",
    )
    manifest = SimpleNamespace(
        graph_id=graph_id,
        graph_snapshot_revision_id=graph_revision_id,
        state="PUBLISHED",
        ontology_version="education-knowledge-graph/1.1",
        snapshot_sha256=graph_sha256,
        created_at=created_at,
        counts=SimpleNamespace(source_revisions=1, nodes=1, edges=0, anchors=1),
        projections=projections,
        structure_manifest=structure_pointer,
    )
    structure = SimpleNamespace(manifest_sha256=semantic_self_hash)
    documents = iter((manifest, structure))
    source = object.__new__(PostgresPdfLearningCompletionSource)
    monkeypatch.setattr(
        source,
        "_resolve_knowledge_member",
        MagicMock(return_value=SimpleNamespace(payload=b"{}")),
    )
    monkeypatch.setattr(
        source,
        "_typed_json",
        lambda *_args, **_kwargs: next(documents),
    )
    session = MagicMock(spec=Session)
    session.scalar.return_value = corpus
    session.get.side_effect = (snapshot, corpus_revision)
    session.scalars.return_value = ()
    request = cast(
        PdfLearningCompletionRequest,
        SimpleNamespace(
            graph_snapshot_revision_id=graph_revision_id,
            graph_snapshot_sha256=graph_sha256,
        ),
    )

    resolved = source._resolve_graph(session, request)

    assert resolved.graph.structure_manifest_sha256 == full_member_hash
    assert resolved.graph.structure_manifest_artifact.sha256 == full_member_hash


def test_pinned_reader_maps_workflow_support_extraction_result_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logical = SimpleNamespace(artifact_type="workflow_support")
    revision = SimpleNamespace(
        manifest={
            "artifact_type": "legacy-item-extraction-result",
            "primary_file": "result.json",
        }
    )
    session = MagicMock(spec=Session)
    session.get.side_effect = (logical, revision)
    resolver = MagicMock(return_value=SimpleNamespace(payload=b"result"))
    monkeypatch.setattr(
        completion_source_module,
        "resolve_pinned_artifact_member",
        resolver,
    )
    reader = _PinnedCatalogArtifactReader(session, MagicMock())

    payload = reader.read_member(
        artifact_id="artifact_" + "1" * 32,
        revision_id="rev_" + "2" * 32,
        member_path="result.json",
        sha256="sha256:" + "3" * 64,
        media_type="application/json",
        schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
        max_bytes=1024,
    )

    assert payload == b"result"
    assert resolver.call_args.kwargs["expected_artifact_types"] == {"workflow_support"}
    assert resolver.call_args.kwargs["expected_manifest_artifact_types"] == {
        "legacy-item-extraction-result"
    }
    assert resolver.call_args.kwargs["expected_primary_file"] == "result.json"


@pytest.mark.parametrize(
    ("member_path", "media_type", "expected_allow_empty"),
    [
        ("normalized/ambiguities.jsonl", "application/x-ndjson", True),
        ("normalized/unknown.jsonl", "application/x-ndjson", False),
        ("normalized/ambiguities.jsonl", "application/json", False),
        ("normalized/proposal-receipt.json", "application/json", False),
    ],
)
def test_pinned_reader_scopes_empty_proposal_members(
    monkeypatch: pytest.MonkeyPatch,
    member_path: str,
    media_type: str,
    expected_allow_empty: bool,
) -> None:
    logical = SimpleNamespace(artifact_type="workflow_support")
    revision = SimpleNamespace(
        manifest={
            "artifact_type": "knowledge-analysis-proposal",
            "primary_file": "normalized/proposal-receipt.json",
        }
    )
    session = MagicMock(spec=Session)
    session.get.side_effect = (logical, revision)
    resolver = MagicMock(return_value=SimpleNamespace(payload=b""))
    monkeypatch.setattr(
        completion_source_module,
        "resolve_pinned_artifact_member",
        resolver,
    )
    reader = _PinnedCatalogArtifactReader(session, MagicMock())

    reader.read_member(
        artifact_id="artifact_" + "1" * 32,
        revision_id="rev_" + "2" * 32,
        member_path=member_path,
        sha256="sha256:" + "3" * 64,
        media_type=media_type,
        schema_ref="eom://schemas/knowledge/ambiguity/3.0",
        max_bytes=1,
    )

    assert resolver.call_args.kwargs["allow_empty"] is expected_allow_empty


def test_valid_historical_analysis_request_is_typed_then_excluded() -> None:
    source = object.__new__(PostgresPdfLearningCompletionSource)
    request = _historical_v2_request().model_dump(mode="json")

    assert source._validated_historical_analysis_request(request) is True


def test_valid_v9_analysis_request_matches_its_persisted_run() -> None:
    request = _v9_request(_v9_source())
    request_source = request.source
    run = KnowledgeAnalysisRunRecord(
        analysis_run_id="analysisrun_" + "1" * 32,
        analysis_request_id=request.analysis_request_id,
        predecessor_analysis_run_id=request.predecessor_analysis_run_id,
        request_sha256=request.request_sha256,
        canonical_request=request.model_dump(mode="json"),
        source_kind=request_source.source_kind,
        source_revision_id=request_source.item_revision_id,
        item_id=request_source.item_id,
        item_revision_id=request_source.item_revision_id,
        source_artifact_id=request_source.artifact_member.artifact_id,
        source_artifact_revision_id=request_source.artifact_member.artifact_revision_id,
        source_sha256=request_source.artifact_member.sha256,
        preset_id=request.execution_preset_id,
        preset_revision_id=request.execution_preset_revision_id,
        risk_policy_revision_id=request.risk_policy_revision_id,
        risk_policy_sha256="sha256:" + "f" * 64,
        created_at=request.created_at,
    )

    assert "risk_policy_sha256" not in run.canonical_request
    assert PostgresPdfLearningCompletionSource._analysis_request_matches_run(run)


def test_malformed_historical_analysis_request_fails_closed() -> None:
    source = object.__new__(PostgresPdfLearningCompletionSource)
    request = _historical_v2_request().model_dump(mode="json")
    request["request_sha256"] = "sha256:" + "f" * 64

    with pytest.raises(PdfLearningCompletionError, match="does not validate exactly"):
        source._validated_historical_analysis_request(request)


def test_v9_analysis_history_scope_accepts_520_leaves_plus_six_predecessors() -> None:
    accepted = {f"analysisrun_{index:032x}" for index in range(520)}
    predecessors = {f"analysisrun_{10_000 + index:032x}" for index in range(6)}

    assert _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=accepted | predecessors,
    )


@pytest.mark.parametrize("predecessor_count", [0, 33])
def test_v9_analysis_history_scope_rejects_out_of_policy_predecessor_count(
    predecessor_count: int,
) -> None:
    accepted = {f"analysisrun_{index:032x}" for index in range(520)}
    predecessors = {f"analysisrun_{10_000 + index:032x}" for index in range(predecessor_count)}

    assert not _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=accepted | predecessors,
    )


def test_v9_analysis_history_scope_rejects_missing_or_extra_rows() -> None:
    accepted = {f"analysisrun_{index:032x}" for index in range(520)}
    predecessors = {f"analysisrun_{10_000 + index:032x}" for index in range(6)}
    exact = accepted | predecessors

    assert not _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=exact - {next(iter(predecessors))},
    )
    assert not _analysis_history_scope_is_exact(
        accepted_ids=accepted,
        predecessor_ids=predecessors,
        scoped_ids=exact | {"analysisrun_" + "f" * 32},
    )
