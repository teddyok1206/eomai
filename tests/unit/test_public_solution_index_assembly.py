"""New report family uses old numerical shards, never old binding meanings."""

from dataclasses import replace

import pytest
from eom_catalog_contracts.embedding_index_families import (
    validate_supported_embedding_index_references,
    validate_supported_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import (
    PublicSolutionEmbeddingIndex,
    PublicSolutionIndexNamespace,
)
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.public_solution_index_assembly import assemble_public_solution_index
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_space,
    shard_pointer,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_public_solution_encoding import public_entry


def setup(*, different_text=False, device="CPU"):
    first = public_entry()
    value = public_entry(
        creative=True, text="다른 과학 풀이" if different_text else first.public_solution.text
    ).model_dump(mode="json")
    value["source"]["item_id"] = "item_" + "9" * 32
    value["source"]["item_revision_id"] = "itemrev_" + "9" * 32
    value["entry_sha256"] = content_sha256(
        {key: v for key, v in value.items() if key != "entry_sha256"}
    )
    second = PublicSolutionEmbeddingEntry.model_validate(value)
    entries = tuple(sorted((first, second), key=lambda entry: entry.source.item_revision_id))
    space = embedding_space(device=device)
    namespace = PublicSolutionIndexNamespace(
        storage_partition="public-solution",
        space_sha256=space.space_sha256,
        recipe_sha256=first.recipe.recipe_sha256,
    )
    encodings = {}
    for entry in entries:
        value = prepare_public_solution_encoding(
            entry, space=space, storage_partition=namespace.storage_partition
        ).input.encoding
        encodings[value.encoding_sha256] = value
    shard = vector_shard(tuple(encodings[key] for key in sorted(encodings)), space=space)
    pointer = shard_pointer(shard, "a")
    rows = tuple(
        RegisteredEmbeddingRow(
            encoding,
            EmbeddingVectorRowRef(
                shard_manifest=pointer, row_index=index, encoding_sha256=encoding.encoding_sha256
            ),
        )
        for index, encoding in enumerate(shard.rows)
    )
    return entries, rows, ((pointer, shard),), namespace, space


def assemble(data, *, rows=None, previous=None, revision="2"):
    entries, available, shards, namespace, space = data
    return assemble_public_solution_index(
        entries,
        available_rows=available if rows is None else rows,
        shards=shards,
        namespace=namespace,
        space=space,
        index_id="embeddingindex_" + "1" * 32,
        index_revision_id="embeddingindexrev_" + revision * 32,
        previous_manifest=previous,
        created_at=NOW,
    )


def test_different_sources_keep_two_bindings_for_one_reused_numeric_row():
    data = setup()
    before = tuple(canonical_json_bytes(entry) for entry in data[0])
    value = assemble(data)
    assert len(data[1]) == 1 and len(value.index.bindings) == 2
    left, right = value.index.bindings
    assert left.profile != right.profile and left.evidence.kind != right.evidence.kind
    assert left.row_ref == right.row_ref
    assert left.encoding == right.encoding
    assert before == tuple(canonical_json_bytes(entry) for entry in data[0])
    assert assemble(data) == value
    validate_supported_embedding_index_references(value.index, value.shards, None)
    validate_supported_embedding_source_bindings(value.index.bindings, data[0], value.shards)
    assert (
        PublicSolutionEmbeddingIndex.model_validate_json(value.index.model_dump_json())
        == value.index
    )


def test_partial_rows_have_partial_coverage_and_do_not_invent_missing_vectors():
    data = setup(different_text=True)
    partial = assemble(data, rows=data[1][:1])
    assert len(partial.index.bindings) == 1
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "b" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/embedding-index-manifest/3.0",
        media_type="application/json",
        sha256=content_sha256(partial.index.model_dump(mode="json")),
    )
    complete = assemble(data, previous=pointer, revision="3")
    assert len(complete.index.bindings) == 2
    assert partial.index.bindings[0] in complete.index.bindings
    assert complete.index.previous_manifest == pointer


def test_no_rows_and_duplicate_sources_fail_explicitly():
    data = setup()
    with pytest.raises(ValueError, match="NO_AVAILABLE_BINDING"):
        assemble(data, rows=())
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        assemble((data[0] * 2, *data[1:]))


def test_legacy_index_is_not_reinterpreted_as_new_namespace_history():
    old = ArtifactMemberPointer(
        artifact_id="artifact_" + "b" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/embedding-index-manifest/2.0",
        media_type="application/json",
        sha256="sha256:" + "b" * 64,
    )
    with pytest.raises(ValueError, match="predecessor schema"):
        assemble(setup(), previous=old)


def test_foreign_recipe_and_encoding_cannot_be_used_to_bind_a_source():
    data = setup(different_text=True)
    namespace = data[3].model_copy(update={"recipe_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="INPUT_MISMATCH"):
        assemble((*data[:3], namespace, data[4]))
    bad = replace(data[1][0], row_ref=data[1][1].row_ref)
    with pytest.raises(ValueError):
        assemble(data, rows=(bad, *data[1][1:]))
