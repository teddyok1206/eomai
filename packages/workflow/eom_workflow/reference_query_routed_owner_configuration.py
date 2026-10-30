"""Opt-in QUERY selection over existing CPU and finite CUDA owners; never authority."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.reference_query_execution import (
    REFERENCE_QUERY_POLICY_REF,
    ReferenceQueryExecutionPolicy,
    parse_reference_query_execution_policy,
)
from eom_workflow.reference_query_owner_configuration import (
    MAX_REFERENCE_QUERY_OWNER_BYTES,
    REFERENCE_QUERY_MIXED_OWNER_SCHEMA_REF,
    REFERENCE_QUERY_OWNER_SCHEMA_REF,
    REFERENCE_QUERY_PUBLIC_OWNER_SCHEMA_REF,
    ReferenceQueryOwnerConfigurationError,
    ReferenceQueryPublicServiceConfiguration,
    ReferenceQueryServiceConfiguration,
    ReferenceQueryServiceConfigurationV2,
    SupportedReferenceQueryServiceConfiguration,
    parse_supported_reference_query_service_configuration,
    reference_query_mixed_owner_configuration_schema,
    reference_query_owner_configuration_schema,
    reference_query_public_owner_configuration_schema,
    supported_reference_query_service_configuration_bytes,
)
from eom_workflow.schemas import reference_query_execution_schema_registry

ROUTED_QUERY_OWNER_SCHEMA_REF = "eom://schemas/workflow/reference-query-owner-configuration/3.0"
ROUTED_QUERY_OWNER_SCHEMA_SHA256 = (
    "sha256:9741d1b843d472369252d40744c4d32d9ad8cc49c3d1776de8847067ac44f37a"
)
PUBLIC_ROUTED_QUERY_OWNER_SCHEMA_REF = (
    "eom://schemas/workflow/reference-query-owner-configuration/5.0"
)
PUBLIC_ROUTED_QUERY_OWNER_SCHEMA_SHA256 = (
    "sha256:917f5b1b154aef3e86c8bb320704989214776fac93f57132c563fa6038648f88"
)


def reference_query_routed_owner_configuration_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/reference-query-owner-configuration-v3.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_REFERENCE_QUERY_OWNER_BYTES + 1)
    if sha256_bytes(raw) != ROUTED_QUERY_OWNER_SCHEMA_SHA256:
        raise ReferenceQueryOwnerConfigurationError()
    schema: dict[str, Any] = json.loads(raw)
    if schema.get("$id") != ROUTED_QUERY_OWNER_SCHEMA_REF:
        raise ReferenceQueryOwnerConfigurationError()
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = reference_query_routed_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    registry = reference_query_execution_schema_registry().with_resources(
        (
            (
                REFERENCE_QUERY_OWNER_SCHEMA_REF,
                Resource.from_contents(reference_query_owner_configuration_schema()),
            ),
            (
                REFERENCE_QUERY_MIXED_OWNER_SCHEMA_REF,
                Resource.from_contents(reference_query_mixed_owner_configuration_schema()),
            ),
        )
    )
    return Draft202012Validator(schema, registry=registry)


def reference_query_public_routed_owner_configuration_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/reference-query-owner-configuration-v5.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_REFERENCE_QUERY_OWNER_BYTES + 1)
    if sha256_bytes(raw) != PUBLIC_ROUTED_QUERY_OWNER_SCHEMA_SHA256:
        raise ReferenceQueryOwnerConfigurationError()
    schema: dict[str, Any] = json.loads(raw)
    if schema.get("$id") != PUBLIC_ROUTED_QUERY_OWNER_SCHEMA_REF:
        raise ReferenceQueryOwnerConfigurationError()
    return schema


@lru_cache(maxsize=1)
def _public_validator() -> Draft202012Validator:
    schema = reference_query_public_routed_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    registry = reference_query_execution_schema_registry().with_resources(
        (
            (
                REFERENCE_QUERY_OWNER_SCHEMA_REF,
                Resource.from_contents(reference_query_owner_configuration_schema()),
            ),
            (
                REFERENCE_QUERY_PUBLIC_OWNER_SCHEMA_REF,
                Resource.from_contents(reference_query_public_owner_configuration_schema()),
            ),
        )
    )
    return Draft202012Validator(schema, registry=registry)


class _RoutedQueryPolicyFields(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    cuda_native_execution_policy: ArtifactMemberPointer
    cuda_native_execution_policy_sha256: Sha256
    routing_policy: ArtifactMemberPointer
    routing_policy_sha256: Sha256
    controller_release: str = Field(strict=True, pattern=r"^[0-9a-f]{40}$")

    def _require_policy_pointer(self, cpu: SupportedReferenceQueryServiceConfiguration) -> None:
        pointer = self.cuda_native_execution_policy
        if (
            pointer.schema_ref != REFERENCE_QUERY_POLICY_REF
            or pointer.member_path != "policy.json"
            or pointer.media_type != "application/json"
            or pointer == cpu.native_execution_policy
            or self.cuda_native_execution_policy_sha256 == cpu.native_execution_policy_sha256
        ):
            raise ReferenceQueryOwnerConfigurationError()


class RoutedReferenceQueryOwnerConfiguration(_RoutedQueryPolicyFields):
    schema_version: Literal["reference-query-owner-configuration/3.0"]
    cpu_configuration: ReferenceQueryServiceConfiguration | ReferenceQueryServiceConfigurationV2

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_REFERENCE_QUERY_OWNER_BYTES:
                raise ReferenceQueryOwnerConfigurationError()
            _validator().validate(document)
            return document
        except Exception:
            raise ReferenceQueryOwnerConfigurationError() from None

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        self._require_policy_pointer(self.cpu_configuration)
        return self


class PublicRoutedReferenceQueryOwnerConfiguration(_RoutedQueryPolicyFields):
    schema_version: Literal["reference-query-owner-configuration/5.0"]
    cpu_configuration: ReferenceQueryPublicServiceConfiguration

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_REFERENCE_QUERY_OWNER_BYTES:
                raise ReferenceQueryOwnerConfigurationError()
            _public_validator().validate(document)
            return document
        except Exception:
            raise ReferenceQueryOwnerConfigurationError() from None

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        self._require_policy_pointer(self.cpu_configuration)
        return self


type SupportedRoutedReferenceQueryOwnerConfiguration = (
    RoutedReferenceQueryOwnerConfiguration | PublicRoutedReferenceQueryOwnerConfiguration
)


def validate_supported_routed_reference_query_configuration(
    value: object,
) -> SupportedRoutedReferenceQueryOwnerConfiguration:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict) and document.get("schema_version") == (
        "reference-query-owner-configuration/5.0"
    ):
        return PublicRoutedReferenceQueryOwnerConfiguration.model_validate(document)
    return RoutedReferenceQueryOwnerConfiguration.model_validate(document)


def supported_routed_reference_query_configuration_bytes(
    value: SupportedRoutedReferenceQueryOwnerConfiguration,
) -> bytes:
    checked = validate_supported_routed_reference_query_configuration(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def reference_query_routed_owner_configuration_bytes(
    value: RoutedReferenceQueryOwnerConfiguration,
) -> bytes:
    checked = RoutedReferenceQueryOwnerConfiguration.model_validate(value)
    document = checked.model_dump(mode="json")
    document["cpu_configuration"] = json.loads(
        supported_reference_query_service_configuration_bytes(checked.cpu_configuration)
    )
    return canonical_json_bytes(document)


def parse_reference_query_routed_owner_configuration(
    raw: bytes,
) -> RoutedReferenceQueryOwnerConfiguration:
    """Canonical roundtrip also rejects duplicate keys, constants and normalization."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_REFERENCE_QUERY_OWNER_BYTES:
            raise ReferenceQueryOwnerConfigurationError()
        checked = RoutedReferenceQueryOwnerConfiguration.model_validate(json.loads(raw))
        if reference_query_routed_owner_configuration_bytes(checked) != raw:
            raise ReferenceQueryOwnerConfigurationError()
        return checked
    except Exception:
        raise ReferenceQueryOwnerConfigurationError() from None


