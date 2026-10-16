"""Source pins and synthetic model values only; no installed/runtime acceptance."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_contracts.embedding_device_benchmark import benchmark_model_family_sha256
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingNumericImplementationPin
from eom_identifiers import sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import benchmark_runtime

ROOT = Path(__file__).resolve().parents[2]
PINNED_CPU_IMPLEMENTATIONS = (
    (
        "FLOAT32_CODEC",
        "unit-f32le/1.0",
        "packages/catalog_contracts/eom_catalog_contracts/embedding_vector_binary.py",
        "sha256:3487cae0e2f21dbe2f95c58a278c083a181bea2255f023e00e53484ee2ebdb79",
    ),
    (
        "HOST_L2",
        "host-l2/1.0",
        "services/catalog_service/eom_catalog_service/inference_transfer_vectors.py",
        "sha256:440d7406db48cc7cf18e423033294b7f8a36b155833eea1eec50b935811490c5",
    ),
    (
        "OFFLINE_ENCODER",
        "native-offline-encoder/1.0",
        "services/catalog_service/eom_catalog_service/embedding_offline_backend.py",
        "sha256:f667e54da9ebf74312ef4d93b6c8f44760c49bb6012dc00b9b47799ff54f500b",
    ),
)


def test_actual_source_preserves_all_three_operating_cpu_implementation_bytes() -> None:
    for _component, _recipe, path, expected in PINNED_CPU_IMPLEMENTATIONS:
        assert sha256_bytes((ROOT / path).read_bytes()) == expected


def test_device_family_matches_without_weakening_the_actual_hash_contract() -> None:
    expected = tuple(
        EmbeddingNumericImplementationPin(component=component, recipe_version=recipe, sha256=digest)
        for component, recipe, _path, digest in PINNED_CPU_IMPLEMENTATIONS
    )
    actual = tuple(
        EmbeddingNumericImplementationPin(
            component=component,
            recipe_version=recipe,
            sha256=sha256_bytes((ROOT / path).read_bytes()),
        )
        for component, recipe, path, _digest in PINNED_CPU_IMPLEMENTATIONS
    )
    cpu, cuda = benchmark_runtime("CPU"), benchmark_runtime("CUDA")
    cpu_family = benchmark_model_family_sha256(
        cpu.spaces.document.model_spec, expected, cpu.numerical_runtime.recipe
    )
    assert cpu_family == benchmark_model_family_sha256(
        cuda.spaces.document.model_spec, actual, cuda.numerical_runtime.recipe
    )
    changed = (
        EmbeddingNumericImplementationPin(
            component="FLOAT32_CODEC",
            recipe_version="unit-f32le/1.0",
            sha256="sha256:73b796b1d83af47827f5df26e6cfd6a2f813e4d958d22c078db3b8a50b062289",
        ),
        *actual[1:],
    )
    assert cpu_family != benchmark_model_family_sha256(
        cuda.spaces.document.model_spec, changed, cuda.numerical_runtime.recipe
    )
