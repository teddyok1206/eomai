"""Schema-first embedding identity/closure; synthetic metadata only, no encoder or storage."""

from __future__ import annotations

import ast
import copy
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import inference_transfer_embedding as contracts
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingEncodingIdentity,
    EmbeddingExecutionRuntime,
    EmbeddingSpace,
    EmbeddingTextInput,
    EmbeddingVectorRowRef,
    embedding_input_set_sha256,
    parse_embedding_binding,
    parse_embedding_index,
    parse_embedding_shard,
    parse_incremental_embedding_input,
    parse_incremental_embedding_result,
    validate_embedding_index_references,
    validate_embedding_source_binding,
    validate_incremental_embedding_result,
)
from eom_catalog_contracts.inference_transfer_experiment import StagedExperimentEntry
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    catalog_schema_registry,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import ValidationError

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_entry,
    embedding_input,
    embedding_result,
    embedding_space,
    encoding_identity,
    execution_runtime,
    index_manifest,
    index_pointer,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import sha

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAME = "item-inference-transfer-embedding"
ERRORS = (ValueError, JsonSchemaError)


def _body_with(
    body: dict[str, Any], path: tuple[str | int, ...], value: object, hash_field: str
) -> dict[str, Any]:
    changed = copy.deepcopy(body)
    target: Any = changed
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    return seal(changed, hash_field)


def test_schema_first_package_mirror_raw_hash_and_draft_are_exact() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[SCHEMA_NAME]
    canonical = ROOT / resource.canonical_path
    packaged = ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    payload = canonical.read_bytes()
    assert payload == packaged.read_bytes()
    assert sha256_bytes(payload) == resource.sha256
    schema = load_schema(SCHEMA_NAME)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_all_preexisting_schema_registry_metadata_and_resource_bytes_are_frozen() -> None:
    resources = {
        name: resource
        for name, resource in CATALOG_SCHEMA_RESOURCES.items()
        if name
        not in {
            SCHEMA_NAME,
            "embedding-registry",
            "embedding-runtime-bundle",
            "embedding-installed-runtime-proof",
            "embedding-device-benchmark",
            "embedding-native-runtime-config",
            "system-rag-similarity-context",
            "embedding-reference-query",
            "embedding-reference-query-input-v1.1",
            "embedding-native-cpu-probe",
            "education-retrieval-access-policy-v1.1",
        }
    }
    assert len(resources) == 296
    # Recorded from the pre-embedding registry, independently compared with HEAD's AST literals.
    # This regression uses package metadata and files only, never runtime Git or source discovery.
    assert content_sha256({name: asdict(resource) for name, resource in resources.items()}) == (
        "sha256:9f761ee9483774a515d122de175018dfb20ec430bcdec2952dde94118619a625"
    )
    for name, resource in resources.items():
        canonical = (ROOT / resource.canonical_path).read_bytes()
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
        assert canonical == packaged, name
        assert sha256_bytes(canonical) == resource.sha256, name


def test_inlined_artifact_member_schema_matches_existing_protocol_constraints() -> None:
    canonical = (ROOT / "schemas/artifact-member/artifact-member-v1.schema.json").read_bytes()
    packaged = (
        ROOT / "packages/protocol/eom_protocol/schemas/artifact-member-v1.schema.json"
    ).read_bytes()
    assert canonical == packaged
    protocol = json.loads(canonical)
    assert protocol["$id"] == "eom://schemas/artifact-member/1.0"
    schema = load_schema(SCHEMA_NAME)
    inline = copy.deepcopy(schema["$defs"]["artifactMember"])
    assert inline["properties"]["sha256"]["$ref"] == schema["$id"] + "#/$defs/hash"
    inline["properties"]["sha256"] = schema["$defs"]["hash"]
    inline.pop("description")
    assert inline == {
        name: value for name, value in protocol.items() if name not in {"$schema", "$id", "title"}
    }


@pytest.mark.parametrize("member_path", ["../shard.json", "/shard.json", "a//b", "a\\b", "a\x00b"])
def test_inlined_protocol_and_typed_pointer_all_reject_unsafe_members(member_path: str) -> None:
    document = shard_pointer(vector_shard()).model_dump(mode="json")
    document["member_path"] = member_path
    schema = load_schema(SCHEMA_NAME)
    inline = schema["$defs"]["artifactMember"]
    protocol = json.loads(
        (ROOT / "schemas/artifact-member/artifact-member-v1.schema.json").read_bytes()
    )
    with pytest.raises(JsonSchemaError):
        Draft202012Validator(inline, registry=catalog_schema_registry()).validate(document)
    with pytest.raises(JsonSchemaError):
        Draft202012Validator(protocol).validate(document)
    with pytest.raises(ValueError):
        ArtifactMemberPointer.model_validate(document)


