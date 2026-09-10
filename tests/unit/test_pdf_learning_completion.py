from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import eom_catalog_contracts.pdf_learning_completion as completion_contract
import pytest
from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    AssessmentOccurrenceItemBinding,
    AutomaticItemCurriculumAlignmentBinding,
    CurriculumUnitBindingV2,
    GraphPlacementDatabaseEvidence,
    GraphProjectionNodeEvidence,
    GraphSnapshotAnalysisDatabaseEvidence,
    GraphSnapshotDatabaseEvidence,
    ItemCompletion,
    KnowledgeAnalysisSourceArtifactMemberV2,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphCounts,
    KnowledgeGraphProjections,
    KnowledgeGraphSnapshotManifestV8,
    KnowledgeGraphStructureManifestV5,
    LegacyExtractionResultIdentityCollisionMember,
    PdfLearningCompletionReceipt,
    PdfLearningItemCompletionShard,
    derive_legacy_extraction_result_identity_collisions,
    verify_completion_shards,
    verify_graph_documents,
)
from eom_catalog_contracts.pdf_learning_completion import validate_payload as _validate_payload
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError


class ReceiptFixture(dict[str, object]):
    """JSON receipt plus separately published mutable shard fixtures."""

    def __init__(
        self,
        payload: dict[str, object],
        shard_documents: list[dict[str, object]],
    ) -> None:
        super().__init__(payload)
        self.shard_documents = shard_documents

    def __getitem__(self, key: str) -> object:
        if key == "items":
            return [
                item
                for shard in self.shard_documents
                for item in shard["items"]  # type: ignore[union-attr]
            ]
        return super().__getitem__(key)


def validate_payload(payload: dict[str, object]) -> PdfLearningCompletionReceipt:
    receipt = _validate_payload(payload)
    if not isinstance(payload, ReceiptFixture):
        raise TypeError("completion test fixture lost its shard documents")
    shards = tuple(
        PdfLearningItemCompletionShard.model_validate(document)
        for document in payload.shard_documents
    )
    verify_completion_shards(receipt, shards)
    return receipt


def _rehash_shards(payload: ReceiptFixture) -> None:
    flattened_items = payload["items"]
    assert isinstance(flattened_items, list)
    payload["coverage_accepted_map_sha256"] = content_sha256(
        [
            {
                "bundle_revision_id": item["bundle_revision_id"],
                "item_number": item["item_number"],
                "acceptance_id": item["acceptance_id"],
                "acceptance_sha256": item["acceptance_sha256"],
            }
            for item in flattened_items
        ]
    )
    payload["completion_map_sha256"] = content_sha256(flattened_items)
    pointers = payload["item_shards"]
    assert isinstance(pointers, list)
    for document, pointer in zip(payload.shard_documents, pointers, strict=True):
        assert isinstance(pointer, dict)
        document["shard_sha256"] = content_sha256(
            {key: value for key, value in document.items() if key != "shard_sha256"}
        )
        pointer["shard_sha256"] = document["shard_sha256"]
        artifact = pointer["artifact"]
        assert isinstance(artifact, dict)
        artifact["sha256"] = sha256_bytes(canonical_json_bytes(document))
    payload["receipt_sha256"] = content_sha256(
        {key: value for key, value in payload.items() if key != "receipt_sha256"}
    )


def _completion_items(payload: ReceiptFixture) -> tuple[ItemCompletion, ...]:
    return tuple(
        item
        for document in payload.shard_documents
        for item in PdfLearningItemCompletionShard.model_validate(document).items
    )


def _identity(prefix: str, number: int) -> str:
    return f"{prefix}_{number:032x}"


def _sha(number: int) -> str:
    return f"sha256:{number:064x}"


def _artifact(number: int, schema_ref: str, member_path: str) -> dict[str, object]:
    return {
        "artifact_id": _identity("artifact", number),
        "artifact_revision_id": _identity("rev", number),
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": "application/json",
        "sha256": _sha(number),
    }


def _knowledge_artifact(
    number: int,
    schema_ref: str,
    member_path: str,
    *,
    media_type: str = "application/json",
) -> dict[str, object]:
    return {
        **_artifact(number, schema_ref, member_path),
        "media_type": media_type,
        "logical_name": member_path.rsplit("/", 1)[-1],
    }


def _rehash_graph(graph: dict[str, object]) -> None:
    graph["placement_sha256"] = content_sha256(
        {
            key: value
            for key, value in graph.items()
            if key
            not in {
                "graph_id",
                "graph_snapshot_revision_id",
                "graph_snapshot_sha256",
                "placement_sha256",
                "membership_sha256",
            }
        }
    )
    graph["membership_sha256"] = content_sha256(
        {key: value for key, value in graph.items() if key != "membership_sha256"}
    )


