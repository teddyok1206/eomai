"""Fixed BASE/LORA comparison using receipt-owned learned conditioning and original prompts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from eom_image_contracts import (
    LocalImageRuntime,
    LocalImageSdxlLearnedComparisonCommand,
    LocalImageSdxlLearnedComparisonResult,
    LocalImageSdxlLineartPromptPolicy,
    LocalImageSdxlLoraEvaluationCommand,
    SdxlLearnedComparisonOutput,
    SdxlLearnedComparisonSources,
    content_json_bytes,
    content_sha256,
    parse_sdxl_learned_comparison_sources,
    select_sdxl_learned_cases,
    validate_contract,
    validate_sdxl_learned_comparison_result,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from jsonschema import ValidationError as JsonSchemaValidationError
from PIL import Image

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_lineart_probe import SdxlProbeBackend, sdxl_publication
from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
from eom_image_provider.sdxl_model_resolution import resolve_sdxl_stack
from eom_image_provider.sdxl_pair_inference import (
    create_sdxl_pair_directories,
    run_sdxl_pair_inference,
)
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(SdxlProbeErrorCode))


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def load_sdxl_learned_comparison_command(
    workspace: Path, command_path: Path
) -> LocalImageSdxlLearnedComparisonCommand:
    if command_path != workspace / "command.json":
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(root, "command.json", maximum_bytes=128 * 1024)
        value = json.loads(raw)
        validate_contract("sdxl-learned-comparison-command", value)
        command = LocalImageSdxlLearnedComparisonCommand.model_validate(value)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise ValueError("noncanonical learned comparison command")
        return command
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc


def _sources(
    root: int, command: LocalImageSdxlLearnedComparisonCommand
) -> SdxlLearnedComparisonSources:
    metadata = {
        name: read_staged_member(
            root,
            "inputs/" + name + ".json",
            maximum_bytes=256 * 1024,
            expected_sha256=pointer.sha256,
        )
        for name, pointer in (
            ("baseline-command", command.baseline_command),
            ("extraction-command", command.extraction_command),
            ("extraction-result", command.extraction_result),
            ("lora-evaluation-command", command.lora_evaluation_command),
        )
    }
    evaluation = LocalImageSdxlLoraEvaluationCommand.model_validate_json(
        metadata["lora-evaluation-command"]
    )
    for name, pointer in (
        ("training-command", evaluation.evaluation.training_command),
        ("training-result", evaluation.evaluation.training_result),
        ("adapter-manifest", evaluation.evaluation.adapter_manifest),
    ):
        metadata[name] = read_staged_member(
            root,
            "inputs/" + name + ".json",
            maximum_bytes=256 * 1024,
            expected_sha256=pointer.sha256,
        )
    sources = parse_sdxl_learned_comparison_sources(
        command,
        baseline_payload=metadata["baseline-command"],
        extraction_command_payload=metadata["extraction-command"],
        extraction_result_payload=metadata["extraction-result"],
        lora_evaluation_command_payload=metadata["lora-evaluation-command"],
        training_command_payload=metadata["training-command"],
        training_result_payload=metadata["training-result"],
        adapter_manifest_payload=metadata["adapter-manifest"],
    )
    policy_raw = read_staged_member(
        root,
        "inputs/prompt-policy.json",
        maximum_bytes=256 * 1024,
        expected_sha256=sources.baseline.prompt_policy.sha256,
    )
    policy_value = json.loads(policy_raw)
    validate_contract("sdxl-lineart-prompt-policy", policy_value)
    policy = LocalImageSdxlLineartPromptPolicy.model_validate(policy_value)
    if policy.cases != sources.baseline.cases or policy_raw != content_json_bytes(
        policy.model_dump(mode="json")
    ):
        raise ValueError("learned comparison differs from original compiled prompt policy")
    return sources


def _conditioning(raw: bytes) -> None:
    with Image.open(io.BytesIO(raw)) as image:
        if (
            image.format != "PNG"
            or image.mode != "RGB"
            or image.size != (832, 512)
            or getattr(image, "n_frames", 1) != 1
        ):
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        image.load()


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlLearnedComparisonCommand,
    sources: SdxlLearnedComparisonSources,
) -> LocalImageSdxlLearnedComparisonResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        return None
    try:
        raw = read_staged_member(root, "result.json", maximum_bytes=128 * 1024)
        value = json.loads(raw)
        validate_contract("sdxl-learned-comparison-result", value)
        result = LocalImageSdxlLearnedComparisonResult.model_validate(value)
        validate_sdxl_learned_comparison_result(command, sources, result)
        if raw != content_json_bytes(result.model_dump(mode="json")):
            raise ValueError("noncanonical learned comparison result")
        for output in result.outputs:
            final = read_staged_member(
                root,
                output.member_path,
                maximum_bytes=output.size_bytes,
                expected_sha256=output.sha256,
            )
            raster = read_staged_member(
                root,
                output.raw_member_path,
                maximum_bytes=output.raw_size_bytes,
                expected_sha256=output.raw_sha256,
            )
            if (
                len(final) != output.size_bytes
                or len(raster) != output.raw_size_bytes
                or final != sdxl_publication(raster)
            ):
                raise ValueError("learned comparison output size/publication differs")
        return result
    except (ProviderError, ValueError, TypeError, OSError, JsonSchemaValidationError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def run_sdxl_learned_comparison(
    *,
    command: LocalImageSdxlLearnedComparisonCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend: SdxlProbeBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlLearnedComparisonResult:
    """Validate pinned local inputs; replay without CUDA; acquire one lease for both fresh arms."""
    try:
        command = LocalImageSdxlLearnedComparisonCommand.model_validate_json(
            command.model_dump_json()
        )
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if (
                load_sdxl_learned_comparison_command(workspace, workspace / "command.json")
                != command
            ):
                raise ValueError("staged learned comparison differs from invocation")
            sources = _sources(root, command)
            cases = select_sdxl_learned_cases(command, sources.baseline)
            extracted = {entry.case_id: entry for entry in sources.extraction_result.outputs}
            inputs = {}
            for case in cases:
                receipt = extracted[case.case_id]
                raw = read_staged_member(
                    root,
                    f"inputs/conditioning/{case.case_id}.png",
                    maximum_bytes=receipt.conditioning_size_bytes,
                    expected_sha256=receipt.conditioning_sha256,
                )
                if len(raw) != receipt.conditioning_size_bytes:
                    raise ValueError("learned comparison conditioning size differs")
                _conditioning(raw)
                inputs[case.case_id] = raw
            replay = _replay(root, workspace, command, sources)
            if replay is not None:
                return replay
            started_at, start = datetime.now(UTC), time.monotonic()
            create_sdxl_pair_directories(root, workspace)
            produced: list[SdxlLearnedComparisonOutput] = []
            runtime: LocalImageRuntime | None = None
            error: SdxlProbeErrorCode | None = None
            try:
                stack = resolve_sdxl_stack(
                    model_store_root,
                    sources.baseline.model,
                    expected_owner_uid=expected_model_owner_uid,
                )
                material = load_sdxl_lora_material(
                    root,
                    sources.lora_sources.manifest,
                    strength=sources.lora_evaluation_command.evaluation.adapter_strength,
                )
                pair = run_sdxl_pair_inference(
                    root=root,
                    stack=stack,
                    material=material,
                    baseline=sources.baseline,
                    cases=cases,
                    inputs=inputs,
                    conditioning_hashes={
                        key: entry.conditioning_sha256 for key, entry in extracted.items()
                    },
                    seed=command.seed,
                    budget=command.budget,
                    start=start,
                    gpu_lock=gpu_lock,
                    backend=backend,
                )
                produced, runtime, error = list(pair.outputs), pair.runtime, pair.error_code
            except ProviderError as exc:
                error = (
                    cast(SdxlProbeErrorCode, exc.code)
                    if exc.code in _ERRORS
                    else "SDXL_PROBE_EXEC_FAILED"
                )
            except Exception:
                error = "SDXL_PROBE_EXEC_FAILED"
            if (
                error is None
                and (time.monotonic() - start) * 1000 > command.budget.maximum_duration_ms
            ):
                error = "SDXL_PROBE_BUDGET_EXCEEDED"
            value = {
                "schema_version": "local-image-sdxl-learned-comparison-result/1.0",
                "run_id": command.run_id,
                "command_sha256": command.command_sha256,
                "baseline_command_sha256": sources.baseline.command_sha256,
                "extraction_result_sha256": sources.extraction_result.result_sha256,
                "model": sources.baseline.model.model_dump(mode="json"),
                "conditioning_policy": command.conditioning_policy,
                "status": "SUCCEEDED" if error is None else "FAILED",
                "error_code": error,
                "runtime": runtime.model_dump(mode="json") if runtime is not None else None,
                "outputs": [entry.model_dump(mode="json") for entry in produced],
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "duration_ms": max(1, int((time.monotonic() - start) * 1000)),
            }
            value["result_sha256"] = content_sha256(value)
            validate_contract("sdxl-learned-comparison-result", value)
            result = LocalImageSdxlLearnedComparisonResult.model_validate(value)
            validate_sdxl_learned_comparison_result(command, sources, result)
            write_staged_member(root, "result.json", content_json_bytes(value))
            return result
    except ProviderError:
        raise
    except (ValueError, TypeError, OSError, JsonSchemaValidationError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
