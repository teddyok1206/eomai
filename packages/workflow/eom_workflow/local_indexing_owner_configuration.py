"""Non-secret fixed service selection; pure values never authenticate an owner."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingRuntimeProfile,
    LocalEmbeddingServiceExecutionPolicy,
)
from eom_workflow.native_embedding_backend_selection import (
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
    NativeEmbeddingBackendSelection,
    native_embedding_backend_selection_schema,
    select_native_index_runtime_profile,
)
from eom_workflow.native_embedding_backend_selection import (
    LocalIndexingRuntimeVerifierPin as LocalIndexingRuntimeVerifierPin,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

LOCAL_INDEXING_OWNER_SCHEMA_REF = "eom://schemas/workflow/local-indexing-owner-configuration/1.0"
LOCAL_INDEXING_OWNER_SCHEMA_SHA256 = (
    "sha256:9d31827404897c154c0412b74f00112cf5f8192b0fd668bdf27801a26b7e3e39"
)
MAX_LOCAL_INDEXING_OWNER_BYTES = 64 * 1024
_RESOURCE = "local-indexing-owner-configuration-v1.schema.json"
LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_REF = (
    "eom://schemas/workflow/local-indexing-owner-configuration/2.0"
)
LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256 = (
    "sha256:5c2f1945c7d670b3affb8cc5c2bb987108905f33492584953c49fdcc307ed43f"
)
LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_REF = (
    "eom://schemas/workflow/local-indexing-owner-configuration/3.0"
)
LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_SHA256 = (
    "sha256:3e1503e14b59e3cc2ea9e8616e11112013c6961170a2dd83a7e7a97e5f45a7a2"
)


class LocalIndexingOwnerConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("LOCAL_INDEXING_OWNER_CONFIGURATION_INVALID")


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with files("eom_workflow").joinpath("resources", _RESOURCE).open("rb") as stream:
        raw = stream.read(32 * 1024 + 1)
    if len(raw) > 32 * 1024 or sha256_bytes(raw) != LOCAL_INDEXING_OWNER_SCHEMA_SHA256:
        raise LocalIndexingOwnerConfigurationError()
    return raw


def local_indexing_owner_configuration_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(_schema_raw())
    if schema.get("$id") != LOCAL_INDEXING_OWNER_SCHEMA_REF:
        raise LocalIndexingOwnerConfigurationError()
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = local_indexing_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resource(
        LOCAL_INDEXING_OWNER_SCHEMA_REF, Resource.from_contents(schema)
    )
    return Draft202012Validator(schema, registry=registry)


@lru_cache(maxsize=1)
def _multiview_validator() -> Draft202012Validator:
    with (
        files("eom_workflow")
        .joinpath("resources", "local-indexing-owner-configuration-v2.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(32 * 1024 + 1)
    if len(raw) > 32 * 1024 or sha256_bytes(raw) != LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256:
        raise LocalIndexingOwnerConfigurationError()
    schema = json.loads(raw)
    if schema.get("$id") != LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_REF:
        raise LocalIndexingOwnerConfigurationError()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resources(
        (
            (
                LOCAL_INDEXING_OWNER_SCHEMA_REF,
                Resource.from_contents(local_indexing_owner_configuration_schema()),
            ),
            (LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_REF, Resource.from_contents(schema)),
        )
    )
    return Draft202012Validator(schema, registry=registry)


@lru_cache(maxsize=1)
def _native_schema_raw() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources", "local-indexing-owner-configuration-v3.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(32 * 1024 + 1)
    if (
        not 0 < len(raw) <= 32 * 1024
        or sha256_bytes(raw) != LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_SHA256
    ):
        raise LocalIndexingOwnerConfigurationError()
    return raw


def local_indexing_native_owner_configuration_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(_native_schema_raw())
    if schema.get("$id") != LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_REF:
        raise LocalIndexingOwnerConfigurationError()
    return schema


@lru_cache(maxsize=1)
def _native_validator() -> Draft202012Validator:
    schema = local_indexing_native_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resources(
        (
            (
                LOCAL_INDEXING_OWNER_SCHEMA_REF,
                Resource.from_contents(local_indexing_owner_configuration_schema()),
            ),
            (
                NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
                Resource.from_contents(native_embedding_backend_selection_schema()),
            ),
        )
    )
    return Draft202012Validator(schema, registry=registry)


def _validate_document(value: object, validator: Draft202012Validator) -> Any:
    try:
        document = raw_similarity_contract_value(value)
        if len(canonical_json_bytes(document)) > MAX_LOCAL_INDEXING_OWNER_BYTES:
            raise LocalIndexingOwnerConfigurationError()
        validator.validate(document)
        return document
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None


class _OwnerValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)


class LocalIndexingOwnerDatabasePin(_OwnerValue):
    role_name: str = Field(strict=True, pattern=r"^[a-z][a-z0-9_]{0,62}$")
    role_oid: int = Field(strict=True, ge=1, le=4294967295)


class _OwnerCommonSelectionFields(_OwnerValue):
    corpus_id: str = Field(strict=True, pattern=r"^corpus_[0-9a-f]{32}$")
    recipe: ExperimentViewRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    service_policy_revision_id: str = Field(strict=True, pattern=r"^accessrev_[0-9a-f]{32}$")
    service_policy_sha256: Sha256
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    runtime_profile: LocalEmbeddingRuntimeProfile
    database_owner: LocalIndexingOwnerDatabasePin
    owner_environment_raw_sha256: Sha256
    poll_interval_seconds: int = Field(strict=True, ge=30, le=1800)
    maximum_targets: int = Field(strict=True, ge=1, le=1024)
    maximum_sources: int = Field(strict=True, ge=1, le=1024)

    @model_validator(mode="after")
    def common_selection(self) -> Self:
        if (
            self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.database_owner.role_name == "eom_catalog_manager_runtime"
            or self.maximum_targets > self.maximum_sources
        ):
            raise LocalIndexingOwnerConfigurationError()
        return self

    def _require_matching_namespaces(self, namespaces: tuple[EmbeddingIndexNamespace, ...]) -> None:
        if len({namespace.view for namespace in namespaces}) != len(namespaces):
            raise LocalIndexingOwnerConfigurationError()
        primary = namespaces[0]
        for namespace in namespaces:
            if (
                namespace.space_sha256 != self.runtime_profile.space.space_sha256
                or namespace.recipe_sha256 != self.recipe.recipe_sha256
                or namespace.projection_version != primary.projection_version
                or namespace.storage_partition != primary.storage_partition
                or namespace.population_scope != primary.population_scope
            ):
                raise LocalIndexingOwnerConfigurationError()


class _OwnerSelectionFields(_OwnerCommonSelectionFields):
    runtime_verifier: LocalIndexingRuntimeVerifierPin
    cpu_environment_raw_sha256: Sha256


class LocalIndexingOwnerConfiguration(_OwnerSelectionFields):
    schema_version: Literal["local-indexing-owner-configuration/1.0"]
    namespace: EmbeddingIndexNamespace

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        return _validate_document(value, _validator())

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if (
            self.namespace.space_sha256 != self.runtime_profile.space.space_sha256
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
        ):
            raise LocalIndexingOwnerConfigurationError()
        return self

    @property
    def namespaces(self) -> tuple[EmbeddingIndexNamespace, ...]:
        return (self.namespace,)


class LocalIndexingMultiviewOwnerConfiguration(_OwnerSelectionFields):
    schema_version: Literal["local-indexing-owner-configuration/2.0"]
    namespace: EmbeddingIndexNamespace
    additional_namespaces: tuple[EmbeddingIndexNamespace, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        return _validate_document(value, _multiview_validator())

    @model_validator(mode="after")
    def exact_namespaces(self) -> Self:
        self._require_matching_namespaces(self.namespaces)
        return self

    @property
    def namespaces(self) -> tuple[EmbeddingIndexNamespace, ...]:
        return (self.namespace, *self.additional_namespaces)


class LocalIndexingNativeOwnerConfiguration(_OwnerCommonSelectionFields):
    """Pure successor selection; current CPU-only composition must not admit this version."""

    schema_version: Literal["local-indexing-owner-configuration/3.0"]
    namespace: EmbeddingIndexNamespace
    additional_namespaces: tuple[EmbeddingIndexNamespace, ...] = Field(max_length=2)
    native_backend: NativeEmbeddingBackendSelection

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        return _validate_document(value, _native_validator())

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if (
            self.native_backend.purpose != "INDEX"
            or self.native_backend.device != self.runtime_profile.resource_profile.device
        ):
            raise LocalIndexingOwnerConfigurationError()
        self._require_matching_namespaces(self.namespaces)
        return self

    @property
    def namespaces(self) -> tuple[EmbeddingIndexNamespace, ...]:
        return (self.namespace, *self.additional_namespaces)


LocalIndexingOwnerSelection = (
    LocalIndexingOwnerConfiguration | LocalIndexingMultiviewOwnerConfiguration
)
SupportedLocalIndexingOwnerSelection = (
    LocalIndexingOwnerSelection | LocalIndexingNativeOwnerConfiguration
)


def _parse_value(value: object) -> LocalIndexingOwnerSelection:
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise LocalIndexingOwnerConfigurationError()
    if document.get("schema_version") == "local-indexing-owner-configuration/2.0":
        return LocalIndexingMultiviewOwnerConfiguration.model_validate(document)
    return LocalIndexingOwnerConfiguration.model_validate(document)


def _parse_supported_value(value: object) -> SupportedLocalIndexingOwnerSelection:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "local-indexing-owner-configuration/3.0"
    ):
        return LocalIndexingNativeOwnerConfiguration.model_validate(document)
    return _parse_value(document)


def local_indexing_owner_configuration_bytes(value: SupportedLocalIndexingOwnerSelection) -> bytes:
    try:
        checked = _parse_supported_value(value)
        return canonical_json_bytes(raw_similarity_contract_value(checked))
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LocalIndexingOwnerConfigurationError()
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise LocalIndexingOwnerConfigurationError()


def parse_local_indexing_owner_configuration(raw: bytes) -> LocalIndexingOwnerSelection:
    """Released CPU-only parser: v3 opt-in belongs to a future executable composition."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_OWNER_BYTES:
        raise LocalIndexingOwnerConfigurationError()
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        checked = _parse_value(value)
        if local_indexing_owner_configuration_bytes(checked) != raw:
            raise LocalIndexingOwnerConfigurationError()
        return checked
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None


