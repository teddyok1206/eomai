"""One pinned SDXL micro workspace: bounded inputs, exclusive outputs and terminal replay."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar

from eom_image_contracts import (
    ImageEvaluationBoundingBox,
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceObjectLineArtCropSet,
    LocalImageSdxlLoraMicroAdapterManifest,
    LocalImageSdxlLoraMicroCommand,
    LocalImageSdxlLoraMicroResult,
    SdxlLoraMicroRealizedSample,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_sdxl_lora_micro_result,
    validate_sdxl_lora_micro_sources,
)
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    LocalImageSdxlReviewedMicroResult,
    SdxlReviewedMicroRealizedSample,
    parse_sdxl_reviewed_micro_sources,
    sdxl_reviewed_micro_metadata_pointers,
)
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack, resolve_sdxl_stack
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel

from eom_image_trainer.crop_processing import (
    CropProcessingError,
    average_hash,
    decode_png,
    materialize_training_crop,
    png_bytes,
)
from eom_image_trainer.diffusers_backend import LoraTensorSample
from eom_image_trainer.runner import (
    TrainingBackendFailure,
    TrainingBackendResult,
    TrainingRunnerError,
    validate_adapter_files,
)

_Document = TypeVar("_Document", bound=BaseModel)
MAX_METADATA_BYTES = 2 * 1024**2
MAX_PNG_BYTES = 16 * 1024**2
_FULL_CROP = ImageEvaluationBoundingBox(left=0, top=0, right=10_000, bottom=10_000)


class SdxlMicroRunnerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SdxlMicroBackend(Protocol):
    def train(
        self,
        *,
        stack: ResolvedSdxlStack,
        samples: tuple[LoraTensorSample, ...],
        command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand,
        output_root: Path,
    ) -> TrainingBackendResult: ...


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


# The isolated CUDA runtime is Python 3.11; PEP 695 syntax would not import there.
def _document(  # noqa: UP047
    raw: bytes, contract: str, model: type[_Document], *, historical_newline: bool = False
) -> _Document:
    try:
        value = json.loads(raw)
        validate_contract(contract, value)
        document = model.model_validate(value)
        canonical = content_json_bytes(document.model_dump(mode="json"))
        if raw not in ((canonical, canonical + b"\n") if historical_newline else (canonical,)):
            raise ValueError("noncanonical input")
        return document
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise SdxlMicroRunnerError("IMAGE_TRAINING_DOCUMENT_INVALID") from exc


def load_sdxl_micro_command(
    workspace: Path, command_path: Path
) -> LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand:
    if command_path != workspace / "command.json":
        raise SdxlMicroRunnerError("IMAGE_TRAINING_COMMAND_PATH_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(root, "command.json", maximum_bytes=MAX_METADATA_BYTES)
        try:
            reviewed = (
                json.loads(raw).get("schema_version") == "local-image-sdxl-lora-micro-command/1.1"
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise SdxlMicroRunnerError("IMAGE_TRAINING_DOCUMENT_INVALID") from exc
        if reviewed:
            return _document(raw, "sdxl-lora-micro-command-v2", LocalImageSdxlReviewedMicroCommand)
        return _document(raw, "sdxl-lora-micro-command", LocalImageSdxlLoraMicroCommand)
    except ProviderError as exc:
        raise SdxlMicroRunnerError("IMAGE_TRAINING_COMMAND_INVALID") from exc


def _adapter_files(workspace: Path) -> tuple[dict[str, object], ...]:
    with verified_directory(workspace / "adapter", expected_owner_uid=os.geteuid()) as descriptor:
        if tuple(sorted(os.listdir(descriptor))) != (
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            raise SdxlMicroRunnerError("IMAGE_TRAINING_ADAPTER_INVALID")
    return validate_adapter_files(workspace / "adapter")


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand,
) -> LocalImageSdxlLoraMicroResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if any(os.path.lexists(workspace / name) for name in ("runtime-dataset", "adapter")):
            raise SdxlMicroRunnerError("IMAGE_TRAINING_UNRECEIPTED_OUTPUT")
        return None
    raw = read_staged_member(
        root, "result.json", maximum_bytes=MAX_METADATA_BYTES, expected_owner_uid=os.geteuid()
    )
    result = (
        _document(raw, "sdxl-lora-micro-result-v2", LocalImageSdxlReviewedMicroResult)
        if isinstance(command, LocalImageSdxlReviewedMicroCommand)
        else _document(raw, "sdxl-lora-micro-result", LocalImageSdxlLoraMicroResult)
    )
    try:
        validate_sdxl_lora_micro_result(command, result)
        for sample in result.realized_samples:
            read_staged_member(
                root,
                (
                    "inputs/targets/"
                    if isinstance(command, LocalImageSdxlReviewedMicroCommand)
                    else "runtime-dataset/"
                )
                + sample.sample_id
                + ".png",
                maximum_bytes=MAX_PNG_BYTES,
                expected_sha256=sample.realized_crop_sha256,
                expected_owner_uid=os.geteuid(),
            )
        if result.adapter_manifest is not None:
            if tuple(
                file.model_dump(mode="json") for file in result.adapter_manifest.files
            ) != _adapter_files(workspace):
                raise ValueError("adapter differs from terminal receipt")
            raw = read_staged_member(
                root,
                "adapter-manifest.json",
                maximum_bytes=MAX_METADATA_BYTES,
                expected_owner_uid=os.geteuid(),
            )
            if raw != content_json_bytes(result.adapter_manifest.model_dump(mode="json")):
                raise ValueError("adapter manifest differs from terminal receipt")
    except (ValueError, ProviderError, TrainingRunnerError) as exc:
        raise SdxlMicroRunnerError("IMAGE_TRAINING_RESULT_INVALID") from exc
    return result


def _manifest(
    command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand,
    realized: tuple[SdxlLoraMicroRealizedSample, ...],
    workspace: Path,
) -> LocalImageSdxlLoraMicroAdapterManifest:
    files = _adapter_files(workspace)
    logical = (
        "imgadapter_" + content_sha256({"training_command_sha256": command.command_sha256})[7:39]
    )
    body = {
        "schema_version": "local-image-sdxl-lora-micro-adapter-manifest/1.0",
        "adapter_id": logical,
        "adapter_revision_id": "imgadapterrev_"
        + content_sha256(
            {
                "adapter_id": logical,
                "base_model": command.base_model.model_dump(mode="json"),
                "files": files,
            }
        )[7:39],
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "base_model": command.base_model.model_dump(mode="json"),
        "training_command_sha256": command.command_sha256,
        "sample_set_sha256": content_sha256(
            [sample.model_dump(mode="json") for sample in realized]
        ),
        "files": list(files),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "manifest_sha256": content_sha256(body)}
    validate_contract("sdxl-lora-micro-adapter-manifest", value)
    return LocalImageSdxlLoraMicroAdapterManifest.model_validate(value)


def run_sdxl_micro_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand,
    backend: SdxlMicroBackend,
) -> LocalImageSdxlLoraMicroResult:
    """Materialize declared TRAIN pixels once; emit a verified local terminal result."""
    raw = content_json_bytes(command.model_dump(mode="json"))
    command = (
        _document(raw, "sdxl-lora-micro-command-v2", LocalImageSdxlReviewedMicroCommand)
        if isinstance(command, LocalImageSdxlReviewedMicroCommand)
        else _document(raw, "sdxl-lora-micro-command", LocalImageSdxlLoraMicroCommand)
    )
    if workspace.name != command.training_run_id:
        raise SdxlMicroRunnerError("IMAGE_TRAINING_WORKSPACE_ID_MISMATCH")
    started_at, started = datetime.now(UTC), time.monotonic()
    if command.created_at > started_at:
        raise SdxlMicroRunnerError("IMAGE_TRAINING_COMMAND_TIME_INVALID")
    realized: list[SdxlLoraMicroRealizedSample] = []
    runtime = None
    completed_steps = 0
    final_loss = None
    status, error, manifest = "SUCCEEDED", None, None
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw_command = read_staged_member(root, "command.json", maximum_bytes=MAX_METADATA_BYTES)
            if raw_command != content_json_bytes(command.model_dump(mode="json")):
                raise SdxlMicroRunnerError("IMAGE_TRAINING_COMMAND_MISMATCH")
            if isinstance(command, LocalImageSdxlReviewedMicroCommand):
                _admit_reviewed_metadata(root, command)
            replay = _replay(root, workspace, command)
            if replay is not None:
                return replay
            try:
                samples = (
                    _reviewed_tensor_samples(root, workspace, command, realized)
                    if isinstance(command, LocalImageSdxlReviewedMicroCommand)
                    else _original_tensor_samples(root, workspace, command, realized)
                )
                if (time.monotonic() - started) * 1000 > command.budget.maximum_duration_ms:
                    raise SdxlMicroRunnerError("IMAGE_TRAINING_RESOURCE_BUDGET_EXCEEDED")
                stack = resolve_sdxl_stack(model_store_root, command.base_model)
                output = backend.train(
                    stack=stack,
                    samples=tuple(samples),
                    command=command,
                    output_root=workspace / "adapter",
                )
                runtime, completed_steps, final_loss = (
                    output.runtime,
                    output.completed_steps,
                    output.final_loss,
                )
                if any(
                    getattr(runtime, name) != getattr(command.dependencies, name)
                    for name in type(command.dependencies).model_fields
                ):
                    runtime = None
                    raise SdxlMicroRunnerError("IMAGE_TRAINING_RUNTIME_DRIFT")
                if completed_steps != 200:
                    raise SdxlMicroRunnerError("IMAGE_TRAINING_INCOMPLETE_STEPS")
                if (
                    (time.monotonic() - started) * 1000 > command.budget.maximum_duration_ms
                    or runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
                ):
                    raise SdxlMicroRunnerError("IMAGE_TRAINING_RESOURCE_BUDGET_EXCEEDED")
                manifest = _manifest(command, tuple(realized), workspace)
            except (SdxlMicroRunnerError, TrainingRunnerError, CropProcessingError) as exc:
                status, error, manifest = "FAILED", exc.code, None
            except TrainingBackendFailure as exc:
                status, error = ("CANCELLED" if exc.cancelled else "FAILED"), exc.code
                completed_steps, final_loss = exc.completed_steps, exc.final_loss
                runtime = exc.runtime
                if runtime is not None and any(
                    getattr(runtime, name) != getattr(command.dependencies, name)
                    for name in type(command.dependencies).model_fields
                ):
                    runtime = None
            except ProviderError as exc:
                status, error = (
                    "FAILED",
                    (
                        "IMAGE_TRAINING_INPUT_HASH_MISMATCH"
                        if exc.code == "SDXL_PROBE_HASH_MISMATCH"
                        else "IMAGE_TRAINING_MODEL_INVALID"
                        if exc.code == "SDXL_PROBE_MODEL_INVALID"
                        else "IMAGE_TRAINING_INPUT_INVALID"
                    ),
                )
            except KeyboardInterrupt:
                status, error = "CANCELLED", "IMAGE_TRAINING_CANCELLED"
            except ValueError:
                status, error = "FAILED", "IMAGE_TRAINING_SOURCE_INVALID"
            except Exception:
                status, error = "FAILED", "IMAGE_TRAINING_EXEC_FAILED"
            completed = datetime.now(UTC)
            body = {
                "schema_version": "local-image-sdxl-lora-micro-result/1.1"
                if isinstance(command, LocalImageSdxlReviewedMicroCommand)
                else "local-image-sdxl-lora-micro-result/1.0",
                "training_run_id": command.training_run_id,
                "command_sha256": command.command_sha256,
                "status": status,
                "error_code": error,
                "adapter_manifest": manifest.model_dump(mode="json") if manifest else None,
                "realized_samples": [sample.model_dump(mode="json") for sample in realized],
                "sample_set_sha256": content_sha256(
                    [sample.model_dump(mode="json") for sample in realized]
                )
                if realized
                else None,
                "runtime": runtime.model_dump(mode="json") if runtime else None,
                "completed_steps": completed_steps,
                "final_loss": final_loss,
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": completed.isoformat().replace("+00:00", "Z"),
                "duration_ms": max(1, int((time.monotonic() - started) * 1000)),
            }
            value = {**body, "result_sha256": content_sha256(body)}
            result: LocalImageSdxlLoraMicroResult
            if isinstance(command, LocalImageSdxlReviewedMicroCommand):
                validate_contract("sdxl-lora-micro-result-v2", value)
                result = LocalImageSdxlReviewedMicroResult.model_validate(value)
            else:
                validate_contract("sdxl-lora-micro-result", value)
                result = LocalImageSdxlLoraMicroResult.model_validate(value)
            validate_sdxl_lora_micro_result(command, result)
            if manifest is not None:
                write_staged_member(
                    root,
                    "adapter-manifest.json",
                    content_json_bytes(manifest.model_dump(mode="json")),
                )
            write_staged_member(root, "result.json", content_json_bytes(value))
            return result
    except ProviderError as exc:
        raise SdxlMicroRunnerError("IMAGE_TRAINING_WORKSPACE_OR_RESULT_INVALID") from exc


def _admit_reviewed_metadata(root: int, command: LocalImageSdxlReviewedMicroCommand) -> None:
    crop_raw = read_staged_member(
        root,
        "inputs/source-crop-set.json",
        maximum_bytes=MAX_METADATA_BYTES,
        expected_sha256=command.source_crop_set.sha256,
    )
    try:
        pointers = sdxl_reviewed_micro_metadata_pointers(command, crop_raw)
        metadata = {
            name: (
                crop_raw
                if name == "inputs/source-crop-set.json"
                else read_staged_member(
                    root, name, maximum_bytes=MAX_METADATA_BYTES, expected_sha256=pointer.sha256
                )
            )
            for name, pointer in pointers.items()
        }
        parse_sdxl_reviewed_micro_sources(command, metadata)
    except (ValueError, JsonSchemaValidationError) as exc:
        raise SdxlMicroRunnerError("IMAGE_TRAINING_SOURCE_INVALID") from exc


def _reviewed_tensor_samples(
    root: int,
    workspace: Path,
    command: LocalImageSdxlReviewedMicroCommand,
    realized: list[SdxlLoraMicroRealizedSample],
) -> list[LoraTensorSample]:
    samples = []
    for sample in command.training_samples:
        raw = read_staged_member(
            root,
            sample.staged_member_path,
            maximum_bytes=MAX_PNG_BYTES,
            expected_sha256=sample.source_image.sha256,
        )
        # Reviewed preparation emits single-frame 8-bit RGB PNGs. Reject other modes,
        # rather than converting canonical targets or silently changing their pixels.
        if raw[24:26] != bytes((8, 2)) or decode_png(raw).size != (768, 512):
            raise SdxlMicroRunnerError("IMAGE_TRAINING_SAMPLE_DIMENSIONS_INVALID")
        samples.append(
            LoraTensorSample(sample.training_caption_en, workspace / sample.staged_member_path)
        )
        realized.append(
            SdxlReviewedMicroRealizedSample(
                sample_id=sample.sample_id,
                source_crop_sha256=sample.source_image.sha256,
                realized_crop_sha256=sample.source_image.sha256,
                training_caption_sha256=sample.training_caption_sha256,
            )
        )
    return samples


def _original_tensor_samples(
    root: int,
    workspace: Path,
    command: LocalImageSdxlLoraMicroCommand,
    realized: list[SdxlLoraMicroRealizedSample],
) -> list[LoraTensorSample]:
    crops = _document(
        read_staged_member(
            root,
            "inputs/crop-set.json",
            maximum_bytes=MAX_METADATA_BYTES,
            expected_sha256=command.crop_set.sha256,
        ),
        "science-object-line-art-crop-set",
        LocalImageScienceObjectLineArtCropSet,
        historical_newline=True,
    )
    _document(
        read_staged_member(
            root,
            "inputs/authorization.json",
            maximum_bytes=MAX_METADATA_BYTES,
            expected_sha256=command.training_authorization.sha256,
        ),
        "science-corpus-training-authorization",
        LocalImageScienceCorpusTrainingAuthorization,
        historical_newline=True,
    )
    validate_sdxl_lora_micro_sources(command, crops)
    create_staged_directory(root, "runtime-dataset")
    samples: list[LoraTensorSample] = []
    seen: set[str] = set()
    for sample in command.training_samples:
        source = decode_png(
            read_staged_member(
                root,
                sample.staged_member_path,
                maximum_bytes=MAX_PNG_BYTES,
                expected_sha256=sample.source_image.sha256,
            )
        )
        if source.size != (sample.source_width_px, sample.source_height_px):
            raise SdxlMicroRunnerError("IMAGE_TRAINING_SAMPLE_DIMENSIONS_INVALID")
        image = materialize_training_crop(
            source, crop_box=_FULL_CROP, redaction_boxes=sample.redaction_boxes
        )
        average_hash(image)  # Reject a redaction that erased the entire object.
        payload = png_bytes(image)
        sha = _sha(payload)
        if sha in seen:
            raise SdxlMicroRunnerError("IMAGE_TRAINING_DUPLICATE_REALIZED_PIXELS")
        seen.add(sha)
        member = "runtime-dataset/" + sample.sample_id + ".png"
        write_staged_member(root, member, payload)
        samples.append(LoraTensorSample(sample.training_caption_en, workspace / member))
        realized.append(
            SdxlLoraMicroRealizedSample(
                sample_id=sample.sample_id,
                source_crop_sha256=sample.source_image.sha256,
                realized_crop_sha256=sha,
                training_caption_sha256=text_sha256(sample.training_caption_en),
            )
        )
    return samples
