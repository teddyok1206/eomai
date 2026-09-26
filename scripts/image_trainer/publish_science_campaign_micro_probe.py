#!/usr/bin/env python3
"""Publish one validated campaign LoRA result through the Orchestrator."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCampaignLoraMicroProbeCommand,
    LocalImageScienceCampaignLoraMicroProbeCommandV2,
    LocalImageScienceCampaignLoraMicroProbeWorkerResult,
    LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
    content_json_bytes,
    validate_contract,
    validate_science_campaign_micro_probe_worker_result,
    validate_science_campaign_micro_probe_worker_result_v2,
)
from eom_orchestrator.database import build_engine
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError

from scripts.image_trainer.publication_io import (
    PublicationFileReadError,
    read_regular_file,
)
from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    WORKSPACE_PARENT,
    CropLocatorStageError,
    _parse_json,
    _require_release,
    _write_exclusive,
)

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_ADAPTER_BYTES = 1024 * 1024 * 1024
_RUN_ID = re.compile(r"^imgscicampaignmicrotrainrun_[0-9a-f]{32}$")
_RESULT_SCHEMA = {
    "1.0": (
        "science-campaign-lora-micro-probe-worker-result",
        "eom://schemas/image-provider/"
        "local-image-science-campaign-lora-micro-probe-worker-result/1.0",
    ),
    "1.1": (
        "science-campaign-lora-micro-probe-worker-result-v2",
        "eom://schemas/image-provider/"
        "local-image-science-campaign-lora-micro-probe-worker-result/1.1",
    ),
}
_MANIFEST_SCHEMA = {
    "1.0": (
        "science-campaign-lora-micro-adapter-manifest",
        "eom://schemas/image-provider/local-image-science-campaign-lora-micro-adapter-manifest/1.0",
    ),
    "1.1": (
        "science-campaign-lora-micro-adapter-manifest-v2",
        "eom://schemas/image-provider/local-image-science-campaign-lora-micro-adapter-manifest/1.1",
    ),
}


class ScienceCampaignMicroProbePublicationError(RuntimeError):
    """Stable operator-facing campaign training publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _workspace(training_run_id: str) -> Path:
    if _RUN_ID.fullmatch(training_run_id) is None:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_RUN_INVALID")
    workspace = WORKSPACE_PARENT / training_run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_RUN_INVALID")
    return workspace


def _read_json(path: Path, *, maximum_bytes: int) -> tuple[bytes, dict[str, object]]:
    payload = read_regular_file(path, maximum_bytes=maximum_bytes)
    return payload, _parse_json(payload)