@pytest.mark.parametrize(
    "reference",
    [
        SHARD_SCHEMA_REF,
        INDEX_SCHEMA_REF,
        "eom://schemas/knowledge/embedding-source-binding/1.0",
        "eom://schemas/knowledge/incremental-embedding-input/1.0",
        "eom://schemas/knowledge/incremental-embedding-result/1.0",
    ],
)
def test_nested_resource_uris_resolve_in_offline_catalog_registry(reference: str) -> None:
    resolved = catalog_schema_registry().resolver().lookup(reference).contents
    assert resolved["$id"] == reference


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "item-inference-transfer",
            "sha256:79e197f598d5fadea0ef757208bd01f05783e83499317680ee804f43600fdff2",
        ),
        (
            "item-inference-transfer-experiment",
            "sha256:becaa7e8281f429267ba9cdcfb03129a5f51ecf53f06b4fcfdf7b9b0789df91b",
        ),
        (
            "item-inference-transfer-pair-result-v1.1",
            "sha256:5dd12768a41eef7d91edfbeb9effc399f2ad7525306f213bb945c3c7a3ec1451",
        ),
    ],
)
def test_released_predecessor_resources_remain_unchanged(name: str, expected: str) -> None:
    resource = CATALOG_SCHEMA_RESOURCES[name]
    assert resource.sha256 == expected
    assert sha256_bytes((ROOT / resource.canonical_path).read_bytes()) == expected


@pytest.mark.parametrize(
    "factory,parser",
    [
        (vector_shard, parse_embedding_shard),
        (source_binding, parse_embedding_binding),
        (index_manifest, parse_embedding_index),
        (embedding_input, parse_incremental_embedding_input),
        (embedding_result, parse_incremental_embedding_result),
    ],
)
def test_closed_frozen_values_roundtrip_without_input_mutation(
    factory: Callable[[], Any], parser: Callable[[dict[str, Any]], Any]
) -> None:
    original = factory()
    document = original.model_dump(mode="json")
    before = copy.deepcopy(document)
    validate_contract(SCHEMA_NAME, document)
    parsed = parser(document)
    assert parsed == original
    assert document == before
    assert canonical_json_bytes(parsed.model_dump(mode="json")) == canonical_json_bytes(before)
    with pytest.raises(ValidationError):
        parsed.schema_version = "altered"


@pytest.mark.parametrize("tf32", [True, 0, 1, None, "false"])
def test_runtime_tf32_is_exact_false_not_coerced(tf32: object) -> None:
    body = execution_runtime().model_dump(mode="json") | {"tf32_enabled": tf32}
    with pytest.raises(ValueError):
        EmbeddingExecutionRuntime.model_validate(body)


def test_cpu_cuda_purpose_and_runtime_build_have_distinct_encoding_spaces() -> None:
    cpu = embedding_space()
    cuda = embedding_space(device="CUDA")
    query = embedding_space(purpose="QUERY")
    rebuilt = embedding_space(fingerprint=sha("f"))
    spaces = (cpu, cuda, query, rebuilt)
    assert len({space.space_sha256 for space in spaces}) == len(spaces)
    assert len({encoding_identity("同じ入力", space).encoding_sha256 for space in spaces}) == 4
    assert all(space.model_spec == cpu.model_spec for space in spaces)


def test_storage_partition_and_exact_input_are_separate_identity_dimensions() -> None:
    shared = encoding_identity("마찰이 없다.")
    private = encoding_identity("마찰이 없다.", storage_partition="synthetic-private")
    changed = encoding_identity("마찰이 있다.")
    assert shared.space_sha256 == private.space_sha256 == changed.space_sha256
    assert shared.input_text_sha256 == private.input_text_sha256
    assert len({value.encoding_sha256 for value in (shared, private, changed)}) == 3


