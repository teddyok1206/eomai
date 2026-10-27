"""Unselected successor policy for a bounded, segmented mixed source population.

Parsing this immutable value does not authenticate a service or activate a new
Catalog source reader. Released 1.1/1.2 policy dispatch remains unchanged.
"""

from __future__ import annotations

from typing import Any, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import LocalIndexingServiceReference
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.local_indexing_mixed_policy import (
    SupportedLocalIndexingAccessPolicy,
    parse_supported_local_indexing_access_policy,
)
from eom_catalog_contracts.local_indexing_policy import (
    MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES,
    LocalIndexingPolicyContractError,
    local_indexing_policy_json_value,
    local_indexing_policy_wire_value,
    require_local_indexing_namespace_scope,
)
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.segmented_embedding_index import MAX_SEGMENTS
from eom_catalog_contracts.validation import validate_contract

SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA = "education-retrieval-access-policy-v1.3"
SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA_REF = (
    "eom://schemas/knowledge/education-retrieval-access-policy/1.3"
)
type LocalIndexingPublicationPolicy = (
    SupportedLocalIndexingAccessPolicy | SegmentedLocalIndexingAccessPolicy
)


class SegmentedLocalIndexingAccessPolicy(FrozenModel):
    """Separate page and population limits; no current-runtime authorization."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )
    schema_version: Literal["education-retrieval-access-policy/1.3"]
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
    namespaces: tuple[MixedEmbeddingIndexNamespace, ...] = Field(min_length=1, max_length=3)
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    native_execution_policy_sha256: Sha256
    resource_profile_sha256: Sha256
    maximum_page_sources: int = Field(strict=True, ge=1, le=1024)
    maximum_population_sources: int = Field(strict=True, ge=1025, le=1024 * MAX_SEGMENTS)
    answer_bearing_use: Literal["ACCEPTED_SOLUTION_OR_REGISTERED_REVIEW_PROJECTION_ONLY"]
    created_at: UtcDatetime
    content_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_before_behavior(cls, value: object) -> Any:
        try:
            raw = local_indexing_policy_wire_value(value)
            if type(raw) is not dict or len(canonical_json_bytes(raw)) > (
                MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES
            ):
                raise LocalIndexingPolicyContractError()
            validate_contract(SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA, raw)
        except Exception:
            raise LocalIndexingPolicyContractError() from None
        return raw

    @model_validator(mode="after")
    def closed_segment_scope(self) -> SegmentedLocalIndexingAccessPolicy:
        require_local_indexing_namespace_scope(
            self.namespaces, space=self.space, recipe=self.recipe
        )
        if (
            self.space.purpose != "DOCUMENT"
            or self.access_policy_revision_id == self.source_access_policy_revision_id
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.maximum_population_sources > self.maximum_page_sources * MAX_SEGMENTS
            or self.content_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"content_sha256"}))
        ):
            raise LocalIndexingPolicyContractError()
        return self


def segmented_local_indexing_policy_bytes(value: SegmentedLocalIndexingAccessPolicy) -> bytes:
    checked = SegmentedLocalIndexingAccessPolicy.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_segmented_local_indexing_access_policy(
    raw: bytes,
) -> SegmentedLocalIndexingAccessPolicy:
    try:
        policy = SegmentedLocalIndexingAccessPolicy.model_validate(
            local_indexing_policy_json_value(raw)
        )
        if segmented_local_indexing_policy_bytes(policy) != raw:
            raise LocalIndexingPolicyContractError()
        return policy
    except Exception:
        raise LocalIndexingPolicyContractError() from None


def parse_local_indexing_publication_policy(value: object) -> LocalIndexingPublicationPolicy:
    """Publication recognizes 1.3; existing runtime-supported dispatch does not."""
    raw = local_indexing_policy_wire_value(value)
    if type(raw) is not dict:
        raise LocalIndexingPolicyContractError()
    version = raw.get("schema_version")
    if version in {
        "education-retrieval-access-policy/1.1",
        "education-retrieval-access-policy/1.2",
    }:
        return parse_supported_local_indexing_access_policy(raw)
    if version == "education-retrieval-access-policy/1.3":
        return SegmentedLocalIndexingAccessPolicy.model_validate(raw)
    raise LocalIndexingPolicyContractError()


def local_indexing_publication_policy_bytes(value: LocalIndexingPublicationPolicy) -> bytes:
    checked = parse_local_indexing_publication_policy(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))
