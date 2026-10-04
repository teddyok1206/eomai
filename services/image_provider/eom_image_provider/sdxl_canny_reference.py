"""Source-initialized spatial successor with transform/model-free terminal replay."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import cast, get_args

from eom_image_contracts.models import LocalImageRuntime, content_json_bytes, content_sha256
from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    LocalImageSdxlCannyReferenceResult,
    SdxlCannyReferenceInitialization,
    SdxlCannyReferenceSources,
    SdxlCannyReferenceTrace,
    parse_sdxl_canny_reference_predecessors,
    validate_sdxl_canny_reference_result,
    validate_sdxl_canny_reference_sources,
)
from eom_image_contracts.sdxl_learned_comparison import SdxlLearnedComparisonOutput
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.validation import validate_contract
from jsonschema import ValidationError as SchemaError
from PIL import Image

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_comparison import read_sdxl_canny_comparison_sources
from eom_image_provider.sdxl_canny_controller_io import (
    ResolvedSdxlCannyController,
    resolve_sdxl_canny_controller,
)
from eom_image_provider.sdxl_canny_pixels import canny_png_edge_count, sdxl_canny_source_canvas
from eom_image_provider.sdxl_canny_reference_backend import (
    SdxlCannyReferenceDiffusersBackend,
    SdxlCannyReferencePixels,
)
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_lineart_probe import SdxlProbeBackend
from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.sdxl_pair_inference import (
    create_sdxl_pair_directories,
    run_sdxl_pair_inference,
)
from eom_image_provider.sdxl_pair_output_validation import validate_sdxl_pair_output_members
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    write_staged_member,
)

ReferenceBackendFactory = Callable[
    [
        ResolvedSdxlCannyController,
        SdxlCannyControlParameters,
        SdxlCannyReferenceInitialization,
        Mapping[str, SdxlCannyReferencePixels],
    ],
    SdxlProbeBackend,
]
_ERRORS = frozenset(get_args(SdxlProbeErrorCode))


def read_sdxl_canny_reference_sources(
    root: int, command: LocalImageSdxlCannyReferenceCommand
) -> SdxlCannyReferenceSources:
    predecessor = parse_sdxl_canny_reference_predecessors(
        command,
        read_staged_member(
            root,
            "inputs/spatial-command.json",
            maximum_bytes=256 * 1024,
            expected_sha256=command.spatial_command.sha256,
        ),
        read_staged_member(
            root,
            "inputs/spatial-result.json",
            maximum_bytes=256 * 1024,
            expected_sha256=command.spatial_result.sha256,
        ),
    )
    sources = SdxlCannyReferenceSources(
        *predecessor, read_sdxl_canny_comparison_sources(root, predecessor[0])
    )
    validate_sdxl_canny_reference_sources(command, sources)
    return sources


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlCannyReferenceCommand,
    sources: SdxlCannyReferenceSources,
) -> LocalImageSdxlCannyReferenceResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        return None
    try:
        raw = read_staged_member(
            root, "result.json", maximum_bytes=256 * 1024, expected_owner_uid=os.geteuid()
        )
        validate_contract("sdxl-canny-reference-result", json.loads(raw))
        result = LocalImageSdxlCannyReferenceResult.model_validate_json(raw)
        validate_sdxl_canny_reference_result(command, sources, result)
        if raw != content_json_bytes(result.model_dump(mode="json")):
            raise ValueError("noncanonical reference result")
        validate_sdxl_pair_output_members(root, workspace, result.outputs)
        return result
    except (ProviderError, ValueError, TypeError, OSError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def run_sdxl_canny_reference(
    *,
    command: LocalImageSdxlCannyReferenceCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend_factory: ReferenceBackendFactory = SdxlCannyReferenceDiffusersBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlCannyReferenceResult:
    try:
        command = LocalImageSdxlCannyReferenceCommand.model_validate_json(command.model_dump_json())
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if load_sdxl_comparison_command(workspace, workspace / "command.json") != command:
                raise ValueError("reference invocation differs from staged command")
            sources = read_sdxl_canny_reference_sources(root, command)
            spatial = sources.spatial_sources
            targets = {target.sample_id: target for target in spatial.targets.targets}
            maps = {output.case_id: output for output in spatial.conditionings.outputs}
            inputs, controls = {}, {}
            for entry in spatial.parent.cases:
                case, output = entry.case, maps[entry.case.case_id]
                source = read_staged_member(
                    root,
                    case.staged_member_path,
                    maximum_bytes=targets[entry.sample_id].size_bytes,
                    expected_sha256=case.reference_image.sha256,
                )
                with Image.open(io.BytesIO(source)) as image:
                    if (
                        image.format != "PNG"
                        or image.size != (768, 512)
                        or image.mode not in ("L", "RGB")
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise ValueError("reference source media mismatch")
                    image.load()
                control = read_staged_member(
                    root,
                    "inputs/canny/" + case.case_id + ".png",
                    maximum_bytes=output.size_bytes,
                    expected_sha256=output.sha256,
                )
                if (
                    len(source) != targets[entry.sample_id].size_bytes
                    or len(control) != output.size_bytes
                    or canny_png_edge_count(control) != output.edge_pixels
                ):
                    raise ValueError("reference source/control size or count mismatch")
                inputs[case.case_id], controls[case.case_id] = source, control
            replay = _replay(root, workspace, command, sources)
            if replay is not None:
                return replay
            if metadata.version("Pillow") != command.initialization.pillow_version:
                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
            started_at, start = datetime.now(UTC), time.monotonic()
            initializations, traces = {}, []
            for entry in spatial.parent.cases:
                case = entry.case
                rgb = (
                    sdxl_canny_source_canvas(
                        inputs[case.case_id], policy=spatial.preparation.policy
                    )
                    .convert("RGB")
                    .tobytes()
                )
                initializations[case.reference_image.sha256] = SdxlCannyReferencePixels(
                    rgb, controls[case.case_id]
                )
                traces.append(
                    SdxlCannyReferenceTrace(
                        case_id=case.case_id,
                        source_sha256=case.reference_image.sha256,
                        conditioning_sha256=maps[case.case_id].sha256,
                        initialization_rgb_sha256="sha256:" + hashlib.sha256(rgb).hexdigest(),
                    )
                )
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
                    sources.spatial_command.controller,
                    expected_owner_uid=expected_model_owner_uid,
                )
                material = load_sdxl_lora_material(
                    root,
                    spatial.targets.lora.manifest,
                    strength=spatial.targets.evaluation.evaluation.adapter_strength,
                )
                pair = run_sdxl_pair_inference(
                    root=root,
                    stack=stack,
                    material=material,
                    baseline=spatial.targets.lora.baseline,
                    cases=tuple(entry.case for entry in spatial.parent.cases),
                    inputs=inputs,
                    conditioning_hashes={key: row.sha256 for key, row in maps.items()},
                    seed=spatial.parent.seed,
                    budget=command.budget,
                    start=start,
                    gpu_lock=gpu_lock,
                    backend=backend_factory(
                        controller,
                        sources.spatial_command.control,
                        command.initialization,
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
                schema_version="local-image-sdxl-canny-reference-result/1.0",
                run_id=command.run_id,
                command_sha256=command.command_sha256,
                spatial_command_sha256=sources.spatial_command.command_sha256,
                spatial_result_sha256=sources.spatial_result.result_sha256,
                initialization=command.initialization.model_dump(mode="json"),
                inputs=[row.model_dump(mode="json") for row in traces],
                quality_acceptance="NOT_REVIEWED",
                activation_policy="FORBIDDEN",
                status="SUCCEEDED" if error is None else "FAILED",
                error_code=error,
                runtime=runtime.model_dump(mode="json") if runtime else None,
                outputs=[row.model_dump(mode="json") for row in outputs],
                started_at=started_at.isoformat().replace("+00:00", "Z"),
                completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                duration_ms=max(1, int((time.monotonic() - start) * 1000)),
            )
            result = LocalImageSdxlCannyReferenceResult.model_validate(
                {**value, "result_sha256": content_sha256(value)}
            )
            validate_sdxl_canny_reference_result(command, sources, result)
            validate_contract("sdxl-canny-reference-result", result.model_dump(mode="json"))
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except (ValueError, TypeError, KeyError, SchemaError, OSError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
