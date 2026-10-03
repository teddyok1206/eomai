from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageScienceObjectLineArtCropSet,
    LocalImageSdxlLoraMicroCommand,
    content_json_bytes,
    content_sha256,
)
from eom_image_trainer import cli
from eom_image_trainer import sdxl_micro_runner as runner
from eom_image_trainer.crop_processing import decode_png, png_bytes
from eom_image_trainer.runner import TrainingBackendFailure, TrainingBackendResult
from PIL import Image, ImageDraw

from tests.unit.test_local_image_training_runner import _runtime, _valid_safetensors
from tests.unit.test_science_corpus_visual_contracts import _authorization_value
from tests.unit.test_sdxl_lora_micro_contracts import _command_value, _seal_command


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)


def _png(index: int) -> bytes:
    image = Image.new("RGB", (96, 96), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((3, 3, 15, 15), fill="black")
    drawing.ellipse((20 + index, 24, 72, 73 + index), outline="black", width=3)
    return png_bytes(image)


def _stage(tmp_path: Path, *, duplicate=False, suffix=b""):
    value, crop_set = _command_value()
    crops = crop_set.model_dump(mode="json")
    authorization = content_json_bytes(_authorization_value()) + suffix
    crops["training_authorization"]["sha256"] = _sha(authorization)
    members = {member["sample_id"]: member for member in crops["members"]}
    pngs = {}
    for index, sample in enumerate(value["training_samples"]):
        raw = _png(index)
        if duplicate and index in {0, 1}:
            image = decode_png(_png(0))
            ImageDraw.Draw(image).rectangle((4, 4, 10, 10), fill=(index, index, index))
            raw = png_bytes(image)
        sample["source_image"]["sha256"] = _sha(raw)
        member = members[sample["sample_id"]]
        member["sha256"] = _sha(raw)
        member["size_bytes"] = len(raw)
        member["sample_id"] = (
            "imgscivislineartcrop_"
            + content_sha256(
                {
                    key: item
                    for key, item in member.items()
                    if key not in {"sample_id", "member_path"}
                }
            )[7:39]
        )
        member["member_path"] = "crops/" + member["sample_id"] + ".png"
        sample["sample_id"] = member["sample_id"]
        sample["source_image"]["member_path"] = member["member_path"]
        pngs[member["sample_id"]] = raw
    crops["members"].sort(key=lambda member: member["sample_id"])
    value["training_samples"].sort(key=lambda sample: sample["sample_id"])
    crops["crop_set_id"] = (
        "imgscivislineartcropset_"
        + content_sha256(
            {
                key: item
                for key, item in crops.items()
                if key not in {"crop_set_id", "crop_set_sha256"}
            }
        )[7:39]
    )
    crops["crop_set_sha256"] = content_sha256(
        {key: item for key, item in crops.items() if key != "crop_set_sha256"}
    )
    raw_crops = content_json_bytes(crops) + suffix
    LocalImageScienceObjectLineArtCropSet.model_validate(crops)
    value["crop_set"]["sha256"] = _sha(raw_crops)
    value["crop_set_semantic_sha256"] = crops["crop_set_sha256"]
    value["training_authorization"] = crops["training_authorization"]
    for sample in value["training_samples"] if duplicate else value["training_samples"][:1]:
        sample["redaction_boxes"] = [{"left": 0, "top": 0, "right": 2000, "bottom": 2000}]
    value["budget"]["maximum_peak_gpu_memory_bytes"] = 16 * 1024**3
    command = LocalImageSdxlLoraMicroCommand.model_validate(_seal_command(value))
    workspace = tmp_path / command.training_run_id
    workspace.mkdir(mode=0o700)
    _write(workspace / "command.json", content_json_bytes(command.model_dump(mode="json")))
    _write(workspace / "inputs/crop-set.json", raw_crops)
    _write(workspace / "inputs/authorization.json", authorization)
    for sample in command.training_samples:
        _write(workspace / sample.staged_member_path, pngs[sample.sample_id])
    return workspace, command


class _Backend:
    """CPU-only application stub: never evidence of actual CUDA training."""

    def __init__(self, *, fault=None):
        self.calls = 0
        self.fault = fault
        self.samples = ()

    def train(self, *, stack, samples, command, output_root):
        self.calls += 1
        self.samples = samples
        assert len(samples) == 16
        if self.fault == "cancel":
            raise TrainingBackendFailure(
                "IMAGE_TRAINING_CANCELLED", completed_steps=7, final_loss=0.5, cancelled=True
            )
        if self.fault == "oom":
            raise TrainingBackendFailure("IMAGE_TRAINING_CUDA_OOM")
        if self.fault == "interrupt":
            raise KeyboardInterrupt
        if self.fault == "exception":
            raise RuntimeError("private details must not appear in result")
        output_root.mkdir(mode=0o700)
        _write(
            output_root / "adapter_config.json",
            content_json_bytes(
                {
                    "peft_type": "LORA",
                    "r": 8,
                    "lora_alpha": 8,
                    "target_modules": ["to_k", "to_out.0", "to_q", "to_v"],
                }
            ),
        )
        _write(output_root / "adapter_model.safetensors", _valid_safetensors())
        if self.fault == "invalid_weights":
            _write(output_root / "adapter_model.safetensors", b"invalid")
        if self.fault == "extra_member":
            _write(output_root / "unexpected.bin", b"not an accepted adapter")
        if self.fault == "missing_member":
            (output_root / "adapter_config.json").unlink()
        runtime = _runtime()
        if self.fault == "drift":
            runtime = runtime.model_copy(update={"python_version": "3.11.15"})
        if self.fault == "memory":
            runtime = runtime.model_copy(update={"peak_gpu_memory_bytes": 17 * 1024**3})
        return TrainingBackendResult(
            runtime=runtime, completed_steps=7 if self.fault == "steps" else 200, final_loss=0.08
        )


def _run(monkeypatch, workspace, command, backend):
    monkeypatch.setattr(runner, "resolve_sdxl_stack", lambda *args: object())
    return runner.run_sdxl_micro_command(
        workspace=workspace,
        model_store_root=Path("/fixture/model-store"),
        command=command,
        backend=backend,
    )


@pytest.mark.parametrize("suffix", [b"", b"\n"])
def test_success_materializes_only_train_redacts_and_seals_adapter(monkeypatch, tmp_path, suffix):
    workspace, command = _stage(tmp_path, suffix=suffix)
    backend = _Backend()
    result = _run(monkeypatch, workspace, command, backend)
    assert result.status == "SUCCEEDED"
    assert result.completed_steps == 200
    assert result.adapter_manifest.base_model == command.base_model
    assert result.adapter_manifest.state == "EVALUATION_ONLY"
    assert result.adapter_manifest.activation_policy == "FORBIDDEN"
    assert len(result.realized_samples) == 16
    assert {path.stem for path in (workspace / "runtime-dataset").iterdir()} == {
        sample.sample_id for sample in command.training_samples
    }
    assert backend.samples[0].caption_en == command.training_samples[0].training_caption_en
    image = decode_png(backend.samples[0].image_path.read_bytes())
    assert image.size == (768, 512)
    assert image.getpixel((346, 218)) == (255, 255, 255)  # Original top-left mark redacted.
    assert _sha((workspace / command.training_samples[0].staged_member_path).read_bytes()) == (
        command.training_samples[0].source_image.sha256
    )
    assert runner.load_sdxl_micro_command(workspace, workspace / "command.json") == command
    assert json.loads((workspace / "result.json").read_bytes())["result_sha256"] == (
        result.result_sha256
    )


@pytest.mark.parametrize("fault", ["hash", "dimensions", "authorization", "symlink"])
def test_invalid_source_fails_before_backend(monkeypatch, tmp_path, fault):
    workspace, command = _stage(tmp_path)
    target = workspace / command.training_samples[0].staged_member_path
    if fault == "hash":
        _write(target, b"not the pinned source")
    elif fault == "authorization":
        _write(workspace / "inputs/authorization.json", b"{}")
    elif fault == "symlink":
        target.unlink()
        target.symlink_to(workspace / command.training_samples[1].staged_member_path)
    else:
        # The on-disk command is valid but lies about dimensions; the crop-set catches it.
        value = command.model_dump(mode="json")
        value["training_samples"][0]["source_width_px"] = 97
        command = LocalImageSdxlLoraMicroCommand.model_validate(_seal_command(value))
        replacement = workspace.parent / command.training_run_id
        workspace.rename(replacement)
        workspace = replacement
        _write(workspace / "command.json", content_json_bytes(command.model_dump(mode="json")))
    backend = _Backend()
    result = _run(monkeypatch, workspace, command, backend)
    assert result.status == "FAILED"
    assert result.adapter_manifest is None
    assert backend.calls == 0


def test_duplicate_realized_pixels_do_not_train(monkeypatch, tmp_path):
    workspace, command = _stage(tmp_path, duplicate=True)
    # Distinct source PNGs differ only inside a declared redaction.
    backend = _Backend()
    result = _run(monkeypatch, workspace, command, backend)
    assert result.error_code == "IMAGE_TRAINING_DUPLICATE_REALIZED_PIXELS"
    assert backend.calls == 0


@pytest.mark.parametrize(
    "fault",
    [
        "cancel",
        "oom",
        "interrupt",
        "exception",
        "invalid_weights",
        "extra_member",
        "missing_member",
        "drift",
        "memory",
        "steps",
    ],
)
def test_backend_failure_never_accepts_adapter(monkeypatch, tmp_path, fault):
    workspace, command = _stage(tmp_path)
    result = _run(monkeypatch, workspace, command, _Backend(fault=fault))
    assert result.status == ("CANCELLED" if fault in {"cancel", "interrupt"} else "FAILED")
    assert result.adapter_manifest is None
    assert not (workspace / "adapter-manifest.json").exists()
    assert "private details" not in (workspace / "result.json").read_text()
    if fault == "drift":
        assert result.runtime is None
        assert result.error_code == "IMAGE_TRAINING_RUNTIME_DRIFT"
    if fault == "cancel":
        assert result.completed_steps == 7


@pytest.mark.parametrize("fault", [None, "oom", "cancel"])
def test_terminal_replay_preserves_receipt_without_retraining(monkeypatch, tmp_path, fault):
    workspace, command = _stage(tmp_path)
    backend = _Backend(fault=fault)
    original = _run(monkeypatch, workspace, command, backend)
    result_bytes = (workspace / "result.json").read_bytes()
    assert _run(monkeypatch, workspace, command, backend) == original
    assert (workspace / "result.json").read_bytes() == result_bytes
    assert backend.calls == 1


@pytest.mark.parametrize(
    "member",
    ["result.json", "adapter-manifest.json", "adapter/adapter_model.safetensors", "derived"],
)
def test_terminal_replay_rejects_corruption(monkeypatch, tmp_path, member):
    workspace, command = _stage(tmp_path)
    backend = _Backend()
    _run(monkeypatch, workspace, command, backend)
    target = (
        workspace / member
        if member != "derived"
        else (workspace / "runtime-dataset" / (command.training_samples[0].sample_id + ".png"))
    )
    _write(target, b"corrupt")
    with pytest.raises(runner.SdxlMicroRunnerError):
        _run(monkeypatch, workspace, command, backend)
    assert backend.calls == 1


@pytest.mark.parametrize("member", ["runtime-dataset", "adapter"])
def test_unreceipted_partial_output_cannot_be_silently_retrained(monkeypatch, tmp_path, member):
    workspace, command = _stage(tmp_path)
    (workspace / member).mkdir(mode=0o700)
    backend = _Backend()
    with pytest.raises(runner.SdxlMicroRunnerError, match="IMAGE_TRAINING_UNRECEIPTED_OUTPUT"):
        _run(monkeypatch, workspace, command, backend)
    assert backend.calls == 0


def test_application_time_budget_expires_before_gpu_dispatch(monkeypatch, tmp_path):
    workspace, command = _stage(tmp_path)
    times = iter((0, 31, 31))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(times))
    backend = _Backend()
    result = _run(monkeypatch, workspace, command, backend)
    assert result.error_code == "IMAGE_TRAINING_RESOURCE_BUDGET_EXCEEDED"
    assert result.duration_ms == 31_000
    assert backend.calls == 0


