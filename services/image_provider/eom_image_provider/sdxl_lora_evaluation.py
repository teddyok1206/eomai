"""Offline matched-input LoRA evaluation with an additive, replay-safe receipt."""

from __future__ import annotations

import json
import os
from pathlib import Path

from eom_image_contracts import (
    LocalImageSdxlLoraEvaluationCommand,
    LocalImageSdxlLoraEvaluationResult,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_sdxl_lora_evaluation_result,
)
from eom_image_contracts.sdxl_lora_evaluation import parse_sdxl_lora_evaluation_sources
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_lineart_probe import (
    MAX_PNG_BYTES,
    SdxlProbeBackend,
    generate_sdxl_probe_evidence,
)
from eom_image_provider.sdxl_lora_material import load_sdxl_lora_material
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    write_staged_member,
)


def load_sdxl_lora_evaluation_command(
    workspace: Path, command_path: Path
) -> LocalImageSdxlLoraEvaluationCommand:
    if command_path != workspace / "command.json":
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        raw = read_staged_member(root, "command.json", maximum_bytes=64 * 1024)
    try:
        value = json.loads(raw)
        validate_contract("sdxl-lora-evaluation-command", value)
        command = LocalImageSdxlLoraEvaluationCommand.model_validate(value)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise ValueError("noncanonical evaluation command")
        return command
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc


def run_sdxl_lora_evaluation(
    *,
    command: LocalImageSdxlLoraEvaluationCommand,
    model_store_root: Path,
    workspace: Path,
    backend: SdxlProbeBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlLoraEvaluationResult:
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        pin = command.evaluation
        try:
            payloads = {
                name: read_staged_member(
                    root,
                    "inputs/" + name + ".json",
                    maximum_bytes=256 * 1024,
                    expected_sha256=pointer.sha256,
                )
                for name, pointer in (
                    ("baseline-command", pin.baseline_command),
                    ("training-command", pin.training_command),
                    ("training-result", pin.training_result),
                    ("adapter-manifest", pin.adapter_manifest),
                )
            }
            sources = parse_sdxl_lora_evaluation_sources(
                command,
                baseline_payload=payloads["baseline-command"],
                training_command_payload=payloads["training-command"],
                training_result_payload=payloads["training-result"],
                manifest_payload=payloads["adapter-manifest"],
            )
        except (ValueError, TypeError, JsonSchemaValidationError) as exc:
            raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
        material = load_sdxl_lora_material(root, sources.manifest, strength=pin.adapter_strength)
        if os.path.lexists(workspace / "result.json"):
            raw = read_staged_member(root, "result.json", maximum_bytes=256 * 1024)
            try:
                value = json.loads(raw)
                validate_contract("sdxl-lora-evaluation-result", value)
                result = LocalImageSdxlLoraEvaluationResult.model_validate(value)
                validate_sdxl_lora_evaluation_result(command, sources.baseline, result)
                if raw != content_json_bytes(result.model_dump(mode="json")):
                    raise ValueError("noncanonical result")
            except (ValueError, TypeError, JsonSchemaValidationError) as exc:
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc
            members = tuple(
                (entry.member_path, entry.sha256) for entry in result.conditionings
            ) + tuple(
                member
                for entry in result.outputs
                for member in (
                    (entry.member_path, entry.sha256),
                    (entry.raw_member_path, entry.raw_sha256),
                )
            )
            for member, sha in members:
                read_staged_member(root, member, maximum_bytes=MAX_PNG_BYTES, expected_sha256=sha)
            return result
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
    evidence = generate_sdxl_probe_evidence(
        command=sources.baseline,
        model_store_root=model_store_root,
        workspace=workspace,
        backend=backend,
        expected_model_owner_uid=expected_model_owner_uid,
        style_adapter=material,
    )
    value = {
        "schema_version": "local-image-sdxl-lora-evaluation-result/1.0",
        "run_id": command.run_id,
        "command_sha256": command.command_sha256,
        "evaluation": pin.model_dump(mode="json"),
        "baseline_command_sha256": sources.baseline.command_sha256,
        "model": sources.baseline.model.model_dump(mode="json"),
        "status": "SUCCEEDED" if evidence.error_code is None else "FAILED",
        "error_code": evidence.error_code,
        "runtime": None if evidence.runtime is None else evidence.runtime.model_dump(mode="json"),
        "conditionings": [entry.model_dump(mode="json") for entry in evidence.conditionings],
        "outputs": [entry.model_dump(mode="json") for entry in evidence.outputs],
        "started_at": evidence.started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": evidence.completed_at.isoformat().replace("+00:00", "Z"),
        "duration_ms": evidence.duration_ms,
    }
    value["result_sha256"] = content_sha256(value)
    validate_contract("sdxl-lora-evaluation-result", value)
    result = LocalImageSdxlLoraEvaluationResult.model_validate(value)
    validate_sdxl_lora_evaluation_result(command, sources.baseline, result)
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        write_staged_member(root, "result.json", content_json_bytes(value))
    return result