def _receipt() -> ReceiptFixture:
    original_batch_id = _identity("legacybatch", 1)
    successor_batch_id = _identity("legacybatch", 2)
    inventory_id = _identity("legacyinventory", 1)
    graph_id = _identity("graph", 1)
    graph_snapshot_revision_id = _identity("graphrev", 1)
    graph_snapshot_sha256 = _sha(8)
    bundle_revisions = [_identity("assessbundlerev", index + 1) for index in range(50)]
    pdf_sources = [
        {
            "inventory_entry_key": _identity("legacyentry", index + 1),
            "content_sha256": _sha(1_000 + index),
            "media_type": "application/pdf",
            "bundle_revision_ids": [bundle_revisions[index]],
        }
        for index in range(50)
    ]

    next_number_by_bundle = {bundle: 1 for bundle in bundle_revisions}
    recovered_ordinals = {23: 0, 65: 1, 85: 2}
    work_units: list[dict[str, object]] = []
    for ordinal in range(108):
        bundle_index = ordinal % 50
        bundle_revision_id = bundle_revisions[bundle_index]
        width = 5 if ordinal < 103 else 1
        start = next_number_by_bundle[bundle_revision_id]
        numbers = list(range(start, start + width))
        next_number_by_bundle[bundle_revision_id] = start + width
        recovered = ordinal in recovered_ordinals
        effective_ordinal = recovered_ordinals[ordinal] if recovered else ordinal
        effective_number = 20_000 + effective_ordinal if recovered else 10_000 + ordinal
        work_units.append(
            {
                "original_work_unit_id": _identity("legacyworkunit", 10_000 + ordinal),
                "original_ordinal": ordinal,
                "effective_batch_id": successor_batch_id if recovered else original_batch_id,
                "effective_work_unit_id": _identity("legacyworkunit", effective_number),
                "effective_ordinal": effective_ordinal,
                "recovered": recovered,
                "bundle_id": _identity("assessbundle", bundle_index + 1),
                "bundle_revision_id": bundle_revision_id,
                "bundle_manifest_sha256": _sha(2_000 + bundle_index),
                "occurrence_id": _identity("occurrence", bundle_index + 1),
                "occurrence_revision_id": _identity("occurrev", bundle_index + 1),
                "occurrence_revision_sha256": _sha(3_000 + bundle_index),
                "expected_item_numbers": numbers,
                "expected_item_numbers_sha256": content_sha256({"item_numbers": numbers}),
                "extraction_request_id": _identity("itemextractreq", effective_number),
                "request_sha256": _sha(30_000 + effective_number),
                "extraction_result_id": _identity("itemextractresult", effective_number),
                "result_sha256": _sha(40_000 + effective_number),
                "result_artifact": _artifact(
                    50_000 + effective_number,
                    "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
                    "result.json",
                ),
                "extraction_receipt_sha256": _sha(60_000 + effective_number),
                "acceptance_id": _identity("itemacceptance", effective_number),
                "acceptance_sha256": _sha(70_000 + effective_number),
                "acceptance_artifact": _artifact(
                    80_000 + effective_number,
                    "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0",
                    "acceptance.json",
                ),
                "acceptance_state": "ACCEPTED",
                "coverage_state": "COMPLETE",
            }
        )

    items: list[dict[str, object]] = []
    serial = 1
    for unit in work_units:
        for item_number in unit["expected_item_numbers"]:
            item_id = _identity("item", serial)
            item_revision_id = _identity("itemrev", serial)
            item_origin_profile_id = _identity("originprofile", serial)
            item_origin_profile_sha256 = _sha(190_000 + serial)
            item_content_artifact = _artifact(
                120_000 + serial,
                "eom://schemas/item-registry/assessment-item-content-v1",
                "assessment-item-content.json",
            )
            accepted_result_artifact = _artifact(
                140_000 + serial,
                "eom://schemas/knowledge/knowledge-analysis-result/9.0",
                "evidence/accepted-result.json",
            )
            analysis = {
                "analysis_run_id": _identity("analysisrun", serial),
                "predecessor_analysis_run_id": None,
                "analysis_request_id": _identity("knowledgeanalysis", serial),
                "request_sha256": _sha(100_000 + serial),
                "submission_sha256": _sha(110_000 + serial),
                "state": "ACCEPTED",
                "successor_run_count": 0,
                "source_kind": "APPROVED_ITEM_REVISION",
                "source_revision_id": item_revision_id,
                "item_id": item_id,
                "item_revision_id": item_revision_id,
                "source_artifact": item_content_artifact,
                "preset_id": _identity("execpreset", 1),
                "preset_revision_id": _identity("execpresetrev", 1),
                "preset_sha256": _sha(130_001),
                "risk_policy_revision_id": _identity("analysisriskrev", 1),
                "risk_policy_sha256": _sha(130_002),
                "accepted_result_artifact": accepted_result_artifact,
                "accepted_result_sha256": accepted_result_artifact["sha256"],
            }
            graph = {
                "graph_id": graph_id,
                "graph_snapshot_revision_id": graph_snapshot_revision_id,
                "graph_snapshot_sha256": graph_snapshot_sha256,
                "analysis_run_id": analysis["analysis_run_id"],
                "item_id": item_id,
                "item_revision_id": item_revision_id,
                "item_origin_profile_id": item_origin_profile_id,
                "item_origin_profile_sha256": item_origin_profile_sha256,
                "extraction_acceptance_id": unit["acceptance_id"],
                "extraction_acceptance_sha256": unit["acceptance_sha256"],
                "assessment_source_bundle_id": unit["bundle_id"],
                "assessment_source_bundle_revision_id": unit["bundle_revision_id"],
                "assessment_source_bundle_sha256": unit["bundle_manifest_sha256"],
                "assessment_occurrence_id": unit["occurrence_id"],
                "assessment_occurrence_revision_id": unit["occurrence_revision_id"],
                "assessment_occurrence_revision_sha256": unit["occurrence_revision_sha256"],
                "occurrence_display_label": f"Fixture occurrence {serial}",
                "administration_year": 2025,
                "administration_month": 6,
                "target_school_level": "HIGH_SCHOOL",
                "target_grade": 1,
                "subject_key": "integrated-science",
                "item_number": item_number,
                "curriculum_unit_ids": [_identity("currunit", (serial % 20) + 1)],
                "placement_sha256": _sha(0),
                "membership_sha256": _sha(0),
            }
            _rehash_graph(graph)
            item_manifest_artifact = _artifact(
                180_000 + serial,
                "eom://schemas/item-registry/item-revision-manifest-v1",
                "item-revision-manifest.json",
            )
            rights = {
                "rights_policy_id": _identity("rightspolicy", 1),
                "rights_policy_revision_id": _identity("rightspolicyrev", 1),
                "rights_policy_sha256": _sha(195_001),
            }
            origin = {
                "item_origin_profile_id": item_origin_profile_id,
                "item_origin_profile_sha256": item_origin_profile_sha256,
                "profile_item_id": item_id,
                "profile_item_revision_id": item_revision_id,
                "profile_item_manifest_sha256": item_manifest_artifact["sha256"],
                "source_domain": "EXTERNAL_INSTITUTION",
                "creation_method": "UNKNOWN",
                "occurrence_relation_count": 1,
                "derivation_count": 1,
                "derivation_source_kind": "ASSESSMENT_SOURCE_BUNDLE_REVISION",
                "derivation_relation": "DIGITIZED_FROM",
                "assessment_source_bundle_id": unit["bundle_id"],
                "assessment_source_bundle_revision_id": unit["bundle_revision_id"],
                "assessment_source_bundle_sha256": unit["bundle_manifest_sha256"],
                "bundle_revision_state": "REVIEWED",
                "assessment_occurrence_id": unit["occurrence_id"],
                "assessment_occurrence_revision_id": unit["occurrence_revision_id"],
                "assessment_occurrence_revision_sha256": unit["occurrence_revision_sha256"],
                "occurrence_schema_version": "assessment-occurrence-revision/2.0",
                "occurrence_revision_state": "REVIEWED",
                "occurrence_lifecycle_state": "ACTIVE",
                "occurrence_current_revision_id": unit["occurrence_revision_id"],
                "profile_rights_policy": dict(rights),
                "occurrence_rights_policy": dict(rights),
                "bundle_rights_policy": dict(rights),
            }
            items.append(
                {
                    "bundle_revision_id": unit["bundle_revision_id"],
                    "item_number": item_number,
                    "effective_work_unit_id": unit["effective_work_unit_id"],
                    "acceptance_id": unit["acceptance_id"],
                    "acceptance_sha256": unit["acceptance_sha256"],
                    "item_proposal_id": _identity("itemproposal", serial),
                    "decision": "ACCEPT",
                    "promotion_registration_key": (
                        "legacy-item-promotion:"
                        + str(unit["acceptance_id"])
                        + ":"
                        + _identity("itemproposal", serial)
                    ),
                    "item_id": item_id,
                    "item_revision_id": item_revision_id,
                    "item_lifecycle_state": "ACTIVE",
                    "item_current_revision_id": item_revision_id,
                    "item_revision_state": "APPROVED",
                    "content_pack_release_id": _identity("packrel", 1),
                    "item_manifest_sha256": item_manifest_artifact["sha256"],
                    "item_manifest_artifact": item_manifest_artifact,
                    "item_content_artifact": item_content_artifact,
                    "item_origin_profile_id": item_origin_profile_id,
                    "item_origin_profile_sha256": item_origin_profile_sha256,
                    "origin": origin,
                    "analysis": analysis,
                    "graph_placement": graph,
                }
            )
            serial += 1
    items.sort(key=lambda item: (item["bundle_revision_id"], item["item_number"]))
    analysis_recoveries: list[dict[str, object]] = []
    for index, item in enumerate(items[:4], start=1):
        predecessor_run_id = _identity("analysisrun", 10_000 + index)
        analysis = item["analysis"]
        assert isinstance(analysis, dict)
        analysis["predecessor_analysis_run_id"] = predecessor_run_id
        lineage: dict[str, object] = {
            "item_id": item["item_id"],
            "item_revision_id": item["item_revision_id"],
            "predecessor_analysis_run_id": predecessor_run_id,
            "predecessor_analysis_request_id": _identity("knowledgeanalysis", 10_000 + index),
            "predecessor_request_sha256": _sha(200_000 + index),
            "predecessor_submission_sha256": _sha(210_000 + index),
            "predecessor_state": "FAILED",
            "predecessor_error_code": "WORKER_RESULT_INVALID",
            "predecessor_accepted_result_present": False,
            "predecessor_successor_count": 1,
            "successor_analysis_run_id": analysis["analysis_run_id"],
            "successor_analysis_request_id": analysis["analysis_request_id"],
            "successor_request_sha256": analysis["request_sha256"],
            "successor_state": "ACCEPTED",
            "lineage_sha256": _sha(0),
        }
        lineage["lineage_sha256"] = content_sha256(
            {key: value for key, value in lineage.items() if key != "lineage_sha256"}
        )
        analysis_recoveries.append(lineage)
    analysis_recoveries.sort(key=lambda value: value["predecessor_analysis_run_id"])

    payload: dict[str, object] = {
        "schema_version": "eom-pdf-learning-completion/1.0",
        "status": "COMPLETE",
        "source_release": {
            "git_commit": "1" * 40,
            "git_tree": "2" * 40,
            "git_archive_sha256": _sha(1),
        },
        "inventory": {
            "inventory_id": inventory_id,
            "inventory_sha256": _sha(2),
            "artifact": _artifact(
                1,
                "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0",
                "legacy-source-inventory.json",
            ),
        },
        "original_batch": {
            "role": "ORIGINAL_SCOPE",
            "extraction_batch_id": original_batch_id,
            "manifest_sha256": _sha(3),
            "manifest_artifact": _artifact(
                2,
                "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1",
                "batch.json",
            ),
            "inventory_id": inventory_id,
            "inventory_sha256": _sha(2),
            "state": "COMPLETED_WITH_GAPS",
            "total_work_unit_count": 108,
            "accepted_work_unit_count": 105,
            "failed_work_unit_count": 3,
            "other_work_unit_count": 0,
        },
        "successor_batch": {
            "role": "VALIDATION_SUCCESSOR",
            "extraction_batch_id": successor_batch_id,
            "manifest_sha256": _sha(4),
            "manifest_artifact": _artifact(
                3,
                "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1",
                "batch.json",
            ),
            "inventory_id": inventory_id,
            "inventory_sha256": _sha(2),
            "state": "SUCCEEDED",
            "total_work_unit_count": 3,
            "accepted_work_unit_count": 3,
            "failed_work_unit_count": 0,
            "other_work_unit_count": 0,
        },
        "recovery_authorization": {
            "recovery_sha256": _sha(5),
            "artifact": _artifact(
                4,
                "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0",
                "recovery.json",
            ),
        },
        "corpus_coverage": {
            "coverage_id": _identity("itemcoverage", 1),
            "coverage_sha256": _sha(6),
            "artifact": _artifact(
                5,
                "eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0",
                "coverage.json",
            ),
            "state": "COMPLETE",
            "expected_item_count": 520,
            "accepted_item_count": 520,
            "missing_item_count": 0,
            "conflict_item_count": 0,
        },
        "pdf_sources": pdf_sources,
        "effective_work_units": work_units,
        "graph_snapshot": {
            "corpus_id": _identity("corpus", 1),
            "corpus_key": "integrated-science-textbooks",
            "corpus_lifecycle_state": "ACTIVE",
            "corpus_revision_id": _identity("corpusrev", 1),
            "corpus_source_set_sha256": _sha(7),
            "graph_id": graph_id,
            "graph_snapshot_revision_id": graph_snapshot_revision_id,
            "snapshot_state": "PUBLISHED",
            "snapshot_sha256": graph_snapshot_sha256,
            "manifest_sha256": _sha(6),
            "manifest_artifact": _knowledge_artifact(
                6,
                "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/8.0",
                "projections/manifest.json",
            ),
            "projections": {
                "nodes": _knowledge_artifact(
                    7,
                    "eom://schemas/knowledge/knowledge-graph-projection/4.0",
                    "projections/nodes.jsonl",
                    media_type="application/x-ndjson",
                ),
                "edges": _knowledge_artifact(
                    7,
                    "eom://schemas/knowledge/knowledge-graph-projection/4.0",
                    "projections/edges.jsonl",
                    media_type="application/x-ndjson",
                ),
                "curriculum_closure": _knowledge_artifact(
                    7,
                    "eom://schemas/knowledge/knowledge-graph-projection/4.0",
                    "projections/curriculum-closure.jsonl",
                    media_type="application/x-ndjson",
                ),
                "markdown": _knowledge_artifact(
                    7,
                    "eom://schemas/knowledge/knowledge-graph-markdown/1.0",
                    "projections/graph.md",
                    media_type="text/markdown",
                ),
                "lexical_index": _knowledge_artifact(
                    7,
                    "eom://schemas/knowledge/knowledge-graph-projection/4.0",
                    "projections/lexical-index.json",
                ),
            },
            "structure_manifest_sha256": _sha(9),
            "structure_manifest_artifact": _knowledge_artifact(
                9,
                "eom://schemas/knowledge/knowledge-graph-structure-manifest/5.0",
                "evidence/graph-structure-manifest.json",
            ),
            "snapshot_created_at": "2026-09-08T00:00:00Z",
            "observed_as_current": True,
        },
        "analysis_recoveries": analysis_recoveries,
        "quiescence": {
            "automation_mode": "DISABLED",
            "volatile_auto_overlay_present": False,
            "deployment_hold": False,
            "missing_keys": 0,
            "conflict_keys": 0,
            "duplicate_expected_keys": 0,
            "extra_effective_keys": 0,
            "unpromoted_items": 0,
            "active_analysis_leaves": 0,
            "failed_analysis_leaves": 0,
            "duplicate_analysis_leaves": 0,
            "graph_missing_items": 0,
            "graph_duplicate_items": 0,
            "source_pending_work_units": 0,
            "promotion_pending_items": 0,
            "graph_pending_items": 0,
            "unaccounted_terminal_work_units": 0,
            "active_platform_jobs": 0,
            "active_workflows": 0,
            "active_workflow_commands": 0,
            "active_analysis_runs": 0,
            "slot05_held_leases": 0,
            "slot06_held_leases": 0,
        },
        "pdf_sources_sha256": content_sha256(pdf_sources),
        "expected_item_keys_sha256": content_sha256(
            [
                {
                    "bundle_revision_id": item["bundle_revision_id"],
                    "item_number": item["item_number"],
                }
                for item in items
            ]
        ),
        "coverage_accepted_map_sha256": content_sha256(
            [
                {
                    "bundle_revision_id": item["bundle_revision_id"],
                    "item_number": item["item_number"],
                    "acceptance_id": item["acceptance_id"],
                    "acceptance_sha256": item["acceptance_sha256"],
                }
                for item in items
            ]
        ),
        "analysis_recovery_set_sha256": content_sha256(analysis_recoveries),
        "completion_map_sha256": content_sha256(items),
        "observed_at_utc": "2026-09-09T00:00:00Z",
        "receipt_sha256": _sha(0),
    }
    shard_documents: list[dict[str, object]] = []
    shard_pointers: list[dict[str, object]] = []
    for shard_index, offset in enumerate(range(0, len(items), 64)):
        shard_items = items[offset : offset + 64]
        first = {
            "bundle_revision_id": shard_items[0]["bundle_revision_id"],
            "item_number": shard_items[0]["item_number"],
        }
        last = {
            "bundle_revision_id": shard_items[-1]["bundle_revision_id"],
            "item_number": shard_items[-1]["item_number"],
        }
        shard: dict[str, object] = {
            "schema_version": "eom-pdf-learning-item-completion-shard/1.0",
            "shard_index": shard_index,
            "first_key": first,
            "last_key": last,
            "item_count": len(shard_items),
            "items": shard_items,
            "shard_sha256": _sha(0),
        }
        shard["shard_sha256"] = content_sha256(
            {key: value for key, value in shard.items() if key != "shard_sha256"}
        )
        shard_documents.append(shard)
        shard_payload = canonical_json_bytes(shard)
        shard_pointers.append(
            {
                "shard_index": shard_index,
                "first_key": first,
                "last_key": last,
                "item_count": len(shard_items),
                "shard_sha256": shard["shard_sha256"],
                "artifact": _artifact(
                    300_000 + shard_index,
                    ("eom://schemas/legacy-assessment/pdf-learning-item-completion-shard/1.0"),
                    f"item-completions/shard-{shard_index:02d}.json",
                )
                | {"sha256": sha256_bytes(shard_payload)},
            }
        )
    payload["item_count"] = len(items)
    payload["item_shards"] = shard_pointers
    payload["receipt_sha256"] = content_sha256(
        {key: value for key, value in payload.items() if key != "receipt_sha256"}
    )
    return ReceiptFixture(payload, shard_documents)


