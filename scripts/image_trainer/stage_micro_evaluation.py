#!/usr/bin/env python3
"""Stage one exact base-versus-adapter evaluation through Orchestrator-owned inputs."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import tempfile
from pathlib import Path

from eom_image_contracts import (
    LocalImageLoraMicroEvaluationCase,
    LocalImageLoraMicroEvaluationCommand,
    LocalImageLoraMicroProbeCommand,
    LocalImageLoraMicroProbeWorkerResult,
    LocalImageQualityEvaluationPlan,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_micro_probe_worker_result,
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


class MicroEvaluationStageError(RuntimeError):
    """Stable operator-facing error for evaluation staging."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-run-id", required=True)
    parser.add_argument("--training-result-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _training_workspace(training_run_id: str) -> Path:
    if not training_run_id.startswith("imgmicrotrainrun_") or len(training_run_id) != 49:
        raise MicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RUN_INVALID")
    workspace = Path(WORKSPACE_PARENT) / training_run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise MicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RUN_INVALID")
    return workspace


def _load_training(
    workspace: Path,
    expected_result_sha256: str,
) -> tuple[LocalImageLoraMicroProbeCommand, LocalImageLoraMicroProbeWorkerResult]:
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
        validate_contract("lora-micro-probe-command", command_value)
        validate_contract("lora-micro-probe-worker-result", result_value)
        command = LocalImageLoraMicroProbeCommand.model_validate(command_value)
        result = LocalImageLoraMicroProbeWorkerResult.model_validate(result_value)
        validate_micro_probe_worker_result(command, result)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RESULT_INVALID") from exc
    if (
        result.status != "SUCCEEDED"
        or result.adapter_manifest is None
        or result.result_sha256 != expected_result_sha256
    ):
        raise MicroEvaluationStageError("IMAGE_EVALUATION_TRAINING_RESULT_INVALID")
    return command, result


def _file_digest(path: Path) -> str:
    import hashlib

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _load_holdout(
    engine: Engine,
    command: LocalImageLoraMicroProbeCommand,
) -> LocalImageQualityEvaluationPlan:
    pointer = command.probe_plan.holdout_evaluation_plan
    payload = _load_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = _parse_json(payload)
        validate_contract("quality-evaluation-plan", value)
        plan = LocalImageQualityEvaluationPlan.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID") from exc
    if content_sha256(plan.model_dump(mode="json")) != pointer.sha256:
        raise MicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID")
    return plan


def _cases(
    holdout: LocalImageQualityEvaluationPlan,
    training: LocalImageLoraMicroProbeCommand,
) -> tuple[LocalImageLoraMicroEvaluationCase, ...]:
    allowed_ids = set(training.probe_plan.holdout_sample_ids)
    allowed_anchors = set(training.probe_plan.holdout_source_anchor_ids)
    selected = tuple(
        sample
        for sample in holdout.samples
        if sample.sample_id in allowed_ids and sample.source_anchor_id in allowed_anchors
    )[:3]
    if len(selected) != 3:
        raise MicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID")
    values = []
    for sample in selected:
        prompts = {prompt.variant_id: prompt for prompt in sample.prompts}
        prompt = prompts.get("ASSESSMENT_STYLE_EN")
        if prompt is None:
            raise MicroEvaluationStageError("IMAGE_EVALUATION_HOLDOUT_INVALID")
        values.append(
            LocalImageLoraMicroEvaluationCase(
                sample_id=sample.sample_id,
                source_anchor_id=sample.source_anchor_id,
                positive_prompt=prompt.positive_prompt,
                positive_prompt_sha256=prompt.positive_prompt_sha256,
                negative_prompt=prompt.negative_prompt,
                negative_prompt_sha256=prompt.negative_prompt_sha256,
                seed=sample.seed,
            )
        )
    return tuple(sorted(values, key=lambda value: value.sample_id))


def _build_command(
    *,
    training: LocalImageLoraMicroProbeCommand,
    result: LocalImageLoraMicroProbeWorkerResult,
    cases: tuple[LocalImageLoraMicroEvaluationCase, ...],
    source_commit: str,
) -> LocalImageLoraMicroEvaluationCommand:
    assert result.adapter_manifest is not None
    body = {
        "schema_version": "local-image-lora-micro-evaluation-command/1.0",
        "training_run_id": training.training_run_id,
        "probe_plan_pointer": training.probe_plan_pointer.model_dump(mode="json"),
        "probe_plan_sha256": training.probe_plan_sha256,
        "training_result_sha256": result.result_sha256,
        "adapter_manifest": result.adapter_manifest.model_dump(mode="json"),
        "holdout_evaluation_plan": (
            training.probe_plan.holdout_evaluation_plan.model_dump(mode="json")
        ),
        "holdout_plan_sha256": training.probe_plan.holdout_evaluation_plan.sha256,
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
    with_id = {**body, "evaluation_run_id": "imgmicroevalrun_" + identity[:32]}
    value = {**with_id, "command_sha256": content_sha256(with_id)}
    try:
        validate_contract("lora-micro-evaluation-command", value)
        return LocalImageLoraMicroEvaluationCommand.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroEvaluationStageError("IMAGE_EVALUATION_COMMAND_INVALID") from exc


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
        holdout = _load_holdout(engine, training)
        cases = _cases(holdout, training)
        command = _build_command(
            training=training,
            result=result,
            cases=cases,
            source_commit=args.source_commit,
        )
        adapter_payloads = {}
        assert result.adapter_manifest is not None
        for value in result.adapter_manifest.files:
            source = training_workspace / "outputs" / value.relative_path
            adapter_payloads[value.relative_path] = _safe_read(
                source,
                expected_sha256=value.sha256,
                maximum_bytes=MAX_ADAPTER_BYTES,
            )
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
            tempfile.mkdtemp(prefix=".micro-evaluation-staging.", dir=WORKSPACE_PARENT)
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
        command_path = temporary / "command.json"
        _stage_file(
            command_path,
            content_json_bytes(command.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        os.chown(temporary, trainer.pw_uid, trainer_gid)
        workspace = WORKSPACE_PARENT / command.evaluation_run_id
        if workspace.exists() or workspace.is_symlink():
            raise MicroEvaluationStageError("IMAGE_EVALUATION_WORKSPACE_EXISTS")
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
                    f"eom-image-lora-micro-evaluation@{command.evaluation_run_id}.service"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
