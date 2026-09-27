#!/usr/bin/env python3
"""Stage one pinned science-subject multi-seed run for the isolated worker."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import tempfile
from pathlib import Path
from typing import Literal, cast

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkResult,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
    LocalImageScienceVisualSubjectMultiseedCommand,
    LocalImageScienceVisualSubjectMultiseedPlan,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_science_visual_subject_benchmark_review,
    validate_science_visual_subject_multiseed_plan,
)
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_member,
)
from eom_orchestrator.database import build_engine
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    WORKSPACE_PARENT,
    _parse_json,
    _require_release,
    _write_exclusive,
)

TRAINER_USER = "eom-image"
MAX_ADAPTER_BYTES = 1024 * 1024 * 1024


class ScienceSubjectMultiseedStageError(RuntimeError):
    """Stable operator error for multi-seed staging."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-artifact-id", required=True)
    parser.add_argument("--plan-artifact-revision-id", required=True)
    parser.add_argument("--plan-artifact-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _pointer(
    *,
    artifact_id: str,
    artifact_revision_id: str,
    member_path: str,
    schema_ref: str,
    media_type: str,
    sha256: str,
) -> ImageEvaluationArtifactMember:
    try:
        return ImageEvaluationArtifactMember(
            artifact_id=artifact_id,
            artifact_revision_id=artifact_revision_id,
            member_path=member_path,
            schema_ref=schema_ref,
            media_type=media_type,
            sha256=sha256,
        )
    except ValueError as exc:
        raise ScienceSubjectMultiseedStageError(
            "SCIENCE_SUBJECT_MULTISEED_POINTER_INVALID"
        ) from exc


def _resolve(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
    *,
    maximum_bytes: int,
) -> bytes:
    try:
        return resolve_control_artifact_member(engine, pointer, maximum_bytes=maximum_bytes)
    except ControlArtifactResolutionError as exc:
        raise ScienceSubjectMultiseedStageError(
            "SCIENCE_SUBJECT_MULTISEED_POINTER_RESOLUTION_FAILED"
        ) from exc


def _typed[T: BaseModel](payload: bytes, *, contract: str, model: type[T]) -> T:
    try:
        value = _parse_json(payload)
        validate_contract(contract, value)
        parsed = model.model_validate(value)
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise ScienceSubjectMultiseedStageError("SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID") from exc
    canonical = content_json_bytes(parsed.model_dump(mode="json"))
    if payload not in {canonical, canonical + b"\n"}:
        raise ScienceSubjectMultiseedStageError("SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID")
    return parsed


def _command(
    *,
    plan_pointer: ImageEvaluationArtifactMember,
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
    source_commit: str,
) -> LocalImageScienceVisualSubjectMultiseedCommand:
    body = {
        "schema_version": "local-image-science-visual-subject-multiseed-command/1.0",
        "plan": plan_pointer.model_dump(mode="json"),
        "plan_sha256": plan.plan_sha256,
        "staged_plan_path": "inputs/subject-multiseed-plan.json",
        "staged_subject_inventory_path": "inputs/science-visual-subject-inventory.json",
        "staged_initial_benchmark_plan_path": "inputs/science-visual-subject-benchmark-plan.json",
        "staged_initial_quality_review_path": (
            "inputs/science-visual-subject-benchmark-review.json"
        ),
        "staged_adapter_manifest_path": "inputs/adapter/adapter-manifest.json",
        "staged_adapter_model_path": "inputs/adapter/adapter_model.safetensors",
        "staged_adapter_config_path": "inputs/adapter/adapter_config.json",
        "output_directory": "outputs",
        "source_commit": source_commit,
    }
    identity = content_sha256(body).removeprefix("sha256:")[:32]
    with_id = {**body, "run_id": f"imgscisubjectmultiseedrun_{identity}"}
    value = {**with_id, "command_sha256": content_sha256(with_id)}
    try:
        validate_contract("science-visual-subject-multiseed-command", value)
        return LocalImageScienceVisualSubjectMultiseedCommand.model_validate(value)
    except ValueError as exc:
        raise ScienceSubjectMultiseedStageError(
            "SCIENCE_SUBJECT_MULTISEED_COMMAND_INVALID"
        ) from exc


