"""Small synthetic metadata pins, never real source authority or live Graph evidence."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts.inference_transfer_metadata import (
    InferenceTransferMetadataResolveRequest,
    InferenceTransferMetadataResolveResult,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_snapshot_fixtures import hashed

ACTOR = "operator_" + "1" * 32


def metadata_request(**updates: Any) -> InferenceTransferMetadataResolveRequest:
    body = {
        "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
        "expected_snapshot_sha256": sha("9"),
        "access_policy_revision_id": "accessrev_" + "a" * 32,
        "access_policy_sha256": sha("a"),
        "source_classes": ("PAST_EXAM",),
    }
    return hashed(InferenceTransferMetadataResolveRequest, "request_sha256", **(body | updates))


def metadata_graph() -> KnowledgeGraphSnapshotPointer:
    return KnowledgeGraphSnapshotPointer.model_validate(
        {
            "graph_id": "graph_" + "e" * 32,
            "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
            "manifest_sha256": sha("e"),
            "manifest_artifact": {
                "artifact_id": "artifact_" + "e" * 32,
                "artifact_revision_id": "rev_" + "e" * 32,
                "sha256": sha("e"),
                "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/9.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
                "member_path": "projections/manifest.json",
            },
        }
    )


def metadata_result(
    request: InferenceTransferMetadataResolveRequest | None = None, **updates: Any
) -> InferenceTransferMetadataResolveResult:
    request = request or metadata_request()
    body = {
        "request_sha256": request.request_sha256,
        "graph_snapshot": metadata_graph(),
        "snapshot_sha256": request.expected_snapshot_sha256,
        "access_policy_revision_id": request.access_policy_revision_id,
        "access_policy_sha256": request.access_policy_sha256,
        "source_classes": request.source_classes,
    }
    return hashed(InferenceTransferMetadataResolveResult, "result_sha256", **(body | updates))
