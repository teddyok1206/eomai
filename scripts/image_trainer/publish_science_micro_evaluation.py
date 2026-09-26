#!/usr/bin/env python3
"""Publish one validated science LoRA comparison through the Orchestrator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath

from eom_identifiers import sha256_file
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceLoraMicroEvaluationCommand,
    LocalImageScienceLoraMicroEvaluationResult,
    content_json_bytes,
    validate_contract,
    validate_science_micro_evaluation_result,
)
from eom_orchestrator.database import build_engine
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    WORKSPACE_PARENT,
    _parse_json,
    _require_release,
    _safe_read,
    _write_exclusive,
)

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-lora-micro-evaluation-result/1.0"
)
IMAGE_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-lora-micro-evaluation-image/1.0"
)
MAX_IMAGE_BYTES = 64 * 1024 * 1024


class ScienceMicroEvaluationPublicationError(RuntimeError):
    """Stable operator-facing evaluation publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _workspace(evaluation_run_id: str) -> Path:
    if not evaluation_run_id.startswith("imgscimicroevalrun_") or len(evaluation_run_id) != 51:
        raise ScienceMicroEvaluationPublicationError("IMAGE_EVALUATION_RUN_INVALID")
    workspace = WORKSPACE_PARENT / evaluation_run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise ScienceMicroEvaluationPublicationError("IMAGE_EVALUATION_RUN_INVALID")
    return workspace


def _read_json(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    payload = _safe_read(
        path,
        expected_sha256=sha256_file(path),
        maximum_bytes=maximum_bytes,
    )
    return _parse_json(payload)


def _load_result(
    workspace: Path,
) -> tuple[
    LocalImageScienceLoraMicroEvaluationCommand,
    LocalImageScienceLoraMicroEvaluationResult,
]:
    try:
        command_value = _read_json(workspace / "command.json", maximum_bytes=MAX_JSON_BYTES)
        result_value = _read_json(workspace / "result.json", maximum_bytes=MAX_JSON_BYTES)
        validate_contract("science-lora-micro-evaluation-command", command_value)
        validate_contract("science-lora-micro-evaluation-result", result_value)
        command = LocalImageScienceLoraMicroEvaluationCommand.model_validate(command_value)
        result = LocalImageScienceLoraMicroEvaluationResult.model_validate(result_value)
        validate_science_micro_evaluation_result(command, result)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceMicroEvaluationPublicationError("IMAGE_EVALUATION_RESULT_INVALID") from exc
    if result.status != "SUCCEEDED":
        raise ScienceMicroEvaluationPublicationError("IMAGE_EVALUATION_RESULT_INVALID")
    return command, result


def _members(
    workspace: Path,
    result: LocalImageScienceLoraMicroEvaluationResult,
) -> tuple[ControlFileSetMember, ...]:
    values = [
        ControlFileSetMember(
            file_name="result.json",
            source=workspace / "result.json",
            sha256=sha256_file(workspace / "result.json"),
            bytes=(workspace / "result.json").stat().st_size,
            schema_ref=RESULT_SCHEMA_REF,
            media_type="application/json",
        )
    ]
    for output in result.outputs:
        member = PurePosixPath(output.member_path)
        if member.is_absolute() or ".." in member.parts:
            raise ScienceMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        source = workspace.joinpath(*member.parts)
        payload = _safe_read(
            source,
            expected_sha256=output.sha256,
            maximum_bytes=MAX_IMAGE_BYTES,
        )
        if len(payload) != output.size_bytes:
            raise ScienceMicroEvaluationPublicationError("IMAGE_EVALUATION_OUTPUT_INVALID")
        values.append(
            ControlFileSetMember(
                file_name=output.member_path,
                source=source,
                sha256=output.sha256,
                bytes=output.size_bytes,
                schema_ref=IMAGE_SCHEMA_REF,
                media_type="image/png",
            )
        )
    return tuple(sorted(values, key=lambda value: value.file_name))


def _write_receipt(path: Path, payload: bytes) -> None:
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        existing = _safe_read(
            path,
            expected_sha256=sha256_file(path),
            maximum_bytes=MAX_JSON_BYTES,
        )
        if existing != payload:
            raise ScienceMicroEvaluationPublicationError("IMAGE_EVALUATION_RECEIPT_CONFLICT")
        return
    _write_exclusive(path, payload, mode=0o600)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    workspace = _workspace(args.evaluation_run_id)
    command, result = _load_result(workspace)
    members = _members(workspace, result)
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
            artifact_type="control_local_image_science_micro_evaluation",
            manifest_version="local-image-science-micro-evaluation-files/1.0",
            idempotency_key=f"science-micro-evaluation:{result.evaluation_run_id}",
            source_commit=args.source_commit,
            created_at=result.completed_at,
        )
    finally:
        engine.dispose()
    result_pointer = ImageEvaluationArtifactMember(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path="result.json",
        schema_ref=RESULT_SCHEMA_REF,
        media_type="application/json",
        sha256=published.primary_sha256,
    )
    receipt = {
        "schema_version": "science-micro-evaluation-publication-receipt/1.0",
        **summary,
        "result_artifact": result_pointer.model_dump(mode="json"),
        "file_set_manifest_sha256": published.manifest_sha256,
        "publication_source_commit": args.source_commit,
    }
    receipt_path = STATE_ROOT / (
        f"science-micro-evaluation-publication-{result.evaluation_run_id}.json"
    )
    _write_receipt(receipt_path, content_json_bytes(receipt))
    print(json.dumps({**summary, "receipt": str(receipt_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
