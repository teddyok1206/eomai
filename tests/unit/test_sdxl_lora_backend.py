from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_image_contracts import LocalImageSdxlLineartStack, LocalImageSdxlLoraMicroCommand
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommand
from eom_image_contracts.sdxl_native_training_targets import NATIVE_TARGET_CANVASES
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack
from eom_image_trainer import diffusers_backend as numerical
from eom_image_trainer.runner import TrainingBackendFailure, TrainingBackendResult
from eom_image_trainer.sdxl_lora_backend import SdxlMicroLoraBackend, SdxlNativeLoraBackend
from PIL import Image

from tests.unit.test_local_image_training_runner import _runtime
from tests.unit.test_sdxl_lineart_stack_contract import _stack
from tests.unit.test_sdxl_lora_micro_contracts import _command_value
from tests.unit.test_sdxl_native_lora_contracts import _command_value as _native_command_value


def _inputs(tmp_path: Path):
    value, _ = _command_value()
    command = LocalImageSdxlLoraMicroCommand.model_validate(value)
    stack = ResolvedSdxlStack(
        LocalImageSdxlLineartStack.model_validate(_stack()),
        {role: tmp_path / role.lower() for role in ("BASE", "LINEART_ADAPTER", "VAE")},
    )
    samples = tuple(
        numerical.LoraTensorSample(
            sample.training_caption_en, tmp_path / (sample.sample_id + ".png")
        )
        for sample in command.training_samples
    )
    return command, stack, samples


def test_sdxl_uses_real_base_and_fixed_vae_without_ssd_conversion_or_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    command, stack, samples = _inputs(tmp_path)
    expected = TrainingBackendResult(_runtime(), 200, 0.1)
    captured: dict[str, Any] = {}

    def train(_self: object, **kwargs: Any):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(numerical.DiffusersUnetLoraBackend, "train", train)
    assert (
        SdxlMicroLoraBackend().train(
            stack=stack, samples=samples, command=command, output_root=tmp_path / "adapter"
        )
        == expected
    )
    assert captured == {
        "model_directory": stack.component_roots["BASE"],
        "vae_source": numerical.VaeWeightLocation(stack.component_roots["VAE"], None, None),
        "samples": samples,
        "recipe": numerical.LoraTrainingRecipe(
            command.dependencies, command.hyperparameters, command.seed
        ),
        "output_root": tmp_path / "adapter",
        "checkpoint_policy": None,
        "budget": numerical.LoraTrainingBudget(
            command.budget.maximum_duration_ms, command.budget.maximum_peak_gpu_memory_bytes
        ),
    }


@pytest.mark.parametrize("fault", ["count", "caption", "model", "revision", "hash"])
def test_sdxl_wrapper_rejects_mismatched_inputs_before_numerical_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fault: str
) -> None:
    command, stack, samples = _inputs(tmp_path)
    if fault == "count":
        samples = samples[:-1]
    elif fault == "caption":
        samples = (numerical.LoraTensorSample("different", samples[0].image_path), *samples[1:])
    else:
        field = {"model": "model_id", "revision": "model_revision_id", "hash": "manifest_sha256"}[
            fault
        ]
        stack = ResolvedSdxlStack(
            stack.manifest.model_copy(update={field: "wrong"}), stack.component_roots
        )

    def forbidden(*_args: object, **_kwargs: object):
        pytest.fail("invalid SDXL input reached tensor backend")

    monkeypatch.setattr(numerical.DiffusersUnetLoraBackend, "train", forbidden)
    with pytest.raises(TrainingBackendFailure):
        SdxlMicroLoraBackend().train(
            stack=stack, samples=samples, command=command, output_root=tmp_path / "adapter"
        )


