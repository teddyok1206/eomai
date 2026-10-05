"""Native geometry/lifecycle application tests; numerical training is stubbed, never CUDA."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

import pytest
from eom_image_contracts import content_json_bytes
from eom_image_trainer import cli
from eom_image_trainer import sdxl_native_lora_runner as runner
from eom_image_trainer.crop_processing import decode_png, png_bytes
from eom_image_trainer.runner import TrainingBackendFailure, TrainingBackendResult
from PIL import Image, ImageDraw

from tests.unit.test_local_image_training_runner import _runtime, _valid_safetensors
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_lora_sources import _fixture, _staged_metadata


def _png(sample_id, width, height):
    image = Image.new("RGB", (width, height), "white")
    index = int(sample_id[-8:], 16) % 50
    ImageDraw.Draw(image).ellipse((64 + index, 64, 440, 480 + index), outline="black", width=4)
    return png_bytes(image)


def _stage(monkeypatch, tmp_path, *, pixel_factory=_png):
    command, records, pixels, *_ = _fixture(monkeypatch, pixel_factory=pixel_factory)
    workspace = tmp_path / command.training_run_id
    workspace.mkdir(mode=0o700)
    _write(workspace / "command.json", content_json_bytes(command.model_dump(mode="json")))
    for member, raw in _staged_metadata(records).items():
        _write(workspace / member, raw)
    for sample in command.training_samples:
        _write(workspace / sample.staged_member_path, pixels[sample.target_id])
    return workspace, command


class _Backend:
    def __init__(self, fault=None):
        self.calls = 0
        self.samples = ()
        self.fault = fault

    def train(self, *, stack, samples, command, output_root):
        self.calls += 1
        self.samples = samples
        if self.fault == "cancel":
            raise TrainingBackendFailure(
                "IMAGE_TRAINING_CANCELLED", completed_steps=7, final_loss=0.5, cancelled=True
            )
        if self.fault == "oom":
            raise TrainingBackendFailure("IMAGE_TRAINING_CUDA_OOM")
        if self.fault == "interrupt":
            raise KeyboardInterrupt
        if self.fault == "exception":
            raise RuntimeError("private model or prompt details must not appear")
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
            _write(output_root / "unexpected.bin", b"not an adapter")
        if self.fault == "missing_member":
            (output_root / "adapter_config.json").unlink()
        runtime = _runtime().model_copy(
            update={**command.dependencies.model_dump(), "peak_gpu_memory_bytes": 512 * 1024**2}
        )
        if self.fault == "drift":
            runtime = runtime.model_copy(update={"python_version": "0.0.0"})
        if self.fault == "memory":
            runtime = runtime.model_copy(update={"peak_gpu_memory_bytes": 17 * 1024**3})
        return TrainingBackendResult(
            runtime=runtime,
            completed_steps=7 if self.fault == "steps" else command.hyperparameters.max_train_steps,
            final_loss=float("nan") if self.fault == "loss" else 0.08,
        )


def _run(monkeypatch, workspace, command, backend):
    monkeypatch.setattr(runner, "resolve_sdxl_stack", lambda *args: object())
    return runner.run_sdxl_native_lora_command(
        workspace=workspace,
        model_store_root=Path("/fixture/model-store"),
        command=command,
        backend=backend,
    )


def test_native_success_preserves_all_geometry_pixels_and_final_conditioning(monkeypatch, tmp_path):
    workspace, command = _stage(monkeypatch, tmp_path)
    original = {
        s.staged_member_path: (workspace / s.staged_member_path).read_bytes()
        for s in command.training_samples
    }
    backend = _Backend()
    result = _run(monkeypatch, workspace, command, backend)
    assert result.status == "SUCCEEDED"
    assert result.completed_steps == command.hyperparameters.max_train_steps
    assert result.adapter_manifest.state == "EVALUATION_ONLY"
    assert result.adapter_manifest.activation_policy == "FORBIDDEN"
    assert (
        result.adapter_manifest.schema_version
        == "local-image-sdxl-native-lora-adapter-manifest/1.0"
    )
    assert len(result.realized_samples) == 12
    assert {(s.width_px, s.height_px) for s in backend.samples} == {
        (1024, 1024),
        (768, 1024),
        (1024, 768),
    }
    assert tuple(s.caption_en for s in backend.samples) == tuple(
        s.training_caption_en for s in command.training_samples
    )
    assert not (workspace / "runtime-dataset").exists()
    for member, raw in original.items():
        assert (workspace / member).read_bytes() == raw
    assert runner.load_sdxl_native_lora_command(workspace, workspace / "command.json") == command
    assert (
        json.loads((workspace / "result.json").read_bytes())["result_sha256"]
        == result.result_sha256
    )


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
        "loss",
    ],
)
def test_native_backend_failure_never_accepts_adapter(monkeypatch, tmp_path, fault):
    workspace, command = _stage(monkeypatch, tmp_path)
    result = _run(monkeypatch, workspace, command, _Backend(fault))
    assert result.status == ("CANCELLED" if fault in {"cancel", "interrupt"} else "FAILED")
    assert result.adapter_manifest is None
    assert not (workspace / "adapter-manifest.json").exists()
    assert "private model" not in (workspace / "result.json").read_text()
    if fault == "cancel":
        assert result.completed_steps == 7
    if fault == "drift":
        assert result.runtime is None
        assert result.error_code == "IMAGE_TRAINING_RUNTIME_DRIFT"


@pytest.mark.parametrize("fault", [None, "oom", "cancel"])
def test_terminal_native_replay_does_not_decode_train_or_rewrite(monkeypatch, tmp_path, fault):
    workspace, command = _stage(monkeypatch, tmp_path)
    backend = _Backend(fault)
    result = _run(monkeypatch, workspace, command, backend)
    original = (workspace / "result.json").read_bytes()
    monkeypatch.setattr(runner, "decode_png", lambda *a: pytest.fail("replay decoded tensors"))
    monkeypatch.setattr(
        runner, "write_staged_member", lambda *a: pytest.fail("replay rewrote output")
    )
    monkeypatch.setattr(
        runner, "resolve_sdxl_stack", lambda *a: pytest.fail("replay resolved model")
    )
    assert (
        runner.run_sdxl_native_lora_command(
            workspace=workspace,
            model_store_root=Path("/fixture/model-store"),
            command=command,
            backend=backend,
        )
        == result
    )
    assert (workspace / "result.json").read_bytes() == original
    assert backend.calls == 1


@pytest.mark.parametrize(
    "fault", ["metadata", "foreign_metadata", "foreign_png", "hash", "symlink"]
)
def test_staged_native_input_rejection_precedes_model_work(monkeypatch, tmp_path, fault):
    workspace, command = _stage(monkeypatch, tmp_path)
    target = workspace / command.training_samples[0].staged_member_path
    backend = _Backend()
    monkeypatch.setattr(
        runner, "resolve_sdxl_stack", lambda *a: pytest.fail("invalid source read model")
    )
    if fault == "metadata":
        _write(next((workspace / "inputs/metadata").iterdir()), b"{}")
    elif fault.startswith("foreign"):
        _write(
            workspace
            / (
                "inputs/metadata/foreign.json"
                if fault == "foreign_metadata"
                else "inputs/targets/foreign.png"
            ),
            b"foreign",
        )
    elif fault == "hash":
        _write(target, b"corrupt")
    else:
        target.unlink()
        target.symlink_to(workspace / command.training_samples[1].staged_member_path)
    if fault in {"hash", "symlink"}:
        result = runner.run_sdxl_native_lora_command(
            workspace=workspace,
            model_store_root=Path("/fixture/model-store"),
            command=command,
            backend=backend,
        )
        assert result.status == "FAILED"
    else:
        with pytest.raises(runner.SdxlNativeLoraRunnerError):
            runner.run_sdxl_native_lora_command(
                workspace=workspace,
                model_store_root=Path("/fixture/model-store"),
                command=command,
                backend=backend,
            )
        assert not (workspace / "result.json").exists()
    assert backend.calls == 0


@pytest.mark.parametrize(
    "pixel_factory",
    [
        lambda sid, w, h: _png(sid, w - 1, h),
        lambda sid, w, h: png_bytes(decode_png(_png(sid, w, h)).convert("L")),
    ],
)
def test_valid_png_hash_does_not_authorize_wrong_geometry_or_mode(
    monkeypatch, tmp_path, pixel_factory
):
    workspace, command = _stage(monkeypatch, tmp_path, pixel_factory=pixel_factory)
    backend = _Backend()
    result = _run(monkeypatch, workspace, command, backend)
    assert result.error_code == "IMAGE_TRAINING_SAMPLE_DIMENSIONS_INVALID"
    assert backend.calls == 0


@pytest.mark.parametrize(
    "member", ["result.json", "adapter-manifest.json", "adapter/adapter_model.safetensors", "input"]
)
def test_terminal_native_replay_rejects_corruption_without_overwriting_history(
    monkeypatch, tmp_path, member
):
    workspace, command = _stage(monkeypatch, tmp_path)
    backend = _Backend()
    _run(monkeypatch, workspace, command, backend)
    target = workspace / (
        command.training_samples[0].staged_member_path if member == "input" else member
    )
    _write(target, b"corrupt")
    before = (workspace / "result.json").read_bytes()
    with pytest.raises(runner.SdxlNativeLoraRunnerError):
        _run(monkeypatch, workspace, command, backend)
    assert (workspace / "result.json").read_bytes() == before
    assert backend.calls == 1


@pytest.mark.parametrize("member", ["adapter", "adapter-manifest.json", "runtime-dataset"])
def test_unreceipted_native_output_never_retrains(monkeypatch, tmp_path, member):
    workspace, command = _stage(monkeypatch, tmp_path)
    if member.endswith("json"):
        _write(workspace / member, b"{}")
    else:
        (workspace / member).mkdir(mode=0o700)
    backend = _Backend()
    with pytest.raises(runner.SdxlNativeLoraRunnerError, match="IMAGE_TRAINING_UNRECEIPTED_OUTPUT"):
        _run(monkeypatch, workspace, command, backend)
    assert backend.calls == 0


def test_native_time_budget_expires_before_model_resolution(monkeypatch, tmp_path):
    workspace, command = _stage(monkeypatch, tmp_path)
    times = iter((0, 31, 31))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        runner, "resolve_sdxl_stack", lambda *a: pytest.fail("expired budget read model")
    )
    backend = _Backend()
    result = runner.run_sdxl_native_lora_command(
        workspace=workspace,
        model_store_root=Path("/fixture/model-store"),
        command=command,
        backend=backend,
    )
    assert result.error_code == "IMAGE_TRAINING_RESOURCE_BUDGET_EXCEEDED"
    assert result.duration_ms == 31_000
    assert backend.calls == 0


def test_native_command_is_not_a_released_micro_alias(monkeypatch, tmp_path):
    from eom_image_trainer.sdxl_micro_runner import SdxlMicroRunnerError, load_sdxl_micro_command

    workspace, command = _stage(monkeypatch, tmp_path)
    with pytest.raises(SdxlMicroRunnerError, match="DOCUMENT_INVALID"):
        load_sdxl_micro_command(workspace, workspace / "command.json")
    assert runner.load_sdxl_native_lora_command(workspace, workspace / "command.json") == command


@pytest.mark.parametrize("fault", [None, "cancel", "exception"])
def test_native_cli_shares_gpu_exclusion_and_restores_signal(monkeypatch, tmp_path, fault):
    workspace, _command = _stage(monkeypatch, tmp_path)
    state = tmp_path / "gpu-state"
    state.mkdir(mode=0o700)
    lock = state / "gpu0.lock"
    backend = _Backend(fault)
    monkeypatch.setattr(runner, "resolve_sdxl_stack", lambda *a: object())
    monkeypatch.setattr(cli, "SdxlNativeLoraBackend", lambda: backend)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eom-local-image-trainer",
            "sdxl-native-lora",
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
    descriptor = cli._lock_gpu(lock)
    try:
        with pytest.raises(Exception, match="IMAGE_TRAINING_GPU_BUSY"):
            cli._lock_gpu(lock)
    finally:
        os.close(descriptor)
    assert backend.calls == 1
