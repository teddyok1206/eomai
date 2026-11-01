"""Closed optional service selection, bound to one unchanged protected reference baseline."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryExecutionPolicyV2
from eom_workflow.reference_query_owner_configuration import (
    ReferenceQueryServiceConfiguration,
    reference_query_service_configuration_bytes,
)
from eom_workflow.reference_query_routed_owner_configuration import (
    PublicRoutedReferenceQueryOwnerConfiguration,
    supported_routed_reference_query_configuration_bytes,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

PRIVATE_CHAT_QUERY_OWNER_SCHEMA_REF = (
    "eom://schemas/workflow/private-chat-query-owner-configuration/1.0"
)
PRIVATE_CHAT_QUERY_OWNER_SCHEMA_SHA256 = (
    "sha256:1de1033a657b6cfdf446fb71b68214aa79dd29f60104eeb449aa27c89f2be2fa"
)
MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES = 16 * 1024
_RESOURCE = "private-chat-query-owner-configuration-v1.schema.json"
PRIVATE_CHAT_PUBLIC_QUERY_OWNER_SCHEMA_REF = (
    "eom://schemas/workflow/private-chat-query-owner-configuration/2.0"
)
PRIVATE_CHAT_PUBLIC_QUERY_OWNER_SCHEMA_SHA256 = (
    "sha256:ed48f9b3b0a430207dd94aa4ab6859c6a8a548a347611282b454508f5273ddb8"
)


class PrivateChatQueryOwnerConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_INVALID")


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with files("eom_workflow").joinpath("resources", _RESOURCE).open("rb") as stream:
        raw = stream.read(16 * 1024 + 1)
    if len(raw) > 16 * 1024 or sha256_bytes(raw) != PRIVATE_CHAT_QUERY_OWNER_SCHEMA_SHA256:
        raise PrivateChatQueryOwnerConfigurationError()
    return raw


def private_chat_query_owner_configuration_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(_schema_raw())
    if schema.get("$id") != PRIVATE_CHAT_QUERY_OWNER_SCHEMA_REF:
        raise PrivateChatQueryOwnerConfigurationError()
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = private_chat_query_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=local_embedding_admission_schema_registry().with_resource(
            PRIVATE_CHAT_QUERY_OWNER_SCHEMA_REF, Resource.from_contents(schema)
        ),
    )


def private_chat_public_query_owner_configuration_schema() -> dict[str, Any]:
    with (
        files("eom_workflow")
        .joinpath("resources/private-chat-query-owner-configuration-v2.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES + 1)
    if (
        not 0 < len(raw) <= MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES
        or sha256_bytes(raw) != PRIVATE_CHAT_PUBLIC_QUERY_OWNER_SCHEMA_SHA256
    ):
        raise PrivateChatQueryOwnerConfigurationError()
    schema: dict[str, Any] = json.loads(raw)
    if schema.get("$id") != PRIVATE_CHAT_PUBLIC_QUERY_OWNER_SCHEMA_REF:
        raise PrivateChatQueryOwnerConfigurationError()
    return schema


@lru_cache(maxsize=1)
def _public_validator() -> Draft202012Validator:
    schema = private_chat_public_query_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=local_embedding_admission_schema_registry())


class PrivateChatQueryServiceConfiguration(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    schema_version: Literal["private-chat-query-owner-configuration/1.0"]
    reference_configuration_raw_sha256: Sha256
    corpus_id: str = Field(strict=True, pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: EmbeddingIndexNamespace
    recipe: ExperimentViewRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    runtime_bundle: EmbeddingRuntimeBundlePointer
    owner_environment_raw_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES:
                raise PrivateChatQueryOwnerConfigurationError()
            _validator().validate(document)
            return document
        except Exception:
            raise PrivateChatQueryOwnerConfigurationError() from None

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if (
            self.namespace.view != "CONTENT_ONLY"
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_classes != tuple(sorted(set(self.source_classes)))
        ):
            raise PrivateChatQueryOwnerConfigurationError()
        return self


class PrivateChatQueryPublicServiceConfiguration(BaseModel):
    """Common corpus and private CPU/CUDA policies, pinned to the real public cohost.

    This configuration cannot borrow reference execution authority. Both private
    policies and the private-purpose routing policy must be independently read.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    schema_version: Literal["private-chat-query-owner-configuration/2.0"]
    reference_configuration_raw_sha256: Sha256
    corpus_id: str = Field(strict=True, pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: PublicSolutionIndexNamespace
    recipe: PublicSolutionEmbeddingRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    runtime_bundle: EmbeddingRuntimeBundlePointer
    owner_environment_raw_sha256: Sha256
    cuda_native_execution_policy: ArtifactMemberPointer
    cuda_native_execution_policy_sha256: Sha256
    routing_policy: ArtifactMemberPointer
    routing_policy_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES:
                raise PrivateChatQueryOwnerConfigurationError()
            _public_validator().validate(document)
            return document
        except Exception:
            raise PrivateChatQueryOwnerConfigurationError() from None

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if (
            self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.native_execution_policy == self.cuda_native_execution_policy
            or self.native_execution_policy_sha256 == self.cuda_native_execution_policy_sha256
        ):
            raise PrivateChatQueryOwnerConfigurationError()
        return self


def private_chat_query_service_configuration_bytes(
    value: PrivateChatQueryServiceConfiguration,
) -> bytes:
    try:
        checked = PrivateChatQueryServiceConfiguration.model_validate(
            raw_similarity_contract_value(value)
        )
        return canonical_json_bytes(raw_similarity_contract_value(checked))
    except Exception:
        raise PrivateChatQueryOwnerConfigurationError() from None


def parse_private_chat_query_service_configuration(
    raw: bytes,
) -> PrivateChatQueryServiceConfiguration:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES:
        raise PrivateChatQueryOwnerConfigurationError()
    try:
        checked = PrivateChatQueryServiceConfiguration.model_validate(json.loads(raw))
        # Canonical bytes also reject duplicate JSON keys, even equal-value ones.
        if private_chat_query_service_configuration_bytes(checked) != raw:
            raise PrivateChatQueryOwnerConfigurationError()
        return checked
    except Exception:
        raise PrivateChatQueryOwnerConfigurationError() from None


def require_private_chat_query_reference_configuration(
    private: PrivateChatQueryServiceConfiguration, reference: ReferenceQueryServiceConfiguration
) -> None:
    """Pure deployment identity check; only the supervisor establishes protected-file provenance."""
    private = PrivateChatQueryServiceConfiguration.model_validate(
        raw_similarity_contract_value(private)
    )
    if private.reference_configuration_raw_sha256 != sha256_bytes(
        reference_query_service_configuration_bytes(reference)
    ):
        raise PrivateChatQueryOwnerConfigurationError()


type SupportedPrivateChatQueryServiceConfiguration = (
    PrivateChatQueryServiceConfiguration | PrivateChatQueryPublicServiceConfiguration
)


def supported_private_chat_query_service_configuration_bytes(
    value: SupportedPrivateChatQueryServiceConfiguration,
) -> bytes:
    try:
        document = raw_similarity_contract_value(value)
        if isinstance(document, dict) and document.get("schema_version") == (
            "private-chat-query-owner-configuration/2.0"
        ):
            checked = PrivateChatQueryPublicServiceConfiguration.model_validate(document)
            return canonical_json_bytes(checked)
        return private_chat_query_service_configuration_bytes(
            PrivateChatQueryServiceConfiguration.model_validate(document)
        )
    except Exception:
        raise PrivateChatQueryOwnerConfigurationError() from None


def parse_supported_private_chat_query_service_configuration(
    raw: bytes,
) -> SupportedPrivateChatQueryServiceConfiguration:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_PRIVATE_CHAT_QUERY_OWNER_BYTES:
            raise PrivateChatQueryOwnerConfigurationError()
        document = json.loads(raw)
        if isinstance(document, dict) and document.get("schema_version") == (
            "private-chat-query-owner-configuration/2.0"
        ):
            checked = PrivateChatQueryPublicServiceConfiguration.model_validate(document)
            if supported_private_chat_query_service_configuration_bytes(checked) != raw:
                raise PrivateChatQueryOwnerConfigurationError()
            return checked
        return parse_private_chat_query_service_configuration(raw)
    except Exception:
        raise PrivateChatQueryOwnerConfigurationError() from None


def require_private_chat_public_query_reference_configuration(
    private: PrivateChatQueryPublicServiceConfiguration,
    reference: PublicRoutedReferenceQueryOwnerConfiguration,
) -> None:
    """Exact same protected cohost/common corpus, not a runtime or user permission grant."""
    private = PrivateChatQueryPublicServiceConfiguration.model_validate(
        raw_similarity_contract_value(private)
    )
    reference = PublicRoutedReferenceQueryOwnerConfiguration.model_validate(
        raw_similarity_contract_value(reference)
    )
    cpu = reference.cpu_configuration
    if (
        private.reference_configuration_raw_sha256
        != sha256_bytes(supported_routed_reference_query_configuration_bytes(reference))
        or private.corpus_id != cpu.corpus_id
        or private.namespace != cpu.namespace
        or private.recipe != cpu.recipe
        or private.source_classes != cpu.source_classes
        or private.runtime_bundle != cpu.runtime_bundle
        or private.owner_environment_raw_sha256 != cpu.owner_environment_raw_sha256
    ):
        raise PrivateChatQueryOwnerConfigurationError()


def require_private_chat_public_query_policies(
    configuration: PrivateChatQueryPublicServiceConfiguration,
    routing: EmbeddingDeviceRoutingPolicy,
    cpu: PrivateChatQueryExecutionPolicyV2,
    cuda: PrivateChatQueryExecutionPolicyV2,
) -> None:
    """Pure exact Artifact/profile closure; canonical read and native admission stay outside."""
    configuration = PrivateChatQueryPublicServiceConfiguration.model_validate(
        raw_similarity_contract_value(configuration)
    )
    routing = EmbeddingDeviceRoutingPolicy.model_validate(raw_similarity_contract_value(routing))
    cpu = PrivateChatQueryExecutionPolicyV2.model_validate(raw_similarity_contract_value(cpu))
    cuda = PrivateChatQueryExecutionPolicyV2.model_validate(raw_similarity_contract_value(cuda))
    if (
        routing.purpose != "PRIVATE_CHAT_QUERY"
        or routing.view_recipe_sha256 != configuration.recipe.recipe_sha256
        or configuration.namespace.space_sha256 != routing.cpu.profile.space.space_sha256
        or configuration.runtime_bundle != cpu.runtime_bundle
        or cpu.workflow_definition_sha256 != cuda.workflow_definition_sha256
        or max(cpu.resource_profile.timeout_seconds, cuda.resource_profile.timeout_seconds)
        > MAX_EMBEDDING_WORK_BATCH_SECONDS
    ):
        raise PrivateChatQueryOwnerConfigurationError()
    for pointer, expected_sha, policy in (
        (configuration.native_execution_policy, configuration.native_execution_policy_sha256, cpu),
        (
            configuration.cuda_native_execution_policy,
            configuration.cuda_native_execution_policy_sha256,
            cuda,
        ),
        (configuration.routing_policy, configuration.routing_policy_sha256, routing),
    ):
        if (
            pointer.sha256 != sha256_bytes(canonical_json_bytes(policy))
            or expected_sha != policy.policy_sha256
        ):
            raise PrivateChatQueryOwnerConfigurationError()
    for policy, profile in ((cpu, routing.cpu.profile), (cuda, routing.cuda.profile)):
        if (
            policy.spaces.document != profile.space
            or policy.runtime_bundle != profile.runtime_bundle
            or policy.resource_profile != profile.resource_profile
        ):
            raise PrivateChatQueryOwnerConfigurationError()
