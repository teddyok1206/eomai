"""Synthetic manifest pairing; not real corpus access, GPU execution or activation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_model_recipe import same_embedding_payload_recipe
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingIndexManifest,
    EmbeddingSpace,
)
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
)
from eom_catalog_service.embedding_device_index_pair import (
    EmbeddingDeviceIndexPairError,
    pair_embedding_device_indexes,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    embedding_space,
    index_manifest,
    index_pointer,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
)
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case


def _index(
    device: Literal["CPU", "CUDA"],
    *seeds: str,
    space: EmbeddingSpace | None = None,
) -> EmbeddingIndexManifest:
    actual_space = space or embedding_space(device=device)
    index = index_manifest(
        *(source_binding(embedding_entry(seed), space=actual_space) for seed in seeds or ("a",)),
        space=actual_space,
        revision_seed="2" if device == "CPU" else "3",
    )
    body = index.model_dump(mode="json")
    body["index_id"] = "embeddingindex_" + ("2" if device == "CPU" else "3") * 32
    return EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))


def _pair(cpu: EmbeddingIndexManifest, cuda: EmbeddingIndexManifest, **changes: Any):
    arguments = {
        "cpu_member": index_pointer(cpu, "4"),
        "cpu_index": cpu,
        "cuda_member": index_pointer(cuda, "5"),
        "cuda_index": cuda,
    }
    return pair_embedding_device_indexes(**(arguments | changes))


def test_exact_device_pair_preserves_actual_spaces_and_small_pointers() -> None:
    cpu, cuda = _index("CPU", "a", "b"), _index("CUDA", "a", "b")
    pair = _pair(cpu, cuda)
    assert pair.target_count == 2
    assert pair.select("CPU").space == cpu.space
    assert pair.select("CUDA").space == cuda.space
    assert pair.cpu.space != pair.cuda.space
    assert pair.cpu.index_revision_id != pair.cuda.index_revision_id
    assert pair.cpu.manifest == index_pointer(cpu, "4")
    assert not hasattr(pair, "bindings") and not hasattr(pair, "vectors")
    assert pair == _pair(cpu, cuda)
    with pytest.raises(FrozenInstanceError):
        pair.target_count = 3  # type: ignore[misc]
    with pytest.raises(EmbeddingDeviceIndexPairError, match="DEVICE_INVALID"):
        pair.select("GPU")  # type: ignore[arg-type]


@pytest.mark.parametrize("seeds", [("a",), ("a", "c"), ("b", "c")])
def test_different_or_incomplete_target_population_is_not_a_stale_fallback(seeds) -> None:
    with pytest.raises(EmbeddingDeviceIndexPairError, match="TARGET_SET_MISMATCH"):
        _pair(_index("CPU", "a", "b"), _index("CUDA", *seeds))


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_sha256", "sha256:" + "9" * 64),
        ("policy_revision_id", "accessrev_" + "9" * 32),
    ],
)
def test_same_source_ids_do_not_hide_changed_policy_evidence(field: str, value: str) -> None:
    cuda = _index("CUDA")
    body = cuda.model_dump(mode="json")
    binding = body["bindings"][0]
    binding[field] = value
    body["bindings"][0] = seal(binding, "binding_sha256")
    cuda = EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    with pytest.raises(EmbeddingDeviceIndexPairError, match="TARGET_SET_MISMATCH"):
        _pair(_index("CPU"), cuda)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "sha256:" + "9" * 64),
        ("member_path", "different.json"),
        ("media_type", "application/octet-stream"),
        ("schema_ref", "eom://schemas/knowledge/embedding-index-manifest/2.0"),
    ],
)
def test_mismatched_pointer_never_resolves_another_member(field: str, value: str) -> None:
    cpu, cuda = _index("CPU"), _index("CUDA")
    pointer = index_pointer(cuda, "5").model_copy(update={field: value})
    with pytest.raises(EmbeddingDeviceIndexPairError, match="POINTER_MISMATCH"):
        _pair(cpu, cuda, cuda_member=pointer)


def test_cpu_cannot_be_labelled_cuda_and_forged_models_are_revalidated() -> None:
    cpu, cuda = _index("CPU"), _index("CUDA")
    with pytest.raises(EmbeddingDeviceIndexPairError, match="DEVICE_MISMATCH"):
        _pair(cpu, cpu)
    forged = cuda.model_copy(update={"index_sha256": "sha256:" + "9" * 64})
    with pytest.raises(EmbeddingDeviceIndexPairError, match="INDEX_INVALID"):
        _pair(cpu, forged)


def test_same_logical_index_cannot_span_distinct_device_namespaces() -> None:
    cpu, cuda = _index("CPU"), _index("CUDA")
    body = cuda.model_dump(mode="json")
    body["index_id"] = cpu.index_id
    cuda = EmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    with pytest.raises(EmbeddingDeviceIndexPairError, match="NAMESPACE_MISMATCH"):
        _pair(cpu, cuda)


def test_runtime_specific_model_revision_is_allowed_but_payload_changes_are_not() -> None:
    cpu = _index("CPU")
    body = cpu.space.model_spec.model_dump(mode="json")
    body["model_revision_id"] = "embeddingmodelrev_" + "9" * 32
    body["runtime_versions"][0]["version"] = "2.0.0"
    spec = LocalEmbeddingModelSpec.model_validate(seal(body, "manifest_sha256"))
    assert same_embedding_payload_recipe(cpu.space.model_spec, spec)
    space_body = embedding_space(device="CUDA").model_dump(mode="json")
    space_body["model_spec"] = spec.model_dump(mode="json")
    cuda_space = EmbeddingSpace.model_validate(seal(space_body, "space_sha256"))
    assert _pair(cpu, _index("CUDA", space=cuda_space)).target_count == 1

    body["files"][0]["sha256"] = "sha256:" + "9" * 64
    spec = LocalEmbeddingModelSpec.model_validate(seal(body, "manifest_sha256"))
    assert not same_embedding_payload_recipe(cpu.space.model_spec, spec)
    space_body["model_spec"] = spec.model_dump(mode="json")
    cuda_space = EmbeddingSpace.model_validate(seal(space_body, "space_sha256"))
    with pytest.raises(EmbeddingDeviceIndexPairError, match="NAMESPACE_MISMATCH"):
        _pair(cpu, _index("CUDA", space=cuda_space))


def test_shared_recipe_comparison_revalidates_even_constructed_models() -> None:
    model = embedding_space().model_spec
    forged = model.model_copy(update={"manifest_sha256": "sha256:" + "9" * 64})
    with pytest.raises(ValueError):
        same_embedding_payload_recipe(model, forged)
    assert same_embedding_payload_recipe(model, model)
    assert content_sha256(model.model_dump(mode="json")) != model.manifest_sha256


@pytest.mark.parametrize("kind", ["string", "float"])
def test_shared_recipe_rejects_serialization_changing_scalar_coercion(kind: str) -> None:
    model = embedding_space().model_spec
    value = str(model.maximum_tokens) if kind == "string" else float(model.maximum_tokens)
    with pytest.raises(ValueError, match="noncanonical"):
        same_embedding_payload_recipe(model, model.model_copy(update={"maximum_tokens": value}))


def test_same_immutable_artifact_member_cannot_have_cpu_and_cuda_hashes() -> None:
    cpu, cuda = _index("CPU"), _index("CUDA")
    original = index_pointer(cpu, "4")
    collision = index_pointer(cuda, "5").model_copy(
        update={
            "artifact_id": original.artifact_id,
            "artifact_revision_id": original.artifact_revision_id,
        }
    )
    assert original.sha256 != collision.sha256
    with pytest.raises(EmbeddingDeviceIndexPairError, match="NAMESPACE_MISMATCH"):
        _pair(cpu, cuda, cuda_member=collision)


@pytest.mark.parametrize("target", ["index", "nested_model", "pointer", "recipe"])
def test_undeclared_copied_fields_are_rejected_instead_of_serialized_away(target: str) -> None:
    cpu, cuda = _index("CPU"), _index("CUDA")
    changes: dict[str, Any] = {}
    if target == "index":
        cuda = cuda.model_copy(update={"injected": "not part of canonical content"})
    elif target == "nested_model":
        model = cuda.space.model_spec.model_copy(update={"injected": "not part of recipe"})
        cuda = cuda.model_copy(
            update={"space": cuda.space.model_copy(update={"model_spec": model})}
        )
        with pytest.raises(ValueError):
            same_embedding_payload_recipe(cpu.space.model_spec, model)
    elif target == "pointer":
        changes["cuda_member"] = index_pointer(cuda, "5").model_copy(update={"injected": True})
    else:
        cuda = cuda.model_copy(update={"recipe": cuda.recipe.model_copy(update={"injected": True})})
    with pytest.raises(EmbeddingDeviceIndexPairError, match="INDEX_INVALID"):
        _pair(cpu, cuda, **changes)


def test_mixed_registered_review_and_past_exam_pair_preserves_evidence_family() -> None:
    cpu = mixed_embedding_case()[-1]
    cuda_space = embedding_space(device="CUDA")
    encodings = tuple(
        EmbeddingEncodingIdentity.model_validate(
            seal(
                binding.encoding.model_dump(mode="json")
                | {"space_sha256": cuda_space.space_sha256},
                "encoding_sha256",
            )
        )
        for binding in cpu.bindings
    )
    shard = vector_shard(encodings, space=cuda_space)
    pointer = shard_pointer(shard, "f")
    positions = {row.encoding_sha256: index for index, row in enumerate(shard.rows)}
    bindings = []
    for binding, encoding in zip(cpu.bindings, encodings, strict=True):
        body = binding.model_dump(mode="json") | {
            "encoding": encoding.model_dump(mode="json"),
            "row_ref": {
                "shard_manifest": pointer.model_dump(mode="json"),
                "row_index": positions[encoding.encoding_sha256],
                "encoding_sha256": encoding.encoding_sha256,
            },
        }
        bindings.append(seal(body, "binding_sha256"))
    body = cpu.model_dump(mode="json") | {
        "index_id": "embeddingindex_" + "f" * 32,
        "index_revision_id": "embeddingindexrev_" + "f" * 32,
        "space": cuda_space.model_dump(mode="json"),
        "shards": [pointer.model_dump(mode="json")],
        "bindings": bindings,
    }
    cuda = MixedEmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))

    def member(index: MixedEmbeddingIndexManifest, seed: str) -> ArtifactMemberPointer:
        return ArtifactMemberPointer(
            artifact_id="artifact_" + seed * 32,
            artifact_revision_id="rev_" + seed * 32,
            member_path="index.json",
            schema_ref=MIXED_EMBEDDING_INDEX_SCHEMA_REF,
            media_type="application/json",
            sha256=content_sha256(index.model_dump(mode="json")),
        )

    arguments = {
        "cpu_index": cpu,
        "cuda_index": cuda,
        "cpu_member": member(cpu, "a"),
        "cuda_member": member(cuda, "b"),
    }
    pair = pair_embedding_device_indexes(**arguments)
    assert pair.target_count == 2
    assert pair.view == "CONCRETE_FACETS"
    assert pair.cuda.manifest.schema_ref == MIXED_EMBEDDING_INDEX_SCHEMA_REF

    # Equal item IDs alone cannot conceal a changed registered-review base analysis.
    position = next(
        index for index, binding in enumerate(body["bindings"]) if "base_analysis_run_id" in binding
    )
    body["bindings"][position]["base_analysis_run_id"] = "analysisrun_" + "9" * 32
    body["bindings"][position] = seal(body["bindings"][position], "binding_sha256")
    changed = MixedEmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    with pytest.raises(EmbeddingDeviceIndexPairError, match="TARGET_SET_MISMATCH"):
        pair_embedding_device_indexes(
            **(arguments | {"cuda_index": changed, "cuda_member": member(changed, "b")})
        )