def parse_supported_local_indexing_owner_configuration(
    raw: bytes,
) -> SupportedLocalIndexingOwnerSelection:
    """Decode all source value versions without claiming that their runtime exists."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_OWNER_BYTES:
        raise LocalIndexingOwnerConfigurationError()
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        checked = _parse_supported_value(value)
        if local_indexing_owner_configuration_bytes(checked) != raw:
            raise LocalIndexingOwnerConfigurationError()
        return checked
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None


def require_native_index_owner_policy(
    configuration: LocalIndexingNativeOwnerConfiguration,
    policy: LocalEmbeddingServiceExecutionPolicy,
) -> None:
    """Compare freshly resolved policy values; no Artifact resolution, authority or launch."""
    try:
        checked = LocalIndexingNativeOwnerConfiguration.model_validate(
            raw_similarity_contract_value(configuration)
        )
        if type(policy) is not LocalEmbeddingServiceExecutionPolicy:
            raise LocalIndexingOwnerConfigurationError()
        policy = LocalEmbeddingServiceExecutionPolicy.model_validate(
            raw_similarity_contract_value(policy)
        )
        selected_profile = select_native_index_runtime_profile(checked.native_backend, policy)
        if (
            policy.policy_sha256 != checked.native_execution_policy_sha256
            or selected_profile != checked.runtime_profile
        ):
            raise LocalIndexingOwnerConfigurationError()
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None
