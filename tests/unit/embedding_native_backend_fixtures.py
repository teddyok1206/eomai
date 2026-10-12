"""Synthetic payload and tensor/library fakes; never imports or executes a real ML library."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    embedding_payload_file_set_sha256,
    embedding_runtime_bundle_bytes,
)
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_catalog_service.embedding_bundle_resolver import ConfiguredEmbeddingBundle
from eom_catalog_service.embedding_execution_ports import InstalledEmbeddingRuntimeObservation
from eom_catalog_service.embedding_offline_backend import observed_embedding_implementation_pins
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_runtime_bundle_contracts import _bundle, _pointer
from tests.unit.test_local_embedding_adapter import _model_tree


def stage_protected_numeric_origins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic protected installed-code surrogates; never chmod the writable source tree."""
    root = tmp_path / "synthetic-runtime"
    root.mkdir(mode=0o700)
    for name in (
        "eom_catalog_contracts.embedding_vector_binary",
        "eom_catalog_service.inference_transfer_vectors",
        "eom_catalog_service.embedding_offline_backend",
    ):
        module = importlib.import_module(name)
        module_origin = module.__file__
        assert module_origin is not None
        source = Path(module_origin)
        staged = root / source.name
        staged.write_bytes(source.read_bytes())
        staged.chmod(0o600)
        monkeypatch.setattr(module, "__file__", str(staged))


def configured_bundle(
    tmp_path: Path, device: Literal["CPU", "CUDA"] = "CPU", *, pooling: str = "MEAN"
) -> tuple[ConfiguredEmbeddingBundle, EmbeddingRuntimeBundle, Path, Path]:
    payload_root = tmp_path / "payloads"
    payload_root.mkdir(mode=0o700)
    model_root, model = _model_tree(payload_root)
    bundle_body = _bundle(device).model_dump(mode="json")
    payload = model.model_dump(mode="json")
    payload["pooling"] = pooling
    if pooling == "CLS":
        payload.update(
            upstream_repo="BAAI/bge-m3",
            upstream_revision="9a0624b896d81da7492a910ffa53731274b6cf3d",
            dimension=1024,
            maximum_tokens=2048,
            query_prefix="",
            document_prefix="",
        )
        config = canonical_json_bytes({"hidden_size": 1024, "model_type": "xlm-roberta"})
        (model_root / "config.json").write_bytes(config)
        payload["files"][0].update(size_bytes=len(config), sha256=sha256_bytes(config))
    payload["runtime_versions"] = bundle_body["payload_model_spec"]["runtime_versions"]
    payload = seal(payload, "manifest_sha256")
    model = LocalEmbeddingModelSpec.model_validate(payload)
    raw = canonical_json_bytes(payload)
    (model_root / "manifest.json").write_bytes(raw)
    execution = payload | {
        "model_revision_id": bundle_body["execution_model_spec"]["model_revision_id"],
        "runtime_versions": bundle_body["execution_model_spec"]["runtime_versions"],
    }
    bundle_body["payload_model_spec"] = payload
    bundle_body["execution_model_spec"] = seal(execution, "manifest_sha256")
    bundle_body["payload_pointer"] = {
        "model_id": model.model_id,
        "model_revision_id": model.model_revision_id,
        "schema_ref": bundle_body["payload_pointer"]["schema_ref"],
        "manifest_sha256": model.manifest_sha256,
        "manifest_raw_sha256": sha256_bytes(raw),
        "file_set_sha256": embedding_payload_file_set_sha256(model),
    }
    runtime = bundle_body["numerical_runtime"]
    runtime["python_version"] = platform.python_version()
    runtime["implementations"] = [
        pin.model_dump(mode="json")
        for pin in observed_embedding_implementation_pins(expected_owner_uid=os.geteuid())
    ]
    bundle_body["numerical_runtime"] = seal(runtime, "runtime_sha256")
    bundle = EmbeddingRuntimeBundle.model_validate(seal(bundle_body, "bundle_sha256"))
    store = tmp_path / "bundles"
    manifest = store / bundle.bundle_id / bundle.bundle_revision_id / "bundle.json"
    manifest.parent.mkdir(parents=True, mode=0o700)
    manifest.parent.parent.chmod(0o700)
    store.chmod(0o700)
    manifest.write_bytes(embedding_runtime_bundle_bytes(bundle))
    manifest.chmod(0o600)
    configured = ConfiguredEmbeddingBundle(store, payload_root, _pointer(bundle), os.geteuid())
    return configured, bundle, model_root, manifest


