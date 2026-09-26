#!/usr/bin/env python3
"""Stage one user-authorized, evaluation-only science LoRA micro probe."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_service.local_image_adapter import load_local_image_provider_binding
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceLoraMicroProbeCommand,
    LocalImageScienceLoraMicroProbePlan,
    LocalImageScienceVisualCropSet,
    content_sha256,
    validate_contract,
    validate_science_micro_probe_plan_sources,
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
    WORKSPACE_PARENT,
    _load_artifact_member,
    _parse_json,
    _require_release,
    _write_exclusive,
)

TRAINER_USER = "eom-image"
TRAINER_PYTHON = Path("/srv/eom/conda/envs/eom-image-trainer/bin/python")
MAX_CROP_BYTES = 64 * 1024 * 1024


class ScienceMicroProbeStageError(RuntimeError):
    """Stable operator-facing staging failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop-set-artifact-id", required=True)
    parser.add_argument("--crop-set-artifact-revision-id", required=True)
    parser.add_argument("--crop-set-artifact-sha256", required=True)
    parser.add_argument("--authorized-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--authorization-reference-sha256", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ScienceMicroProbeStageError("IMAGE_TRAINING_TIMESTAMP_INVALID")
    return value


def _crop_set_pointer(args: argparse.Namespace) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=args.crop_set_artifact_id,
        artifact_revision_id=args.crop_set_artifact_revision_id,
        member_path="manifests/science-visual-crop-set.json",
        schema_ref="eom://schemas/image-provider/local-image-science-visual-crop-set/1.0",
        media_type="application/json",
        sha256=args.crop_set_artifact_sha256,
    )


def _load_crop_set(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
) -> LocalImageScienceVisualCropSet:
    payload = _load_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = _parse_json(payload)
        validate_contract("science-visual-crop-set", value)
        return LocalImageScienceVisualCropSet.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceMicroProbeStageError("IMAGE_TRAINING_CROP_SET_INVALID") from exc


