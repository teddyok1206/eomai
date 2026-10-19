"""Synthetic mixed-association metadata, never stored or authorized source evidence."""

from __future__ import annotations

from eom_catalog_contracts.inference_transfer_experiment import ExperimentView, experiment_view_text
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingSourceBinding,
    registered_review_embedding_text,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    embedding_space,
    encoding_identity,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
    view_recipe,
)
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_registered_review_embedding_delta import _entry


def mixed_embedding_case(view: ExperimentView = "CONCRETE_FACETS") -> tuple:
    old, new = embedding_entry(), _entry()
    space = embedding_space()
    old_text, new_text = (
        experiment_view_text(old, view),
        registered_review_embedding_text(new, view),
    )
    assert old_text is not None and new_text is not None
    new_encoding = encoding_identity(new_text, space)
    shard = vector_shard((encoding_identity(old_text, space), new_encoding), space=space)
    pointer = shard_pointer(shard)
    legacy = source_binding(old, view=view, shard=shard, pointer=pointer)
    body = {
        "schema_version": "embedding-source-binding/2.0",
        "source": new.profile.source_basis.source.model_dump(mode="json"),
        "base_analysis_run_id": "analysisrun_" + "c" * 32,
        "profile": RegisteredReviewProfilePointer.from_profile(new.profile).model_dump(mode="json"),
        "review_evidence": new.profile.source_basis.review_evidence.model_dump(mode="json"),
        "graph_snapshot": new.profile.source_basis.graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": "accessrev_" + "e" * 32,
        "policy_sha256": sha("e"),
        "recipe": view_recipe().model_dump(mode="json"),
        "view": view,
        "projection_version": "registered-item-review-comparison/1.0",
        "encoding": new_encoding.model_dump(mode="json"),
        "row_ref": {
            "shard_manifest": pointer.model_dump(mode="json"),
            "row_index": next(i for i, row in enumerate(shard.rows) if row == new_encoding),
            "encoding_sha256": new_encoding.encoding_sha256,
        },
    }
    binding = RegisteredReviewEmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))
    index_body = {
        "schema_version": "embedding-index-manifest/2.0",
        "index_id": "embeddingindex_" + "d" * 32,
        "index_revision_id": "embeddingindexrev_" + "d" * 32,
        "previous_manifest": None,
        "storage_partition": PARTITION,
        "space": space.model_dump(mode="json"),
        "view": view,
        "recipe": view_recipe().model_dump(mode="json"),
        "shards": [pointer.model_dump(mode="json")],
        "bindings": [
            b.model_dump(mode="json")
            for b in sorted((legacy, binding), key=lambda b: b.source.item_revision_id)
        ],
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    index = MixedEmbeddingIndexManifest.model_validate(seal(index_body, "index_sha256"))
    return new, binding, shard, pointer, index
