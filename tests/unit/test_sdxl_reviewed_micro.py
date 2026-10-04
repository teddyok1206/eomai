"""CPU fixtures: exact target admission/replay, not evidence of CUDA or quality PASS."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts import (
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_sdxl_lora_micro_result,
)
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    LocalImageSdxlReviewedMicroResult,
    parse_sdxl_reviewed_micro_sources,
)
from eom_image_trainer import sdxl_micro_runner as trainer
from eom_image_trainer import sdxl_training_target_runner as preparation
from eom_image_trainer.runner import TrainingBackendFailure, TrainingBackendResult
from eom_orchestrator import sdxl_micro_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_local_image_training_runner import _runtime, _valid_safetensors
from tests.unit.test_sdxl_lora_micro_contracts import _command_value, _seal_command
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_workspace import _operator
from tests.unit.test_sdxl_source_training_targets import _fixture


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _prepared_fixture(tmp_path, monkeypatch):
    target_root, target_command, metadata, _, _, _ = _fixture(tmp_path, monkeypatch)
    result = preparation.run_sdxl_training_target_command(
        workspace=target_root, command=target_command
    )
    assert result.status == "SUCCEEDED"
    command_raw = content_json_bytes(target_command.model_dump(mode="json"))
    result_raw = content_json_bytes(result.model_dump(mode="json"))
    pointer = {
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "member_path": "manifests/sdxl-training-target-command.json",
        "schema_ref": "eom://schemas/image-provider/local-image-sdxl-training-target-command/1.1",
        "media_type": "application/json",
        "sha256": _sha(command_raw),
    }
    result_pointer = {
        **pointer,
        "member_path": "manifests/sdxl-training-target-result.json",
        "schema_ref": "eom://schemas/image-provider/local-image-sdxl-training-target-result/1.1",
        "sha256": _sha(result_raw),
    }
    original, _ = _command_value()
    value = {
        key: original[key]
        for key in (
            "created_by",
            "source_commit",
            "base_model",
            "experiment_authorization",
            "dependencies",
            "hyperparameters",
            "budget",
            "seed",
            "activation_policy",
        )
    }
    value.update(
        {
            "schema_version": "local-image-sdxl-lora-micro-command/1.1",
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_crop_set": target_command.source_crop_set.model_dump(mode="json"),
            "training_authorization": target_command.training_authorization.model_dump(mode="json"),
            "target_batches": [{"command": pointer, "result": result_pointer}],
            "training_samples": [
                {
                    "sample_id": target.sample_id,
                    "target_id": target.target_id,
                    "target_revision_id": target.target_revision_id,
                    "source_image": {
                        **result_pointer,
                        "member_path": target.member_path,
                        "schema_ref": "eom://schemas/image-provider/local-image-sdxl-training-target-png/1.0",
                        "media_type": "image/png",
                        "sha256": target.sha256,
                    },
                    "training_caption_en": target.training_caption_en,
                    "training_caption_sha256": target.training_caption_sha256,
                }
                for target in result.prepared_targets
            ],
            "review_scope": "OWN_TRAIN_TARGET_SCREENING_NOT_INDEPENDENT",
            "caption_policy": "EXACT_REVIEWED_TARGET_CAPTION/1.0",
            "preprocessing_policy": "EXACT_PREPARED_RGB_768X512/1.0",
            "purpose": "EVALUATION_ONLY_SDXL_REVIEWED_LITERAL_TARGET_MICRO",
        }
    )
    value["budget"]["maximum_peak_gpu_memory_bytes"] = 16 * 1024**3
    command = LocalImageSdxlReviewedMicroCommand.model_validate(_seal_command(value))
    metadata = {
        **metadata,
        "inputs/target-batches/0/command.json": command_raw,
        "inputs/target-batches/0/result.json": result_raw,
    }
    root = tmp_path / command.training_run_id
    root.mkdir(mode=0o700)
    _write(root / "command.json", content_json_bytes(command.model_dump(mode="json")))
    for name, raw in metadata.items():
        _write(root / name, raw)
    pixels = {}
    for sample in command.training_samples:
        raw = (target_root / sample.source_image.member_path).read_bytes()
        pixels[sample.sample_id] = raw
        _write(root / sample.staged_member_path, raw)
    return root, command, metadata, pixels


class _Backend:
    def __init__(self, fault=None):
        self.calls, self.fault, self.samples = 0, fault, ()

    def train(self, *, stack, samples, command, output_root):
        self.calls += 1
        self.samples = samples
        if self.fault == "cancel":
            raise TrainingBackendFailure(
                "IMAGE_TRAINING_CANCELLED", completed_steps=7, final_loss=0.5, cancelled=True
            )
        if self.fault == "oom":
            raise TrainingBackendFailure("IMAGE_TRAINING_CUDA_OOM")
        output_root.mkdir(mode=0o700)
        _write(
            output_root / "adapter_config.json",
            content_json_bytes(
                {
                    "peft_type": "LORA",
                    "r": 8,
                    "lora_alpha": 8,
                    "target_modules": ["to_k", "to_out.0", "to_q", "to_v"],
                    "base_model_name_or_path": "PINNED_LOCAL_MODEL_REVISION",
                    "bias": "none",
                    "inference_mode": True,
                    "task_type": None,
                }
            ),
        )
        _write(output_root / "adapter_model.safetensors", _valid_safetensors())
        return TrainingBackendResult(_runtime(), 200, 0.08)


def _run(monkeypatch, root, command, backend):
    monkeypatch.setattr(trainer, "resolve_sdxl_stack", lambda *a: object())
    return trainer.run_sdxl_micro_command(
        workspace=root, command=command, model_store_root=Path("/fixture"), backend=backend
    )


def test_success_reuses_exact_target_bytes_and_replay_never_trains_or_transforms(
    tmp_path, monkeypatch
):
    root, command, metadata, pixels = _prepared_fixture(tmp_path, monkeypatch)
    assert parse_sdxl_reviewed_micro_sources(command, metadata)
    validate_contract("sdxl-lora-micro-command-v2", command.model_dump(mode="json"))
    assert trainer.load_sdxl_micro_command(root, root / "command.json") == command

    def forbidden(*a, **kw):
        raise AssertionError("reviewed targets must not be transformed again")

    monkeypatch.setattr(trainer, "materialize_training_crop", forbidden)
    backend = _Backend()
    result = _run(monkeypatch, root, command, backend)
    assert result.status == "SUCCEEDED" and backend.calls == 1
    assert not (root / "runtime-dataset").exists()
    assert tuple(s.image_path.read_bytes() for s in backend.samples) == tuple(
        pixels[s.sample_id] for s in command.training_samples
    )
    assert all(s.realized_crop_sha256 == s.source_crop_sha256 for s in result.realized_samples)
    validate_contract("sdxl-lora-micro-result-v2", result.model_dump(mode="json"))
    validate_sdxl_lora_micro_result(command, result)
    assert _run(monkeypatch, root, command, backend) == result
    assert backend.calls == 1


@pytest.mark.parametrize(
    "fault", ["caption", "revision", "pointer_hash", "missing_source", "batch_hash"]
)
def test_mismatched_derivative_fails_before_target_pixels(tmp_path, monkeypatch, fault):
    _, command, metadata, _ = _prepared_fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    sample = value["training_samples"][0]
    if fault == "caption":
        sample["training_caption_en"] += " unrelated"
        sample["training_caption_sha256"] = text_sha256(sample["training_caption_en"])
    elif fault == "revision":
        sample["target_revision_id"] = "imgsdxltargetrev_" + "0" * 32
    elif fault == "pointer_hash":
        sample["source_image"]["sha256"] = "sha256:" + "0" * 64
    elif fault == "missing_source":
        sample["sample_id"] = "imgsourcecrop_" + "0" * 32
        value["training_samples"].sort(key=lambda s: s["sample_id"])
    else:
        value["target_batches"][0]["result"]["sha256"] = "sha256:" + "0" * 64
    command = LocalImageSdxlReviewedMicroCommand.model_validate(_seal_command(value))
    with pytest.raises(ValueError):
        parse_sdxl_reviewed_micro_sources(command, metadata)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "pixel_duplicate",
        "old_source_id",
        "wrong_batch_revision",
        "permission",
        "schema_version",
    ],
)
def test_invalid_successor_does_not_alias_old_contract(tmp_path, monkeypatch, fault):
    _, command, _, _ = _prepared_fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "duplicate":
        value["training_samples"][1] = copy.deepcopy(value["training_samples"][0])
    elif fault == "pixel_duplicate":
        value["training_samples"][1]["source_image"]["sha256"] = value["training_samples"][0][
            "source_image"
        ]["sha256"]
    elif fault == "old_source_id":
        value["training_samples"][0]["sample_id"] = "imgscivislineartcrop_" + "0" * 32
    elif fault == "wrong_batch_revision":
        value["training_samples"][0]["source_image"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif fault == "permission":
        value["experiment_authorization"]["permitted_uses"] = ["INTERNAL_SDXL_COMPARISON"]
    else:
        value["schema_version"] = "local-image-sdxl-lora-micro-command/1.0"
    with pytest.raises((ValidationError, SchemaError)):
        value = _seal_command(value)
        validate_contract("sdxl-lora-micro-command-v2", value)
        LocalImageSdxlReviewedMicroCommand.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("sdxl-lora-micro-command", command.model_dump(mode="json"))


@pytest.mark.parametrize("fault", ["cancel", "oom"])
def test_terminal_failure_preserves_evidence_without_adapter_or_auto_retry(
    tmp_path, monkeypatch, fault
):
    root, command, _, _ = _prepared_fixture(tmp_path, monkeypatch)
    backend = _Backend(fault)
    result = _run(monkeypatch, root, command, backend)
    assert result.status == ("CANCELLED" if fault == "cancel" else "FAILED")
    assert result.adapter_manifest is None and len(result.realized_samples) == 2
    assert _run(monkeypatch, root, command, backend) == result and backend.calls == 1


def test_success_requires_full_command_coverage_and_exact_realized_hash(tmp_path, monkeypatch):
    root, command, _, _ = _prepared_fixture(tmp_path, monkeypatch)
    result = _run(monkeypatch, root, command, _Backend())
    value = result.model_dump(mode="json")
    value["realized_samples"].pop()
    value["sample_set_sha256"] = content_sha256(value["realized_samples"])
    value["adapter_manifest"] = None
    value["status"], value["error_code"] = "FAILED", "IMAGE_TRAINING_EXEC_FAILED"
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    LocalImageSdxlReviewedMicroResult.model_validate(value)
    changed = result.model_copy(update={"realized_samples": result.realized_samples[:-1]})
    with pytest.raises(ValueError, match="cover"):
        validate_sdxl_lora_micro_result(command, changed)
    changed = result.model_copy(
        update={
            "realized_samples": (
                result.realized_samples[0].model_copy(
                    update={"realized_crop_sha256": "sha256:" + "0" * 64}
                ),
                *result.realized_samples[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="pinned"):
        validate_sdxl_lora_micro_result(command, changed)


def test_admission_batches_pixels_only_after_full_lineage_and_handoff_is_exclusive(
    tmp_path, monkeypatch
):
    _, command, metadata, pixels = _prepared_fixture(tmp_path, monkeypatch)
    events = []
    records = {command.source_crop_set: metadata["inputs/source-crop-set.json"]}
    from eom_image_contracts.sdxl_reviewed_micro import sdxl_reviewed_micro_metadata_pointers

    for name, pointer in sdxl_reviewed_micro_metadata_pointers(
        command, metadata["inputs/source-crop-set.json"]
    ).items():
        records[pointer] = metadata[name]
    for sample in command.training_samples:
        records[sample.source_image] = pixels[sample.sample_id]

    def read(engine, pointer, *, maximum_bytes):
        assert len(records[pointer]) <= maximum_bytes
        events.append(pointer.media_type)
        return records[pointer]

    monkeypatch.setattr(admission, "resolve_control_artifact_member", read)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda engine, reads: tuple(
            read(engine, r.pointer, maximum_bytes=r.maximum_bytes) for r in reads
        ),
    )
    monkeypatch.setattr(
        admission, "prepare_source_page_crop_reads", lambda *a: events.append("LINEAGE_ADMITTED")
    )
    prepared = admission.prepare_sdxl_micro_inputs(object(), command)
    assert events.index("LINEAGE_ADMITTED") < events.index("image/png")
    assert events.count("image/png") == 2 and len(prepared.files) == 8
    root, worker, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_micro_inputs(prepared, workspace_parent=root, worker=worker)
    assert (
        staged.systemd_unit == f"eom-image-sdxl-lora-micro-probe@{command.training_run_id}.service"
    )
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_micro_inputs(prepared, workspace_parent=root, worker=worker)
    with pytest.raises((ValueError, handoff.SdxlProbeHandoffError)):
        handoff.stage_sdxl_micro_inputs(
            replace(prepared, files=prepared.files[:-1]), workspace_parent=root, worker=worker
        )


def test_corrupted_staged_metadata_and_target_never_call_backend(tmp_path, monkeypatch):
    root, command, _, _ = _prepared_fixture(tmp_path, monkeypatch)
    target = root / command.training_samples[0].staged_member_path
    _write(target, b"invalid bytes")
    backend = _Backend()
    result = _run(monkeypatch, root, command, backend)
    assert result.status == "FAILED" and backend.calls == 0
    _write(root / "inputs/target-batches/0/result.json", b"{}")
    with pytest.raises(trainer.SdxlMicroRunnerError):
        _run(monkeypatch, root, command, backend)
    assert backend.calls == 0
