from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingNumericLibraryPin
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors, read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingSpace,
    IncrementalEmbeddingInput,
)
from eom_catalog_service.embedding_bundle_resolver import (
    ResolvedEmbeddingBundle,
    resolve_configured_embedding_bundle,
)
from eom_catalog_service.embedding_encoder_adapter import (
    IncrementalEmbeddingEncodeError,
    encode_incremental_batch,
)
from eom_catalog_service.embedding_offline_backend import (
    NativeEmbeddingBackendError,
    OfflineNativeEmbeddingBackend,
    observed_embedding_implementation_pins,
)
from eom_identifiers import sha256_bytes

from tests.unit.embedding_native_backend_fixtures import (
    FakeObserver,
    FakeOwnership,
    configured_bundle,
    fake_libraries,
    stage_protected_numeric_origins,
)
from tests.unit.inference_transfer_embedding_fixtures import embedding_input, seal

ROOT = Path(__file__).resolve().parents[2]


def test_pre_resolved_backend_does_not_repeat_payload_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    resolved = resolve_configured_embedding_bundle(configured)
    state = fake_libraries(monkeypatch, bundle)
    monkeypatch.setattr(
        "eom_catalog_service.embedding_offline_backend.resolve_configured_embedding_bundle",
        lambda *_args: pytest.fail("second large payload read"),
    )
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle), resolved_bundle=resolved
    )
    assert state["loads"] and backend.execution_runtime.device == "CPU"
    backend.close()


@pytest.mark.parametrize("fault", ("forged", "payload_copy", "manifest_copy", "root", "changed"))
def test_untrusted_resolved_snapshot_denies_before_observation_or_ml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, root, _ = configured_bundle(tmp_path)
    original = resolve_configured_embedding_bundle(configured)
    resolved = original
    if fault == "forged":
        resolved = ResolvedEmbeddingBundle(original.bundle, original.payload, original.manifest)
    elif fault == "payload_copy":
        resolved = replace(original, payload=replace(original.payload))
    elif fault == "manifest_copy":
        resolved = replace(original, manifest=replace(original.manifest))
    elif fault == "root":
        configured = replace(configured, payload_store_root=tmp_path / "different")
    else:
        (root / "model.safetensors").write_bytes(b"changed")
    observer = FakeObserver(bundle)
    monkeypatch.setattr(
        importlib, "import_module", lambda *_args, **_kwargs: pytest.fail("no ML import")
    )
    with pytest.raises(NativeEmbeddingBackendError):
        OfflineNativeEmbeddingBackend(
            configured, device="CPU", runtime_observer=observer, resolved_bundle=resolved
        )
    assert observer.calls == 0


