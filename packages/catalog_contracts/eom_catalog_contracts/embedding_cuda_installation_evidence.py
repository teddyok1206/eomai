"""CUDA-only ROOTLOCAL metadata closure, never an actual seal, observation or compute grant."""

from __future__ import annotations

import stat
from types import MappingProxyType
from typing import Annotated, Final, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import Field, TypeAdapter, field_validator, model_validator
from referencing.exceptions import Unresolvable

from eom_catalog_contracts.embedding_cuda_host_extension import (
    CudaHostExtensionPointer,
    CudaHostExtensionSnapshot,
    validate_cuda_host_extension_pointer,
)
from eom_catalog_contracts.embedding_host_configuration import EmbeddingHostConfigurationSnapshot
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    CudaRuntimeDeviceCapture,
    EmbeddingInstalledRuntimeProof,
    EmbeddingInstalledRuntimeProofPointer,
    parse_installed_runtime_proof,
    validate_installed_runtime_proof_pointer,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
    RootLocalAncestorEpoch,
    RootLocalEvidenceValue,
    RootLocalInstallationEvidenceError,
    RootLocalNativeConfigurationPin,
    RootLocalNativeUnitFacts,
    RootLocalPrefixInventoryCandidate,
    RootLocalPrefixInventoryPin,
    RootLocalStatEpoch,
    parse_rootlocal_evidence_document,
    rootlocal_evidence_values,
    rootlocal_prefix_inventory_candidate_bytes,
    validate_rootlocal_evidence_hash,
    validate_rootlocal_evidence_schema,
    validate_rootlocal_evidence_utc,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EmbeddingNativeRuntimeConfigV12,
    installed_embedding_native_runtime_config_bytes,
    parse_installed_embedding_native_runtime_config_bytes,
    validate_installed_embedding_native_runtime_config_raw,
    validate_installed_embedding_native_runtime_config_references,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    parse_embedding_runtime_bundle,
    validate_embedding_runtime_bundle_pointer,
)
from eom_catalog_contracts.models import Sha256, UtcDatetime

CUDA_ADMISSION_EVIDENCE_REF: Final = "eom://local/embedding-native-admission-receipt/2.0"
CUDA_ADMISSION_DRAFT_RAW_SHA256: Final = (
    "sha256:1850d34ebe477f383f6b0ea0a8c88909aa8e2bb2c21356d110dfd340f27ac5dc"
)
type _Gid = Annotated[int, Field(ge=1, le=4294967294, strict=True)]
type _Pid = Annotated[int, Field(ge=1, le=2147483647, strict=True)]
type _Tick = Annotated[int, Field(ge=1, le=18446744073709551615, strict=True)]
type _Zero = Annotated[int, Field(ge=0, le=0, strict=True)]
type _One = Annotated[int, Field(ge=1, le=1, strict=True)]
type _Utc = Annotated[str, Field(min_length=20, max_length=27, strict=True)]
type CudaDeviceRole = Literal["NVIDIA0", "NVIDIACTL", "NVIDIA_UVM", "NVIDIA_UVM_TOOLS"]
CUDA_DEVICE_NODE_SPECS: Final = MappingProxyType(
    {
        "NVIDIA0": ("/dev/nvidia0", 195, 0),
        "NVIDIACTL": ("/dev/nvidiactl", 195, 255),
        "NVIDIA_UVM": ("/dev/nvidia-uvm", None, 0),
        "NVIDIA_UVM_TOOLS": ("/dev/nvidia-uvm-tools", None, 1),
    }
)


class RootLocalCudaDeviceNode(RootLocalEvidenceValue):
    role: CudaDeviceRole
    path: str = Field(min_length=1, max_length=128, strict=True)
    epoch: RootLocalStatEpoch
    rdev_major: int = Field(ge=1, le=4294967294, strict=True)
    rdev_minor: int = Field(ge=0, le=4294967294, strict=True)

    @model_validator(mode="after")
    def fixed_character_device(self) -> RootLocalCudaDeviceNode:
        path, major, minor = CUDA_DEVICE_NODE_SPECS[self.role]
        if (
            self.path != path
            or (major is not None and self.rdev_major != major)
            or self.rdev_minor != minor
            or not stat.S_ISCHR(self.epoch[4])
            or self.epoch[4] & 0o7000
            or self.epoch[5:7] != (1, 0)
        ):
            raise ValueError("CUDA receipt character node frame differs")
        return self


class RootLocalCudaSharedGpuLease(RootLocalEvidenceValue):
    """Declared same-inode probe facts; not a held lock or other-entrypoint migration proof."""

    source: Literal["ROOT_PROVISIONED_TMPFS_READONLY_EXCLUSIVE_FLOCK/1.0"]
    resource_id: Literal["GPU0"]
    lock_path: Literal["/run/eom-gpu-lease/gpu0.lock"]
    filesystem: Literal["tmpfs"]
    lease_gid: _Gid
    parent_epoch: RootLocalAncestorEpoch
    lock_epoch: RootLocalStatEpoch
    holder_pid: _Pid
    holder_start_time_ticks: _Tick

    @model_validator(mode="after")
    def exact_root_tmpfs_frame(self) -> RootLocalCudaSharedGpuLease:
        parent, lock = self.parent_epoch, self.lock_epoch
        if (
            parent[4] != stat.S_IFDIR | 0o750
            or lock[4] != stat.S_IFREG | 0o640
            or parent[3] != self.lease_gid
            or lock[3] != self.lease_gid
            or parent[0] != lock[0]
            or parent[:2] == lock[:2]
            or lock[5:7] != (1, 0)
        ):
            raise ValueError("CUDA receipt shared lease frame differs")
        return self


