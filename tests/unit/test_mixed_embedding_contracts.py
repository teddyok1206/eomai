"""Schema-first mixed metadata, not numerical execution or Graph authorization."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingSourceBinding,
    parse_embedding_binding,
    parse_embedding_index,
)
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_SCHEMA,
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingEntry,
    RegisteredReviewEmbeddingSourceBinding,
    parse_supported_embedding_binding,
    parse_supported_embedding_entry,
    parse_supported_embedding_index,
    validate_mixed_embedding_index_references,
    validate_mixed_embedding_source_bindings,
    validate_registered_review_embedding_binding,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case

ROOT = Path(__file__).resolve().parents[2]
INVALID = (ValueError, SchemaError, TypeError)


def test_mixed_schema_mirror_identity_and_no_old_resource_changes() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[MIXED_EMBEDDING_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    Draft202012Validator.check_schema(load_schema(MIXED_EMBEDDING_SCHEMA))


@pytest.mark.parametrize("view", ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"))
def test_mixed_index_retains_exact_old_binding_and_unchanged_shard(view) -> None:
    entry, binding, shard, pointer, index = mixed_embedding_case(view)
    validate_registered_review_embedding_binding(binding, entry, pointer, shard)
    for value in (entry, binding, index):
        validate_contract(MIXED_EMBEDDING_SCHEMA, value.model_dump(mode="json"))
        assert type(value).model_validate(value).model_dump(mode="json") == value.model_dump(
            mode="json"
        )
    assert len(index.bindings) == 2
    legacy = next(b for b in index.bindings if isinstance(b, EmbeddingSourceBinding))
    assert parse_embedding_binding(legacy.model_dump(mode="json")) == legacy
    assert shard.schema_version == "embedding-vector-shard/1.0"
    assert index.shards == (pointer,)
    with pytest.raises(INVALID):
        parse_embedding_index(index.model_dump(mode="json"))
    with pytest.raises(INVALID):
        parse_embedding_binding(binding.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field", ("source", "profile", "review_evidence", "graph_snapshot", "encoding", "row_ref")
)
def test_forged_registered_binding_is_rejected_even_when_its_own_hash_is_resealed(field) -> None:
    entry, binding, shard, pointer, _index = mixed_embedding_case()
    body = binding.model_dump(mode="json")
    if field == "source":
        body[field]["item_revision_id"] = "itemrev_" + "f" * 32
    elif field == "profile":
        body[field]["profile_sha256"] = "sha256:" + "f" * 64
    elif field == "review_evidence":
        body[field]["review"]["job_id"] = "job_" + "f" * 32
    elif field == "graph_snapshot":
        body[field]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    elif field == "encoding":
        body[field]["input_text_sha256"] = "sha256:" + "f" * 64
    else:
        body[field]["row_index"] = 1023
    with pytest.raises(INVALID):
        value = RegisteredReviewEmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))
        validate_registered_review_embedding_binding(value, entry, pointer, shard)


@pytest.mark.parametrize(
    "field", ("space", "storage_partition", "view", "recipe", "shards", "bindings")
)
def test_mixed_index_layout_is_closed_even_when_its_hash_is_resealed(field) -> None:
    *_prefix, index = mixed_embedding_case()
    body = index.model_dump(mode="json")
    if field == "space":
        body[field]["purpose"] = "QUERY"
        body[field] = seal(body[field], "space_sha256")
    elif field == "storage_partition":
        body[field] = "foreign-partition"
    elif field == "view":
        body[field] = "CONTENT_ONLY"
    elif field == "recipe":
        body[field]["maximum_text_bytes"] = 1
    elif field == "shards":
        body[field] *= 2
    else:
        body[field] *= 2
    with pytest.raises(INVALID):
        MixedEmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))


@pytest.mark.parametrize("model_index", (0, 1, 4))
def test_copied_extra_fields_are_not_discarded_before_validation(model_index) -> None:
    value = mixed_embedding_case()[model_index]
    with pytest.raises(INVALID):
        type(value).model_validate(value.model_copy(update={"undeclared": "value"}))


def test_legacy_solution_pointer_cannot_substitute_for_review_evidence() -> None:
    *_prefix, index = mixed_embedding_case()
    legacy = next(b for b in index.bindings if isinstance(b, EmbeddingSourceBinding))
    new = next(b for b in index.bindings if isinstance(b, RegisteredReviewEmbeddingSourceBinding))
    body = new.model_dump(mode="json")
    body["review_evidence"] = copy.deepcopy(legacy.solution_evidence.model_dump(mode="json"))
    with pytest.raises(INVALID):
        RegisteredReviewEmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))


def test_real_base_analysis_identity_is_required_not_a_review_job_id() -> None:
    _entry, binding, *_rest = mixed_embedding_case()
    body = binding.model_dump(mode="json")
    body["base_analysis_run_id"] = body["review_evidence"]["review"]["job_id"]
    with pytest.raises(INVALID):
        RegisteredReviewEmbeddingSourceBinding.model_validate(seal(body, "binding_sha256"))


def test_wire_entry_is_one_canonical_shape_and_hash_preserves_negative_units() -> None:
    entry, *_rest = mixed_embedding_case()
    payload = canonical_json_bytes(entry.model_dump(mode="json"))
    checked = RegisteredReviewEmbeddingEntry.model_validate_json(payload)
    assert checked == entry and checked.content is not None
    assert "-2 m/s" in checked.content.text and "없다" in checked.content.text


@pytest.mark.parametrize("view", ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"))
def test_mixed_materialized_closure_validates_both_real_families(view) -> None:
    entry, _binding, shard, pointer, index = mixed_embedding_case(view)
    validate_mixed_embedding_source_bindings(
        index.bindings, (embedding_entry(), entry), ((pointer, shard),)
    )
    validate_mixed_embedding_index_references(index, ((pointer, shard),))
    assert parse_supported_embedding_index(index) == index
    assert parse_supported_embedding_entry(entry) == entry
    assert parse_supported_embedding_entry(embedding_entry()) == embedding_entry()
    for binding in index.bindings:
        assert parse_supported_embedding_binding(binding) == binding


@pytest.mark.parametrize(
    "case",
    (
        "duplicate_entry",
        "duplicate_binding",
        "missing_entry",
        "wrong_entry_family",
        "missing_shard",
        "duplicate_shard",
    ),
)
def test_mixed_materialized_closure_rejects_duplicate_or_foreign_values(case) -> None:
    entry, review_binding, shard, pointer, index = mixed_embedding_case()
    entries, bindings, shards = (embedding_entry(), entry), index.bindings, ((pointer, shard),)
    if case == "duplicate_entry":
        entries += (entry,)
    elif case == "duplicate_binding":
        bindings += (review_binding,)
    elif case == "missing_entry":
        entries = (embedding_entry(),)
    elif case == "wrong_entry_family":
        bindings = (review_binding,)
        entries = (embedding_entry(),)
    elif case == "missing_shard":
        shards = ()
    else:
        shards += shards
    with pytest.raises(INVALID):
        validate_mixed_embedding_source_bindings(bindings, entries, shards)


@pytest.mark.parametrize("field", ("space", "row", "parent", "member_sha"))
def test_mixed_index_references_reject_mismatched_materialization(field) -> None:
    _entry, _binding, shard, pointer, index = mixed_embedding_case()
    shards, parent = ((pointer, shard),), None
    if field == "space":
        body = shard.model_dump(mode="json")
        body["space"]["runtime"]["execution_runtime_sha256"] = "sha256:" + "f" * 64
        body["space"] = seal(body["space"], "space_sha256")
        shard = shard.model_copy(update={"space": shard.space.model_validate(body["space"])})
        shards = ((pointer, shard),)
    elif field == "row":
        original = index.bindings[0]
        bad = original.model_copy(
            update={"row_ref": original.row_ref.model_copy(update={"row_index": 1023})}
        )
        index = index.model_copy(update={"bindings": (bad, *index.bindings[1:])})
    elif field == "parent":
        parent = (pointer, index)
    else:
        shards = ((pointer.model_copy(update={"sha256": "sha256:" + "f" * 64}), shard),)
    with pytest.raises(INVALID):
        validate_mixed_embedding_index_references(index, shards, parent)


@pytest.mark.parametrize(
    "parser,value",
    (
        (parse_supported_embedding_entry, {"profile": {"schema_version": "unknown/1.0"}}),
        (parse_supported_embedding_binding, {"schema_version": "unknown/1.0"}),
        (parse_supported_embedding_index, {"schema_version": "unknown/1.0"}),
    ),
)
def test_explicit_mixed_dispatch_never_guesses_an_unknown_family(parser, value) -> None:
    with pytest.raises(INVALID):
        parser(value)
