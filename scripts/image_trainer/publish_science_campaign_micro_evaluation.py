#!/usr/bin/env python3
"""Publish one validated campaign BASE-versus-LoRA evaluation."""

from __future__ import annotations

import argparse
import json
import re
import struct
import zlib
from pathlib import Path, PurePosixPath

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCampaignLoraMicroEvaluationCommand,
    LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    LocalImageScienceCampaignLoraMicroEvaluationResult,
    LocalImageScienceCampaignLoraMicroEvaluationResultV2,
    content_json_bytes,
    validate_contract,
    validate_science_campaign_micro_evaluation_result,
    validate_science_campaign_micro_evaluation_result_v2,
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
MAX_IMAGE_BYTES = 64 * 1024 * 1024
_RUN_ID = re.compile(r"^imgscicampaignmicroevalrun_[0-9a-f]{32}$")
_RESULT_SCHEMA = {
    "1.0": (
        "science-campaign-lora-micro-evaluation-result",
        "eom://schemas/image-provider/"
        "local-image-science-campaign-lora-micro-evaluation-result/1.0",
    ),
    "1.1": (
        "science-campaign-lora-micro-evaluation-result-v2",
        "eom://schemas/image-provider/"
        "local-image-science-campaign-lora-micro-evaluation-result/1.1",
    ),
}


class ScienceCampaignMicroEvaluationPublicationError(RuntimeError):
    """Stable operator-facing campaign evaluation publication failure."""


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
    offset = 8
    dimensions: tuple[int, int] | None = None
    saw_end = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > MAX_IMAGE_BYTES or end > len(payload):
            raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        chunk_data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                raise ScienceCampaignMicroEvaluationPublicationError(
                    "IMAGE_EVALUATION_OUTPUT_INVALID"
                )
            dimensions = struct.unpack(">II", chunk_data[:8])
        if chunk_type == b"IEND":
            if length != 0 or end != len(payload):
                raise ScienceCampaignMicroEvaluationPublicationError(
                    "IMAGE_EVALUATION_OUTPUT_INVALID"
                )
            saw_end = True
        offset = end
    if dimensions is None or not saw_end:
        raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
    return dimensions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _workspace(evaluation_run_id: str) -> Path:
    if _RUN_ID.fullmatch(evaluation_run_id) is None:
        raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_RUN_INVALID")
    workspace = WORKSPACE_PARENT / evaluation_run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_RUN_INVALID")
    return workspace


def _read_json(path: Path) -> tuple[bytes, dict[str, object]]:
    payload = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
    return payload, _parse_json(payload)


