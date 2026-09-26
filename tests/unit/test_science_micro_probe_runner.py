from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

from eom_image_contracts import (
    LocalImageLoraTrainingRuntime,
    LocalImageScienceLoraMicroProbeCommand,
    LocalImageScienceLoraMicroRealizedSample,
    LocalImageScienceVisualCropSet,
    content_sha256,
)
from eom_image_trainer import science_micro_probe_runner
from eom_image_trainer.runner import TrainingBackendResult
from PIL import Image, ImageDraw

from tests.unit.test_science_corpus_visual_contracts import (
    _crop_set_value,
    _science_micro_command_value,
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
    command: LocalImageScienceLoraMicroProbeCommand,
    crop_set: LocalImageScienceVisualCropSet,
) -> tuple[LocalImageScienceLoraMicroRealizedSample, ...]:
    members = {value.candidate_id: value for value in crop_set.members}
    values = [
        LocalImageScienceLoraMicroRealizedSample(
            candidate_id=candidate_id,
            document_id=members[candidate_id].document_id,
            exam_group_sha256=members[candidate_id].exam_group_sha256,
            training_sample_id=f"imgtrainsample_{index + 1:032x}",
            source_crop_sha256=members[candidate_id].sha256,
            realized_crop_sha256="sha256:" + f"{index + 100:064x}",
            caption_sha256=members[candidate_id].caption_sha256,
            perceptual_hash=f"{index + 1000:016x}",
        )
        for index, candidate_id in enumerate(command.probe_plan.training_member_ids)
    ]
    return tuple(sorted(values, key=lambda value: value.training_sample_id))


def test_science_micro_probe_runner_emits_only_evaluation_adapter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    command = LocalImageScienceLoraMicroProbeCommand.model_validate(_science_micro_command_value())
    crop_set = LocalImageScienceVisualCropSet.model_validate(_crop_set_value())
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
        science_micro_probe_runner,
        "_load_plan",
        lambda *_args: command.probe_plan,
    )
    monkeypatch.setattr(
        science_micro_probe_runner,
        "_load_crop_set",
        lambda *_args: crop_set,
    )

    def _materialize(**_kwargs):
        runtime_dataset_root.mkdir(mode=0o700)
        return (
            runtime_dataset_root,
            science_micro_probe_runner._RuntimeDataset(
                samples=tuple(
                    science_micro_probe_runner._RuntimeSample(
                        caption_en="black and white Korean science exam illustration",
                        crop_member=science_micro_probe_runner._RuntimeCropMember(
                            member_path=f"samples/{value.training_sample_id}.png"
                        ),
                    )
                    for value in realized
                )
            ),
            realized,
            sample_set_sha256,
        )

    monkeypatch.setattr(science_micro_probe_runner, "_materialize_samples", _materialize)
    monkeypatch.setattr(
        science_micro_probe_runner,
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

    result = science_micro_probe_runner.run_science_micro_probe_command(
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
    assert {value.candidate_id for value in result.realized_samples} == set(
        command.probe_plan.training_member_ids
    )
    assert (workspace / "result.json").is_file()
    assert (workspace / "outputs/manifests/adapter-manifest.json").is_file()


def test_science_micro_probe_materializes_only_exact_training_partition(
    tmp_path: Path,
) -> None:
    command = LocalImageScienceLoraMicroProbeCommand.model_validate(_science_micro_command_value())
    crop_set = LocalImageScienceVisualCropSet.model_validate(_crop_set_value())
    workspace = tmp_path / command.training_run_id
    crops = workspace / command.staged_crops_root
    crops.mkdir(parents=True, mode=0o700)
    members = {value.candidate_id: value for value in crop_set.members}
    updated = []
    for index, candidate_id in enumerate(command.probe_plan.training_member_ids):
        image = Image.new("RGB", (128, 96), "white")
        drawing = ImageDraw.Draw(image)
        for bit in range(8):
            if (index + 1) & (1 << bit):
                drawing.rectangle((bit * 14 + 4, 8, bit * 14 + 12, 88), fill="black")
            else:
                drawing.ellipse((bit * 14 + 4, 36, bit * 14 + 12, 44), fill="black")
        target = io.BytesIO()
        image.save(target, format="PNG", compress_level=9)
        payload = target.getvalue()
        path = crops / f"{candidate_id}.png"
        path.write_bytes(payload)
        path.chmod(0o600)
        updated.append(
            members[candidate_id].model_copy(
                update={
                    "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            )
        )
    untouched = [
        value
        for value in crop_set.members
        if value.candidate_id not in set(command.probe_plan.training_member_ids)
    ]
    runtime_crop_set = crop_set.model_copy(
        update={
            "members": tuple(sorted((*updated, *untouched), key=lambda value: value.candidate_id))
        }
    )
    runtime_command = SimpleNamespace(
        runtime_dataset_root=command.runtime_dataset_root,
        staged_crops_root=command.staged_crops_root,
        probe_plan=command.probe_plan,
    )

    dataset_root, dataset, realized, sample_set_sha256 = (
        science_micro_probe_runner._materialize_samples(
            workspace=workspace,
            command=runtime_command,  # type: ignore[arg-type]
            crop_set=runtime_crop_set,
        )
    )

    assert len(dataset.samples) == 12
    assert len(realized) == 12
    assert {value.candidate_id for value in realized} == set(command.probe_plan.training_member_ids)
    assert sample_set_sha256 == content_sha256(
        [value.model_dump(mode="json") for value in realized]
    )
    assert len(tuple((dataset_root / "samples").glob("*.png"))) == 12
    for sample in dataset.samples:
        with Image.open(dataset_root / sample.crop_member.member_path) as value:
            assert value.size == (768, 512)
            assert value.convert("RGB").getextrema()[0] == value.convert("RGB").getextrema()[1]