def _load_result(
    workspace: Path,
) -> tuple[
    LocalImageScienceCampaignLoraMicroProbeCommand
    | LocalImageScienceCampaignLoraMicroProbeCommandV2,
    LocalImageScienceCampaignLoraMicroProbeWorkerResult
    | LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
    bytes,
    str,
]:
    try:
        _command_payload, command_value = _read_json(
            workspace / "command.json", maximum_bytes=MAX_JSON_BYTES
        )
        result_payload, result_value = _read_json(
            workspace / "result.json", maximum_bytes=MAX_JSON_BYTES
        )
        version = str(result_value.get("schema_version", "")).rsplit("/", 1)[-1]
        result_contract, result_schema_ref = _RESULT_SCHEMA[version]
        validate_contract(result_contract, result_value)
        if version == "1.1":
            validate_contract("science-campaign-lora-micro-probe-command-v2", command_value)
            command: (
                LocalImageScienceCampaignLoraMicroProbeCommand
                | LocalImageScienceCampaignLoraMicroProbeCommandV2
            ) = LocalImageScienceCampaignLoraMicroProbeCommandV2.model_validate(command_value)
            result: (
                LocalImageScienceCampaignLoraMicroProbeWorkerResult
                | LocalImageScienceCampaignLoraMicroProbeWorkerResultV2
            ) = LocalImageScienceCampaignLoraMicroProbeWorkerResultV2.model_validate(result_value)
            assert isinstance(command, LocalImageScienceCampaignLoraMicroProbeCommandV2)
            assert isinstance(result, LocalImageScienceCampaignLoraMicroProbeWorkerResultV2)
            validate_science_campaign_micro_probe_worker_result_v2(command, result)
        else:
            validate_contract("science-campaign-lora-micro-probe-command", command_value)
            command = LocalImageScienceCampaignLoraMicroProbeCommand.model_validate(command_value)
            result = LocalImageScienceCampaignLoraMicroProbeWorkerResult.model_validate(
                result_value
            )
            validate_science_campaign_micro_probe_worker_result(command, result)
    except (
        CropLocatorStageError,
        KeyError,
        PublicationFileReadError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_RESULT_INVALID") from exc
    if (
        result.status != "SUCCEEDED"
        or result.adapter_manifest is None
        or result.completed_steps != 200
        or content_json_bytes(result.model_dump(mode="json")) != result_payload
    ):
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_RESULT_INVALID")
    return command, result, result_payload, result_schema_ref


def _member(
    *,
    file_name: str,
    source: Path,
    sha256: str,
    size_bytes: int,
    schema_ref: str,
    media_type: str,
) -> ControlFileSetMember:
    try:
        payload = read_regular_file(
            source,
            expected_sha256=sha256,
            maximum_bytes=MAX_ADAPTER_BYTES,
        )
    except PublicationFileReadError as exc:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_OUTPUT_INVALID") from exc
    if len(payload) != size_bytes:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_OUTPUT_INVALID")
    return ControlFileSetMember(
        file_name=file_name,
        source=source,
        sha256=sha256,
        bytes=size_bytes,
        schema_ref=schema_ref,
        media_type=media_type,
    )


def _members(
    workspace: Path,
    result: LocalImageScienceCampaignLoraMicroProbeWorkerResult
    | LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
    result_payload: bytes,
    result_schema_ref: str,
) -> tuple[ControlFileSetMember, ...]:
    assert result.adapter_manifest is not None
    version = result.adapter_manifest.schema_version.rsplit("/", 1)[-1]
    manifest_contract, manifest_schema_ref = _MANIFEST_SCHEMA[version]
    manifest_path = workspace / "outputs" / "manifests" / "adapter-manifest.json"
    manifest_payload, manifest_value = _read_json(manifest_path, maximum_bytes=MAX_JSON_BYTES)
    try:
        validate_contract(manifest_contract, manifest_value)
        if manifest_value != result.adapter_manifest.model_dump(mode="json"):
            raise ValueError("adapter manifest differs from worker result")
    except (
        CropLocatorStageError,
        PublicationFileReadError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_OUTPUT_INVALID") from exc
    output_root = workspace / "outputs"
    actual = tuple(
        sorted(
            path.relative_to(output_root).as_posix()
            for path in output_root.rglob("*")
            if path.is_file()
        )
    )
    expected = (
        "adapter_config.json",
        "adapter_model.safetensors",
        "manifests/adapter-manifest.json",
    )
    if actual != expected:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_OUTPUT_INVALID")
    declared = {value.relative_path: value for value in result.adapter_manifest.files}
    try:
        config_payload = read_regular_file(
            output_root / "adapter_config.json",
            expected_sha256=declared["adapter_config.json"].sha256,
            maximum_bytes=MAX_JSON_BYTES,
        )
        config = _parse_json(config_payload)
    except (PublicationFileReadError, TypeError, ValueError) as exc:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_OUTPUT_INVALID") from exc
    if config.get("peft_type") != "LORA" or config.get("r") != 8 or config.get("lora_alpha") != 8:
        raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_OUTPUT_INVALID")
    values = [
        ControlFileSetMember(
            file_name="result.json",
            source=workspace / "result.json",
            sha256=sha256_bytes(result_payload),
            bytes=len(result_payload),
            schema_ref=result_schema_ref,
            media_type="application/json",
        ),
        ControlFileSetMember(
            file_name="manifests/adapter-manifest.json",
            source=manifest_path,
            sha256=sha256_bytes(manifest_payload),
            bytes=len(manifest_payload),
            schema_ref=manifest_schema_ref,
            media_type="application/json",
        ),
    ]
    for entry, schema_ref, media_type in (
        (
            declared["adapter_config.json"],
            "eom://schemas/image-provider/local-image-lora-adapter-config/1.0",
            "application/json",
        ),
        (
            declared["adapter_model.safetensors"],
            "eom://schemas/image-provider/local-image-lora-adapter-weights/1.0",
            "application/octet-stream",
        ),
    ):
        values.append(
            _member(
                file_name=entry.relative_path,
                source=output_root / entry.relative_path,
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
                schema_ref=schema_ref,
                media_type=media_type,
            )
        )
    return tuple(sorted(values, key=lambda value: value.file_name))


def _write_receipt(path: Path, payload: bytes) -> None:
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        existing = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
        if existing != payload:
            raise ScienceCampaignMicroProbePublicationError("IMAGE_TRAINING_RECEIPT_CONFLICT")
        return
    _write_exclusive(path, payload, mode=0o600)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    workspace = _workspace(args.training_run_id)
    command, result, result_payload, result_schema_ref = _load_result(workspace)
    members = _members(workspace, result, result_payload, result_schema_ref)
    assert result.adapter_manifest is not None
    summary = {
        "training_run_id": result.training_run_id,
        "result_sha256": result.result_sha256,
        "adapter_id": result.adapter_manifest.adapter_id,
        "adapter_revision_id": result.adapter_manifest.adapter_revision_id,
        "adapter_manifest_sha256": result.adapter_manifest.manifest_sha256,
        "member_count": len(members),
        "generation_source_commit": command.probe_plan.source_commit,
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0
    engine = build_engine()
    try:
        published = ControlFileSetPublisher(engine, Settings.from_environment()).publish(
            members=members,
            primary_file="result.json",
            artifact_type="control_local_image_science_campaign_lora_result",
            manifest_version="local-image-science-campaign-lora-result-files/1.0",
            idempotency_key=f"science-campaign-lora-result:{result.training_run_id}",
            source_commit=args.source_commit,
            created_at=result.completed_at,
        )
    finally:
        engine.dispose()
    result_pointer = ImageEvaluationArtifactMember(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path="result.json",
        schema_ref=result_schema_ref,
        media_type="application/json",
        sha256=published.primary_sha256,
    )
    receipt = {
        "schema_version": "science-campaign-lora-result-publication-receipt/1.0",
        **summary,
        "result_artifact": result_pointer.model_dump(mode="json"),
        "file_set_manifest_sha256": published.manifest_sha256,
        "publication_source_commit": args.source_commit,
    }
    receipt_path = STATE_ROOT / (
        f"science-campaign-lora-result-publication-{result.training_run_id}.json"
    )
    _write_receipt(receipt_path, content_json_bytes(receipt))
    print(json.dumps({**summary, "receipt": str(receipt_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