def _set_analysis_recovery_count(payload: ReceiptFixture, count: int) -> None:
    items = payload["items"]
    assert isinstance(items, list)
    for item in items:
        analysis = item["analysis"]
        assert isinstance(analysis, dict)
        analysis["predecessor_analysis_run_id"] = None
    recoveries: list[dict[str, object]] = []
    for index, item in enumerate(items[:count], start=1):
        analysis = item["analysis"]
        assert isinstance(analysis, dict)
        predecessor_run_id = _identity("analysisrun", 10_000 + index)
        analysis["predecessor_analysis_run_id"] = predecessor_run_id
        lineage: dict[str, object] = {
            "item_id": item["item_id"],
            "item_revision_id": item["item_revision_id"],
            "predecessor_analysis_run_id": predecessor_run_id,
            "predecessor_analysis_request_id": _identity("knowledgeanalysis", 10_000 + index),
            "predecessor_request_sha256": _sha(200_000 + index),
            "predecessor_submission_sha256": _sha(210_000 + index),
            "predecessor_state": "FAILED",
            "predecessor_error_code": "WORKER_RESULT_INVALID",
            "predecessor_accepted_result_present": False,
            "predecessor_successor_count": 1,
            "successor_analysis_run_id": analysis["analysis_run_id"],
            "successor_analysis_request_id": analysis["analysis_request_id"],
            "successor_request_sha256": analysis["request_sha256"],
            "successor_state": "ACCEPTED",
            "lineage_sha256": _sha(0),
        }
        lineage["lineage_sha256"] = content_sha256(
            {key: value for key, value in lineage.items() if key != "lineage_sha256"}
        )
        recoveries.append(lineage)
    recoveries.sort(key=lambda value: value["predecessor_analysis_run_id"])
    payload["analysis_recoveries"] = recoveries
    payload["analysis_recovery_set_sha256"] = content_sha256(recoveries)


