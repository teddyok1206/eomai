"""Additive mixed-index registration; never authority or an implicit V1 upgrade."""

from __future__ import annotations

from typing import Literal

from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.embedding_registry import (
    MAX_EMBEDDING_REGISTRATION_BYTES,
    EmbeddingIndexId,
    EmbeddingIndexRevisionId,
    EmbeddingRegistrationOperationKey,
    validate_embedding_registration_hash,
    validate_embedding_registration_head,
    validate_embedding_registration_receipt_binding,
    validate_embedding_registration_receipt_head,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    StoragePartition,
    validate_embedding_manifest_pointer,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.mixed_embedding_index import MIXED_EMBEDDING_INDEX_SCHEMA_REF
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

MIXED_EMBEDDING_REGISTRY_SCHEMA = "embedding-registry-v2"


class MixedEmbeddingIndexNamespace(FrozenModel):
    """New immutable mixed namespace, not a reinterpretation of a historical index."""

    model_config = ConfigDict(revalidate_instances="always")
    storage_partition: StoragePartition
    space_sha256: Sha256
    view: ExperimentView
    recipe_sha256: Sha256
    projection_version: Literal["mixed-solution-comparison/2.0"] = "mixed-solution-comparison/2.0"
    population_scope: Literal["ALL_ADMITTED_GRAPH_ITEMS"]

    @model_validator(mode="before")
    @classmethod
    def exact_raw_value(cls, value: object) -> object:
        return raw_similarity_contract_value(value)

    def accepts_projection(self, projection_version: str) -> bool:
        return projection_version in {
            "accepted-solution-comparison/1.0",
            "registered-item-review-comparison/1.0",
        }


class _MixedRegistrationValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, MIXED_EMBEDDING_REGISTRY_SCHEMA, MAX_EMBEDDING_REGISTRATION_BYTES
        )


class RegisterEmbeddingIndexCommandV2(_MixedRegistrationValue):
    schema_version: Literal["embedding-registry-registration-command/2.0"] = (
        "embedding-registry-registration-command/2.0"
    )
    operation: Literal["REGISTER_EMBEDDING_INDEX"] = "REGISTER_EMBEDDING_INDEX"
    operation_key: EmbeddingRegistrationOperationKey
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: MixedEmbeddingIndexNamespace
    index_id: EmbeddingIndexId
    index_revision_id: EmbeddingIndexRevisionId
    index_manifest: ArtifactMemberPointer
    index_sha256: Sha256
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    expected_current_index_revision_id: EmbeddingIndexRevisionId | None
    expected_lock_version: int = Field(ge=1, strict=True)
    source_set_sha256: Sha256
    binding_set_sha256: Sha256
    eligible_source_count: int = Field(ge=1, le=1024, strict=True)
    binding_count: int = Field(ge=1, le=1024, strict=True)
    requested_at: UtcDatetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_registration_intent(self) -> RegisterEmbeddingIndexCommandV2:
        validate_embedding_manifest_pointer(
            self.index_manifest, MIXED_EMBEDDING_INDEX_SCHEMA_REF, "index.json"
        )
        validate_embedding_registration_head(
            graph_snapshot=self.graph_snapshot,
            index_revision_id=self.index_revision_id,
            expected_current_index_revision_id=self.expected_current_index_revision_id,
            expected_lock_version=self.expected_lock_version,
            binding_count=self.binding_count,
            eligible_source_count=self.eligible_source_count,
        )
        validate_embedding_registration_hash(self, "request_sha256")
        return self


class EmbeddingIndexRegistrationResultV2(_MixedRegistrationValue):
    schema_version: Literal["embedding-registry-registration-result/2.0"] = (
        "embedding-registry-registration-result/2.0"
    )
    operation_key: EmbeddingRegistrationOperationKey
    request_sha256: Sha256
    index_id: EmbeddingIndexId
    index_revision_id: EmbeddingIndexRevisionId
    previous_index_revision_id: EmbeddingIndexRevisionId | None
    index_manifest: ArtifactMemberPointer
    index_sha256: Sha256
    registered_lock_version: int = Field(ge=2, strict=True)
    current_index_revision_id: EmbeddingIndexRevisionId
    current_lock_version: int = Field(ge=2, strict=True)
    replayed: bool = Field(strict=True)
    is_current: bool = Field(strict=True)
    registered_at: UtcDatetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_registration_receipt(self) -> EmbeddingIndexRegistrationResultV2:
        validate_embedding_manifest_pointer(
            self.index_manifest, MIXED_EMBEDDING_INDEX_SCHEMA_REF, "index.json"
        )
        validate_embedding_registration_receipt_head(
            index_revision_id=self.index_revision_id,
            previous_index_revision_id=self.previous_index_revision_id,
            current_index_revision_id=self.current_index_revision_id,
            registered_lock_version=self.registered_lock_version,
            current_lock_version=self.current_lock_version,
            replayed=self.replayed,
            is_current=self.is_current,
        )
        validate_embedding_registration_hash(self, "result_sha256")
        return self


def parse_embedding_registration_command_v2(value: object) -> RegisterEmbeddingIndexCommandV2:
    return RegisterEmbeddingIndexCommandV2.model_validate(value)


def parse_embedding_registration_result_v2(value: object) -> EmbeddingIndexRegistrationResultV2:
    return EmbeddingIndexRegistrationResultV2.model_validate(value)


def validate_embedding_registration_result_v2(
    command: RegisterEmbeddingIndexCommandV2, result: EmbeddingIndexRegistrationResultV2
) -> EmbeddingIndexRegistrationResultV2:
    command = parse_embedding_registration_command_v2(command)
    result = parse_embedding_registration_result_v2(result)
    validate_embedding_registration_receipt_binding(command, result)
    return result
