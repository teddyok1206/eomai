"""Exact native inputs and terminal-only execution in one isolated SDXL workspace."""

from __future__ import annotations

import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar

from eom_image_contracts import content_json_bytes, content_sha256, validate_contract
from eom_image_contracts.sdxl_lora_micro import sdxl_lora_adapter_ids
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraAdapterManifest,
    LocalImageSdxlNativeLoraResult,
    NativeLoraCommand,
    SdxlNativeLoraRealizedSample,
    native_lora_command_protocol,
    validate_sdxl_native_lora_result,
)
from eom_image_contracts.sdxl_native_lora_sources import (
    NATIVE_LORA_MAX_METADATA_BYTES,
    SdxlNativeLoraMetadataAdmission,
    SdxlNativeLoraSources,
    sdxl_native_lora_metadata_member_path,
)
from eom_image_contracts.training import LocalImageLoraAdapterFile, LocalImageLoraTrainingRuntime
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack, resolve_sdxl_stack
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    write_staged_member,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel

from eom_image_trainer.crop_processing import CropProcessingError, decode_png
from eom_image_trainer.diffusers_backend import LoraTensorSample
from eom_image_trainer.runner import (
    TrainingBackendFailure,
    TrainingBackendResult,
    TrainingRunnerError,
)
from eom_image_trainer.sdxl_adapter_output import validate_sdxl_adapter_files

_Document = TypeVar("_Document", bound=BaseModel)


class SdxlNativeLoraRunnerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NativeLoraTrainingBackend(Protocol):
    def train(
        self,
        *,
        stack: ResolvedSdxlStack,
        samples: tuple[LoraTensorSample, ...],
        command: NativeLoraCommand,
        output_root: Path,
    ) -> TrainingBackendResult: ...


# The actual isolated CUDA interpreter is Python3.11, not the source test interpreter.
def _validated_document(  # noqa: UP047
    raw: bytes, value: object, contract: str, model: type[_Document]
) -> _Document:
    try:
        if not isinstance(value, dict):
            raise ValueError("document must be an object")
        validate_contract(contract, value)
        document = model.model_validate(value)
        if raw != content_json_bytes(document.model_dump(mode="json")):
            raise ValueError("noncanonical document")
        return document
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_DOCUMENT_INVALID") from exc


def _document(  # noqa: UP047
    raw: bytes, contract: str, model: type[_Document]
) -> _Document:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_DOCUMENT_INVALID") from exc
    return _validated_document(raw, value, contract, model)


def load_sdxl_native_lora_command(workspace: Path, command_path: Path) -> NativeLoraCommand:
    if command_path != workspace / "command.json":
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_COMMAND_PATH_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(
                root, "command.json", maximum_bytes=NATIVE_LORA_MAX_METADATA_BYTES
            )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("command must be an object")
        protocol = native_lora_command_protocol(value.get("schema_version", ""))
        return _validated_document(raw, value, protocol.contract, protocol.model)
    except ProviderError as exc:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_COMMAND_INVALID") from exc
    except (ValueError, TypeError) as exc:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_DOCUMENT_INVALID") from exc


def _directory_members(root: int, parts: tuple[str, ...]) -> set[str]:
    """Inspect only fixed local input directories through no-link descriptors."""
    descriptors = []
    try:
        for part in parts:
            root = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
            )
            descriptors.append(root)
        return set(os.listdir(root))
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _admit_metadata(root: int, command: NativeLoraCommand) -> SdxlNativeLoraSources:
    admission = SdxlNativeLoraMetadataAdmission(command)
    while pending := admission.pending_pointers():
        for pointer in pending:
            raw = read_staged_member(
                root,
                sdxl_native_lora_metadata_member_path(pointer),
                maximum_bytes=NATIVE_LORA_MAX_METADATA_BYTES,
                expected_sha256=pointer.sha256,
            )
            admission.admit(pointer, raw)
    sources = admission.validated_sources()
    if (
        _directory_members(root, ("inputs",)) != {"metadata", "targets"}
        or _directory_members(root, ("inputs", "metadata"))
        != {
            sdxl_native_lora_metadata_member_path(p).rsplit("/", 1)[1]
            for p in sources.metadata_pointers
        }
        or _directory_members(root, ("inputs", "targets"))
        != {s.sample_id + ".png" for s in command.training_samples}
    ):
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_INPUT_CLOSURE_INVALID")
    return sources


