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
from eom_catalog_service.embedding_execution_ports import (
    NativeAllocatorPeaks,
    NativeObservedEncoding,
    NativeTokenBatchObservation,
    NativeTokenRejection,
    NativeTokenRowObservation,
)
from eom_catalog_service.embedding_offline_backend import (
    NativeEmbeddingBackendError,
    OfflineNativeEmbeddingBackend,
    observed_embedding_implementation_pins,
)
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.embedding_native_backend_fixtures import (
    FakeObserver,
    FakeOwnership,
    configured_bundle,
    fake_libraries,
    stage_protected_numeric_origins,
)
from tests.unit.inference_transfer_embedding_fixtures import embedding_input, seal

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_cumulative_actual_cuda_oom_counter_includes_constructor_without_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: Literal["CPU", "CUDA"]
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path, device)
    state = fake_libraries(monkeypatch, bundle)
    state["cuda_ooms"] = 2
    backend = OfflineNativeEmbeddingBackend(
        configured,
        device=device,
        runtime_observer=FakeObserver(bundle),
        cuda_ownership=FakeOwnership() if device == "CUDA" else None,
    )
    assert backend.cuda_oom_count() == (2 if device == "CUDA" else None)
    state["cuda_ooms"] = 3
    assert backend.cuda_oom_count() == (3 if device == "CUDA" else None)
    assert state["oom_reads"] == ([0, 0] if device == "CUDA" else [])
    backend.close()
    with pytest.raises(NativeEmbeddingBackendError, match="CLOSED"):
        backend.cuda_oom_count()


@pytest.mark.parametrize(
    "fault", ("missing", "bool", "none", "float", "negative", "overflow", "lease", "runtime")
)
def test_actual_cuda_oom_counter_invalid_or_drift_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path, "CUDA")
    state = fake_libraries(monkeypatch, bundle)
    ownership = FakeOwnership()
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CUDA", runtime_observer=FakeObserver(bundle), cuda_ownership=ownership
    )
    if fault == "missing":
        state["torch"].cuda.memory_stats = lambda _device: {}
    elif fault == "lease":
        state["on_oom_read"] = lambda: setattr(ownership, "valid", False)
    elif fault == "runtime":
        state["on_oom_read"] = lambda: state.update(threads=3)
    else:
        state["cuda_ooms"] = {
            "bool": True,
            "none": None,
            "float": 1.0,
            "negative": -1,
            "overflow": 65,
        }[fault]
    with pytest.raises(NativeEmbeddingBackendError):
        backend.cuda_oom_count()


@pytest.mark.parametrize("purpose", ("QUERY", "DOCUMENT"))
@pytest.mark.parametrize("side", ("left", "right"))
def test_observed_encode_reads_actual_ordered_padded_tokens_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    purpose: Literal["QUERY", "DOCUMENT"],
    side: str,
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    state["tokenizer"].padding_side = side
    state["token_ids"] = [[11, 12, 13], [21, 22]]
    state["token_type_ids"] = [[0, 1, 1], [2, 2]]
    observed = backend.encode_observed(("first", "second"), purpose=purpose)
    assert observed.vectors == ((0.6, 0.8) + (0.0,) * 382,) * 2
    batch = observed.batches[0]
    assert batch.purpose == purpose and batch.padding_side == side and batch.pad_token_id == 0
    assert batch.rows[0].input_ids == (11, 12, 13)
    second = batch.rows[1]
    assert second.input_ids == ((0, 21, 22) if side == "left" else (21, 22, 0))
    assert second.attention_mask == ((0, 1, 1) if side == "left" else (1, 1, 0))
    assert second.token_type_ids == ((0, 2, 2) if side == "left" else (2, 2, 0))
    assert second.unpadded_token_count == 2
    assert second.input_text_sha256 == content_sha256("second")
    assert second.token_ids_sha256 == content_sha256(
        {"input_ids": [21, 22], "token_type_ids": [2, 2]}
    )
    assert len(state["padding_reads"]) == 3 and state["forwards"] == 1
    state["token_ids"][1][0] = 999
    assert second.input_ids == ((0, 21, 22) if side == "left" else (21, 22, 0))
    backend.close()


