"""A metadata successor reuses historical bindings and numerical rows verbatim."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_index_families import (
    parse_supported_embedding_binding,
    parse_supported_embedding_index,
    validate_supported_embedding_index_references,
    validate_supported_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    validate_embedding_index_reference_layout,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    PublicSolutionEmbeddingIndex,
    PublicSolutionIndexNamespace,
)
from eom_catalog_contracts.registered_public_solution_index import (
    PublicSolutionEmbeddingIndexV4,
    RegisteredPublicSolutionProfilePointer,
    RegisteredPublicSolutionSourceBinding,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_repository import binding_columns
from eom_catalog_service.public_solution_index_assembly import assemble_public_solution_binding
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from tests.unit.test_public_solution_index_assembly import assemble, setup
from tests.unit.test_registered_public_solution_embedding import registered_entry


def registered_index_entry():
    entry = registered_entry()
    source = entry.model_dump(mode="json")
    source["source"]["item_id"] = "item_" + "8" * 32
    source["source"]["item_revision_id"] = "itemrev_" + "8" * 32
    source["entry_sha256"] = content_sha256(
        {key: value for key, value in source.items() if key != "entry_sha256"}
    )
    return type(entry).model_validate(source)


def successor():
    data = setup(device="CUDA")
    parent = assemble(data).index
    # All three sources have the same actual public text. No new numeric row.
    entry = registered_index_entry()
    old = parent.bindings[0]
    body = dict(
        schema_version="embedding-source-binding/4.0",
        source=entry.source,
        base_analysis_run_id=entry.base_analysis_run_id,
        profile=RegisteredPublicSolutionProfilePointer.from_entry(entry),
        evidence=entry.evidence,
        graph_snapshot=entry.graph_snapshot,
        policy_revision_id=entry.policy_revision_id,
        policy_sha256=entry.policy_sha256,
        recipe=entry.recipe,
        view="CONCRETE_FACETS",
        projection_version="public-solution-text/1.0",
        encoding=old.encoding,
        row_ref=old.row_ref,
    )
    binding = RegisteredPublicSolutionSourceBinding.model_validate(
        body | {"binding_sha256": content_sha256(body)}
    )
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/embedding-index-manifest/3.0",
        media_type="application/json",
        sha256=content_sha256(parent.model_dump(mode="json")),
    )
    value = parent.model_dump(mode="json")
    value.update(
        schema_version="embedding-index-manifest/4.0",
        index_revision_id="embeddingindexrev_" + "4" * 32,
        previous_manifest=pointer.model_dump(mode="json"),
        bindings=[
            item.model_dump(mode="json")
            for item in sorted(
                (*parent.bindings, binding), key=lambda value: value.source.item_revision_id
            )
        ],
    )
    value["index_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "index_sha256"}
    )
    return parent, PublicSolutionEmbeddingIndexV4.model_validate(value), pointer, data[2]


def test_index4_preserves_all_past_and_creative_binding3_bytes_and_existing_vector_rows():
    parent, current, pointer, shards = successor()
    before = {value.binding_sha256: canonical_json_bytes(value) for value in parent.bindings}
    assert len(current.bindings) == 3 and len(shards) == 1 and shards[0][1].row_count == 1
    for binding in current.bindings:
        if binding.binding_sha256 in before:
            assert canonical_json_bytes(binding) == before[binding.binding_sha256]
    assert current.space == parent.space and current.recipe == parent.recipe
    assert {binding.encoding for binding in current.bindings} == {parent.bindings[0].encoding}
    assert current.shards == parent.shards
    validate_embedding_index_reference_layout(current, shards, (pointer, parent))
    validate_supported_embedding_index_references(current, shards, (pointer, parent))
    original_entries = setup(device="CUDA")[0]
    selected = tuple(
        sorted(
            (*original_entries, registered_index_entry()),
            key=lambda value: value.source.item_revision_id,
        )
    )
    validate_supported_embedding_source_bindings(current.bindings, selected, shards)
    assert parse_supported_embedding_index(current) == current
    assert PublicSolutionEmbeddingIndexV4.model_validate_json(current.model_dump_json()) == current
    with pytest.raises((ValueError, JsonSchemaValidationError)):
        PublicSolutionEmbeddingIndex.model_validate(current.model_dump(mode="json"))


def test_actual_binding_assembly_and_pointer_only_ledger_preserve_the_registered_run():
    _parent, current, _pointer, _shards = successor()
    binding = next(
        value
        for value in current.bindings
        if value.schema_version == "embedding-source-binding/4.0"
    )
    namespace = PublicSolutionIndexNamespace(
        storage_partition=current.storage_partition,
        space_sha256=current.space.space_sha256,
        recipe_sha256=current.recipe.recipe_sha256,
    )
    built = assemble_public_solution_binding(
        registered_index_entry(),
        row=RegisteredEmbeddingRow(binding.encoding, binding.row_ref),
        space=current.space,
        namespace=namespace,
    )
    assert built == binding and parse_supported_embedding_binding(built) == binding
    columns = binding_columns(built)
    assert columns["evidence_kind"] == "PUBLIC_SOLUTION_REPORT"
    assert columns["solution_analysis_run_id"] == built.evidence.solution.solution_analysis_run_id
    assert columns["solution_pointer_sha256"] == content_sha256(built.evidence)
    assert columns["review_job_id"] is None
    assert not {"text", "report", "vector", "payload"}.intersection(columns)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_evidence",
        "old_profile",
        "bad_row",
        "bad_base",
        "duplicate_source",
        "wrong_previous",
        "different_partition",
        "different_space",
        "recipe_hash",
    ],
)
def test_closed_successor_rejects_wrong_identity_even_when_outer_hash_is_recomputed(change):
    _parent, current, _pointer, _shards = successor()
    value = current.model_dump(mode="json")
    binding = next(
        item
        for item in value["bindings"]
        if item["schema_version"] == "embedding-source-binding/4.0"
    )
    if change == "unknown_evidence":
        binding["evidence"]["kind"] = "REVIEW_CONCLUSION"
    elif change == "old_profile":
        binding["profile"]["schema_ref"] = (
            "eom://schemas/knowledge/public-solution-embedding-entry/1.0"
        )
    elif change == "bad_row":
        binding["row_ref"]["encoding_sha256"] = "sha256:" + "0" * 64
    elif change == "bad_base":
        binding["base_analysis_run_id"] = "analysisrun_" + "0" * 32
    elif change == "duplicate_source":
        value["bindings"].append(deepcopy(binding))
    elif change == "wrong_previous":
        value["previous_manifest"]["schema_ref"] = (
            "eom://schemas/knowledge/embedding-index-manifest/2.0"
        )
    elif change == "different_partition":
        value["storage_partition"] = "other"
    elif change == "different_space":
        value["space"]["space_sha256"] = "sha256:" + "0" * 64
    else:
        value["recipe"]["recipe_sha256"] = "sha256:" + "0" * 64
    binding["binding_sha256"] = content_sha256(
        {key: item for key, item in binding.items() if key != "binding_sha256"}
    )
    value["index_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "index_sha256"}
    )
    with pytest.raises(ValueError):
        PublicSolutionEmbeddingIndexV4.model_validate(value)


def test_registered_index_schema_is_pinned_packaged_and_2020_12():
    root = Path(__file__).resolve().parents[2]
    relative = "knowledge/public-solution-embedding-index-v4.schema.json"
    assert (root / "schemas" / relative).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
    ).read_bytes()
    schema = load_schema("public-solution-embedding-index-v4")
    Draft202012Validator.check_schema(schema)
    _parent, current, _pointer, _shards = successor()
    validate_contract("public-solution-embedding-index-v4", current.model_dump(mode="json"))
