"""Pure exact-index pairing after official resolution; never a source or compute grant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.embedding_index_families import parse_supported_embedding_index
from eom_catalog_contracts.embedding_model_recipe import same_embedding_payload_recipe
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    EmbeddingSpace,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    PublicSolutionEmbeddingIndex,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_registry_ports import SupportedEmbeddingIndex


class EmbeddingDeviceIndexPairError(ValueError):
    """An incomplete/incompatible pair is not permission to fall back to stale data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EmbeddingDeviceIndexPin:
    """Small owner-local resolved value; bytes, access and lifecycle remain owner checks."""

    index_id: str
    index_revision_id: str
    manifest: ArtifactMemberPointer
    index_sha256: str
    space: EmbeddingSpace


@dataclass(frozen=True, slots=True)
class EmbeddingDeviceIndexPair:
    """Pinned pair for one exact target snapshot, not a mutable current-index selector."""

    cpu: EmbeddingDeviceIndexPin
    cuda: EmbeddingDeviceIndexPin
    storage_partition: str
    view: ExperimentView
    recipe_sha256: str
    target_set_sha256: str
    target_count: int

    def select(self, device: Literal["CPU", "CUDA"]) -> EmbeddingDeviceIndexPin:
        if device == "CPU":
            return self.cpu
        if device == "CUDA":
            return self.cuda
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_DEVICE_INVALID")


def validate_resolved_embedding_index(
    pointer: ArtifactMemberPointer, index: SupportedEmbeddingIndex, device: str
) -> tuple[ArtifactMemberPointer, SupportedEmbeddingIndex]:
    """Reparse one pinned member/index pair; no store read or authority is inferred."""
    try:
        checked = parse_supported_embedding_index(raw_similarity_contract_value(index))
        member = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointer))
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_INVALID") from None
    if isinstance(checked, PublicSolutionEmbeddingIndex):
        expected_schema = PUBLIC_SOLUTION_INDEX_SCHEMA_REF
    elif isinstance(checked, MixedEmbeddingIndexManifest):
        expected_schema = MIXED_EMBEDDING_INDEX_SCHEMA_REF
    else:
        expected_schema = INDEX_SCHEMA_REF
    if (
        member.member_path != "index.json"
        or member.schema_ref != expected_schema
        or member.media_type != "application/json"
        or member.sha256 != content_sha256(checked.model_dump(mode="json"))
    ):
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_POINTER_MISMATCH")
    if checked.space.runtime.device != device:
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_DEVICE_MISMATCH")
    return member, checked


def canonical_embedding_index_targets(index: SupportedEmbeddingIndex) -> tuple[dict[str, Any], ...]:
    """Device-independent ordered source/profile/input identities for exact pairing."""
    # Runtime-dependent row/encoding identity must differ; every scientific source,
    # accepted analysis/review, Graph, policy, recipe and input-text hash must not.
    targets: list[dict[str, Any]] = []
    for binding in index.bindings:
        body = binding.model_dump(mode="json", exclude={"encoding", "row_ref", "binding_sha256"})
        targets.append(
            body
            | {
                "input_text_sha256": binding.encoding.input_text_sha256,
                "storage_partition": binding.encoding.storage_partition,
            }
        )
    return tuple(targets)


def pair_embedding_device_indexes(
    *,
    cpu_member: ArtifactMemberPointer,
    cpu_index: SupportedEmbeddingIndex,
    cuda_member: ArtifactMemberPointer,
    cuda_index: SupportedEmbeddingIndex,
) -> EmbeddingDeviceIndexPair:
    """O(n) closure over two already-resolved manifests, without reading any store.

    The calling Catalog owner must resolve/re-authorize both pinned members and their
    source population using the existing official contracts. Pairing is not a grant,
    an activation, a cross-device numeric equivalence claim or a latest lookup.
    """
    cpu_member, cpu_index = validate_resolved_embedding_index(cpu_member, cpu_index, "CPU")
    cuda_member, cuda_index = validate_resolved_embedding_index(cuda_member, cuda_index, "CUDA")
    if (
        type(cpu_index) is not type(cuda_index)
        or cpu_index.storage_partition != cuda_index.storage_partition
        or cpu_index.view != cuda_index.view
        or cpu_index.recipe != cuda_index.recipe
        or not same_embedding_payload_recipe(
            cpu_index.space.model_spec, cuda_index.space.model_spec
        )
        or cpu_index.space.space_sha256 == cuda_index.space.space_sha256
        or (
            cpu_member.artifact_id,
            cpu_member.artifact_revision_id,
            cpu_member.member_path,
        )
        == (
            cuda_member.artifact_id,
            cuda_member.artifact_revision_id,
            cuda_member.member_path,
        )
        or cpu_index.space.runtime.execution_runtime_sha256
        == cuda_index.space.runtime.execution_runtime_sha256
        or (
            cpu_index.space.model_spec.model_revision_id
            == cuda_index.space.model_spec.model_revision_id
            and cpu_index.space.model_spec.manifest_sha256
            != cuda_index.space.model_spec.manifest_sha256
        )
        or cpu_index.index_id == cuda_index.index_id
        or cpu_index.index_revision_id == cuda_index.index_revision_id
    ):
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_NAMESPACE_MISMATCH")
    cpu_targets, cuda_targets = (
        canonical_embedding_index_targets(cpu_index),
        canonical_embedding_index_targets(cuda_index),
    )
    if cpu_targets != cuda_targets:
        raise EmbeddingDeviceIndexPairError("EMBEDDING_DEVICE_INDEX_TARGET_SET_MISMATCH")
    return EmbeddingDeviceIndexPair(
        cpu=EmbeddingDeviceIndexPin(
            cpu_index.index_id,
            cpu_index.index_revision_id,
            cpu_member,
            cpu_index.index_sha256,
            cpu_index.space,
        ),
        cuda=EmbeddingDeviceIndexPin(
            cuda_index.index_id,
            cuda_index.index_revision_id,
            cuda_member,
            cuda_index.index_sha256,
            cuda_index.space,
        ),
        storage_partition=cpu_index.storage_partition,
        view=cpu_index.view,
        recipe_sha256=cpu_index.recipe.recipe_sha256,
        target_set_sha256=content_sha256(cpu_targets),
        target_count=len(cpu_targets),
    )