@pytest.fixture(autouse=True)
def protected_numeric_origins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stage_protected_numeric_origins(tmp_path, monkeypatch)


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_native_recipe_reads_actual_runtime_and_loads_original_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: Literal["CPU", "CUDA"]
) -> None:
    configured, bundle, root, _manifest = configured_bundle(tmp_path, device)
    state = fake_libraries(monkeypatch, bundle)
    observer, ownership = FakeObserver(bundle), FakeOwnership() if device == "CUDA" else None
    backend = OfflineNativeEmbeddingBackend(
        configured, device=device, runtime_observer=observer, cuda_ownership=ownership
    )
    assert backend.model_spec == bundle.execution_model_spec
    assert backend.provenance.model_spec != bundle.payload_model_spec
    assert backend.execution_runtime.device == device
    assert (
        backend.execution_runtime.execution_runtime_sha256
        == bundle.numerical_runtime.runtime_sha256
    )
    assert state["loads"] == [
        (
            "tokenizer",
            str(root),
            {
                "local_files_only": True,
                "trust_remote_code": False,
                "use_fast": True,
            },
        ),
        (
            "model",
            str(root),
            {
                "local_files_only": True,
                "trust_remote_code": False,
                "use_safetensors": True,
                "dtype": "float32",
                "attn_implementation": "eager",
            },
        ),
    ]
    vectors = backend.encode(("마찰이 없다 36 km/h", "전류는 2 A"), purpose="DOCUMENT")
    assert vectors == ((0.6, 0.8) + (0.0,) * 382,) * 2
    payload = pack_unit_vectors(vectors, dimension=384)
    assert len(payload) == 2 * 384 * 4
    decoded = read_unit_vectors(
        payload, row_count=2, dimension=384, expected_sha256=sha256_bytes(payload)
    )
    assert decoded[0][:2] == pytest.approx((0.6, 0.8), abs=1e-7)
    assert state["forwards"] == 1
    assert state["tokenized"] == [("query: 마찰이 없다 36 km/h", "query: 전류는 2 A")]
    assert state["threads"] == 4 and state["interop"] == 1
    assert state["matmul_precision"] == "highest"
    assert state["deterministic"] is True and state["warn_only"] is False
    assert state["torch"].backends.cuda.matmul.allow_tf32 is False
    assert state["torch"].backends.cudnn.allow_tf32 is False
    assert state["torch"].backends.cudnn.benchmark is False
    assert state["placement"] == ("cpu" if device == "CPU" else "cuda:0")
    assert state["syncs"] == (1 if device == "CUDA" else 0)
    backend.close()
    assert state["syncs"] == (2 if device == "CUDA" else 0)
    if ownership is not None:
        assert ownership.calls > 5 and ownership.valid
    with pytest.raises(NativeEmbeddingBackendError, match="CLOSED"):
        backend.encode(("다시 실행",), purpose="DOCUMENT")


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_optional_ml_import_denied_without_trusted_observer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: Literal["CPU", "CUDA"]
) -> None:
    configured, _bundle, _root, _manifest = configured_bundle(tmp_path, device)
    monkeypatch.setattr(importlib, "import_module", lambda *_a, **_k: pytest.fail("no ML import"))
    with pytest.raises(NativeEmbeddingBackendError, match="CONFIGURATION_INVALID"):
        OfflineNativeEmbeddingBackend(configured, device=device, runtime_observer=None)


@pytest.mark.parametrize("missing", [True, False])
def test_cuda_ownership_required_before_any_cuda_or_ml_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path, "CUDA")
    monkeypatch.setattr(importlib, "import_module", lambda *_a, **_k: pytest.fail("no ML import"))
    ownership = FakeOwnership()
    ownership.valid = False
    observer = FakeObserver(bundle)
    with pytest.raises(NativeEmbeddingBackendError, match="CUDA_OWNERSHIP"):
        OfflineNativeEmbeddingBackend(
            configured,
            device="CUDA",
            runtime_observer=observer,
            cuda_ownership=None if missing else ownership,
        )
    assert observer.calls == 0


@pytest.mark.parametrize("device,configured_device", [("CPU", "CUDA"), ("CUDA", "CPU")])
def test_explicit_device_cannot_change_configured_numerical_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    device: Literal["CPU", "CUDA"],
    configured_device: Literal["CPU", "CUDA"],
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path, configured_device)
    monkeypatch.setattr(importlib, "import_module", lambda *_a, **_k: pytest.fail("no ML import"))
    with pytest.raises(NativeEmbeddingBackendError, match="DEVICE_MISMATCH"):
        OfflineNativeEmbeddingBackend(
            configured, device=device, runtime_observer=FakeObserver(bundle)
        )


@pytest.mark.parametrize(
    "fault", ["python", "distribution_sha", "driver", "observer_denial", "version"]
)
def test_installed_observations_are_not_claimed_runtime_hash_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path, "CUDA")
    state = fake_libraries(monkeypatch, bundle)
    observer = FakeObserver(bundle)
    if fault == "python":
        observer.value = replace(observer.value, python_version="3.12.0")
    elif fault == "distribution_sha":
        libraries = list(observer.value.libraries)
        libraries[0] = EmbeddingNumericLibraryPin.model_validate(
            libraries[0].model_dump(mode="json") | {"distribution_sha256": "sha256:" + "f" * 64}
        )
        observer.value = replace(observer.value, libraries=tuple(libraries))
    elif fault == "driver":
        observer.value = replace(
            observer.value,
            device=observer.value.device.model_copy(update={"driver_version": "999.0"}),
        )
    elif fault == "observer_denial":
        observer.failure = True
    else:
        monkeypatch.setattr(importlib.metadata, "version", lambda _name: "999.0")
    with pytest.raises(NativeEmbeddingBackendError, match=r"RUNTIME_MISMATCH|OBSERVATION_FAILED"):
        OfflineNativeEmbeddingBackend(
            configured, device="CUDA", runtime_observer=observer, cuda_ownership=FakeOwnership()
        )
    assert state["imports"] == [] and state["loads"] == []


