"""Non-secret fixed reader selection; no source, operator or native execution grant."""

from __future__ import annotations

import json
from typing import Literal

from eom_identifiers import canonical_json_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSpace
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.models import FrozenModel, Sha256

MAX_SIMILARITY_READER_CONFIGURATION_BYTES = 64 * 1024


class SimilarityReaderDatabaseOwner(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    role_name: str = Field(strict=True, pattern=r"^[a-z][a-z0-9_]{0,62}$")
    role_oid: int = Field(strict=True, ge=1, le=4294967295)


class _ReaderSelectionFields(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    corpus_id: str = Field(strict=True, pattern=r"^corpus_[0-9a-f]{32}$")
    document_space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]
    native_execution_policy: ArtifactMemberPointer
    native_execution_policy_sha256: Sha256
    runtime_bundle: EmbeddingRuntimeBundlePointer
    database_owner: SimilarityReaderDatabaseOwner

    def _require_namespace(
        self, namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace
    ) -> None:
        if (
            namespace.space_sha256 != self.document_space.space_sha256
            or namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_classes != tuple(sorted(set(self.source_classes)))
        ):
            raise ValueError("similarity reader namespace/space/recipe/source selection differs")


class SimilarityReaderConfiguration(_ReaderSelectionFields):
    schema_version: Literal["system-rag-similarity-reader-configuration/1.0"]
    namespace: EmbeddingIndexNamespace

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value,
            "system-rag-similarity-reader-configuration",
            MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
        )

    @model_validator(mode="after")
    def exact_namespace(self) -> SimilarityReaderConfiguration:
        self._require_namespace(self.namespace)
        return self


class SimilarityReaderConfigurationV2(_ReaderSelectionFields):
    schema_version: Literal["system-rag-similarity-reader-configuration/2.0"]
    namespace: MixedEmbeddingIndexNamespace

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value,
            "system-rag-similarity-reader-configuration-v2",
            MAX_SIMILARITY_READER_CONFIGURATION_BYTES,
        )

    @model_validator(mode="after")
    def exact_namespace(self) -> SimilarityReaderConfigurationV2:
        self._require_namespace(self.namespace)
        if self.document_space.runtime.device != "CPU":
            raise ValueError("mixed similarity reader requires its selected CPU document space")
        return self


type SupportedSimilarityReaderConfiguration = (
    SimilarityReaderConfiguration | SimilarityReaderConfigurationV2
)


def require_mixed_similarity_reader_cohost(
    primary: SimilarityReaderConfiguration, mixed: SimilarityReaderConfigurationV2
) -> None:
    """Compare deployment scope only; real read authority remains the Catalog fence."""
    primary = SimilarityReaderConfiguration.model_validate(raw_similarity_contract_value(primary))
    mixed = SimilarityReaderConfigurationV2.model_validate(raw_similarity_contract_value(mixed))
    if (
        primary.database_owner != mixed.database_owner
        or primary.document_space != mixed.document_space
        or primary.corpus_id != mixed.corpus_id
        or primary.recipe != mixed.recipe
        or primary.native_execution_policy != mixed.native_execution_policy
        or primary.native_execution_policy_sha256 != mixed.native_execution_policy_sha256
        or primary.runtime_bundle != mixed.runtime_bundle
    ):
        raise ValueError("mixed similarity reader cohost deployment scope differs")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, child in pairs:
        if name in value:
            raise ValueError("duplicate reader configuration field")
        value[name] = child
    return value


def _no_constant(_value: str) -> object:
    raise ValueError("reader configuration cannot contain non-JSON values")


def parse_similarity_reader_configuration(raw: bytes) -> SimilarityReaderConfiguration:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SIMILARITY_READER_CONFIGURATION_BYTES:
        raise ValueError("similarity reader configuration exceeds its byte bound")
    value = SimilarityReaderConfiguration.model_validate(
        json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_no_constant)
    )
    if canonical_json_bytes(raw_similarity_contract_value(value)) != raw:
        raise ValueError("reader configuration must have exact canonical bytes")
    return value


def parse_similarity_reader_configuration_v2(raw: bytes) -> SimilarityReaderConfigurationV2:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SIMILARITY_READER_CONFIGURATION_BYTES:
        raise ValueError("similarity reader configuration exceeds its byte bound")
    value = SimilarityReaderConfigurationV2.model_validate(
        json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_no_constant)
    )
    if canonical_json_bytes(raw_similarity_contract_value(value)) != raw:
        raise ValueError("reader configuration must have exact canonical bytes")
    return value