class RootLocalCudaUnitProbeMetadata(RootLocalNativeUnitFacts):
    recipe: Literal["NATIVE_CUDA_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0"]
    supplementary_gids: tuple[_Gid, ...] = Field(min_length=1, max_length=1)
    cuda_initialization_calls: _One
    cuda_synchronize_calls: _One
    terminal_probe_gpu_client_count: _Zero


def validate_rootlocal_cuda_resource_file_metadata(
    nodes: tuple[RootLocalCudaDeviceNode, ...], lease: RootLocalCudaSharedGpuLease
) -> None:
    """One ordered-node/lease identity rule shared by metadata and actual FD capture."""
    if type(nodes) is not tuple or len(nodes) != 4:
        raise ValueError("CUDA resource file metadata frame differs")
    nodes = tuple(RootLocalCudaDeviceNode.model_validate(node) for node in nodes)
    lease = RootLocalCudaSharedGpuLease.model_validate(lease)
    identities = {node.epoch[:2] for node in nodes}
    if (
        tuple(node.role for node in nodes) != tuple(CUDA_DEVICE_NODE_SPECS)
        or len(identities) != 4
        or lease.parent_epoch[:2] in identities
        or lease.lock_epoch[:2] in identities
        or len({(node.rdev_major, node.rdev_minor) for node in nodes}) != 4
        or nodes[2].rdev_major != nodes[3].rdev_major
    ):
        raise ValueError("CUDA resource file metadata identity differs")


class RootLocalCudaAdmissionReceiptMetadata(RootLocalEvidenceValue):
    """A parsed CUDA SEALED claim only; root observations/admission are separate prerequisites."""

    schema_version: Literal["embedding-native-admission-receipt/2.0"]
    evidence_state: Literal["SEALED_INSTALLATION_EVIDENCE"]
    profile: Literal["CUDA_INDEX_FP32"]
    configuration: RootLocalNativeConfigurationPin
    inventory: RootLocalPrefixInventoryPin
    installed_proof: EmbeddingInstalledRuntimeProofPointer
    bundle: EmbeddingRuntimeBundlePointer
    runtime_sha256: Sha256
    cuda_host_extension: CudaHostExtensionPointer
    device_capture: CudaRuntimeDeviceCapture
    device_nodes: tuple[RootLocalCudaDeviceNode, ...] = Field(min_length=4, max_length=4)
    shared_gpu_lease: RootLocalCudaSharedGpuLease
    unit_probe: RootLocalCudaUnitProbeMetadata
    sealed_at_utc: _Utc
    receipt_sha256: Sha256

    @field_validator("sealed_at_utc")
    @classmethod
    def valid_utc(cls, value: str) -> str:
        return validate_rootlocal_evidence_utc(value)

    @model_validator(mode="after")
    def exact_cuda_metadata(self) -> RootLocalCudaAdmissionReceiptMetadata:
        nodes, lease, probe = self.device_nodes, self.shared_gpu_lease, self.unit_probe
        validate_rootlocal_cuda_resource_file_metadata(nodes, lease)
        if (
            self.installed_proof.profile != "CUDA_INDEX_FP32"
            or probe.supplementary_gids != (lease.lease_gid,)
            or probe.worker_gid == lease.lease_gid
            or (probe.pid, probe.start_time_ticks)
            != (lease.holder_pid, lease.holder_start_time_ticks)
            or probe.observed_runtime_sha256 != self.runtime_sha256
            or TypeAdapter(UtcDatetime).validate_python(self.sealed_at_utc)
            < TypeAdapter(UtcDatetime).validate_python(probe.terminated_at_utc)
        ):
            raise ValueError("CUDA receipt profile/device/lease/runtime/time closure differs")
        validate_rootlocal_evidence_hash(
            self, "receipt_sha256", MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES
        )
        return self


def rootlocal_cuda_admission_receipt_metadata_bytes(
    value: RootLocalCudaAdmissionReceiptMetadata,
) -> bytes:
    """Serialize a claim, never seal observations or admit execution."""
    return canonical_json_bytes(
        RootLocalCudaAdmissionReceiptMetadata.model_validate(value).model_dump(mode="json")
    )


