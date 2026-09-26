#!/usr/bin/env python3
"""Stage one exact science base-versus-adapter evaluation."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import shutil
import tempfile
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceLoraMicroEvaluationCase,
    LocalImageScienceLoraMicroEvaluationCommand,
    LocalImageScienceLoraMicroProbeCommand,
    LocalImageScienceLoraMicroProbePlan,
    LocalImageScienceLoraMicroProbeWorkerResult,
    LocalImageScienceVisualCropSet,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_science_micro_evaluation_command,
    validate_science_micro_probe_plan_sources,
    validate_science_micro_probe_worker_result,
)
from eom_orchestrator.database import build_engine
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    WORKSPACE_PARENT,
    _load_artifact_member,
    _parse_json,
    _require_release,
    _safe_read,
    _write_exclusive,
)

TRAINER_USER = "eom-image"
MAX_ADAPTER_BYTES = 1024 * 1024 * 1024
NEGATIVE_PROMPT = (
    "people, portrait, photorealistic scene, decorative text, watermark, color, "
    "answer markings, cropped subject, clutter"
)


class ScienceMicroEvaluationStageError(RuntimeError):
    """Stable operator-facing science evaluation staging failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-run-id", required=True)
    parser.add_argument("--training-result-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _training_workspace(training_run_id: str) -> Path:
    if not training_run_id.startswith("imgscimicrotrainrun_") or len(training_run_id) != 52:
        raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RUN_INVALID")
    workspace = Path(WORKSPACE_PARENT) / training_run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RUN_INVALID")
    return workspace


def _file_digest(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _load_training(
    workspace: Path,
    expected_result_sha256: str,
) -> tuple[
    LocalImageScienceLoraMicroProbeCommand,
    LocalImageScienceLoraMicroProbeWorkerResult,
]:
    command_payload = _safe_read(
        workspace / "command.json",
        expected_sha256="sha256:" + _file_digest(workspace / "command.json"),
        maximum_bytes=MAX_JSON_BYTES,
    )
    result_payload = _safe_read(
        workspace / "result.json",
        expected_sha256="sha256:" + _file_digest(workspace / "result.json"),
        maximum_bytes=MAX_JSON_BYTES,
    )
    try:
        command_value = _parse_json(command_payload)
        result_value = _parse_json(result_payload)
        validate_contract("science-lora-micro-probe-command", command_value)
        validate_contract("science-lora-micro-probe-worker-result", result_value)
        command = LocalImageScienceLoraMicroProbeCommand.model_validate(command_value)
        result = LocalImageScienceLoraMicroProbeWorkerResult.model_validate(result_value)
        validate_science_micro_probe_worker_result(command, result)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RESULT_INVALID") from exc
    if (
        result.status != "SUCCEEDED"
        or result.adapter_manifest is None
        or result.result_sha256 != expected_result_sha256
    ):
        raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RESULT_INVALID")
    return command, result


def _load_sources(
    engine: Engine,
    training: LocalImageScienceLoraMicroProbeCommand,
) -> tuple[LocalImageScienceLoraMicroProbePlan, LocalImageScienceVisualCropSet]:
    plan_payload = _load_artifact_member(
        engine,
        training.probe_plan_pointer,
        maximum_bytes=MAX_JSON_BYTES,
    )
    crop_payload = _load_artifact_member(
        engine,
        training.probe_plan.crop_set,
        maximum_bytes=MAX_JSON_BYTES,
    )
    try:
        plan_value = _parse_json(plan_payload)
        crop_value = _parse_json(crop_payload)
        validate_contract("science-lora-micro-probe-plan", plan_value)
        validate_contract("science-visual-crop-set", crop_value)
        plan = LocalImageScienceLoraMicroProbePlan.model_validate(plan_value)
        crop_set = LocalImageScienceVisualCropSet.model_validate(crop_value)
        validate_science_micro_probe_plan_sources(plan, crop_set)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID") from exc
    if plan != training.probe_plan:
        raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID")
    return plan, crop_set


def _cases(
    plan: LocalImageScienceLoraMicroProbePlan,
    crop_set: LocalImageScienceVisualCropSet,
) -> tuple[LocalImageScienceLoraMicroEvaluationCase, ...]:
    members = {value.candidate_id: value for value in crop_set.members}
    values = []
    for index, candidate_id in enumerate(plan.holdout_member_ids):
        member = members.get(candidate_id)
        if member is None or member.partition != "HOLDOUT":
            raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID")
        values.append(
            LocalImageScienceLoraMicroEvaluationCase(
                candidate_id=member.candidate_id,
                document_id=member.document_id,
                exam_group_sha256=member.exam_group_sha256,
                positive_prompt=member.caption_en,
                positive_prompt_sha256=member.caption_sha256,
                negative_prompt=NEGATIVE_PROMPT,
                negative_prompt_sha256=text_sha256(NEGATIVE_PROMPT),
                seed=plan.seed + 1000 + index,
            )
        )
    return tuple(sorted(values, key=lambda value: value.candidate_id))


def _build_command(
    *,
    training: LocalImageScienceLoraMicroProbeCommand,
    result: LocalImageScienceLoraMicroProbeWorkerResult,
    plan: LocalImageScienceLoraMicroProbePlan,
    crop_set: LocalImageScienceVisualCropSet,
    cases: tuple[LocalImageScienceLoraMicroEvaluationCase, ...],
    source_commit: str,
) -> LocalImageScienceLoraMicroEvaluationCommand:
    assert result.adapter_manifest is not None
    body = {
        "schema_version": "local-image-science-lora-micro-evaluation-command/1.0",
        "training_run_id": training.training_run_id,
        "probe_plan_pointer": training.probe_plan_pointer.model_dump(mode="json"),
        "probe_plan_sha256": training.probe_plan_sha256,
        "crop_set": plan.crop_set.model_dump(mode="json"),
        "crop_set_sha256": crop_set.crop_set_sha256,
        "training_result_sha256": result.result_sha256,
        "adapter_manifest": result.adapter_manifest.model_dump(mode="json"),
        "cases": [value.model_dump(mode="json") for value in cases],
        "inference_steps": 20,
        "guidance_scale": 7.5,
        "generation_width": 800,
        "generation_height": 504,
        "delivery_width": 800,
        "delivery_height": 500,
        "staged_adapter_root": "inputs/adapter",
        "output_root_member": "outputs",
        "source_commit": source_commit,
        "timeout_seconds": 3600,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "evaluation_run_id": "imgscimicroevalrun_" + identity[:32]}
    value = {**with_id, "command_sha256": content_sha256(with_id)}
    try:
        validate_contract("science-lora-micro-evaluation-command", value)
        command = LocalImageScienceLoraMicroEvaluationCommand.model_validate(value)
        validate_science_micro_evaluation_command(plan, crop_set, result, command)
        return command
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_COMMAND_INVALID") from exc


def _stage_file(path: Path, payload: bytes, *, trainer_gid: int) -> None:
    _write_exclusive(path, payload, mode=0o440)
    os.chown(path, 0, trainer_gid)


def main() -> None:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    training_workspace = _training_workspace(args.training_run_id)
    training, result = _load_training(training_workspace, args.training_result_sha256)
    engine = build_engine()
    temporary: Path | None = None
    try:
        plan, crop_set = _load_sources(engine, training)
        cases = _cases(plan, crop_set)
        command = _build_command(
            training=training,
            result=result,
            plan=plan,
            crop_set=crop_set,
            cases=cases,
            source_commit=args.source_commit,
        )
        assert result.adapter_manifest is not None
        adapter_payloads = {
            value.relative_path: _safe_read(
                training_workspace / "outputs" / value.relative_path,
                expected_sha256=value.sha256,
                maximum_bytes=MAX_ADAPTER_BYTES,
            )
            for value in result.adapter_manifest.files
        }
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "status": "PREFLIGHT_PASS",
                        "evaluation_run_id": command.evaluation_run_id,
                        "command_sha256": command.command_sha256,
                        "case_count": len(command.cases),
                        "training_result_sha256": command.training_result_sha256,
                        "activation_policy": command.adapter_manifest.activation_policy,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return
        trainer = pwd.getpwnam(TRAINER_USER)
        trainer_gid = grp.getgrnam(TRAINER_USER).gr_gid
        temporary = Path(
            tempfile.mkdtemp(prefix=".science-micro-evaluation.", dir=WORKSPACE_PARENT)
        )
        os.chmod(temporary, 0o700)
        inputs = temporary / "inputs"
        inputs.mkdir(mode=0o550)
        os.chown(inputs, 0, trainer_gid)
        adapter = inputs / "adapter"
        adapter.mkdir(mode=0o550)
        os.chown(adapter, 0, trainer_gid)
        for name, payload in sorted(adapter_payloads.items()):
            _stage_file(adapter / name, payload, trainer_gid=trainer_gid)
        _stage_file(
            temporary / "command.json",
            content_json_bytes(command.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        os.chown(temporary, trainer.pw_uid, trainer_gid)
        workspace = WORKSPACE_PARENT / command.evaluation_run_id
        if workspace.exists() or workspace.is_symlink():
            raise ScienceMicroEvaluationStageError("IMAGE_EVALUATION_WORKSPACE_EXISTS")
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
                "status": "STAGED",
                "evaluation_run_id": command.evaluation_run_id,
                "command_sha256": command.command_sha256,
                "workspace": str(workspace),
                "systemd_unit": (
                    f"eom-image-science-lora-micro-evaluation@{command.evaluation_run_id}.service"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
