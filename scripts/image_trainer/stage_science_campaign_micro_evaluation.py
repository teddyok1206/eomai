#!/usr/bin/env python3
"""Stage one exact campaign BASE-versus-ADAPTER holdout evaluation."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import re
import shutil
import tempfile
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceCampaignLoraMicroEvaluationCase,
    LocalImageScienceCampaignLoraMicroEvaluationCommand,
    LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    LocalImageScienceCampaignLoraMicroProbeCommand,
    LocalImageScienceCampaignLoraMicroProbeCommandV2,
    LocalImageScienceCampaignLoraMicroProbePlan,
    LocalImageScienceCampaignLoraMicroProbePlanV2,
    LocalImageScienceCampaignLoraMicroProbeWorkerResult,
    LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
    LocalImageScienceVisualCampaignCropSet,
    LocalImageScienceVisualCampaignCropSetV2,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_science_campaign_micro_evaluation_command,
    validate_science_campaign_micro_evaluation_command_v2,
    validate_science_campaign_micro_probe_plan_sources,
    validate_science_campaign_micro_probe_plan_sources_v2,
    validate_science_campaign_micro_probe_worker_result,
    validate_science_campaign_micro_probe_worker_result_v2,
)
from eom_orchestrator.database import build_engine
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    WORKSPACE_PARENT,
    _load_artifact_member,
    _make_trainer_readonly_directory,
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


class ScienceCampaignMicroEvaluationStageError(RuntimeError):
    """Stable operator-facing campaign evaluation staging failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-run-id", required=True)
    parser.add_argument("--training-result-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _training_workspace(training_run_id: str) -> Path:
    if re.fullmatch(r"imgscicampaignmicrotrainrun_[0-9a-f]{32}", training_run_id) is None:
        raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RUN_INVALID")
    workspace = Path(WORKSPACE_PARENT) / training_run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RUN_INVALID")
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
    LocalImageScienceCampaignLoraMicroProbeCommand
    | LocalImageScienceCampaignLoraMicroProbeCommandV2,
    LocalImageScienceCampaignLoraMicroProbeWorkerResult
    | LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
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
        expanded = command_value.get("schema_version") == (
            "local-image-science-campaign-lora-micro-probe-command/1.1"
        )
        if expanded:
            validate_contract("science-campaign-lora-micro-probe-command-v2", command_value)
            validate_contract("science-campaign-lora-micro-probe-worker-result-v2", result_value)
            command: (
                LocalImageScienceCampaignLoraMicroProbeCommand
                | LocalImageScienceCampaignLoraMicroProbeCommandV2
            ) = LocalImageScienceCampaignLoraMicroProbeCommandV2.model_validate(command_value)
            result: (
                LocalImageScienceCampaignLoraMicroProbeWorkerResult
                | LocalImageScienceCampaignLoraMicroProbeWorkerResultV2
            ) = LocalImageScienceCampaignLoraMicroProbeWorkerResultV2.model_validate(result_value)
            assert isinstance(command, LocalImageScienceCampaignLoraMicroProbeCommandV2)
            assert isinstance(result, LocalImageScienceCampaignLoraMicroProbeWorkerResultV2)
            validate_science_campaign_micro_probe_worker_result_v2(command, result)
        else:
            validate_contract("science-campaign-lora-micro-probe-command", command_value)
            validate_contract("science-campaign-lora-micro-probe-worker-result", result_value)
            command = LocalImageScienceCampaignLoraMicroProbeCommand.model_validate(command_value)
            result = LocalImageScienceCampaignLoraMicroProbeWorkerResult.model_validate(
                result_value
            )
            validate_science_campaign_micro_probe_worker_result(command, result)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceCampaignMicroEvaluationStageError(
            "IMAGE_EVALUATION_TRAINING_RESULT_INVALID"
        ) from exc
    if (
        result.status != "SUCCEEDED"
        or result.adapter_manifest is None
        or result.result_sha256 != expected_result_sha256
    ):
        raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RESULT_INVALID")
    return command, result


def _load_sources(
    engine: Engine,
    training: LocalImageScienceCampaignLoraMicroProbeCommand
    | LocalImageScienceCampaignLoraMicroProbeCommandV2,
) -> tuple[
    LocalImageScienceCampaignLoraMicroProbePlan | LocalImageScienceCampaignLoraMicroProbePlanV2,
    LocalImageScienceVisualCampaignCropSet | LocalImageScienceVisualCampaignCropSetV2,
]:
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
        if isinstance(training, LocalImageScienceCampaignLoraMicroProbeCommandV2):
            validate_contract("science-campaign-lora-micro-probe-plan-v2", plan_value)
            validate_contract("science-visual-campaign-crop-set-v2", crop_value)
            plan: (
                LocalImageScienceCampaignLoraMicroProbePlan
                | LocalImageScienceCampaignLoraMicroProbePlanV2
            ) = LocalImageScienceCampaignLoraMicroProbePlanV2.model_validate(plan_value)
            crop_set: (
                LocalImageScienceVisualCampaignCropSet | LocalImageScienceVisualCampaignCropSetV2
            ) = LocalImageScienceVisualCampaignCropSetV2.model_validate(crop_value)
            assert isinstance(plan, LocalImageScienceCampaignLoraMicroProbePlanV2)
            assert isinstance(crop_set, LocalImageScienceVisualCampaignCropSetV2)
            validate_science_campaign_micro_probe_plan_sources_v2(plan, crop_set)
        else:
            validate_contract("science-campaign-lora-micro-probe-plan", plan_value)
            validate_contract("science-visual-campaign-crop-set", crop_value)
            plan = LocalImageScienceCampaignLoraMicroProbePlan.model_validate(plan_value)
            crop_set = LocalImageScienceVisualCampaignCropSet.model_validate(crop_value)
            validate_science_campaign_micro_probe_plan_sources(plan, crop_set)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID") from exc
    if plan != training.probe_plan:
        raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID")
    return plan, crop_set


def _cases(
    plan: LocalImageScienceCampaignLoraMicroProbePlan
    | LocalImageScienceCampaignLoraMicroProbePlanV2,
    crop_set: LocalImageScienceVisualCampaignCropSet | LocalImageScienceVisualCampaignCropSetV2,
) -> tuple[LocalImageScienceCampaignLoraMicroEvaluationCase, ...]:
    members = {value.sample_id: value for value in crop_set.members}
    values = []
    for index, sample_id in enumerate(plan.holdout_member_ids):
        member = members.get(sample_id)
        if member is None or member.partition != "HOLDOUT":
            raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID")
        values.append(
            LocalImageScienceCampaignLoraMicroEvaluationCase(
                sample_id=member.sample_id,
                parent_candidate_id=member.parent_candidate_id,
                document_id=member.document_id,
                exam_group_sha256=member.exam_group_sha256,
                positive_prompt=member.caption_en,
                positive_prompt_sha256=member.caption_sha256,
                negative_prompt=NEGATIVE_PROMPT,
                negative_prompt_sha256=text_sha256(NEGATIVE_PROMPT),
                seed=plan.seed + 1000 + index,
            )
        )
    return tuple(sorted(values, key=lambda value: value.sample_id))


def _build_command(
    *,
    training: LocalImageScienceCampaignLoraMicroProbeCommand
    | LocalImageScienceCampaignLoraMicroProbeCommandV2,
    result: LocalImageScienceCampaignLoraMicroProbeWorkerResult
    | LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
    plan: LocalImageScienceCampaignLoraMicroProbePlan
    | LocalImageScienceCampaignLoraMicroProbePlanV2,
    crop_set: LocalImageScienceVisualCampaignCropSet | LocalImageScienceVisualCampaignCropSetV2,
    cases: tuple[LocalImageScienceCampaignLoraMicroEvaluationCase, ...],
    source_commit: str,
) -> (
    LocalImageScienceCampaignLoraMicroEvaluationCommand
    | LocalImageScienceCampaignLoraMicroEvaluationCommandV2
):
    assert result.adapter_manifest is not None
    expanded = isinstance(training, LocalImageScienceCampaignLoraMicroProbeCommandV2)
    version = "1.1" if expanded else "1.0"
    body = {
        "schema_version": (f"local-image-science-campaign-lora-micro-evaluation-command/{version}"),
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
    with_id = {**body, "evaluation_run_id": "imgscicampaignmicroevalrun_" + identity[:32]}
    value = {**with_id, "command_sha256": content_sha256(with_id)}
    try:
        if expanded:
            validate_contract("science-campaign-lora-micro-evaluation-command-v2", value)
            command_v2 = LocalImageScienceCampaignLoraMicroEvaluationCommandV2.model_validate(value)
            assert isinstance(plan, LocalImageScienceCampaignLoraMicroProbePlanV2)
            assert isinstance(crop_set, LocalImageScienceVisualCampaignCropSetV2)
            assert isinstance(result, LocalImageScienceCampaignLoraMicroProbeWorkerResultV2)
            validate_science_campaign_micro_evaluation_command_v2(
                plan, crop_set, result, command_v2
            )
            return command_v2
        validate_contract("science-campaign-lora-micro-evaluation-command", value)
        command_v1 = LocalImageScienceCampaignLoraMicroEvaluationCommand.model_validate(value)
        assert isinstance(plan, LocalImageScienceCampaignLoraMicroProbePlan)
        assert isinstance(crop_set, LocalImageScienceVisualCampaignCropSet)
        assert isinstance(result, LocalImageScienceCampaignLoraMicroProbeWorkerResult)
        validate_science_campaign_micro_evaluation_command(plan, crop_set, result, command_v1)
        return command_v1
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_COMMAND_INVALID") from exc


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
            tempfile.mkdtemp(prefix=".science-campaign-micro-evaluation.", dir=WORKSPACE_PARENT)
        )
        os.chmod(temporary, 0o700)
        inputs = temporary / "inputs"
        _make_trainer_readonly_directory(inputs, trainer_gid=trainer_gid)
        adapter = inputs / "adapter"
        _make_trainer_readonly_directory(adapter, trainer_gid=trainer_gid)
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
            raise ScienceCampaignMicroEvaluationStageError("IMAGE_EVALUATION_WORKSPACE_EXISTS")
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
                    "eom-image-science-campaign-lora-micro-evaluation@"
                    f"{command.evaluation_run_id}.service"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
