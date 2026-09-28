from __future__ import annotations

from pathlib import Path

from eom_image_contracts import (
    LocalImageLoraTrainingRuntime,
    LocalImageScienceCampaignLoraMicroProbeCommand,
    LocalImageScienceCampaignLoraMicroProbeCommandV2,
    LocalImageScienceCampaignLoraMicroProbeCommandV3,
    LocalImageScienceCampaignLoraMicroRealizedSample,
    LocalImageScienceCampaignLoraMicroRealizedSampleV3,
    LocalImageScienceObjectLineArtCropSet,
    LocalImageScienceVisualCampaignCropSet,
    LocalImageScienceVisualCampaignCropSetV2,
    content_sha256,
)
from eom_image_trainer import science_campaign_micro_probe_runner
from eom_image_trainer.runner import TrainingBackendResult

from tests.unit.test_science_campaign_expanded_training_contracts import (
    _expanded_command_value,
    _expanded_crop_set_value,
)
from tests.unit.test_science_campaign_micro_training_contracts import _command_value
from tests.unit.test_science_corpus_visual_contracts import _campaign_crop_successor_values
from tests.unit.test_science_object_line_art_training_contracts import (
    _crop_set_value as _line_art_crop_set_value,
)
from tests.unit.test_science_object_line_art_training_contracts import (
    _line_art_command_value,
)


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


def _realized(
    command: LocalImageScienceCampaignLoraMicroProbeCommand
    | LocalImageScienceCampaignLoraMicroProbeCommandV2,
    crop_set: LocalImageScienceVisualCampaignCropSet | LocalImageScienceVisualCampaignCropSetV2,
) -> tuple[LocalImageScienceCampaignLoraMicroRealizedSample, ...]:
    members = {value.sample_id: value for value in crop_set.members}
    values = [
        LocalImageScienceCampaignLoraMicroRealizedSample(
            sample_id=sample_id,
            parent_candidate_id=members[sample_id].parent_candidate_id,
            document_id=members[sample_id].document_id,
            exam_group_sha256=members[sample_id].exam_group_sha256,
            training_sample_id=f"imgtrainsample_{index + 1:032x}",
            source_crop_sha256=members[sample_id].sha256,
            realized_crop_sha256="sha256:" + f"{index + 100:064x}",
            caption_sha256=members[sample_id].caption_sha256,
            perceptual_hash=f"{index + 1000:016x}",
        )
        for index, sample_id in enumerate(command.probe_plan.training_member_ids)
    ]
    return tuple(sorted(values, key=lambda value: value.training_sample_id))


def test_campaign_micro_probe_runner_emits_nonactivatable_adapter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    command = LocalImageScienceCampaignLoraMicroProbeCommand.model_validate(_command_value())
    crop_set = LocalImageScienceVisualCampaignCropSet.model_validate(
        _campaign_crop_successor_values()[-1]
    )
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
    realized = _realized(command, crop_set)
    sample_set_sha256 = content_sha256([value.model_dump(mode="json") for value in realized])
    runtime_dataset_root = workspace / command.runtime_dataset_root
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_load_plan",
        lambda *_args: command.probe_plan,
    )
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_load_crop_set",
        lambda *_args: crop_set,
    )

    def _materialize(**_kwargs):
        runtime_dataset_root.mkdir(mode=0o700)
        return (
            runtime_dataset_root,
            science_campaign_micro_probe_runner._RuntimeDataset(
                samples=tuple(
                    science_campaign_micro_probe_runner._RuntimeSample(
                        caption_en="grayscale science assessment reference image",
                        crop_member=science_campaign_micro_probe_runner._RuntimeCropMember(
                            member_path=f"samples/{value.training_sample_id}.png"
                        ),
                    )
                    for value in realized
                )
            ),
            realized,
            sample_set_sha256,
        )

    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_materialize_samples",
        _materialize,
    )
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
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

    result = science_campaign_micro_probe_runner.run_science_campaign_micro_probe_command(
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
    assert {value.sample_id for value in result.realized_samples} == set(
        command.probe_plan.training_member_ids
    )
    assert (workspace / "result.json").is_file()
    assert (workspace / "outputs/manifests/adapter-manifest.json").is_file()


def test_expanded_campaign_micro_probe_runner_dispatches_v2_and_realizes_16(
    monkeypatch,
    tmp_path: Path,
) -> None:
    command = LocalImageScienceCampaignLoraMicroProbeCommandV2.model_validate(
        _expanded_command_value()
    )
    crop_set = LocalImageScienceVisualCampaignCropSetV2.model_validate(_expanded_crop_set_value())
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
            "peak_gpu_memory_bytes": 2048,
        }
    )
    realized = _realized(command, crop_set)
    sample_set_sha256 = content_sha256([value.model_dump(mode="json") for value in realized])
    runtime_dataset_root = workspace / command.runtime_dataset_root
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_load_plan",
        lambda *_args: command.probe_plan,
    )
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_load_crop_set",
        lambda *_args: crop_set,
    )

    def _materialize(**_kwargs):
        runtime_dataset_root.mkdir(mode=0o700)
        return (
            runtime_dataset_root,
            science_campaign_micro_probe_runner._RuntimeDataset(
                samples=tuple(
                    science_campaign_micro_probe_runner._RuntimeSample(
                        caption_en="grayscale science assessment reference image",
                        crop_member=science_campaign_micro_probe_runner._RuntimeCropMember(
                            member_path=f"samples/{value.training_sample_id}.png"
                        ),
                    )
                    for value in realized
                )
            ),
            realized,
            sample_set_sha256,
        )

    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_materialize_samples",
        _materialize,
    )
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
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

    result = science_campaign_micro_probe_runner.run_science_campaign_micro_probe_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(runtime),  # type: ignore[arg-type]
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.schema_version.endswith("/1.1")
    assert result.status == "SUCCEEDED"
    assert result.adapter_manifest is not None
    assert result.adapter_manifest.schema_version.endswith("/1.1")
    assert result.adapter_manifest.activation_policy == "FORBIDDEN"
    assert len(result.realized_samples) == 16
    assert result.sample_set_sha256 == sample_set_sha256


