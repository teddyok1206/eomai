"""Purpose-specific Catalog data policy; never authenticates a runtime/operator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import LocalIndexingServiceReference
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.knowledge import EducationRetrievalAccessPolicy
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

LOCAL_INDEXING_ACCESS_POLICY_SCHEMA = "education-retrieval-access-policy-v1.1"
LOCAL_INDEXING_ACCESS_POLICY_SCHEMA_REF = (
    "eom://schemas/knowledge/education-retrieval-access-policy/1.1"
)
MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES = 64 * 1024


class LocalIndexingPolicyContractError(ValueError):
    def __init__(self) -> None:
        super().__init__("LOCAL_INDEXING_POLICY_CONTRACT_INVALID")


def _wire_values(value: object) -> Any:
    """Preserve/reject copied-model extras BEFORE serializers can drop them."""
    remaining = 4096

    def walk(member: object, depth: int) -> Any:
        nonlocal remaining
        remaining -= 1
        if depth > 24 or remaining < 0:
            raise LocalIndexingPolicyContractError()
        if isinstance(member, BaseModel):
            names = type(member).model_fields
            if member.__pydantic_extra__ or set(member.__dict__) != set(names):
                raise LocalIndexingPolicyContractError()
            return {name: walk(getattr(member, name), depth + 1) for name in names}
        if type(member) is dict:
            if len(member) > 128 or any(type(key) is not str or len(key) > 128 for key in member):
                raise LocalIndexingPolicyContractError()
            return {key: walk(item, depth + 1) for key, item in member.items()}
        if isinstance(member, tuple | list):
            if type(member) not in (tuple, list) or len(member) > 128:
                raise LocalIndexingPolicyContractError()
            return [walk(item, depth + 1) for item in member]
        if isinstance(member, Enum):
            return walk(member.value, depth + 1)
        if type(member) is datetime:
            if member.tzinfo is None or member.utcoffset() != UTC.utcoffset(member):
                raise LocalIndexingPolicyContractError()
            return member.isoformat().replace("+00:00", "Z")
        if type(member) is str:
            if len(member) > MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES:
                raise LocalIndexingPolicyContractError()
            return member
        if member is None or type(member) in (int, bool):
            return member
        raise LocalIndexingPolicyContractError()

    return walk(value, 0)


class LocalIndexingAccessPolicy(FrozenModel):
    """Small immutable grant scope. A parsed policy is NOT an authenticated caller."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )
    schema_version: Literal["education-retrieval-access-policy/1.1"]
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
    namespaces: tuple[EmbeddingIndexNamespace, ...] = Field(min_length=1, max_length=3)
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    native_execution_policy_sha256: Sha256
    resource_profile_sha256: Sha256
    maximum_sources: int = Field(strict=True, ge=1, le=1024)
    answer_bearing_use: Literal["ACCEPTED_SOLUTION_PROJECTION_ONLY"]
    created_at: UtcDatetime
    content_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_before_behavior(cls, value: object) -> Any:
        try:
            raw = _wire_values(value)
            if type(raw) is not dict or len(canonical_json_bytes(raw)) > (
                MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES
            ):
                raise LocalIndexingPolicyContractError()
            validate_contract(LOCAL_INDEXING_ACCESS_POLICY_SCHEMA, raw)
        except Exception:
            raise LocalIndexingPolicyContractError() from None
        return raw

    @model_validator(mode="after")
    def closed_derivation_scope(self) -> LocalIndexingAccessPolicy:
        views = tuple(namespace.view for namespace in self.namespaces)
        common = self.namespaces[0]
        if (
            self.space.purpose != "DOCUMENT"
            or self.access_policy_revision_id == self.source_access_policy_revision_id
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or views != tuple(sorted(set(views)))
            or any(
                namespace.space_sha256 != self.space.space_sha256
                or namespace.recipe_sha256 != self.recipe.recipe_sha256
                or namespace.storage_partition != common.storage_partition
                or namespace.population_scope != common.population_scope
                for namespace in self.namespaces
            )
            or (
                common.population_scope == "OCCURRENCE_BACKED_PAST_EXAM"
                and self.source_classes != ("PAST_EXAM",)
            )
            or self.content_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"content_sha256"}))
        ):
            raise LocalIndexingPolicyContractError()
        return self


def local_indexing_access_policy_bytes(value: LocalIndexingAccessPolicy) -> bytes:
    checked = LocalIndexingAccessPolicy.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def local_indexing_authorization_audit_sha256(value: LocalIndexingAccessPolicy) -> str:
    """Bind immutable authority provenance only, NOT current authentication/permission."""
    policy = LocalIndexingAccessPolicy.model_validate(value)
    return content_sha256(
        {
            "purpose": policy.purpose,
            "service": policy.service.model_dump(mode="json"),
            "service_policy_revision_id": policy.access_policy_revision_id,
            "service_policy_sha256": policy.content_sha256,
            "runtime_configuration_sha256": policy.runtime_configuration_sha256,
            "source_access_policy_revision_id": policy.source_access_policy_revision_id,
            "source_access_policy_sha256": policy.source_access_policy_sha256,
        }
    )


def require_local_indexing_source_policy(
    policy: LocalIndexingAccessPolicy,
    source: EducationRetrievalAccessPolicy,
) -> None:
    """One pure compatibility rule, never runtime identity/permission authentication."""
    if (
        policy.source_access_policy_revision_id != source.access_policy_revision_id
        or policy.source_access_policy_sha256 != source.content_sha256
        or not set(policy.source_classes).issubset(source.allowed_source_classes)
        or "ITEM_PREPARATION" not in source.allowed_query_kinds
        or not source.answer_bearing_roles
        or source.maximum_budget.max_item_revisions < 1
    ):
        raise LocalIndexingPolicyContractError()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LocalIndexingPolicyContractError()
        result[key] = value
    return result


def _nonfinite(_value: str) -> object:
    raise LocalIndexingPolicyContractError()


def parse_local_indexing_access_policy(raw: bytes) -> LocalIndexingAccessPolicy:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_ACCESS_POLICY_BYTES:
        raise LocalIndexingPolicyContractError()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        policy = LocalIndexingAccessPolicy.model_validate(value)
        if local_indexing_access_policy_bytes(policy) != raw:
            raise LocalIndexingPolicyContractError()
        return policy
    except Exception:
        raise LocalIndexingPolicyContractError() from None
