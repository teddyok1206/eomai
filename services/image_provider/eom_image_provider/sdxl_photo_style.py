"""One frozen licensed-photo comparison using the existing isolated paired lifecycle."""

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

from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.sdxl_native_canny_reference import sdxl_reference_adapter
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStyleControlWindowPlan,
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
    photo_style_control_parameters,
    photo_style_region_reviews_sha256,
    photo_style_version,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleCommand,
    LocalImageSdxlPhotoStyleResult,
    SdxlPhotoStyleExecutionSources,
    parse_photo_style_command,
    parse_photo_style_result,
    validate_photo_style_result,
)
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
from eom_image_provider.sdxl_canny_reference_backend import SdxlCannyReferenceDiffusersBackend
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.sdxl_pair_inference import (
    SdxlPairInferenceEvidence,
    create_sdxl_pair_directories,
    run_sdxl_pair_inference,
)
from eom_image_provider.sdxl_pair_output_validation import validate_sdxl_pair_output_members
from eom_image_provider.sdxl_photo_conditioning import photo_style_conditioner
from eom_image_provider.sdxl_photo_style_sources import read_sdxl_photo_style_sources
from eom_image_provider.sdxl_reference_pixels import (
    REFERENCE_PIXEL_DIRECTORIES,
    prepare_sdxl_reference_pixels,
    sdxl_reference_initializer,
    validate_sdxl_reference_pixel_members,
)
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(SdxlProbeErrorCode))


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read_originals(root: int, sources: SdxlPhotoStyleExecutionSources) -> dict[str, bytes]:
    originals = {}
    for entry, source in zip(sources.plan.cases, sources.photos, strict=True):
        member = source.bundle.normalized_member
        raw = read_staged_member(
            root,
            entry.case.staged_member_path,
            maximum_bytes=member.size_bytes,
            expected_sha256=entry.case.reference_image.sha256,
        )
        if len(raw) != member.size_bytes:
            raise ValueError("photo input size mismatch")
        with Image.open(io.BytesIO(raw)) as image:
            if (
                image.format != "PNG"
                or image.mode != member.mode
                or image.size != (member.width_px, member.height_px)
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ValueError("photo input media mismatch")
            image.load()
        originals[entry.case.case_id] = raw
    return originals


def validate_sdxl_photo_style_workspace_result(
    *,
    command: LocalImageSdxlPhotoStyleCommand,
    sources: SdxlPhotoStyleExecutionSources,
    workspace: Path,
    expected_owner_uid: int,
) -> LocalImageSdxlPhotoStyleResult:
    try:
        with verified_directory(workspace, expected_owner_uid=expected_owner_uid) as root:
            raw = read_staged_member(
                root, "result.json", maximum_bytes=256 * 1024, expected_owner_uid=expected_owner_uid
            )
            result = parse_photo_style_result(json.loads(raw))
            validate_photo_style_result(command, sources, result)
            if raw != content_json_bytes(result.model_dump(mode="json")):
                raise ValueError("noncanonical photo result")
            validate_sdxl_reference_pixel_members(
                root, workspace, result.inputs, owner=expected_owner_uid
            )
            validate_sdxl_pair_output_members(
                root, workspace, result.outputs, expected_owner_uid=expected_owner_uid
            )
            return result
    except (ProviderError, ValueError, TypeError, OSError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def run_sdxl_photo_style(
    *,
    command: LocalImageSdxlPhotoStyleCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend_factory: ReferenceBackendFactory = SdxlCannyReferenceDiffusersBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlPhotoStyleResult:
    try:
        command = parse_photo_style_command(command.model_dump(mode="json"))
        if command.created_at > datetime.now(UTC):
            raise ValueError("photo command is dated in the future")
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if load_sdxl_comparison_command(workspace, workspace / "command.json") != command:
                raise ValueError("photo invocation differs from staged command")
            sources = read_sdxl_photo_style_sources(root, command)
            originals = _read_originals(root, sources)
            if os.path.lexists(workspace / "result.json"):
                return validate_sdxl_photo_style_workspace_result(
                    command=command,
                    sources=sources,
                    workspace=workspace,
                    expected_owner_uid=os.geteuid(),
                )
            if any(
                os.path.lexists(workspace / name)
                for name in ("outputs", *REFERENCE_PIXEL_DIRECTORIES)
            ):
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
            spatial = sources.configuration_sources.spatial_sources
            plan = sources.plan
            control = photo_style_control_parameters(
                plan, sources.configuration_sources.spatial_command.control
            )
            if (
                metadata.version("Pillow") != plan.initialization.pillow_version
                or read_canny_runtime() != spatial.preparation.runtime
            ):
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            started_at, start = datetime.now(UTC), time.monotonic()
            pixels = prepare_sdxl_reference_pixels(
                root,
                tuple(row.case for row in plan.cases),
                originals,
                policy=spatial.preparation.policy,
                conditioner=photo_style_conditioner(plan, canny=canny_conditioning_canvas_png),
                initialization=plan.initialization,
            )
            create_sdxl_pair_directories(root, workspace)
            try:
                stack = resolve_sdxl_stack(
                    model_store_root,
                    spatial.targets.lora.baseline.model,
                    expected_owner_uid=expected_model_owner_uid,
                )
                controller = resolve_sdxl_canny_controller(
                    model_store_root,
                    sources.configuration_sources.spatial_command.controller,
                    expected_owner_uid=expected_model_owner_uid,
                )
                selected = sdxl_reference_adapter(sources.configuration_sources)
                material = load_sdxl_lora_material(
                    root, selected.manifest, strength=selected.strength
                )
                pair = run_sdxl_pair_inference(
                    root=root,
                    stack=stack,
                    material=material,
                    baseline=spatial.targets.lora.baseline,
                    cases=tuple(row.case for row in plan.cases),
                    inputs=originals,
                    conditioning_hashes={
                        row.case_id: row.conditioning_sha256 for row in pixels.traces
                    },
                    seed=plan.seed,
                    budget=plan.budget,
                    start=start,
                    gpu_lock=gpu_lock,
                    backend=backend_factory(
                        controller,
                        control,
                        plan.initialization,
                        pixels.initializations,
                    ),
                )
            except ProviderError as exc:
                code = (
                    cast(SdxlProbeErrorCode, exc.code)
                    if exc.code in _ERRORS
                    else "SDXL_PROBE_EXEC_FAILED"
                )
                pair = SdxlPairInferenceEvidence((), None, code)
            except Exception:
                pair = SdxlPairInferenceEvidence((), None, "SDXL_PROBE_EXEC_FAILED")
            value = dict(
                schema_version="local-image-sdxl-photo-style-result/"
                + photo_style_version(command.schema_version),
                run_id=command.run_id,
                command_sha256=command.command_sha256,
                plan_sha256=plan.plan_sha256,
                configuration_command_sha256=sources.configuration.command_sha256,
                native_evaluation_command_sha256=sources.configuration_sources.evaluation.command_sha256,
                native_adapter_manifest_sha256=sources.configuration_sources.native.manifest.manifest_sha256,
                case_relation="LICENSED_PHOTO_REFERENCES_NOT_CORPUS_HOLDOUT",
                native_fit_policy="NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0",
                initialization=plan.initialization.model_dump(mode="json"),
                quality_acceptance="NOT_REVIEWED",
                activation_policy="FORBIDDEN",
                training_steps=0,
                holdout_binary_reads=0,
                status="SUCCEEDED" if pair.error_code is None else "FAILED",
                error_code=pair.error_code,
                runtime=pair.runtime.model_dump(mode="json") if pair.runtime else None,
                inputs=[row.model_dump(mode="json") for row in pixels.traces],
                outputs=[row.model_dump(mode="json") for row in pair.outputs],
                started_at=started_at.isoformat().replace("+00:00", "Z"),
                completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                duration_ms=max(1, int((time.monotonic() - start) * 1000)),
            )
            if isinstance(plan, LocalImageSdxlPhotoStyleControlWindowPlan):
                value["control_window"] = plan.control_window.model_dump(mode="json")
            if isinstance(plan, LocalImageSdxlPhotoStyleRetainedRegionPlan):
                value["control"] = plan.control.model_dump(mode="json")
                value["region_reviews_sha256"] = photo_style_region_reviews_sha256(plan)
            result = parse_photo_style_result({**value, "result_sha256": content_sha256(value)})
            validate_photo_style_result(command, sources, result)
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except (ValueError, TypeError, KeyError, SchemaError, OSError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc


def verify_sdxl_photo_style_transforms(workspace: Path) -> LocalImageSdxlPhotoStyleResult:
    """CPU-only recomputation under the pinned numerical interpreter; never writes."""
    from eom_image_provider.sdxl_lineart_probe import sdxl_publication

    command = load_sdxl_comparison_command(workspace, workspace / "command.json")
    if not isinstance(command, LocalImageSdxlPhotoStyleCommand):
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        sources = read_sdxl_photo_style_sources(root, command)
        spatial = sources.configuration_sources.spatial_sources
        if (
            metadata.version("Pillow") != sources.plan.initialization.pillow_version
            or read_canny_runtime() != spatial.preparation.runtime
        ):
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        result = validate_sdxl_photo_style_workspace_result(
            command=command,
            sources=sources,
            workspace=workspace,
            expected_owner_uid=os.geteuid(),
        )
        traces = {row.case_id: row for row in result.inputs}
        originals = _read_originals(root, sources)
        conditioner = photo_style_conditioner(sources.plan, canny=canny_conditioning_canvas_png)
        for entry in sources.plan.cases:
            case = entry.case
            original = originals[case.case_id]
            canvas = sdxl_canny_native_source_canvas(
                original, width_px=case.reference_width_px, height_px=case.reference_height_px
            )
            if (
                _sha(
                    sdxl_reference_initializer(
                        canvas, initialization=sources.plan.initialization
                    ).tobytes()
                )
                != traces[case.case_id].initialization_rgb_sha256
                or _sha(conditioner(case, canvas, policy=spatial.preparation.policy))
                != traces[case.case_id].conditioning_sha256
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
