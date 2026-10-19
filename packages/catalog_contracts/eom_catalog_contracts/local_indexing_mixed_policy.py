"""Closed mixed-projection service policy successor, never runtime authentication."""

from __future__ import annotations

from typing import Any, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import LocalIndexingServiceReference
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.local_indexing_policy import (
    MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES,
    LocalIndexingAccessPolicy,
    LocalIndexingPolicyContractError,
    local_indexing_authorization_scope_sha256,
    local_indexing_policy_json_value,
    local_indexing_policy_wire_value,
    require_local_indexing_namespace_scope,
)
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

LOCAL_INDEXING_MIXED_POLICY_SCHEMA = "education-retrieval-access-policy-v1.2"
LOCAL_INDEXING_MIXED_POLICY_SCHEMA_REF = (
    "eom://schemas/knowledge/education-retrieval-access-policy/1.2"
)


class LocalIndexingMixedAccessPolicy(FrozenModel):
    """Mixed namespace only; original source policy and runtime fence remain separate."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )
    schema_version: Literal["education-retrieval-access-policy/1.2"]
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
    maximum_sources: int = Field(strict=True, ge=1, le=1024)
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
            validate_contract(LOCAL_INDEXING_MIXED_POLICY_SCHEMA, raw)
        except Exception:
            raise LocalIndexingPolicyContractError() from None
        return raw

    @model_validator(mode="after")
    def closed_derivation_scope(self) -> LocalIndexingMixedAccessPolicy:
        require_local_indexing_namespace_scope(
            self.namespaces, space=self.space, recipe=self.recipe
        )
        if (
            self.space.purpose != "DOCUMENT"
            or self.access_policy_revision_id == self.source_access_policy_revision_id
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.content_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"content_sha256"}))
        ):
            raise LocalIndexingPolicyContractError()
        return self


type SupportedLocalIndexingAccessPolicy = LocalIndexingAccessPolicy | LocalIndexingMixedAccessPolicy


def parse_supported_local_indexing_access_policy(
    value: object,
) -> SupportedLocalIndexingAccessPolicy:
    """Explicit released-version dispatch; never reinterpret an old policy as mixed."""
    raw = local_indexing_policy_wire_value(value)
    if type(raw) is not dict:
        raise LocalIndexingPolicyContractError()
    if raw.get("schema_version") == "education-retrieval-access-policy/1.1":
        return LocalIndexingAccessPolicy.model_validate(raw)
    if raw.get("schema_version") == "education-retrieval-access-policy/1.2":
        return LocalIndexingMixedAccessPolicy.model_validate(raw)
    raise LocalIndexingPolicyContractError()


def supported_local_indexing_access_policy_bytes(
    value: SupportedLocalIndexingAccessPolicy,
) -> bytes:
    checked = parse_supported_local_indexing_access_policy(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_local_indexing_mixed_access_policy(raw: bytes) -> LocalIndexingMixedAccessPolicy:
    try:
        policy = LocalIndexingMixedAccessPolicy.model_validate(
            local_indexing_policy_json_value(raw)
        )
        if supported_local_indexing_access_policy_bytes(policy) != raw:
            raise LocalIndexingPolicyContractError()
        return policy
    except Exception:
        raise LocalIndexingPolicyContractError() from None


def supported_local_indexing_authorization_audit_sha256(
    value: SupportedLocalIndexingAccessPolicy,
) -> str:
    """Exact versioned policy provenance only; never proof of current authorization."""
    policy = parse_supported_local_indexing_access_policy(value)
    return local_indexing_authorization_scope_sha256(
        purpose=policy.purpose,
        service=policy.service,
        service_policy_revision_id=policy.access_policy_revision_id,
        service_policy_sha256=policy.content_sha256,
        runtime_configuration_sha256=policy.runtime_configuration_sha256,
        source_access_policy_revision_id=policy.source_access_policy_revision_id,
        source_access_policy_sha256=policy.source_access_policy_sha256,
    )
