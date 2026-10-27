"""Successor contract only; synthetic pointers do not prove Catalog population coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.segmented_embedding_index import SegmentedEmbeddingIndexRoot
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    embedding_space,
    index_manifest,
    index_pointer,
)
from tests.unit.inference_transfer_fixtures import NOW

ROOT = Path(__file__).resolve().parents[2]


def test_segmented_schema_mirror_and_registered_hash() -> None:
    resource = CATALOG_SCHEMA_RESOURCES["segmented-embedding-index-v1"]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == resource.sha256
    Draft202012Validator.check_schema(load_schema("segmented-embedding-index-v1"))


def _root_body() -> dict[str, Any]:
    entries = (embedding_entry("a"), embedding_entry("b"))
    segments = []
    indexes = []
    for ordinal, entry in enumerate(entries):
        index = index_manifest(revision_seed=str(ordinal + 2))
        indexes.append(index)
        pointer = index_pointer(index, str(ordinal + 4))
        source_revision_id = entry.profile.source_basis.source.item_revision_id
        segments.append(
            {
                "index_manifest": pointer.model_dump(mode="json"),
                "first_source_revision_id": source_revision_id,
                "last_source_revision_id": source_revision_id,
                "binding_count": 1024 if ordinal == 0 else 1,
                "target_set_sha256": content_sha256({"synthetic_segment": ordinal}),
            }
        )
    body = {
        "schema_version": "segmented-embedding-index/1.0",
        "index_id": "embeddingindex_" + "9" * 32,
        "index_revision_id": "embeddingindexrev_" + "9" * 32,
        "previous_root": None,
        "corpus_id": "corpus_" + "c" * 32,
        "graph_snapshot": entries[0].profile.source_basis.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": "accessrev_" + "d" * 32,
        "policy_sha256": content_sha256({"synthetic_policy": True}),
        "storage_partition": PARTITION,
        "space": embedding_space().model_dump(mode="json"),
        "view": "METADATA_ONLY",
        "recipe": indexes[0].recipe.model_dump(mode="json"),
        "segments": segments,
        "source_count": 1025,
        "source_selection_sha256": content_sha256({"synthetic_population": True}),
        "binding_count": 1025,
        "target_set_sha256": content_sha256(
            [
                {
                    "first_source_revision_id": segment["first_source_revision_id"],
                    "last_source_revision_id": segment["last_source_revision_id"],
                    "binding_count": segment["binding_count"],
                    "target_set_sha256": segment["target_set_sha256"],
                }
                for segment in segments
            ]
        ),
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    body["root_sha256"] = content_sha256(body)
    return body


def _reseal(body: dict[str, Any]) -> dict[str, Any]:
    body["target_set_sha256"] = content_sha256(
        [
            {
                "first_source_revision_id": segment["first_source_revision_id"],
                "last_source_revision_id": segment["last_source_revision_id"],
                "binding_count": segment["binding_count"],
                "target_set_sha256": segment["target_set_sha256"],
            }
            for segment in body["segments"]
        ]
    )
    body["root_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "root_sha256"}
    )
    return body


def test_segmented_root_preserves_ordered_pointers_and_immutable_hash() -> None:
    body = _root_body()
    root = SegmentedEmbeddingIndexRoot.model_validate(body)
    assert root.binding_count == 1025
    assert root.source_count == 1025
    assert len(root.segments) == 2
    assert root.root_sha256 == body["root_sha256"]
    assert root.model_dump(mode="json") == body


@pytest.mark.parametrize(
    "fault",
    [
        "order",
        "overlap",
        "duplicate",
        "count",
        "source_count",
        "segment_hash",
        "root_hash",
        "media",
        "version",
    ],
)
def test_segmented_root_refuses_incomplete_or_drifting_descriptors(fault: str) -> None:
    body = _root_body()
    if fault == "order":
        body["segments"].reverse()
    elif fault == "overlap":
        body["segments"][1]["first_source_revision_id"] = body["segments"][0][
            "last_source_revision_id"
        ]
    elif fault == "duplicate":
        body["segments"][1]["index_manifest"] = body["segments"][0]["index_manifest"]
    elif fault == "count":
        body["binding_count"] = 1026
    elif fault == "source_count":
        body["source_count"] = 1024
    elif fault == "segment_hash":
        body["segments"][1]["target_set_sha256"] = "sha256:" + "0" * 64
    elif fault == "root_hash":
        body["root_sha256"] = "sha256:" + "0" * 64
    elif fault == "media":
        body["segments"][0]["index_manifest"]["media_type"] = "image/png"
    else:
        body["schema_version"] = "segmented-embedding-index/2.0"
    if fault not in {"root_hash", "segment_hash"}:
        _reseal(body)
    with pytest.raises((ValueError, SchemaError)):
        SegmentedEmbeddingIndexRoot.model_validate(body)


def test_segmented_root_rejects_coercion_and_unbounded_population() -> None:
    body = _root_body()
    body["segments"][0]["binding_count"] = "1024"
    _reseal(body)
    with pytest.raises((ValueError, SchemaError)):
        SegmentedEmbeddingIndexRoot.model_validate(body)
    body = _root_body()
    body["binding_count"] = 1_048_577
    _reseal(body)
    with pytest.raises((ValueError, SchemaError)):
        SegmentedEmbeddingIndexRoot.model_validate(body)


def test_self_consistent_segment_descriptor_is_not_an_artifact_coverage_proof() -> None:
    body = _root_body()
    body["segments"][1]["target_set_sha256"] = "sha256:" + "0" * 64
    _reseal(body)
    # A pure pointer contract cannot inspect the referred-to index. Catalog must
    # reopen each manifest and compare the real source/input identities at commit.
    assert SegmentedEmbeddingIndexRoot.model_validate(body).segments[1].target_set_sha256 == (
        "sha256:" + "0" * 64
    )


def test_self_consistent_source_selection_is_not_current_population_proof() -> None:
    body = _root_body()
    body["source_selection_sha256"] = "sha256:" + "0" * 64
    _reseal(body)
    assert SegmentedEmbeddingIndexRoot.model_validate(body).source_selection_sha256 == (
        "sha256:" + "0" * 64
    )
