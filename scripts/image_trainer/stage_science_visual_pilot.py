#!/usr/bin/env python3
"""Publish controls and stage one bounded science-corpus visual pilot attempt."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eom_catalog_contracts import ScienceAssessmentWebCorpusManifestV2
from eom_catalog_service.science_visual_pilot import (
    build_science_corpus_training_authorization,
    build_science_visual_pilot_plan,
    select_science_visual_pilot_sources,
)
from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotPlan,
    ScienceVisualGuidanceAuthority,
    ScienceVisualToolIdentity,
    ScienceVisualToolSet,
    content_json_bytes,
    content_sha256,
    validate_contract,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    CropLocatorStageError,
    _load_artifact_member,
    _parse_json,
    _write_exclusive,
)

REPOSITORY_ROOT = Path("/home/eom/EOM")
WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
TRAINER_USER = "eom-image"
CORPUS_MEMBER = "corpus-manifest.json"
CORPUS_SCHEMA_REF = "eom://schemas/legacy-assessment/science-assessment-web-corpus-manifest/2.0"
GuidanceRole = Literal[
    "AUTHORING_TEAM_LEAD",
    "HWPX_EDITOR_TEAM_LEAD",
    "KICE_ILLUSTRATION_GUIDE",
]
GUIDANCE_PATHS: tuple[tuple[GuidanceRole, str], ...] = (
    (
        "AUTHORING_TEAM_LEAD",
        "config/control-plane/standard-item-v5/references/guidance/"
        "content-team-integrated-science-authoring-v05.md",
    ),
    (
        "HWPX_EDITOR_TEAM_LEAD",
        "config/control-plane/standard-item-v6/references/guidance/"
        "content-team-hwp-question-editor-handoff-v1.md",
    ),
    (
        "KICE_ILLUSTRATION_GUIDE",
        "content/image-specs/kice-integrated-science-illustration-v1.md",
    ),
)


class ScienceVisualPilotStageError(RuntimeError):
    """Stable operator-facing staging failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-artifact-id", required=True)
    parser.add_argument("--corpus-artifact-revision-id", required=True)
    parser.add_argument("--corpus-artifact-sha256", required=True)
    parser.add_argument("--approved-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--selection-seed-sha256", required=True)
    parser.add_argument("--source-limit", type=int, default=36)
    parser.add_argument("--page-limit", type=int, default=192)
    parser.add_argument("--candidate-limit", type=int, default=256)
    parser.add_argument("--lora-crop-limit", type=int, default=24)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ScienceVisualPilotStageError(f"SCIENCE_VISUAL_PILOT_{field}_NOT_UTC")


def _require_release(source_commit: str) -> None:
    if os.geteuid() != 0:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_STAGE_ROOT_REQUIRED")
    try:
        head = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout.strip()
        tracked_dirty = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_SOURCE_RELEASE_INVALID") from exc
    if head != source_commit or tracked_dirty:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_SOURCE_RELEASE_INVALID")
    metadata = WORKSPACE_PARENT.lstat()
    if (
        WORKSPACE_PARENT.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o3770
    ):
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_WORKSPACE_PARENT_INVALID")


def _git_blob(source_commit: str, logical_name: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "show", f"{source_commit}:{logical_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_GUIDANCE_INVALID") from exc
    if completed.returncode != 0 or not 1 <= len(completed.stdout) <= 4 * 1024 * 1024:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_GUIDANCE_INVALID")
    return completed.stdout