class FakeObserver:
    def __init__(self, bundle: EmbeddingRuntimeBundle) -> None:
        runtime = bundle.numerical_runtime
        self.value = InstalledEmbeddingRuntimeObservation(
            runtime.python_version,
            runtime.libraries,
            runtime.device,
            runtime.torch_build_cuda_version,
        )
        self.calls = 0
        self.failure = False

    def observe(self) -> InstalledEmbeddingRuntimeObservation:
        self.calls += 1
        if self.failure:
            raise RuntimeError("synthetic observer denial")
        return self.value


class FakeOwnership:
    def __init__(self) -> None:
        self.calls = 0
        self.valid = True

    def assert_owned(self) -> None:
        self.calls += 1
        if not self.valid:
            raise RuntimeError("synthetic ownership denial")


def _map(value: Any, function: Any) -> Any:
    return (
        [_map(member, function) for member in value] if isinstance(value, list) else function(value)
    )


class FakeTensor:
    def __init__(self, data: Any, *, dtype: str = "float32", device: str = "cpu") -> None:
        self.data, self.dtype, self.device = data, dtype, device

    @property
    def shape(self) -> tuple[int, ...]:
        dimensions = []
        data = self.data
        while isinstance(data, list):
            dimensions.append(len(data))
            data = data[0] if data else None
        return tuple(dimensions)

    def to(self, *, device: str, dtype: str | None = None) -> FakeTensor:
        return FakeTensor(self.data, device=device, dtype=dtype or self.dtype)

    def detach(self) -> FakeTensor:
        return self

    def is_floating_point(self) -> bool:
        return self.dtype in {"float32", "float16", "bfloat16"}

    def tolist(self) -> Any:
        return self.data

    def unsqueeze(self, dimension: int) -> FakeTensor:
        assert dimension == -1
        if len(self.shape) == 1:
            data = [[value] for value in self.data]
        else:
            data = [[[value] for value in row] for row in self.data]
        return FakeTensor(data, dtype=self.dtype, device=self.device)

    def bool(self) -> FakeTensor:
        return FakeTensor(_map(self.data, bool), dtype="bool", device=self.device)

    def __invert__(self) -> FakeTensor:
        return FakeTensor(
            _map(self.data, lambda value: not value), dtype="bool", device=self.device
        )

    def masked_fill(self, mask: FakeTensor, value: float) -> FakeTensor:
        data = [
            [
                [value] * len(token) if omit[0] else token
                for token, omit in zip(row, masks, strict=True)
            ]
            for row, masks in zip(self.data, mask.data, strict=True)
        ]
        return FakeTensor(data, dtype=self.dtype, device=self.device)

    def sum(self, *, dim: int) -> FakeTensor:
        assert dim == 1
        if len(self.shape) == 3:
            data = [[sum(component) for component in zip(*row, strict=True)] for row in self.data]
        else:
            data = [sum(row) for row in self.data]
        return FakeTensor(data, dtype=self.dtype, device=self.device)

    def __truediv__(self, other: FakeTensor) -> FakeTensor:
        data = [
            [value / divisor[0] for value in row]
            for row, divisor in zip(self.data, other.data, strict=True)
        ]
        return FakeTensor(data, dtype=self.dtype, device=self.device)

    def __getitem__(self, key: tuple[slice, int]) -> FakeTensor:
        assert key == (slice(None), 0)
        return FakeTensor([row[0] for row in self.data], dtype=self.dtype, device=self.device)