def _v12_receipt(recovery_count: int = 6) -> ReceiptFixture:
    payload = _receipt()
    work_units = payload["effective_work_units"]
    assert isinstance(work_units, list)
    for first_index, stop_index in ((0, 5), (5, 8), (8, 10)):
        first = work_units[first_index]
        assert isinstance(first, dict)
        for index in range(first_index + 1, stop_index):
            member = work_units[index]
            assert isinstance(member, dict)
            member["extraction_result_id"] = first["extraction_result_id"]
    evidence = derive_legacy_extraction_result_identity_collisions(
        LegacyExtractionResultIdentityCollisionMember(
            effective_batch_id=unit["effective_batch_id"],
            effective_work_unit_id=unit["effective_work_unit_id"],
            effective_ordinal=unit["effective_ordinal"],
            extraction_request_id=unit["extraction_request_id"],
            request_sha256=unit["request_sha256"],
            extraction_result_id=unit["extraction_result_id"],
            result_artifact=unit["result_artifact"],
            result_sha256=unit["result_sha256"],
            extraction_receipt_sha256=unit["extraction_receipt_sha256"],
            acceptance_id=unit["acceptance_id"],
            acceptance_sha256=unit["acceptance_sha256"],
            acceptance_artifact=unit["acceptance_artifact"],
        )
        for unit in work_units
        if isinstance(unit, dict)
    )
    assert evidence is not None
    payload["schema_version"] = "eom-pdf-learning-completion/1.2"
    payload["historical_result_identity_collisions"] = evidence.model_dump(mode="json")
    _set_analysis_recovery_count(payload, recovery_count)
    _rehash_shards(payload)
    return payload


