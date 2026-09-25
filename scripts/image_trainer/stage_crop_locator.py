#!/usr/bin/env python3
"""Stage one approved crop-locator command without exposing PostgreSQL or NAS to the worker."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from eom_catalog_contracts import KnowledgeAnalysisResultV9, LegacyItemExtractionResult
from eom_catalog_contracts.validation import validate_contract as validate_catalog_contract
from eom_catalog_service.local_image_training_candidates import (
    AcceptedVisualTrainingSource,
    TrainingVisualCropSource,
    select_training_visual_crop_sources,
)
from eom_catalog_service.local_image_training_evaluation import align_training_holdout_plan
from eom_identifiers import canonical_json_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageTrainingRightsPolicy,
    LocalImageCropLocatorCommand,
    LocalImageCropLocatorSource,
    LocalImageQualityEvaluationPlan,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCropProposalOmission,
    content_sha256,
    validate_contract,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    AUTHORIZATION_MEMBER,
    AUTHORIZATION_SCHEMA_REF,
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, bindparam, text

REPOSITORY_ROOT = Path("/home/eom/EOM")
WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
TRAINER_USER = "eom-image"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PAGE_BYTES = 64 * 1024 * 1024


class CropLocatorStageError(RuntimeError):
    """Stable operator-facing staging failure."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_JSON_INVALID")
        value[key] = item
    return value


def _parse_json(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CropLocatorStageError("IMAGE_TRAINING_SOURCE_JSON_INVALID")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_JSON_INVALID")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization-artifact-id", required=True)
    parser.add_argument("--authorization-artifact-revision-id", required=True)
    parser.add_argument("--authorization-artifact-sha256", required=True)
    parser.add_argument("--holdout-template", type=Path, required=True)
    parser.add_argument("--holdout-template-file-sha256", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _require_release(source_commit: str) -> None:
    if os.geteuid() != 0:
        raise CropLocatorStageError("IMAGE_TRAINING_STAGE_ROOT_REQUIRED")
    try:
        head = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_RELEASE_INVALID") from exc
    if head != source_commit or dirty:
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_RELEASE_INVALID")
    if not WORKSPACE_PARENT.is_absolute() or WORKSPACE_PARENT.is_symlink():
        raise CropLocatorStageError("IMAGE_TRAINING_WORKSPACE_PARENT_INVALID")
    metadata = WORKSPACE_PARENT.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise CropLocatorStageError("IMAGE_TRAINING_WORKSPACE_PARENT_INVALID")


def _safe_read(path: Path, *, expected_sha256: str, maximum_bytes: int) -> bytes:
    if not path.is_absolute():
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_PATH_INVALID")
    current = Path(path.root)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_PATH_INVALID")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_READ_FAILED") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
        ):
            raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_FILE_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_FILE_TRUNCATED")
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
            raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_FILE_CHANGED")
    finally:
        os.close(descriptor)
    body = bytes(payload)
    if "sha256:" + hashlib.sha256(body).hexdigest() != expected_sha256:
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_HASH_MISMATCH")
    return body


def _write_exclusive(path: Path, payload: bytes, *, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode,
    )
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _manifest_member(manifest: object, member_path: str) -> Mapping[str, object]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise CropLocatorStageError("IMAGE_TRAINING_ARTIFACT_MANIFEST_INVALID")
    matches = [
        value
        for value in manifest["files"]
        if isinstance(value, dict) and value.get("file_name") == member_path
    ]
    if len(matches) != 1:
        raise CropLocatorStageError("IMAGE_TRAINING_ARTIFACT_MEMBER_INVALID")
    return cast(Mapping[str, object], matches[0])


def _load_artifact_member(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
    *,
    maximum_bytes: int,
) -> bytes:
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        row = (
            connection.execute(
                text(
                    """
                    SELECT ar.nas_path, ar.manifest, ar.approved AS revision_approved,
                           a.approved AS artifact_approved
                    FROM artifact_revisions ar
                    JOIN artifacts a ON a.logical_artifact_id = ar.logical_artifact_id
                    WHERE ar.logical_artifact_id = :artifact_id
                      AND ar.revision_id = :revision_id
                    """
                ),
                {
                    "artifact_id": pointer.artifact_id,
                    "revision_id": pointer.artifact_revision_id,
                },
            )
            .mappings()
            .one_or_none()
        )
    if row is None or not row["artifact_approved"] or not row["revision_approved"]:
        raise CropLocatorStageError("IMAGE_TRAINING_ARTIFACT_POINTER_INVALID")
    member = _manifest_member(row["manifest"], pointer.member_path)
    if (
        member.get("sha256") != pointer.sha256
        or member.get("schema_ref") != pointer.schema_ref
        or member.get("media_type") != pointer.media_type
    ):
        raise CropLocatorStageError("IMAGE_TRAINING_ARTIFACT_MEMBER_INVALID")
    return _safe_read(
        Path(str(row["nas_path"])) / pointer.member_path,
        expected_sha256=pointer.sha256,
        maximum_bytes=maximum_bytes,
    )