@pytest.mark.parametrize("fault", [None, "cancel", "exception"])
def test_cli_uses_shared_gpu_lock_and_restores_sigterm(monkeypatch, tmp_path, fault):
    workspace, _command = _stage(tmp_path)
    state = tmp_path / "gpu-state"
    state.mkdir(mode=0o700)
    lock = state / "gpu0.lock"
    backend = _Backend(fault=fault)
    monkeypatch.setattr(runner, "resolve_sdxl_stack", lambda *args: object())
    monkeypatch.setattr(cli, "SdxlMicroLoraBackend", lambda: backend)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eom-local-image-trainer",
            "sdxl-micro-probe",
            "--workspace",
            str(workspace),
            "--command",
            str(workspace / "command.json"),
            "--model-store-root",
            str(tmp_path),
            "--gpu-lock",
            str(lock),
        ],
    )
    previous = signal.getsignal(signal.SIGTERM)
    if fault is None:
        cli.main()
    else:
        with pytest.raises(SystemExit, match="IMAGE_TRAINING_"):
            cli.main()
    assert signal.getsignal(signal.SIGTERM) == previous
    assert backend.calls == 1
    # A closed descriptor releases the lock even on terminal failure.
    descriptor = cli._lock_gpu(lock)
    os.close(descriptor)


def test_fixed_micro_unit_keeps_offline_runtime_and_bounded_timeout():
    path = (
        Path(__file__).resolve().parents[2]
        / "infra/systemd/eom-image-sdxl-lora-micro-probe@.service"
    )
    text = path.read_text()
    for invariant in (
        "User=eom-image",
        "PrivateNetwork=true",
        "NoNewPrivileges=true",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/home/eom/EOM\n",
        "sdxl-micro-probe --command /srv/eom/image-training-workspaces/%i/command.json",
        "--gpu-lock /var/lib/eom-image/gpu0.lock",
        "TimeoutStartSec=3660",
        "Restart=no",
    ):
        assert invariant in text