def _graph_evidence(
    payload: dict[str, object],
    *,
    structure_item_id_drift: bool = False,
    structure_alias_extra: bool = False,
    manifest_source_conflict: bool = False,
) -> tuple[
    KnowledgeGraphSnapshotManifestV8,
    KnowledgeGraphStructureManifestV5,
    dict[str, bytes],
    GraphSnapshotDatabaseEvidence,
    tuple[GraphPlacementDatabaseEvidence, ...],
    tuple[GraphSnapshotAnalysisDatabaseEvidence, ...],
]:
    items = payload["items"]
    graph_snapshot = payload["graph_snapshot"]
    assert isinstance(items, list)
    assert isinstance(graph_snapshot, dict)

    structure_placements: list[AssessmentOccurrenceItemBinding] = []
    automatic_alignments: list[AutomaticItemCurriculumAlignmentBinding] = []
    projection_nodes_by_stable_key: dict[str, GraphProjectionNodeEvidence] = {}
    placement_rows: list[GraphPlacementDatabaseEvidence] = []
    analysis_rows: list[GraphSnapshotAnalysisDatabaseEvidence] = []
    source_revisions: list[ApprovedItemKnowledgeSourceV2] = []
    analysis_results: list[KnowledgeArtifactMemberPointer] = []
    for serial, item in enumerate(items, start=1):
        assert isinstance(item, dict)
        placement = item["graph_placement"]
        analysis = item["analysis"]
        assert isinstance(placement, dict)
        assert isinstance(analysis, dict)
        structure_placement_document = {
            key: value
            for key, value in placement.items()
            if key
            not in {
                "graph_id",
                "graph_snapshot_revision_id",
                "graph_snapshot_sha256",
                "membership_sha256",
            }
        }
        structure_placements.append(
            AssessmentOccurrenceItemBinding.model_validate(structure_placement_document)
        )

        occurrence_revision_id = str(placement["assessment_occurrence_revision_id"])
        item_revision_id = str(placement["item_revision_id"])
        item_number = int(placement["item_number"])
        stable_keys = (
            "assessment-item-occurrence:" + occurrence_revision_id + f":{item_number}",
            "assessment-occurrence-revision:" + occurrence_revision_id,
            "item-revision:" + item_revision_id,
        )
        node_numbers = (
            300_000 + serial,
            400_000 + int(occurrence_revision_id[-8:], 16),
            500_000 + serial,
        )
        node_values: list[GraphProjectionNodeEvidence] = []
        for stable_key, node_number in zip(stable_keys, node_numbers, strict=True):
            existing = projection_nodes_by_stable_key.get(stable_key)
            if existing is None:
                existing = GraphProjectionNodeEvidence(
                    node_id=_identity("knode", node_number), stable_key=stable_key
                )
                projection_nodes_by_stable_key[stable_key] = existing
            node_values.append(existing)

        placement_rows.append(
            GraphPlacementDatabaseEvidence(
                graph_snapshot_revision_id=str(placement["graph_snapshot_revision_id"]),
                placement_node_id=node_values[0].node_id,
                occurrence_node_id=node_values[1].node_id,
                item_node_id=node_values[2].node_id,
                analysis_run_id=str(placement["analysis_run_id"]),
                assessment_occurrence_id=str(placement["assessment_occurrence_id"]),
                assessment_occurrence_revision_id=occurrence_revision_id,
                assessment_occurrence_revision_sha256=str(
                    placement["assessment_occurrence_revision_sha256"]
                ),
                occurrence_display_label=str(placement["occurrence_display_label"]),
                administration_year=int(placement["administration_year"]),
                administration_month=int(placement["administration_month"]),
                target_school_level=str(placement["target_school_level"]),
                target_grade=int(placement["target_grade"]),
                subject_key=str(placement["subject_key"]),
                item_number=item_number,
                item_id=str(placement["item_id"]),
                item_revision_id=item_revision_id,
                item_origin_profile_id=str(placement["item_origin_profile_id"]),
                extraction_acceptance_id=str(placement["extraction_acceptance_id"]),
                assessment_source_bundle_revision_id=str(
                    placement["assessment_source_bundle_revision_id"]
                ),
                placement_sha256=str(placement["placement_sha256"]),
            )
        )
        source_artifact = analysis["source_artifact"]
        result_artifact = analysis["accepted_result_artifact"]
        assert isinstance(source_artifact, dict)
        assert isinstance(result_artifact, dict)
        source_revisions.append(
            ApprovedItemKnowledgeSourceV2(
                source_kind="APPROVED_ITEM_REVISION",
                source_class="PAST_EXAM",
                item_id=str(item["item_id"]),
                item_revision_id=item_revision_id,
                lifecycle_state="APPROVED",
                artifact_member=KnowledgeAnalysisSourceArtifactMemberV2(
                    **source_artifact,
                    materialized_path="source/item-content.json",
                    bytes=100,
                    logical_name="item-content.json",
                ),
            )
        )
        accepted_result = KnowledgeArtifactMemberPointer.model_validate(
            {**result_artifact, "logical_name": "accepted-result.json"}
        )
        analysis_results.append(accepted_result)
        alignment_document: dict[str, object] = {
            "alignment_mode": "AUTO_POLICY",
            "analysis_run_id": str(analysis["analysis_run_id"]),
            "item_id": str(item["item_id"]),
            "item_revision_id": item_revision_id,
            "accepted_result": accepted_result.model_dump(mode="json"),
            "prior_graph_snapshot_revision_id": _identity("graphrev", 999),
            "evidence_bundle_id": _identity("evidence", serial),
            "evidence_bundle_revision_id": _identity("evidencerev", serial),
            "retrieval_request_id": _identity("retrieval", serial),
            "retrieval_request_sha256": _sha(600_000 + serial),
            "evidence_manifest": _knowledge_artifact(
                700_000 + serial,
                "eom://schemas/knowledge/evidence-bundle-manifest/4.0",
                "evidence/manifest.json",
            ),
            "evidence_node_ids": [_identity("knode", 800_000 + serial)],
            "curriculum_unit_ids": list(placement["curriculum_unit_ids"]),
            "alignment_policy_version": "integrated-science-auto-alignment/1.1",
            "alignment_policy_sha256": _sha(900_000),
            "requested_by_operator_id": _identity("operator", 1),
            "aligned_at": "2026-09-08T00:00:00Z",
            "alignment_sha256": _sha(0),
        }
        alignment_document["alignment_sha256"] = content_sha256(
            {key: value for key, value in alignment_document.items() if key != "alignment_sha256"}
        )
        automatic_alignments.append(
            AutomaticItemCurriculumAlignmentBinding.model_validate(alignment_document)
        )
        analysis_rows.append(
            GraphSnapshotAnalysisDatabaseEvidence(
                graph_snapshot_revision_id=str(placement["graph_snapshot_revision_id"]),
                analysis_run_id=str(analysis["analysis_run_id"]),
                source_kind="APPROVED_ITEM_REVISION",
                source_revision_id=item_revision_id,
                source_artifact_id=str(source_artifact["artifact_id"]),
                source_artifact_revision_id=str(source_artifact["artifact_revision_id"]),
                source_sha256=str(source_artifact["sha256"]),
                accepted_result_artifact_id=str(result_artifact["artifact_id"]),
                accepted_result_artifact_revision_id=str(result_artifact["artifact_revision_id"]),
                accepted_result_sha256=str(result_artifact["sha256"]),
            )
        )

    major_id = _identity("currunit", 10_001)
    middle_id = _identity("currunit", 10_002)
    curriculum_units = [
        CurriculumUnitBindingV2(
            framework_revision_id=_identity("curriculumrev", 1),
            curriculum_unit_id=major_id,
            node_stable_key="curriculum.major",
            parent_unit_id=None,
            unit_level="MAJOR",
            ordinal=1,
            unit_key="a-major",
            unit_code="A",
            label="Major",
        ),
        CurriculumUnitBindingV2(
            framework_revision_id=_identity("curriculumrev", 1),
            curriculum_unit_id=middle_id,
            node_stable_key="curriculum.major.middle",
            parent_unit_id=major_id,
            unit_level="MIDDLE",
            ordinal=1,
            unit_key="b-middle",
            unit_code="B",
            label="Middle",
        ),
    ]
    curriculum_units.extend(
        CurriculumUnitBindingV2(
            framework_revision_id=_identity("curriculumrev", 1),
            curriculum_unit_id=_identity("currunit", number),
            node_stable_key=f"curriculum.major.middle.minor-{number:02d}",
            parent_unit_id=middle_id,
            unit_level="MINOR",
            ordinal=number,
            unit_key=f"minor-{number:02d}",
            unit_code=f"M{number:02d}",
            label=f"Minor {number}",
        )
        for number in range(1, 21)
    )
    structure_manifest = KnowledgeGraphStructureManifestV5.model_construct(
        schema_version="knowledge-graph-structure-manifest/5.0",
        structure_manifest_id=_identity("graphstructure", 1),
        framework_key="integrated-science",
        framework_revision_id=_identity("curriculumrev", 1),
        outline_key="stage-c-fixture",
        outline_revision="1.0",
        outline_sha256=_sha(910_000),
        source_analysis_run_ids=tuple(
            sorted(str(item["analysis"]["analysis_run_id"]) for item in items)
        ),
        curriculum_units=tuple(curriculum_units),
        analysis_curriculum_bindings=(),
        item_elements=(),
        reviewed_by_operator_id=_identity("operator", 1),
        created_at=datetime(2026, 9, 8, tzinfo=UTC),
        approved_item_curriculum_bindings=(),
        automatic_item_curriculum_bindings=tuple(
            sorted(automatic_alignments, key=lambda value: value.analysis_run_id)
        ),
        assessment_item_occurrences=tuple(
            sorted(
                structure_placements,
                key=lambda value: (
                    value.administration_year,
                    value.administration_month,
                    value.target_school_level,
                    value.target_grade,
                    value.assessment_occurrence_revision_id,
                    value.item_number,
                    value.item_revision_id,
                ),
            )
        ),
        manifest_sha256=_sha(0),
    )
    if structure_item_id_drift:
        first = structure_manifest.assessment_item_occurrences[0]
        changed = first.model_copy(update={"item_id": _identity("item", 999_999)})
        changed = changed.model_copy(
            update={
                "placement_sha256": content_sha256(
                    changed.model_dump(mode="json", exclude={"placement_sha256"})
                )
            }
        )
        structure_manifest = structure_manifest.model_copy(
            update={
                "assessment_item_occurrences": (
                    changed,
                    *structure_manifest.assessment_item_occurrences[1:],
                )
            }
        )
    if structure_alias_extra:
        alias = structure_manifest.assessment_item_occurrences[0].model_copy(
            update={
                "assessment_source_bundle_revision_id": _identity("assessbundlerev", 999_999),
                "item_number": 199,
            }
        )
        alias = alias.model_copy(
            update={
                "placement_sha256": content_sha256(
                    alias.model_dump(mode="json", exclude={"placement_sha256"})
                )
            }
        )
        structure_manifest = structure_manifest.model_copy(
            update={
                "assessment_item_occurrences": (
                    *structure_manifest.assessment_item_occurrences,
                    alias,
                )
            }
        )
    structure_manifest = structure_manifest.model_copy(
        update={
            "manifest_sha256": content_sha256(
                structure_manifest.model_dump(mode="json", exclude={"manifest_sha256"})
            )
        }
    )
    structure_member_sha256 = sha256_bytes(canonical_json_bytes(structure_manifest))
    graph_snapshot["structure_manifest_sha256"] = structure_member_sha256
    structure_artifact = graph_snapshot["structure_manifest_artifact"]
    assert isinstance(structure_artifact, dict)
    structure_artifact["sha256"] = structure_member_sha256

    nodes_payload = b"".join(
        canonical_json_bytes(value.model_dump(mode="json")) + b"\n"
        for value in projection_nodes_by_stable_key.values()
    )
    projection_payloads = {
        "projections/nodes.jsonl": nodes_payload,
        "projections/edges.jsonl": b"",
        "projections/curriculum-closure.jsonl": b"",
        "projections/graph.md": b"# Stage C fixture\n",
        "projections/lexical-index.json": b"{}",
    }
    projections = graph_snapshot["projections"]
    assert isinstance(projections, dict)
    projection_name_by_path = {
        "projections/nodes.jsonl": "nodes",
        "projections/edges.jsonl": "edges",
        "projections/curriculum-closure.jsonl": "curriculum_closure",
        "projections/graph.md": "markdown",
        "projections/lexical-index.json": "lexical_index",
    }
    descriptors = []
    for path, raw in sorted(projection_payloads.items()):
        pointer = projections[projection_name_by_path[path]]
        assert isinstance(pointer, dict)
        pointer["sha256"] = sha256_bytes(raw)
        descriptors.append({"member_path": path, "sha256": pointer["sha256"], "bytes": len(raw)})
    snapshot_sha256 = content_sha256(
        {
            "analysis_run_ids": list(structure_manifest.source_analysis_run_ids),
            "members": descriptors,
        }
    )
    graph_snapshot["snapshot_sha256"] = snapshot_sha256
    for item in items:
        graph = item["graph_placement"]
        assert isinstance(graph, dict)
        graph["graph_snapshot_sha256"] = snapshot_sha256
        _rehash_graph(graph)
    if manifest_source_conflict:
        first = source_revisions[0]
        source_revisions.append(
            first.model_copy(
                update={
                    "artifact_member": first.artifact_member.model_copy(
                        update={
                            "artifact_id": _identity("artifact", 999_997),
                            "artifact_revision_id": _identity("rev", 999_997),
                            "sha256": _sha(999_997),
                        }
                    )
                }
            )
        )
    projection_contract = KnowledgeGraphProjections.model_validate(projections)
    snapshot_manifest = KnowledgeGraphSnapshotManifestV8.model_construct(
        schema_version="knowledge-graph-snapshot-manifest/8.0",
        graph_id=str(graph_snapshot["graph_id"]),
        graph_snapshot_revision_id=str(graph_snapshot["graph_snapshot_revision_id"]),
        revision_number=1,
        previous_graph_snapshot_revision_id=None,
        state="PUBLISHED",
        ontology_version="education-knowledge-graph/1.1",
        publisher_version="1.0.0",
        source_revisions=tuple(source_revisions),
        analysis_results=tuple(analysis_results),
        projections=projection_contract,
        counts=KnowledgeGraphCounts(
            source_revisions=len(source_revisions),
            nodes=len(projection_nodes_by_stable_key),
            edges=0,
            anchors=len(items),
        ),
        snapshot_sha256=snapshot_sha256,
        created_at=datetime(2026, 9, 8, tzinfo=UTC),
        structure_manifest=KnowledgeArtifactMemberPointer.model_validate(structure_artifact),
    )
    manifest_member_sha256 = sha256_bytes(canonical_json_bytes(snapshot_manifest))
    graph_snapshot["manifest_sha256"] = manifest_member_sha256
    manifest_artifact = graph_snapshot["manifest_artifact"]
    assert isinstance(manifest_artifact, dict)
    manifest_artifact["sha256"] = manifest_member_sha256
    assert isinstance(payload, ReceiptFixture)
    _rehash_shards(payload)

    snapshot_database = GraphSnapshotDatabaseEvidence(
        corpus_id=str(graph_snapshot["corpus_id"]),
        corpus_key=str(graph_snapshot["corpus_key"]),
        corpus_lifecycle_state="ACTIVE",
        current_corpus_revision_id=str(graph_snapshot["corpus_revision_id"]),
        current_graph_snapshot_revision_id=str(graph_snapshot["graph_snapshot_revision_id"]),
        corpus_revision_id=str(graph_snapshot["corpus_revision_id"]),
        corpus_source_set_sha256=str(graph_snapshot["corpus_source_set_sha256"]),
        graph_id=str(graph_snapshot["graph_id"]),
        graph_snapshot_revision_id=str(graph_snapshot["graph_snapshot_revision_id"]),
        snapshot_state="PUBLISHED",
        ontology_version="education-knowledge-graph/1.1",
        manifest_artifact_id=str(manifest_artifact["artifact_id"]),
        manifest_artifact_revision_id=str(manifest_artifact["artifact_revision_id"]),
        manifest_sha256=manifest_member_sha256,
        projection_artifact_id=str(graph_snapshot["projections"]["nodes"]["artifact_id"]),
        projection_artifact_revision_id=str(
            graph_snapshot["projections"]["nodes"]["artifact_revision_id"]
        ),
        snapshot_sha256=str(graph_snapshot["snapshot_sha256"]),
        created_at=str(graph_snapshot["snapshot_created_at"]),
    )
    return (
        snapshot_manifest,
        structure_manifest,
        projection_payloads,
        snapshot_database,
        tuple(placement_rows),
        tuple(analysis_rows),
    )


