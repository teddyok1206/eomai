"""GPU-preferred service selection; pure metadata, not runtime, source or GPU authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.local_indexing_owner_configuration import (
    LOCAL_INDEXING_MIXED_OWNER_SCHEMA_REF,
    LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_REF,
    LOCAL_INDEXING_OWNER_SCHEMA_REF,
    MAX_LOCAL_INDEXING_OWNER_BYTES,
    CpuLocalIndexingOwnerSelection,
    LocalIndexingMixedOwnerConfiguration,
    LocalIndexingOwnerConfigurationError,
    LocalIndexingOwnerDatabasePin,
    LocalIndexingRuntimeVerifierPin,
    local_indexing_mixed_owner_configuration_schema,
    local_indexing_multiview_owner_configuration_schema,
    local_indexing_owner_configuration_bytes,
    local_indexing_owner_configuration_schema,
)
from eom_workflow.native_embedding_backend_selection import (
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
    NativeCpuBackendSelection,
    NativeEmbeddingBackendSelection,
    native_embedding_backend_selection_schema,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_REF = (
    "eom://schemas/workflow/local-indexing-owner-configuration/5.0"
)
LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_SHA256 = (
    "sha256:9c04d3d14f4161e2cf2364ed9c422aa86e6629d3a4f6bcfb4c57c97fb4947f60"
)
LOCAL_INDEXING_PUBLIC_OWNER_SCHEMA_REF = (
    "eom://schemas/workflow/local-indexing-owner-configuration/6.0"
)
LOCAL_INDEXING_PUBLIC_OWNER_SCHEMA_SHA256 = (
    "sha256:bff68d37e24c2c024c3230805687d56c32b85a85892272bb72ec44c46cda4e99"
)


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources/local-indexing-owner-configuration-v5.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_LOCAL_INDEXING_OWNER_BYTES + 1)
    if sha256_bytes(raw) != LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_SHA256:
        raise LocalIndexingOwnerConfigurationError()
    return raw


def local_indexing_routed_owner_configuration_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(_schema_raw())
    if value.get("$id") != LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_REF:
        raise LocalIndexingOwnerConfigurationError()
    return value


@lru_cache(maxsize=2)
def _validator(*, public: bool = False) -> Draft202012Validator:
    schema = local_indexing_routed_owner_configuration_schema()
    legacy_schema = schema
    if public:
        with (
            files("eom_workflow")
            .joinpath("resources/local-indexing-owner-configuration-v6.schema.json")
            .open("rb") as stream
        ):
            raw = stream.read(MAX_LOCAL_INDEXING_OWNER_BYTES + 1)
        if sha256_bytes(raw) != LOCAL_INDEXING_PUBLIC_OWNER_SCHEMA_SHA256:
            raise LocalIndexingOwnerConfigurationError()
        schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resources(
        (name, Resource.from_contents(value))
        for name, value in (
            (LOCAL_INDEXING_OWNER_SCHEMA_REF, local_indexing_owner_configuration_schema()),
            (
                LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_REF,
                local_indexing_multiview_owner_configuration_schema(),
            ),
            (
                LOCAL_INDEXING_MIXED_OWNER_SCHEMA_REF,
                local_indexing_mixed_owner_configuration_schema(),
            ),
            (
                NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
                native_embedding_backend_selection_schema(),
            ),
            (LOCAL_INDEXING_ROUTED_OWNER_SCHEMA_REF, legacy_schema),
        )
    )
    return Draft202012Validator(schema, registry=registry)


class _RoutedValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)


class LocalIndexingCudaGrant(_RoutedValue):
    cpu_service_policy_revision_id: str = Field(strict=True, pattern=r"^accessrev_[0-9a-f]{32}$")
    service_policy_revision_id: str = Field(strict=True, pattern=r"^accessrev_[0-9a-f]{32}$")
    service_policy_sha256: Sha256
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256


class PublicSolutionCpuIndexingSelection(_RoutedValue):
    """Nested config6 scope. It neither authenticates a service nor widens config1-5."""

    corpus_id: str = Field(strict=True, pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: PublicSolutionIndexNamespace
    recipe: PublicSolutionEmbeddingRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    service_policy_revision_id: str = Field(strict=True, pattern=r"^accessrev_[0-9a-f]{32}$")
    service_policy_sha256: Sha256
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    runtime_profile: LocalEmbeddingRuntimeProfile
    database_owner: LocalIndexingOwnerDatabasePin
    runtime_verifier: LocalIndexingRuntimeVerifierPin
    cpu_environment_raw_sha256: Sha256
    owner_environment_raw_sha256: Sha256
    poll_interval_seconds: int = Field(strict=True, ge=30, le=1800)
    maximum_targets: int = Field(strict=True, ge=1, le=1024)
    maximum_sources: int = Field(strict=True, ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES)

    @property
    def namespaces(self) -> tuple[PublicSolutionIndexNamespace, ...]:
        return (self.namespace,)

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if (
            self.runtime_profile.resource_profile.device != "CPU"
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.database_owner.role_name == "eom_catalog_manager_runtime"
            or self.maximum_targets > self.maximum_sources
            or self.namespace.space_sha256 != self.runtime_profile.space.space_sha256
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
        ):
            raise LocalIndexingOwnerConfigurationError()
        return self


type RoutedCpuIndexingSelection = (
    CpuLocalIndexingOwnerSelection | PublicSolutionCpuIndexingSelection
)


@dataclass(frozen=True, slots=True)
class RoutedLocalIndexingGroup:
    cpu: RoutedCpuIndexingSelection
    cuda_grant: LocalIndexingCudaGrant

    def cuda_namespaces(
        self, profile: LocalEmbeddingRuntimeProfile
    ) -> tuple[
        EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace | PublicSolutionIndexNamespace, ...
    ]:
        """New namespace identities only; never reinterpret a CPU row as CUDA."""
        return tuple(
            type(namespace).model_validate(
                namespace.model_dump(mode="json") | {"space_sha256": profile.space.space_sha256}
            )
            for namespace in self.cpu.namespaces
        )


class RoutedLocalIndexingOwnerConfiguration(_RoutedValue):
    schema_version: Literal["local-indexing-owner-configuration/5.0"]
    cpu_configuration: RoutedCpuIndexingSelection
    cuda_runtime_profile: LocalEmbeddingRuntimeProfile
    cuda_backend: NativeEmbeddingBackendSelection
    cuda_grants: tuple[LocalIndexingCudaGrant, ...] = Field(min_length=1, max_length=2)
    routing_policy: ArtifactMemberPointer
    routing_policy_sha256: Sha256
    controller_release: str = Field(strict=True, pattern=r"^[0-9a-f]{40}$")

    @property
    def poll_interval_seconds(self) -> int:
        return self.cpu_configuration.poll_interval_seconds

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_LOCAL_INDEXING_OWNER_BYTES:
                raise LocalIndexingOwnerConfigurationError()
            _validator().validate(document)
            return document
        except Exception:
            raise LocalIndexingOwnerConfigurationError() from None

    @property
    def cpu_groups(self) -> tuple[RoutedCpuIndexingSelection, ...]:
        cpu = self.cpu_configuration
        if isinstance(cpu, LocalIndexingMixedOwnerConfiguration) and cpu.legacy_configuration:
            return cpu, cpu.legacy_configuration
        return (cpu,)

    @property
    def groups(self) -> tuple[RoutedLocalIndexingGroup, ...]:
        return tuple(
            RoutedLocalIndexingGroup(cpu, grant)
            for cpu, grant in zip(self.cpu_groups, self.cuda_grants, strict=True)
        )

    @model_validator(mode="after")
    def exact_groups(self) -> Self:
        cpu, cuda = self.cpu_configuration.runtime_profile, self.cuda_runtime_profile
        groups = self.cpu_groups
        if (
            cpu.resource_profile.device != "CPU"
            or cuda.resource_profile.device != "CUDA"
            or self.cuda_backend.purpose != "INDEX"
            or self.cuda_backend.device != "CUDA"
            or max(cpu.resource_profile.timeout_seconds, cuda.resource_profile.timeout_seconds)
            > MAX_EMBEDDING_WORK_BATCH_SECONDS
            or cpu.space.space_sha256 == cuda.space.space_sha256
            or tuple(g.cpu_service_policy_revision_id for g in self.cuda_grants)
            != tuple(c.service_policy_revision_id for c in groups)
            or len({g.service_policy_revision_id for g in self.cuda_grants}) != len(groups)
            or len({g.service_policy_sha256 for g in self.cuda_grants}) != len(groups)
        ):
            raise LocalIndexingOwnerConfigurationError()
        cpu_revisions = {g.service_policy_revision_id for g in groups}
        cpu_hashes = {g.service_policy_sha256 for g in groups}
        native_hashes = {g.native_execution_policy_sha256 for g in groups}
        if any(
            g.service_policy_revision_id in cpu_revisions
            or g.service_policy_sha256 in cpu_hashes
            or g.native_execution_policy_sha256 in native_hashes
            for g in self.cuda_grants
        ):
            raise LocalIndexingOwnerConfigurationError()
        return self


class PublicSolutionRoutedOwnerConfiguration(RoutedLocalIndexingOwnerConfiguration):
    # The old schema guard remains closed; this successor shares only pure
    # device/grant closure and the existing execution composition.
    schema_version: Literal["local-indexing-owner-configuration/6.0"]  # type: ignore[assignment]
    cpu_configuration: PublicSolutionCpuIndexingSelection
    cuda_grants: tuple[LocalIndexingCudaGrant, ...] = Field(min_length=1, max_length=1)
    legacy_configuration: RoutedLocalIndexingOwnerConfiguration | None

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_LOCAL_INDEXING_OWNER_BYTES:
                raise LocalIndexingOwnerConfigurationError()
            _validator(public=True).validate(document)
            return document
        except Exception:
            raise LocalIndexingOwnerConfigurationError() from None

    @model_validator(mode="after")
    def exact_legacy_runtime(self) -> Self:
        legacy = self.legacy_configuration
        if legacy is None:
            return self
        cpu, old_cpu = self.cpu_configuration, legacy.cpu_configuration
        if (
            self.cuda_runtime_profile != legacy.cuda_runtime_profile
            or self.cuda_backend != legacy.cuda_backend
            or self.controller_release != legacy.controller_release
            or any(
                getattr(cpu, key) != getattr(old_cpu, key)
                for key in (
                    "corpus_id",
                    "runtime_profile",
                    "database_owner",
                    "runtime_verifier",
                    "cpu_environment_raw_sha256",
                    "owner_environment_raw_sha256",
                )
            )
        ):
            raise LocalIndexingOwnerConfigurationError()
        groups = (*self.groups, *legacy.groups)
        revisions = [
            revision
            for group in groups
            for revision in (
                group.cpu.service_policy_revision_id,
                group.cuda_grant.service_policy_revision_id,
            )
        ]
        hashes = [
            sha
            for group in groups
            for sha in (
                group.cpu.service_policy_sha256,
                group.cuda_grant.service_policy_sha256,
            )
        ]
        if len(set(revisions)) != len(revisions) or len(set(hashes)) != len(hashes):
            raise LocalIndexingOwnerConfigurationError()
        return self


type SupportedRoutedIndexingConfiguration = (
    RoutedLocalIndexingOwnerConfiguration | PublicSolutionRoutedOwnerConfiguration
)


def validate_supported_routed_indexing_configuration(
    value: object,
) -> SupportedRoutedIndexingConfiguration:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and document.get("schema_version") == (
        "local-indexing-owner-configuration/6.0"
    ):
        return PublicSolutionRoutedOwnerConfiguration.model_validate(document)
    return RoutedLocalIndexingOwnerConfiguration.model_validate(document)


def local_indexing_routed_owner_configuration_bytes(
    value: SupportedRoutedIndexingConfiguration,
) -> bytes:
    checked = validate_supported_routed_indexing_configuration(value)
    document = checked.model_dump(mode="json")
    # Preserve the old nested CPU4 absent-field canonical representation too.
    if not isinstance(checked.cpu_configuration, PublicSolutionCpuIndexingSelection):
        document["cpu_configuration"] = json.loads(
            local_indexing_owner_configuration_bytes(checked.cpu_configuration)
        )
    if isinstance(checked, PublicSolutionRoutedOwnerConfiguration) and checked.legacy_configuration:
        document["legacy_configuration"] = json.loads(
            local_indexing_routed_owner_configuration_bytes(checked.legacy_configuration)
        )
    return canonical_json_bytes(document)


def parse_local_indexing_routed_owner_configuration(
    raw: bytes,
) -> RoutedLocalIndexingOwnerConfiguration:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_OWNER_BYTES:
            raise LocalIndexingOwnerConfigurationError()
        value = RoutedLocalIndexingOwnerConfiguration.model_validate(json.loads(raw))
        if local_indexing_routed_owner_configuration_bytes(value) != raw:
            raise LocalIndexingOwnerConfigurationError()
        return value
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None


def parse_supported_routed_indexing_configuration(
    raw: bytes,
) -> SupportedRoutedIndexingConfiguration:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_OWNER_BYTES:
            raise LocalIndexingOwnerConfigurationError()
        value = validate_supported_routed_indexing_configuration(json.loads(raw))
        if local_indexing_routed_owner_configuration_bytes(value) != raw:
            raise LocalIndexingOwnerConfigurationError()
        return value
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None


def require_routed_indexing_policy(
    configuration: SupportedRoutedIndexingConfiguration, policy: EmbeddingDeviceRoutingPolicy
) -> None:
    """Fresh resolved control comparison, not source permission or allocation authority."""
    checked = validate_supported_routed_indexing_configuration(configuration)
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
    cpu_backend = policy.cpu.backend.backend
    cpu = checked.cpu_configuration
    if (
        policy.purpose != "INDEX"
        or policy.policy_sha256 != checked.routing_policy_sha256
        or policy.view_recipe_sha256 != cpu.recipe.recipe_sha256
        or policy.cpu.profile != cpu.runtime_profile
        or policy.cuda.profile != checked.cuda_runtime_profile
        or policy.cuda.backend != checked.cuda_backend
        or not isinstance(cpu_backend, NativeCpuBackendSelection)
        or cpu_backend.cpu_environment_raw_sha256 != cpu.cpu_environment_raw_sha256
        or cpu_backend.runtime_verifier != cpu.runtime_verifier
    ):
        raise LocalIndexingOwnerConfigurationError()
