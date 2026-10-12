"""Pure bounded metadata validation; no source admission, vectors or inference."""

from __future__ import annotations

from time import perf_counter
from typing import Any

import pytest
from eom_catalog_contracts import inference_transfer_embedding as contracts
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingSourceBinding,
    EmbeddingVectorShardManifest,
    validate_embedding_source_binding,
    validate_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    embedding_space,
    encoding_identity,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
)


def test_batch_uses_the_same_scalar_semantic_leaf() -> None:
    entry = embedding_entry()
    binding = source_binding(entry)
    shard = vector_shard((binding.encoding,))
    pointer = binding.row_ref.shard_manifest
    validate_embedding_source_binding(binding, entry, pointer, shard)
    validate_embedding_source_bindings((binding,), (entry,), ((pointer, shard),))
    for field, expected_error in (
        ("profile", "exact approved profile"),
        ("text", "exact available source text"),
        ("row", "foreign shard, row"),
    ):
        body = binding.model_dump(mode="json")
        if field == "profile":
            body["profile"]["profile_revision_id"] = "inferenceprofilerev_" + "f" * 32
        elif field == "text":
            body["encoding"] = encoding_identity("changed synthetic text").model_dump(mode="json")
            body["row_ref"]["encoding_sha256"] = body["encoding"]["encoding_sha256"]
        else:
            body["row_ref"]["row_index"] = 1
        changed = EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))
        with pytest.raises(ValueError, match=expected_error):
            validate_embedding_source_binding(changed, entry, pointer, shard)
        with pytest.raises(ValueError, match=expected_error):
            validate_embedding_source_bindings((changed,), (entry,), ((pointer, shard),))


def test_batch_rejects_missing_duplicate_and_unexpected_pointer_closure() -> None:
    entry = embedding_entry()
    binding = source_binding(entry)
    shard = vector_shard((binding.encoding,))
    pointer = binding.row_ref.shard_manifest
    with pytest.raises(ValueError, match="exact approved profile"):
        validate_embedding_source_bindings((binding,), (), ((pointer, shard),))
    with pytest.raises(ValueError, match="foreign shard, row"):
        validate_embedding_source_bindings((binding,), (entry,), ())
    with pytest.raises(ValueError, match="sorted and unique"):
        validate_embedding_source_bindings((binding,), (entry,), ((pointer, shard),) * 2)
    with pytest.raises(ValueError, match="duplicate source revisions"):
        validate_embedding_source_bindings((binding,), (entry,) * 2, ((pointer, shard),))
    with pytest.raises(ValueError, match="duplicate source bindings"):
        validate_embedding_source_bindings((binding,) * 2, (entry,), ((pointer, shard),))
    unexpected = shard_pointer(shard, "f")
    with pytest.raises(ValueError, match="shard set is missing or differs"):
        validate_embedding_source_bindings(
            (binding,), (entry,), ((pointer, shard), (unexpected, shard))
        )
    with pytest.raises(ValueError, match="sorted and unique"):
        validate_embedding_source_bindings(
            (binding,), (entry,), ((unexpected, shard), (pointer, shard))
        )


def test_batch_revalidates_forged_frozen_values_and_changed_raw_member() -> None:
    entry = embedding_entry()
    binding = source_binding(entry)
    shard = vector_shard((binding.encoding,))
    pointer = binding.row_ref.shard_manifest
    with pytest.raises(ValueError, match="binding_sha256"):
        validate_embedding_source_bindings(
            (binding.model_copy(update={"binding_sha256": "sha256:" + "f" * 64}),),
            (entry,),
            ((pointer, shard),),
        )
    with pytest.raises(ValueError, match="shard_sha256"):
        validate_embedding_source_bindings(
            (binding,),
            (entry,),
            ((pointer, shard.model_copy(update={"shard_sha256": "sha256:" + "f" * 64})),),
        )
    changed_pointer = pointer.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32})
    with pytest.raises(ValueError, match="foreign shard, row"):
        validate_embedding_source_bindings((binding,), (entry,), ((changed_pointer, shard),))
    body = shard.model_dump(mode="json")
    body["binary"]["sha256"] = "sha256:" + "f" * 64
    changed_shard = EmbeddingVectorShardManifest.model_validate(seal(body, "shard_sha256"))
    with pytest.raises(ValueError, match="foreign shard, row"):
        validate_embedding_source_bindings((binding,), (entry,), ((pointer, changed_shard),))
    with pytest.raises(ValueError, match="row budget"):
        validate_embedding_source_bindings((binding,) * 1025, (entry,), ((pointer, shard),))


