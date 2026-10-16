"""Membership-refresh intent; only the actual current service owner may admit work."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    parse_embedding_binding,
    parse_embedding_index,
)
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import Field, model_validator
from referencing import Resource

from eom_workflow.local_embedding_request_values import LocalEmbeddingServiceWorkflowRequest
from eom_workflow.schemas import NativeEmbeddingContract, local_embedding_admission_schema_registry

INDEX_REFRESH_REQUEST_SCHEMA_REF = "eom://schemas/workflow/local-embedding-workflow-request/1.3"
INDEX_REFRESH_REQUEST_SCHEMA_SHA256 = (
    "sha256:dec4ade0ac871e74a84c3139c639a053ae7b8a83dd297c8c27f980d582a01986"
)
MAX_INDEX_REFRESH_REQUEST_BYTES = 64 * 1024
_RESOURCE = "local-embedding-workflow-request-v1_3.schema.json"


class IndexRefreshContractError(ValueError):
    def __init__(self) -> None:
        super().__init__("LOCAL_EMBEDDING_INDEX_REFRESH_CONTRACT_INVALID")


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    with files("eom_workflow").joinpath("resources", _RESOURCE).open("rb") as stream:
        raw = stream.read(MAX_INDEX_REFRESH_REQUEST_BYTES + 1)
    if (
        not 0 < len(raw) <= MAX_INDEX_REFRESH_REQUEST_BYTES
        or sha256_bytes(raw) != INDEX_REFRESH_REQUEST_SCHEMA_SHA256
    ):
        raise IndexRefreshContractError()
    schema = json.loads(raw)
    if schema.get("$id") != INDEX_REFRESH_REQUEST_SCHEMA_REF:
        raise IndexRefreshContractError()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resource(
        INDEX_REFRESH_REQUEST_SCHEMA_REF, Resource.from_contents(schema)
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class IndexMembershipRefreshBasis(NativeEmbeddingContract):
    """Small immutable observation; its hashes do not authorize source/index access."""

    reason: Literal["MISSING_NAMESPACE_INDEX", "INDEX_MEMBERSHIP_CHANGED"]
    previous_index_manifest: ArtifactMemberPointer | None
    previous_index_sha256: Sha256 | None
    eligible_source_set_sha256: Sha256
    eligible_source_count: int = Field(strict=True, ge=1, le=1024)
    available_binding_set_sha256: Sha256
    available_binding_count: int = Field(strict=True, ge=1, le=1024)

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_predecessor(self) -> IndexMembershipRefreshBasis:
        if (
            (self.previous_index_manifest is None) != (self.previous_index_sha256 is None)
            or (self.reason == "MISSING_NAMESPACE_INDEX") != (self.previous_index_manifest is None)
            or self.available_binding_count > self.eligible_source_count
        ):
            raise ValueError("index refresh basis has inconsistent predecessor or coverage")
        if self.previous_index_manifest is not None and (
            self.previous_index_manifest.member_path != "index.json"
            or self.previous_index_manifest.schema_ref != INDEX_SCHEMA_REF
            or self.previous_index_manifest.media_type != "application/json"
        ):
            raise ValueError("index refresh requires the exact predecessor manifest member")
        return self


class LocalEmbeddingIndexRefreshRequest(LocalEmbeddingServiceWorkflowRequest):
    """Successor meaning stays separate from old success-equivalent1.2 requests."""

    schema_version: Literal["local-embedding-workflow-request/1.3"] = (
        "local-embedding-workflow-request/1.3"  # type: ignore[assignment]
    )
    reconciliation_basis: IndexMembershipRefreshBasis

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        raw = raw_similarity_contract_value(value)
        if len(canonical_json_bytes(raw)) > MAX_INDEX_REFRESH_REQUEST_BYTES:
            raise IndexRefreshContractError()
        _validator().validate(raw)
        return raw


def parse_index_refresh_request(value: object) -> LocalEmbeddingIndexRefreshRequest:
    """Parse metadata only; current runtime/source admission is always separate."""
    try:
        return LocalEmbeddingIndexRefreshRequest.model_validate(value)
    except Exception:
        raise IndexRefreshContractError() from None


def index_refresh_request_bytes(value: LocalEmbeddingIndexRefreshRequest) -> bytes:
    return canonical_json_bytes(parse_index_refresh_request(value).model_dump(mode="json"))


def parse_index_refresh_predecessor(
    value: object,
) -> tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None:
    """One pure resolved-pointer closure shared by planning and admission validation."""
    if value is None:
        return None
    if type(value) is not tuple or len(value) != 2:
        raise IndexRefreshContractError()
    try:
        pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(value[0]))
        index = parse_embedding_index(raw_similarity_contract_value(value[1]))
    except (ValueError, TypeError, SchemaError):
        raise IndexRefreshContractError() from None
    if (
        pointer.member_path != "index.json"
        or pointer.schema_ref != INDEX_SCHEMA_REF
        or pointer.media_type != "application/json"
        or pointer.sha256 != content_sha256(index.model_dump(mode="json"))
    ):
        raise IndexRefreshContractError()
    return pointer, index


def validate_index_refresh_request_basis(
    request: LocalEmbeddingIndexRefreshRequest,
    *,
    eligible_source_set_sha256: str,
    eligible_source_count: int,
    available_bindings: tuple[EmbeddingSourceBinding, ...],
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None,
) -> None:
    """Pure owner-resolved closure; current IAM/source/producer/hash IO remains mandatory.

    Call only with the exact current-root Catalog observation. Reusing this return
    value in a later root is not reauthorization. No model/Job/queue is created.
    """
    checked = parse_index_refresh_request(request)
    basis = checked.reconciliation_basis
    if (
        type(eligible_source_count) is not int
        or type(available_bindings) is not tuple
        or not 1 <= len(available_bindings) <= 1024
    ):
        raise IndexRefreshContractError()
    try:
        bindings = tuple(
            parse_embedding_binding(raw_similarity_contract_value(value))
            for value in available_bindings
        )
    except (ValueError, TypeError, SchemaError):
        raise IndexRefreshContractError() from None
    revisions = tuple(value.source.item_revision_id for value in bindings)
    if (
        revisions != tuple(sorted(set(revisions)))
        or basis.eligible_source_set_sha256 != eligible_source_set_sha256
        or basis.eligible_source_count != eligible_source_count
        or basis.available_binding_count != len(bindings)
        or basis.available_binding_set_sha256
        != content_sha256([value.binding_sha256 for value in bindings])
        or any(
            value.graph_snapshot != checked.graph_snapshot
            or value.policy_revision_id != checked.access_policy_revision_id
            or value.policy_sha256 != checked.access_policy_sha256
            or value.encoding.space_sha256 != checked.namespace.space_sha256
            or value.encoding.storage_partition != checked.namespace.storage_partition
            or value.view != checked.namespace.view
            or value.recipe.recipe_sha256 != checked.namespace.recipe_sha256
            or value.projection_version != checked.namespace.projection_version
            for value in bindings
        )
    ):
        raise IndexRefreshContractError()
    predecessor = parse_index_refresh_predecessor(previous)
    if predecessor is None:
        if basis.previous_index_manifest is not None:
            raise IndexRefreshContractError()
        return
    pointer, index = predecessor
    if (
        pointer != basis.previous_index_manifest
        or index.index_sha256 != basis.previous_index_sha256
        or index.space != checked.space
        or index.view != checked.namespace.view
        or index.storage_partition != checked.namespace.storage_partition
        or index.recipe.recipe_sha256 != checked.namespace.recipe_sha256
        or index.bindings == bindings
    ):
        raise IndexRefreshContractError()