def test_legacy_ssd_wrapper_preserves_bundled_vae_recipe_and_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    micro, _, _ = _inputs(tmp_path)
    plan = SimpleNamespace(
        dependencies=micro.dependencies, hyperparameters=micro.hyperparameters, seed=17
    )
    legacy = SimpleNamespace(training_plan=plan)
    dataset = SimpleNamespace(
        samples=(
            SimpleNamespace(
                caption_en="legacy caption", crop_member=SimpleNamespace(member_path="crops/a.png")
            ),
        )
    )
    captured: dict[str, Any] = {}
    expected = TrainingBackendResult(_runtime(), 200, 0.1)

    def train(_self: object, **kwargs: Any):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(numerical.DiffusersUnetLoraBackend, "train", train)
    assert (
        numerical.Ssd1bLoraBackend().train(
            model_directory=tmp_path / "ssd",
            dataset=dataset,
            dataset_root=tmp_path / "dataset",
            command=legacy,
            output_root=tmp_path / "out",
            checkpoint_root=tmp_path / "checkpoints",
        )
        == expected
    )
    assert captured["vae_source"] == numerical.VaeWeightLocation(tmp_path / "ssd", "vae", "fp16")
    assert captured["samples"] == (
        numerical.LoraTensorSample("legacy caption", tmp_path / "dataset/crops/a.png"),
    )
    assert captured["recipe"] == numerical.LoraTrainingRecipe(
        plan.dependencies, plan.hyperparameters, 17
    )
    policy = captured["checkpoint_policy"]
    assert policy.command is legacy and policy.root == tmp_path / "checkpoints"
    assert "budget" not in captured


def test_legacy_checkpoint_keeps_exact_identity_progress_and_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    command = SimpleNamespace()
    policy = numerical._SsdCheckpointPolicy(command, tmp_path)
    saved = {}
    model, optimizer, torch = object(), object(), object()

    def load(**kwargs: object):
        assert kwargs == {
            "root": tmp_path,
            "command": command,
            "model": model,
            "optimizer": optimizer,
            "torch": torch,
        }
        return SimpleNamespace(completed_steps=200, micro_steps=800)

    monkeypatch.setattr(numerical, "load_latest_checkpoint", load)
    monkeypatch.setattr(numerical, "save_checkpoint", lambda **kwargs: saved.update(kwargs))
    assert policy.load(
        model=model, optimizer=optimizer, torch=torch
    ) == numerical.LoraCheckpointProgress(200, 800)
    policy.save(model=model, optimizer=optimizer, torch=torch, completed_steps=200, micro_steps=800)
    assert saved == {
        "root": tmp_path,
        "command": command,
        "model": model,
        "optimizer": optimizer,
        "torch": torch,
        "completed_steps": 200,
        "micro_steps": 800,
    }


@pytest.mark.parametrize(
    "duration,memory,failure", [(2000, 10, False), (1999, 10, True), (2000, 9, True)]
)
def test_budget_checks_exact_limits_before_more_tensor_work(
    monkeypatch: pytest.MonkeyPatch, duration: int, memory: int, failure: bool
) -> None:
    monkeypatch.setattr(numerical.time, "monotonic", lambda: 2.0)
    torch = SimpleNamespace(cuda=SimpleNamespace(max_memory_allocated=lambda _device: 10))
    if failure:
        with pytest.raises(TrainingBackendFailure, match="RESOURCE_BUDGET_EXCEEDED"):
            numerical._require_training_budget(
                budget=numerical.LoraTrainingBudget(duration, memory), started=0.0, torch=torch
            )
    else:
        numerical._require_training_budget(
            budget=numerical.LoraTrainingBudget(duration, memory), started=0.0, torch=torch
        )
    numerical._require_training_budget(budget=None, started=0.0, torch=torch)


@pytest.mark.parametrize("fixed", [True, False])
def test_vae_load_keeps_fixed_and_bundled_locations_distinct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixed: bool
) -> None:
    seen = {}

    def load(root: Path, **kwargs: object):
        seen.update({"root": root, **kwargs})
        raise RuntimeError("stopped before CUDA")

    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(AutoencoderKL=SimpleNamespace(from_pretrained=load)),
    )
    source = numerical.VaeWeightLocation(
        tmp_path, None if fixed else "vae", None if fixed else "fp16"
    )
    with pytest.raises(RuntimeError, match="stopped before CUDA"):
        numerical._latents(
            vae_source=source, samples=(), seed=17, torch=SimpleNamespace(float16="fp16")
        )
    expected = {
        "root": tmp_path,
        "torch_dtype": "fp16",
        "local_files_only": True,
        "use_safetensors": True,
    }
    if not fixed:
        expected.update({"subfolder": "vae", "variant": "fp16"})
    assert seen == expected