def test_correct_supplied_hashes_are_not_recalculated_or_repaired() -> None:
    body = embedding_space().model_dump(mode="json")
    body["model_spec"]["manifest_sha256"] = sha("f")
    with pytest.raises(ValueError):
        EmbeddingSpace.model_validate(seal(body, "space_sha256"))
    encoding = encoding_identity("exact text").model_dump(mode="json")
    encoding["encoding_sha256"] = sha("f")
    before = copy.deepcopy(encoding)
    with pytest.raises(ValueError):
        EmbeddingEncodingIdentity.model_validate(encoding)
    assert encoding == before


@pytest.mark.parametrize(
    "factory,parser,hash_field",
    [
        (vector_shard, parse_embedding_shard, "shard_sha256"),
        (source_binding, parse_embedding_binding, "binding_sha256"),
        (index_manifest, parse_embedding_index, "index_sha256"),
        (embedding_input, parse_incremental_embedding_input, "request_sha256"),
        (embedding_result, parse_incremental_embedding_result, "result_sha256"),
    ],
)
@pytest.mark.parametrize("failure", ["missing", "null", "wrong"])
def test_required_self_hash_is_never_derived_for_untrusted_embedding_messages(
    factory: Callable[[], Any],
    parser: Callable[[dict[str, Any]], Any],
    hash_field: str,
    failure: str,
) -> None:
    body = factory().model_dump(mode="json")
    if failure == "missing":
        del body[hash_field]
    else:
        body[hash_field] = None if failure == "null" else sha("f")
    before = copy.deepcopy(body)
    with pytest.raises(ERRORS):
        parser(body)
    assert body == before


@pytest.mark.parametrize(
    "path,value",
    [
        (("dimension",), 383),
        (("dimension",), True),
        (("row_count",), 2),
        (("row_count",), True),
        (("binary", "byte_count"), 1535),
        (("binary", "dtype"), "FLOAT16"),
        (("binary", "byte_order"), "BIG_ENDIAN"),
        (("binary", "layout"), "COLUMN_MAJOR"),
        (("binary", "member_path"), "../vectors.f32"),
        (("binary", "media_type"), "application/json"),
        (("input_set_sha256",), sha("f")),
    ],
)
def test_shard_shape_format_and_input_closure_remain_strict(
    path: tuple[str | int, ...], value: object
) -> None:
    body = _body_with(vector_shard().model_dump(mode="json"), path, value, "shard_sha256")
    with pytest.raises(ERRORS):
        parse_embedding_shard(body)


@pytest.mark.parametrize("failure", ["empty", "duplicate", "reverse", "foreign_space"])
def test_shard_rows_are_nonempty_unique_ordered_and_bound_to_one_space(failure: str) -> None:
    request = embedding_input("첫째 입력", "둘째 입력")
    body = vector_shard(tuple(row.encoding for row in request.rows)).model_dump(mode="json")
    if failure == "empty":
        body["rows"] = []
    elif failure == "duplicate":
        body["rows"] = [body["rows"][0], body["rows"][0]]
    elif failure == "reverse":
        body["rows"].reverse()
    else:
        body["rows"][0] = encoding_identity(
            "첫째 입력", embedding_space(purpose="QUERY")
        ).model_dump(mode="json")
    with pytest.raises(ERRORS):
        parse_embedding_shard(seal(body, "shard_sha256"))


def test_binary_vectors_are_not_canonical_json_numbers_or_inline_metadata() -> None:
    with pytest.raises(TypeError, match="floats"):
        canonical_json_bytes({"vectors": [[0.5]]})
    body = vector_shard().model_dump(mode="json") | {"vectors": [[1]]}
    with pytest.raises(ERRORS):
        parse_embedding_shard(seal(body, "shard_sha256"))


@pytest.mark.parametrize("text", ["", " \n\t", "unsafe\x00text", "x" * 262145])
def test_encoding_input_requires_bounded_safe_exact_text(text: str) -> None:
    with pytest.raises(ValueError):
        EmbeddingTextInput(encoding=encoding_identity(text), text=text)


def test_text_hash_mismatch_does_not_normalize_negation_units_or_content() -> None:
    text = "마찰이 없고 속력은 36 km/h이다."
    body = {"encoding": encoding_identity(text).model_dump(mode="json"), "text": text + " 변경"}
    before = copy.deepcopy(body)
    with pytest.raises(ValueError):
        EmbeddingTextInput.model_validate(body)
    assert body == before


def test_incremental_input_accepts_document_purpose_only() -> None:
    with pytest.raises(ValueError):
        embedding_input(space=embedding_space(purpose="QUERY"))


