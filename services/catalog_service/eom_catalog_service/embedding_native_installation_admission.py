"""Read independently accepted CPU installation evidence; never seal, publish or launch it."""

from __future__ import annotations

import grp
import json
import os
import pwd
from pathlib import Path

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    EmbeddingRuntimeProfile,
    parse_installed_runtime_proof,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
    MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
    MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES,
    PREFIX_INVENTORY_DRAFT_RAW_SHA256,
    RootLocalNativeConfigurationPin,
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
    validate_rootlocal_native_installation_metadata_references,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    MAX_NATIVE_RUNTIME_CONFIG_BYTES,
    EmbeddingNativeRuntimeConfigV11,
    parse_installed_embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
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


class ProtectedNativeEmbeddingInstallationAdmission:
    """A current protected evidence capture, not self-issued runtime or source authority.

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
            inventory_raw = self._files.read(
                base / "inventory.json",
                sha256=receipt.inventory.inventory_raw_sha256,
                maximum=MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES,
            )
            candidate = parse_rootlocal_prefix_inventory_candidate(
                inventory_raw,
                schema_raw=self._files.read(
                    _EVIDENCE_ROOT / "schemas/prefix-inventory-v1.schema.json",
                    sha256=PREFIX_INVENTORY_DRAFT_RAW_SHA256,
                    maximum=32 * 1024,
                ),
            )
            config_raw = self._files.read(
                _CONFIG_ROOT
                / self._configuration.configuration_id
                / self._configuration.configuration_revision_id
                / "config.json",
                sha256=self._configuration.configuration_raw_sha256,
                maximum=MAX_NATIVE_RUNTIME_CONFIG_BYTES,
            )
            config = parse_installed_embedding_native_runtime_config_bytes(config_raw)
            proof_raw = self._files.read(
                _PROOF_ROOT
                / receipt.installed_proof.proof_id
                / receipt.installed_proof.proof_revision_id
                / "proof.json",
                sha256=receipt.installed_proof.proof_raw_sha256,
                maximum=MAX_INSTALLED_RUNTIME_PROOF_BYTES,
            )
            proof = parse_installed_runtime_proof(json.loads(proof_raw))
            bundle_raw = self._files.read(
                _BUNDLE_ROOT
                / receipt.bundle.bundle_id
                / receipt.bundle.bundle_revision_id
                / "bundle.json",
                sha256=receipt.bundle.bundle_raw_sha256,
                maximum=MAX_RUNTIME_BUNDLE_BYTES,
            )
            bundle = parse_embedding_runtime_bundle(json.loads(bundle_raw))
            validate_rootlocal_native_installation_metadata_references(
                receipt,
                receipt_raw,
                expected_receipt_raw_sha256=receipt_pin,
                inventory=candidate,
                inventory_raw=inventory_raw,
                config=config,
                config_raw=config_raw,
                proof=proof,
                proof_raw=proof_raw,
                bundle=bundle,
                bundle_raw=bundle_raw,
            )
            self._boot_id = candidate.boot_id
            self._worker_identity = (receipt.unit_probe.worker_uid, receipt.unit_probe.worker_gid)
            self._inventory = PrefixRuntimeInventory(
                self._prefix,
                0,
                candidate.prefix_root_epoch,
                tuple(
                    zip(
                        reversed(self._prefix.parents), candidate.fixed_ancestor_epochs, strict=True
                    )
                ),
                tuple(
                    PrefixRuntimeInventoryEntry(
                        e.relative_member, e.epoch, e.sha256, e.symlink_target
                    )
                    for e in candidate.entries
                ),
            )
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