def _read_executable(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_TOOL_INVALID") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 256 * 1024 * 1024
        ):
            raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_TOOL_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_TOOL_INVALID")
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
            raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_TOOL_INVALID")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _tool(
    path_value: Literal["/usr/bin/pdftoppm", "/usr/bin/tesseract"],
    *version_args: str,
) -> ScienceVisualToolIdentity:
    path = Path(path_value)
    payload = _read_executable(path)
    try:
        completed = subprocess.run(
            [str(path), *version_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=15,
        )
        version_line = completed.stdout.decode("utf-8", errors="strict").splitlines()[0].strip()
    except (IndexError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_TOOL_INVALID") from exc
    if completed.returncode != 0:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_TOOL_INVALID")
    return ScienceVisualToolIdentity(
        path=path_value,
        sha256=sha256_bytes(payload),
        version=version_line,
    )


def _guidance(source_commit: str) -> tuple[ScienceVisualGuidanceAuthority, ...]:
    return tuple(
        ScienceVisualGuidanceAuthority(
            role=role,
            logical_name=logical_name,
            source_commit=source_commit,
            sha256=sha256_bytes(_git_blob(source_commit, logical_name)),
        )
        for role, logical_name in GUIDANCE_PATHS
    )


def _corpus_pointer(args: argparse.Namespace) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=args.corpus_artifact_id,
        artifact_revision_id=args.corpus_artifact_revision_id,
        member_path=CORPUS_MEMBER,
        schema_ref=CORPUS_SCHEMA_REF,
        media_type="application/json",
        sha256=args.corpus_artifact_sha256,
    )


def _load_corpus(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
) -> ScienceAssessmentWebCorpusManifestV2:
    payload = _load_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = _parse_json(payload)
        return ScienceAssessmentWebCorpusManifestV2.model_validate(value)
    except (CropLocatorStageError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_CORPUS_INVALID") from exc


def _build_command(
    *,
    plan: LocalImageScienceCorpusVisualPilotPlan,
    plan_pointer: ImageEvaluationArtifactMember,
    requested_at: datetime,
    requested_by: str,
) -> LocalImageScienceCorpusVisualPilotCommand:
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-command/1.0",
        "plan": plan_pointer.model_dump(mode="json"),
        "plan_sha256": plan.plan_sha256,
        "staged_plan_member": "input/visual-pilot-plan.json",
        "staged_sources": tuple(
            {
                "document_id": source.document_id,
                "staged_pdf_member": f"input/pdfs/{source.document_id}.pdf",
                "sha256": source.pdf.sha256,
                "bytes": source.bytes,
                "page_count": source.page_count,
            }
            for source in plan.selected_sources
        ),
        "result_member": "manifests/visual-pilot-result.json",
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "requested_by": requested_by,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["attempt_id"] = "imgscivisattempt_" + identity[:32]
    body["command_sha256"] = content_sha256(body)
    command = LocalImageScienceCorpusVisualPilotCommand.model_validate(body)
    validate_contract("science-corpus-visual-pilot-command", command.model_dump(mode="json"))
    return command


def _chown_workspace(workspace: Path) -> None:
    identity = pwd.getpwnam(TRAINER_USER)
    for path in sorted(workspace.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_WORKSPACE_INVALID")
        os.chown(path, identity.pw_uid, identity.pw_gid, follow_symlinks=False)
        os.chmod(path, 0o700 if stat.S_ISDIR(metadata.st_mode) else 0o600)
    os.chown(workspace, identity.pw_uid, identity.pw_gid, follow_symlinks=False)
    os.chmod(workspace, 0o700)


def _stage_workspace(
    *,
    engine: Engine,
    plan: LocalImageScienceCorpusVisualPilotPlan,
    plan_pointer: ImageEvaluationArtifactMember,
    command: LocalImageScienceCorpusVisualPilotCommand,
) -> Path:
    workspace = WORKSPACE_PARENT / command.attempt_id
    if workspace.exists() or workspace.is_symlink():
        raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_WORKSPACE_EXISTS")
    workspace.mkdir(mode=0o700)
    try:
        input_root = workspace / "input"
        input_root.mkdir(mode=0o700)
        pdf_root = input_root / "pdfs"
        pdf_root.mkdir(mode=0o700)
        plan_payload = _load_artifact_member(engine, plan_pointer, maximum_bytes=MAX_JSON_BYTES)
        _write_exclusive(input_root / "visual-pilot-plan.json", plan_payload, mode=0o600)
        source_by_document = {value.document_id: value for value in plan.selected_sources}
        for staged in command.staged_sources:
            source = source_by_document[staged.document_id]
            payload = _load_artifact_member(engine, source.pdf, maximum_bytes=100 * 1024 * 1024)
            if len(payload) != staged.bytes:
                raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_SOURCE_SIZE_MISMATCH")
            _write_exclusive(workspace / staged.staged_pdf_member, payload, mode=0o600)
        _write_exclusive(
            workspace / "command.json",
            content_json_bytes(command.model_dump(mode="json")),
            mode=0o600,
        )
        _chown_workspace(workspace)
        return workspace
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def _write_receipt(
    *,
    command: LocalImageScienceCorpusVisualPilotCommand,
    plan_pointer: ImageEvaluationArtifactMember,
    authorization_pointer: ImageEvaluationArtifactMember,
    workspace: Path,
) -> Path:
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt = STATE_ROOT / f"science-visual-pilot-stage-{command.attempt_id}.json"
    value = {
        "schema_version": "science-visual-pilot-stage-receipt/1.0",
        "attempt_id": command.attempt_id,
        "command_sha256": command.command_sha256,
        "plan": plan_pointer.model_dump(mode="json"),
        "training_authorization": authorization_pointer.model_dump(mode="json"),
        "workspace": str(workspace),
        "systemd_unit": f"eom-image-science-visual-pilot@{command.attempt_id}.service",
    }
    _write_exclusive(receipt, content_json_bytes(value), mode=0o600)
    return receipt


def main() -> int:
    args = _parser().parse_args()
    _require_utc(args.approved_at, "APPROVAL")
    _require_utc(args.created_at, "CREATION")
    _require_release(args.source_commit)
    engine = build_engine()
    corpus_pointer = _corpus_pointer(args)
    corpus = _load_corpus(engine, corpus_pointer)
    selected = select_science_visual_pilot_sources(
        corpus.documents,
        selection_seed_sha256=args.selection_seed_sha256,
        source_limit=args.source_limit,
        page_limit=args.page_limit,
    )
    for source in selected:
        payload = _load_artifact_member(engine, source.pdf, maximum_bytes=100 * 1024 * 1024)
        if len(payload) != source.bytes:
            raise ScienceVisualPilotStageError("SCIENCE_VISUAL_PILOT_SOURCE_SIZE_MISMATCH")
    guidance = _guidance(args.source_commit)
    tools = ScienceVisualToolSet(
        pdftoppm=_tool("/usr/bin/pdftoppm", "-v"),
        tesseract=_tool("/usr/bin/tesseract", "--version"),
    )
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "preflight": "PASS",
                    "selected_sources": len(selected),
                    "selected_pages": sum(value.page_count for value in selected),
                },
                sort_keys=True,
            )
        )
        return 0

    publisher = LocalImageTrainingControlArtifactPublisher(
        ControlArtifactPublisher(engine, Settings.from_environment()),
        source_commit=args.source_commit,
    )
    authorization = build_science_corpus_training_authorization(
        corpus=corpus,
        corpus_manifest=corpus_pointer,
        approved_at=args.approved_at,
        approved_by=args.approved_by,
    )
    authorization_pointer = publisher.commit_science_corpus_authorization(authorization)
    plan = build_science_visual_pilot_plan(
        corpus=corpus,
        corpus_manifest=corpus_pointer,
        authorization=authorization,
        authorization_pointer=authorization_pointer,
        selection_seed_sha256=args.selection_seed_sha256,
        guidance_authorities=guidance,
        tools=tools,
        source_commit=args.source_commit,
        created_at=args.created_at,
        created_by=args.created_by,
        source_limit=args.source_limit,
        page_limit=args.page_limit,
        max_visual_candidates=args.candidate_limit,
        max_lora_training_crops=args.lora_crop_limit,
    )
    plan_pointer = publisher.commit_science_visual_pilot_plan(plan)
    command = _build_command(
        plan=plan,
        plan_pointer=plan_pointer,
        requested_at=args.created_at,
        requested_by=args.created_by,
    )
    workspace = _stage_workspace(
        engine=engine,
        plan=plan,
        plan_pointer=plan_pointer,
        command=command,
    )
    receipt = _write_receipt(
        command=command,
        plan_pointer=plan_pointer,
        authorization_pointer=authorization_pointer,
        workspace=workspace,
    )
    print(
        json.dumps(
            {
                "attempt_id": command.attempt_id,
                "receipt": str(receipt),
                "systemd_unit": f"eom-image-science-visual-pilot@{command.attempt_id}.service",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
