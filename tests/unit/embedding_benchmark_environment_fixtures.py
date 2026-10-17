"""Synthetic compatible metadata claims only; never a seal, source or model admission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
    rootlocal_native_admission_receipt_metadata_bytes,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    embedding_native_runtime_config_bytes,
)
from eom_catalog_service.embedding_native_cpu_backend import NativeCpuBackendPins
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_native_installation_evidence import (
    INVENTORY_DRAFT,
    RECEIPT_DRAFT,
    inventory_body,
    receipt_body,
)


@dataclass(frozen=True)
class EnvironmentMetadata:
    request: BenchmarkOwnerRequest
    invocation: BenchmarkWorkerInvocation
    inputs: BenchmarkStagedInputs
    backend: NativeCpuBackendPins
    configuration_raw: bytes
    receipt_raw: bytes
    receipt_schema: bytes


def environment_metadata() -> EnvironmentMetadata:
    config, _, _ = native_config_metadata()
    request_body = owner_request().model_dump(mode="json")
    request_body["cpu"]["bundle"] = config.bundle.model_dump(mode="json")
    request_body["cpu"]["installed_proof"] = config.installed_proof.model_dump(mode="json")
    request = BenchmarkOwnerRequest.model_validate(seal(request_body, "request_sha256"))
    invocation_body = worker_invocation().model_dump(mode="json")
    invocation_body["runtime"] = request.cpu.model_dump(mode="json")
    invocation_body["owner_request_sha256"] = request.request_sha256
    invocation = BenchmarkWorkerInvocation.model_validate(
        seal(invocation_body, "invocation_sha256")
    )
    inventory = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(inventory_body()), schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    receipt = parse_rootlocal_native_admission_receipt_metadata(
        canonical_json_bytes(receipt_body(inventory, config)), schema_raw=RECEIPT_DRAFT.read_bytes()
    )
    config_raw = embedding_native_runtime_config_bytes(config)
    receipt_raw = rootlocal_native_admission_receipt_metadata_bytes(receipt)
    backend = NativeCpuBackendPins(
        config.configuration_id,
        config.configuration_revision_id,
        config.config_sha256,
        sha256_bytes(config_raw),
        sha256_bytes(receipt_raw),
    )
    return EnvironmentMetadata(
        request,
        invocation,
        staged_inputs(),
        backend,
        config_raw,
        receipt_raw,
        RECEIPT_DRAFT.read_bytes(),
    )


def stage_installation(root: Path, metadata: EnvironmentMetadata) -> tuple[Path, Path]:
    """Explicit private test materialization, never production evidence publication."""
    config = root / "config"
    evidence = root / "evidence"
    for path in (config, evidence):
        path.mkdir(mode=0o700)
        base = path / metadata.backend.configuration_id
        base.mkdir(mode=0o700)
        revision = base / metadata.backend.configuration_revision_id
        revision.mkdir(mode=0o700)
    (evidence / "schemas").mkdir(mode=0o700)
    for path, raw in (
        (
            config
            / metadata.backend.configuration_id
            / metadata.backend.configuration_revision_id
            / "config.json",
            metadata.configuration_raw,
        ),
        (
            evidence
            / metadata.backend.configuration_id
            / metadata.backend.configuration_revision_id
            / "receipt.json",
            metadata.receipt_raw,
        ),
        (evidence / "schemas/admission-receipt-v1.schema.json", metadata.receipt_schema),
    ):
        path.write_bytes(raw)
        path.chmod(0o600)
    return config, evidence
