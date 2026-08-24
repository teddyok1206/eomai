from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_catalog_contracts import KnowledgeAnalysisRequestV2, KnowledgeAnalysisWorkerProposal
from eom_identifiers import content_sha256, sha256_file
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal


def _request() -> KnowledgeAnalysisRequestV2:
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-request/2.0",
        "predecessor_analysis_run_id": None,
        "analysis_request_id": "knowledgeanalysis_" + "1" * 32,
        "source": {
            "source_kind": "CONTENT_INTAKE_FILE",
            "source_class": "TEXTBOOK",
            "intake_batch_id": "intake_" + "2" * 32,
            "source_file_id": "sourcefile_" + "3" * 32,
            "lifecycle_state": "ELIGIBLE",
            "artifact_member": {
                "artifact_id": "artifact_" + "4" * 32,
                "artifact_revision_id": "rev_" + "5" * 32,
                "member_path": "source.pdf",
                "materialized_path": "source/source.pdf",
                "sha256": "sha256:" + "6" * 64,
                "bytes": 123,
                "schema_ref": None,
                "media_type": "application/pdf",
                "logical_name": "source.pdf",
            },
        },
        "execution_preset_id": "execpreset_" + "7" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "8" * 32,
        "execution_preset_sha256": "sha256:" + "9" * 64,
        "worker_proposal_schema_ref": (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
        ),
        "accepted_result_schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/2.0",
        "prior_graph_snapshot": None,
        "requested_outputs": [
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
        "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
        "risk_policy_revision_id": "analysisriskrev_" + "a" * 32,
        "created_at": "2026-08-23T00:00:00Z",
    }
    value["request_sha256"] = content_sha256(value)
    return KnowledgeAnalysisRequestV2.model_validate(value)


def _proposal() -> KnowledgeAnalysisWorkerProposal:
    return KnowledgeAnalysisWorkerProposal.model_validate(
        {
            "schema_version": "knowledge-analysis-worker-proposal/1.0",
            "analysis_request_id": "knowledgeanalysis_" + "1" * 32,
            "normalized_markdown": "# Source\n\nNormalized text.\n",
            "anchors": [
                {
                    "anchor_id": "anchor_page_1",
                    "artifact_revision_id": "rev_" + "5" * 32,
                    "member_path": "source.pdf",
                    "anchor_kind": "PAGE",
                    "locator": "page=1",
                    "excerpt_sha256": "sha256:" + "b" * 64,
                }
            ],
            "nodes": [
                {
                    "node_id": "knode_concept",
                    "node_type": "CONCEPT",
                    "stable_key": "concept.source",
                    "label": "source concept",
                    "anchor_ids": ["anchor_page_1"],
                }
            ],
            "edges": [],
            "claims": [],
            "component_observations": [],
            "unresolved_ambiguities": [],
            "general_knowledge_used": False,
            "completed_at": "2026-08-23T01:00:00Z",
        }
    )


def test_proposal_is_split_deterministically_without_large_database_result(tmp_path: Path) -> None:
    outputs = []
    for suffix in ("a", "b"):
        root = tmp_path / suffix
        root.mkdir()
        staged, receipt = stage_knowledge_analysis_proposal(
            proposal=_proposal(),
            request=_request(),
            job_id="job_" + "c" * 32,
            logical_artifact_id="artifact_" + "d" * 32,
            revision_id="rev_" + "e" * 32,
            staging=root,
        )
        outputs.append((staged, receipt))
        assert len(staged.files) == 8
        assert receipt.counts.nodes == 1
        assert receipt.counts.edges == 0
        assert "normalized_markdown" not in receipt.model_dump(mode="json")
        assert len(json.dumps(receipt.model_dump(mode="json"))) < 10_000
        assert staged.primary_hash == sha256_file(
            staged.directory / "normalized/proposal-receipt.json"
        )
        empty_jsonl = staged.directory / "normalized/edges.jsonl"
        assert empty_jsonl.read_bytes() == b""
    assert outputs[0][0].manifest_hash == outputs[1][0].manifest_hash
    assert outputs[0][1] == outputs[1][1]


def test_proposal_request_identity_mismatch_publishes_no_stage(tmp_path: Path) -> None:
    proposal = _proposal().model_copy(
        update={"analysis_request_id": "knowledgeanalysis_" + "f" * 32}
    )
    with pytest.raises(Exception, match="request identity"):
        stage_knowledge_analysis_proposal(
            proposal=proposal,
            request=_request(),
            job_id="job_" + "c" * 32,
            logical_artifact_id="artifact_" + "d" * 32,
            revision_id="rev_" + "e" * 32,
            staging=tmp_path,
        )
    assert not (tmp_path / "knowledge-proposal-artifact").exists()