def _replay(
    root: int, workspace: Path, command: NativeLoraCommand
) -> LocalImageSdxlNativeLoraResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if any(
            os.path.lexists(workspace / name)
            for name in ("adapter", "adapter-manifest.json", "runtime-dataset")
        ):
            raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_UNRECEIPTED_OUTPUT")
        return None
    result = _document(
        read_staged_member(
            root,
            "result.json",
            maximum_bytes=NATIVE_LORA_MAX_METADATA_BYTES,
            expected_owner_uid=os.geteuid(),
        ),
        "sdxl-native-lora-result",
        LocalImageSdxlNativeLoraResult,
    )
    try:
        validate_sdxl_native_lora_result(command, result)
        if result.adapter_manifest is not None:
            if tuple(
                f.model_dump(mode="json") for f in result.adapter_manifest.files
            ) != validate_sdxl_adapter_files(workspace):
                raise ValueError("adapter differs from receipt")
            raw = read_staged_member(
                root,
                "adapter-manifest.json",
                maximum_bytes=NATIVE_LORA_MAX_METADATA_BYTES,
                expected_owner_uid=os.geteuid(),
            )
            if raw != content_json_bytes(result.adapter_manifest.model_dump(mode="json")):
                raise ValueError("manifest differs from receipt")
        elif os.path.lexists(workspace / "adapter-manifest.json"):
            raise ValueError("failed run has a purported accepted manifest")
    except (ValueError, TrainingRunnerError, ProviderError) as exc:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_RESULT_INVALID") from exc
    return result


def _tensor_samples(
    root: int,
    workspace: Path,
    command: NativeLoraCommand,
    sources: SdxlNativeLoraSources,
    realized: list[SdxlNativeLoraRealizedSample],
) -> tuple[LoraTensorSample, ...]:
    samples = []
    for sample, target in zip(command.training_samples, sources.targets, strict=True):
        raw = read_staged_member(
            root,
            sample.staged_member_path,
            maximum_bytes=target.size_bytes,
            expected_sha256=sample.source_image.sha256,
        )
        if (
            len(raw) != target.size_bytes
            or raw[24:26] != bytes((8, 2))
            or decode_png(raw).size != sample.width_height
        ):
            raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_SAMPLE_DIMENSIONS_INVALID")
        width, height = sample.width_height
        samples.append(
            LoraTensorSample(
                sample.training_caption_en, workspace / sample.staged_member_path, width, height
            )
        )
        realized.append(
            SdxlNativeLoraRealizedSample(
                sample_id=sample.sample_id,
                target_png_sha256=sample.source_image.sha256,
                training_caption_sha256=sample.training_caption_sha256,
                canvas=sample.canvas,
            )
        )
    return tuple(samples)


def _manifest(
    command: NativeLoraCommand,
    realized: list[SdxlNativeLoraRealizedSample],
    workspace: Path,
) -> LocalImageSdxlNativeLoraAdapterManifest:
    files = tuple(
        LocalImageLoraAdapterFile.model_validate(f) for f in validate_sdxl_adapter_files(workspace)
    )
    logical, revision = sdxl_lora_adapter_ids(
        training_command_sha256=command.command_sha256, base_model=command.base_model, files=files
    )
    body = {
        "schema_version": "local-image-sdxl-native-lora-adapter-manifest/1.0",
        "adapter_id": logical,
        "adapter_revision_id": revision,
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "base_model": command.base_model.model_dump(mode="json"),
        "training_command_sha256": command.command_sha256,
        "sample_set_sha256": content_sha256([s.model_dump(mode="json") for s in realized]),
        "files": [f.model_dump(mode="json") for f in files],
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "profile": command.profile,
    }
    return _document(
        content_json_bytes({**body, "manifest_sha256": content_sha256(body)}),
        "sdxl-native-lora-adapter-manifest",
        LocalImageSdxlNativeLoraAdapterManifest,
    )


def _matching_runtime(
    command: NativeLoraCommand, runtime: LocalImageLoraTrainingRuntime | None
) -> LocalImageLoraTrainingRuntime | None:
    if runtime is None or any(
        getattr(runtime, name) != getattr(command.dependencies, name)
        for name in type(command.dependencies).model_fields
    ):
        return None
    return runtime