def parse_reference_query_installed_owner_selection(
    raw: bytes,
) -> tuple[
    SupportedReferenceQueryServiceConfiguration,
    SupportedRoutedReferenceQueryOwnerConfiguration | None,
]:
    """Explicit installed dispatcher; predecessor decoders still reject a routed wrapper."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_REFERENCE_QUERY_OWNER_BYTES:
            raise ReferenceQueryOwnerConfigurationError()
        document = json.loads(raw)
        if isinstance(document, dict) and document.get("schema_version") == (
            "reference-query-owner-configuration/5.0"
        ):
            public = PublicRoutedReferenceQueryOwnerConfiguration.model_validate(document)
            if supported_routed_reference_query_configuration_bytes(public) != raw:
                raise ReferenceQueryOwnerConfigurationError()
            return public.cpu_configuration, public
        if (
            isinstance(document, dict)
            and document.get("schema_version") == "reference-query-owner-configuration/3.0"
        ):
            routed = parse_reference_query_routed_owner_configuration(raw)
            return routed.cpu_configuration, routed
        return parse_supported_reference_query_service_configuration(raw), None
    except Exception:
        raise ReferenceQueryOwnerConfigurationError() from None


def require_routed_reference_query_policy(
    configuration: RoutedReferenceQueryOwnerConfiguration,
    routing: EmbeddingDeviceRoutingPolicy,
    cpu: ReferenceQueryExecutionPolicy,
    cuda: ReferenceQueryExecutionPolicy,
) -> None:
    """Pure policy/profile closure only; caller must resolve current canonical Artifacts."""
    configuration = RoutedReferenceQueryOwnerConfiguration.model_validate(configuration)
    require_supported_routed_reference_query_policy(configuration, routing, cpu, cuda)


def require_supported_routed_reference_query_policy(
    configuration: SupportedRoutedReferenceQueryOwnerConfiguration,
    routing: EmbeddingDeviceRoutingPolicy,
    cpu: ReferenceQueryExecutionPolicy,
    cuda: ReferenceQueryExecutionPolicy,
) -> None:
    """Same closure after explicit legacy/public family parsing, never runtime authority."""
    configuration = validate_supported_routed_reference_query_configuration(configuration)
    routing = EmbeddingDeviceRoutingPolicy.model_validate(routing)
    cpu = parse_reference_query_execution_policy(cpu)
    cuda = parse_reference_query_execution_policy(cuda)
    selected = configuration.cpu_configuration
    if (
        routing.purpose != "REFERENCE_QUERY"
        or routing.policy_sha256 != configuration.routing_policy_sha256
        or routing.view_recipe_sha256 != selected.recipe.recipe_sha256
        or selected.namespace.space_sha256 != routing.cpu.profile.space.space_sha256
        or cpu.policy_sha256 != selected.native_execution_policy_sha256
        or cuda.policy_sha256 != configuration.cuda_native_execution_policy_sha256
        or cpu.spaces.document != routing.cpu.profile.space
        or cuda.spaces.document != routing.cuda.profile.space
        or cpu.resource_profile != routing.cpu.profile.resource_profile
        or cuda.resource_profile != routing.cuda.profile.resource_profile
        or cpu.runtime_bundle != selected.runtime_bundle
        or cpu.runtime_bundle != routing.cpu.profile.runtime_bundle
        or cuda.runtime_bundle != routing.cuda.profile.runtime_bundle
        or cpu.workflow_definition_sha256 != cuda.workflow_definition_sha256
        or max(cpu.resource_profile.timeout_seconds, cuda.resource_profile.timeout_seconds)
        > MAX_EMBEDDING_WORK_BATCH_SECONDS
    ):
        raise ReferenceQueryOwnerConfigurationError()
