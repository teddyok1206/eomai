from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import cast

import pytest
from eom_image_contracts import (
    LocalImageLoraMicroAdapterManifest,
    LocalImageLoraMicroProbeCommand,
    LocalImageLoraMicroProbePlan,
    LocalImageLoraMicroProbeWorkerResult,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_micro_probe_worker_result,
)
from pydantic import BaseModel, ValidationError


def _sha(value: str) -> str:
    return "sha256:" + value * 64


def _pointer(name: str, schema_ref: str, member_path: str) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + name * 32,
        "artifact_revision_id": "rev_" + name * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": "application/json",
        "sha256": _sha(name),
    }


def _plan_value() -> dict[str, object]:
    selections = [
        {
            "source_anchor_id": f"assessmentanchor_{index:032x}",
            "crop_proposal_id": f"imgcropproposal_{index:032x}",
            "caption_en": f"A bounded assessment illustration sample {index}",
            "caption_sha256": text_sha256(f"A bounded assessment illustration sample {index}"),
        }
        for index in range(12)
    ]
    body: dict[str, object] = {
        "schema_version": "local-image-lora-micro-probe-plan/1.0",
        "source_snapshot": {
            "graph_revision_id": "graphrev_" + "1" * 32,
            "graph_snapshot_sha256": _sha("1"),
            "graph_manifest_sha256": _sha("2"),
            "target_count": 520,
            "target_set_sha256": _sha("3"),
        },
        "training_authorization": _pointer(
            "4",
            "eom://schemas/image-provider/local-image-training-authorization/1.0",
            "manifests/training-authorization.json",
        ),
        "crop_proposal_set": _pointer(
            "5",
            "eom://schemas/image-provider/local-image-training-crop-proposal-set/1.0",
            "manifests/crop-proposals.json",
        ),
        "crop_proposal_set_sha256": _sha("6"),
        "holdout_evaluation_plan": _pointer(
            "7",
            "eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0",
            "manifests/evaluation-plan.json",
        ),
        "holdout_sample_ids": [f"imgsample_{index + 100:032x}" for index in range(12)],
        "holdout_source_anchor_ids": [
            f"assessmentanchor_{index + 100:032x}" for index in range(12)
        ],
        "base_model": {
            "model_id": "imgmodel_" + "8" * 32,
            "model_revision_id": "imgmodelrev_" + "9" * 32,
            "manifest_sha256": _sha("a"),
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        },
        "preprocessing_revision": "local-image-micro-crop-preprocess/1.0",
        "selections": selections,
        "trainer_contract": "eom-local-image-lora-micro-trainer/1.0",
        "dependencies": {
            "python_version": "3.11.14",
            "torch_version": "2.7.1+cu128",
            "diffusers_version": "0.35.2",
            "transformers_version": "4.56.2",
            "accelerate_version": "1.10.1",
            "peft_version": "0.17.1",
            "bitsandbytes_version": "0.47.0",
        },
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
        "seed": 20260925,
        "purpose": "EVALUATION_ONLY_MICRO_PROBE",
        "activation_policy": "FORBIDDEN",
        "authorized_at": "2026-09-25T12:00:00Z",
        "authorized_by": "user:owner",
        "authorization_reference_sha256": _sha("b"),
        "created_at": "2026-09-25T12:01:00Z",
        "created_by": "codex:root",
        "source_commit": "c" * 40,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["probe_id"] = "imgmicroprobe_" + identity[:32]
    body["plan_sha256"] = content_sha256(body)
    return body


def _command_value() -> dict[str, object]:
    plan = LocalImageLoraMicroProbePlan.model_validate(_plan_value())
    pointer = _pointer(
        "d",
        "eom://schemas/image-provider/local-image-lora-micro-probe-plan/1.0",
        "manifests/micro-probe-plan.json",
    )
    identity = content_sha256(
        {
            "probe_plan_pointer": pointer,
            "probe_plan_sha256": plan.plan_sha256,
            "attempt": 1,
        }
    ).removeprefix("sha256:")
    body: dict[str, object] = {
        "schema_version": "local-image-lora-micro-probe-command/1.0",
        "training_run_id": "imgmicrotrainrun_" + identity[:32],
        "probe_plan_pointer": pointer,
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
    return {**body, "command_sha256": content_sha256(body)}


def _adapter_value(
    command: LocalImageLoraMicroProbeCommand,
    sample_set_sha256: str,
) -> dict[str, object]:
    files = [
        {
            "relative_path": "adapter_config.json",
            "size_bytes": 128,
            "sha256": _sha("e"),
        },
        {
            "relative_path": "adapter_model.safetensors",
            "size_bytes": 4096,
            "sha256": _sha("f"),
        },
    ]
    identity = content_sha256(
        {
            "probe_plan": command.probe_plan_pointer.model_dump(mode="json"),
            "training_run_id": command.training_run_id,
        }
    ).removeprefix("sha256:")
    revision = content_sha256({"adapter_identity": identity, "files": files}).removeprefix(
        "sha256:"
    )
    body: dict[str, object] = {
        "schema_version": "local-image-lora-micro-adapter-manifest/1.0",
        "adapter_id": "imgadapter_" + identity[:32],
        "adapter_revision_id": "imgadapterrev_" + revision[:32],
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "base_model": command.probe_plan.base_model.model_dump(mode="json"),
        "probe_plan": command.probe_plan_pointer.model_dump(mode="json"),
        "sample_set_sha256": sample_set_sha256,
        "files": files,
        "created_at": "2026-09-25T12:20:00Z",
    }
    return {**body, "manifest_sha256": content_sha256(body)}


def _result_value() -> dict[str, object]:
    command = LocalImageLoraMicroProbeCommand.model_validate(_command_value())
    realized = [
        {
            "source_anchor_id": f"assessmentanchor_{index:032x}",
            "crop_proposal_id": f"imgcropproposal_{index:032x}",
            "training_sample_id": f"imgtrainsample_{index:032x}",
            "crop_sha256": "sha256:" + f"{index + 1:064x}",
            "caption_sha256": command.probe_plan.selections[index].caption_sha256,
            "perceptual_hash": f"{index + 1:016x}",
        }
        for index in range(12)
    ]
    sample_set_sha256 = content_sha256(realized)
    body: dict[str, object] = {
        "schema_version": "local-image-lora-micro-probe-worker-result/1.0",
        "training_run_id": command.training_run_id,
        "probe_plan_pointer": command.probe_plan_pointer.model_dump(mode="json"),
        "probe_plan_sha256": command.probe_plan_sha256,
        "command_sha256": command.command_sha256,
        "attempt": 1,
        "status": "SUCCEEDED",
        "adapter_manifest": _adapter_value(command, sample_set_sha256),
        "realized_samples": realized,
        "sample_set_sha256": sample_set_sha256,
        "error_code": None,
        "runtime": {
            **command.probe_plan.dependencies.model_dump(mode="json"),
            "cuda_version": "12.8",
            "gpu_name": "NVIDIA GeForce RTX 5080",
            "compute_capability": "12.0",
            "peak_gpu_memory_bytes": 1024,
        },
        "completed_steps": 200,
        "final_loss": 0.25,
        "started_at": "2026-09-25T12:02:00Z",
        "completed_at": "2026-09-25T12:20:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


@pytest.mark.parametrize(
    ("contract", "factory", "model"),
    [
        ("lora-micro-probe-plan", _plan_value, LocalImageLoraMicroProbePlan),
        ("lora-micro-probe-command", _command_value, LocalImageLoraMicroProbeCommand),
        (
            "lora-micro-probe-worker-result",
            _result_value,
            LocalImageLoraMicroProbeWorkerResult,
        ),
    ],
)
def test_micro_probe_contract_schema_and_model_parity(
    contract: str,
    factory: Callable[[], dict[str, object]],
    model: type[BaseModel],
) -> None:
    value = factory()
    validate_contract(contract, value)
    model.model_validate(value)


def test_micro_probe_adapter_is_structurally_evaluation_only() -> None:
    command = LocalImageLoraMicroProbeCommand.model_validate(_command_value())
    value = _adapter_value(command, _sha("1"))
    validate_contract("lora-micro-adapter-manifest", value)
    adapter = LocalImageLoraMicroAdapterManifest.model_validate(value)
    assert adapter.state == "EVALUATION_ONLY"
    assert adapter.activation_policy == "FORBIDDEN"


def test_micro_probe_rejects_fewer_than_twelve_selections() -> None:
    value = _plan_value()
    selections = cast(list[dict[str, object]], value["selections"])
    value["selections"] = selections[:11]
    with pytest.raises(ValidationError):
        LocalImageLoraMicroProbePlan.model_validate(value)


def test_micro_probe_rejects_duplicate_source_anchor() -> None:
    value = _plan_value()
    selections = cast(list[dict[str, object]], deepcopy(value["selections"]))
    selections[1]["source_anchor_id"] = selections[0]["source_anchor_id"]
    value["selections"] = selections
    with pytest.raises(ValidationError, match="unique source anchors"):
        LocalImageLoraMicroProbePlan.model_validate(value)


def test_micro_probe_worker_result_binds_command() -> None:
    command = LocalImageLoraMicroProbeCommand.model_validate(_command_value())
    result = LocalImageLoraMicroProbeWorkerResult.model_validate(_result_value())
    validate_micro_probe_worker_result(command, result)
    changed = result.model_copy(update={"command_sha256": _sha("0")})
    with pytest.raises(ValueError, match="exact command"):
        validate_micro_probe_worker_result(command, changed)
