"""Explicit CPU and CUDA installation readers; never seal, publish, launch or own a GPU."""

from __future__ import annotations

import grp
import json
import os
import pwd
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    EmbeddingInstalledRuntimeProof,
    EmbeddingRuntimeProfile,
    parse_installed_runtime_proof,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
    MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
    MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES,
    PREFIX_INVENTORY_DRAFT_RAW_SHA256,
    RootLocalNativeConfigurationPin,
    RootLocalPrefixInventoryCandidate,
    parse_rootlocal_evidence_document,
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
    validate_rootlocal_native_installation_metadata_references,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    MAX_NATIVE_RUNTIME_CONFIG_BYTES,
    EmbeddingNativeRuntimeConfigV11,
    InstalledEmbeddingNativeRuntimeConfig,
    parse_installed_embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    parse_embedding_runtime_bundle,
)
from eom_catalog_contracts.models import Sha256
from pydantic import TypeAdapter

from eom_catalog_service.embedding_host_configuration_files import (
    capture_snapshot_embedding_host,
    require_host_configuration_snapshot_mount,
    resolve_host_configuration_snapshot,
)
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    fixed_native_embedding_profile,
    read_live_runtime_os_file,
)
from eom_catalog_service.embedding_runtime_host_closure import (
    ProtectedEmbeddingHostClosure,
    capture_protected_embedding_host,
)
from eom_catalog_service.embedding_runtime_os_identity import require_native_runtime_interpreter
from eom_catalog_service.embedding_runtime_prefix_closure import (
    PrefixRuntimeInventory,
    PrefixRuntimeInventoryEntry,
)

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_cuda_installation_evidence import (
        CudaAdmissionReceiptMetadata,
    )
    from eom_catalog_contracts.embedding_native_installation_evidence import (
        RootLocalNativeAdmissionReceiptMetadata,
    )

    from eom_catalog_service.embedding_cuda_host_closure import ProtectedCudaEmbeddingHostClosure
    from eom_catalog_service.embedding_cuda_probe_resource_files import (
        CapturedCudaInstallationResourceFiles,
    )

_EVIDENCE_ROOT = Path("/opt/eom/embedding-runtime-admission")
_CONFIG_ROOT = Path("/opt/eom/embedding-native-config")
_PROOF_ROOT = Path("/opt/eom/embedding-runtime-proofs")
_BUNDLE_ROOT = Path("/opt/eom/embedding-runtime-bundles")
_UNIT_PATH = Path("/etc/systemd/system/eom-embedding-native-cpu-probe@.service")
_PROBE_MEMBER = "lib/python3.12/site-packages/eom_catalog_service/embedding_native_cpu_probe.py"
_BOOT_PATH = Path("/proc/sys/kernel/random/boot_id")


class NativeInstallationAdmissionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _InstallationMaterials:
    candidate: RootLocalPrefixInventoryCandidate
    inventory_raw: bytes
    config: InstalledEmbeddingNativeRuntimeConfig
    config_raw: bytes
    proof: EmbeddingInstalledRuntimeProof
    proof_raw: bytes
    bundle: EmbeddingRuntimeBundle
    bundle_raw: bytes


def _read_installation_materials(
    files: NumericalRuntimeFileSnapshots,
    configuration: RootLocalNativeConfigurationPin,
    receipt: RootLocalNativeAdmissionReceiptMetadata | CudaAdmissionReceiptMetadata,
) -> _InstallationMaterials:
    """Same bounded protected read boundary for both explicit families; not an admission."""
    base = _EVIDENCE_ROOT / configuration.configuration_id / configuration.configuration_revision_id
    inventory_raw = files.read(
        base / "inventory.json",
        sha256=receipt.inventory.inventory_raw_sha256,
        maximum=MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES,
    )
    candidate = parse_rootlocal_prefix_inventory_candidate(
        inventory_raw,
        schema_raw=files.read(
            _EVIDENCE_ROOT / "schemas/prefix-inventory-v1.schema.json",
            sha256=PREFIX_INVENTORY_DRAFT_RAW_SHA256,
            maximum=32 * 1024,
        ),
    )
    config_raw = files.read(
        _CONFIG_ROOT
        / configuration.configuration_id
        / configuration.configuration_revision_id
        / "config.json",
        sha256=configuration.configuration_raw_sha256,
        maximum=MAX_NATIVE_RUNTIME_CONFIG_BYTES,
    )
    config = parse_installed_embedding_native_runtime_config_bytes(config_raw)
    proof_raw = files.read(
        _PROOF_ROOT
        / receipt.installed_proof.proof_id
        / receipt.installed_proof.proof_revision_id
        / "proof.json",
        sha256=receipt.installed_proof.proof_raw_sha256,
        maximum=MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    )
    proof = parse_installed_runtime_proof(json.loads(proof_raw))
    bundle_raw = files.read(
        _BUNDLE_ROOT / receipt.bundle.bundle_id / receipt.bundle.bundle_revision_id / "bundle.json",
        sha256=receipt.bundle.bundle_raw_sha256,
        maximum=MAX_RUNTIME_BUNDLE_BYTES,
    )
    bundle = parse_embedding_runtime_bundle(json.loads(bundle_raw))
    return _InstallationMaterials(
        candidate, inventory_raw, config, config_raw, proof, proof_raw, bundle, bundle_raw
    )


