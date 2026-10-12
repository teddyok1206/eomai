"""Fixed-profile source composition; actual owner admission is mandatory, not supplied here."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.embedding_installed_runtime_proof import EmbeddingRuntimeProfile
from eom_catalog_contracts.embedding_native_runtime_config import (
    MAX_NATIVE_RUNTIME_CONFIG_BYTES,
    parse_embedding_native_runtime_config_bytes,
    validate_embedding_native_runtime_config_raw,
    validate_embedding_native_runtime_config_references,
)

from eom_catalog_service.embedding_bundle_resolver import (
    ConfiguredEmbeddingBundle,
    ResolvedEmbeddingBundle,
    resolve_configured_embedding_bundle,
)
from eom_catalog_service.embedding_execution_ports import (
    CudaEmbeddingOwnership,
    InstalledEmbeddingRuntimeObservation,
    InstalledEmbeddingRuntimeObserver,
    NativeEmbeddingBackend,
)
from eom_catalog_service.embedding_installed_runtime_observer import (
    ConfiguredInstalledRuntimeProof,
    ProtectedInstalledEmbeddingRuntimeObserver,
)
from eom_catalog_service.embedding_offline_backend import OfflineNativeEmbeddingBackend
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    fixed_native_embedding_profile,
)

_CONFIG_ROOT = Path("/opt/eom/embedding-native-config")
_BUNDLE_ROOT = Path("/opt/eom/embedding-runtime-bundles")
_PAYLOAD_ROOT = Path("/opt/eom/embedding-models")


class NativeEmbeddingFactoryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class NativeEmbeddingInstallationAdmission(Protocol):
    def assert_current(
        self,
        *,
        profile: EmbeddingRuntimeProfile,
        configuration_id: str,
        configuration_revision_id: str,
        configuration_raw_sha256: str,
    ) -> None:
        """Assert independently accepted current whole installation; no default receipt or grant."""
        ...


@dataclass(frozen=True, slots=True)
class _CapturedInstallation:
    profile: EmbeddingRuntimeProfile
    configuration_id: str
    configuration_revision_id: str
    configuration_raw_sha256: str
    admission: NativeEmbeddingInstallationAdmission
    ownership: CudaEmbeddingOwnership | None

    def assert_current(self) -> None:
        assert_admitted: Callable[..., object] = self.admission.assert_current
        if (
            assert_admitted(
                profile=self.profile,
                configuration_id=self.configuration_id,
                configuration_revision_id=self.configuration_revision_id,
                configuration_raw_sha256=self.configuration_raw_sha256,
            )
            is not None
        ):
            raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_ADMISSION_INVALID")
        if self.ownership is not None:
            assert_owned: Callable[[], object] = self.ownership.assert_owned
            if assert_owned() is not None:
                raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_OWNERSHIP_INVALID")


@dataclass(frozen=True, slots=True)
class _GatedObserver:
    actual: InstalledEmbeddingRuntimeObserver
    check: Callable[[], None]

    def observe(self) -> InstalledEmbeddingRuntimeObservation:
        self.check()
        observation = self.actual.observe()
        self.check()
        return observation


def native_embedding_backend_scope(
    *,
    profile: EmbeddingRuntimeProfile,
    configuration_id: str,
    configuration_revision_id: str,
    configuration_raw_sha256: str,
    admission: NativeEmbeddingInstallationAdmission,
    cuda_ownership: CudaEmbeddingOwnership | None = None,
) -> Callable[[], AbstractContextManager[NativeEmbeddingBackend]]:
    """Bind trusted owner inputs once; returned factory accepts no worker/request arguments.

    No root-installed capture/main or real receipt loader is implemented. Callers own the
    independently accepted admission and CUDA lifetime; neither config parsing nor this binder
    grants source, Job, unit, installed-prefix or physical-device authorization.
    """
    fixed = fixed_native_embedding_profile(profile)
    for value, pattern in (
        (configuration_id, r"embeddingnativeconfig_[0-9a-f]{32}"),
        (configuration_revision_id, r"embeddingnativeconfigrev_[0-9a-f]{32}"),
        (configuration_raw_sha256, r"sha256:[0-9a-f]{64}"),
    ):
        if type(value) is not str or re.fullmatch(pattern, value, re.ASCII) is None:
            raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_CAPTURE_INVALID")
    if admission is None or not callable(getattr(admission, "assert_current", None)):
        raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_ADMISSION_REQUIRED")
    if (fixed.profile == "CPU_INDEX_FP32" and cuda_ownership is not None) or (
        fixed.profile == "CUDA_INDEX_FP32" and cuda_ownership is None
    ):
        raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_OWNERSHIP_REQUIRED")
    captured = _CapturedInstallation(
        profile,
        configuration_id,
        configuration_revision_id,
        configuration_raw_sha256,
        admission,
        cuda_ownership,
    )

    @contextmanager
    def scope() -> Iterator[NativeEmbeddingBackend]:
        files = NumericalRuntimeFileSnapshots(0)
        resolved: ResolvedEmbeddingBundle | None = None
        backend: OfflineNativeEmbeddingBackend | None = None

        def check() -> None:
            captured.assert_current()
            files.assert_unchanged()
            if resolved is not None:
                resolved.assert_unchanged()

        try:
            check()
            path = _CONFIG_ROOT / configuration_id / configuration_revision_id / "config.json"
            raw = files.read(
                path, sha256=configuration_raw_sha256, maximum=MAX_NATIVE_RUNTIME_CONFIG_BYTES
            )
            config = parse_embedding_native_runtime_config_bytes(raw)
            validate_embedding_native_runtime_config_raw(config, raw, configuration_raw_sha256)
            if (
                config.profile != profile
                or config.configuration_id != configuration_id
                or config.configuration_revision_id != configuration_revision_id
            ):
                raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_CAPTURE_MISMATCH")
            check()
            observer = ProtectedInstalledEmbeddingRuntimeObserver(
                ConfiguredInstalledRuntimeProof(config.installed_proof),
                cuda_ownership=cuda_ownership,
            )
            metadata = observer.verified_proof_metadata
            configured = ConfiguredEmbeddingBundle(_BUNDLE_ROOT, _PAYLOAD_ROOT, config.bundle)
            resolved = resolve_configured_embedding_bundle(
                configured, observe_member_identity=files.observe_protected_member_identity
            )
            check()
            validate_embedding_native_runtime_config_references(
                config, resolved.bundle, resolved.manifest.raw, metadata.proof, metadata.raw
            )
            backend = OfflineNativeEmbeddingBackend(
                configured,
                device="CPU" if profile == "CPU_INDEX_FP32" else "CUDA",
                runtime_observer=_GatedObserver(observer, check),
                cuda_ownership=cuda_ownership,
                resolved_bundle=resolved,
            )
            check()
            if (
                backend.execution_runtime.execution_runtime_sha256 != config.runtime_sha256
                or backend.batch_size != config.resources.batch_size
                or backend.threads != config.resources.threads
            ):
                raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_FACTORY_RUNTIME_MISMATCH")
            yield backend
        finally:
            failed = False
            try:
                check()
            except Exception:
                failed = True
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    failed = True
            try:
                check()
            except Exception:
                failed = True
            if failed:
                raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_FACTORY_TEARDOWN_UNCERTAIN")

    return scope
