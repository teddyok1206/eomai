#!/usr/bin/env python3
"""Stage one user-authorized, evaluation-only LoRA micro probe."""

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
    LocalImageLoraMicroProbeCommand,
    LocalImageLoraMicroProbePlan,
    LocalImageLoraMicroSelection,
    LocalImageTrainingAuthorization,
    LocalImageTrainingCropProposalSet,
    content_sha256,
    validate_contract,
    validate_micro_probe_plan_sources,
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
    MAX_PAGE_BYTES,
    WORKSPACE_PARENT,
    _load_artifact_member,
    _parse_json,
    _require_release,
    _safe_read,
    _write_exclusive,
)

TRAINER_USER = "eom-image"
TRAINER_PYTHON = Path("/srv/eom/conda/envs/eom-image-trainer/bin/python")


class MicroProbeStageError(RuntimeError):
    """Stable operator-facing staging failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal-artifact-id", required=True)
    parser.add_argument("--proposal-artifact-revision-id", required=True)
    parser.add_argument("--proposal-artifact-sha256", required=True)
    parser.add_argument("--selections", type=Path, required=True)
    parser.add_argument("--selections-file-sha256", required=True)
    parser.add_argument("--authorized-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--authorization-reference-sha256", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--seed", type=int, default=20260925)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise MicroProbeStageError("IMAGE_TRAINING_TIMESTAMP_INVALID")
    return value


def _proposal_pointer(args: argparse.Namespace) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=args.proposal_artifact_id,
        artifact_revision_id=args.proposal_artifact_revision_id,
        member_path="manifests/crop-proposals.json",
        schema_ref=("eom://schemas/image-provider/local-image-training-crop-proposal-set/1.0"),
        media_type="application/json",
        sha256=args.proposal_artifact_sha256,
    )


def _load_proposal_set(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
) -> LocalImageTrainingCropProposalSet:
    payload = _load_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = _parse_json(payload)
        validate_contract("training-crop-proposal-set", value)
        proposal_set = LocalImageTrainingCropProposalSet.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroProbeStageError("IMAGE_TRAINING_PROPOSAL_SET_INVALID") from exc
    if content_sha256(proposal_set.model_dump(mode="json")) != pointer.sha256:
        raise MicroProbeStageError("IMAGE_TRAINING_PROPOSAL_SET_POINTER_MISMATCH")
    return proposal_set


def _load_authorization(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
) -> LocalImageTrainingAuthorization:
    payload = _load_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = _parse_json(payload)
        validate_contract("training-authorization", value)
        authorization = LocalImageTrainingAuthorization.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroProbeStageError("IMAGE_TRAINING_AUTHORIZATION_INVALID") from exc
    if content_sha256(authorization.model_dump(mode="json")) != pointer.sha256:
        raise MicroProbeStageError("IMAGE_TRAINING_AUTHORIZATION_POINTER_MISMATCH")
    return authorization


def _load_selections(args: argparse.Namespace) -> tuple[LocalImageLoraMicroSelection, ...]:
    payload = _safe_read(
        args.selections,
        expected_sha256=args.selections_file_sha256,
        maximum_bytes=MAX_JSON_BYTES,
    )
    try:
        value = json.loads(payload)
        if not isinstance(value, list):
            raise TypeError
        selections = tuple(LocalImageLoraMicroSelection.model_validate(item) for item in value)
    except (json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroProbeStageError("IMAGE_TRAINING_MICRO_SELECTION_INVALID") from exc
    if not 12 <= len(selections) <= 18:
        raise MicroProbeStageError("IMAGE_TRAINING_MICRO_SELECTION_INVALID")
    return tuple(sorted(selections, key=lambda value: value.crop_proposal_id))


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
        raise MicroProbeStageError("IMAGE_TRAINING_RUNTIME_DRIFT") from exc
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
        raise MicroProbeStageError("IMAGE_TRAINING_RUNTIME_DRIFT")
    return value


def _build_plan(
    *,
    args: argparse.Namespace,
    proposal_pointer: ImageEvaluationArtifactMember,
    proposal_set: LocalImageTrainingCropProposalSet,
    authorization: LocalImageTrainingAuthorization,
    selections: tuple[LocalImageLoraMicroSelection, ...],
) -> LocalImageLoraMicroProbePlan:
    binding = load_local_image_provider_binding(
        CatalogSettings.from_environment().local_image_provider_binding
    )
    body = {
        "schema_version": "local-image-lora-micro-probe-plan/1.0",
        "source_snapshot": proposal_set.source_snapshot.model_dump(mode="json"),
        "training_authorization": proposal_set.training_authorization.model_dump(mode="json"),
        "crop_proposal_set": proposal_pointer.model_dump(mode="json"),
        "crop_proposal_set_sha256": proposal_set.proposal_set_sha256,
        "holdout_evaluation_plan": proposal_set.holdout_evaluation_plan.model_dump(mode="json"),
        "holdout_sample_ids": list(proposal_set.holdout_sample_ids),
        "holdout_source_anchor_ids": list(proposal_set.holdout_source_anchor_ids),
        "base_model": binding.model.model_dump(mode="json"),
        "preprocessing_revision": "local-image-micro-crop-preprocess/1.0",
        "selections": [value.model_dump(mode="json") for value in selections],
        "trainer_contract": "eom-local-image-lora-micro-trainer/1.0",
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
        "purpose": "EVALUATION_ONLY_MICRO_PROBE",
        "activation_policy": "FORBIDDEN",
        "authorized_at": _utc(args.authorized_at).isoformat().replace("+00:00", "Z"),
        "authorized_by": args.authorized_by,
        "authorization_reference_sha256": args.authorization_reference_sha256,
        "created_at": _utc(args.created_at).isoformat().replace("+00:00", "Z"),
        "created_by": args.created_by,
        "source_commit": args.source_commit,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "probe_id": "imgmicroprobe_" + identity[:32]}
    value = {**with_id, "plan_sha256": content_sha256(with_id)}
    try:
        validate_contract("lora-micro-probe-plan", value)
        plan = LocalImageLoraMicroProbePlan.model_validate(value)
        validate_micro_probe_plan_sources(plan, proposal_set, authorization)
        return plan
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroProbeStageError("IMAGE_TRAINING_MICRO_PLAN_INVALID") from exc


def _build_command(
    *,
    plan: LocalImageLoraMicroProbePlan,
    plan_pointer: ImageEvaluationArtifactMember,
) -> LocalImageLoraMicroProbeCommand:
    identity = content_sha256(
        {
            "probe_plan_pointer": plan_pointer.model_dump(mode="json"),
            "probe_plan_sha256": plan.plan_sha256,
            "attempt": 1,
        }
    ).removeprefix("sha256:")
    body = {
        "schema_version": "local-image-lora-micro-probe-command/1.0",
        "training_run_id": "imgmicrotrainrun_" + identity[:32],
        "probe_plan_pointer": plan_pointer.model_dump(mode="json"),
        "probe_plan_sha256": plan.plan_sha256,
        "probe_plan": plan.model_dump(mode="json"),
        "attempt": 1,
        "staged_plan_member": "inputs/micro-probe-plan.json",
        "staged_authorization_member": "inputs/training-authorization.json",
        "staged_proposal_set_member": "inputs/crop-proposals.json",
        "staged_pages_root": "inputs/pages",
        "runtime_dataset_root": "runtime-dataset",
        "output_root_member": "outputs",
        "checkpoint_root_member": "checkpoints",
        "timeout_seconds": 7200,
    }
    value = {**body, "command_sha256": content_sha256(body)}
    try:
        validate_contract("lora-micro-probe-command", value)
        return LocalImageLoraMicroProbeCommand.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise MicroProbeStageError("IMAGE_TRAINING_MICRO_COMMAND_INVALID") from exc


def _stage_file(path: Path, payload: bytes, *, trainer_gid: int) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise MicroProbeStageError("IMAGE_TRAINING_WORKSPACE_INVALID")
    _write_exclusive(path, payload, mode=0o440)
    os.chown(path, 0, trainer_gid)


def main() -> None:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    proposal_pointer = _proposal_pointer(args)
    selections = _load_selections(args)
    account = pwd.getpwnam(TRAINER_USER)
    trainer_gid = grp.getgrnam(TRAINER_USER).gr_gid
    engine = build_engine()
    temporary: Path | None = None
    try:
        proposal_set = _load_proposal_set(engine, proposal_pointer)
        authorization = _load_authorization(engine, proposal_set.training_authorization)
        plan = _build_plan(
            args=args,
            proposal_pointer=proposal_pointer,
            proposal_set=proposal_set,
            authorization=authorization,
            selections=selections,
        )
        selected = {value.crop_proposal_id for value in selections}
        proposals = tuple(
            value for value in proposal_set.proposals if value.crop_proposal_id in selected
        )
        if len(proposals) != len(selections):
            raise MicroProbeStageError("IMAGE_TRAINING_MICRO_SELECTION_INVALID")
        page_pointers = {
            (value.source_page_image.artifact_revision_id, value.source_page_image.member_path): (
                value.source_page_image
            )
            for value in proposals
        }
        page_payloads = {
            key: _load_artifact_member(engine, pointer, maximum_bytes=MAX_PAGE_BYTES)
            for key, pointer in page_pointers.items()
        }
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "status": "PREFLIGHT_PASS",
                        "probe_id": plan.probe_id,
                        "plan_sha256": plan.plan_sha256,
                        "selection_count": len(selections),
                        "unique_page_count": len(page_payloads),
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
        plan_pointer = publisher.commit_micro_probe_plan(plan)
        command = _build_command(plan=plan, plan_pointer=plan_pointer)
        temporary = Path(tempfile.mkdtemp(prefix=".micro-probe-staging.", dir=WORKSPACE_PARENT))
        os.chmod(temporary, 0o700)
        inputs = temporary / "inputs"
        inputs.mkdir(mode=0o550)
        os.chown(inputs, 0, trainer_gid)
        _stage_file(
            inputs / "micro-probe-plan.json",
            canonical_json_bytes(plan.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        _stage_file(
            inputs / "crop-proposals.json",
            canonical_json_bytes(proposal_set.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        _stage_file(
            inputs / "training-authorization.json",
            canonical_json_bytes(authorization.model_dump(mode="json")),
            trainer_gid=trainer_gid,
        )
        pages = inputs / "pages"
        pages.mkdir(mode=0o550)
        os.chown(pages, 0, trainer_gid)
        for key, pointer in sorted(page_pointers.items()):
            _stage_file(
                pages / f"{pointer.sha256.removeprefix('sha256:')}.png",
                page_payloads[key],
                trainer_gid=trainer_gid,
            )
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
            raise MicroProbeStageError("IMAGE_TRAINING_WORKSPACE_EXISTS")
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
                "selection_count": len(plan.selections),
                "workspace": str(workspace),
                "systemd_unit": (f"eom-image-lora-micro-probe@{command.training_run_id}.service"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