def _installation_inventory(
    prefix: Path, candidate: RootLocalPrefixInventoryCandidate
) -> PrefixRuntimeInventory:
    return PrefixRuntimeInventory(
        prefix,
        0,
        candidate.prefix_root_epoch,
        tuple(zip(reversed(prefix.parents), candidate.fixed_ancestor_epochs, strict=True)),
        tuple(
            PrefixRuntimeInventoryEntry(e.relative_member, e.epoch, e.sha256, e.symlink_target)
            for e in candidate.entries
        ),
    )


class ProtectedNativeEmbeddingInstallationAdmission:
    """CPU-only protected evidence capture, not self-issued runtime or source authority.

    Composition supplies a separately accepted receipt pin and configuration identity. Those
    ordinary values must never come from model/request input. The root owner must already
    have checked first-instruction safety; reading a receipt cannot establish it retroactively.
    """

    def __init__(
        self,
        configuration: RootLocalNativeConfigurationPin,
        *,
        expected_receipt_raw_sha256: str,
    ) -> None:
        self._closed = True
        self._host: ProtectedEmbeddingHostClosure | None = None
        try:
            self._configuration = RootLocalNativeConfigurationPin.model_validate(configuration)
            receipt_pin = TypeAdapter(Sha256).validate_python(
                expected_receipt_raw_sha256, strict=True
            )
            fixed = fixed_native_embedding_profile("CPU_INDEX_FP32")
            self._prefix, self._worker = fixed.prefix, fixed.worker_user
            require_native_runtime_interpreter(self._prefix)
            self._files = NumericalRuntimeFileSnapshots(0)
            base = (
                _EVIDENCE_ROOT
                / self._configuration.configuration_id
                / self._configuration.configuration_revision_id
            )
            receipt_raw = self._files.read(
                base / "receipt.json",
                sha256=receipt_pin,
                maximum=MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
            )
            receipt = parse_rootlocal_native_admission_receipt_metadata(
                receipt_raw,
                schema_raw=self._files.read(
                    _EVIDENCE_ROOT / "schemas/admission-receipt-v1.schema.json",
                    sha256=ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
                    maximum=32 * 1024,
                ),
            )
            if receipt.configuration != self._configuration:
                raise ValueError(
                    "installation configuration differs from independently accepted pin"
                )
            materials = _read_installation_materials(self._files, self._configuration, receipt)
            candidate, config = materials.candidate, materials.config
            validate_rootlocal_native_installation_metadata_references(
                receipt,
                receipt_raw,
                expected_receipt_raw_sha256=receipt_pin,
                inventory=candidate,
                inventory_raw=materials.inventory_raw,
                config=config,
                config_raw=materials.config_raw,
                proof=materials.proof,
                proof_raw=materials.proof_raw,
                bundle=materials.bundle,
                bundle_raw=materials.bundle_raw,
            )
            self._boot_id = candidate.boot_id
            self._worker_identity = (receipt.unit_probe.worker_uid, receipt.unit_probe.worker_gid)
            self._inventory = _installation_inventory(self._prefix, candidate)
            # The independently observed probe/code remains part of this exact installation.
            self._files.read(
                _UNIT_PATH, sha256=receipt.unit_probe.unit_template_sha256, maximum=64 * 1024
            )
            self._files.read(
                self._prefix / _PROBE_MEMBER,
                sha256=receipt.unit_probe.probe_code_sha256,
                maximum=64 * 1024,
            )
            if isinstance(config, EmbeddingNativeRuntimeConfigV11):
                snapshot = resolve_host_configuration_snapshot(config.host_configuration)
                mount = require_host_configuration_snapshot_mount(snapshot)
                self._host = capture_snapshot_embedding_host(
                    expected_seed_sha256=candidate.host_seed_sha256,
                    files=self._files,
                    snapshot_mount=mount,
                )
            else:
                self._host = capture_protected_embedding_host(
                    expected_seed_sha256=candidate.host_seed_sha256, files=self._files
                )
            self._closed = False
            self._assert_current()
        except Exception:
            self._closed = True
            if self._host is not None:
                try:
                    self._host.close()
                except Exception:
                    raise NativeInstallationAdmissionError(
                        "NATIVE_INSTALLATION_CAPTURE_CLEANUP_UNCERTAIN"
                    ) from None
            raise NativeInstallationAdmissionError("NATIVE_INSTALLATION_CAPTURE_INVALID") from None

    def __enter__(self) -> ProtectedNativeEmbeddingInstallationAdmission:
        try:
            self._assert_current()
        except Exception:
            # Python will not call __exit__ if entry fails after construction.
            self.close()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _assert_current(self) -> None:
        try:
            if self._closed or self._host is None:
                raise ValueError("installation capture is closed")
            require_native_runtime_interpreter(self._prefix)
            worker, group = pwd.getpwnam(self._worker), grp.getgrnam(self._worker)
            if (
                (worker.pw_uid, group.gr_gid) != self._worker_identity
                or worker.pw_gid != group.gr_gid
                or set(os.getgrouplist(self._worker, worker.pw_gid)) != {group.gr_gid}
                or read_live_runtime_os_file(_BOOT_PATH, maximum=64, owner_uid=0)
                .decode("ascii")
                .strip()
                != self._boot_id
            ):
                raise ValueError("installation boot/account changed")
            self._files.assert_unchanged()
            self._inventory.assert_unchanged()
            self._host.assert_current()
        except Exception:
            raise NativeInstallationAdmissionError("NATIVE_INSTALLATION_CHANGED") from None

    def assert_current(
        self,
        *,
        profile: EmbeddingRuntimeProfile,
        configuration_id: str,
        configuration_revision_id: str,
        configuration_raw_sha256: str,
    ) -> None:
        values = (profile, configuration_id, configuration_revision_id, configuration_raw_sha256)
        if any(type(value) is not str for value in values) or values != (
            "CPU_INDEX_FP32",
            self._configuration.configuration_id,
            self._configuration.configuration_revision_id,
            self._configuration.configuration_raw_sha256,
        ):
            raise NativeInstallationAdmissionError("NATIVE_INSTALLATION_CAPTURE_MISMATCH")
        self._assert_current()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._assert_current()
        finally:
            self._closed = True
            if self._host is not None:
                try:
                    self._host.close()
                except Exception:
                    raise NativeInstallationAdmissionError(
                        "NATIVE_INSTALLATION_CAPTURE_CLEANUP_UNCERTAIN"
                    ) from None