def _large_capture() -> tuple[
    tuple[EmbeddingSourceBinding, ...],
    tuple[StagedExperimentEntry, ...],
    tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
]:
    """Linear fixture construction, exactly 1,024 sources sharing one pinned shard."""
    template_entry = embedding_entry().model_dump(mode="json")
    template_binding = source_binding().model_dump(mode="json")
    space = embedding_space()
    entries = []
    encodings = []
    for number in range(1024):
        identity = f"{number + 1:032x}"
        body = embedding_entry().model_dump(mode="json")
        body["profile"]["source_basis"]["source"].update(
            item_id="item_" + identity, item_revision_id="itemrev_" + identity
        )
        body["profile"].update(
            profile_id="inferenceprofile_" + identity,
            profile_revision_id="inferenceprofilerev_" + identity,
        )
        body["profile"] = seal(body["profile"], "profile_sha256")
        body["metadata"][0]["value"] = template_entry["metadata"][0]["value"] + str(number)
        entry = StagedExperimentEntry.model_validate(body)
        text = experiment_view_text(entry, "METADATA_ONLY")
        assert text is not None
        entries.append(entry)
        encodings.append(encoding_identity(text, space))
    shard = vector_shard(tuple(encodings), space=space)
    pointer = shard_pointer(shard)
    row_indexes = {row.encoding_sha256: index for index, row in enumerate(shard.rows)}
    bindings = []
    for entry, encoding in zip(entries, encodings, strict=True):
        basis = entry.profile.source_basis
        body = template_binding | {
            "source": basis.source.model_dump(mode="json"),
            "profile": InferenceTransferProfilePointer.from_profile(entry.profile).model_dump(
                mode="json"
            ),
            "encoding": encoding.model_dump(mode="json"),
            "row_ref": {
                "shard_manifest": pointer.model_dump(mode="json"),
                "row_index": row_indexes[encoding.encoding_sha256],
                "encoding_sha256": encoding.encoding_sha256,
            },
        }
        bindings.append(EmbeddingSourceBinding.model_validate(seal(body, "binding_sha256")))
    return tuple(bindings), tuple(entries), ((pointer, shard),)


def test_1024_shared_rows_parse_and_hash_each_unique_shard_once(
    monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    bindings, entries, shards = _large_capture()
    counts = {"bindings": 0, "entries": 0, "shards": 0, "shard_hashes": 0}
    original_binding = contracts.parse_embedding_binding
    original_shard = contracts.parse_embedding_shard
    original_entry = StagedExperimentEntry.model_validate
    original_hash = content_sha256

    def count_binding(value: dict[str, Any]) -> EmbeddingSourceBinding:
        counts["bindings"] += 1
        return original_binding(value)

    def count_shard(value: dict[str, Any]) -> EmbeddingVectorShardManifest:
        counts["shards"] += 1
        return original_shard(value)

    def count_entry(_cls: type[StagedExperimentEntry], value: Any) -> StagedExperimentEntry:
        counts["entries"] += 1
        return original_entry(value)

    def count_hash(value: Any) -> str:
        if isinstance(value, dict) and value.get("schema_version") == "embedding-vector-shard/1.0":
            counts["shard_hashes"] += 1
        return original_hash(value)

    monkeypatch.setattr(contracts, "parse_embedding_binding", count_binding)
    monkeypatch.setattr(contracts, "parse_embedding_shard", count_shard)
    monkeypatch.setattr(StagedExperimentEntry, "model_validate", classmethod(count_entry))
    monkeypatch.setattr(contracts, "content_sha256", count_hash)
    started = perf_counter()
    validate_embedding_source_bindings(bindings, entries, shards)
    record_property("synthetic_1024_validation_seconds", perf_counter() - started)
    # Semantic-shard and raw-member hashes each run once, not once per binding.
    assert counts == {"bindings": 1024, "entries": 1024, "shards": 1, "shard_hashes": 2}