def _trainer_dependencies() -> dict[str, str]:
    script = """
import json, platform
from importlib import metadata
names = ('torch','diffusers','transformers','accelerate','peft','bitsandbytes')
print(json.dumps({'python_version': platform.python_version(), **{
    name + '_version': metadata.version(name) for name in names
}}, sort_keys=True, separators=(',', ':')))
"""
    try:
        completed = subprocess.run(
            [str(TRAINER_PYTHON), "-I", "-c", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        value = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ScienceMicroProbeStageError("IMAGE_TRAINING_RUNTIME_DRIFT") from exc
    expected = {
        "python_version",
        "torch_version",
        "diffusers_version",
        "transformers_version",
        "accelerate_version",
        "peft_version",
        "bitsandbytes_version",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or not all(isinstance(item, str) for item in value.values())
    ):
        raise ScienceMicroProbeStageError("IMAGE_TRAINING_RUNTIME_DRIFT")
    return value


def _build_plan(
    *,
    args: argparse.Namespace,
    crop_set_pointer: ImageEvaluationArtifactMember,
    crop_set: LocalImageScienceVisualCropSet,
) -> LocalImageScienceLoraMicroProbePlan:
    binding = load_local_image_provider_binding(
        CatalogSettings.from_environment().local_image_provider_binding
    )
    partitions = {
        partition: sorted(
            member.candidate_id for member in crop_set.members if member.partition == partition
        )
        for partition in ("TRAIN", "VALIDATION", "HOLDOUT")
    }
    body = {
        "schema_version": "local-image-science-lora-micro-probe-plan/1.0",
        "crop_set": crop_set_pointer.model_dump(mode="json"),
        "crop_set_sha256": crop_set.crop_set_sha256,
        "base_model": binding.model.model_dump(mode="json"),
        "training_member_ids": partitions["TRAIN"],
        "validation_member_ids": partitions["VALIDATION"],
        "holdout_member_ids": partitions["HOLDOUT"],
        "preprocessing_revision": "local-image-science-crop-preprocess/1.0",
        "trainer_contract": "eom-local-image-science-lora-micro-trainer/1.0",
        "dependencies": _trainer_dependencies(),
        "hyperparameters": {
            "adapter_type": "UNET_LORA",
            "rank": 8,
            "alpha": 8,
            "resolution_width": 768,
            "resolution_height": 512,
            "train_batch_size": 1,
            "gradient_accumulation_steps": 4,
            "gradient_checkpointing": True,
            "mixed_precision": "fp16",
            "optimizer": "adamw_8bit",
            "learning_rate": "1e-4",
            "max_train_steps": 200,
            "checkpointing_steps": 200,
            "random_flip": False,
            "train_text_encoders": False,
            "train_vae": False,
        },
        "seed": args.seed,
        "purpose": "EVALUATION_ONLY_SCIENCE_MICRO_PROBE",
        "activation_policy": "FORBIDDEN",
        "authorized_at": _utc(args.authorized_at).isoformat().replace("+00:00", "Z"),
        "authorized_by": args.authorized_by,
        "authorization_reference_sha256": args.authorization_reference_sha256,
        "created_at": _utc(args.created_at).isoformat().replace("+00:00", "Z"),
        "created_by": args.created_by,
        "source_commit": args.source_commit,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "probe_id": "imgscimicroprobe_" + identity[:32]}
    value = {**with_id, "plan_sha256": content_sha256(with_id)}
    try:
        validate_contract("science-lora-micro-probe-plan", value)
        plan = LocalImageScienceLoraMicroProbePlan.model_validate(value)
        validate_science_micro_probe_plan_sources(plan, crop_set)
        return plan
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceMicroProbeStageError("IMAGE_TRAINING_MICRO_PLAN_INVALID") from exc


def _build_command(
    *,
    plan: LocalImageScienceLoraMicroProbePlan,
    plan_pointer: ImageEvaluationArtifactMember,
) -> LocalImageScienceLoraMicroProbeCommand:
    identity = content_sha256(
        {
            "probe_plan_pointer": plan_pointer.model_dump(mode="json"),
            "probe_plan_sha256": plan.plan_sha256,
            "attempt": 1,
        }
    ).removeprefix("sha256:")
    body = {
        "schema_version": "local-image-science-lora-micro-probe-command/1.0",
        "training_run_id": "imgscimicrotrainrun_" + identity[:32],
        "probe_plan_pointer": plan_pointer.model_dump(mode="json"),
        "probe_plan_sha256": plan.plan_sha256,
        "probe_plan": plan.model_dump(mode="json"),
        "attempt": 1,
        "staged_plan_member": "inputs/science-micro-probe-plan.json",
        "staged_crop_set_member": "inputs/science-visual-crop-set.json",
        "staged_crops_root": "inputs/crops",
        "runtime_dataset_root": "runtime-dataset",
        "output_root_member": "outputs",
        "checkpoint_root_member": "checkpoints",
        "timeout_seconds": 7200,
    }
    value = {**body, "command_sha256": content_sha256(body)}
    try:
        validate_contract("science-lora-micro-probe-command", value)
        return LocalImageScienceLoraMicroProbeCommand.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceMicroProbeStageError("IMAGE_TRAINING_MICRO_COMMAND_INVALID") from exc


def _stage_file(path: Path, payload: bytes, *, trainer_gid: int) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ScienceMicroProbeStageError("IMAGE_TRAINING_WORKSPACE_INVALID")
    _write_exclusive(path, payload, mode=0o440)
    os.chown(path, 0, trainer_gid)


def main() -> None:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    crop_set_pointer = _crop_set_pointer(args)
    account = pwd.getpwnam(TRAINER_USER)
    trainer_gid = grp.getgrnam(TRAINER_USER).gr_gid
    engine = build_engine()
    temporary: Path | None = None
    try:
        crop_set = _load_crop_set(engine, crop_set_pointer)
        plan = _build_plan(args=args, crop_set_pointer=crop_set_pointer, crop_set=crop_set)
        crop_payloads = {
            member.candidate_id: _load_artifact_member(
                engine,
                ImageEvaluationArtifactMember(
                    artifact_id=crop_set_pointer.artifact_id,
                    artifact_revision_id=crop_set_pointer.artifact_revision_id,
                    member_path=member.member_path,
                    schema_ref=("eom://schemas/image-provider/local-image-science-visual-crop/1.0"),
                    media_type="image/png",
                    sha256=member.sha256,
                ),
                maximum_bytes=MAX_CROP_BYTES,
            )
            for member in crop_set.members
        }
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "status": "PREFLIGHT_PASS",
                        "probe_id": plan.probe_id,
                        "plan_sha256": plan.plan_sha256,
                        "training_member_count": len(plan.training_member_ids),
                        "validation_member_count": len(plan.validation_member_ids),
                        "holdout_member_count": len(plan.holdout_member_ids),
                        "activation_policy": plan.activation_policy,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return
        publisher = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        )
        plan_pointer = publisher.commit_science_micro_probe_plan(plan)
        command = _build_command(plan=plan, plan_pointer=plan_pointer)
        temporary = Path(tempfile.mkdtemp(prefix=".science-micro-probe.", dir=WORKSPACE_PARENT))
        os.chmod(temporary, 0o700)
        inputs = temporary / "inputs"
        inputs.mkdir(mode=0o550)
        os.chown(inputs, 0, trainer_gid)
        _stage_file(
            inputs / "science-micro-probe-plan.json",
            canonical_json_bytes(plan.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        _stage_file(
            inputs / "science-visual-crop-set.json",
            canonical_json_bytes(crop_set.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        crops = inputs / "crops"
        crops.mkdir(mode=0o550)
        os.chown(crops, 0, trainer_gid)
        for candidate_id, payload in sorted(crop_payloads.items()):
            _stage_file(crops / f"{candidate_id}.png", payload, trainer_gid=trainer_gid)
        command_path = temporary / "command.json"
        _write_exclusive(
            command_path,
            canonical_json_bytes(command.model_dump(mode="json")),
            mode=0o440,
        )
        os.chown(command_path, 0, trainer_gid)
        os.chown(temporary, account.pw_uid, trainer_gid)
        workspace = WORKSPACE_PARENT / command.training_run_id
        if workspace.exists() or workspace.is_symlink():
            raise ScienceMicroProbeStageError("IMAGE_TRAINING_WORKSPACE_EXISTS")
        os.rename(temporary, workspace)
        temporary = None
        parent_descriptor = os.open(WORKSPACE_PARENT, os.O_RDONLY | os.O_CLOEXEC)
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
                "probe_id": plan.probe_id,
                "training_run_id": command.training_run_id,
                "command_sha256": command.command_sha256,
                "plan_pointer": plan_pointer.model_dump(mode="json"),
                "training_member_count": len(plan.training_member_ids),
                "workspace": str(workspace),
                "systemd_unit": (
                    f"eom-image-science-lora-micro-probe@{command.training_run_id}.service"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