def _stage_file(path: Path, payload: bytes, *, trainer_gid: int) -> None:
    _write_exclusive(path, payload, mode=0o440)
    os.chown(path, 0, trainer_gid)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    plan_pointer = _pointer(
        artifact_id=args.plan_artifact_id,
        artifact_revision_id=args.plan_artifact_revision_id,
        member_path="manifests/science-visual-subject-multiseed-plan.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-plan/1.0"
        ),
        media_type="application/json",
        sha256=args.plan_artifact_sha256,
    )
    engine = build_engine()
    temporary: Path | None = None
    try:
        plan_payload = _resolve(engine, plan_pointer, maximum_bytes=MAX_JSON_BYTES)
        plan = _typed(
            plan_payload,
            contract="science-visual-subject-multiseed-plan",
            model=LocalImageScienceVisualSubjectMultiseedPlan,
        )
        inventory_payload = _resolve(engine, plan.subject_inventory, maximum_bytes=MAX_JSON_BYTES)
        inventory = _typed(
            inventory_payload,
            contract="science-visual-subject-inventory",
            model=LocalImageScienceVisualSubjectInventory,
        )
        initial_plan_payload = _resolve(
            engine, plan.initial_benchmark_plan, maximum_bytes=MAX_JSON_BYTES
        )
        initial_plan = _typed(
            initial_plan_payload,
            contract="science-visual-subject-benchmark-plan",
            model=LocalImageScienceVisualSubjectBenchmarkPlan,
        )
        initial_review_payload = _resolve(
            engine, plan.initial_quality_review, maximum_bytes=MAX_JSON_BYTES
        )
        initial_review = _typed(
            initial_review_payload,
            contract="science-visual-subject-benchmark-review",
            model=LocalImageScienceVisualSubjectBenchmarkReview,
        )
        initial_result = _typed(
            _resolve(engine, initial_review.benchmark_result, maximum_bytes=MAX_JSON_BYTES),
            contract="science-visual-subject-benchmark-result",
            model=LocalImageScienceVisualSubjectBenchmarkResult,
        )
        validate_science_visual_subject_benchmark_review(
            inventory,
            initial_plan,
            initial_result,
            initial_review,
        )
        validate_science_visual_subject_multiseed_plan(
            inventory,
            initial_plan,
            initial_review,
            plan,
        )
        adapter_manifest_payload = _resolve(
            engine, plan.adapter_manifest, maximum_bytes=MAX_JSON_BYTES
        )
        adapter = _typed(
            adapter_manifest_payload,
            contract="science-campaign-lora-micro-adapter-manifest-v2",
            model=LocalImageScienceCampaignLoraMicroAdapterManifestV2,
        )
        if adapter.base_model != plan.base_model:
            raise ScienceSubjectMultiseedStageError("SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID")
        declared = {value.relative_path: value for value in adapter.files}
        adapter_payloads: dict[str, bytes] = {}
        for member_path, schema_ref, media_type in (
            (
                "adapter_config.json",
                "eom://schemas/image-provider/local-image-lora-adapter-config/1.0",
                "application/json",
            ),
            (
                "adapter_model.safetensors",
                "eom://schemas/image-provider/local-image-lora-adapter-weights/1.0",
                "application/octet-stream",
            ),
        ):
            adapter_name = cast(
                Literal["adapter_config.json", "adapter_model.safetensors"], member_path
            )
            entry = declared.get(adapter_name)
            if entry is None:
                raise ScienceSubjectMultiseedStageError("SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID")
            pointer = _pointer(
                artifact_id=plan.adapter_manifest.artifact_id,
                artifact_revision_id=plan.adapter_manifest.artifact_revision_id,
                member_path=member_path,
                schema_ref=schema_ref,
                media_type=media_type,
                sha256=entry.sha256,
            )
            payload = _resolve(engine, pointer, maximum_bytes=MAX_ADAPTER_BYTES)
            if len(payload) != entry.size_bytes:
                raise ScienceSubjectMultiseedStageError("SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID")
            adapter_payloads[member_path] = payload
        command = _command(plan_pointer=plan_pointer, plan=plan, source_commit=args.source_commit)
        summary = {
            "case_count": len(plan.cases),
            "command_sha256": command.command_sha256,
            "run_id": command.run_id,
            "subject_count": len({value.subject_id for value in plan.cases}),
        }
        if args.preflight_only:
            print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        trainer = pwd.getpwnam(TRAINER_USER)
        trainer_gid = grp.getgrnam(TRAINER_USER).gr_gid
        temporary = Path(
            tempfile.mkdtemp(prefix=".science-subject-multiseed.", dir=WORKSPACE_PARENT)
        )
        os.chmod(temporary, 0o700)
        inputs = temporary / "inputs"
        inputs.mkdir(mode=0o550)
        os.chown(inputs, 0, trainer_gid)
        adapter_root = inputs / "adapter"
        adapter_root.mkdir(mode=0o550)
        os.chown(adapter_root, 0, trainer_gid)
        for path, payload in (
            (inputs / "subject-multiseed-plan.json", plan_payload),
            (inputs / "science-visual-subject-inventory.json", inventory_payload),
            (inputs / "science-visual-subject-benchmark-plan.json", initial_plan_payload),
            (inputs / "science-visual-subject-benchmark-review.json", initial_review_payload),
            (adapter_root / "adapter-manifest.json", adapter_manifest_payload),
        ):
            _stage_file(path, payload, trainer_gid=trainer_gid)
        for adapter_file_name, payload in sorted(adapter_payloads.items()):
            _stage_file(adapter_root / adapter_file_name, payload, trainer_gid=trainer_gid)
        _stage_file(
            temporary / "command.json",
            content_json_bytes(command.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        os.chown(temporary, trainer.pw_uid, trainer_gid)
        workspace = WORKSPACE_PARENT / command.run_id
        if workspace.exists() or workspace.is_symlink():
            raise ScienceSubjectMultiseedStageError("SCIENCE_SUBJECT_MULTISEED_WORKSPACE_EXISTS")
        os.rename(temporary, workspace)
        temporary = None
        descriptor = os.open(WORKSPACE_PARENT, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        engine.dispose()
        if temporary is not None:
            shutil.rmtree(temporary)
    print(
        json.dumps(
            {
                **summary,
                "status": "STAGED",
                "systemd_unit": f"eom-image-science-subject-multiseed@{command.run_id}.service",
                "workspace": str(workspace),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
