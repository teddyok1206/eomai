from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageLoraTrainingCommand,
    LocalImageLoraTrainingPlan,
    LocalImageLoraTrainingRuntime,
    content_sha256,
    validate_contract,
)
from eom_image_trainer import (
    TrainingBackendFailure,
    TrainingBackendResult,
    TrainingRunnerError,
    run_training_command,
)

from tests.unit.test_local_image_dataset_builder import _build


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _runtime() -> LocalImageLoraTrainingRuntime:
    return LocalImageLoraTrainingRuntime.model_validate(
        {
            "python_version": "3.11.13",
            "torch_version": "2.7.1+cu128",
            "diffusers_version": "0.35.2",
            "transformers_version": "4.56.2",
            "accelerate_version": "1.10.1",
            "peft_version": "0.17.1",
            "bitsandbytes_version": "0.47.0",
            "cuda_version": "12.8",
            "gpu_name": "NVIDIA GeForce RTX 5080",
            "compute_capability": "12.0",
            "peak_gpu_memory_bytes": 12_000_000_000,
        }
    )


def _valid_safetensors() -> bytes:
    header = json.dumps(
        {
            "lora.test": {
                "dtype": "F32",
                "shape": [1],
                "data_offsets": [0, 4],
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return len(header).to_bytes(8, "little") + header + b"\0\0\0\0"


class SuccessfulBackend:
    def train(self, **kwargs: object) -> TrainingBackendResult:
        output_root = kwargs["output_root"]
        command = kwargs["command"]
        assert isinstance(output_root, Path)
        assert isinstance(command, LocalImageLoraTrainingCommand)
        output_root.mkdir(mode=0o700)
        config = {
            "peft_type": "LORA",
            "r": 8,
            "lora_alpha": 8,
            "target_modules": ["to_k", "to_out.0", "to_q", "to_v"],
        }
        config_path = output_root / "adapter_config.json"
        config_path.write_bytes(_canonical_json(config))
        config_path.chmod(0o600)
        weights_path = output_root / "adapter_model.safetensors"
        weights_path.write_bytes(_valid_safetensors())
        weights_path.chmod(0o600)
        return TrainingBackendResult(
            runtime=_runtime(),
            completed_steps=command.training_plan.hyperparameters.max_train_steps,
            final_loss=0.08,
        )


class FailedBackend:
    def train(self, **_kwargs: object) -> TrainingBackendResult:
        raise TrainingBackendFailure("IMAGE_TRAINING_CUDA_OOM")


class InvalidOutputBackend(SuccessfulBackend):
    def train(self, **kwargs: object) -> TrainingBackendResult:
        result = super().train(**kwargs)
        output_root = kwargs["output_root"]
        assert isinstance(output_root, Path)
        (output_root / "adapter_model.safetensors").write_bytes(b"invalid")
        return result


def _stage_command(
    tmp_path: Path,
) -> tuple[Path, Path, LocalImageLoraTrainingCommand]:
    dataset, dataset_output, _, _, _ = _build(tmp_path / "dataset-build")
    workspace = tmp_path / "worker"
    workspace.mkdir(mode=0o700)
    inputs = workspace / "inputs"
    inputs.mkdir(mode=0o700)
    shutil.copytree(dataset_output / "dataset", inputs / "dataset")
    dataset_manifest_path = inputs / "dataset/manifests/training-dataset.json"
    dataset_pointer = {
        "artifact_id": "artifact_" + "1" * 32,
        "artifact_revision_id": "rev_" + "2" * 32,
        "member_path": "manifests/training-dataset.json",
        "schema_ref": ("eom://schemas/image-provider/local-image-training-dataset-manifest/1.0"),
        "media_type": "application/json",
        "sha256": _sha(dataset_manifest_path.read_bytes()),
    }
    body = {
        "schema_version": "local-image-lora-training-plan/1.0",
        "training_plan_id": "imgtrainplan_" + "3" * 32,
        "dataset_manifest": dataset_pointer,
        "base_model": dataset.base_model.model_dump(mode="json"),
        "trainer_contract": "eom-local-image-lora-trainer/1.0",
        "dependencies": {
            "python_version": "3.11.13",
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
            "checkpointing_steps": 100,
            "random_flip": False,
            "train_text_encoders": False,
            "train_vae": False,
        },
        "seed": 20260925,
        "created_at": "2026-09-25T04:00:00Z",
        "created_by": "operator_test",
    }
    plan_value = {**body, "plan_sha256": content_sha256(body)}
    validate_contract("lora-training-plan", plan_value)
    plan = LocalImageLoraTrainingPlan.model_validate(plan_value)
    plan_payload = _canonical_json(plan_value)
    plan_path = inputs / "training-plan.json"
    plan_path.write_bytes(plan_payload)
    plan_path.chmod(0o600)
    command_body = {
        "schema_version": "local-image-lora-training-command/1.0",
        "training_run_id": "imgtrainrun_" + "4" * 32,
        "training_plan_pointer": {
            "artifact_id": "artifact_" + "5" * 32,
            "artifact_revision_id": "rev_" + "6" * 32,
            "member_path": "manifests/training-plan.json",
            "schema_ref": ("eom://schemas/image-provider/local-image-lora-training-plan/1.0"),
            "media_type": "application/json",
            "sha256": _sha(plan_payload),
        },
        "training_plan_sha256": plan.plan_sha256,
        "training_plan": plan.model_dump(mode="json"),
        "attempt": 1,
        "staged_plan_member": "inputs/training-plan.json",
        "staged_dataset_root": "inputs/dataset",
        "output_root_member": "outputs",
        "checkpoint_root_member": "checkpoints",
        "timeout_seconds": 3600,
    }
    command_value = {
        **command_body,
        "command_sha256": content_sha256(command_body),
    }
    validate_contract("lora-training-command", command_value)
    command = LocalImageLoraTrainingCommand.model_validate(command_value)
    model_root = tmp_path / "models"
    model_root.mkdir(mode=0o700)
    return workspace, model_root, command


def _model_resolver(_root: Path, _pointer: object) -> tuple[object, Path]:
    return object(), _root


def test_training_runner_validates_and_writes_success_result(tmp_path: Path) -> None:
    workspace, model_root, command = _stage_command(tmp_path)
    result = run_training_command(
        workspace=workspace,
        model_store_root=model_root,
        command=command,
        backend=SuccessfulBackend(),
        model_resolver=_model_resolver,
    )
    assert result.status == "SUCCEEDED"
    assert result.adapter_manifest is not None
    assert result.completed_steps == 200
    assert (workspace / "outputs/manifests/adapter-manifest.json").is_file()
    assert (workspace / "result.json").is_file()


def test_training_runner_writes_typed_backend_failure(tmp_path: Path) -> None:
    workspace, model_root, command = _stage_command(tmp_path)
    result = run_training_command(
        workspace=workspace,
        model_store_root=model_root,
        command=command,
        backend=FailedBackend(),
        model_resolver=_model_resolver,
    )
    assert result.status == "FAILED"
    assert result.error_code == "IMAGE_TRAINING_CUDA_OOM"
    assert result.runtime is None
    assert result.adapter_manifest is None


def test_training_runner_allows_exact_checkpoint_root_after_interruption(
    tmp_path: Path,
) -> None:
    workspace, model_root, command = _stage_command(tmp_path)
    (workspace / "checkpoints").mkdir(mode=0o700)
    result = run_training_command(
        workspace=workspace,
        model_store_root=model_root,
        command=command,
        backend=SuccessfulBackend(),
        model_resolver=_model_resolver,
    )
    assert result.status == "SUCCEEDED"


def test_training_runner_maps_invalid_adapter_to_typed_failure(tmp_path: Path) -> None:
    workspace, model_root, command = _stage_command(tmp_path)
    result = run_training_command(
        workspace=workspace,
        model_store_root=model_root,
        command=command,
        backend=InvalidOutputBackend(),
        model_resolver=_model_resolver,
    )
    assert result.status == "FAILED"
    assert result.error_code == "IMAGE_TRAINING_ADAPTER_INVALID"
    assert result.runtime == _runtime()
    assert result.completed_steps == 200


def test_training_runner_rejects_staged_sample_hash_drift(tmp_path: Path) -> None:
    workspace, model_root, command = _stage_command(tmp_path)
    sample = command.training_plan.dataset_manifest
    assert sample.member_path == "manifests/training-dataset.json"
    first = next((workspace / "inputs/dataset/samples").glob("*.png"))
    first.write_bytes(first.read_bytes() + b"changed")
    with pytest.raises(TrainingRunnerError, match="IMAGE_TRAINING_SAMPLE_HASH_MISMATCH"):
        run_training_command(
            workspace=workspace,
            model_store_root=model_root,
            command=command,
            backend=SuccessfulBackend(),
            model_resolver=_model_resolver,
        )
    assert not (workspace / "outputs").exists()
