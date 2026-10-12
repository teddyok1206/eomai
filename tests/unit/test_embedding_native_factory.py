"""Synthetic ordering ports only, never installed admission, actual ML or GPU execution."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingRuntimeProfile,
    installed_runtime_proof_bytes,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EmbeddingNativeRuntimeConfig,
    embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.embedding_runtime_bundle import embedding_runtime_bundle_bytes
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingExecutionRuntime
from eom_catalog_service import embedding_native_factory as factory
from eom_catalog_service.embedding_bundle_resolver import (
    ConfiguredEmbeddingBundle,
    ResolvedEmbeddingBundle,
)
from eom_catalog_service.embedding_execution_ports import (
    InstalledEmbeddingRuntimeObservation,
    InstalledEmbeddingRuntimeObserver,
    NativeEmbeddingBackend,
)
from eom_catalog_service.embedding_installed_runtime_observer import (
    VerifiedInstalledRuntimeProofMetadata,
)
from eom_catalog_service.inference_transfer_ports import EmbeddingRankerProvenance
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_native_backend_fixtures import FakeOwnership
from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal


@dataclass
class Scenario:
    config: EmbeddingNativeRuntimeConfig
    raw: bytes
    events: list[str]
    epoch_valid: bool = True
    admitted: bool = True
    close_failed: bool = False
    observer_failed: bool = False
    backend_failed: bool = False

    def assert_current(
        self,
        *,
        profile: EmbeddingRuntimeProfile,
        configuration_id: str,
        configuration_revision_id: str,
        configuration_raw_sha256: str,
    ) -> None:
        self.events.append("admission")
        assert (profile, configuration_id, configuration_revision_id, configuration_raw_sha256) == (
            self.config.profile,
            self.config.configuration_id,
            self.config.configuration_revision_id,
            sha256_bytes(self.raw),
        )
        if not self.admitted:
            raise ValueError("synthetic admission denied")


def scenario(
    monkeypatch: pytest.MonkeyPatch, profile: EmbeddingRuntimeProfile = "CPU_INDEX_FP32"
) -> tuple[
    Scenario, Callable[[], AbstractContextManager[NativeEmbeddingBackend]], FakeOwnership | None
]:
    config, bundle, proof = native_config_metadata(profile)
    state = Scenario(config, embedding_native_runtime_config_bytes(config), [])
    ownership = FakeOwnership() if profile == "CUDA_INDEX_FP32" else None
    root = (
        Path("/opt/eom/embedding-models")
        / bundle.payload_model_spec.model_id
        / bundle.payload_model_spec.model_revision_id
    )
    resolved = SimpleNamespace(
        bundle=bundle,
        manifest=SimpleNamespace(
            path=Path("/opt/eom/embedding-runtime-bundles")
            / bundle.bundle_id
            / bundle.bundle_revision_id
            / "bundle.json",
            raw=embedding_runtime_bundle_bytes(bundle),
        ),
        payload=SimpleNamespace(root=root, manifest=SimpleNamespace(path=root / "manifest.json")),
        assert_unchanged=lambda: state.events.append("resolved-epoch"),
    )

    class Files:
        def __init__(self, owner_uid: int) -> None:
            assert owner_uid == 0

        def read(self, path: Path, *, sha256: str, maximum: int) -> bytes:
            state.events.append("config-read")
            assert (
                path
                == Path("/opt/eom/embedding-native-config")
                / config.configuration_id
                / config.configuration_revision_id
                / "config.json"
            )
            assert sha256 == sha256_bytes(state.raw) and maximum == 64 * 1024
            return state.raw

        def assert_unchanged(self) -> None:
            state.events.append("file-epoch")
            if not state.epoch_valid:
                raise ValueError("synthetic epoch denied")

        def observe_protected_member_identity(self, path: Path) -> None:
            assert path.is_relative_to(Path("/opt/eom"))
            state.events.append("member-epoch")

    actual = InstalledEmbeddingRuntimeObservation(
        bundle.numerical_runtime.python_version,
        bundle.numerical_runtime.libraries,
        bundle.numerical_runtime.device,
        bundle.numerical_runtime.torch_build_cuda_version,
    )

    class Observer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            state.events.append("observer-create")
            assert state.admitted
            if ownership is not None:
                assert ownership.calls > 0

        @property
        def verified_proof_metadata(self) -> VerifiedInstalledRuntimeProofMetadata:
            state.events.append("proof-readonly")
            return VerifiedInstalledRuntimeProofMetadata(
                proof, installed_runtime_proof_bytes(proof)
            )

        def observe(self) -> InstalledEmbeddingRuntimeObservation:
            state.events.append("observe")
            if state.observer_failed:
                raise ValueError("synthetic observation denied")
            return actual

    class Backend:
        dimension = bundle.execution_model_spec.dimension
        batch_size = config.resources.batch_size
        threads = config.resources.threads
        model_spec = bundle.execution_model_spec
        provenance = EmbeddingRankerProvenance("PINNED_MODEL", model_spec)
        execution_runtime = EmbeddingExecutionRuntime(
            device=bundle.numerical_runtime.device.kind,
            execution_runtime_sha256=config.runtime_sha256,
        )

        def __init__(self, *args: object, **kwargs: object) -> None:
            assert kwargs["resolved_bundle"] is resolved
            self.observer = cast(InstalledEmbeddingRuntimeObserver, kwargs["runtime_observer"])
            self.observer.observe()
            state.events.append("backend-create")
            if state.backend_failed:
                raise ValueError("synthetic backend construction denied")

        def close(self) -> None:
            state.events.append("close-attempt")
            self.observer.observe()
            if state.close_failed:
                raise ValueError("synthetic close denied")

        def encode(self, texts: tuple[str, ...], *, purpose: str) -> tuple[tuple[float, ...], ...]:
            self.observer.observe()
            return ((1.0,) + (0.0,) * (self.dimension - 1),) * len(texts)

        def token_lengths(self, texts: tuple[str, ...], *, purpose: str) -> tuple[int, ...]:
            self.observer.observe()
            return (3,) * len(texts)

    monkeypatch.setattr(factory, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(factory, "ProtectedInstalledEmbeddingRuntimeObserver", Observer)
    monkeypatch.setattr(factory, "OfflineNativeEmbeddingBackend", Backend)

    def resolve(*_args: object, observe_member_identity: Callable[[Path], None]) -> SimpleNamespace:
        for path in (
            resolved.manifest.path,
            resolved.payload.manifest.path,
            *(root / pin.member_path for pin in bundle.payload_model_spec.files),
        ):
            observe_member_identity(path)
        return resolved

    monkeypatch.setattr(factory, "resolve_configured_embedding_bundle", resolve)
    scope = factory.native_embedding_backend_scope(
        profile=profile,
        configuration_id=config.configuration_id,
        configuration_revision_id=config.configuration_revision_id,
        configuration_raw_sha256=sha256_bytes(state.raw),
        admission=state,
        cuda_ownership=ownership,
    )
    return state, scope, ownership


@pytest.mark.parametrize("profile", ("CPU_INDEX_FP32", "CUDA_INDEX_FP32"))
def test_scope_has_no_request_parameters_and_reuses_resolved_metadata(
    monkeypatch: pytest.MonkeyPatch, profile: EmbeddingRuntimeProfile
) -> None:
    state, scope, ownership = scenario(monkeypatch, profile)
    with scope() as backend:
        assert backend.batch_size == 4 and backend.threads == 4
        backend.encode(("synthetic input",), purpose="DOCUMENT")
    assert state.events.index("admission") < state.events.index("config-read")
    assert state.events.index("config-read") < state.events.index("observer-create")
    assert state.events.index("member-epoch") < state.events.index("backend-create")
    assert state.events.count("config-read") == state.events.count("proof-readonly") == 1
    assert state.events.count("close-attempt") == 1
    if ownership is not None:
        assert ownership.valid and ownership.calls > 5
    with pytest.raises(TypeError):
        cast(Callable[..., object], scope)(state.config)


@pytest.mark.parametrize(
    "failure", ("admitted", "epoch_valid", "observer_failed", "backend_failed")
)
def test_preflight_failures_never_yield_an_encoder(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state, scope, _ownership = scenario(monkeypatch)
    setattr(state, failure, failure.endswith("failed"))
    with pytest.raises(ValueError), scope():
        pytest.fail("invalid source context yielded")
    if failure in {"admitted", "epoch_valid"}:
        assert "observer-create" not in state.events and "backend-create" not in state.events


@pytest.mark.parametrize(
    "failure", ("admitted", "epoch_valid", "observer_failed", "close_failed", "body")
)
def test_exceptional_work_still_attempts_close_and_preserves_fencing(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state, scope, _ownership = scenario(monkeypatch)
    with pytest.raises(ValueError), scope():
        if failure == "body":
            raise ValueError("synthetic body denied")
        setattr(state, failure, failure.endswith("failed"))
    assert "close-attempt" in state.events
    assert state.events[-1] in {"admission", "file-epoch", "resolved-epoch"}


@pytest.mark.parametrize(
    "field,bad",
    (
        ("profile", "AUTO"),
        ("configuration_id", True),
        ("configuration_revision_id", "latest"),
        ("configuration_raw_sha256", "version-derived"),
        ("admission", None),
        ("cuda_ownership", FakeOwnership()),
    ),
)
def test_capture_cannot_choose_paths_profiles_knobs_or_optional_admission(
    field: str, bad: object
) -> None:
    config, _, _ = native_config_metadata()
    values: dict[str, Any] = dict(
        profile=config.profile,
        configuration_id=config.configuration_id,
        configuration_revision_id=config.configuration_revision_id,
        configuration_raw_sha256=sha256_bytes(embedding_native_runtime_config_bytes(config)),
        admission=object(),
    )
    values[field] = bad
    with pytest.raises(ValueError):
        factory.native_embedding_backend_scope(**values)


def test_cuda_lost_ownership_denies_before_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    state, scope, ownership = scenario(monkeypatch, "CUDA_INDEX_FP32")
    assert ownership is not None
    ownership.valid = False
    with pytest.raises(ValueError), scope():
        pytest.fail("lost ownership yielded")
    assert "observer-create" not in state.events


def test_admission_boolean_is_not_a_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    state, scope, _ownership = scenario(monkeypatch)
    monkeypatch.setattr(state, "assert_current", lambda **_kwargs: True)
    with pytest.raises(factory.NativeEmbeddingFactoryError), scope():
        pytest.fail("boolean grant cannot yield")
    assert "config-read" not in state.events and "observer-create" not in state.events


def test_cuda_scope_requires_ownership_at_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    state, _scope, _ownership = scenario(monkeypatch, "CUDA_INDEX_FP32")
    with pytest.raises(factory.NativeEmbeddingFactoryError, match="OWNERSHIP_REQUIRED"):
        factory.native_embedding_backend_scope(
            profile=state.config.profile,
            configuration_id=state.config.configuration_id,
            configuration_revision_id=state.config.configuration_revision_id,
            configuration_raw_sha256=sha256_bytes(state.raw),
            admission=state,
        )


def test_gate_loss_during_work_is_checked_by_existing_observer_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, scope, _ownership = scenario(monkeypatch)
    with pytest.raises(ValueError), scope() as backend:
        state.admitted = False
        backend.encode(("no source execution",), purpose="DOCUMENT")
    assert "close-attempt" in state.events


@pytest.mark.parametrize("fault", ("logical", "revision", "profile", "runtime", "newline"))
def test_owner_raw_pin_never_substitutes_config_identity_or_runtime_closure(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    state, _scope, _ownership = scenario(monkeypatch)
    body = state.config.model_dump(mode="json")
    if fault == "logical":
        body["configuration_id"] = "embeddingnativeconfig_" + "9" * 32
    elif fault == "revision":
        body["configuration_revision_id"] = "embeddingnativeconfigrev_" + "9" * 32
    elif fault == "profile":
        body = native_config_metadata("CUDA_INDEX_FP32")[0].model_dump(mode="json")
    elif fault == "runtime":
        body["runtime_sha256"] = "sha256:" + "0" * 64
    state.raw = canonical_json_bytes(seal(body, "config_sha256")) + (
        b"\n" if fault == "newline" else b""
    )
    scope = factory.native_embedding_backend_scope(
        profile=state.config.profile,
        configuration_id=state.config.configuration_id,
        configuration_revision_id=state.config.configuration_revision_id,
        configuration_raw_sha256=sha256_bytes(state.raw),
        admission=state,
    )
    with pytest.raises(ValueError), scope():
        pytest.fail("foreign config yielded")
    assert "backend-create" not in state.events


def test_drift_during_resolver_is_denied_before_backend_or_optional_ml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, scope, _ownership = scenario(monkeypatch)
    actual = cast(
        Callable[..., ResolvedEmbeddingBundle],
        vars(factory)["resolve_configured_embedding_bundle"],
    )

    def changed(
        configured: ConfiguredEmbeddingBundle, *, observe_member_identity: Callable[[Path], None]
    ) -> ResolvedEmbeddingBundle:
        result = actual(configured, observe_member_identity=observe_member_identity)
        state.epoch_valid = False
        return result

    monkeypatch.setattr(factory, "resolve_configured_embedding_bundle", changed)
    with pytest.raises(ValueError), scope():
        pytest.fail("resolution race yielded")
    assert "member-epoch" in state.events and "backend-create" not in state.events
