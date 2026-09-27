#!/usr/bin/env python3
"""Build a closed science visual subject inventory from immutable accepted sources."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_service.science_visual_subjects import (
    AcceptedVisualSubjectSource,
    project_science_visual_subject_inventory,
)
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageScienceVisualSubjectInventory,
    content_json_bytes,
    content_sha256,
    validate_contract,
)
from eom_orchestrator.database import build_engine
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, text

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    _accepted_sources,
    _load_artifact_member,
    _load_authorization,
    _parse_json,
)

PATTERN_INVENTORY_MEMBER = "manifests/science-visual-campaign-pattern-inventory.json"
PATTERN_INVENTORY_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-campaign-pattern-inventory/1.0"
)


class ScienceVisualSubjectInventoryBuildError(RuntimeError):
    """Stable operator error for subject inventory construction."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization-artifact-id", required=True)
    parser.add_argument("--authorization-artifact-revision-id", required=True)
    parser.add_argument("--authorization-artifact-sha256", required=True)
    parser.add_argument("--pattern-inventory-artifact-id", required=True)
    parser.add_argument("--pattern-inventory-artifact-revision-id", required=True)
    parser.add_argument("--pattern-inventory-artifact-sha256", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _pointer(
    *,
    artifact_id: str,
    artifact_revision_id: str,
    member_path: str,
    schema_ref: str,
    sha256: str,
) -> ImageEvaluationArtifactMember:
    try:
        return ImageEvaluationArtifactMember(
            artifact_id=artifact_id,
            artifact_revision_id=artifact_revision_id,
            member_path=member_path,
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=sha256,
        )
    except PydanticValidationError as exc:
        raise ScienceVisualSubjectInventoryBuildError(
            "SCIENCE_VISUAL_SUBJECT_POINTER_INVALID"
        ) from exc


def _artifact_member(manifest: object, member_path: str) -> Mapping[str, object]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ScienceVisualSubjectInventoryBuildError(
            "SCIENCE_VISUAL_SUBJECT_ARTIFACT_MANIFEST_INVALID"
        )
    matches = tuple(
        value
        for value in manifest["files"]
        if isinstance(value, dict) and value.get("file_name") == member_path
    )
    if len(matches) != 1:
        raise ScienceVisualSubjectInventoryBuildError(
            "SCIENCE_VISUAL_SUBJECT_ARTIFACT_MEMBER_INVALID"
        )
    return matches[0]


def _source_pointers(
    engine: Engine,
    *,
    graph_revision_id: str,
) -> dict[str, tuple[ImageEvaluationArtifactMember, ImageEvaluationArtifactMember]]:
    query = text(
        """
        SELECT o.item_revision_id,
               r.accepted_result_artifact_id, r.accepted_result_artifact_revision_id,
               r.accepted_result_sha256, rar.manifest AS accepted_manifest,
               a.result_artifact_id, a.result_artifact_revision_id,
               a.result_artifact_member_path, a.result_artifact_schema_ref,
               a.result_artifact_media_type, a.result_artifact_sha256,
               ear.manifest AS extraction_manifest
        FROM assessment_item_occurrence_references o
        JOIN knowledge_analysis_runs r ON r.analysis_run_id = o.analysis_run_id
        JOIN legacy_item_extraction_acceptances a
          ON a.acceptance_id = o.extraction_acceptance_id
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
          AND ra.approved = true AND rar.approved = true
          AND ea.approved = true AND ear.approved = true
        ORDER BY o.item_revision_id
        """
    )
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        rows = connection.execute(query, {"graph_revision_id": graph_revision_id}).mappings().all()
    resolved: dict[str, tuple[ImageEvaluationArtifactMember, ImageEvaluationArtifactMember]] = {}
    for row in rows:
        accepted_path = row["accepted_manifest"].get("primary_file")
        if not isinstance(accepted_path, str):
            raise ScienceVisualSubjectInventoryBuildError(
                "SCIENCE_VISUAL_SUBJECT_ACCEPTED_POINTER_INVALID"
            )
        accepted_member = _artifact_member(row["accepted_manifest"], accepted_path)
        extraction_path = str(row["result_artifact_member_path"])
        extraction_member = _artifact_member(row["extraction_manifest"], extraction_path)
        if (
            accepted_member.get("sha256") != row["accepted_result_sha256"]
            or extraction_member.get("sha256") != row["result_artifact_sha256"]
        ):
            raise ScienceVisualSubjectInventoryBuildError(
                "SCIENCE_VISUAL_SUBJECT_SOURCE_POINTER_INVALID"
            )
        item_revision_id = str(row["item_revision_id"])
        if item_revision_id in resolved:
            raise ScienceVisualSubjectInventoryBuildError("SCIENCE_VISUAL_SUBJECT_SOURCE_DUPLICATE")
        resolved[item_revision_id] = (
            _pointer(
                artifact_id=str(row["accepted_result_artifact_id"]),
                artifact_revision_id=str(row["accepted_result_artifact_revision_id"]),
                member_path=accepted_path,
                schema_ref=str(accepted_member["schema_ref"]),
                sha256=str(row["accepted_result_sha256"]),
            ),
            _pointer(
                artifact_id=str(row["result_artifact_id"]),
                artifact_revision_id=str(row["result_artifact_revision_id"]),
                member_path=extraction_path,
                schema_ref=str(row["result_artifact_schema_ref"]),
                sha256=str(row["result_artifact_sha256"]),
            ),
        )
    return resolved


def _safe_write(path: Path, payload: bytes) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ScienceVisualSubjectInventoryBuildError("SCIENCE_VISUAL_SUBJECT_OUTPUT_PATH_INVALID")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ScienceVisualSubjectInventoryBuildError("SCIENCE_VISUAL_SUBJECT_OUTPUT_PATH_INVALID")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ScienceVisualSubjectInventoryBuildError(
                "SCIENCE_VISUAL_SUBJECT_OUTPUT_WRITE_INVALID"
            )
    finally:
        os.close(descriptor)


def build_science_visual_subject_inventory(
    engine: Engine,
    *,
    authorization_pointer: ImageEvaluationArtifactMember,
    pattern_pointer: ImageEvaluationArtifactMember,
    created_at: datetime,
    created_by: str,
) -> LocalImageScienceVisualSubjectInventory:
    """Resolve exact immutable sources and build one closed subject inventory."""

    authorization = _load_authorization(engine, authorization_pointer)
    pattern_payload = _load_artifact_member(engine, pattern_pointer, maximum_bytes=MAX_JSON_BYTES)
    try:
        pattern_value = _parse_json(pattern_payload)
        validate_contract("science-visual-campaign-pattern-inventory", pattern_value)
        pattern_inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(
            pattern_value
        )
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualSubjectInventoryBuildError(
            "SCIENCE_VISUAL_SUBJECT_PATTERN_INVENTORY_INVALID"
        ) from exc
    if (
        content_json_bytes(pattern_inventory.model_dump(mode="json")) != pattern_payload
        or content_sha256(pattern_inventory.model_dump(mode="json")) != pattern_pointer.sha256
    ):
        raise ScienceVisualSubjectInventoryBuildError(
            "SCIENCE_VISUAL_SUBJECT_PATTERN_INVENTORY_POINTER_MISMATCH"
        )
    accepted_sources = _accepted_sources(engine, authorization)
    pointers = _source_pointers(
        engine, graph_revision_id=authorization.source_snapshot.graph_revision_id
    )
    sources: list[AcceptedVisualSubjectSource] = []
    for source in accepted_sources:
        item_revision_id = source.accepted.source.item_revision_id
        pair = pointers.get(item_revision_id)
        if pair is None:
            raise ScienceVisualSubjectInventoryBuildError(
                "SCIENCE_VISUAL_SUBJECT_SOURCE_POINTER_MISSING"
            )
        sources.append(
            AcceptedVisualSubjectSource(
                accepted=source.accepted,
                accepted_result=pair[0],
                extraction=source.extraction,
                extraction_result=pair[1],
            )
        )
    return project_science_visual_subject_inventory(
        sources=tuple(sources),
        training_authorization=authorization_pointer,
        pattern_inventory=pattern_pointer,
        target_set_sha256=authorization.source_snapshot.target_set_sha256,
        created_at=created_at,
        created_by=created_by,
    )


def main() -> int:
    args = _parser().parse_args()
    if args.created_at.tzinfo is None or args.created_at.utcoffset() != UTC.utcoffset(
        args.created_at
    ):
        raise ScienceVisualSubjectInventoryBuildError("SCIENCE_VISUAL_SUBJECT_CREATED_AT_NOT_UTC")
    authorization_pointer = _pointer(
        artifact_id=args.authorization_artifact_id,
        artifact_revision_id=args.authorization_artifact_revision_id,
        member_path="manifests/training-authorization.json",
        schema_ref="eom://schemas/image-provider/local-image-training-authorization/1.0",
        sha256=args.authorization_artifact_sha256,
    )
    pattern_pointer = _pointer(
        artifact_id=args.pattern_inventory_artifact_id,
        artifact_revision_id=args.pattern_inventory_artifact_revision_id,
        member_path=PATTERN_INVENTORY_MEMBER,
        schema_ref=PATTERN_INVENTORY_SCHEMA_REF,
        sha256=args.pattern_inventory_artifact_sha256,
    )
    engine = build_engine()
    try:
        inventory = build_science_visual_subject_inventory(
            engine,
            authorization_pointer=authorization_pointer,
            pattern_pointer=pattern_pointer,
            created_at=args.created_at,
            created_by=args.created_by,
        )
    finally:
        engine.dispose()
    value = inventory.model_dump(mode="json")
    validate_contract("science-visual-subject-inventory", value)
    summary = {
        "blocked_subject_count": sum(
            subject.render_route == "BLOCKED" for subject in inventory.subjects
        ),
        "covered_visual_observation_count": inventory.covered_visual_observation_count,
        "inventory_id": inventory.inventory_id,
        "inventory_sha256": inventory.inventory_sha256,
        "omission_count": len(inventory.omissions),
        "source_item_count": inventory.source_item_count,
        "source_visual_observation_count": inventory.source_visual_observation_count,
        "subject_count": len(inventory.subjects),
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0
    _safe_write(args.output, content_json_bytes(value))
    print(json.dumps({**summary, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