def parse_rootlocal_cuda_admission_receipt_metadata(
    raw: bytes, *, schema_raw: bytes
) -> RootLocalCudaAdmissionReceiptMetadata:
    try:
        document = parse_rootlocal_evidence_document(raw, MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES)
        validate_rootlocal_evidence_schema(
            schema_raw, document, CUDA_ADMISSION_DRAFT_RAW_SHA256, CUDA_ADMISSION_EVIDENCE_REF
        )
        receipt = RootLocalCudaAdmissionReceiptMetadata.model_validate(document)
        if raw != rootlocal_cuda_admission_receipt_metadata_bytes(receipt):
            raise ValueError("CUDA receipt raw bytes are not canonical")
        return receipt
    except (
        ValueError,
        TypeError,
        SchemaError,
        JsonSchemaValidationError,
        RecursionError,
        Unresolvable,
    ):
        raise RootLocalInstallationEvidenceError(
            "ROOTLOCAL_CUDA_ADMISSION_EVIDENCE_INVALID"
        ) from None


def validate_rootlocal_cuda_installation_metadata_references(
    receipt: RootLocalCudaAdmissionReceiptMetadata,
    receipt_raw: bytes,
    *,
    expected_receipt_raw_sha256: str,
    inventory: RootLocalPrefixInventoryCandidate,
    inventory_raw: bytes,
    config: EmbeddingNativeRuntimeConfigV12,
    config_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
    host_snapshot: CudaHostExtensionSnapshot,
    host_snapshot_raw: bytes,
    base_snapshot: EmbeddingHostConfigurationSnapshot,
    base_snapshot_raw: bytes,
) -> None:
    """Pure reference closure; independent root composition must supply the expected raw pin."""
    try:
        receipt = RootLocalCudaAdmissionReceiptMetadata.model_validate(receipt)
        expected = TypeAdapter(Sha256).validate_python(expected_receipt_raw_sha256, strict=True)
        inventory = RootLocalPrefixInventoryCandidate.model_validate(inventory)
        if (
            type(receipt_raw) is not bytes
            or receipt_raw != rootlocal_cuda_admission_receipt_metadata_bytes(receipt)
            or sha256_bytes(receipt_raw) != expected
            or type(inventory_raw) is not bytes
            or inventory_raw != rootlocal_prefix_inventory_candidate_bytes(inventory)
            or sha256_bytes(inventory_raw) != receipt.inventory.inventory_raw_sha256
            or inventory.inventory_sha256 != receipt.inventory.inventory_sha256
            or inventory.profile != "CUDA_INDEX_FP32"
        ):
            raise ValueError("CUDA receipt/inventory raw/profile frame differs")
        config = EmbeddingNativeRuntimeConfigV12.model_validate(rootlocal_evidence_values(config))
        proof = EmbeddingInstalledRuntimeProof.model_validate(rootlocal_evidence_values(proof))
        bundle = EmbeddingRuntimeBundle.model_validate(rootlocal_evidence_values(bundle))
        if (
            config != parse_installed_embedding_native_runtime_config_bytes(config_raw)
            or installed_embedding_native_runtime_config_bytes(config) != config_raw
            or proof
            != parse_installed_runtime_proof(
                parse_rootlocal_evidence_document(proof_raw, MAX_INSTALLED_RUNTIME_PROOF_BYTES)
            )
            or bundle
            != parse_embedding_runtime_bundle(
                parse_rootlocal_evidence_document(bundle_raw, MAX_RUNTIME_BUNDLE_BYTES)
            )
        ):
            raise ValueError("CUDA supplied metadata differs from actual raw pointers")
        validate_installed_embedding_native_runtime_config_raw(
            config, config_raw, receipt.configuration.configuration_raw_sha256
        )
        validate_installed_embedding_native_runtime_config_references(
            config, bundle, bundle_raw, proof, proof_raw
        )
        validate_installed_runtime_proof_pointer(proof, receipt.installed_proof, proof_raw)
        validate_embedding_runtime_bundle_pointer(bundle, receipt.bundle, bundle_raw)
        host_snapshot = validate_cuda_host_extension_pointer(
            receipt.cuda_host_extension,
            host_snapshot,
            host_snapshot_raw,
            base_snapshot,
            base_snapshot_raw,
        )
        if (
            receipt.configuration.configuration_id != config.configuration_id
            or receipt.configuration.configuration_revision_id != config.configuration_revision_id
            or receipt.configuration.configuration_sha256 != config.config_sha256
            or receipt.installed_proof != config.installed_proof
            or receipt.bundle != config.bundle
            or receipt.runtime_sha256 != config.runtime_sha256
            or receipt.cuda_host_extension != config.cuda_host_extension
            or receipt.device_capture != proof.device_capture
            or inventory.boot_id != receipt.device_capture.boot_id
            or inventory.host_seed_sha256 != host_snapshot.host_seed_sha256
            or receipt.device_capture.numeric_device.driver_version != host_snapshot.driver_release
        ):
            raise ValueError("CUDA installation config/host/device/boot reference closure differs")
    except (
        ValueError,
        TypeError,
        SchemaError,
        JsonSchemaValidationError,
        RecursionError,
        Unresolvable,
    ):
        raise RootLocalInstallationEvidenceError(
            "ROOTLOCAL_CUDA_INSTALLATION_REFERENCE_INVALID"
        ) from None
