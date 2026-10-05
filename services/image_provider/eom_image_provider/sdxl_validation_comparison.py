"""Frozen reserved-crop diagnostic on the existing paired GPU lifecycle."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import cast, get_args

from eom_image_contracts.models import LocalImageRuntime, content_json_bytes, content_sha256
from eom_image_contracts.sdxl_learned_comparison import SdxlLearnedComparisonOutput
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommand,
    LocalImageSdxlValidationComparisonResult,
    SdxlValidationComparisonSources,
    parse_sdxl_validation_command,
    parse_sdxl_validation_configuration,
    parse_sdxl_validation_crop_source,
    parse_sdxl_validation_result,
    sdxl_validation_adapter,
    sdxl_validation_native_result_fields,
    sdxl_validation_protocol,
    validate_sdxl_validation_result,
    validate_sdxl_validation_sources,
)
from eom_image_contracts.validation import validate_contract
from jsonschema import ValidationError as SchemaError
from PIL import Image

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_controller_io import resolve_sdxl_canny_controller
from eom_image_provider.sdxl_canny_pixels import (
    canny_conditioning_canvas_png,
    read_canny_runtime,
    sdxl_canny_native_source_canvas,
)
from eom_image_provider.sdxl_canny_reference import ReferenceBackendFactory
from eom_image_provider.sdxl_canny_reference_backend import (
    SdxlCannyReferenceDiffusersBackend,
)
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.sdxl_pair_inference import (
    create_sdxl_pair_directories,
    run_sdxl_pair_inference,
)
from eom_image_provider.sdxl_pair_output_validation import validate_sdxl_pair_output_members
from eom_image_provider.sdxl_reference_metadata import read_sdxl_reference_metadata
from eom_image_provider.sdxl_reference_pixels import (
    REFERENCE_PIXEL_DIRECTORIES,
    prepare_sdxl_reference_pixels,
    validate_sdxl_reference_pixel_members,
)
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(SdxlProbeErrorCode))
_PIXEL_DIRECTORIES = REFERENCE_PIXEL_DIRECTORIES


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_sdxl_validation_sources(
    root: int, command: LocalImageSdxlValidationComparisonCommand
) -> SdxlValidationComparisonSources:
    metadata = read_sdxl_reference_metadata(root, command.configuration_anchor)
    anchor_raw, inherited = metadata.command_raw, metadata.inherited
    configuration = parse_sdxl_validation_configuration(command, anchor_raw, inherited)
    crops = tuple(
        parse_sdxl_validation_crop_source(
            pin,
            review_raw=read_staged_member(
                root,
                f"inputs/validation-sources/{index}/review.json",
                maximum_bytes=2 * 1024**2,
                expected_sha256=pin.review.sha256,
            ),
            crop_set_raw=read_staged_member(
                root,
                f"inputs/validation-sources/{index}/crop-set.json",
                maximum_bytes=2 * 1024**2,
                expected_sha256=pin.crop_set.sha256,
            ),
        )
        for index, pin in enumerate(command.crop_sources)
    )
    sources = SdxlValidationComparisonSources(configuration, crops)
    validate_sdxl_validation_sources(command, sources)
    return sources


def validate_sdxl_validation_workspace_result(
    *,
    command: LocalImageSdxlValidationComparisonCommand,
    sources: SdxlValidationComparisonSources,
    workspace: Path,
    expected_owner_uid: int,
) -> LocalImageSdxlValidationComparisonResult:
    """One read-only evidence closure for replay and Orchestrator publication."""
    try:
        with verified_directory(workspace, expected_owner_uid=expected_owner_uid) as root:
            raw = read_staged_member(
                root,
                "result.json",
                maximum_bytes=256 * 1024,
                expected_owner_uid=expected_owner_uid,
            )
            result = parse_sdxl_validation_result(json.loads(raw))
            validate_sdxl_validation_result(command, sources, result)
            if raw != content_json_bytes(result.model_dump(mode="json")):
                raise ValueError("noncanonical reserved comparison result")
            validate_sdxl_reference_pixel_members(
                root, workspace, result.inputs, owner=expected_owner_uid
            )
            validate_sdxl_pair_output_members(
                root, workspace, result.outputs, expected_owner_uid=expected_owner_uid
            )
            return result
    except (ProviderError, ValueError, TypeError, OSError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def run_sdxl_validation_comparison(
    *,
    command: LocalImageSdxlValidationComparisonCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend_factory: ReferenceBackendFactory = SdxlCannyReferenceDiffusersBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlValidationComparisonResult:
    try:
        command = parse_sdxl_validation_command(command.model_dump(mode="json"))
        if command.created_at > datetime.now(UTC):
            raise ValueError("reserved comparison command is dated in the future")
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if load_sdxl_comparison_command(workspace, workspace / "command.json") != command:
                raise ValueError("reserved invocation differs from staged command")
            sources = read_sdxl_validation_sources(root, command)
            members = validate_sdxl_validation_sources(command, sources)
            originals = {}
            for entry, (_, member) in zip(command.cases, members, strict=True):
                raw = read_staged_member(
                    root,
                    entry.case.staged_member_path,
                    maximum_bytes=member.size_bytes,
                    expected_sha256=entry.case.reference_image.sha256,
                )
                if len(raw) != member.size_bytes:
                    raise ValueError("reserved source size mismatch")
                with Image.open(io.BytesIO(raw)) as image:
                    if (
                        image.format != "PNG"
                        or image.mode not in ("L", "RGB")
                        or image.size != (member.width_px, member.height_px)
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise ValueError("reserved source media mismatch")
                    image.load()
                originals[entry.case.case_id] = raw
            if os.path.lexists(workspace / "result.json"):
                return validate_sdxl_validation_workspace_result(
                    command=command,
                    sources=sources,
                    workspace=workspace,
                    expected_owner_uid=os.geteuid(),
                )
            if any(os.path.lexists(workspace / name) for name in ("outputs", *_PIXEL_DIRECTORIES)):
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
            spatial = sources.configuration.sources.spatial_sources
            if (
                metadata.version("Pillow")
                != sources.configuration.command.initialization.pillow_version
                or read_canny_runtime() != spatial.preparation.runtime
            ):
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            started_at, start = datetime.now(UTC), time.monotonic()
            pixels = prepare_sdxl_reference_pixels(
                root,
                tuple(entry.case for entry in command.cases),
                originals,
                policy=spatial.preparation.policy,
                conditioner=canny_conditioning_canvas_png,
            )
            initializations, traces = pixels.initializations, pixels.traces
            create_sdxl_pair_directories(root, workspace)
            outputs: tuple[SdxlLearnedComparisonOutput, ...] = ()
            runtime: LocalImageRuntime | None = None
            error: SdxlProbeErrorCode | None = None
            try:
                stack = resolve_sdxl_stack(
                    model_store_root,
                    spatial.targets.lora.baseline.model,
                    expected_owner_uid=expected_model_owner_uid,
                )
                controller = resolve_sdxl_canny_controller(
                    model_store_root,
                    sources.configuration.sources.spatial_command.controller,
                    expected_owner_uid=expected_model_owner_uid,
                )
                selected = sdxl_validation_adapter(sources.configuration)
                material = load_sdxl_lora_material(
                    root, selected.manifest, strength=selected.strength
                )
                pair = run_sdxl_pair_inference(
                    root=root,
                    stack=stack,
                    material=material,
                    baseline=spatial.targets.lora.baseline,
                    cases=tuple(entry.case for entry in command.cases),
                    inputs=originals,
                    conditioning_hashes={
                        trace.case_id: trace.conditioning_sha256 for trace in traces
                    },
                    seed=command.seed,
                    budget=command.budget,
                    start=start,
                    gpu_lock=gpu_lock,
                    backend=backend_factory(
                        controller,
                        sources.configuration.sources.spatial_command.control,
                        sources.configuration.command.initialization,
                        initializations,
                    ),
                )
                outputs, runtime, error = pair.outputs, pair.runtime, pair.error_code
            except ProviderError as exc:
                error = (
                    cast(SdxlProbeErrorCode, exc.code)
                    if exc.code in _ERRORS
                    else "SDXL_PROBE_EXEC_FAILED"
                )
            except Exception:
                error = "SDXL_PROBE_EXEC_FAILED"
            value = dict(
                schema_version=sdxl_validation_protocol(command).result_version,
                run_id=command.run_id,
                command_sha256=command.command_sha256,
                configuration_command_sha256=sources.configuration.command.command_sha256,
                case_relation="RESERVED_VALIDATION_NOT_TRAIN_OR_HOLDOUT",
                native_fit_policy="NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0",
                quality_acceptance="NOT_REVIEWED",
                activation_policy="FORBIDDEN",
                training_steps=0,
                holdout_binary_reads=0,
                status="SUCCEEDED" if error is None else "FAILED",
                error_code=error,
                runtime=runtime.model_dump(mode="json") if runtime else None,
                inputs=[trace.model_dump(mode="json") for trace in traces],
                outputs=[output.model_dump(mode="json") for output in outputs],
                started_at=started_at.isoformat().replace("+00:00", "Z"),
                completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                duration_ms=max(1, int((time.monotonic() - start) * 1000)),
                **sdxl_validation_native_result_fields(sources),
            )
            result = sdxl_validation_protocol(command).result_model.model_validate(
                {**value, "result_sha256": content_sha256(value)}
            )
            validate_sdxl_validation_result(command, sources, result)
            validate_contract(
                sdxl_validation_protocol(command).result_contract, result.model_dump(mode="json")
            )
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except (ValueError, TypeError, KeyError, SchemaError, OSError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc


def verify_sdxl_validation_transforms(workspace: Path) -> LocalImageSdxlValidationComparisonResult:
    """CPU-only publication verification under the installed numerical interpreter.

    Canonical admission is the parent Orchestrator's responsibility. This fixed
    adapter recomputes declared transforms but never writes or accesses a model.
    """
    from eom_image_provider.sdxl_lineart_probe import sdxl_publication

    command = load_sdxl_comparison_command(workspace, workspace / "command.json")
    if not isinstance(command, LocalImageSdxlValidationComparisonCommand):
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        sources = read_sdxl_validation_sources(root, command)
        spatial = sources.configuration.sources.spatial_sources
        if (
            metadata.version("Pillow")
            != sources.configuration.command.initialization.pillow_version
            or read_canny_runtime() != spatial.preparation.runtime
        ):
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        result = validate_sdxl_validation_workspace_result(
            command=command, sources=sources, workspace=workspace, expected_owner_uid=os.geteuid()
        )
        traces = {trace.case_id: trace for trace in result.inputs}
        members = validate_sdxl_validation_sources(command, sources)
        for entry, (_, member) in zip(command.cases, members, strict=True):
            case = entry.case
            original = read_staged_member(
                root,
                case.staged_member_path,
                maximum_bytes=member.size_bytes,
                expected_sha256=case.reference_image.sha256,
            )
            canvas = sdxl_canny_native_source_canvas(
                original, width_px=case.reference_width_px, height_px=case.reference_height_px
            )
            trace = traces[case.case_id]
            if _sha(canvas.convert("RGB").tobytes()) != trace.initialization_rgb_sha256:
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
            if _sha(canny_conditioning_canvas_png(canvas, policy=spatial.preparation.policy)) != (
                trace.conditioning_sha256
            ):
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        for output in result.outputs:
            raw = read_staged_member(
                root,
                output.raw_member_path,
                maximum_bytes=output.raw_size_bytes,
                expected_sha256=output.raw_sha256,
            )
            if _sha(sdxl_publication(raw)) != output.sha256:
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        return result