def test_saved_peft_configuration_retains_released_canonical_bytes(tmp_path: Path) -> None:
    command, _, _ = _inputs(tmp_path)
    value = {
        "base_model_name_or_path": "PINNED_LOCAL_MODEL_REVISION",
        "bias": "none",
        "inference_mode": True,
        "lora_alpha": 8,
        "peft_type": "LORA",
        "r": 8,
        "target_modules": ["to_k", "to_out.0", "to_q", "to_v"],
        "task_type": None,
    }
    expected = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert numerical._canonical_config(command.hyperparameters) == expected


def test_native_wrapper_preserves_three_canvases_exact_captions_and_terminal_only_recipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    command = LocalImageSdxlNativeLoraCommand.model_validate(_native_command_value())
    _, stack, _ = _inputs(tmp_path)
    samples = tuple(
        numerical.LoraTensorSample(
            source.training_caption_en,
            tmp_path / source.staged_member_path,
            *source.width_height,
        )
        for source in command.training_samples
    )
    captured = {}
    expected = TrainingBackendResult(_runtime(), 20, 0.1)

    def train(_self: object, **kwargs: Any):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(numerical.DiffusersUnetLoraBackend, "train", train)
    assert (
        SdxlNativeLoraBackend().train(
            stack=stack, samples=samples, command=command, output_root=tmp_path / "adapter"
        )
        == expected
    )
    assert captured["checkpoint_policy"] is None
    assert captured["recipe"] == numerical.LoraTrainingRecipe(
        command.dependencies, command.hyperparameters, command.seed
    )
    assert captured["samples"] == samples
    assert captured["vae_source"] == numerical.VaeWeightLocation(
        stack.component_roots["VAE"], None, None
    )
    assert numerical._canonical_config(command.hyperparameters) == numerical._canonical_config(
        _inputs(tmp_path)[0].hyperparameters
    )


@pytest.mark.parametrize(
    "fault", ["count", "caption", "geometry", "order", "model", "revision", "hash"]
)
def test_native_wrapper_rejects_mismatched_cohort_before_tensor_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fault: str
) -> None:
    command = LocalImageSdxlNativeLoraCommand.model_validate(_native_command_value())
    _, stack, _ = _inputs(tmp_path)
    samples = tuple(
        numerical.LoraTensorSample(
            s.training_caption_en, tmp_path / s.staged_member_path, *s.width_height
        )
        for s in command.training_samples
    )
    if fault == "count":
        samples = samples[:-1]
    elif fault in {"caption", "geometry"}:
        sample = samples[0]
        samples = (
            numerical.LoraTensorSample(
                "different caption" if fault == "caption" else sample.caption_en,
                sample.image_path,
                *((768, 512) if fault == "geometry" else (sample.width_px, sample.height_px)),
            ),
            *samples[1:],
        )
    elif fault == "order":
        samples = tuple(reversed(samples))
    else:
        field = {"model": "model_id", "revision": "model_revision_id", "hash": "manifest_sha256"}[
            fault
        ]
        stack = ResolvedSdxlStack(
            stack.manifest.model_copy(update={field: "wrong"}), stack.component_roots
        )
    monkeypatch.setattr(
        numerical.DiffusersUnetLoraBackend,
        "train",
        lambda *_a, **_k: pytest.fail("invalid native input reached numerical backend"),
    )
    with pytest.raises(TrainingBackendFailure):
        SdxlNativeLoraBackend().train(
            stack=stack, samples=samples, command=command, output_root=tmp_path / "adapter"
        )