def _load_result(
    workspace: Path,
) -> tuple[
    LocalImageScienceCampaignLoraMicroEvaluationCommand
    | LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    LocalImageScienceCampaignLoraMicroEvaluationResult
    | LocalImageScienceCampaignLoraMicroEvaluationResultV2,
    bytes,
    str,
]:
    try:
        _command_payload, command_value = _read_json(workspace / "command.json")
        result_payload, result_value = _read_json(workspace / "result.json")
        version = str(result_value.get("schema_version", "")).rsplit("/", 1)[-1]
        result_contract, result_schema_ref = _RESULT_SCHEMA[version]
        validate_contract(result_contract, result_value)
        if version == "1.1":
            validate_contract("science-campaign-lora-micro-evaluation-command-v2", command_value)
            command: (
                LocalImageScienceCampaignLoraMicroEvaluationCommand
                | LocalImageScienceCampaignLoraMicroEvaluationCommandV2
            ) = LocalImageScienceCampaignLoraMicroEvaluationCommandV2.model_validate(command_value)
            result: (
                LocalImageScienceCampaignLoraMicroEvaluationResult
                | LocalImageScienceCampaignLoraMicroEvaluationResultV2
            ) = LocalImageScienceCampaignLoraMicroEvaluationResultV2.model_validate(result_value)
            assert isinstance(command, LocalImageScienceCampaignLoraMicroEvaluationCommandV2)
            assert isinstance(result, LocalImageScienceCampaignLoraMicroEvaluationResultV2)
            validate_science_campaign_micro_evaluation_result_v2(command, result)
        else:
            validate_contract("science-campaign-lora-micro-evaluation-command", command_value)
            command = LocalImageScienceCampaignLoraMicroEvaluationCommand.model_validate(
                command_value
            )
            result = LocalImageScienceCampaignLoraMicroEvaluationResult.model_validate(result_value)
            validate_science_campaign_micro_evaluation_result(command, result)
    except (
        CropLocatorStageError,
        KeyError,
        PublicationFileReadError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise ScienceCampaignMicroEvaluationPublicationError(
            "IMAGE_EVALUATION_RESULT_INVALID"
        ) from exc
    if (
        result.status != "SUCCEEDED"
        or content_json_bytes(result.model_dump(mode="json")) + b"\n" != result_payload
    ):
        raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_RESULT_INVALID")
    return command, result, result_payload, result_schema_ref


def _members(
    workspace: Path,
    result: LocalImageScienceCampaignLoraMicroEvaluationResult
    | LocalImageScienceCampaignLoraMicroEvaluationResultV2,
    result_payload: bytes,
    result_schema_ref: str,
) -> tuple[ControlFileSetMember, ...]:
    expected_paths = {value.member_path for value in result.outputs}
    output_root = workspace / "outputs"
    actual_paths = {
        path.relative_to(workspace).as_posix() for path in output_root.rglob("*") if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
    values = [
        ControlFileSetMember(
            file_name="result.json",
            source=workspace / "result.json",
            sha256=sha256_bytes(result_payload),
            bytes=len(result_payload),
            schema_ref=result_schema_ref,
            media_type="application/json",
        )
    ]
    for output in result.outputs:
        relative = PurePosixPath(output.member_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        source = workspace.joinpath(*relative.parts)
        try:
            payload = read_regular_file(
                source,
                expected_sha256=output.sha256,
                maximum_bytes=MAX_IMAGE_BYTES,
            )
        except PublicationFileReadError as exc:
            raise ScienceCampaignMicroEvaluationPublicationError(
                "IMAGE_EVALUATION_OUTPUT_INVALID"
            ) from exc
        if len(payload) != output.size_bytes:
            raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        if _png_dimensions(payload) != (output.width_px, output.height_px):
            raise ScienceCampaignMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        values.append(
            ControlFileSetMember(
                file_name=output.member_path,
                source=source,
                sha256=output.sha256,
                bytes=output.size_bytes,
                schema_ref=(
                    "eom://schemas/image-provider/"
                    "local-image-science-campaign-lora-evaluation-image/1.0"
                ),
                media_type="image/png",
            )
        )
    return tuple(sorted(values, key=lambda value: value.file_name))


def _write_receipt(path: Path, payload: bytes) -> None:
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        existing = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
        if existing != payload:
            raise ScienceCampaignMicroEvaluationPublicationError(
                "IMAGE_EVALUATION_RECEIPT_CONFLICT"
            )
        return
    _write_exclusive(path, payload, mode=0o600)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    workspace = _workspace(args.evaluation_run_id)
    command, result, result_payload, result_schema_ref = _load_result(workspace)
    members = _members(workspace, result, result_payload, result_schema_ref)
    summary = {
        "evaluation_run_id": result.evaluation_run_id,
        "result_sha256": result.result_sha256,
        "output_count": len(result.outputs),
        "training_result_sha256": result.training_result_sha256,
        "adapter_manifest_sha256": result.adapter_manifest_sha256,
        "generation_source_commit": command.source_commit,
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0
    engine = build_engine()
    try:
        published = ControlFileSetPublisher(engine, Settings.from_environment()).publish(
            members=members,
            primary_file="result.json",
            artifact_type="control_local_image_science_campaign_lora_eval",
            manifest_version="local-image-science-campaign-lora-eval-files/1.0",
            idempotency_key=f"science-campaign-lora-eval:{result.evaluation_run_id}",
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
        "schema_version": "science-campaign-lora-evaluation-publication-receipt/1.0",
        **summary,
        "result_artifact": result_pointer.model_dump(mode="json"),
        "file_set_manifest_sha256": published.manifest_sha256,
        "publication_source_commit": args.source_commit,
    }
    receipt_path = STATE_ROOT / (
        f"science-campaign-lora-evaluation-publication-{result.evaluation_run_id}.json"
    )
    _write_receipt(receipt_path, content_json_bytes(receipt))
    print(json.dumps({**summary, "receipt": str(receipt_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
