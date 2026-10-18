"""Closed deployment values; never installation, device ownership or execution admission."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Literal

from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eom_workflow.local_embedding_execution_policy import (
    LocalEmbeddingExecutionPolicy,
    LocalEmbeddingRuntimeProfile,
    LocalEmbeddingServiceExecutionPolicy,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF = (
    "eom://schemas/workflow/native-embedding-backend-selection/1.0"
)
NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_SHA256 = (
    "sha256:3ef1d2da0106f12239164f2dce80cbe71521ec518f693f16caf8f014cf30ca15"
)
MAX_NATIVE_EMBEDDING_BACKEND_SELECTION_BYTES = 16 * 1024
_RESOURCE = "native-embedding-backend-selection-v1.schema.json"


class NativeEmbeddingBackendSelectionError(ValueError):
    def __init__(self) -> None:
        super().__init__("NATIVE_EMBEDDING_BACKEND_SELECTION_INVALID")


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with files("eom_workflow").joinpath("resources", _RESOURCE).open("rb") as stream:
        raw = stream.read(MAX_NATIVE_EMBEDDING_BACKEND_SELECTION_BYTES + 1)
    if (
        not 0 < len(raw) <= MAX_NATIVE_EMBEDDING_BACKEND_SELECTION_BYTES
        or sha256_bytes(raw) != NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_SHA256
    ):
        raise NativeEmbeddingBackendSelectionError()
    return raw


def native_embedding_backend_selection_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(_schema_raw())
    if schema.get("$id") != NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF:
        raise NativeEmbeddingBackendSelectionError()
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = native_embedding_backend_selection_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=local_embedding_admission_schema_registry())


class _BackendValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)


class LocalIndexingRuntimeVerifierPin(_BackendValue):
    """The released CPU verifier value, also re-exported from its original module."""

    source_commit: str = Field(strict=True, pattern=r"^[0-9a-f]{40}$")
    script_raw_sha256: Sha256


class NativeCpuBackendSelection(_BackendValue):
    device: Literal["CPU"]
    runtime_verifier: LocalIndexingRuntimeVerifierPin
    cpu_environment_raw_sha256: Sha256


class NativeCudaBackendSelection(_BackendValue):
    device: Literal["CUDA"]
    configuration: RootLocalNativeConfigurationPin
    receipt_raw_sha256: Sha256
    cuda_environment_raw_sha256: Sha256


class NativeEmbeddingBackendSelection(_BackendValue):
    schema_version: Literal["native-embedding-backend-selection/1.0"]
    purpose: Literal["INDEX", "REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"]
    backend: Annotated[
        NativeCpuBackendSelection | NativeCudaBackendSelection, Field(discriminator="device")
    ]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > MAX_NATIVE_EMBEDDING_BACKEND_SELECTION_BYTES:
                raise NativeEmbeddingBackendSelectionError()
            _validator().validate(document)
            return document
        except Exception:
            raise NativeEmbeddingBackendSelectionError() from None

    @property
    def device(self) -> Literal["CPU", "CUDA"]:
        return self.backend.device


def native_embedding_backend_selection_bytes(value: NativeEmbeddingBackendSelection) -> bytes:
    try:
        checked = NativeEmbeddingBackendSelection.model_validate(
            raw_similarity_contract_value(value)
        )
        return canonical_json_bytes(raw_similarity_contract_value(checked))
    except Exception:
        raise NativeEmbeddingBackendSelectionError() from None


def parse_native_embedding_backend_selection(raw: bytes) -> NativeEmbeddingBackendSelection:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_NATIVE_EMBEDDING_BACKEND_SELECTION_BYTES:
        raise NativeEmbeddingBackendSelectionError()
    try:
        checked = NativeEmbeddingBackendSelection.model_validate(json.loads(raw))
        # The canonical equality also rejects duplicate keys and noncanonical scalars.
        if native_embedding_backend_selection_bytes(checked) != raw:
            raise NativeEmbeddingBackendSelectionError()
        return checked
    except Exception:
        raise NativeEmbeddingBackendSelectionError() from None


def select_native_index_runtime_profile(
    selection: NativeEmbeddingBackendSelection,
    policy: LocalEmbeddingExecutionPolicy | LocalEmbeddingServiceExecutionPolicy,
) -> LocalEmbeddingRuntimeProfile:
    """Pure resolved-policy consistency; this neither selects a launcher nor grants compute."""
    try:
        checked = NativeEmbeddingBackendSelection.model_validate(
            raw_similarity_contract_value(selection)
        )
        if type(policy) not in (
            LocalEmbeddingExecutionPolicy,
            LocalEmbeddingServiceExecutionPolicy,
        ):
            raise NativeEmbeddingBackendSelectionError()
        policy = type(policy).model_validate(raw_similarity_contract_value(policy))
        if checked.purpose != "INDEX" or checked.device != policy.default_device:
            raise NativeEmbeddingBackendSelectionError()
        matches = tuple(
            profile
            for profile in policy.profiles
            if profile.resource_profile.device == checked.device
        )
        if len(matches) != 1:
            raise NativeEmbeddingBackendSelectionError()
        return matches[0]
    except Exception:
        raise NativeEmbeddingBackendSelectionError() from None
