"""Closed non-secret deployment selection, never user/source/native authority."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.local_indexing_owner_configuration import (
    LocalIndexingOwnerDatabasePin,
    LocalIndexingRuntimeVerifierPin,
)
from eom_workflow.schemas import reference_query_execution_schema_registry

REFERENCE_QUERY_OWNER_SCHEMA_REF = "eom://schemas/workflow/reference-query-owner-configuration/1.0"
REFERENCE_QUERY_OWNER_SCHEMA_SHA256 = (
    "sha256:41c63c8bcf2e1191ffd51ef860de87a2cd16d907673aabf5d64d92e452bef862"
)
MAX_REFERENCE_QUERY_OWNER_BYTES = 64 * 1024
_RESOURCE = "reference-query-owner-configuration-v1.schema.json"


class ReferenceQueryOwnerConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("REFERENCE_QUERY_OWNER_CONFIGURATION_INVALID")


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with files("eom_workflow").joinpath("resources", _RESOURCE).open("rb") as stream:
        raw = stream.read(16 * 1024 + 1)
    if len(raw) > 16 * 1024 or sha256_bytes(raw) != REFERENCE_QUERY_OWNER_SCHEMA_SHA256:
        raise ReferenceQueryOwnerConfigurationError()
    return raw


def reference_query_owner_configuration_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(_schema_raw())
    if schema.get("$id") != REFERENCE_QUERY_OWNER_SCHEMA_REF:
        raise ReferenceQueryOwnerConfigurationError()
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = reference_query_owner_configuration_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=reference_query_execution_schema_registry().with_resource(
            REFERENCE_QUERY_OWNER_SCHEMA_REF, Resource.from_contents(schema)
        ),
    )


class _QueryOwnerValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)


class ReferenceQueryProviderCodePin(_QueryOwnerValue):
    member: str = Field(
        strict=True, pattern=r"^[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)+\.py$", max_length=240
    )
    sha256: Sha256


class ReferenceQueryProviderConfiguration(_QueryOwnerValue):
    source_commit: str = Field(strict=True, pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40)
    wheel_sha256: Sha256
    configuration_sha256: Sha256
    code_members: tuple[ReferenceQueryProviderCodePin, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_members(self) -> Self:
        members = tuple(pin.member for pin in self.code_members)
        if members != tuple(sorted(set(members))):
            raise ReferenceQueryOwnerConfigurationError()
        return self


class ReferenceQueryServiceConfiguration(_QueryOwnerValue):
    schema_version: Literal["reference-query-owner-configuration/1.0"]
    owner_source_commit: str = Field(
        strict=True, pattern=r"^[0-9a-f]{40}$", min_length=40, max_length=40
    )
    corpus_id: str = Field(strict=True, pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: EmbeddingIndexNamespace
    recipe: ExperimentViewRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    runtime_bundle: EmbeddingRuntimeBundlePointer
    database_owner: LocalIndexingOwnerDatabasePin
    runtime_verifier: LocalIndexingRuntimeVerifierPin
    cpu_environment_raw_sha256: Sha256
    owner_environment_raw_sha256: Sha256
    api_provider: ReferenceQueryProviderConfiguration

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
        if (
            self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.database_owner.role_name != "eom_app"
        ):
            raise ReferenceQueryOwnerConfigurationError()
        return self


def reference_query_service_configuration_bytes(value: ReferenceQueryServiceConfiguration) -> bytes:
    try:
        checked = ReferenceQueryServiceConfiguration.model_validate(
            raw_similarity_contract_value(value)
        )
        return canonical_json_bytes(raw_similarity_contract_value(checked))
    except Exception:
        raise ReferenceQueryOwnerConfigurationError() from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceQueryOwnerConfigurationError()
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ReferenceQueryOwnerConfigurationError()


def parse_reference_query_service_configuration(raw: bytes) -> ReferenceQueryServiceConfiguration:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_REFERENCE_QUERY_OWNER_BYTES:
        raise ReferenceQueryOwnerConfigurationError()
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        checked = ReferenceQueryServiceConfiguration.model_validate(value)
        if reference_query_service_configuration_bytes(checked) != raw:
            raise ReferenceQueryOwnerConfigurationError()
        return checked
    except Exception:
        raise ReferenceQueryOwnerConfigurationError() from None