def test_object_line_art_campaign_micro_probe_runner_dispatches_v3_and_realizes_16(
    monkeypatch,
    tmp_path: Path,
) -> None:
    command = LocalImageScienceCampaignLoraMicroProbeCommandV3.model_validate(
        _line_art_command_value()
    )
    crop_set = LocalImageScienceObjectLineArtCropSet.model_validate(_line_art_crop_set_value())
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
            "peak_gpu_memory_bytes": 2048,
        }
    )
    members = {value.sample_id: value for value in crop_set.members}
    realized = tuple(
        LocalImageScienceCampaignLoraMicroRealizedSampleV3(
            sample_id=sample_id,
            parent_candidate_id=members[sample_id].parent_candidate_id,
            document_id=members[sample_id].document_id,
            exam_group_sha256=members[sample_id].exam_group_sha256,
            training_sample_id=f"imgtrainsample_{index + 1:032x}",
            source_crop_sha256=members[sample_id].sha256,
            realized_crop_sha256="sha256:" + f"{index + 100:064x}",
            caption_sha256=members[sample_id].caption_sha256,
            perceptual_hash=f"{index + 1000:016x}",
        )
        for index, sample_id in enumerate(command.probe_plan.training_member_ids)
    )
    realized = tuple(sorted(realized, key=lambda value: value.training_sample_id))
    sample_set_sha256 = content_sha256([value.model_dump(mode="json") for value in realized])
    runtime_dataset_root = workspace / command.runtime_dataset_root
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_load_plan",
        lambda *_args: command.probe_plan,
    )
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_load_crop_set",
        lambda *_args: crop_set,
    )

    def _materialize(**_kwargs):
        runtime_dataset_root.mkdir(mode=0o700)
        return (
            runtime_dataset_root,
            science_campaign_micro_probe_runner._RuntimeDataset(
                samples=tuple(
                    science_campaign_micro_probe_runner._RuntimeSample(
                        caption_en="black and white Korean science assessment object line art",
                        crop_member=science_campaign_micro_probe_runner._RuntimeCropMember(
                            member_path=f"samples/{value.training_sample_id}.png"
                        ),
                    )
                    for value in realized
                )
            ),
            realized,
            sample_set_sha256,
        )

    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
        "_materialize_samples",
        _materialize,
    )
    monkeypatch.setattr(
        science_campaign_micro_probe_runner,
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

    result = science_campaign_micro_probe_runner.run_science_campaign_micro_probe_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(runtime),  # type: ignore[arg-type]
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.schema_version.endswith("/1.2")
    assert result.status == "SUCCEEDED"
    assert result.adapter_manifest is not None
    assert result.adapter_manifest.schema_version.endswith("/1.2")
    assert result.adapter_manifest.state == "EVALUATION_ONLY"
    assert result.adapter_manifest.activation_policy == "FORBIDDEN"
    assert len(result.realized_samples) == 16
    assert result.sample_set_sha256 == sample_set_sha256
