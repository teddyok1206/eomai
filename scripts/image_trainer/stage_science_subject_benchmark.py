#!/usr/bin/env python3
"""Stage one pinned science-subject benchmark through Orchestrator-owned inputs."""

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
    LocalImageScienceVisualSubjectBenchmarkCommand,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectInventory,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_science_visual_subject_benchmark_plan,
)
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_member,
)
from eom_orchestrator.database import build_engine
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    WORKSPACE_PARENT,
    _make_trainer_readonly_directory,
    _parse_json,
    _require_release,
    _write_exclusive,
)

TRAINER_USER = "eom-image"
MAX_ADAPTER_BYTES = 1024 * 1024 * 1024


class ScienceSubjectBenchmarkStageError(RuntimeError):
    """Stable operator error for subject-benchmark staging."""


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
    except PydanticValidationError as exc:
        raise ScienceSubjectBenchmarkStageError(
            "SCIENCE_SUBJECT_BENCHMARK_POINTER_INVALID"
        ) from exc


def _resolve(
    engine: Engine, pointer: ImageEvaluationArtifactMember, *, maximum_bytes: int
) -> bytes:
    try:
        return resolve_control_artifact_member(engine, pointer, maximum_bytes=maximum_bytes)
    except ControlArtifactResolutionError as exc:
        raise ScienceSubjectBenchmarkStageError(
            "SCIENCE_SUBJECT_BENCHMARK_POINTER_RESOLUTION_FAILED"
        ) from exc


def _load_typed(payload: bytes, *, contract: str, model: type[BaseModel]) -> BaseModel:
    try:
        value = _parse_json(payload)
        validate_contract(contract, value)
        parsed = model.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceSubjectBenchmarkStageError("SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID") from exc
    canonical = content_json_bytes(parsed.model_dump(mode="json"))
    if payload not in {canonical, canonical + b"\n"}:
        raise ScienceSubjectBenchmarkStageError("SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID")
    return parsed


def _command(
    *,
    plan_pointer: ImageEvaluationArtifactMember,
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    source_commit: str,
) -> LocalImageScienceVisualSubjectBenchmarkCommand:
    body = {
        "schema_version": "local-image-science-visual-subject-benchmark-command/1.0",
        "plan": plan_pointer.model_dump(mode="json"),
        "plan_sha256": plan.plan_sha256,
        "staged_plan_path": "inputs/subject-benchmark-plan.json",
        "staged_subject_inventory_path": "inputs/science-visual-subject-inventory.json",
        "staged_adapter_manifest_path": "inputs/adapter/adapter-manifest.json",
        "staged_adapter_model_path": "inputs/adapter/adapter_model.safetensors",
        "staged_adapter_config_path": "inputs/adapter/adapter_config.json",
        "output_directory": "outputs",
        "source_commit": source_commit,
    }
    identity = content_sha256(body).removeprefix("sha256:")[:32]
    with_id = {**body, "run_id": f"imgscisubjectbenchmarkrun_{identity}"}
    value = {**with_id, "command_sha256": content_sha256(with_id)}
    try:
        validate_contract("science-visual-subject-benchmark-command", value)
        return LocalImageScienceVisualSubjectBenchmarkCommand.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceSubjectBenchmarkStageError(
            "SCIENCE_SUBJECT_BENCHMARK_COMMAND_INVALID"
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
        member_path="manifests/science-visual-subject-benchmark-plan.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-plan/1.0"
        ),
        media_type="application/json",
        sha256=args.plan_artifact_sha256,
    )
    engine = build_engine()
    temporary: Path | None = None
    try:
        plan_payload = _resolve(engine, plan_pointer, maximum_bytes=MAX_JSON_BYTES)
        plan = cast(
            LocalImageScienceVisualSubjectBenchmarkPlan,
            _load_typed(
                plan_payload,
                contract="science-visual-subject-benchmark-plan",
                model=LocalImageScienceVisualSubjectBenchmarkPlan,
            ),
        )
        inventory_payload = _resolve(engine, plan.subject_inventory, maximum_bytes=MAX_JSON_BYTES)
        inventory = cast(
            LocalImageScienceVisualSubjectInventory,
            _load_typed(
                inventory_payload,
                contract="science-visual-subject-inventory",
                model=LocalImageScienceVisualSubjectInventory,
            ),
        )
        adapter_manifest_payload = _resolve(
            engine, plan.adapter_manifest, maximum_bytes=MAX_JSON_BYTES
        )
        adapter = cast(
            LocalImageScienceCampaignLoraMicroAdapterManifestV2,
            _load_typed(
                adapter_manifest_payload,
                contract="science-campaign-lora-micro-adapter-manifest-v2",
                model=LocalImageScienceCampaignLoraMicroAdapterManifestV2,
            ),
        )
        validate_science_visual_subject_benchmark_plan(inventory, plan)
        if adapter.base_model != plan.base_model:
            raise ScienceSubjectBenchmarkStageError("SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID")
        declared = {value.relative_path: value for value in adapter.files}
        adapter_payloads = {}
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
            declared_name = cast(
                Literal["adapter_config.json", "adapter_model.safetensors"], member_path
            )
            entry = declared.get(declared_name)
            if entry is None:
                raise ScienceSubjectBenchmarkStageError("SCIENCE_SUBJECT_BENCHMARK_ADAPTER_INVALID")
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
                raise ScienceSubjectBenchmarkStageError("SCIENCE_SUBJECT_BENCHMARK_ADAPTER_INVALID")
            adapter_payloads[member_path] = payload
        command = _command(
            plan_pointer=plan_pointer,
            plan=plan,
            source_commit=args.source_commit,
        )
        summary = {
            "case_count": len(plan.cases),
            "command_sha256": command.command_sha256,
            "quality_case_count": sum(case.case_kind == "QUALITY" for case in plan.cases),
            "route_case_count": sum(case.case_kind == "ROUTE" for case in plan.cases),
            "run_id": command.run_id,
        }
        if args.preflight_only:
            print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        trainer = pwd.getpwnam(TRAINER_USER)
        trainer_gid = grp.getgrnam(TRAINER_USER).gr_gid
        temporary = Path(
            tempfile.mkdtemp(prefix=".science-subject-benchmark.", dir=WORKSPACE_PARENT)
        )
        os.chmod(temporary, 0o700)
        inputs = temporary / "inputs"
        _make_trainer_readonly_directory(inputs, trainer_gid=trainer_gid)
        adapter_root = inputs / "adapter"
        _make_trainer_readonly_directory(adapter_root, trainer_gid=trainer_gid)
        _stage_file(inputs / "subject-benchmark-plan.json", plan_payload, trainer_gid=trainer_gid)
        _stage_file(
            inputs / "science-visual-subject-inventory.json",
            inventory_payload,
            trainer_gid=trainer_gid,
        )
        _stage_file(
            adapter_root / "adapter-manifest.json",
            adapter_manifest_payload,
            trainer_gid=trainer_gid,
        )
        for name, payload in sorted(adapter_payloads.items()):
            _stage_file(adapter_root / name, payload, trainer_gid=trainer_gid)
        _stage_file(
            temporary / "command.json",
            content_json_bytes(command.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        os.chown(temporary, trainer.pw_uid, trainer_gid)
        workspace = WORKSPACE_PARENT / command.run_id
        if workspace.exists() or workspace.is_symlink():
            raise ScienceSubjectBenchmarkStageError("SCIENCE_SUBJECT_BENCHMARK_WORKSPACE_EXISTS")
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
                "systemd_unit": f"eom-image-science-subject-benchmark@{command.run_id}.service",
                "workspace": str(workspace),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