def fake_libraries(
    monkeypatch: pytest.MonkeyPatch, bundle: EmbeddingRuntimeBundle
) -> dict[str, Any]:
    versions = {pin.name: pin.version for pin in bundle.numerical_runtime.libraries}
    state: dict[str, Any] = {
        "imports": [],
        "tokenized": [],
        "loads": [],
        "forwards": 0,
        "syncs": 0,
        "inference": False,
        "inference_readback": True,
        "autocast": False,
        "deterministic": False,
        "warn_only": True,
        "threads": 1,
        "interop": 2,
        "matmul_precision": "medium",
        "on_forward": lambda: None,
        "placement": "cpu",
        "output_dtype": "float32",
        "output_device": None,
        "bad_padding": False,
        "token_ids": None,
        "token_vector": lambda _index: [3.0, 4.0],
    }

    class Tokenizer:
        padding_side = "right"
        pad_token_id = 0

        def __call__(self, texts: tuple[str, ...], **kwargs: Any) -> dict[str, Any]:
            assert kwargs == {"truncation": False, "padding": False}
            state["tokenized"].append(texts)
            ids = state["token_ids"] or [list(range(len(text.split()) + 2)) for text in texts]
            return {"input_ids": ids, "attention_mask": [[1] * len(row) for row in ids]}

        def pad(self, tokens: Any, **kwargs: Any) -> dict[str, Any]:
            assert kwargs == {"padding": True, "return_tensors": "pt"}
            ids = tokens["input_ids"]
            maximum = max(len(row) for row in ids)
            padded = [row + [0] * (maximum - len(row)) for row in ids]
            masks = [[1] * len(row) + [0] * (maximum - len(row)) for row in ids]
            if state["bad_padding"]:
                padded[0] = [999] * len(padded[0])
            return {
                "input_ids": FakeTensor(padded, dtype="int64"),
                "attention_mask": FakeTensor(masks, dtype="int64"),
            }

    class Model:
        config = SimpleNamespace(
            hidden_size=bundle.execution_model_spec.dimension, _attn_implementation="eager"
        )
        training = True

        def __init__(self) -> None:
            self.parameter = FakeTensor([1.0])
            self.buffer = FakeTensor([1.0])

        def to(self, *, device: str, dtype: str) -> Model:
            state["placement"] = device
            self.parameter = self.parameter.to(device=device, dtype=dtype)
            self.buffer = self.buffer.to(device=device, dtype=dtype)
            return self

        def eval(self) -> Model:
            self.training = False
            return self

        def parameters(self) -> tuple[FakeTensor, ...]:
            return (self.parameter,)

        def buffers(self) -> tuple[FakeTensor, ...]:
            return (self.buffer,)

        def modules(self) -> tuple[Model, ...]:
            return (self,)

        def __call__(self, **tokens: Any) -> Any:
            assert state["inference"]
            assert all(tensor.device == state["placement"] for tensor in tokens.values())
            state["forwards"] += 1
            state["on_forward"]()
            ids = tokens["input_ids"].data
            hidden = [
                [
                    state["token_vector"](index)
                    + [0.0] * (bundle.execution_model_spec.dimension - 2)
                    for index, _token in enumerate(row)
                ]
                for row in ids
            ]
            return SimpleNamespace(
                last_hidden_state=FakeTensor(
                    hidden,
                    dtype=state["output_dtype"],
                    device=state["output_device"] or state["placement"],
                )
            )

    def load_tokenizer(path: str, **kwargs: Any) -> Tokenizer:
        state["loads"].append(("tokenizer", path, kwargs))
        tokenizer = Tokenizer()
        state["tokenizer"] = tokenizer
        return tokenizer

    def load_model(path: str, **kwargs: Any) -> Model:
        state["loads"].append(("model", path, kwargs))
        model = Model()
        state["model"] = model
        return model

    @contextmanager
    def inference_mode() -> Iterator[None]:
        state["inference"] = True
        try:
            yield
        finally:
            state["inference"] = False

    def deterministic(value: bool, *, warn_only: bool) -> None:
        state["deterministic"], state["warn_only"] = value, warn_only

    torch = SimpleNamespace(
        __version__=versions["torch"],
        float32="float32",
        int64="int64",
        inference_mode=inference_mode,
        version=SimpleNamespace(cuda=bundle.numerical_runtime.torch_build_cuda_version),
        set_num_threads=lambda value: state.update(threads=value),
        get_num_threads=lambda: state["threads"],
        set_num_interop_threads=lambda value: state.update(interop=value),
        get_num_interop_threads=lambda: state["interop"],
        set_float32_matmul_precision=lambda value: state.update(matmul_precision=value),
        get_float32_matmul_precision=lambda: state["matmul_precision"],
        use_deterministic_algorithms=deterministic,
        are_deterministic_algorithms_enabled=lambda: state["deterministic"],
        is_deterministic_algorithms_warn_only_enabled=lambda: state["warn_only"],
        is_autocast_enabled=lambda _device: state["autocast"],
        is_inference_mode_enabled=lambda: state["inference"] and state["inference_readback"],
        is_grad_enabled=lambda: not state["inference"],
        backends=SimpleNamespace(
            cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
            cudnn=SimpleNamespace(allow_tf32=True, benchmark=True),
        ),
        cuda=SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            current_device=lambda: 0,
            get_device_name=lambda _device: bundle.numerical_runtime.device.hardware_model,
            get_device_capability=lambda _device: (
                bundle.numerical_runtime.device.compute_capability
            ),
            synchronize=lambda _device: state.update(syncs=state["syncs"] + 1),
        ),
    )
    transformers = SimpleNamespace(
        __version__=versions["transformers"],
        AutoTokenizer=SimpleNamespace(from_pretrained=load_tokenizer),
        AutoModel=SimpleNamespace(from_pretrained=load_model),
    )
    original_import = importlib.import_module

    def load_module(name: str, package: str | None = None) -> Any:
        state["imports"].append(name)
        return {"torch": torch, "transformers": transformers}.get(name) or original_import(
            name, package
        )

    monkeypatch.setattr(importlib, "import_module", load_module)
    monkeypatch.setattr(importlib.metadata, "version", versions.__getitem__)
    if bundle.numerical_runtime.device.kind == "CUDA":
        monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    state["torch"], state["transformers"] = torch, transformers
    return state
