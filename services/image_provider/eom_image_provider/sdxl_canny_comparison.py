"""Admitted spatial pair execution and terminal replay without transforms or models."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from eom_image_contracts.models import LocalImageRuntime, content_json_bytes, content_sha256
from eom_image_contracts.sdxl_canny_comparison import (
    LocalImageSdxlCannyComparisonCommand,
    LocalImageSdxlCannyComparisonResult,
    SdxlCannyComparisonSources,
    SdxlCannyControlParameters,
    parse_sdxl_canny_comparison_sources,
    validate_sdxl_canny_comparison_result,
)
from eom_image_contracts.sdxl_canny_conditioning import (
    LocalImageSdxlCannyConditioningCommand,
    parse_sdxl_canny_parent,
)
from eom_image_contracts.sdxl_learned_comparison import SdxlLearnedComparisonOutput
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.validation import validate_contract
from jsonschema import ValidationError as SchemaError

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_backend import SdxlCannyDiffusersBackend
from eom_image_provider.sdxl_canny_controller_io import (
    ResolvedSdxlCannyController,
    resolve_sdxl_canny_controller,
)
from eom_image_provider.sdxl_canny_pixels import canny_png_edge_count
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_lineart_probe import SdxlProbeBackend
from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.sdxl_pair_inference import (
    create_sdxl_pair_directories,
    run_sdxl_pair_inference,
)
from eom_image_provider.sdxl_pair_output_validation import validate_sdxl_pair_output_members
from eom_image_provider.sdxl_target_source_io import read_sdxl_target_comparison_metadata
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(SdxlProbeErrorCode))
CannyBackendFactory = Callable[
    [ResolvedSdxlCannyController, SdxlCannyControlParameters], SdxlProbeBackend
]


def read_sdxl_canny_comparison_sources(
    root: int,
    command: LocalImageSdxlCannyComparisonCommand,
) -> SdxlCannyComparisonSources:
    return parse_sdxl_canny_comparison_sources(
        command, read_sdxl_canny_comparison_metadata(root, command)
    )


def read_sdxl_canny_comparison_metadata(
    root: int, command: LocalImageSdxlCannyComparisonCommand
) -> dict[str, bytes]:
    """One bounded metadata reader; numerical successors do not need TRAIN pixels."""
    metadata = {}
    for name, pointer in (
        ("canny-command", command.conditioning_command),
        ("canny-result", command.conditioning_result),
        ("canny-detail-review", command.detail_review),
        ("source-target-result", command.baseline_result),
    ):
        metadata["inputs/" + name + ".json"] = read_staged_member(
            root,
            "inputs/" + name + ".json",
            maximum_bytes=256 * 1024,
            expected_sha256=pointer.sha256,
        )
    preparation = LocalImageSdxlCannyConditioningCommand.model_validate_json(
        metadata["inputs/canny-command.json"]
    )
    parent_raw = read_staged_member(
        root,
        "inputs/parent-command.json",
        maximum_bytes=256 * 1024,
        expected_sha256=preparation.source_command.sha256,
    )
    parent = parse_sdxl_canny_parent(preparation, parent_raw)
    metadata.update(read_sdxl_target_comparison_metadata(root, parent))
    metadata["inputs/parent-command.json"] = parent_raw
    metadata["inputs/canny-own-review-evidence.json"] = read_staged_member(
        root,
        "inputs/canny-own-review-evidence.json",
        maximum_bytes=256 * 1024,
    )
    return metadata


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlCannyComparisonCommand,
    sources: SdxlCannyComparisonSources,
) -> LocalImageSdxlCannyComparisonResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        return None
    try:
        raw = read_staged_member(
            root, "result.json", maximum_bytes=256 * 1024, expected_owner_uid=os.geteuid()
        )
        validate_contract("sdxl-canny-comparison-result", json.loads(raw))
        result = LocalImageSdxlCannyComparisonResult.model_validate_json(raw)
        validate_sdxl_canny_comparison_result(command, sources, result)
        if raw != content_json_bytes(result.model_dump(mode="json")):
            raise ValueError("noncanonical spatial result")
        validate_sdxl_pair_output_members(root, workspace, result.outputs)
        return result
    except (ProviderError, ValueError, TypeError, OSError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def run_sdxl_canny_comparison(
    *,
    command: LocalImageSdxlCannyComparisonCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend_factory: CannyBackendFactory = SdxlCannyDiffusersBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlCannyComparisonResult:
    try:
        command = LocalImageSdxlCannyComparisonCommand.model_validate_json(
            command.model_dump_json()
        )
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if load_sdxl_comparison_command(workspace, workspace / "command.json") != command:
                raise ValueError("spatial invocation differs from staged command")
            sources = read_sdxl_canny_comparison_sources(root, command)
            inputs = {}
            for output in sources.conditionings.outputs:
                pixels = read_staged_member(
                    root,
                    "inputs/canny/" + output.case_id + ".png",
                    maximum_bytes=output.size_bytes,
                    expected_sha256=output.sha256,
                )
                if (
                    len(pixels) != output.size_bytes
                    or canny_png_edge_count(pixels) != output.edge_pixels
                ):
                    raise ValueError("spatial control-map byte/edge-count mismatch")
                inputs[output.case_id] = pixels
            replay = _replay(root, workspace, command, sources)
            if replay is not None:
                return replay
            started_at, start = datetime.now(UTC), time.monotonic()
            create_sdxl_pair_directories(root, workspace)
            outputs: tuple[SdxlLearnedComparisonOutput, ...] = ()
            runtime: LocalImageRuntime | None = None
            error: SdxlProbeErrorCode | None = None
            try:
                stack = resolve_sdxl_stack(
                    model_store_root,
                    sources.targets.lora.baseline.model,
                    expected_owner_uid=expected_model_owner_uid,
                )
                controller = resolve_sdxl_canny_controller(
                    model_store_root,
                    command.controller,
                    expected_owner_uid=expected_model_owner_uid,
                )
                material = load_sdxl_lora_material(
                    root,
                    sources.targets.lora.manifest,
                    strength=sources.targets.evaluation.evaluation.adapter_strength,
                )
                pair = run_sdxl_pair_inference(
                    root=root,
                    stack=stack,
                    material=material,
                    baseline=sources.targets.lora.baseline,
                    cases=tuple(entry.case for entry in sources.parent.cases),
                    inputs=inputs,
                    conditioning_hashes={
                        out.case_id: out.sha256 for out in sources.conditionings.outputs
                    },
                    seed=sources.parent.seed,
                    budget=command.budget,
                    start=start,
                    gpu_lock=gpu_lock,
                    backend=backend_factory(controller, command.control),
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
                schema_version="local-image-sdxl-canny-comparison-result/1.0",
                run_id=command.run_id,
                command_sha256=command.command_sha256,
                preparation_result_sha256=sources.conditionings.result_sha256,
                detail_review_sha256=sources.review.review_sha256,
                baseline_result_sha256=sources.baseline.result_sha256,
                base_model=sources.targets.lora.baseline.model.model_dump(mode="json"),
                controller=command.controller.model_dump(mode="json"),
                control=command.control.model_dump(mode="json"),
                case_relation=command.case_relation,
                quality_acceptance="NOT_REVIEWED",
                activation_policy="FORBIDDEN",
                status="SUCCEEDED" if error is None else "FAILED",
                error_code=error,
                runtime=runtime.model_dump(mode="json") if runtime else None,
                outputs=[out.model_dump(mode="json") for out in outputs],
                started_at=started_at.isoformat().replace("+00:00", "Z"),
                completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                duration_ms=max(1, int((time.monotonic() - start) * 1000)),
            )
            value["result_sha256"] = content_sha256(value)
            validate_contract("sdxl-canny-comparison-result", value)
            result = LocalImageSdxlCannyComparisonResult.model_validate(value)
            validate_sdxl_canny_comparison_result(command, sources, result)
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except (ProviderError, ValueError, KeyError, TypeError, OSError, SchemaError) as exc:
        if isinstance(exc, ProviderError):
            raise
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
