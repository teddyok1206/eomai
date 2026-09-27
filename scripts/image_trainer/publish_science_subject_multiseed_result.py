#!/usr/bin/env python3
"""Publish one validated science-subject multi-seed result and its PNG members."""

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
    LocalImageScienceVisualSubjectMultiseedCommand,
    LocalImageScienceVisualSubjectMultiseedPlan,
    LocalImageScienceVisualSubjectMultiseedResult,
    content_json_bytes,
    validate_contract,
    validate_science_visual_subject_multiseed_result,
)
from eom_orchestrator.database import build_engine
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.settings import Settings
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from scripts.image_trainer.publication_io import (
    PublicationFileReadError,
    read_regular_file,
)
from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    WORKSPACE_PARENT,
    _parse_json,
    _require_release,
    _write_exclusive,
)

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_IMAGE_BYTES = 64 * 1024 * 1024
RUN_ID = re.compile(r"^imgscisubjectmultiseedrun_[0-9a-f]{32}$")
RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-result/1.0"
)


class ScienceSubjectMultiseedPublicationError(RuntimeError):
    """Stable operator-facing multi-seed publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _workspace(run_id: str) -> Path:
    if RUN_ID.fullmatch(run_id) is None:
        raise ScienceSubjectMultiseedPublicationError("SCIENCE_SUBJECT_MULTISEED_RUN_INVALID")
    workspace = WORKSPACE_PARENT / run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise ScienceSubjectMultiseedPublicationError("SCIENCE_SUBJECT_MULTISEED_RUN_INVALID")
    return workspace


def _read_json(path: Path) -> tuple[bytes, dict[str, object]]:
    payload = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
    return payload, _parse_json(payload)


def _load(
    workspace: Path,
) -> tuple[
    LocalImageScienceVisualSubjectMultiseedCommand,
    LocalImageScienceVisualSubjectMultiseedPlan,
    LocalImageScienceVisualSubjectMultiseedResult,
    bytes,
]:
    try:
        _command_payload, command_value = _read_json(workspace / "command.json")
        _plan_payload, plan_value = _read_json(workspace / "inputs" / "subject-multiseed-plan.json")
        result_payload, result_value = _read_json(workspace / "result.json")
        validate_contract("science-visual-subject-multiseed-command", command_value)
        validate_contract("science-visual-subject-multiseed-plan", plan_value)
        validate_contract("science-visual-subject-multiseed-result", result_value)
        command = LocalImageScienceVisualSubjectMultiseedCommand.model_validate(command_value)
        plan = LocalImageScienceVisualSubjectMultiseedPlan.model_validate(plan_value)
        result = LocalImageScienceVisualSubjectMultiseedResult.model_validate(result_value)
        validate_science_visual_subject_multiseed_result(plan, command, result)
    except (
        PublicationFileReadError,
        JsonSchemaValidationError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise ScienceSubjectMultiseedPublicationError(
            "SCIENCE_SUBJECT_MULTISEED_RESULT_INVALID"
        ) from exc
    if (
        result.status != "SUCCEEDED"
        or content_json_bytes(result.model_dump(mode="json")) + b"\n" != result_payload
    ):
        raise ScienceSubjectMultiseedPublicationError("SCIENCE_SUBJECT_MULTISEED_RESULT_INVALID")
    return command, plan, result, result_payload


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ScienceSubjectMultiseedPublicationError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
    offset = 8
    dimensions: tuple[int, int] | None = None
    saw_end = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise ScienceSubjectMultiseedPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
            )
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > MAX_IMAGE_BYTES or end > len(payload):
            raise ScienceSubjectMultiseedPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
            )
        chunk = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
            raise ScienceSubjectMultiseedPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
            )
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                raise ScienceSubjectMultiseedPublicationError(
                    "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
                )
            dimensions = struct.unpack(">II", chunk[:8])
        if chunk_type == b"IEND":
            if length != 0 or end != len(payload):
                raise ScienceSubjectMultiseedPublicationError(
                    "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
                )
            saw_end = True
        offset = end
    if dimensions is None or not saw_end:
        raise ScienceSubjectMultiseedPublicationError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
    return dimensions


def _members(
    workspace: Path,
    result: LocalImageScienceVisualSubjectMultiseedResult,
    result_payload: bytes,
) -> tuple[ControlFileSetMember, ...]:
    expected_paths = {output.relative_path for output in result.outputs}
    output_root = workspace / "outputs"
    actual_paths = {
        path.relative_to(workspace).as_posix() for path in output_root.rglob("*") if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ScienceSubjectMultiseedPublicationError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
    values = [
        ControlFileSetMember(
            file_name="result.json",
            source=workspace / "result.json",
            sha256=sha256_bytes(result_payload),
            bytes=len(result_payload),
            schema_ref=RESULT_SCHEMA_REF,
            media_type="application/json",
        )
    ]
    for output in result.outputs:
        relative = PurePosixPath(output.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ScienceSubjectMultiseedPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
            )
        source = workspace.joinpath(*relative.parts)
        try:
            payload = read_regular_file(
                source,
                expected_sha256=output.sha256,
                maximum_bytes=MAX_IMAGE_BYTES,
            )
        except PublicationFileReadError as exc:
            raise ScienceSubjectMultiseedPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
            ) from exc
        if len(payload) != output.bytes or _png_dimensions(payload) != (
            output.width_px,
            output.height_px,
        ):
            raise ScienceSubjectMultiseedPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
            )
        values.append(
            ControlFileSetMember(
                file_name=output.relative_path,
                source=source,
                sha256=output.sha256,
                bytes=output.bytes,
                schema_ref=(
                    "eom://schemas/image-provider/"
                    "local-image-science-visual-subject-multiseed-image/1.0"
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
            raise ScienceSubjectMultiseedPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_RECEIPT_CONFLICT"
            )
        return
    _write_exclusive(path, payload, mode=0o600)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    workspace = _workspace(args.run_id)
    command, plan, result, result_payload = _load(workspace)
    members = _members(workspace, result, result_payload)
    summary = {
        "output_count": len(result.outputs),
        "plan_id": plan.plan_id,
        "result_sha256": result.result_sha256,
        "run_id": result.run_id,
        "source_commit": command.source_commit,
    }
    if args.preflight_only:
        print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
        return 0
    engine = build_engine()
    try:
        published = ControlFileSetPublisher(engine, Settings.from_environment()).publish(
            members=members,
            primary_file="result.json",
            artifact_type="control_local_image_science_subject_multiseed",
            manifest_version="local-image-science-subject-multiseed-files/1.0",
            idempotency_key=f"science-subject-multiseed:{result.run_id}",
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
        "schema_version": "science-subject-multiseed-publication-receipt/1.0",
        **summary,
        "result_artifact": result_pointer.model_dump(mode="json"),
        "file_set_manifest_sha256": published.manifest_sha256,
        "publication_source_commit": args.source_commit,
    }
    receipt_path = STATE_ROOT / f"science-subject-multiseed-publication-{result.run_id}.json"
    _write_receipt(receipt_path, content_json_bytes(receipt))
    print(
        json.dumps({**summary, "receipt": str(receipt_path), "status": "PUBLISHED"}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
