"""Index4 intent/receipt; same transaction, CAS and immutable replay semantics."""

from typing import Literal, Self

from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_contract_values import raw_public_solution_contract_value
from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexId,
    EmbeddingIndexRevisionId,
    EmbeddingRegistrationOperationKey,
    validate_embedding_registration_hash,
    validate_embedding_registration_head,
    validate_embedding_registration_receipt_binding,
    validate_embedding_registration_receipt_head,
)
from eom_catalog_contracts.inference_transfer_embedding import validate_embedding_manifest_pointer
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
)
from eom_catalog_contracts.registered_public_solution_index import (
    REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
)
from eom_catalog_contracts.validation import validate_contract

REGISTERED_PUBLIC_SOLUTION_REGISTRY_SCHEMA = "public-solution-embedding-registry-v4"


class _RegisteredPublicRegistryValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_public_solution_contract_value(value)
        if not isinstance(document, dict):
            raise ValueError("REGISTERED_PUBLIC_REGISTRATION_INVALID")
        try:
            validate_contract(REGISTERED_PUBLIC_SOLUTION_REGISTRY_SCHEMA, document)
        except JsonSchemaValidationError:
            raise ValueError("REGISTERED_PUBLIC_REGISTRATION_SCHEMA_INVALID") from None
        return document


class RegisterPublicSolutionIndexCommandV4(_RegisteredPublicRegistryValue):
    schema_version: Literal["embedding-registry-registration-command/4.0"] = (
        "embedding-registry-registration-command/4.0"
    )
    operation: Literal["REGISTER_EMBEDDING_INDEX"] = "REGISTER_EMBEDDING_INDEX"
    operation_key: EmbeddingRegistrationOperationKey
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: PublicSolutionIndexNamespace
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
    eligible_source_count: int = Field(ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    binding_count: int = Field(ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    requested_at: UtcDatetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        PublicSolutionIndexNamespace.model_validate(self.namespace.model_dump(mode="json"))
        validate_embedding_manifest_pointer(
            self.index_manifest, REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF, "index.json"
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


class PublicSolutionIndexRegistrationResultV4(_RegisteredPublicRegistryValue):
    schema_version: Literal["embedding-registry-registration-result/4.0"] = (
        "embedding-registry-registration-result/4.0"
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
    def exact_receipt(self) -> Self:
        validate_embedding_manifest_pointer(
            self.index_manifest, REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF, "index.json"
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


def validate_public_solution_registration_result_v4(
    command: RegisterPublicSolutionIndexCommandV4, result: PublicSolutionIndexRegistrationResultV4
) -> PublicSolutionIndexRegistrationResultV4:
    command = RegisterPublicSolutionIndexCommandV4.model_validate(command)
    result = PublicSolutionIndexRegistrationResultV4.model_validate(result)
    validate_embedding_registration_receipt_binding(command, result)
    return result
