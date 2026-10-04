"""Matched BASE/LORA over pinned prepared target pixels; never changes the training set."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from eom_image_contracts.models import LocalImageRuntime, content_json_bytes, content_sha256
from eom_image_contracts.sdxl_learned_comparison import SdxlLearnedComparisonOutput
from eom_image_contracts.sdxl_lineart_probe import (
    SdxlLineartProbeConditioning,
    SdxlProbeErrorCode,
)
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    LocalImageSdxlTargetComparisonResult,
    SdxlTargetComparisonSources,
    validate_sdxl_target_comparison_result,
)
from eom_image_contracts.validation import validate_contract
from jsonschema import ValidationError as SchemaError

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_image_provider.sdxl_lineart_probe import (
    MAX_PNG_BYTES,
    SdxlProbeBackend,
    lineart_conditioning,
    sdxl_publication,
)
from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.sdxl_pair_inference import (
    create_sdxl_pair_directories,
    run_sdxl_pair_inference,
)
from eom_image_provider.sdxl_target_source_io import read_sdxl_target_comparison_sources
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(SdxlProbeErrorCode))


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlTargetComparisonCommand,
    sources: SdxlTargetComparisonSources,
    inputs: dict[str, bytes],
) -> LocalImageSdxlTargetComparisonResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        return None
    try:
        raw = read_staged_member(
            root, "result.json", maximum_bytes=128 * 1024, expected_owner_uid=os.geteuid()
        )
        validate_contract("sdxl-target-comparison-result", json.loads(raw))
        result = LocalImageSdxlTargetComparisonResult.model_validate_json(raw)
        validate_sdxl_target_comparison_result(command, sources, result)
        if raw != content_json_bytes(result.model_dump(mode="json")):
            raise ValueError("noncanonical target comparison result")
        cases = {entry.case.case_id: entry.case for entry in command.cases}
        for conditioning in result.conditionings:
            pixels = read_staged_member(
                root,
                conditioning.member_path,
                maximum_bytes=MAX_PNG_BYTES,
                expected_sha256=conditioning.sha256,
                expected_owner_uid=os.geteuid(),
            )
            case = cases[conditioning.case_id]
            if pixels != lineart_conditioning(
                inputs[case.case_id],
                expected_size=(case.reference_width_px, case.reference_height_px),
            ):
                raise ValueError("target conditioning differs from declared transform")
        for output in result.outputs:
            final = read_staged_member(
                root,
                output.member_path,
                maximum_bytes=output.size_bytes,
                expected_sha256=output.sha256,
                expected_owner_uid=os.geteuid(),
            )
            raster = read_staged_member(
                root,
                output.raw_member_path,
                maximum_bytes=output.raw_size_bytes,
                expected_sha256=output.raw_sha256,
                expected_owner_uid=os.geteuid(),
            )
            if (
                len(final) != output.size_bytes
                or len(raster) != output.raw_size_bytes
                or final != sdxl_publication(raster)
            ):
                raise ValueError("target comparison output size/publication differs")
        return result
    except (ProviderError, ValueError, TypeError, OSError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def run_sdxl_target_comparison(
    *,
    command: LocalImageSdxlTargetComparisonCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend: SdxlProbeBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlTargetComparisonResult:
    try:
        command = LocalImageSdxlTargetComparisonCommand.model_validate_json(
            command.model_dump_json()
        )
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if load_sdxl_comparison_command(workspace, workspace / "command.json") != command:
                raise ValueError("staged target comparison differs from invocation")
            sources = read_sdxl_target_comparison_sources(root, command)
            cases = tuple(entry.case for entry in command.cases)
            originals = {
                case.case_id: read_staged_member(
                    root,
                    case.staged_member_path,
                    maximum_bytes=MAX_PNG_BYTES,
                    expected_sha256=case.reference_image.sha256,
                )
                for case in cases
            }
            replay = _replay(root, workspace, command, sources, originals)
            if replay is not None:
                return replay
            # Pixel transform is a declared first-use boundary, never an implicit training rewrite.
            inputs = {
                case.case_id: lineart_conditioning(
                    originals[case.case_id], expected_size=(768, 512)
                )
                for case in cases
            }
            started_at, start = datetime.now(UTC), time.monotonic()
            create_sdxl_pair_directories(root, workspace)
            with verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()) as out:
                create_staged_directory(out, "conditioning")
            conditionings = []
            for case in cases:
                path = "outputs/conditioning/" + case.case_id + ".png"
                write_staged_member(root, path, inputs[case.case_id])
                conditionings.append(
                    SdxlLineartProbeConditioning(
                        case_id=case.case_id,
                        member_path=path,
                        sha256=_sha(inputs[case.case_id]),
                        width_px=832,
                        height_px=512,
                    )
                )
            produced: tuple[SdxlLearnedComparisonOutput, ...] = ()
            runtime: LocalImageRuntime | None = None
            error: SdxlProbeErrorCode | None = None
            try:
                stack = resolve_sdxl_stack(
                    model_store_root,
                    sources.lora.baseline.model,
                    expected_owner_uid=expected_model_owner_uid,
                )
                material = load_sdxl_lora_material(
                    root,
                    sources.lora.manifest,
                    strength=sources.evaluation.evaluation.adapter_strength,
                )
                pair = run_sdxl_pair_inference(
                    root=root,
                    stack=stack,
                    material=material,
                    baseline=sources.lora.baseline,
                    cases=cases,
                    inputs=inputs,
                    conditioning_hashes={item.case_id: item.sha256 for item in conditionings},
                    seed=command.seed,
                    budget=command.budget,
                    start=start,
                    gpu_lock=gpu_lock,
                    backend=backend,
                )
                produced, runtime, error = pair.outputs, pair.runtime, pair.error_code
            except ProviderError as exc:
                error = (
                    cast(SdxlProbeErrorCode, exc.code)
                    if exc.code in _ERRORS
                    else "SDXL_PROBE_EXEC_FAILED"
                )
            except Exception:
                error = "SDXL_PROBE_EXEC_FAILED"
            value = {
                "schema_version": "local-image-sdxl-target-comparison-result/1.0",
                "run_id": command.run_id,
                "command_sha256": command.command_sha256,
                "baseline_command_sha256": sources.lora.baseline.command_sha256,
                "training_result_sha256": sources.lora.training_result.result_sha256,
                "model": sources.lora.baseline.model.model_dump(mode="json"),
                "case_relation": command.case_relation,
                "conditioning_policy": command.conditioning_policy,
                "status": "SUCCEEDED" if error is None else "FAILED",
                "error_code": error,
                "runtime": runtime.model_dump(mode="json") if runtime else None,
                "conditionings": [entry.model_dump(mode="json") for entry in conditionings],
                "outputs": [out.model_dump(mode="json") for out in produced],
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "duration_ms": max(1, int((time.monotonic() - start) * 1000)),
            }
            value["result_sha256"] = content_sha256(value)
            validate_contract("sdxl-target-comparison-result", value)
            result = LocalImageSdxlTargetComparisonResult.model_validate(value)
            validate_sdxl_target_comparison_result(command, sources, result)
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except (ProviderError, ValueError, KeyError, TypeError, OSError, SchemaError) as exc:
        if isinstance(exc, ProviderError):
            raise
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