@pytest.mark.parametrize("fault", ["torch", "transformers", "cuda_build"])
def test_actual_import_versions_must_match_receipt_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    if fault == "cuda_build":
        state["torch"].version.cuda = "12.8"
    else:
        state[fault].__version__ = "999.0"
    with pytest.raises(NativeEmbeddingBackendError, match="RUNTIME_MISMATCH"):
        OfflineNativeEmbeddingBackend(
            configured, device="CPU", runtime_observer=FakeObserver(bundle)
        )
    assert state["loads"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "tf32",
        "cudnn_tf32",
        "benchmark",
        "threads",
        "interop",
        "deterministic",
        "warn_only",
        "autocast",
        "precision",
    ],
)
def test_before_and_after_numeric_readback_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )

    def drift() -> None:
        if fault == "tf32":
            state["torch"].backends.cuda.matmul.allow_tf32 = True
        elif fault == "cudnn_tf32":
            state["torch"].backends.cudnn.allow_tf32 = True
        elif fault == "benchmark":
            state["torch"].backends.cudnn.benchmark = True
        elif fault == "precision":
            state["matmul_precision"] = "high"
        elif fault == "deterministic":
            state["deterministic"] = False
        else:
            state[fault] = {"threads": 3, "interop": 2, "warn_only": True, "autocast": True}[fault]

    state["on_forward"] = drift
    with pytest.raises(NativeEmbeddingBackendError, match="NUMERICS_MISMATCH"):
        backend.encode(("속력은 10 m/s",), purpose="DOCUMENT")


@pytest.mark.parametrize(
    "fault", ["missing", "count", "current", "hardware", "capability", "workspace"]
)
def test_cuda_actual_device_is_not_the_configured_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path, "CUDA")
    state = fake_libraries(monkeypatch, bundle)
    if fault == "workspace":
        monkeypatch.delenv("CUBLAS_WORKSPACE_CONFIG")
    else:
        field, actual = {
            "missing": ("is_available", False),
            "count": ("device_count", 2),
            "current": ("current_device", 1),
            "hardware": ("get_device_name", "wrong-gpu"),
            "capability": ("get_device_capability", (11, 0)),
        }[fault]
        setattr(state["torch"].cuda, field, lambda *_args: actual)
    with pytest.raises(NativeEmbeddingBackendError, match=r"DEVICE_MISMATCH|RUNTIME_MISMATCH"):
        OfflineNativeEmbeddingBackend(
            configured,
            device="CUDA",
            runtime_observer=FakeObserver(bundle),
            cuda_ownership=FakeOwnership(),
        )
    assert state["loads"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "parameter_dtype",
        "buffer_device",
        "eval",
        "attention",
        "compiled",
        "hidden_dtype",
        "hidden_device",
        "padding",
    ],
)
def test_fp32_eager_tensor_closure_and_exact_padding_cannot_be_relaxed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    if fault == "parameter_dtype":
        state["model"].parameter.dtype = "float16"
    elif fault == "buffer_device":
        state["model"].buffer.device = "cuda:0"
    elif fault == "eval":
        state["model"].training = True
    elif fault == "attention":
        state["model"].config = type(state["model"].config)(
            hidden_size=384, _attn_implementation="sdpa"
        )
    elif fault == "compiled":
        state["model"]._orig_mod = state["model"]
    elif fault == "hidden_dtype":
        state["output_dtype"] = "bfloat16"
    elif fault == "hidden_device":
        state["output_device"] = "cuda:0"
    else:
        state["bad_padding"] = True
    with pytest.raises(
        NativeEmbeddingBackendError,
        match=r"PRECISION_MISMATCH|DEVICE_MISMATCH|MODEL_INVALID|TOKENIZER_INVALID",
    ):
        backend.encode(("속력은 10 m/s",), purpose="DOCUMENT")


