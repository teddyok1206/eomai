"""Explicit installed completed-read device controls; not a compute/fallback policy."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_reader_configuration import (
    MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
    SupportedSimilarityReaderConfiguration,
    parse_similarity_reader_configuration,
    parse_similarity_reader_configuration_v2,
)


class RoutedSimilarityReaderConfiguration(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["system-rag-similarity-reader-configuration/3.0"]
    cpu_configuration: Annotated[
        SupportedSimilarityReaderConfiguration, Field(discriminator="schema_version")
    ]
    cuda_document_space: EmbeddingSpace
    cuda_native_execution_policy: ArtifactMemberPointer
    cuda_native_execution_policy_sha256: Sha256
    cuda_runtime_bundle: EmbeddingRuntimeBundlePointer

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value,
            "system-rag-similarity-reader-configuration-v3",
            MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
        )

    @model_validator(mode="after")
    def separate_devices(self) -> Self:
        cpu = self.cpu_configuration
        if (
            cpu.document_space.runtime.device != "CPU"
            or self.cuda_document_space.runtime.device != "CUDA"
            or self.cuda_document_space.purpose != "DOCUMENT"
            or self.cuda_native_execution_policy == cpu.native_execution_policy
            or self.cuda_native_execution_policy_sha256 == cpu.native_execution_policy_sha256
            or self.cuda_runtime_bundle == cpu.runtime_bundle
        ):
            raise ValueError("SIMILARITY_READER_DEVICE_CONTROLS_INVALID")
        return self


def routed_similarity_reader_configuration_bytes(
    value: RoutedSimilarityReaderConfiguration,
) -> bytes:
    checked = RoutedSimilarityReaderConfiguration.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_similarity_reader_installed_selection(
    raw: bytes,
) -> tuple[SupportedSimilarityReaderConfiguration, RoutedSimilarityReaderConfiguration | None]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SIMILARITY_READER_CONFIGURATION_BYTES:
        raise ValueError("SIMILARITY_READER_CONFIGURATION_INVALID")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("SIMILARITY_READER_CONFIGURATION_INVALID")
    version = value.get("schema_version")
    if version == "system-rag-similarity-reader-configuration/3.0":
        wrapper = RoutedSimilarityReaderConfiguration.model_validate(value)
        if routed_similarity_reader_configuration_bytes(wrapper) != raw:
            raise ValueError("SIMILARITY_READER_CONFIGURATION_INVALID")
        return wrapper.cpu_configuration, wrapper
    if version == "system-rag-similarity-reader-configuration/2.0":
        return parse_similarity_reader_configuration_v2(raw), None
    return parse_similarity_reader_configuration(raw), None


def require_same_routed_reader_controls(
    primary: RoutedSimilarityReaderConfiguration | None,
    mixed: RoutedSimilarityReaderConfiguration | None,
) -> None:
    """Cohost families share installed device controls, not their source class grants."""
    if (primary is None) != (mixed is None):
        raise ValueError("SIMILARITY_READER_DEVICE_COHOST_MISMATCH")
    if primary is not None and mixed is not None:
        primary = RoutedSimilarityReaderConfiguration.model_validate(primary)
        mixed = RoutedSimilarityReaderConfiguration.model_validate(mixed)
        for name in (
            "cuda_document_space",
            "cuda_native_execution_policy",
            "cuda_native_execution_policy_sha256",
            "cuda_runtime_bundle",
        ):
            if getattr(primary, name) != getattr(mixed, name):
                raise ValueError("SIMILARITY_READER_DEVICE_COHOST_MISMATCH")