@pytest.mark.parametrize("field,value", [("batch_size", 17), ("threads", 0), ("threads", True)])
def test_execution_limits_are_strict_small_integers(field: str, value: object) -> None:
    body = embedding_input().model_dump(mode="json") | {field: value}
    with pytest.raises(ERRORS):
        parse_incremental_embedding_input(seal(body, "request_sha256"))


def test_incremental_result_requires_exact_request_identity_and_rows() -> None:
    request = embedding_input("첫째 입력", "둘째 입력")
    result = embedding_result(request)
    validate_incremental_embedding_result(request, result)
    other = embedding_input("다른 입력", job_id="job_" + "2" * 32)
    foreign = embedding_result(other)
    with pytest.raises(ERRORS):
        validate_incremental_embedding_result(request, foreign)
    wrong_rows = embedding_result()
    with pytest.raises(ERRORS):
        validate_incremental_embedding_result(request, wrong_rows)


def test_model_copy_cannot_bypass_request_or_result_validation() -> None:
    request = embedding_input()
    result = embedding_result(request)
    changed_row = request.rows[0].model_copy(update={"text": "model-copy altered text"})
    forged_request = request.model_copy(update={"rows": (changed_row,)})
    with pytest.raises(ERRORS):
        validate_incremental_embedding_result(forged_request, result)
    with pytest.raises(ERRORS):
        validate_incremental_embedding_result(
            request, result.model_copy(update={"result_sha256": sha("f")})
        )


@pytest.mark.parametrize("view", ["CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"])
def test_source_binding_preserves_exact_entry_view_and_pinned_shard(view: Any) -> None:
    staged = embedding_entry()
    binding = source_binding(staged, view=view)
    shard = vector_shard((binding.encoding,))
    pointer = shard_pointer(shard)
    validate_embedding_source_binding(binding, staged, pointer, shard)
    assert binding.source == staged.profile.source_basis.source
    assert binding.solution_evidence == staged.profile.source_basis.solution_evidence
    assert pointer.sha256 != shard.shard_sha256


@pytest.mark.parametrize(
    "path,value",
    [
        (("profile", "profile_sha256"), sha("f")),
        (("source", "item_revision_id"), "itemrev_" + "f" * 32),
        (("graph_snapshot", "graph_snapshot_revision_id"), "graphrev_" + "f" * 32),
        (("row_ref", "row_index"), 1),
        (("row_ref", "shard_manifest", "artifact_revision_id"), "rev_" + "f" * 32),
        (("row_ref", "shard_manifest", "sha256"), sha("f")),
    ],
)
def test_binding_cannot_dereference_foreign_source_row_or_artifact_revision(
    path: tuple[str | int, ...], value: object
) -> None:
    staged = embedding_entry()
    binding = source_binding(staged)
    shard = vector_shard((binding.encoding,))
    pointer = shard_pointer(shard)
    body = _body_with(binding.model_dump(mode="json"), path, value, "binding_sha256")
    with pytest.raises(ERRORS):
        changed = parse_embedding_binding(body)
        validate_embedding_source_binding(changed, staged, pointer, shard)


@pytest.mark.parametrize(
    "field,value", [("schema_ref", INDEX_SCHEMA_REF), ("member_path", "index.json")]
)
def test_row_reference_requires_the_exact_shard_pointer_contract(field: str, value: str) -> None:
    body = source_binding().row_ref.model_dump(mode="json")
    body["shard_manifest"][field] = value
    with pytest.raises(ValueError):
        EmbeddingVectorRowRef.model_validate(body)