def test_overflow_token_measurement_does_not_truncate_or_run_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    text = "물체 " * 520 + "마찰이 없다 36 km/h"
    assert (
        backend.token_lengths((text,), purpose="QUERY")[0]
        > bundle.execution_model_spec.maximum_tokens
    )
    with pytest.raises(NativeEmbeddingBackendError, match="INPUT_TOO_LONG"):
        backend.encode((text,), purpose="QUERY")
    assert state["forwards"] == 0
    assert state["tokenized"][-1][0].endswith("마찰이 없다 36 km/h")


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_bge_cls_keeps_official_revision_and_2048_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: Literal["CPU", "CUDA"]
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path, device, pooling="CLS")
    state = fake_libraries(monkeypatch, bundle)
    state["token_vector"] = lambda index: [3.0, 4.0] if index == 0 else [0.0, 5.0]
    backend = OfflineNativeEmbeddingBackend(
        configured,
        device=device,
        runtime_observer=FakeObserver(bundle),
        cuda_ownership=FakeOwnership() if device == "CUDA" else None,
    )
    assert backend.model_spec.upstream_revision == "9a0624b896d81da7492a910ffa53731274b6cf3d"
    assert backend.model_spec.maximum_tokens == 2048
    assert backend.encode(("속력은 10 m/s",), purpose="DOCUMENT") == ((0.6, 0.8) + (0.0,) * 1022,)
    assert state["tokenized"] == [("속력은 10 m/s",)]
    with pytest.raises(NativeEmbeddingBackendError, match="INPUT_TOO_LONG"):
        backend.encode(("물체 " * 2047,), purpose="DOCUMENT")
    assert state["forwards"] == 1


@pytest.mark.parametrize("target", ["payload", "bundle", "ownership", "observer"])
def test_drift_during_forward_returns_no_vectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    configured, bundle, root, manifest = configured_bundle(tmp_path, "CUDA")
    state = fake_libraries(monkeypatch, bundle)
    observer, ownership = FakeObserver(bundle), FakeOwnership()
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CUDA", runtime_observer=observer, cuda_ownership=ownership
    )

    def drift() -> None:
        if target == "ownership":
            ownership.valid = False
        elif target == "observer":
            observer.failure = True
        else:
            path = root / "model.safetensors" if target == "payload" else manifest
            path.write_bytes(path.read_bytes() + b"x")

    state["on_forward"] = drift
    with pytest.raises(NativeEmbeddingBackendError):
        backend.encode(("속력은 10 m/s",), purpose="DOCUMENT")


def test_implementation_pins_hash_actual_modules_and_exclude_git_release() -> None:
    pins = observed_embedding_implementation_pins(expected_owner_uid=os.geteuid())
    assert tuple(pin.component for pin in pins) == ("FLOAT32_CODEC", "HOST_L2", "OFFLINE_ENCODER")
    assert all(pin.sha256.startswith("sha256:") for pin in pins)
    assert "git" not in repr(pins).lower()


@pytest.mark.parametrize("fault", ["missing", "symlink", "oversized", "write_mode"])
def test_untrusted_actual_implementation_origin_fails_before_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    module = sys.modules["eom_catalog_service.embedding_offline_backend"]
    module_origin = module.__file__
    assert module_origin is not None
    origin = tmp_path / "implementation.py"
    if fault == "symlink":
        origin.symlink_to(module_origin)
    elif fault == "oversized":
        origin.write_bytes(b"x" * (128 * 1024 + 1))
        origin.chmod(0o600)
    elif fault == "write_mode":
        origin.write_bytes(Path(module_origin).read_bytes())
        origin.chmod(0o660)
    monkeypatch.setattr(module, "__file__", str(origin))
    with pytest.raises(NativeEmbeddingBackendError, match="IMPLEMENTATION_INVALID"):
        OfflineNativeEmbeddingBackend(
            configured, device="CPU", runtime_observer=FakeObserver(bundle)
        )
    assert state["loads"] == []


def test_actual_implementation_epoch_drift_is_rejected_without_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    fake_libraries(monkeypatch, bundle)
    module = sys.modules["eom_catalog_service.embedding_offline_backend"]
    module_origin = module.__file__
    assert module_origin is not None
    origin = tmp_path / "implementation.py"
    origin.write_bytes(Path(module_origin).read_bytes())
    origin.chmod(0o600)
    monkeypatch.setattr(module, "__file__", str(origin))
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    origin.write_bytes(origin.read_bytes() + b"\n# synthetic drift\n")
    with pytest.raises(NativeEmbeddingBackendError, match="IMPLEMENTATION_CHANGED"):
        backend.encode(("속력은 10 m/s",), purpose="DOCUMENT")