class ProtectedNativeCudaEmbeddingInstallationAdmission:
    """Read pinned explicit CUDA2.0/2.1 evidence; current GPU ownership stays separate."""

    def __init__(
        self, configuration: RootLocalNativeConfigurationPin, *, expected_receipt_raw_sha256: str
    ) -> None:
        self._closed = True
        self._stack = ExitStack()
        self._host: ProtectedCudaEmbeddingHostClosure | None = None
        self._resources: CapturedCudaInstallationResourceFiles | None = None
        try:
            from eom_catalog_contracts.embedding_cuda_host_extension import (
                parse_cuda_host_extension_bytes,
            )
            from eom_catalog_contracts.embedding_cuda_installation_evidence import (
                CUDA_ADMISSION_DRAFT_RAW_SHA256,
                CUDA_ADMISSION_V21_DRAFT_RAW_SHA256,
                parse_rootlocal_cuda_admission_receipt_metadata,
                parse_rootlocal_cuda_admission_receipt_metadata_v21,
                validate_rootlocal_cuda_installation_metadata_references,
            )
            from eom_catalog_contracts.embedding_host_configuration import (
                parse_host_configuration_snapshot,
            )
            from eom_catalog_contracts.embedding_native_runtime_config import (
                EmbeddingNativeRuntimeConfigV12,
                EmbeddingNativeRuntimeConfigV13,
            )

            from eom_catalog_service.embedding_cuda_host_capture import (
                parse_cuda_host_extension_pin,
                resolve_cuda_host_extension,
            )
            from eom_catalog_service.embedding_cuda_host_closure import capture_cuda_embedding_host
            from eom_catalog_service.embedding_cuda_probe_resource_files import (
                capture_cuda_installation_resource_files,
            )
            from eom_catalog_service.embedding_host_configuration_capture import (
                require_host_configuration_snapshot_mount as require_cuda_snapshot_mount,
            )
            from eom_catalog_service.embedding_runtime_files import (
                require_cuda_loader_working_directory,
            )

            self._configuration = RootLocalNativeConfigurationPin.model_validate(configuration)
            receipt_pin = TypeAdapter(Sha256).validate_python(
                expected_receipt_raw_sha256, strict=True
            )
            fixed = fixed_native_embedding_profile("CUDA_INDEX_FP32")
            self._prefix, self._worker = fixed.prefix, fixed.worker_user
            require_native_runtime_interpreter(self._prefix)
            self._files = NumericalRuntimeFileSnapshots(0)
            require_cuda_loader_working_directory(self._files)
            base = (
                _EVIDENCE_ROOT
                / self._configuration.configuration_id
                / self._configuration.configuration_revision_id
            )
            receipt_raw = self._files.read(
                base / "receipt.json",
                sha256=receipt_pin,
                maximum=MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
            )
            document = parse_rootlocal_evidence_document(
                receipt_raw, MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES
            )
            receipt: CudaAdmissionReceiptMetadata
            if document.get("schema_version") == "embedding-native-admission-receipt/2.0":
                receipt = parse_rootlocal_cuda_admission_receipt_metadata(
                    receipt_raw,
                    schema_raw=self._files.read(
                        _EVIDENCE_ROOT / "schemas/admission-receipt-v2.schema.json",
                        sha256=CUDA_ADMISSION_DRAFT_RAW_SHA256,
                        maximum=32 * 1024,
                    ),
                )
            elif document.get("schema_version") == "embedding-native-admission-receipt/2.1":
                receipt = parse_rootlocal_cuda_admission_receipt_metadata_v21(
                    receipt_raw,
                    schema_raw=self._files.read(
                        _EVIDENCE_ROOT / "schemas/admission-receipt-v2.1.schema.json",
                        sha256=CUDA_ADMISSION_V21_DRAFT_RAW_SHA256,
                        maximum=32 * 1024,
                    ),
                )
            else:
                raise ValueError("CUDA installation receipt version is unsupported")
            if receipt.configuration != self._configuration:
                raise ValueError(
                    "installation configuration differs from independently accepted pin"
                )
            materials = _read_installation_materials(self._files, self._configuration, receipt)
            config, candidate = materials.config, materials.candidate
            if not isinstance(
                config, EmbeddingNativeRuntimeConfigV12 | EmbeddingNativeRuntimeConfigV13
            ):
                raise ValueError("CUDA installation requires config1.2 or1.3")
            resolved = resolve_cuda_host_extension(
                parse_cuda_host_extension_pin(
                    config.cuda_host_extension.model_dump(mode="json"),
                    expected_schema_ref=config.cuda_host_extension.schema_ref,
                )
            )
            snapshot = parse_cuda_host_extension_bytes(resolved.snapshot_raw)
            base_snapshot = parse_host_configuration_snapshot(
                json.loads(resolved.base_configuration.snapshot_raw)
            )
            validate_rootlocal_cuda_installation_metadata_references(
                receipt,
                receipt_raw,
                expected_receipt_raw_sha256=receipt_pin,
                inventory=candidate,
                inventory_raw=materials.inventory_raw,
                config=config,
                config_raw=materials.config_raw,
                proof=materials.proof,
                proof_raw=materials.proof_raw,
                bundle=materials.bundle,
                bundle_raw=materials.bundle_raw,
                host_snapshot=snapshot,
                host_snapshot_raw=resolved.snapshot_raw,
                base_snapshot=base_snapshot,
                base_snapshot_raw=resolved.base_configuration.snapshot_raw,
            )
            self._boot_id, self._device = candidate.boot_id, receipt.device_capture
            self._worker_identity = (receipt.unit_probe.worker_uid, receipt.unit_probe.worker_gid)
            self._lease_gid = receipt.shared_gpu_lease.lease_gid
            self._inventory = _installation_inventory(self._prefix, candidate)
            self._files.read(
                Path("/etc/systemd/system/eom-embedding-native-cuda-probe@.service"),
                sha256=receipt.unit_probe.unit_template_sha256,
                maximum=64 * 1024,
            )
            self._files.read(
                self._prefix
                / "lib/python3.12/site-packages/eom_catalog_service/embedding_native_cuda_probe.py",
                sha256=receipt.unit_probe.probe_code_sha256,
                maximum=64 * 1024,
            )
            self._resources = capture_cuda_installation_resource_files(
                receipt.device_nodes, receipt.shared_gpu_lease
            )
            self._stack.callback(self._resources.close)
            self._host = capture_cuda_embedding_host(
                expected_seed_sha256=candidate.host_seed_sha256,
                files=self._files,
                snapshot_mount=require_cuda_snapshot_mount(resolved),
            )
            self._stack.callback(self._host.close)
            self._closed = False
            self._assert_current()
        except Exception:
            self._closed = True
            try:
                self._stack.close()
            except Exception:
                raise NativeInstallationAdmissionError(
                    "NATIVE_INSTALLATION_CAPTURE_CLEANUP_UNCERTAIN"
                ) from None
            raise NativeInstallationAdmissionError("NATIVE_INSTALLATION_CAPTURE_INVALID") from None

    def __enter__(self) -> ProtectedNativeCudaEmbeddingInstallationAdmission:
        try:
            self._assert_current()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _assert_current(self) -> None:
        from eom_catalog_service.embedding_runtime_files import (
            require_cuda_loader_working_directory,
        )
        from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device

        try:
            if self._closed or self._host is None or self._resources is None:
                raise ValueError("installation capture is closed")
            require_native_runtime_interpreter(self._prefix)
            worker, group = pwd.getpwnam(self._worker), grp.getgrnam(self._worker)
            lease_gid = grp.getgrnam("eom-gpu-lease").gr_gid
            if (
                (worker.pw_uid, group.gr_gid) != self._worker_identity
                or worker.pw_gid != group.gr_gid
                or lease_gid != self._lease_gid
                or set(os.getgrouplist(self._worker, worker.pw_gid)) != {group.gr_gid, lease_gid}
                or read_live_runtime_os_file(_BOOT_PATH, maximum=64, owner_uid=0)
                .decode("ascii")
                .strip()
                != self._boot_id
            ):
                raise ValueError("installation boot/account changed")
            require_cuda_loader_working_directory(self._files)
            observe_runtime_device(self._device)
            self._files.assert_unchanged()
            self._inventory.assert_unchanged()
            self._resources.assert_current()
            self._host.assert_current()
        except Exception:
            raise NativeInstallationAdmissionError("NATIVE_INSTALLATION_CHANGED") from None

    def assert_current(
        self,
        *,
        profile: EmbeddingRuntimeProfile,
        configuration_id: str,
        configuration_revision_id: str,
        configuration_raw_sha256: str,
    ) -> None:
        values = (profile, configuration_id, configuration_revision_id, configuration_raw_sha256)
        if any(type(v) is not str for v in values) or values != (
            "CUDA_INDEX_FP32",
            self._configuration.configuration_id,
            self._configuration.configuration_revision_id,
            self._configuration.configuration_raw_sha256,
        ):
            raise NativeInstallationAdmissionError("NATIVE_INSTALLATION_CAPTURE_MISMATCH")
        self._assert_current()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._assert_current()
        finally:
            self._closed = True
            try:
                self._stack.close()
            except Exception:
                raise NativeInstallationAdmissionError(
                    "NATIVE_INSTALLATION_CAPTURE_CLEANUP_UNCERTAIN"
                ) from None