def _authorization_pointer(args: argparse.Namespace) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=args.authorization_artifact_id,
        artifact_revision_id=args.authorization_artifact_revision_id,
        member_path=AUTHORIZATION_MEMBER,
        schema_ref=AUTHORIZATION_SCHEMA_REF,
        media_type="application/json",
        sha256=args.authorization_artifact_sha256,
    )


def _load_authorization(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
) -> LocalImageTrainingAuthorization:
    payload = _load_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = _parse_json(payload)
        validate_contract("training-authorization", value)
        authorization = LocalImageTrainingAuthorization.model_validate(value)
    except (json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise CropLocatorStageError("IMAGE_TRAINING_AUTHORIZATION_INVALID") from exc
    if content_sha256(authorization.model_dump(mode="json")) != pointer.sha256:
        raise CropLocatorStageError("IMAGE_TRAINING_AUTHORIZATION_POINTER_MISMATCH")
    return authorization


def _load_holdout_template(args: argparse.Namespace) -> LocalImageQualityEvaluationPlan:
    payload = _safe_read(
        args.holdout_template,
        expected_sha256=args.holdout_template_file_sha256,
        maximum_bytes=MAX_JSON_BYTES,
    )
    try:
        value = _parse_json(payload)
        validate_contract("quality-evaluation-plan", value)
        return LocalImageQualityEvaluationPlan.model_validate(value)
    except (json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise CropLocatorStageError("IMAGE_TRAINING_HOLDOUT_TEMPLATE_INVALID") from exc


def _accepted_sources(
    engine: Engine,
    authorization: LocalImageTrainingAuthorization,
) -> tuple[AcceptedVisualTrainingSource, ...]:
    query = text(
        """
        SELECT o.item_revision_id,
               r.accepted_result_artifact_id, r.accepted_result_artifact_revision_id,
               r.accepted_result_sha256, rar.nas_path AS accepted_nas_path,
               rar.manifest AS accepted_manifest,
               a.result_artifact_id, a.result_artifact_revision_id,
               a.result_artifact_member_path, a.result_artifact_schema_ref,
               a.result_artifact_media_type, a.result_artifact_sha256,
               ear.nas_path AS extraction_nas_path, ear.manifest AS extraction_manifest,
               b.rights_policy_id, b.rights_policy_revision_id, b.rights_policy_sha256
        FROM assessment_item_occurrence_references o
        JOIN knowledge_analysis_runs r ON r.analysis_run_id = o.analysis_run_id
        JOIN legacy_item_extraction_acceptances a
          ON a.acceptance_id = o.extraction_acceptance_id
        JOIN assessment_source_bundle_revisions b
          ON b.assessment_source_bundle_revision_id = o.assessment_source_bundle_revision_id
        JOIN artifacts ra ON ra.logical_artifact_id = r.accepted_result_artifact_id
        JOIN artifact_revisions rar
          ON rar.logical_artifact_id = r.accepted_result_artifact_id
         AND rar.revision_id = r.accepted_result_artifact_revision_id
        JOIN artifacts ea ON ea.logical_artifact_id = a.result_artifact_id
        JOIN artifact_revisions ear
          ON ear.logical_artifact_id = a.result_artifact_id
         AND ear.revision_id = a.result_artifact_revision_id
        WHERE o.graph_snapshot_revision_id = :graph_revision_id
          AND r.state = 'ACCEPTED'
          AND r.canonical_request->>'schema_version' = 'knowledge-analysis-request/9.0'
          AND a.state = 'ACCEPTED'
          AND b.state IN ('REVIEWED','SUPERSEDED')
          AND ra.approved = true AND rar.approved = true
          AND ea.approved = true AND ear.approved = true
        ORDER BY o.item_revision_id
        """
    )
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        rows = (
            connection.execute(
                query,
                {"graph_revision_id": authorization.source_snapshot.graph_revision_id},
            )
            .mappings()
            .all()
        )
    if len(rows) != authorization.source_snapshot.target_count:
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_SET_INCOMPLETE")
    policies = {value.rights_policy_revision_id: value for value in authorization.rights_policies}
    sources: list[AcceptedVisualTrainingSource] = []
    target_ids: list[str] = []
    for row in rows:
        accepted_manifest = row["accepted_manifest"]
        if not isinstance(accepted_manifest, dict):
            raise CropLocatorStageError("IMAGE_TRAINING_ACCEPTED_RESULT_INVALID")
        accepted_member_path = accepted_manifest.get("primary_file")
        if not isinstance(accepted_member_path, str):
            raise CropLocatorStageError("IMAGE_TRAINING_ACCEPTED_RESULT_INVALID")
        accepted_member = _manifest_member(accepted_manifest, accepted_member_path)
        if accepted_member.get("sha256") != row["accepted_result_sha256"]:
            raise CropLocatorStageError("IMAGE_TRAINING_ACCEPTED_RESULT_INVALID")
        accepted_payload = _safe_read(
            Path(str(row["accepted_nas_path"])) / accepted_member_path,
            expected_sha256=str(row["accepted_result_sha256"]),
            maximum_bytes=MAX_JSON_BYTES,
        )
        extraction_member = _manifest_member(
            row["extraction_manifest"],
            str(row["result_artifact_member_path"]),
        )
        if (
            extraction_member.get("sha256") != row["result_artifact_sha256"]
            or extraction_member.get("schema_ref") != row["result_artifact_schema_ref"]
            or extraction_member.get("media_type") != row["result_artifact_media_type"]
        ):
            raise CropLocatorStageError("IMAGE_TRAINING_EXTRACTION_POINTER_INVALID")
        extraction_payload = _safe_read(
            Path(str(row["extraction_nas_path"])) / str(row["result_artifact_member_path"]),
            expected_sha256=str(row["result_artifact_sha256"]),
            maximum_bytes=MAX_JSON_BYTES,
        )
        try:
            accepted_value = _parse_json(accepted_payload)
            extraction_value = _parse_json(extraction_payload)
            validate_catalog_contract("knowledge-analysis-result-v9", accepted_value)
            validate_catalog_contract("legacy-item-extraction-result", extraction_value)
            accepted = KnowledgeAnalysisResultV9.model_validate(accepted_value)
            extraction = LegacyItemExtractionResult.model_validate(extraction_value)
        except (json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
            raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_RESULT_INVALID") from exc
        if accepted.source.item_revision_id != row["item_revision_id"]:
            raise CropLocatorStageError("IMAGE_TRAINING_ACCEPTED_RESULT_INVALID")
        policy = policies.get(str(row["rights_policy_revision_id"]))
        stored_policy = ImageTrainingRightsPolicy.model_validate(
            {
                "rights_policy_id": row["rights_policy_id"],
                "rights_policy_revision_id": row["rights_policy_revision_id"],
                "rights_policy_sha256": row["rights_policy_sha256"],
            }
        )
        if policy is None or policy != stored_policy:
            raise CropLocatorStageError("IMAGE_TRAINING_RIGHTS_POLICY_INVALID")
        target_ids.append(str(row["item_revision_id"]))
        sources.append(
            AcceptedVisualTrainingSource(
                accepted=accepted,
                extraction=extraction,
                rights_policy=policy,
            )
        )
    if (
        tuple(target_ids) != tuple(sorted(set(target_ids)))
        or content_sha256(tuple(target_ids)) != authorization.source_snapshot.target_set_sha256
    ):
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_SET_INVALID")
    return tuple(sources)


def _page_records(
    engine: Engine,
    sources: tuple[TrainingVisualCropSource, ...],
) -> dict[str, Mapping[str, object]]:
    revision_ids = tuple(
        sorted({value.source_page_image.artifact_revision_id for value in sources})
    )
    query = text(
        """
        SELECT ar.revision_id, ar.logical_artifact_id, ar.nas_path, ar.manifest,
               ar.approved AS revision_approved, a.approved AS artifact_approved
        FROM artifact_revisions ar
        JOIN artifacts a ON a.logical_artifact_id = ar.logical_artifact_id
        WHERE ar.revision_id IN :revision_ids
        """
    ).bindparams(bindparam("revision_ids", expanding=True))
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        rows = connection.execute(query, {"revision_ids": revision_ids}).mappings().all()
    by_revision = {str(row["revision_id"]): cast(Mapping[str, object], row) for row in rows}
    if len(by_revision) != len(revision_ids):
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_PAGE_POINTER_INVALID")
    return by_revision


def _stage_pages(
    *,
    stage_root: Path,
    sources: tuple[TrainingVisualCropSource, ...],
    records: Mapping[str, Mapping[str, object]],
    trainer_uid: int,
    trainer_gid: int,
) -> tuple[LocalImageCropLocatorSource, ...]:
    pages_root = stage_root / "pages"
    pages_root.mkdir(mode=0o750)
    os.chown(pages_root, 0, trainer_gid)
    staged_hashes: set[str] = set()
    values: list[LocalImageCropLocatorSource] = []
    for source in sources:
        pointer = source.source_page_image
        payload = _source_page_payload(source=source, records=records)
        filename = pointer.sha256.removeprefix("sha256:") + ".png"
        if pointer.sha256 not in staged_hashes:
            target = pages_root / filename
            _write_exclusive(target, payload, mode=0o640)
            os.chown(target, 0, trainer_gid)
            staged_hashes.add(pointer.sha256)
        values.append(
            LocalImageCropLocatorSource(
                item_revision_id=source.item_revision_id,
                extraction_result=source.extraction_result,
                source_anchor_id=source.source_anchor_id,
                visual_pattern_ids=source.visual_pattern_ids,
                source_page_image=source.source_page_image,
                staged_page_member="pages/" + filename,
                physical_page=source.physical_page,
                context_bounding_box=source.context_bounding_box,
                rights_policy=source.rights_policy,
                representation_kind=source.representation_kind,
                rendering_mode=source.rendering_mode,
                visual_features=source.visual_features,
            )
        )
    if not values:
        raise CropLocatorStageError("IMAGE_TRAINING_CROP_SOURCE_SET_EMPTY")
    if trainer_uid == 0:
        raise CropLocatorStageError("IMAGE_TRAINING_RUNTIME_IDENTITY_INVALID")
    return tuple(values)


def _source_page_payload(
    *,
    source: TrainingVisualCropSource,
    records: Mapping[str, Mapping[str, object]],
) -> bytes:
    pointer = source.source_page_image
    row = records[pointer.artifact_revision_id]
    member = _manifest_member(row["manifest"], pointer.member_path)
    if (
        row["logical_artifact_id"] != pointer.artifact_id
        or not row["artifact_approved"]
        or not row["revision_approved"]
        or member.get("sha256") != pointer.sha256
        or member.get("schema_ref") != pointer.schema_ref
        or member.get("media_type") != "image/png"
    ):
        raise CropLocatorStageError("IMAGE_TRAINING_SOURCE_PAGE_POINTER_INVALID")
    return _safe_read(
        Path(str(row["nas_path"])) / pointer.member_path,
        expected_sha256=pointer.sha256,
        maximum_bytes=MAX_PAGE_BYTES,
    )


def _build_command(
    *,
    authorization: LocalImageTrainingAuthorization,
    authorization_pointer: ImageEvaluationArtifactMember,
    holdout_plan: LocalImageQualityEvaluationPlan,
    holdout_pointer: ImageEvaluationArtifactMember,
    sources: tuple[LocalImageCropLocatorSource, ...],
    omissions: tuple[LocalImageTrainingCropProposalOmission, ...],
    created_at: datetime,
    created_by: str,
) -> LocalImageCropLocatorCommand:
    body = {
        "schema_version": "local-image-crop-locator-command/1.0",
        "source_snapshot": authorization.source_snapshot.model_dump(mode="json"),
        "training_authorization": authorization_pointer.model_dump(mode="json"),
        "holdout_evaluation_plan": holdout_pointer.model_dump(mode="json"),
        "holdout_sample_ids": sorted(value.sample_id for value in holdout_plan.samples),
        "holdout_source_anchor_ids": sorted(
            value.source_anchor_id for value in holdout_plan.samples
        ),
        "selection_query_revision": "local-image-lora-crop-source-query/1.0",
        "locator_revision": "local-image-visual-crop-locator/1.0",
        "sources": [value.model_dump(mode="json") for value in sources],
        "preliminary_omissions": [value.model_dump(mode="json") for value in omissions],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
        "output_member": "outputs/crop-locator-result.json",
    }
    identity = content_sha256(body).removeprefix("sha256:")
    command_body = {**body, "locator_run_id": "imgcroplocator_" + identity[:32]}
    value = {**command_body, "command_sha256": content_sha256(command_body)}
    try:
        validate_contract("crop-locator-command", value)
        return LocalImageCropLocatorCommand.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise CropLocatorStageError("IMAGE_TRAINING_CROP_LOCATOR_COMMAND_INVALID") from exc


def main() -> None:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    if args.created_at.tzinfo is None or args.created_at.utcoffset() != UTC.utcoffset(
        args.created_at
    ):
        raise CropLocatorStageError("IMAGE_TRAINING_TIMESTAMP_INVALID")
    account = pwd.getpwnam(TRAINER_USER)
    trainer_uid = account.pw_uid
    trainer_gid = grp.getgrnam(TRAINER_USER).gr_gid
    engine = build_engine()
    temporary: Path | None = None
    try:
        authorization_pointer = _authorization_pointer(args)
        authorization = _load_authorization(engine, authorization_pointer)
        holdout_plan = align_training_holdout_plan(
            template=_load_holdout_template(args),
            source_snapshot=authorization.source_snapshot,
            created_at=args.created_at,
        )
        accepted = _accepted_sources(engine, authorization)
        holdout_anchor_ids = tuple(sorted(value.source_anchor_id for value in holdout_plan.samples))
        selected, omissions = select_training_visual_crop_sources(
            sources=accepted,
            holdout_source_anchor_ids=holdout_anchor_ids,
        )
        if not selected:
            raise CropLocatorStageError("IMAGE_TRAINING_CROP_SOURCE_SET_EMPTY")
        records = _page_records(engine, selected)
        if args.preflight_only:
            for source in selected:
                _source_page_payload(source=source, records=records)
            print(
                json.dumps(
                    {
                        "status": "PREFLIGHT_PASS",
                        "source_count": len(selected),
                        "unique_page_count": len(
                            {value.source_page_image.sha256 for value in selected}
                        ),
                        "preliminary_omission_count": len(omissions),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return
        temporary = Path(tempfile.mkdtemp(prefix=".crop-locator-staging.", dir=WORKSPACE_PARENT))
        os.chmod(temporary, 0o770)
        os.chown(temporary, 0, trainer_gid)
        staged_sources = _stage_pages(
            stage_root=temporary,
            sources=selected,
            records=records,
            trainer_uid=trainer_uid,
            trainer_gid=trainer_gid,
        )
        holdout_pointer = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        ).commit_evaluation_plan(holdout_plan)
        command = _build_command(
            authorization=authorization,
            authorization_pointer=authorization_pointer,
            holdout_plan=holdout_plan,
            holdout_pointer=holdout_pointer,
            sources=staged_sources,
            omissions=omissions,
            created_at=args.created_at,
            created_by=args.created_by,
        )
        outputs = temporary / "outputs"
        outputs.mkdir(mode=0o700)
        os.chown(outputs, trainer_uid, trainer_gid)
        review = temporary / "review"
        review.mkdir(mode=0o700)
        os.chown(review, trainer_uid, trainer_gid)
        command_path = temporary / "command.json"
        _write_exclusive(
            command_path,
            canonical_json_bytes(command.model_dump(mode="json")),
            mode=0o640,
        )
        os.chown(command_path, 0, trainer_gid)
        # The worker receives immutable root-owned inputs and may write only to its pre-created
        # output directories.  Group traversal is sufficient; workspace-wide write access is not.
        os.chmod(temporary, 0o750)
        workspace = WORKSPACE_PARENT / command.locator_run_id
        if workspace.exists() or workspace.is_symlink():
            raise CropLocatorStageError("IMAGE_TRAINING_WORKSPACE_EXISTS")
        os.rename(temporary, workspace)
        temporary = None
        parent_descriptor = os.open(
            WORKSPACE_PARENT,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        engine.dispose()
        if temporary is not None:
            shutil.rmtree(temporary)
    print(
        json.dumps(
            {
                "status": "STAGED",
                "locator_run_id": command.locator_run_id,
                "command_sha256": command.command_sha256,
                "source_count": len(command.sources),
                "preliminary_omission_count": len(command.preliminary_omissions),
                "workspace": str(workspace),
                "systemd_unit": f"eom-image-crop-locator@{command.locator_run_id}.service",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
