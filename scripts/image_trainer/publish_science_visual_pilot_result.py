#!/usr/bin/env python3
"""Validate one terminal science-visual workspace and publish its result via Orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import struct
import zlib
from pathlib import Path, PurePosixPath

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotPlan,
    LocalImageScienceCorpusVisualPilotResult,
    ScienceVisualCandidate,
    ScienceVisualPageImage,
    content_json_bytes,
    validate_contract,
    validate_science_visual_pilot_command,
    validate_science_visual_pilot_result,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError

WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ScienceVisualPilotPublicationError(RuntimeError):
    """Stable operator-facing publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _safe_read(path: Path, *, maximum_bytes: int, expected_sha256: str | None = None) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_CHANGED")
    finally:
        os.close(descriptor)
    body = bytes(payload)
    if expected_sha256 is not None and sha256_bytes(body) != expected_sha256:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_HASH_MISMATCH")
    return body


def _json_object(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_JSON_INVALID")
    return value


def _member_path(workspace: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_PATH_INVALID")
    current = workspace
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_MISSING") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_INVALID")
    return current


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
    offset = 8
    dimensions: tuple[int, int] | None = None
    saw_end = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > MAX_PNG_BYTES or end > len(payload):
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
        chunk_data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
            width, height = struct.unpack(">II", chunk_data[:8])
            if not 0 < width <= 10_000 or not 0 < height <= 10_000:
                raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
            dimensions = (width, height)
        if chunk_type == b"IEND":
            if length != 0 or end != len(payload):
                raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
            saw_end = True
        offset = end
    if dimensions is None or not saw_end:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_INVALID")
    return dimensions


def _load_workspace(
    workspace: Path,
) -> tuple[
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotPlan,
    LocalImageScienceCorpusVisualPilotResult,
    bytes,
    int,
]:
    command_value = _json_object(
        _safe_read(workspace / "command.json", maximum_bytes=MAX_JSON_BYTES)
    )
    try:
        validate_contract("science-corpus-visual-pilot-command", command_value)
        command = LocalImageScienceCorpusVisualPilotCommand.model_validate(command_value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_RESULT_INVALID") from exc
    plan_value = _json_object(
        _safe_read(
            workspace / "input/visual-pilot-plan.json",
            maximum_bytes=MAX_JSON_BYTES,
            expected_sha256=command.plan.sha256,
        )
    )
    result_payload = _safe_read(
        workspace / "manifests/visual-pilot-result.json",
        maximum_bytes=MAX_JSON_BYTES,
    )
    result_value = _json_object(result_payload)
    try:
        validate_contract("science-corpus-visual-pilot-plan", plan_value)
        validate_contract("science-corpus-visual-pilot-result", result_value)
        plan = LocalImageScienceCorpusVisualPilotPlan.model_validate(plan_value)
        result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)
        validate_science_visual_pilot_command(plan, command)
        validate_science_visual_pilot_result(plan, result)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_RESULT_INVALID") from exc
    if result.status != "SUCCEEDED" or command.attempt_id != workspace.name:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_RESULT_INVALID")

    declared = {"manifests/visual-pilot-result.json"}
    output_bytes = len(result_payload)
    output_records: tuple[ScienceVisualPageImage | ScienceVisualCandidate, ...] = (
        *result.page_images,
        *result.visual_candidates,
    )
    for record in output_records:
        payload = _safe_read(
            _member_path(workspace, record.member_path),
            maximum_bytes=MAX_PNG_BYTES,
            expected_sha256=record.sha256,
        )
        if len(payload) != record.size_bytes:
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_SIZE_MISMATCH")
        dimensions = _png_dimensions(payload)
        if isinstance(record, ScienceVisualPageImage) and dimensions != (
            record.width_px,
            record.height_px,
        ):
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_PNG_DIMENSION_MISMATCH")
        declared.add(record.member_path)
        output_bytes += len(payload)
        if output_bytes > MAX_OUTPUT_BYTES:
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_OUTPUT_TOO_LARGE")
    actual = {"manifests/visual-pilot-result.json"}
    for root_name in ("pages", "crops"):
        root = workspace / root_name
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_MEMBER_INVALID")
            if path.is_file():
                actual.add(path.relative_to(workspace).as_posix())
    if actual != declared:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_OUTPUT_CLOSURE_INVALID")
    return command, plan, result, result_payload, output_bytes


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if _safe_read(path, maximum_bytes=MAX_JSON_BYTES) != payload:
            raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_RECEIPT_CONFLICT")
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    if os.geteuid() != 0:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_ROOT_REQUIRED")
    if _ATTEMPT.fullmatch(args.attempt_id) is None or _COMMIT.fullmatch(args.source_commit) is None:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_ARGUMENT_INVALID")
    workspace = WORKSPACE_PARENT / args.attempt_id
    command, plan, result, result_payload, output_bytes = _load_workspace(workspace)
    if command.plan_sha256 != plan.plan_sha256:
        raise ScienceVisualPilotPublicationError("SCIENCE_VISUAL_PILOT_RESULT_INVALID")
    summary = {
        "attempt_id": command.attempt_id,
        "candidate_count": len(result.visual_candidates),
        "output_bytes": output_bytes,
        "page_count": len(result.page_images),
        "result_file_sha256": sha256_bytes(result_payload),
        "result_sha256": result.result_sha256,
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0

    engine = build_engine()
    adapter = LocalImageTrainingControlArtifactPublisher(
        ControlArtifactPublisher(engine, Settings.from_environment()),
        source_commit=args.source_commit,
    )
    pointer = adapter.commit_science_visual_pilot_result(result)
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / f"science-visual-pilot-publication-{command.attempt_id}.json"
    receipt_value = {
        "schema_version": "science-visual-pilot-publication-receipt/1.0",
        **summary,
        "result_artifact": pointer.model_dump(mode="json"),
        "source_commit": args.source_commit,
    }
    _write_receipt(receipt_path, content_json_bytes(receipt_value))
    print(
        json.dumps(
            {
                "artifact_id": pointer.artifact_id,
                "artifact_revision_id": pointer.artifact_revision_id,
                "attempt_id": command.attempt_id,
                "receipt": str(receipt_path),
                "result_file_sha256": pointer.sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