def test_normal_encode_has_no_observation_copies_and_keeps_original_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("normal encode must not construct/hash token observations")

    monkeypatch.setattr(backend, "_token_observation", forbidden)
    texts = tuple(f"row {index}" for index in range(5))
    assert len(backend.encode(texts, purpose="DOCUMENT")) == 5
    assert state["forwards"] == 2 and len(state["padding_reads"]) == 4
    assert backend.encode((), purpose="DOCUMENT") == ()
    backend.close()


def test_observed_encode_fixed_batch4_and_input_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    texts = tuple(f"row {index}" for index in range(18))
    observed = backend.encode_observed(texts, purpose="DOCUMENT")
    assert tuple(len(batch.rows) for batch in observed.batches) == (4, 4, 4, 4, 2)
    assert tuple(
        row.input_text_sha256 for batch in observed.batches for row in batch.rows
    ) == tuple(content_sha256(text) for text in texts)
    assert state["forwards"] == 5 and len(state["padding_reads"]) == 10
    with pytest.raises(NativeEmbeddingBackendError, match="INPUT_INVALID"):
        backend.encode_observed((*texts, "nineteenth"), purpose="DOCUMENT")
    backend.close()


@pytest.mark.parametrize("batch", (1, 4))
def test_empty_rejection_is_before_tokenizer_with_absent_token_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch: int
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    with pytest.raises(NativeEmbeddingBackendError, match="INPUT_INVALID") as caught:
        backend.encode_observed(("",) * batch, purpose="DOCUMENT")
    assert caught.value.token_rejection == NativeTokenRejection(
        "EMPTY", (content_sha256(""),) * batch, None, None
    )
    assert state["tokenized"] == [] and state["forwards"] == 0
    with pytest.raises(NativeEmbeddingBackendError) as mixed:
        backend.encode_observed(("", "valid text"), purpose="DOCUMENT")
    assert mixed.value.token_rejection is None
    backend.close()


@pytest.mark.parametrize("count", (2048, 2049, 4096, 4097))
@pytest.mark.parametrize("batch", (1, 4))
def test_actual_capacity_and_bounded_overflow_summary_never_export_long_arrays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int, batch: int
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path, pooling="CLS")
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    state["token_ids"] = [list(range(count)) for _ in range(batch)]
    if count == 2048:
        observed = backend.encode_observed(("actual capacity",) * batch, purpose="DOCUMENT")
        assert all(len(row.input_ids) == 2048 for row in observed.batches[0].rows)
        assert state["forwards"] == 1
    else:
        with pytest.raises(NativeEmbeddingBackendError, match="TOO_LONG") as caught:
            backend.encode_observed(("actual overflow",) * batch, purpose="DOCUMENT")
        rejection = caught.value.token_rejection
        if count <= 4096:
            assert rejection is not None and rejection.reason == "OVERFLOW"
            assert rejection.token_counts == (count,) * batch
            assert (
                rejection.token_ids_sha256
                == (content_sha256({"input_ids": list(range(count)), "token_type_ids": None}),)
                * batch
            )
        else:
            assert rejection is None
        assert state["forwards"] == 0 and state["padding_reads"] == []
    backend.close()


@pytest.mark.parametrize("fault", ("mask", "types", "runtime"))
def test_observed_method_does_not_turn_invalid_tokens_or_runtime_into_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    state["token_ids"] = [[1, 2, 3]]
    state["token_type_ids"] = [[0, 1, 1]]
    if fault == "runtime":
        state["on_forward"] = lambda: state.update(threads=3)
    else:
        state[f"bad_{fault}"] = True
    with pytest.raises(NativeEmbeddingBackendError) as caught:
        backend.encode_observed(("a row",), purpose="QUERY")
    assert caught.value.token_rejection is None


def test_observed_inference_failure_is_not_claimed_empty_overflow_or_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )

    def failed() -> None:
        raise RuntimeError("synthetic allocator/kernel failure")

    state["on_forward"] = failed
    with pytest.raises(NativeEmbeddingBackendError, match="INFERENCE_FAILED") as caught:
        backend.encode_observed(("actual nonempty row",), purpose="DOCUMENT")
    assert caught.value.token_rejection is None and state["forwards"] == 1
    backend.close()


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_public_device_fence_and_cumulative_allocator_peaks_never_reset_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: Literal["CPU", "CUDA"]
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path, device)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured,
        device=device,
        runtime_observer=FakeObserver(bundle),
        cuda_ownership=FakeOwnership() if device == "CUDA" else None,
    )
    backend.synchronize()
    assert state["syncs"] == (1 if device == "CUDA" else 0)
    assert backend.allocator_peaks() == (
        NativeAllocatorPeaks(100, 200) if device == "CUDA" else NativeAllocatorPeaks(None, None)
    )
    state.update(allocated_peak=300, reserved_peak=400)
    assert backend.allocator_peaks() == (
        NativeAllocatorPeaks(300, 400) if device == "CUDA" else NativeAllocatorPeaks(None, None)
    )
    assert state["allocator_reads"] == (
        [("allocated", 0), ("reserved", 0)] * 2 if device == "CUDA" else []
    )
    backend.close()
    for method in (backend.synchronize, backend.allocator_peaks):
        with pytest.raises(NativeEmbeddingBackendError, match="CLOSED"):
            method()


