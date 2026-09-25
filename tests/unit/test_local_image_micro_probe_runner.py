from __future__ import annotations

from pathlib import Path

from eom_image_contracts import (
    LocalImageLoraMicroProbeCommand,
    LocalImageLoraMicroRealizedSample,
    LocalImageLoraTrainingRuntime,
    content_sha256,
)
from eom_image_trainer import micro_probe_runner
from eom_image_trainer.runner import TrainingBackendResult

from tests.unit.test_local_image_lora_micro_probe_contracts import _command_value


class _Backend:
    def __init__(self, runtime: LocalImageLoraTrainingRuntime) -> None:
        self.runtime = runtime

    def train(
        self,
        *,
        model_directory: Path,
        dataset: object,
        dataset_root: Path,
        command: object,
        output_root: Path,
        checkpoint_root: Path,
    ) -> TrainingBackendResult:
        assert model_directory.is_dir()
        assert dataset_root.is_dir()
        assert checkpoint_root.is_dir()
        output_root.mkdir(mode=0o700)
        return TrainingBackendResult(
            runtime=self.runtime,
            completed_steps=200,
            final_loss=0.125,
        )


def _realized() -> tuple[LocalImageLoraMicroRealizedSample, ...]:
    return tuple(
        LocalImageLoraMicroRealizedSample(
            source_anchor_id=f"assessmentanchor_{index:032x}",
            crop_proposal_id=f"imgcropproposal_{index:032x}",
            training_sample_id=f"imgtrainsample_{index:032x}",
            crop_sha256="sha256:" + f"{index + 1:064x}",
            caption_sha256="sha256:" + f"{index + 100:064x}",
            perceptual_hash=f"{index + 1:016x}",
        )
        for index in range(12)
    )


def test_micro_probe_runner_emits_only_evaluation_adapter(monkeypatch, tmp_path: Path) -> None:
    command = LocalImageLoraMicroProbeCommand.model_validate(_command_value())
    workspace = tmp_path / command.training_run_id
    workspace.mkdir(mode=0o700)
    model_directory = tmp_path / "model"
    model_directory.mkdir()
    runtime = LocalImageLoraTrainingRuntime.model_validate(
        {
            **command.probe_plan.dependencies.model_dump(mode="json"),
            "cuda_version": "12.8",
            "gpu_name": "NVIDIA GeForce RTX 5080",
            "compute_capability": "12.0",
            "peak_gpu_memory_bytes": 1024,
        }
    )
    realized = _realized()
    sample_set_sha256 = content_sha256([value.model_dump(mode="json") for value in realized])
    runtime_dataset_root = workspace / command.runtime_dataset_root

    monkeypatch.setattr(micro_probe_runner, "_load_plan", lambda *_args: command.probe_plan)
    monkeypatch.setattr(micro_probe_runner, "_load_proposal_set", lambda *_args: object())
    monkeypatch.setattr(micro_probe_runner, "_load_authorization", lambda *_args: object())
    monkeypatch.setattr(
        micro_probe_runner,
        "validate_micro_probe_plan_sources",
        lambda *_args: None,
    )

    def _materialize(**_kwargs):
        runtime_dataset_root.mkdir(mode=0o700)
        return (
            runtime_dataset_root,
            micro_probe_runner._RuntimeDataset(
                samples=tuple(
                    micro_probe_runner._RuntimeSample(
                        caption_en=selection.caption_en,
                        crop_member=micro_probe_runner._RuntimeCropMember(
                            member_path=f"samples/{realized[index].training_sample_id}.png"
                        ),
                    )
                    for index, selection in enumerate(command.probe_plan.selections)
                )
            ),
            realized,
            sample_set_sha256,
        )

    monkeypatch.setattr(micro_probe_runner, "_materialize_samples", _materialize)
    monkeypatch.setattr(
        micro_probe_runner,
        "validate_adapter_files",
        lambda _root: (
            {
                "relative_path": "adapter_config.json",
                "size_bytes": 128,
                "sha256": "sha256:" + "a" * 64,
            },
            {
                "relative_path": "adapter_model.safetensors",
                "size_bytes": 4096,
                "sha256": "sha256:" + "b" * 64,
            },
        ),
    )

    result = micro_probe_runner.run_micro_probe_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(runtime),  # type: ignore[arg-type]
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.status == "SUCCEEDED"
    assert result.adapter_manifest is not None
    assert result.adapter_manifest.state == "EVALUATION_ONLY"
    assert result.adapter_manifest.activation_policy == "FORBIDDEN"
    assert result.sample_set_sha256 == sample_set_sha256
    assert (workspace / "result.json").is_file()
    assert (workspace / "outputs/manifests/adapter-manifest.json").is_file()