def test_valid_exact_520_bijection_passes_schema_pydantic_and_self_hash() -> None:
    receipt = validate_payload(_receipt())
    assert len(receipt.pdf_sources) == 50
    assert len(receipt.effective_work_units) == 108
    assert receipt.item_count == 520


def test_v12_accepts_six_exact_hash_bound_analysis_recoveries() -> None:
    payload = _v12_receipt()

    receipt = validate_payload(payload)

    assert receipt.schema_version == "eom-pdf-learning-completion/1.2"
    assert len(receipt.analysis_recoveries) == 6
    assert receipt.analysis_recovery_set_sha256 == content_sha256(
        [value.model_dump(mode="json") for value in receipt.analysis_recoveries]
    )


@pytest.mark.parametrize("count", [0, 33])
def test_v12_rejects_recovery_counts_outside_runtime_bound(count: int) -> None:
    payload = _v12_receipt(count)

    with pytest.raises(JsonSchemaValidationError):
        _validate_payload(payload)
    with pytest.raises(PydanticValidationError):
        PdfLearningCompletionReceipt.model_validate(payload)


@pytest.mark.parametrize(
    "schema_version",
    ["eom-pdf-learning-completion/1.0", "eom-pdf-learning-completion/1.1"],
)
def test_legacy_receipt_versions_keep_exactly_four_recoveries(schema_version: str) -> None:
    payload = _v12_receipt()
    payload["schema_version"] = schema_version
    if schema_version.endswith("/1.0"):
        del payload["historical_result_identity_collisions"]
    _rehash_shards(payload)

    with pytest.raises(JsonSchemaValidationError):
        _validate_payload(payload)
    with pytest.raises(PydanticValidationError, match="exactly four"):
        PdfLearningCompletionReceipt.model_validate(payload)


def test_exact_historical_result_identity_collision_attestation_is_preserved() -> None:
    payload = _receipt()
    work_units = payload["effective_work_units"]
    assert isinstance(work_units, list)
    collision_ranges = ((0, 5), (5, 8), (8, 10))
    for first_index, stop_index in collision_ranges:
        first = work_units[first_index]
        assert isinstance(first, dict)
        for index in range(first_index + 1, stop_index):
            member = work_units[index]
            assert isinstance(member, dict)
            member["extraction_result_id"] = first["extraction_result_id"]
    evidence = derive_legacy_extraction_result_identity_collisions(
        LegacyExtractionResultIdentityCollisionMember(
            effective_batch_id=unit["effective_batch_id"],
            effective_work_unit_id=unit["effective_work_unit_id"],
            effective_ordinal=unit["effective_ordinal"],
            extraction_request_id=unit["extraction_request_id"],
            request_sha256=unit["request_sha256"],
            extraction_result_id=unit["extraction_result_id"],
            result_artifact=unit["result_artifact"],
            result_sha256=unit["result_sha256"],
            extraction_receipt_sha256=unit["extraction_receipt_sha256"],
            acceptance_id=unit["acceptance_id"],
            acceptance_sha256=unit["acceptance_sha256"],
            acceptance_artifact=unit["acceptance_artifact"],
        )
        for unit in work_units
        if isinstance(unit, dict)
    )
    assert evidence is not None
    assert (
        evidence.collision_group_count,
        evidence.collision_membership_count,
        evidence.noncanonical_membership_count,
    ) == (3, 10, 7)
    payload["schema_version"] = "eom-pdf-learning-completion/1.1"
    payload["historical_result_identity_collisions"] = evidence.model_dump(mode="json")
    _rehash_shards(payload)

    receipt = validate_payload(payload)

    assert receipt.historical_result_identity_collisions == evidence

    del payload["historical_result_identity_collisions"]
    _rehash_shards(payload)
    with pytest.raises(PydanticValidationError, match="version and collision evidence differ"):
        PdfLearningCompletionReceipt.model_validate(payload)


def test_v1_receipt_retains_strict_result_identity_uniqueness() -> None:
    payload = _receipt()
    work_units = payload["effective_work_units"]
    assert isinstance(work_units, list)
    first = work_units[0]
    second = work_units[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    second["extraction_result_id"] = first["extraction_result_id"]
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="evidence pointers must be unique"):
        PdfLearningCompletionReceipt.model_validate(payload)