@pytest.mark.parametrize(
    "fault", ("bool", "float", "negative", "overflow", "none", "lease", "runtime")
)
def test_allocator_readback_invalid_or_drift_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path, "CUDA")
    state = fake_libraries(monkeypatch, bundle)
    ownership = FakeOwnership()
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CUDA", runtime_observer=FakeObserver(bundle), cuda_ownership=ownership
    )
    if fault == "none":
        state.update(allocated_peak=None, reserved_peak=None)
    elif fault in {"bool", "float", "negative", "overflow"}:
        state["allocated_peak"] = {
            "bool": True,
            "float": 1.0,
            "negative": -1,
            "overflow": 65 * 1024**3,
        }[fault]
    elif fault == "lease":
        state["on_allocator_read"] = lambda: setattr(ownership, "valid", False)
    else:
        state["on_allocator_read"] = lambda: state.update(threads=3)
    with pytest.raises(NativeEmbeddingBackendError):
        backend.allocator_peaks()


@pytest.mark.parametrize(
    "field,value",
    (
        ("input_ids", (True,)),
        ("unpadded_token_count", True),
        ("attention_mask", (True,)),
        ("token_type_ids", (False,)),
    ),
)
def test_native_observation_raw_bool_and_bounds_are_not_integer_values(
    field: str, value: Any
) -> None:
    row = NativeTokenRowObservation(content_sha256("a"), (1,), (1,), None, 1, content_sha256([1]))
    with pytest.raises(ValueError):
        replace(row, **{field: value})
    with pytest.raises(ValueError):
        NativeTokenBatchObservation("DOCUMENT", True, "right", (row,))
    with pytest.raises(ValueError):
        NativeTokenBatchObservation("QUERY", 0, "right", (row,) * 5)
    with pytest.raises(ValueError):
        NativeTokenRejection("EMPTY", (content_sha256(""),), (0,), (content_sha256([]),))


@pytest.mark.parametrize(
    "target,field,value",
    (
        ("row", "unpadded_token_count", True),
        ("row", "attention_mask", (True,)),
        ("batch", "purpose", True),
        ("batch", "rows", (object(),)),
    ),
)
def test_observed_encoding_revalidates_raw_nested_values_before_access(
    target: str, field: str, value: Any
) -> None:
    row = NativeTokenRowObservation(content_sha256("a"), (1,), (1,), None, 1, content_sha256([1]))
    batch = NativeTokenBatchObservation("DOCUMENT", 0, "right", (row,))
    object.__setattr__(row if target == "row" else batch, field, value)
    with pytest.raises(ValueError):
        NativeObservedEncoding(((1.0,),), (batch,))


@pytest.mark.parametrize("count", (1, 2048, True, 4097))
def test_false_or_unbounded_overflow_is_not_a_token_rejection(count: Any) -> None:
    with pytest.raises(ValueError):
        NativeTokenRejection("OVERFLOW", (content_sha256("a"),), (count,), (content_sha256([1]),))


def test_nonbenchmark_model_ceiling_does_not_mint_false_2048_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured, bundle, _, _ = configured_bundle(tmp_path)
    state = fake_libraries(monkeypatch, bundle)
    backend = OfflineNativeEmbeddingBackend(
        configured, device="CPU", runtime_observer=FakeObserver(bundle)
    )
    state["token_ids"] = [list(range(bundle.execution_model_spec.maximum_tokens + 1))]
    with pytest.raises(NativeEmbeddingBackendError, match="TOO_LONG") as caught:
        backend.encode_observed(("generic model overflow",), purpose="DOCUMENT")
    assert caught.value.token_rejection is None and state["forwards"] == 0
    backend.close()


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