@pytest.mark.parametrize("width,height", [(768, 512), *NATIVE_TARGET_CANVASES.values()])
def test_exact_canvas_time_ids_and_tensor_reshape_without_resize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, width: int, height: int
) -> None:
    path = tmp_path / "exact.png"
    Image.new("RGB", (width, height), "white").save(path)
    seen = {}

    class Tensor:
        def reshape(self, *shape):
            seen["reshape"] = shape
            return self

        def permute(self, *shape):
            seen["permute"] = shape
            return self

        def unsqueeze(self, _dim):
            return self

        def to(self, *_args, **_kwargs):
            return self

        def div(self, _scale):
            return self

        def sub(self, _bias):
            return self

        def mul(self, _scale):
            return self

    tensor = Tensor()

    class Vae:
        config = SimpleNamespace(scaling_factor=0.13025)

        def requires_grad_(self, _enabled):
            return None

        def eval(self):
            return None

        def to(self, *_args):
            return None

        def encode(self, image):
            assert image is tensor
            return SimpleNamespace(latent_dist=SimpleNamespace(sample=lambda **_kw: tensor))

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def frombuffer(payload, **_kwargs):
        seen["bytes"] = len(payload)
        return tensor

    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(AutoencoderKL=SimpleNamespace(from_pretrained=lambda *_a, **_kw: Vae())),
    )
    torch = SimpleNamespace(
        float16="fp16",
        uint8="uint8",
        no_grad=Context,
        frombuffer=frombuffer,
        Generator=lambda **_kwargs: SimpleNamespace(manual_seed=lambda _seed: object()),
        isfinite=lambda _t: SimpleNamespace(all=lambda: SimpleNamespace(item=lambda: True)),
        cuda=SimpleNamespace(empty_cache=lambda: None),
    )
    sample = numerical.LoraTensorSample("exact source", path, width, height)
    assert sample.sdxl_time_ids == (height, width, 0, 0, height, width)
    assert numerical._latents(
        vae_source=numerical.VaeWeightLocation(tmp_path, None, None),
        samples=(sample,),
        seed=17,
        torch=torch,
    ) == (tensor,)
    assert seen == {
        "reshape": (height, width, 3),
        "permute": (2, 0, 1),
        "bytes": width * height * 3,
    }


@pytest.mark.parametrize(
    "size,mode", [((768, 512), "RGB"), ((1024, 1024), "L"), ((1024, 1024), "RGBA")]
)
def test_native_vae_rejects_wrong_png_geometry_or_silent_color_conversion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, size: tuple[int, int], mode: str
) -> None:
    path = tmp_path / "wrong.png"
    Image.new(mode, size).save(path)
    vae = SimpleNamespace(
        requires_grad_=lambda _v: None,
        eval=lambda: None,
        to=lambda *_args: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "diffusers",
        SimpleNamespace(AutoencoderKL=SimpleNamespace(from_pretrained=lambda *_a, **_kw: vae)),
    )

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    torch = SimpleNamespace(
        float16="fp16",
        no_grad=Context,
        Generator=lambda **_kwargs: SimpleNamespace(manual_seed=lambda _seed: object()),
        cuda=SimpleNamespace(empty_cache=lambda: None),
        frombuffer=lambda *_a, **_kw: pytest.fail("invalid PNG reached tensor conversion"),
    )
    with pytest.raises(TrainingBackendFailure, match="SAMPLE_INVALID"):
        numerical._latents(
            vae_source=numerical.VaeWeightLocation(tmp_path, None, None),
            samples=(numerical.LoraTensorSample("native source", path, 1024, 1024),),
            seed=17,
            torch=torch,
        )


def test_native_recipe_cannot_attach_an_old_checkpoint_policy_before_imports(
    tmp_path: Path,
) -> None:
    command = LocalImageSdxlNativeLoraCommand.model_validate(_native_command_value())
    with pytest.raises(TrainingBackendFailure, match="CHECKPOINT_POLICY_INVALID"):
        numerical.DiffusersUnetLoraBackend().train(
            model_directory=tmp_path,
            vae_source=numerical.VaeWeightLocation(tmp_path, None, None),
            samples=(),
            recipe=numerical.LoraTrainingRecipe(command.dependencies, command.hyperparameters, 17),
            output_root=tmp_path / "adapter",
            checkpoint_policy=SimpleNamespace(),
        )


@pytest.mark.parametrize("width,height", [(768, 768), (0, 1024), (2048, 1024), (1024, 512)])
def test_unadmitted_tensor_geometry_is_not_a_generic_resize_api(
    tmp_path: Path, width: int, height: int
) -> None:
    with pytest.raises(TrainingBackendFailure, match="SAMPLE_INVALID"):
        numerical.LoraTensorSample("source", tmp_path / "source.png", width, height)


def test_old_micro_wrapper_does_not_accept_native_canvas_as_a_protocol_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    command, stack, samples = _inputs(tmp_path)
    samples = tuple(
        numerical.LoraTensorSample(s.caption_en, s.image_path, 1024, 1024) for s in samples
    )
    monkeypatch.setattr(
        numerical.DiffusersUnetLoraBackend, "train", lambda *_a, **_kw: pytest.fail("native alias")
    )
    with pytest.raises(TrainingBackendFailure, match="SAMPLE_INVALID"):
        SdxlMicroLoraBackend().train(
            stack=stack, samples=samples, command=command, output_root=tmp_path / "out"
        )