def test_unbounded_historical_result_identity_collision_attestation_fails() -> None:
    payload = _receipt()
    work_units = payload["effective_work_units"]
    assert isinstance(work_units, list)
    first = work_units[0]
    second = work_units[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    second["extraction_result_id"] = first["extraction_result_id"]
    evidence = derive_legacy_extraction_result_identity_collisions(
        LegacyExtractionResultIdentityCollisionMember(
            effective_batch_id=unit["effective_batch_id"],
            effective_work_unit_id=unit["effective_work_unit_id"],
            effective_ordinal=unit["effective_ordinal"],
            extraction_request_id=unit["extraction_request_id"],
            request_sha256=unit["request_sha256"],
            extraction_result_id=unit["extraction_result_id"],
            result_artifact=unit["result_artifact"],
            result_sha256=unit["result_sha256"],
            extraction_receipt_sha256=unit["extraction_receipt_sha256"],
            acceptance_id=unit["acceptance_id"],
            acceptance_sha256=unit["acceptance_sha256"],
            acceptance_artifact=unit["acceptance_artifact"],
        )
        for unit in work_units
        if isinstance(unit, dict)
    )
    assert evidence is not None
    payload["schema_version"] = "eom-pdf-learning-completion/1.1"
    payload["historical_result_identity_collisions"] = evidence.model_dump(mode="json")
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="collision cardinality differs"):
        PdfLearningCompletionReceipt.model_validate(payload)


def test_missing_item_fails_closed() -> None:
    payload = _receipt()
    last_items = payload.shard_documents[-1]["items"]
    assert isinstance(last_items, list)
    last_items.pop()
    with pytest.raises(PydanticValidationError, match="boundaries differ"):
        validate_payload(payload)


def test_duplicate_expected_key_fails_closed() -> None:
    payload = _receipt()
    payload["effective_work_units"][1]["bundle_revision_id"] = payload["effective_work_units"][0][
        "bundle_revision_id"
    ]
    payload["effective_work_units"][1]["expected_item_numbers"] = payload["effective_work_units"][
        0
    ]["expected_item_numbers"]
    payload["effective_work_units"][1]["expected_item_numbers_sha256"] = payload[
        "effective_work_units"
    ][0]["expected_item_numbers_sha256"]
    with pytest.raises(PydanticValidationError, match="520 unique expected keys"):
        validate_payload(payload)


def test_mixed_batch_effective_unit_fails_closed() -> None:
    payload = _receipt()
    payload["effective_work_units"][0]["effective_batch_id"] = _identity("legacybatch", 99)
    with pytest.raises(PydanticValidationError, match="unauthorized batch"):
        validate_payload(payload)


def test_receipt_hash_tamper_fails_closed() -> None:
    payload = _receipt()
    payload["receipt_sha256"] = _sha(999)
    with pytest.raises(PydanticValidationError, match="self-hash differs"):
        validate_payload(payload)


def test_graph_pointer_drift_fails_closed() -> None:
    payload = _receipt()
    payload["items"][0]["graph_placement"]["item_revision_id"] = _identity("itemrev", 9999)
    graph = payload["items"][0]["graph_placement"]
    _rehash_graph(graph)
    _rehash_shards(payload)
    with pytest.raises(ValueError, match="Graph placement pointer drifts"):
        validate_payload(payload)


def test_duplicate_promoted_revision_fails_closed() -> None:
    payload = _receipt()
    payload["items"][1]["item_revision_id"] = payload["items"][0]["item_revision_id"]
    payload["items"][1]["item_current_revision_id"] = payload["items"][0]["item_revision_id"]
    payload["items"][1]["analysis"]["source_revision_id"] = payload["items"][0]["item_revision_id"]
    payload["items"][1]["analysis"]["item_revision_id"] = payload["items"][0]["item_revision_id"]
    payload["items"][1]["origin"]["profile_item_revision_id"] = payload["items"][0][
        "item_revision_id"
    ]
    payload["items"][1]["graph_placement"]["item_revision_id"] = payload["items"][0][
        "item_revision_id"
    ]
    graph = payload["items"][1]["graph_placement"]
    _rehash_graph(graph)
    _rehash_shards(payload)
    with pytest.raises(ValueError, match="not one-to-one"):
        validate_payload(payload)


def test_graph_placement_hash_tamper_fails_closed() -> None:
    payload = _receipt()
    payload["items"][0]["graph_placement"]["placement_sha256"] = _sha(9999)
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="Graph placement hash"):
        validate_payload(payload)


def test_item_manifest_pointer_hash_drift_fails_closed() -> None:
    payload = _receipt()
    payload["items"][0]["item_manifest_artifact"]["sha256"] = _sha(9999)
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="manifest Artifact pointer differs"):
        validate_payload(payload)


def test_analysis_result_pointer_hash_drift_fails_closed() -> None:
    payload = _receipt()
    payload["items"][0]["analysis"]["accepted_result_artifact"]["sha256"] = _sha(9999)
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="accepted-result Artifact pointer differs"):
        validate_payload(payload)


def test_analysis_source_pointer_drift_fails_closed() -> None:
    payload = _receipt()
    source = dict(payload["items"][0]["analysis"]["source_artifact"])
    source["artifact_revision_id"] = _identity("rev", 9999)
    payload["items"][0]["analysis"]["source_artifact"] = source
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="analysis source does not bind"):
        validate_payload(payload)


def test_institutional_origin_rights_drift_fails_closed() -> None:
    payload = _receipt()
    payload["items"][0]["origin"]["occurrence_rights_policy"]["rights_policy_sha256"] = _sha(9999)
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="origin rights pointers differ"):
        validate_payload(payload)


def test_institutional_origin_stale_occurrence_fails_closed() -> None:
    payload = _receipt()
    payload["items"][0]["origin"]["occurrence_current_revision_id"] = _identity("occurrev", 9999)
    _rehash_shards(payload)

    with pytest.raises(PydanticValidationError, match="occurrence is not current"):
        validate_payload(payload)


def test_graph_snapshot_membership_pointer_drift_fails_closed() -> None:
    payload = _receipt()
    graph = payload["items"][0]["graph_placement"]
    graph["graph_snapshot_revision_id"] = _identity("graphrev", 9999)
    _rehash_graph(graph)
    _rehash_shards(payload)

    with pytest.raises(ValueError, match="Graph placement pointer drifts"):
        validate_payload(payload)


def test_graph_manifest_artifact_hash_drift_fails_closed() -> None:
    payload = _receipt()
    payload["graph_snapshot"]["manifest_artifact"]["sha256"] = _sha(9999)

    with pytest.raises(PydanticValidationError, match="snapshot manifest Artifact pointer"):
        validate_payload(payload)


def test_analysis_recovery_set_hash_drift_fails_closed() -> None:
    payload = _receipt()
    payload["analysis_recovery_set_sha256"] = _sha(9999)

    with pytest.raises(PydanticValidationError, match="recovery set hash differs"):
        validate_payload(payload)


def test_graph_documents_bind_structure_projection_and_current_database() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload)
    receipt = validate_payload(payload)

    verify_graph_documents(
        receipt,
        items=_completion_items(payload),
        snapshot_manifest=graph_evidence[0],
        structure_manifest=graph_evidence[1],
        projection_member_bytes=graph_evidence[2],
        snapshot_database=graph_evidence[3],
        placement_database_rows=graph_evidence[4],
        snapshot_analysis_database_rows=graph_evidence[5],
    )