def test_numerical_files_are_bounded_hashed_once_then_only_epoch_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    fake_libraries(monkeypatch, bundle)
    module = sys.modules["eom_catalog_service.embedding_offline_backend"]
    original_read = module.read_protected_embedding_manifest
    reads: list[tuple[Path, int]] = []

    def record_read(path: Path, **kwargs: Any) -> Any:
        reads.append((path, kwargs["maximum_bytes"]))
        return original_read(path, **kwargs)

    monkeypatch.setattr(module, "read_protected_embedding_manifest", record_read)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    assert len(reads) == 3 and all(limit == 128 * 1024 for _path, limit in reads)
    assert backend.provenance.model_spec == bundle.execution_model_spec
    assert backend.execution_runtime.device == "CPU"
    backend.token_lengths(("속력은 10 m/s",), purpose="QUERY")
    backend.encode(("속력은 10 m/s",), purpose="DOCUMENT")
    backend.close()
    assert len(reads) == 3


def test_inference_mode_itself_is_read_back_not_merely_entered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    state["inference_readback"] = False
    with pytest.raises(NativeEmbeddingBackendError, match="NUMERICS_MISMATCH"):
        backend.encode(("속력은 10 m/s",), purpose="DOCUMENT")
    assert state["forwards"] == 0


def test_modules_and_catalog_core_import_without_ml_library() -> None:
    modules = (
        "embedding_bundle_resolver",
        "embedding_offline_backend",
        "embedding_execution_ports",
    )
    for name in modules:
        path = ROOT / "services/catalog_service/eom_catalog_service" / f"{name}.py"
        tree = ast.parse(path.read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not imports & {"torch", "transformers", "safetensors", "tokenizers", "numpy"}
    code = (
        "import sys; import eom_catalog_service; "
        "import eom_catalog_service.embedding_offline_backend; "
        "assert not {'torch','transformers','safetensors','tokenizers'} & set(sys.modules)"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_native_port_denies_cpu_request_against_cuda_backend_before_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path, "CUDA")
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured,
        device="CUDA",
        runtime_observer=FakeObserver(bundle),
        cuda_ownership=FakeOwnership(),
    )
    body = {
        "model_spec": bundle.execution_model_spec.model_dump(mode="json"),
        "purpose": "DOCUMENT",
        "runtime": backend.execution_runtime.model_dump(mode="json") | {"device": "CPU"},
    }
    space = EmbeddingSpace.model_validate(seal(body, "space_sha256"))
    # Even the exact execution model cannot use a CPU query/document claim in CUDA space.
    with pytest.raises(IncrementalEmbeddingEncodeError, match="RUNTIME_MISMATCH"):
        encode_incremental_batch(embedding_input(space=space), backend)
    assert state["forwards"] == 0


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_concrete_native_backend_builds_exact_binary_batch_and_recipe_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: Literal["CPU", "CUDA"]
) -> None:
    configured, bundle, _root, _manifest = configured_bundle(tmp_path, device)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured,
        device=device,
        runtime_observer=FakeObserver(bundle),
        cuda_ownership=FakeOwnership() if device == "CUDA" else None,
    )
    space_body = {
        "model_spec": bundle.execution_model_spec.model_dump(mode="json"),
        "purpose": "DOCUMENT",
        "runtime": backend.execution_runtime.model_dump(mode="json"),
    }
    space = EmbeddingSpace.model_validate(seal(space_body, "space_sha256"))
    request = embedding_input("속력은 10 m/s", "전류는 2 A", space=space)
    with pytest.raises(IncrementalEmbeddingEncodeError, match="RECIPE_MISMATCH"):
        encode_incremental_batch(request, backend)
    assert state["forwards"] == 0
    request_body = request.model_dump(mode="json") | {
        "batch_size": bundle.numerical_runtime.recipe.batch_size,
        "threads": bundle.numerical_runtime.recipe.threads,
    }
    request = IncrementalEmbeddingInput.model_validate(seal(request_body, "request_sha256"))
    encoded = encode_incremental_batch(request, backend)
    assert encoded.result.shard.space == space
    assert encoded.result.shard.rows == tuple(row.encoding for row in request.rows)
    assert len(encoded.vectors) == 2 * 384 * 4
    assert state["forwards"] == 1
