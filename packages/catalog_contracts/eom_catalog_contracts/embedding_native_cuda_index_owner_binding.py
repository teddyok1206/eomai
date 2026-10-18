"""Original owner-process linkage only; not authority, backend selection or root ACK."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_native_cpu_probe import ExecutionId
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256

NATIVE_CUDA_INDEX_OWNER_BINDING_SCHEMA = "embedding-native-cuda-index-owner-binding"
MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES = 1024


class NativeCudaIndexOwnerBinding(FrozenModel):
    """A claimed original PID/birth, requiring protected staging and fresh kernel checks."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["embedding-native-cuda-index-owner-binding/1.0"]
    execution_id: ExecutionId
    launch_association_sha256: Sha256
    owner_pid: int = Field(ge=1, le=2147483647, strict=True)
    owner_start_ticks: int = Field(ge=1, le=18446744073709551615, strict=True)
    binding_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def exact_raw_wire(cls, value: object) -> object:
        return similarity_contract_document(
            value, NATIVE_CUDA_INDEX_OWNER_BINDING_SCHEMA, MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES
        )

    @model_validator(mode="after")
    def exact_hash(self) -> NativeCudaIndexOwnerBinding:
        if self.binding_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"binding_sha256"})
        ):
            raise ValueError("NATIVE_CUDA_INDEX_OWNER_BINDING_HASH_INVALID")
        return self


def native_cuda_index_owner_binding_bytes(value: NativeCudaIndexOwnerBinding) -> bytes:
    checked = NativeCudaIndexOwnerBinding.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_native_cuda_index_owner_binding(raw: bytes) -> NativeCudaIndexOwnerBinding:
    document = parse_rootlocal_evidence_document(raw, MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES)
    value = NativeCudaIndexOwnerBinding.model_validate(document)
    if native_cuda_index_owner_binding_bytes(value) != raw:
        raise ValueError("NATIVE_CUDA_INDEX_OWNER_BINDING_NONCANONICAL")
    return value
