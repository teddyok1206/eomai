"""Explicit public-report service scope; immutable policy is not a runtime grant."""

from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import LocalIndexingServiceReference
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.local_indexing_policy import (
    MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES,
    LocalIndexingPolicyContractError,
    local_indexing_policy_wire_value,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
)
from eom_catalog_contracts.validation import validate_contract


class PublicSolutionIndexingAccessPolicy(FrozenModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )
    schema_version: Literal["education-retrieval-access-policy/1.4"]
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    state: Literal["RELEASED"]
    purpose: Literal["LOCAL_EMBEDDING_INDEX"]
    service: LocalIndexingServiceReference
    runtime_configuration_sha256: Sha256
    source_access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    source_access_policy_sha256: Sha256
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_id: str = Field(pattern=r"^graph_[0-9a-f]{32}$")
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    namespaces: tuple[PublicSolutionIndexNamespace, ...] = Field(min_length=1, max_length=1)
    space: EmbeddingSpace
    recipe: PublicSolutionEmbeddingRecipe
    native_execution_policy_sha256: Sha256
    resource_profile_sha256: Sha256
    maximum_sources: int = Field(strict=True, ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES)
    maximum_page_sources: int = Field(strict=True, ge=1, le=1024)
    answer_bearing_use: Literal["VERIFIABLE_PUBLIC_SOLUTION_ONLY"]
    created_at: UtcDatetime
    content_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        try:
            raw = local_indexing_policy_wire_value(value)
            if (
                type(raw) is not dict
                or len(canonical_json_bytes(raw)) > MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES
            ):
                raise LocalIndexingPolicyContractError()
            validate_contract("education-retrieval-access-policy-v1.4", raw)
        except Exception:
            raise LocalIndexingPolicyContractError() from None
        return raw

    @model_validator(mode="after")
    def closed_scope(self) -> Self:
        namespace = self.namespaces[0]
        if (
            self.space.purpose != "DOCUMENT"
            or namespace.space_sha256 != self.space.space_sha256
            or namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.access_policy_revision_id == self.source_access_policy_revision_id
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.maximum_page_sources > self.maximum_sources
            or self.content_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"content_sha256"}))
        ):
            raise LocalIndexingPolicyContractError()
        return self
