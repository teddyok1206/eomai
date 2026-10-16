"""Synthetic1.1 metadata, not installed snapshots, root receipts or real model execution."""

from __future__ import annotations

from eom_catalog_contracts.embedding_host_configuration import parse_host_configuration_snapshot
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProof,
    EmbeddingRuntimeProfile,
)
from eom_catalog_contracts.embedding_native_runtime_config import EmbeddingNativeRuntimeConfigV11
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundle

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_host_configuration_contracts import snapshot_body, snapshot_pointer


def native_config_metadata_v11(
    profile: EmbeddingRuntimeProfile = "CPU_INDEX_FP32",
) -> tuple[EmbeddingNativeRuntimeConfigV11, EmbeddingRuntimeBundle, EmbeddingInstalledRuntimeProof]:
    config, bundle, proof = native_config_metadata(profile)
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    body = config.model_dump(mode="json")
    body.update(
        schema_version="embedding-native-runtime-config/1.1",
        configuration_revision_id="embeddingnativeconfigrev_" + "e" * 32,
        host_configuration=snapshot_pointer(snapshot).model_dump(mode="json"),
    )
    return (
        EmbeddingNativeRuntimeConfigV11.model_validate(seal(body, "config_sha256")),
        bundle,
        proof,
    )
