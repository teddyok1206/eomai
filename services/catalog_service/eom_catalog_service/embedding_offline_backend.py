"""Optional source-only CPU/CUDA native leaf; no ML imports occur at module import."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingNumericalDevice,
    EmbeddingNumericalRecipe,
    EmbeddingNumericalRuntimeDescriptor,
    EmbeddingNumericImplementationPin,
    EmbeddingNumericLibraryPin,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingExecutionRuntime
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_identifiers import content_sha256

from eom_catalog_service.embedding_bundle_resolver import (
    ConfiguredEmbeddingBundle,
    EmbeddingBundleResolutionError,
    ResolvedEmbeddingBundle,
    resolve_configured_embedding_bundle,
    validate_resolved_embedding_bundle,
)
from eom_catalog_service.embedding_execution_ports import (
    CudaEmbeddingOwnership,
    InstalledEmbeddingRuntimeObservation,
    InstalledEmbeddingRuntimeObserver,
    NativeAllocatorPeaks,
    NativeObservedEncoding,
    NativeTokenBatchObservation,
    NativeTokenRejection,
    NativeTokenRowObservation,
)
from eom_catalog_service.inference_transfer_ports import EmbeddingRankerProvenance
from eom_catalog_service.inference_transfer_vectors import normalized_vector
from eom_catalog_service.local_embedding_adapter import (
    LocalEmbeddingError,
    ProtectedEmbeddingManifest,
    read_protected_embedding_manifest,
)

_IMPLEMENTATIONS = (
    ("FLOAT32_CODEC", "unit-f32le/1.0", "eom_catalog_contracts.embedding_vector_binary"),
    ("HOST_L2", "host-l2/1.0", "eom_catalog_service.inference_transfer_vectors"),
    ("OFFLINE_ENCODER", "native-offline-encoder/1.0", __name__),
)
_MAX_TEXT_BYTES = 256 * 1024
_MAX_TEXTS = 1024


class NativeEmbeddingBackendError(ValueError):
    def __init__(self, code: str, *, token_rejection: NativeTokenRejection | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.token_rejection = token_rejection


@dataclass(frozen=True, slots=True)
class _NumericalImplementationSnapshot:
    pins: tuple[EmbeddingNumericImplementationPin, ...]
    files: tuple[ProtectedEmbeddingManifest, ...]

    def assert_unchanged(self) -> None:
        try:
            for file in self.files:
                file.assert_unchanged()
        except LocalEmbeddingError as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_IMPLEMENTATION_CHANGED") from exc


def _resolve_implementation_snapshot(owner_uid: int) -> _NumericalImplementationSnapshot:
    """Bounded no-follow initial SHA, then immutable epochs rather than repeated hashing.

    Installed protection/RECORD is independently checked by the owner observer. Whole
    relevant module files intentionally define the small implementation release boundary.
    """
    pins: list[EmbeddingNumericImplementationPin] = []
    files: list[ProtectedEmbeddingManifest] = []
    for component, recipe, name in _IMPLEMENTATIONS:
        origin = getattr(importlib.import_module(name), "__file__", None)
        if origin is None:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_IMPLEMENTATION_INVALID")
        try:
            file = read_protected_embedding_manifest(
                Path(origin), expected_owner_uid=owner_uid, maximum_bytes=128 * 1024
            )
        except LocalEmbeddingError as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_IMPLEMENTATION_INVALID") from exc
        files.append(file)
        pins.append(
            EmbeddingNumericImplementationPin.model_validate(
                {
                    "component": component,
                    "recipe_version": recipe,
                    "sha256": file.sha256,
                }
            )
        )
    result = _NumericalImplementationSnapshot(tuple(pins), tuple(files))
    result.assert_unchanged()
    return result


def observed_embedding_implementation_pins(
    *, expected_owner_uid: int = 0
) -> tuple[EmbeddingNumericImplementationPin, ...]:
    """Resolve actual imported implementation SHA once; no Git or asserted fingerprints."""
    return _resolve_implementation_snapshot(expected_owner_uid).pins


class OfflineNativeEmbeddingBackend:
    """Lazy exact FP32/eager backend over one verified legacy payload.

    Configuration/observer/ownership are supplied by the trusted installed owner, not
    the worker request. No default selector, CUDA lease acquisition, fallback or release
    is implemented here. The owner keeps the handle through unit exit/cleanup fencing.
    """

    def __init__(
        self,
        configured: ConfiguredEmbeddingBundle,
        *,
        device: Literal["CPU", "CUDA"],
        runtime_observer: InstalledEmbeddingRuntimeObserver | None,
        cuda_ownership: CudaEmbeddingOwnership | None = None,
        resolved_bundle: ResolvedEmbeddingBundle | None = None,
    ) -> None:
        self._torch: Any = None
        self._model: Any = None
        self._tokenizer: Any = None
        self._closed = False
        self._implementation_pins: tuple[EmbeddingNumericImplementationPin, ...] = ()
        self._implementation_snapshot: _NumericalImplementationSnapshot | None = None
        self._implementation_owner_uid = configured.expected_owner_uid
        self._observer = runtime_observer
        self._ownership = cuda_ownership
        self._device = device
        if device not in {"CPU", "CUDA"} or runtime_observer is None:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_CONFIGURATION_INVALID")
        if device == "CPU" and cuda_ownership is not None:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_DEVICE_MISMATCH")
        try:
            if resolved_bundle is None:
                self._resolved = resolve_configured_embedding_bundle(configured)
            else:
                validate_resolved_embedding_bundle(configured, resolved_bundle)
                self._resolved = resolved_bundle
            self._spec = self._resolved.bundle.execution_model_spec
            self._expected = self._resolved.bundle.numerical_runtime
            if self._expected.device.kind != device:
                raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_DEVICE_MISMATCH")
            self._placement = "cpu" if device == "CPU" else "cuda:0"
            self._require_owned()
            if device == "CUDA" and os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
                raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_RUNTIME_MISMATCH")
            self._require_installation()
            self._torch = importlib.import_module("torch")
            self._transformers = importlib.import_module("transformers")
            self._require_import_versions()
            self._configure_numerics()
            self._assert_runtime()
            self._tokenizer = self._transformers.AutoTokenizer.from_pretrained(
                str(self._resolved.payload.root),
                local_files_only=True,
                trust_remote_code=False,
                use_fast=True,
            )
            self._model = (
                self._transformers.AutoModel.from_pretrained(
                    str(self._resolved.payload.root),
                    local_files_only=True,
                    trust_remote_code=False,
                    use_safetensors=True,
                    dtype=self._torch.float32,
                    attn_implementation="eager",
                )
                .to(device=self._placement, dtype=self._torch.float32)
                .eval()
            )
            self._assert_model()
            self._assert_runtime()
        except NativeEmbeddingBackendError:
            self._discard_failed_model()
            raise
        except EmbeddingBundleResolutionError as exc:
            raise NativeEmbeddingBackendError(exc.code) from exc
        except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
            self._discard_failed_model()
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_RUNTIME_UNAVAILABLE") from exc
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            self._discard_failed_model()
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_RUNTIME_INVALID") from exc

    def _require_owned(self) -> None:
        if self._device == "CUDA":
            if self._ownership is None:
                raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_CUDA_OWNERSHIP_REQUIRED")
            try:
                self._ownership.assert_owned()
            except Exception as exc:
                raise NativeEmbeddingBackendError(
                    "NATIVE_EMBEDDING_CUDA_OWNERSHIP_INVALID"
                ) from exc

    def _require_installation(self) -> InstalledEmbeddingRuntimeObservation:
        if self._observer is None:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_CONFIGURATION_INVALID")
        try:
            observation = self._observer.observe()
        except Exception as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_OBSERVATION_FAILED") from exc
        libraries = tuple(
            EmbeddingNumericLibraryPin.model_validate(pin.model_dump(mode="json"))
            for pin in observation.libraries
        )
        device = EmbeddingNumericalDevice.model_validate(observation.device.model_dump(mode="json"))
        if (
            observation.python_version != platform.python_version()
            or observation.python_version != self._expected.python_version
            or libraries != self._expected.libraries
            or device != self._expected.device
            or observation.torch_build_cuda_version != self._expected.torch_build_cuda_version
            or sys.platform != "linux"
            or platform.machine() != "x86_64"
            or any(importlib.metadata.version(pin.name) != pin.version for pin in libraries)
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_RUNTIME_MISMATCH")
        self._installation = InstalledEmbeddingRuntimeObservation(
            observation.python_version, libraries, device, observation.torch_build_cuda_version
        )
        return self._installation

    def _require_import_versions(self) -> None:
        libraries = {pin.name: pin.version for pin in self._expected.libraries}
        if (
            str(self._torch.__version__) != libraries["torch"]
            or str(self._transformers.__version__) != libraries["transformers"]
            or self._torch.version.cuda != self._expected.torch_build_cuda_version
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_RUNTIME_MISMATCH")

    def _configure_numerics(self) -> None:
        torch = self._torch
        torch.set_num_threads(self._expected.recipe.threads)
        # Fixed interop=1 is part of this installed encoder implementation recipe.
        torch.set_num_interop_threads(1)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.use_deterministic_algorithms(True, warn_only=False)

    def _observed_descriptor(self) -> EmbeddingNumericalRuntimeDescriptor:
        torch = self._torch
        recipe = self._expected.recipe
        if (
            torch.get_float32_matmul_precision() != "highest"
            or torch.backends.cuda.matmul.allow_tf32 is not False
            or torch.backends.cudnn.allow_tf32 is not False
            or torch.backends.cudnn.benchmark is not False
            or torch.are_deterministic_algorithms_enabled() is not True
            or torch.is_deterministic_algorithms_warn_only_enabled() is not False
            or torch.is_autocast_enabled("cpu") is not False
            or torch.is_autocast_enabled("cuda") is not False
            or type(torch.get_num_threads()) is not int
            or torch.get_num_threads() != recipe.threads
            or torch.get_num_interop_threads() != 1
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_NUMERICS_MISMATCH")
        if self._device == "CUDA":
            self._require_owned()
            if (
                os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8"
                or torch.cuda.is_available() is not True
                or torch.cuda.device_count() != 1
                or torch.cuda.current_device() != 0
                or torch.cuda.get_device_name(0) != self._expected.device.hardware_model
                or tuple(torch.cuda.get_device_capability(0))
                != self._expected.device.compute_capability
            ):
                raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_DEVICE_MISMATCH")
            actual_device = EmbeddingNumericalDevice(
                kind="CUDA",
                hardware_model=torch.cuda.get_device_name(0),
                compute_capability=tuple(torch.cuda.get_device_capability(0)),
                driver_version=self._installation.device.driver_version,
            )
        else:
            actual_device = self._installation.device
        observed_recipe = EmbeddingNumericalRecipe.model_validate(
            {
                "cublas_workspace": (
                    os.environ["CUBLAS_WORKSPACE_CONFIG"] if self._device == "CUDA" else None
                ),
                "batch_size": recipe.batch_size,
                "threads": torch.get_num_threads(),
            }
        )
        body = {
            "schema_version": "embedding-numerical-runtime/1.0",
            "python_version": platform.python_version(),
            "implementations": [pin.model_dump(mode="json") for pin in self._implementation_pins],
            "libraries": [pin.model_dump(mode="json") for pin in self._installation.libraries],
            "device": actual_device.model_dump(mode="json"),
            "recipe": observed_recipe.model_dump(mode="json"),
            "torch_build_cuda_version": torch.version.cuda,
        }
        return EmbeddingNumericalRuntimeDescriptor.model_validate(
            body | {"runtime_sha256": content_sha256(body)}
        )

    def _assert_runtime(self) -> None:
        try:
            self._read_runtime()
        except NativeEmbeddingBackendError:
            raise
        except EmbeddingBundleResolutionError as exc:
            raise NativeEmbeddingBackendError(exc.code) from exc
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_RUNTIME_INVALID") from exc

    def _read_runtime(self) -> None:
        if self._closed:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_CLOSED")
        self._require_owned()
        self._resolved.assert_unchanged()
        self._require_installation()
        self._require_import_versions()
        if self._implementation_snapshot is None:
            self._implementation_snapshot = _resolve_implementation_snapshot(
                self._implementation_owner_uid
            )
            self._implementation_pins = self._implementation_snapshot.pins
        self._implementation_snapshot.assert_unchanged()
        if self._observed_descriptor() != self._expected:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_RUNTIME_MISMATCH")
        if self._model is not None:
            self._assert_model()

    def _assert_model(self) -> None:
        torch, model = self._torch, self._model
        if (
            model.training is not False
            or model.config.hidden_size != self._spec.dimension
            or model.config._attn_implementation != "eager"
            or hasattr(model, "_orig_mod")
            or getattr(model, "is_quantized", False) is not False
            or any(module.training is not False for module in model.modules())
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_MODEL_INVALID")
        parameters = tuple(model.parameters())
        if not parameters:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_MODEL_INVALID")
        if any(not tensor.is_floating_point() for tensor in parameters):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_PRECISION_MISMATCH")
        for tensor in (*parameters, *model.buffers()):
            self._assert_tensor_device(tensor)
            if tensor.is_floating_point() and tensor.dtype != torch.float32:
                raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_PRECISION_MISMATCH")

    def _assert_tensor_device(self, tensor: Any) -> None:
        if str(tensor.device) != self._placement:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_DEVICE_MISMATCH")

    @property
    def dimension(self) -> int:
        return self._spec.dimension

    @property
    def batch_size(self) -> int:
        self._assert_runtime()
        return self._expected.recipe.batch_size

    @property
    def threads(self) -> int:
        self._assert_runtime()
        return self._observed_descriptor().recipe.threads

    @property
    def model_spec(self) -> LocalEmbeddingModelSpec:
        self._assert_runtime()
        return self._spec

    @property
    def provenance(self) -> EmbeddingRankerProvenance:
        self._assert_runtime()
        return EmbeddingRankerProvenance("PINNED_MODEL", self._spec)

    @property
    def execution_runtime(self) -> EmbeddingExecutionRuntime:
        self._assert_runtime()
        actual = self._observed_descriptor()
        return EmbeddingExecutionRuntime(
            device=actual.device.kind,
            execution_runtime_sha256=actual.runtime_sha256,
        )

    def _validate_texts(
        self, texts: tuple[str, ...], purpose: Literal["QUERY", "DOCUMENT"]
    ) -> None:
        if (
            not isinstance(texts, tuple)
            or purpose not in {"QUERY", "DOCUMENT"}
            or len(texts) > _MAX_TEXTS
            or any(
                not isinstance(text, str)
                or not text.strip()
                or len(text.encode("utf-8")) > _MAX_TEXT_BYTES
                for text in texts
            )
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_INPUT_INVALID")
        self._assert_runtime()

    def _tokens(self, texts: tuple[str, ...], purpose: Literal["QUERY", "DOCUMENT"]) -> Any:
        prefix = self._spec.query_prefix if purpose == "QUERY" else self._spec.document_prefix
        tokens = self._tokenizer(
            tuple(prefix + text for text in texts), truncation=False, padding=False
        )
        ids, masks = tokens["input_ids"], tokens["attention_mask"]
        if (
            set(tokens) - {"input_ids", "attention_mask", "token_type_ids"}
            or len(ids) != len(texts)
            or len(masks) != len(texts)
            or any(
                not row
                or len(row) != len(mask)
                or any(type(value) is not int or value < 0 for value in row)
                or any(type(value) is not int or value != 1 for value in mask)
                for row, mask in zip(ids, masks, strict=True)
            )
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
        token_types = tokens.get("token_type_ids")
        if token_types is not None and (
            len(token_types) != len(ids)
            or any(
                len(types) != len(row)
                or any(type(value) is not int or value < 0 for value in types)
                for types, row in zip(token_types, ids, strict=True)
            )
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
        return tokens

    def _require_exact_padding(self, tokens: Any, padded: Any) -> tuple[Any, Any, Any]:
        """Read actual padded IDs/masks back before device transfer; never truncate silently."""
        ids = tokens["input_ids"]
        maximum = max(len(row) for row in ids)
        side, pad_id = self._tokenizer.padding_side, self._tokenizer.pad_token_id
        if side not in {"left", "right"} or type(pad_id) is not int or pad_id < 0:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
        expected_ids, expected_masks, expected_types = [], [], []
        token_types = tokens.get("token_type_ids")
        for index, row in enumerate(ids):
            padding = [pad_id] * (maximum - len(row))
            mask_padding = [0] * len(padding)
            expected_ids.append(padding + row if side == "left" else row + padding)
            expected_masks.append(
                mask_padding + [1] * len(row) if side == "left" else [1] * len(row) + mask_padding
            )
            if token_types is not None:
                types = token_types[index]
                expected_types.append(
                    mask_padding + types if side == "left" else types + mask_padding
                )
        actual_ids = padded["input_ids"].tolist()
        actual_masks = padded["attention_mask"].tolist()
        actual_types = (
            padded["token_type_ids"].tolist()
            if token_types is not None and "token_type_ids" in padded
            else None
        )
        if (
            actual_ids != expected_ids
            or actual_masks != expected_masks
            or ("token_type_ids" in padded) != (token_types is not None)
            or (token_types is not None and actual_types != expected_types)
        ):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
        return actual_ids, actual_masks, actual_types

    def _token_observation(
        self,
        texts: tuple[str, ...],
        purpose: Literal["QUERY", "DOCUMENT"],
        tokens: Any,
        actual: tuple[Any, Any, Any],
    ) -> NativeTokenBatchObservation:
        ids, masks, types = actual
        unpadded_types = tokens.get("token_type_ids")
        return NativeTokenBatchObservation(
            purpose=purpose,
            pad_token_id=self._tokenizer.pad_token_id,
            padding_side=self._tokenizer.padding_side,
            rows=tuple(
                NativeTokenRowObservation(
                    input_text_sha256=content_sha256(text),
                    input_ids=tuple(ids[index]),
                    attention_mask=tuple(masks[index]),
                    token_type_ids=tuple(types[index]) if types is not None else None,
                    unpadded_token_count=len(tokens["input_ids"][index]),
                    token_ids_sha256=content_sha256(
                        {
                            "input_ids": tokens["input_ids"][index],
                            "token_type_ids": (
                                unpadded_types[index] if unpadded_types is not None else None
                            ),
                        }
                    ),
                )
                for index, text in enumerate(texts)
            ),
        )

    def token_lengths(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[int, ...]:
        self._validate_texts(texts, purpose)
        try:
            lengths: list[int] = []
            for offset in range(0, len(texts), self._expected.recipe.batch_size):
                tokens = self._tokens(
                    texts[offset : offset + self._expected.recipe.batch_size], purpose
                )
                lengths.extend(len(row) for row in tokens["input_ids"])
            self._assert_runtime()
            return tuple(lengths)
        except NativeEmbeddingBackendError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_INFERENCE_FAILED") from exc

    def encode(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[tuple[float, ...], ...]:
        return self._encode(texts, purpose=purpose, observations=None)

    def encode_observed(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> NativeObservedEncoding:
        """Same encoder, bounded token read-back only for an explicit observed call."""
        if type(texts) is not tuple or not 1 <= len(texts) <= 18:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_INPUT_INVALID")
        # Empty rejection precedes tokenizer; never fabricate count0/empty-ID evidence.
        if (
            purpose in ("QUERY", "DOCUMENT")
            and len(texts) <= 4
            and all(type(text) is str and not text.strip() for text in texts)
            and all(len(text.encode("utf-8")) <= _MAX_TEXT_BYTES for text in texts)
        ):
            self._assert_runtime()
            raise NativeEmbeddingBackendError(
                "NATIVE_EMBEDDING_INPUT_INVALID",
                token_rejection=NativeTokenRejection(
                    "EMPTY", tuple(content_sha256(text) for text in texts), None, None
                ),
            )
        observations: list[NativeTokenBatchObservation] = []
        vectors = self._encode(texts, purpose=purpose, observations=observations)
        return NativeObservedEncoding(vectors, tuple(observations))

    def _encode(
        self,
        texts: tuple[str, ...],
        *,
        purpose: Literal["QUERY", "DOCUMENT"],
        observations: list[NativeTokenBatchObservation] | None,
    ) -> tuple[tuple[float, ...], ...]:
        self._validate_texts(texts, purpose)
        output: list[tuple[float, ...]] = []
        try:
            for offset in range(0, len(texts), self._expected.recipe.batch_size):
                self._assert_runtime()
                batch = texts[offset : offset + self._expected.recipe.batch_size]
                tokens = self._tokens(batch, purpose)
                if any(len(row) > self._spec.maximum_tokens for row in tokens["input_ids"]):
                    if observations is not None and any(
                        value >= 2**31
                        for rows in (tokens["input_ids"], tokens.get("token_type_ids") or ())
                        for row in rows
                        for value in row
                    ):
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
                    rejection = None
                    if (
                        observations is not None
                        and self._spec.maximum_tokens == 2048
                        and all(len(row) <= 4096 for row in tokens["input_ids"])
                    ):
                        types = tokens.get("token_type_ids")
                        rejection = NativeTokenRejection(
                            "OVERFLOW",
                            tuple(content_sha256(text) for text in batch),
                            tuple(len(row) for row in tokens["input_ids"]),
                            tuple(
                                content_sha256(
                                    {
                                        "input_ids": row,
                                        "token_type_ids": types[index]
                                        if types is not None
                                        else None,
                                    }
                                )
                                for index, row in enumerate(tokens["input_ids"])
                            ),
                        )
                    self._assert_runtime()
                    raise NativeEmbeddingBackendError(
                        "NATIVE_EMBEDDING_INPUT_TOO_LONG", token_rejection=rejection
                    )
                padded = self._tokenizer.pad(tokens, padding=True, return_tensors="pt")
                if set(padded) - {"input_ids", "attention_mask", "token_type_ids"}:
                    raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
                if any(
                    str(tensor.device) != "cpu" or tensor.dtype != self._torch.int64
                    for tensor in padded.values()
                ):
                    raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
                actual = self._require_exact_padding(tokens, padded)
                observation = (
                    self._token_observation(batch, purpose, tokens, actual)
                    if observations is not None
                    else None
                )
                tensors = {key: tensor.to(device=self._placement) for key, tensor in padded.items()}
                for tensor in tensors.values():
                    self._assert_tensor_device(tensor)
                    if tensor.dtype != self._torch.int64:
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_TOKENIZER_INVALID")
                with self._torch.inference_mode():
                    if (
                        self._torch.is_inference_mode_enabled() is not True
                        or self._torch.is_grad_enabled() is not False
                        or self._torch.is_autocast_enabled("cpu") is not False
                        or self._torch.is_autocast_enabled("cuda") is not False
                    ):
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_NUMERICS_MISMATCH")
                    hidden = self._model(**tensors).last_hidden_state
                    self._assert_tensor_device(hidden)
                    if hidden.dtype != self._torch.float32:
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_PRECISION_MISMATCH")
                    if tuple(hidden.shape) != (
                        len(batch),
                        max(len(row) for row in tokens["input_ids"]),
                        self.dimension,
                    ):
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_SHAPE_MISMATCH")
                    if self._spec.pooling == "CLS":
                        pooled = hidden[:, 0]
                    else:
                        mask = tensors["attention_mask"].unsqueeze(-1).bool()
                        pooled = hidden.masked_fill(~mask, 0.0).sum(dim=1)
                        pooled = pooled / tensors["attention_mask"].sum(dim=1).unsqueeze(-1)
                    self._assert_tensor_device(pooled)
                    if pooled.dtype != self._torch.float32:
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_PRECISION_MISMATCH")
                    host = pooled.detach().to(device="cpu", dtype=self._torch.float32)
                    if str(host.device) != "cpu" or host.dtype != self._torch.float32:
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_DEVICE_MISMATCH")
                    rows = host.tolist()
                    if len(rows) != len(batch):
                        raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_ROW_COUNT_MISMATCH")
                    output.extend(normalized_vector(tuple(row), self.dimension) for row in rows)
                self._synchronize()
                self._assert_runtime()
                if observations is not None:
                    assert observation is not None
                    observations.append(observation)
            self._assert_runtime()
            return tuple(output)
        except NativeEmbeddingBackendError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_INFERENCE_FAILED") from exc

    def _synchronize(self) -> None:
        if self._device == "CUDA":
            self._require_owned()
            self._torch.cuda.synchronize(0)

    def synchronize(self) -> None:
        """Measured-span device fence; no lease release or optional runtime bypass."""
        try:
            self._assert_runtime()
            self._synchronize()
            self._assert_runtime()
        except NativeEmbeddingBackendError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_INFERENCE_FAILED") from exc

    def allocator_peaks(self) -> NativeAllocatorPeaks:
        """Read actual cumulative local peaks, including constructor; never reset them."""
        try:
            self._assert_runtime()
            if self._device == "CPU":
                peaks = NativeAllocatorPeaks(None, None)
            else:
                self._synchronize()
                peaks = NativeAllocatorPeaks(
                    self._torch.cuda.max_memory_allocated(0),
                    self._torch.cuda.max_memory_reserved(0),
                )
                if peaks.allocated_bytes is None:
                    raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_NUMERICS_MISMATCH")
            self._assert_runtime()
            return peaks
        except NativeEmbeddingBackendError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_INFERENCE_FAILED") from exc

    def _discard_failed_model(self) -> None:
        # Never release the owner's lease on uncertain initialization/kernel failure.
        self._model = None
        self._tokenizer = None
        self._closed = True

    def close(self) -> None:
        """Synchronize before teardown; owner retains the physical lease until unit exit."""
        if self._closed:
            return
        self._assert_runtime()
        self._synchronize()
        self._model = None
        self._tokenizer = None
        self._closed = True
        self._require_owned()
