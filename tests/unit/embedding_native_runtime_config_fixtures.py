"""Tiny synthetic installation metadata; no installed environment or authority proof."""

from __future__ import annotations

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProof,
    EmbeddingRuntimeProfile,
)
from eom_catalog_contracts.embedding_native_runtime_config import EmbeddingNativeRuntimeConfig
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    embedding_payload_file_set_sha256,
    embedding_runtime_bundle_bytes,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import benchmark_family, benchmark_runtime
from tests.unit.embedding_installed_runtime_fixtures import proof_pointer, runtime_proof
from tests.unit.inference_transfer_embedding_fixtures import seal


def native_config_metadata(
    profile: EmbeddingRuntimeProfile = "CPU_INDEX_FP32",
) -> tuple[EmbeddingNativeRuntimeConfig, EmbeddingRuntimeBundle, EmbeddingInstalledRuntimeProof]:
    runtime = benchmark_runtime("CPU" if profile == "CPU_INDEX_FP32" else "CUDA")
    proof_body = runtime_proof(profile).model_dump(mode="json")
    proof_body.update(
        proof_id=runtime.installed_proof.proof_id,
        proof_revision_id=runtime.installed_proof.proof_revision_id,
    )
    proof = EmbeddingInstalledRuntimeProof.model_validate(seal(proof_body, "proof_sha256"))
    payload = benchmark_family().model
    bundle = EmbeddingRuntimeBundle.model_validate(
        seal(
            {
                "schema_version": "embedding-runtime-bundle/1.0",
                "bundle_id": runtime.bundle.bundle_id,
                "bundle_revision_id": runtime.bundle.bundle_revision_id,
                "payload_pointer": {
                    "model_id": payload.model_id,
                    "model_revision_id": payload.model_revision_id,
                    "schema_ref": "eom://schemas/knowledge/item-inference-transfer/1.0#/$defs/localEmbeddingModel",
                    "manifest_sha256": payload.manifest_sha256,
                    "manifest_raw_sha256": sha256_bytes(
                        canonical_json_bytes(payload.model_dump(mode="json"))
                    ),
                    "file_set_sha256": embedding_payload_file_set_sha256(payload),
                },
                "payload_model_spec": payload.model_dump(mode="json"),
                "execution_model_spec": runtime.spaces.document.model_spec.model_dump(mode="json"),
                "numerical_runtime": runtime.numerical_runtime.model_dump(mode="json"),
            },
            "bundle_sha256",
        )
    )
    pointer_body = runtime.bundle.model_dump(mode="json")
    pointer_body["bundle_sha256"] = bundle.bundle_sha256
    pointer_body["bundle_raw_sha256"] = sha256_bytes(embedding_runtime_bundle_bytes(bundle))
    pointer_body["manifest_member"]["sha256"] = pointer_body["bundle_raw_sha256"]
    resource_body = {
        "batch_size": 4,
        "threads": 4,
        "interop_threads": 1,
        "cpu_quota_percent": 400,
        "tasks_max": 64,
        "ram_limit_bytes": 6 * 1024**3,
        "timeout_seconds": 180,
        "maximum_active_launches": 1,
        "index_output_limit_bytes": 64 * 1024**2,
        "benchmark_output_limit_bytes": 16 * 1024**2,
        "vram_limit_bytes": 0 if profile == "CPU_INDEX_FP32" else 8 * 1024**3,
    }
    config = EmbeddingNativeRuntimeConfig.model_validate(
        seal(
            {
                "schema_version": "embedding-native-runtime-config/1.0",
                "configuration_id": "embeddingnativeconfig_" + "5" * 32,
                "configuration_revision_id": "embeddingnativeconfigrev_"
                + ("6" if profile == "CPU_INDEX_FP32" else "7") * 32,
                "profile": profile,
                "bundle": pointer_body,
                "installed_proof": proof_pointer(proof).model_dump(mode="json"),
                "runtime_sha256": bundle.numerical_runtime.runtime_sha256,
                "resources": seal(resource_body, "resource_sha256"),
            },
            "config_sha256",
        )
    )
    return config, bundle, proof