def run_sdxl_native_lora_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: NativeLoraCommand,
    backend: NativeLoraTrainingBackend,
) -> LocalImageSdxlNativeLoraResult:
    """Validate metadata before pixels/models; preserve terminal outcomes without resume."""
    protocol = native_lora_command_protocol(command.schema_version)
    command = _document(
        content_json_bytes(command.model_dump(mode="json")),
        protocol.contract,
        protocol.model,
    )
    if workspace.name != command.training_run_id:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_WORKSPACE_ID_MISMATCH")
    started_at, started = datetime.now(UTC), time.monotonic()
    if command.created_at > started_at:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_COMMAND_TIME_INVALID")
    realized: list[SdxlNativeLoraRealizedSample] = []
    runtime: LocalImageLoraTrainingRuntime | None = None
    completed_steps, final_loss = 0, None
    status, error = "SUCCEEDED", None
    manifest: LocalImageSdxlNativeLoraAdapterManifest | None = None
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if read_staged_member(
                root, "command.json", maximum_bytes=NATIVE_LORA_MAX_METADATA_BYTES
            ) != content_json_bytes(command.model_dump(mode="json")):
                raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_COMMAND_MISMATCH")
            try:
                sources = _admit_metadata(root, command)
            except (ValueError, JsonSchemaValidationError, OSError) as exc:
                raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_SOURCE_INVALID") from exc
            replay = _replay(root, workspace, command)
            if replay is not None:
                # Validate the closed pinned input hashes, not tensors or rewritten PNGs.
                for sample, target in zip(command.training_samples, sources.targets, strict=True):
                    read_staged_member(
                        root,
                        sample.staged_member_path,
                        maximum_bytes=target.size_bytes,
                        expected_sha256=sample.source_image.sha256,
                    )
                return replay
            try:
                samples = _tensor_samples(root, workspace, command, sources, realized)
                if (time.monotonic() - started) * 1000 > command.budget.maximum_duration_ms:
                    raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_RESOURCE_BUDGET_EXCEEDED")
                stack = resolve_sdxl_stack(model_store_root, command.base_model)
                output = backend.train(
                    stack=stack, samples=samples, command=command, output_root=workspace / "adapter"
                )
                runtime, completed_steps, final_loss = (
                    output.runtime,
                    output.completed_steps,
                    output.final_loss,
                )
                if not math.isfinite(final_loss) or not 0 <= final_loss <= 1_000_000:
                    final_loss = None
                    raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_LOSS_INVALID")
                if _matching_runtime(command, runtime) is None:
                    runtime = None
                    raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_RUNTIME_DRIFT")
                if completed_steps != command.hyperparameters.max_train_steps:
                    raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_INCOMPLETE_STEPS")
                if (
                    (time.monotonic() - started) * 1000 > command.budget.maximum_duration_ms
                    or runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
                ):
                    raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_RESOURCE_BUDGET_EXCEEDED")
                manifest = _manifest(command, realized, workspace)
            except (SdxlNativeLoraRunnerError, TrainingRunnerError, CropProcessingError) as exc:
                status, error = "FAILED", exc.code
            except TrainingBackendFailure as exc:
                status, error = (
                    ("CANCELLED", "IMAGE_TRAINING_CANCELLED")
                    if exc.cancelled
                    else ("FAILED", exc.code)
                )
                completed_steps, final_loss = exc.completed_steps, exc.final_loss
                if final_loss is not None and (
                    not math.isfinite(final_loss) or not 0 <= final_loss <= 1_000_000
                ):
                    final_loss = None
                runtime = _matching_runtime(command, exc.runtime)
            except ProviderError as exc:
                status, error = (
                    "FAILED",
                    "IMAGE_TRAINING_INPUT_HASH_MISMATCH"
                    if exc.code == "SDXL_PROBE_HASH_MISMATCH"
                    else "IMAGE_TRAINING_MODEL_INVALID"
                    if exc.code == "SDXL_PROBE_MODEL_INVALID"
                    else "IMAGE_TRAINING_INPUT_INVALID",
                )
            except KeyboardInterrupt:
                status, error = "CANCELLED", "IMAGE_TRAINING_CANCELLED"
            except Exception:
                status, error = "FAILED", "IMAGE_TRAINING_EXEC_FAILED"
            body = {
                "schema_version": "local-image-sdxl-native-lora-result/1.0",
                "training_run_id": command.training_run_id,
                "command_sha256": command.command_sha256,
                "profile": command.profile,
                "status": status,
                "error_code": error,
                "adapter_manifest": manifest.model_dump(mode="json") if manifest else None,
                "realized_samples": [s.model_dump(mode="json") for s in realized],
                "sample_set_sha256": content_sha256([s.model_dump(mode="json") for s in realized])
                if realized
                else None,
                "runtime": runtime.model_dump(mode="json") if runtime else None,
                "requested_steps": command.hyperparameters.max_train_steps,
                "completed_steps": completed_steps,
                "final_loss": final_loss,
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "duration_ms": max(1, int((time.monotonic() - started) * 1000)),
            }
            result = _document(
                content_json_bytes({**body, "result_sha256": content_sha256(body)}),
                "sdxl-native-lora-result",
                LocalImageSdxlNativeLoraResult,
            )
            validate_sdxl_native_lora_result(command, result)
            if manifest is not None:
                write_staged_member(
                    root,
                    "adapter-manifest.json",
                    content_json_bytes(manifest.model_dump(mode="json")),
                )
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except ProviderError as exc:
        raise SdxlNativeLoraRunnerError("IMAGE_TRAINING_WORKSPACE_OR_RESULT_INVALID") from exc