def test_graph_only_reassociation_reuses_encoding_without_merging_source_identity() -> None:
    original = embedding_entry()
    body = original.model_dump(mode="json")
    graph = body["profile"]["source_basis"]["graph_snapshot"]
    graph["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    graph["manifest_sha256"] = sha("f")
    graph["manifest_artifact"].update(artifact_revision_id="rev_" + "f" * 32, sha256=sha("f"))
    body["profile"]["profile_revision_id"] = "inferenceprofilerev_" + "f" * 32
    body["profile"] = seal(body["profile"], "profile_sha256")
    changed = StagedExperimentEntry.model_validate(body)
    first, again = source_binding(original), source_binding(changed)
    assert first.encoding == again.encoding
    assert first.row_ref == again.row_ref
    assert first.profile.profile_id == again.profile.profile_id
    assert first.profile.profile_revision_id != again.profile.profile_revision_id
    assert first.profile.profile_sha256 != again.profile.profile_sha256
    assert first.binding_sha256 != again.binding_sha256
    shard = vector_shard((first.encoding,))
    validate_embedding_source_binding(again, changed, shard_pointer(shard), shard)


def test_distinct_sources_can_share_one_vector_without_duplicate_artifacts() -> None:
    left, right = source_binding(embedding_entry("a")), source_binding(embedding_entry("b"))
    assert left.encoding == right.encoding
    assert left.source.item_revision_id != right.source.item_revision_id
    assert left.binding_sha256 != right.binding_sha256
    index = index_manifest(left, right)
    shard = vector_shard((left.encoding,))
    assert len(index.shards) == 1
    validate_embedding_index_references(index, ((shard_pointer(shard), shard),))


@pytest.mark.parametrize("failure", ["duplicate_binding", "duplicate_shard", "foreign_partition"])
def test_index_rejects_ambiguous_membership_or_partition(failure: str) -> None:
    index = index_manifest()
    body = index.model_dump(mode="json")
    if failure == "duplicate_binding":
        body["bindings"].append(body["bindings"][0])
    elif failure == "duplicate_shard":
        body["shards"].append(body["shards"][0])
    else:
        body["storage_partition"] = "foreign-partition"
    with pytest.raises(ERRORS):
        parse_embedding_index(seal(body, "index_sha256"))


def test_index_resolution_requires_exact_shards_not_missing_latest_or_forged_models() -> None:
    binding = source_binding()
    index = index_manifest(binding)
    shard = vector_shard((binding.encoding,))
    pointer = shard_pointer(shard)
    validate_embedding_index_references(index, ((pointer, shard),))
    with pytest.raises(ERRORS):
        validate_embedding_index_references(index, ())
    wrong = pointer.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32})
    with pytest.raises(ERRORS):
        validate_embedding_index_references(index, ((wrong, shard),))
    with pytest.raises(ERRORS):
        validate_embedding_index_references(
            index, ((pointer, shard.model_copy(update={"shard_sha256": sha("f")})),)
        )
    with pytest.raises(ERRORS):
        validate_embedding_index_references(
            index.model_copy(update={"index_sha256": sha("f")}), ((pointer, shard),)
        )


def test_previous_index_is_pinned_and_must_be_resolved_explicitly() -> None:
    original = index_manifest()
    previous = index_pointer(original)
    child = index_manifest(previous_manifest=previous, revision_seed="3")
    shard = vector_shard((child.bindings[0].encoding,))
    shards = ((shard_pointer(shard), shard),)
    validate_embedding_index_references(child, shards, previous=(previous, original))
    with pytest.raises(ERRORS):
        validate_embedding_index_references(child, shards)
    foreign = previous.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32})
    with pytest.raises(ERRORS):
        validate_embedding_index_references(child, shards, previous=(foreign, original))
    with pytest.raises(ERRORS):
        validate_embedding_index_references(original, shards, previous=(previous, original))


@pytest.mark.parametrize(
    "field", ["actor_id", "permissions", "storage_uri", "worker_prompt", "nas_path"]
)
def test_worker_input_does_not_accept_authority_paths_or_arbitrary_metadata(field: str) -> None:
    body = embedding_input().model_dump(mode="json") | {field: "forbidden"}
    with pytest.raises(ERRORS):
        parse_incremental_embedding_input(seal(body, "request_sha256"))


def test_input_set_hash_preserves_order_and_has_no_runtime_source_lookup() -> None:
    request = embedding_input("first", "second")
    identities = tuple(row.encoding for row in request.rows)
    assert embedding_input_set_sha256(identities) == content_sha256(
        [identity.model_dump(mode="json") for identity in identities]
    )
    assert request.input_set_sha256 != content_sha256(
        [identity.model_dump(mode="json") for identity in reversed(identities)]
    )
    assert all(identity.storage_partition == PARTITION for identity in identities)


def test_embedding_contracts_do_not_import_infrastructure_or_numerical_runtime() -> None:
    assert contracts.__file__ is not None
    tree = ast.parse(Path(contracts.__file__).read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = (
        "eom_catalog_service",
        "eom_orchestrator",
        "sqlalchemy",
        "numpy",
        "torch",
        "subprocess",
        "requests",
        "httpx",
    )
    assert not any(name.startswith(forbidden) for name in imports)
