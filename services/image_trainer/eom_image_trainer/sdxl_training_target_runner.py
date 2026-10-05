"""Isolated CPU-only reviewed TRAIN preparation; no model, database or NAS access."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts import (
    LocalImageSdxlTrainingTargetCommand,
    LocalImageSdxlTrainingTargetResult,
    SdxlPreparedTrainingTarget,
    SdxlPrepareTargetDecision,
    content_json_bytes,
    content_sha256,
    parse_sdxl_training_target_sources,
    sdxl_target_caption,
    sdxl_target_id,
    sdxl_target_placement,
    text_sha256,
    validate_contract,
    validate_sdxl_training_target_result,
)
from eom_image_contracts.sdxl_lora_micro import SdxlLoraMicroSample
from eom_image_contracts.sdxl_native_training_targets import (
    NATIVE_TARGET_CANVASES,
    NativeTrainingTargetCommand,
    NativeTrainingTargetResult,
    SdxlNativePrepareTargetDecision,
    SdxlNativeTargetPlacement,
    SdxlNativeTrainingTargetSources,
    SdxlPreparedNativeTrainingTarget,
    native_training_target_protocol,
    parse_sdxl_native_training_target_sources,
    sdxl_native_target_id,
    sdxl_native_target_placement,
    validate_sdxl_native_training_target_result,
)
from eom_image_contracts.sdxl_source_training_targets import (
    LocalImageSdxlSourceTrainingTargetCommand,
    LocalImageSdxlSourceTrainingTargetResult,
    SdxlPreparedSourceTrainingTarget,
    SdxlSourcePrepareTargetDecision,
    SdxlSourceTargetSample,
    SdxlSourceTrainingTargetSources,
    parse_sdxl_source_training_target_sources,
    sdxl_source_target_caption,
    sdxl_source_target_id,
    sdxl_source_target_placement,
    validate_sdxl_source_training_target_result,
)
from eom_image_contracts.sdxl_training_targets import (
    SdxlTargetPlacement,
    SdxlTrainingTargetSources,
    TargetErrorCode,
    sdxl_reviewed_target_caption,
)
from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image
from PIL import __version__ as pillow_version

from eom_image_trainer.crop_processing import (
    CropProcessingError,
    materialize_reviewed_sdxl_target,
    png_bytes,
)

MAX_METADATA_BYTES = 2 * 1024**2
MAX_SOURCE_BYTES = 16 * 1024**2
TargetCommand = (
    LocalImageSdxlTrainingTargetCommand
    | LocalImageSdxlSourceTrainingTargetCommand
    | NativeTrainingTargetCommand
)
TargetResult = (
    LocalImageSdxlTrainingTargetResult
    | LocalImageSdxlSourceTrainingTargetResult
    | NativeTrainingTargetResult
)
TargetSources = (
    SdxlTrainingTargetSources | SdxlSourceTrainingTargetSources | SdxlNativeTrainingTargetSources
)
PreparedTarget = SdxlPreparedTrainingTarget | SdxlPreparedNativeTrainingTarget


class SdxlTrainingTargetError(RuntimeError):
    def __init__(self, code: TargetErrorCode) -> None:
        super().__init__(code)
        self.code = code


def _command(raw: bytes) -> TargetCommand:
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("command must be an object")
        command: TargetCommand
        if value.get("schema_version") in {
            "local-image-sdxl-training-target-command/1.2",
            "local-image-sdxl-training-target-command/1.3",
        }:
            protocol = native_training_target_protocol(value["schema_version"])
            validate_contract(protocol.command_contract, value)
            command = protocol.command_model.model_validate(value)
        elif value.get("schema_version") == "local-image-sdxl-training-target-command/1.1":
            validate_contract("sdxl-training-target-command-v2", value)
            command = LocalImageSdxlSourceTrainingTargetCommand.model_validate(value)
        else:
            validate_contract("sdxl-training-target-command", value)
            command = LocalImageSdxlTrainingTargetCommand.model_validate(value)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise ValueError("noncanonical command")
        return command
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID") from exc


def load_sdxl_training_target_command(workspace: Path, command_path: Path) -> TargetCommand:
    if command_path != workspace / "command.json":
        raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            return _command(
                read_staged_member(root, "command.json", maximum_bytes=MAX_METADATA_BYTES)
            )
    except ProviderError as exc:
        raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID") from exc


def _decode(
    payload: bytes, *, size: tuple[int, int], required_mode: str | None = None
) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if (
                source.format != "PNG"
                or source.mode not in {"RGB", "L"}
                or getattr(source, "n_frames", 1) != 1
                or source.size != size
                or (required_mode is not None and source.mode != required_mode)
            ):
                raise ValueError("source PNG metadata mismatch")
            source.load()
            return source.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise SdxlTrainingTargetError("SDXL_TARGET_SOURCE_INVALID") from exc


def _check_outputs(workspace: Path, root: int, result: TargetResult) -> None:
    try:
        if result.prepared_targets or os.path.lexists(workspace / "targets"):
            with verified_directory(
                workspace / "targets", expected_owner_uid=os.geteuid()
            ) as outputs:
                if tuple(sorted(os.listdir(outputs))) != tuple(
                    sorted(target.target_id + ".png" for target in result.prepared_targets)
                ):
                    raise ValueError("unreceipted target output")
        for target in result.prepared_targets:
            payload = read_staged_member(
                root,
                target.member_path,
                maximum_bytes=target.size_bytes,
                expected_sha256=target.sha256,
                expected_owner_uid=os.geteuid(),
            )
            if len(payload) != target.size_bytes:
                raise ValueError("target size mismatch")
            _decode(payload, size=(target.width_px, target.height_px), required_mode=target.mode)
    except (ValueError, ProviderError, SdxlTrainingTargetError) as exc:
        raise SdxlTrainingTargetError("SDXL_TARGET_OUTPUT_INVALID") from exc


def _load_sources(root: int, command: TargetCommand) -> TargetSources:
    def read(member: str) -> bytes:
        return read_staged_member(root, member, maximum_bytes=MAX_METADATA_BYTES)

    if isinstance(command, NativeTrainingTargetCommand):
        return parse_sdxl_native_training_target_sources(
            command,
            crop_set_payload=read("inputs/source-crop-set.json"),
            source_command_payload=read("inputs/native-crop-command.json"),
            review_payload=read("inputs/source-review.json"),
            authorization_payload=read("inputs/authorization.json"),
        )
    if isinstance(command, LocalImageSdxlSourceTrainingTargetCommand):
        return parse_sdxl_source_training_target_sources(
            command,
            crop_set_payload=read("inputs/source-crop-set.json"),
            review_payload=read("inputs/source-review.json"),
            authorization_payload=read("inputs/authorization.json"),
        )
    return parse_sdxl_training_target_sources(
        command,
        training_command_payload=read("inputs/training-command.json"),
        training_result_payload=read("inputs/training-result.json"),
        crop_set_payload=read("inputs/crop-set.json"),
        authorization_payload=read("inputs/authorization.json"),
    )


def _validated_result(
    command: TargetCommand, sources: TargetSources, value: object
) -> TargetResult:
    if not isinstance(value, dict):
        raise ValueError("result must be an object")
    if isinstance(command, NativeTrainingTargetCommand):
        if not isinstance(sources, SdxlNativeTrainingTargetSources):
            raise ValueError("source protocol mismatch")
        protocol = native_training_target_protocol(command.schema_version)
        validate_contract(protocol.result_contract, value)
        native_result = protocol.result_model.model_validate(value)
        validate_sdxl_native_training_target_result(command, sources, native_result)
        return native_result
    if isinstance(command, LocalImageSdxlSourceTrainingTargetCommand):
        if not isinstance(sources, SdxlSourceTrainingTargetSources):
            raise ValueError("source protocol mismatch")
        validate_contract("sdxl-training-target-result-v2", value)
        result = LocalImageSdxlSourceTrainingTargetResult.model_validate(value)
        validate_sdxl_source_training_target_result(command, sources, result)
        return result
    if not isinstance(sources, SdxlTrainingTargetSources):
        raise ValueError("source protocol mismatch")
    validate_contract("sdxl-training-target-result", value)
    legacy_result = LocalImageSdxlTrainingTargetResult.model_validate(value)
    validate_sdxl_training_target_result(command, sources, legacy_result)
    return legacy_result


def _source_result_fields(command: TargetCommand, sources: TargetSources) -> dict[str, str]:
    if isinstance(command, NativeTrainingTargetCommand) and isinstance(
        sources, SdxlNativeTrainingTargetSources
    ):
        return {
            "schema_version": command.schema_version.replace("-command/", "-result/"),
            "source_snapshot_sha256": sources.snapshot_sha256,
        }
    if isinstance(command, LocalImageSdxlSourceTrainingTargetCommand) and isinstance(
        sources, SdxlSourceTrainingTargetSources
    ):
        return {
            "schema_version": "local-image-sdxl-training-target-result/1.1",
            "source_snapshot_sha256": sources.snapshot_sha256,
        }
    if isinstance(command, LocalImageSdxlTrainingTargetCommand) and isinstance(
        sources, SdxlTrainingTargetSources
    ):
        return {
            "schema_version": "local-image-sdxl-training-target-result/1.0",
            "original_training_command_sha256": sources.training_command.command_sha256,
            "original_training_result_sha256": sources.training_result.result_sha256,
        }
    raise ValueError("source protocol mismatch")


def run_sdxl_training_target_command(
    *,
    workspace: Path,
    command: TargetCommand,
) -> TargetResult:
    """Read only declared TRAIN pixels; exclusive output plus verified receipt-only replay."""
    command = _command(content_json_bytes(command.model_dump(mode="json")))
    started_at, started = datetime.now(UTC), time.monotonic()
    if workspace.name != command.run_id or command.created_at > started_at:
        raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if (
                _command(read_staged_member(root, "command.json", maximum_bytes=MAX_METADATA_BYTES))
                != command
            ):
                raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID")
            sources = _load_sources(root, command)
            if os.path.lexists(workspace / "result.json"):
                raw = read_staged_member(
                    root,
                    "result.json",
                    maximum_bytes=MAX_METADATA_BYTES,
                    expected_owner_uid=os.geteuid(),
                )
                try:
                    value = json.loads(raw)
                    result = _validated_result(command, sources, value)
                    if raw != content_json_bytes(result.model_dump(mode="json")):
                        raise ValueError("noncanonical result")
                except (ValueError, TypeError, JsonSchemaValidationError) as exc:
                    raise SdxlTrainingTargetError("SDXL_TARGET_OUTPUT_INVALID") from exc
                _check_outputs(workspace, root, result)
                return result
            if os.path.lexists(workspace / "targets"):
                raise SdxlTrainingTargetError("SDXL_TARGET_OUTPUT_INVALID")
            prepared: list[PreparedTarget] = []
            native_output_hashes: set[str] = set()
            error: TargetErrorCode | None = None
            source_samples: tuple[SdxlSourceTargetSample, ...] | tuple[SdxlLoraMicroSample, ...] = (
                sources.samples
                if isinstance(
                    sources, (SdxlSourceTrainingTargetSources, SdxlNativeTrainingTargetSources)
                )
                else sources.training_command.training_samples
            )
            samples = {sample.sample_id: sample for sample in source_samples}
            try:
                if pillow_version != command.pillow_version:
                    raise SdxlTrainingTargetError("SDXL_TARGET_RUNTIME_MISMATCH")
                create_staged_directory(root, "targets")
                for decision in command.decisions:
                    if not isinstance(decision, SdxlPrepareTargetDecision):
                        continue
                    sample = samples[decision.sample_id]
                    source = _decode(
                        read_staged_member(
                            root,
                            sample.staged_member_path,
                            maximum_bytes=MAX_SOURCE_BYTES,
                            expected_sha256=sample.source_image.sha256,
                        ),
                        size=(sample.source_width_px, sample.source_height_px),
                    )
                    target_model: (
                        type[SdxlPreparedTrainingTarget] | type[SdxlPreparedNativeTrainingTarget]
                    )
                    placement: SdxlTargetPlacement | SdxlNativeTargetPlacement
                    canvas_size = (768, 512)
                    if isinstance(command, NativeTrainingTargetCommand):
                        if not isinstance(sample, SdxlSourceTargetSample) or not isinstance(
                            decision, SdxlNativePrepareTargetDecision
                        ):
                            raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID")
                        placement = sdxl_native_target_placement(
                            sample, decision, maximum_upscale_milli=command.maximum_upscale_milli
                        )
                        logical = sdxl_native_target_id(command, sample, decision)
                        caption = sdxl_reviewed_target_caption(
                            decision.reviewed_caption_en, decision.expression
                        )
                        canvas_size = NATIVE_TARGET_CANVASES[decision.canvas]
                        target_model = SdxlPreparedNativeTrainingTarget
                    elif isinstance(command, LocalImageSdxlSourceTrainingTargetCommand):
                        if not isinstance(sample, SdxlSourceTargetSample) or not isinstance(
                            decision, SdxlSourcePrepareTargetDecision
                        ):
                            raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID")
                        placement = sdxl_source_target_placement(
                            sample, decision, maximum_upscale_milli=command.maximum_upscale_milli
                        )
                        logical = sdxl_source_target_id(command, sample, decision)
                        caption = sdxl_source_target_caption(sample, decision)
                        target_model = SdxlPreparedSourceTrainingTarget
                    else:
                        if not isinstance(sample, SdxlLoraMicroSample):
                            raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID")
                        placement = sdxl_target_placement(
                            sample, decision, maximum_upscale_milli=command.maximum_upscale_milli
                        )
                        logical = sdxl_target_id(command, sample, decision)
                        caption = sdxl_target_caption(sample, decision)
                        target_model = SdxlPreparedTrainingTarget
                    image = materialize_reviewed_sdxl_target(
                        source, decision=decision, placement=placement
                    )
                    payload = png_bytes(image)
                    sha = "sha256:" + hashlib.sha256(payload).hexdigest()
                    if isinstance(command, NativeTrainingTargetCommand):
                        if sha in native_output_hashes:
                            raise SdxlTrainingTargetError("SDXL_TARGET_SOURCE_INVALID")
                        native_output_hashes.add(sha)
                    caption_sha = text_sha256(caption)
                    revision = content_sha256(
                        {
                            "target_id": logical,
                            "sha256": sha,
                            "training_caption_sha256": caption_sha,
                            "placement": placement.model_dump(mode="json"),
                        }
                    )
                    target = target_model.model_validate(
                        {
                            "sample_id": sample.sample_id,
                            "target_id": logical,
                            "target_revision_id": "imgsdxltargetrev_" + revision[7:39],
                            "source_crop_sha256": sample.source_image.sha256,
                            "member_path": "targets/" + logical + ".png",
                            "sha256": sha,
                            "size_bytes": len(payload),
                            "width_px": canvas_size[0],
                            "height_px": canvas_size[1],
                            "mode": "RGB",
                            "training_caption_en": caption,
                            "training_caption_sha256": caption_sha,
                            "placement": placement,
                        }
                    )
                    write_staged_member(root, target.member_path, payload)
                    prepared.append(target)
            except SdxlTrainingTargetError as exc:
                error = exc.code
            except CropProcessingError:
                error = "SDXL_TARGET_SOURCE_INVALID"
            except ProviderError as exc:
                error = (
                    "SDXL_TARGET_OUTPUT_INVALID"
                    if exc.code == "SDXL_PROBE_OUTPUT_INVALID"
                    else "SDXL_TARGET_SOURCE_INVALID"
                )
            except Exception:
                error = "SDXL_TARGET_PREPARATION_FAILED"
            body = {
                **_source_result_fields(command, sources),
                "run_id": command.run_id,
                "command_sha256": command.command_sha256,
                "state": "UNREVIEWED_TRAIN_TARGET_CANDIDATES",
                "activation_policy": "FORBIDDEN",
                "status": "SUCCEEDED" if error is None else "FAILED",
                "error_code": error,
                "pillow_version": pillow_version,
                "prepared_targets": [target.model_dump(mode="json") for target in prepared],
                "deferred_sample_ids": [
                    decision.sample_id
                    for decision in command.decisions
                    if decision.disposition == "DEFER"
                ],
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "duration_ms": max(1, int((time.monotonic() - started) * 1000)),
            }
            value = {**body, "result_sha256": content_sha256(body)}
            result = _validated_result(command, sources, value)
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except (ProviderError, ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise SdxlTrainingTargetError("SDXL_TARGET_INPUT_INVALID") from exc
