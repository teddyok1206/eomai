"""Bounded pointer-only registration intent; actual owner authority is external."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.inference_transfer_embedding import INDEX_SCHEMA_REF, StoragePartition
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

EMBEDDING_REGISTRY_SCHEMA = "embedding-registry"
MAX_EMBEDDING_REGISTRATION_BYTES = 64 * 1024
type EmbeddingIndexId = Annotated[str, Field(pattern=r"^embeddingindex_[0-9a-f]{32}$")]
type EmbeddingIndexRevisionId = Annotated[str, Field(pattern=r"^embeddingindexrev_[0-9a-f]{32}$")]
type EmbeddingRegistrationOperationKey = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
]


class _RegistryContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")


def validate_embedding_registration_hash(value: FrozenModel, field: str) -> None:
    document = value.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > MAX_EMBEDDING_REGISTRATION_BYTES:
        raise ValueError("embedding registration exceeds its metadata byte bound")
    if getattr(value, field) != content_sha256(value.model_dump(mode="json", exclude={field})):
        raise ValueError("embedding registration canonical hash differs")


def validate_embedding_registration_head(
    *,
    graph_snapshot: KnowledgeGraphSnapshotPointer,
    index_revision_id: str,
    expected_current_index_revision_id: str | None,
    expected_lock_version: int,
    binding_count: int,
    eligible_source_count: int,
) -> None:
    """Common immutable Graph, coverage and CAS intent rules after schema validation."""
    graph = KnowledgeGraphSnapshotPointer.model_validate(graph_snapshot.model_dump(mode="json"))
    if graph.manifest_artifact.sha256 != graph.manifest_sha256:
        raise ValueError("embedding registration Graph manifest hash differs")
    if expected_current_index_revision_id == index_revision_id:
        raise ValueError("embedding registration cannot advance to its predecessor")
    if (expected_current_index_revision_id is None and expected_lock_version != 1) or (
        expected_current_index_revision_id is not None and expected_lock_version < 2
    ):
        raise ValueError("embedding registration current pointer/version differ")
    if binding_count > eligible_source_count:
        raise ValueError("embedding registration coverage exceeds its denominator")


def validate_embedding_registration_receipt_head(
    *,
    index_revision_id: str,
    previous_index_revision_id: str | None,
    current_index_revision_id: str,
    registered_lock_version: int,
    current_lock_version: int,
    replayed: bool,
    is_current: bool,
) -> None:
    """Common new/replayed receipt rules; never authorize or roll back a head."""
    if previous_index_revision_id == index_revision_id:
        raise ValueError("embedding registration receipt predecessor is self")
    if is_current != (current_index_revision_id == index_revision_id):
        raise ValueError("embedding registration receipt current selection differs")
    if current_lock_version < registered_lock_version:
        raise ValueError("embedding registration receipt version moved backwards")
    if is_current and current_lock_version != registered_lock_version:
        raise ValueError("current embedding registration receipt has a different generation")
    if not is_current and (not replayed or current_lock_version <= registered_lock_version):
        raise ValueError("historical embedding registration receipt requires a newer head")
    if not replayed and (not is_current or current_lock_version != registered_lock_version):
        raise ValueError("new embedding registration receipt must identify its current head")


def validate_embedding_registration_receipt_binding(
    command: FrozenModel, result: FrozenModel
) -> None:
    """Shared exact identity closure after each caller validates its released family."""
    request_values = command.model_dump(mode="python")
    receipt_values = result.model_dump(mode="python")
    fields = (
        "operation_key",
        "request_sha256",
        "index_id",
        "index_revision_id",
        "index_manifest",
        "index_sha256",
    )
    if any(receipt_values[field] != request_values[field] for field in fields) or (
        receipt_values["previous_index_revision_id"]
        != request_values["expected_current_index_revision_id"]
        or receipt_values["registered_lock_version"] != request_values["expected_lock_version"] + 1
    ):
        raise ValueError("embedding registration receipt differs from its exact command")


def _index_pointer(value: ArtifactMemberPointer) -> None:
    pointer = ArtifactMemberPointer.model_validate(value.model_dump(mode="json"))
    if (
        pointer.member_path != "index.json"
        or pointer.schema_ref != INDEX_SCHEMA_REF
        or pointer.media_type != "application/json"
    ):
        raise ValueError("embedding registration index member contract differs")


class EmbeddingIndexNamespace(_RegistryContract):
    """One immutable selection namespace; no access role or permission claim."""

    storage_partition: StoragePartition
    space_sha256: Sha256
    view: ExperimentView
    recipe_sha256: Sha256
    projection_version: Literal["accepted-solution-comparison/1.0"] = (
        "accepted-solution-comparison/1.0"
    )
    population_scope: Literal["ALL_ADMITTED_GRAPH_ITEMS", "OCCURRENCE_BACKED_PAST_EXAM"]

    def accepts_projection(self, projection_version: str) -> bool:
        return projection_version == self.projection_version


class RegisterEmbeddingIndexCommand(_RegistryContract):
    """Server-built intent, not proof of source access or Artifact validation."""

    schema_version: Literal["embedding-registry-registration-command/1.0"] = (
        "embedding-registry-registration-command/1.0"
    )
    operation: Literal["REGISTER_EMBEDDING_INDEX"] = "REGISTER_EMBEDDING_INDEX"
    operation_key: EmbeddingRegistrationOperationKey
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: EmbeddingIndexNamespace
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
    def exact_registration_intent(self) -> RegisterEmbeddingIndexCommand:
        EmbeddingIndexNamespace.model_validate(self.namespace.model_dump(mode="json"))
        _index_pointer(self.index_manifest)
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


class EmbeddingIndexRegistrationResult(_RegistryContract):
    """Immutable receipt plus current selection; replay never rolls the head back."""

    schema_version: Literal["embedding-registry-registration-result/1.0"] = (
        "embedding-registry-registration-result/1.0"
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
    def exact_registration_receipt(self) -> EmbeddingIndexRegistrationResult:
        _index_pointer(self.index_manifest)
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


def parse_embedding_registration_command(value: dict[str, Any]) -> RegisterEmbeddingIndexCommand:
    validate_contract(EMBEDDING_REGISTRY_SCHEMA, value)
    return RegisterEmbeddingIndexCommand.model_validate(value)


def parse_embedding_registration_result(value: dict[str, Any]) -> EmbeddingIndexRegistrationResult:
    validate_contract(EMBEDDING_REGISTRY_SCHEMA, value)
    return EmbeddingIndexRegistrationResult.model_validate(value)


def validate_embedding_registration_result(
    command: RegisterEmbeddingIndexCommand, result: EmbeddingIndexRegistrationResult
) -> EmbeddingIndexRegistrationResult:
    """Verify exact immutable request/receipt closure, never actual source authority."""
    command = parse_embedding_registration_command(command.model_dump(mode="json"))
    result = parse_embedding_registration_result(result.model_dump(mode="json"))
    validate_embedding_registration_receipt_binding(command, result)
    return result
