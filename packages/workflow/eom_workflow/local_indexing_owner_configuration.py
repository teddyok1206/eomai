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

from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.schemas import local_embedding_admission_schema_registry

LOCAL_INDEXING_OWNER_SCHEMA_REF = "eom://schemas/workflow/local-indexing-owner-configuration/1.0"
LOCAL_INDEXING_OWNER_SCHEMA_SHA256 = (
    "sha256:9d31827404897c154c0412b74f00112cf5f8192b0fd668bdf27801a26b7e3e39"
)
MAX_LOCAL_INDEXING_OWNER_BYTES = 64 * 1024
_RESOURCE = "local-indexing-owner-configuration-v1.schema.json"


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


class LocalIndexingRuntimeVerifierPin(_OwnerValue):
    source_commit: str = Field(strict=True, pattern=r"^[0-9a-f]{40}$")
    script_raw_sha256: Sha256


class LocalIndexingOwnerConfiguration(_OwnerValue):
    schema_version: Literal["local-indexing-owner-configuration/1.0"]
    corpus_id: str = Field(strict=True, pattern=r"^corpus_[0-9a-f]{32}$")
    namespace: EmbeddingIndexNamespace
    recipe: ExperimentViewRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
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
    maximum_sources: int = Field(strict=True, ge=1, le=1024)

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

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if (
            self.namespace.space_sha256 != self.runtime_profile.space.space_sha256
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.database_owner.role_name == "eom_catalog_manager_runtime"
            or self.maximum_targets > self.maximum_sources
        ):
            raise LocalIndexingOwnerConfigurationError()
        return self


def local_indexing_owner_configuration_bytes(value: LocalIndexingOwnerConfiguration) -> bytes:
    try:
        checked = LocalIndexingOwnerConfiguration.model_validate(
            raw_similarity_contract_value(value)
        )
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


def parse_local_indexing_owner_configuration(raw: bytes) -> LocalIndexingOwnerConfiguration:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_OWNER_BYTES:
        raise LocalIndexingOwnerConfigurationError()
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        checked = LocalIndexingOwnerConfiguration.model_validate(value)
        if local_indexing_owner_configuration_bytes(checked) != raw:
            raise LocalIndexingOwnerConfigurationError()
        return checked
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None