def test_accepted_analysis_result_binds_committed_json_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact identity uses producer JSON bytes, not the result's semantic self-hash."""

    accepted_at = datetime(2026, 9, 10, tzinfo=UTC)
    analysis_run_id = _identity("analysisrun", 990_001)
    analysis_request_id = _identity("knowledgeanalysis", 990_001)
    request_sha256 = _sha(990_001)
    risk_policy_revision_id = _identity("analysisriskrev", 990_001)
    semantic_body = {
        "accepted_at": "2026-09-10T00:00:00Z",
        "analysis_request_id": analysis_request_id,
    }
    semantic_hash = content_sha256(semantic_body)
    json_document = {**semantic_body, "result_sha256": semantic_hash}
    source = SimpleNamespace()
    result = SimpleNamespace(
        analysis_request_id=analysis_request_id,
        analysis_request_sha256=request_sha256,
        risk_policy_revision_id=risk_policy_revision_id,
        source=source,
        result_sha256=semantic_hash,
    )

    def dump_result(*, mode: str) -> dict[str, object]:
        document = dict(json_document)
        if mode == "python":
            document["accepted_at"] = accepted_at
        elif mode != "json":
            raise ValueError(f"unexpected serialization mode: {mode}")
        return document

    result.model_dump = dump_result
    artifact_sha256 = sha256_bytes(canonical_json_bytes(result.model_dump(mode="json")))
    assert result.result_sha256 != artifact_sha256
    assert sha256_bytes(canonical_json_bytes(result)) != artifact_sha256

    analysis = SimpleNamespace(
        analysis_run_id=analysis_run_id,
        analysis_request_id=analysis_request_id,
        request_sha256=request_sha256,
        predecessor_analysis_run_id=None,
        preset_id=_identity("execpreset", 990_001),
        preset_revision_id=_identity("execpresetrev", 990_001),
        preset_sha256=_sha(990_002),
        risk_policy_revision_id=risk_policy_revision_id,
    )
    request = SimpleNamespace(
        analysis_request_id=analysis_request_id,
        request_sha256=request_sha256,
        predecessor_analysis_run_id=None,
        execution_preset_id=analysis.preset_id,
        execution_preset_revision_id=analysis.preset_revision_id,
        execution_preset_sha256=analysis.preset_sha256,
        risk_policy_revision_id=risk_policy_revision_id,
        source=source,
    )
    first_item = SimpleNamespace(
        analysis=analysis,
        effective_work_unit_id="effective-work-unit",
        item_number=1,
    )
    first_document = SimpleNamespace(
        analysis_run_id=analysis_run_id,
        request_storage="KNOWLEDGE_ANALYSIS_RUN_CANONICAL_REQUEST_JSONB",
        result_storage="ARTIFACT_REVISION_RESULT_JSONB_AND_MEMBER",
        request=request,
        result=result,
        proposal_receipt=SimpleNamespace(),
        proposal=SimpleNamespace(),
    )
    remaining_run_ids = tuple(
        _identity("analysisrun", serial) for serial in range(990_002, 990_521)
    )
    items = (
        first_item,
        *(
            SimpleNamespace(analysis=SimpleNamespace(analysis_run_id=run_id))
            for run_id in remaining_run_ids
        ),
    )
    documents = (
        first_document,
        *(SimpleNamespace(analysis_run_id=run_id) for run_id in remaining_run_ids),
    )
    effective = SimpleNamespace(
        effective_work_unit_id="effective-work-unit",
        effective_batch_id="effective-batch",
    )

    class SerializationObserved(Exception):
        pass

    observed: list[object] = []

    def capture_serialization(value: object) -> bytes:
        observed.append(value)
        raise SerializationObserved

    monkeypatch.setattr(
        completion_contract,
        "canonical_json_bytes",
        capture_serialization,
    )

    with pytest.raises(SerializationObserved):
        completion_contract._verify_knowledge_analysis_documents(
            SimpleNamespace(effective_work_units=(effective,)),
            items=items,
            effective_documents=(
                SimpleNamespace(
                    effective_work_unit_id="effective-work-unit",
                    result=SimpleNamespace(items=(SimpleNamespace(item_number=1),)),
                ),
            ),
            knowledge_documents=documents,
            manifest_units={
                ("effective-batch", "effective-work-unit"): SimpleNamespace(
                    request=SimpleNamespace()
                )
            },
        )

    assert observed == [json_document]


def test_graph_documents_allow_unrelated_document_analysis_in_incremental_snapshot() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload)
    receipt = validate_payload(payload)
    unrelated = GraphSnapshotAnalysisDatabaseEvidence(
        graph_snapshot_revision_id=receipt.graph_snapshot.graph_snapshot_revision_id,
        analysis_run_id=_identity("analysisrun", 999_901),
        source_kind="DOCUMENT_REVISION",
        source_revision_id=_identity("edudocrev", 999_902),
        source_artifact_id=_identity("artifact", 999_903),
        source_artifact_revision_id=_identity("rev", 999_904),
        source_sha256=_sha(999_905),
        accepted_result_artifact_id=_identity("artifact", 999_906),
        accepted_result_artifact_revision_id=_identity("rev", 999_907),
        accepted_result_sha256=_sha(999_908),
    )

    verify_graph_documents(
        receipt,
        items=_completion_items(payload),
        snapshot_manifest=graph_evidence[0],
        structure_manifest=graph_evidence[1],
        projection_member_bytes=graph_evidence[2],
        snapshot_database=graph_evidence[3],
        placement_database_rows=graph_evidence[4],
        snapshot_analysis_database_rows=(*graph_evidence[5], unrelated),
    )


def test_graph_documents_reject_exact_pinned_structure_placement_drift() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload, structure_item_id_drift=True)
    receipt = validate_payload(payload)

    with pytest.raises(ValueError, match="differs from pinned Graph structure"):
        verify_graph_documents(
            receipt,
            items=_completion_items(payload),
            snapshot_manifest=graph_evidence[0],
            structure_manifest=graph_evidence[1],
            projection_member_bytes=graph_evidence[2],
            snapshot_database=graph_evidence[3],
            placement_database_rows=graph_evidence[4],
            snapshot_analysis_database_rows=graph_evidence[5],
        )


def test_graph_documents_reject_snapshot_database_pointer_drift() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload)
    receipt = validate_payload(payload)
    snapshot_database = graph_evidence[3].model_copy(
        update={"manifest_artifact_revision_id": _identity("rev", 999_999)}
    )

    with pytest.raises(ValueError, match="current database snapshot differs"):
        verify_graph_documents(
            receipt,
            items=_completion_items(payload),
            snapshot_manifest=graph_evidence[0],
            structure_manifest=graph_evidence[1],
            projection_member_bytes=graph_evidence[2],
            snapshot_database=snapshot_database,
            placement_database_rows=graph_evidence[4],
            snapshot_analysis_database_rows=graph_evidence[5],
        )


def test_graph_documents_reject_placement_row_not_from_pinned_projection() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload)
    receipt = validate_payload(payload)
    placements = list(graph_evidence[4])
    placements[0] = placements[0].model_copy(
        update={"placement_node_id": _identity("knode", 999_999)}
    )

    with pytest.raises(ValueError, match="differs from pinned structure/projection"):
        verify_graph_documents(
            receipt,
            items=_completion_items(payload),
            snapshot_manifest=graph_evidence[0],
            structure_manifest=graph_evidence[1],
            projection_member_bytes=graph_evidence[2],
            snapshot_database=graph_evidence[3],
            placement_database_rows=placements,
            snapshot_analysis_database_rows=graph_evidence[5],
        )


def test_graph_documents_reject_graph_creation_after_receipt_observation() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload)
    receipt = validate_payload(payload)
    snapshot_database = GraphSnapshotDatabaseEvidence.model_validate(
        {
            **graph_evidence[3].model_dump(mode="json"),
            "created_at": "2026-09-09T00:00:01Z",
        }
    )

    with pytest.raises(ValueError, match="current database snapshot differs"):
        verify_graph_documents(
            receipt,
            items=_completion_items(payload),
            snapshot_manifest=graph_evidence[0],
            structure_manifest=graph_evidence[1],
            projection_member_bytes=graph_evidence[2],
            snapshot_database=snapshot_database,
            placement_database_rows=graph_evidence[4],
            snapshot_analysis_database_rows=graph_evidence[5],
        )


def test_graph_documents_reject_cross_bundle_alias_of_expected_item() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload, structure_alias_extra=True)
    receipt = validate_payload(payload)

    with pytest.raises(ValueError, match="placement set is not exact"):
        verify_graph_documents(
            receipt,
            items=_completion_items(payload),
            snapshot_manifest=graph_evidence[0],
            structure_manifest=graph_evidence[1],
            projection_member_bytes=graph_evidence[2],
            snapshot_database=graph_evidence[3],
            placement_database_rows=graph_evidence[4],
            snapshot_analysis_database_rows=graph_evidence[5],
        )


def test_graph_documents_reject_conflicting_manifest_source_for_item_revision() -> None:
    payload = _receipt()
    graph_evidence = _graph_evidence(payload, manifest_source_conflict=True)
    receipt = validate_payload(payload)

    with pytest.raises(ValueError, match="manifest counts differ"):
        verify_graph_documents(
            receipt,
            items=_completion_items(payload),
            snapshot_manifest=graph_evidence[0],
            structure_manifest=graph_evidence[1],
            projection_member_bytes=graph_evidence[2],
            snapshot_database=graph_evidence[3],
            placement_database_rows=graph_evidence[4],
            snapshot_analysis_database_rows=graph_evidence[5],
        )
