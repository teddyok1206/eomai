"""CPU-only, replayable input preparation; no model store or GPU argument exists."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.sdxl_canny_conditioning import (
    CannyErrorCode,
    LocalImageSdxlCannyConditioningCommand,
    LocalImageSdxlCannyConditioningResult,
    SdxlCannyOutput,
    parse_sdxl_canny_parent,
    validate_sdxl_canny_result,
    validate_sdxl_canny_sources,
)
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    SdxlTargetComparisonSources,
)
from eom_image_contracts.validation import validate_contract
from jsonschema import ValidationError as SchemaError

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_pixels import (
    CannyPixels,
    canny_conditioning_png,
    canny_png_edge_count,
    opencv_canny_pixels,
    read_canny_runtime,
)
from eom_image_provider.sdxl_target_source_io import read_sdxl_target_comparison_sources
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(CannyErrorCode))


def load_sdxl_canny_command(
    workspace: Path, command_path: Path
) -> LocalImageSdxlCannyConditioningCommand:
    if command_path != workspace / "command.json":
        raise ProviderError("SDXL_CANNY_INPUT_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(root, "command.json", maximum_bytes=128 * 1024)
        validate_contract("sdxl-canny-conditioning-command", json.loads(raw))
        command = LocalImageSdxlCannyConditioningCommand.model_validate_json(raw)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise ValueError("noncanonical Canny command")
        return command
    except (ValueError, TypeError, OSError, SchemaError, ProviderError) as exc:
        raise ProviderError("SDXL_CANNY_INPUT_INVALID") from exc


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlCannyConditioningCommand,
    parent: LocalImageSdxlTargetComparisonCommand,
    sources: SdxlTargetComparisonSources,
) -> LocalImageSdxlCannyConditioningResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_CANNY_OUTPUT_INVALID")
        return None
    try:
        raw = read_staged_member(
            root, "result.json", maximum_bytes=128 * 1024, expected_owner_uid=os.geteuid()
        )
        validate_contract("sdxl-canny-conditioning-result", json.loads(raw))
        result = LocalImageSdxlCannyConditioningResult.model_validate_json(raw)
        validate_sdxl_canny_result(command, parent, sources, result)
        if raw != content_json_bytes(result.model_dump(mode="json")):
            raise ValueError("noncanonical Canny receipt")
        for output in result.outputs:
            pixels = read_staged_member(
                root,
                output.member_path,
                maximum_bytes=output.size_bytes,
                expected_sha256=output.sha256,
                expected_owner_uid=os.geteuid(),
            )
            if (
                len(pixels) != output.size_bytes
                or canny_png_edge_count(pixels) != output.edge_pixels
            ):
                raise ValueError("Canny output size/pixels differ from receipt")
        with verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()) as out:
            if set(os.listdir(out)) != {"conditioning"}:
                raise ValueError("unreceipted Canny output directory")
        with verified_directory(
            workspace / "outputs/conditioning", expected_owner_uid=os.geteuid()
        ) as out:
            if set(os.listdir(out)) != {
                output.member_path.rsplit("/", 1)[1] for output in result.outputs
            }:
                raise ValueError("unreceipted Canny output member")
        return result
    except (ValueError, TypeError, OSError, SchemaError, ProviderError) as exc:
        raise ProviderError("SDXL_CANNY_OUTPUT_INVALID") from exc


def run_sdxl_canny_conditioning(
    *,
    command: LocalImageSdxlCannyConditioningCommand,
    workspace: Path,
    extractor: CannyPixels = opencv_canny_pixels,
) -> LocalImageSdxlCannyConditioningResult:
    try:
        command = LocalImageSdxlCannyConditioningCommand.model_validate_json(
            command.model_dump_json()
        )
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if load_sdxl_canny_command(workspace, workspace / "command.json") != command:
                raise ValueError("invoked Canny command differs from staged command")
            raw = read_staged_member(
                root,
                "inputs/parent-command.json",
                maximum_bytes=256 * 1024,
                expected_sha256=command.source_command.sha256,
            )
            parent = parse_sdxl_canny_parent(command, raw)
            sources = read_sdxl_target_comparison_sources(root, parent)
            validate_sdxl_canny_sources(command, parent, sources)
            runtime = read_canny_runtime()
            if runtime != command.runtime:
                raise ProviderError("SDXL_CANNY_RUNTIME_INVALID")
            targets = {target.sample_id: target for target in sources.targets}
            inputs = {}
            for entry in parent.cases:
                size = targets[entry.sample_id].size_bytes
                if not 0 < size <= command.budget.maximum_input_png_bytes:
                    raise ValueError("Canny source size exceeds budget")
                pixels = read_staged_member(
                    root,
                    entry.case.staged_member_path,
                    maximum_bytes=size,
                    expected_sha256=entry.case.reference_image.sha256,
                )
                if len(pixels) != size:
                    raise ValueError("Canny source size mismatch")
                inputs[entry.case.case_id] = pixels
            replay = _replay(root, workspace, command, parent, sources)
            if replay is not None:
                return replay
            started_at, start = datetime.now(UTC), time.monotonic()
            create_staged_directory(root, "outputs")
            with verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()) as out:
                create_staged_directory(out, "conditioning")
            produced = []
            error: CannyErrorCode | None = None
            try:
                for entry in parent.cases:
                    if (time.monotonic() - start) * 1000 > command.budget.maximum_duration_ms:
                        raise ProviderError("SDXL_CANNY_BUDGET_EXCEEDED")
                    pixels = canny_conditioning_png(
                        inputs[entry.case.case_id], policy=command.policy, extractor=extractor
                    )
                    if (time.monotonic() - start) * 1000 > command.budget.maximum_duration_ms:
                        raise ProviderError("SDXL_CANNY_BUDGET_EXCEEDED")
                    output = SdxlCannyOutput(
                        case_id=entry.case.case_id,
                        source=entry.case.reference_image,
                        member_path="outputs/conditioning/" + entry.case.case_id + ".png",
                        sha256="sha256:" + hashlib.sha256(pixels).hexdigest(),
                        size_bytes=len(pixels),
                        edge_pixels=canny_png_edge_count(pixels),
                    )
                    write_staged_member(root, output.member_path, pixels)
                    produced.append(output)
            except Exception as exc:
                error = (
                    cast(CannyErrorCode, exc.code)
                    if isinstance(exc, ProviderError) and exc.code in _ERRORS
                    else "SDXL_CANNY_EXEC_FAILED"
                )
            value = dict(
                schema_version="local-image-sdxl-canny-conditioning-result/1.0",
                run_id=command.run_id,
                command_sha256=command.command_sha256,
                parent_command_content_sha256=parent.command_sha256,
                policy_sha256=command.policy_sha256,
                status="SUCCEEDED" if error is None else "FAILED",
                error_code=error,
                case_relation=command.case_relation,
                preparation_state="UNREVIEWED_CANNY_INPUTS",
                activation_policy="FORBIDDEN",
                runtime=runtime.model_dump(mode="json"),
                outputs=[output.model_dump(mode="json") for output in produced],
                model_executions=0,
                training_steps=0,
                started_at=started_at.isoformat().replace("+00:00", "Z"),
                completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                duration_ms=max(1, int((time.monotonic() - start) * 1000)),
            )
            result = LocalImageSdxlCannyConditioningResult.model_validate(
                {**value, "result_sha256": content_sha256(value)}
            )
            validate_sdxl_canny_result(command, parent, sources, result)
            validate_contract("sdxl-canny-conditioning-result", result.model_dump(mode="json"))
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except ProviderError as exc:
        if exc.code in {
            "SDXL_CANNY_INPUT_INVALID",
            "SDXL_CANNY_OUTPUT_INVALID",
            "SDXL_CANNY_RUNTIME_INVALID",
        }:
            raise
        raise ProviderError("SDXL_CANNY_INPUT_INVALID") from exc
    except (ValueError, TypeError, OSError, KeyError, SchemaError) as exc:
        raise ProviderError("SDXL_CANNY_INPUT_INVALID") from exc
