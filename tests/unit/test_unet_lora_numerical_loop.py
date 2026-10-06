"""CPU fakes verify orchestration/accounting; not a claim of CUDA numerical acceptance."""

from __future__ import annotations

import math
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import LocalImageSdxlLoraMicroCommand
from eom_image_trainer import diffusers_backend as numerical
from eom_image_trainer.runner import TrainingBackendFailure

from tests.unit.test_local_image_training_runner import _runtime
from tests.unit.test_sdxl_lora_micro_contracts import _command_value


class Tensor:
    def __init__(self, value=0.1):
        self.value = value
        self.shape = (1, 4, 64, 96)
        self.requires_grad = False
        self.data = self
        self.transfers = []

    def to(self, *args, **kwargs):
        self.transfers.append((args, kwargs))
        return self

    def float(self):
        return self

    def detach(self):
        return self

    def item(self):
        return self.value

    def all(self):
        return self


@pytest.fixture
def numerical_runtime(monkeypatch: pytest.MonkeyPatch):
    command = LocalImageSdxlLoraMicroCommand.model_validate(_command_value()[0])
    state = SimpleNamespace(
        loss=0.1,
        gradient=0.2,
        saved=[],
        backward=0,
        clipped=0,
        optimizer_steps=0,
        clears=0,
        devices=[],
        seeds=[],
        sample_orders=[],
        sampled_indices=[],
        base=Tensor(),
        lora=Tensor(),
        accumulator=None,
    )

    class Unet:
        def requires_grad_(self, value):
            state.base.requires_grad = state.lora.requires_grad = value

        def add_adapter(self, configuration):
            assert configuration["r"] == configuration["lora_alpha"] == 8
            assert configuration["target_modules"] == list(numerical.TARGET_MODULES)
            state.lora.requires_grad = True

        def enable_gradient_checkpointing(self):
            state.checkpointing_enabled = True

        def parameters(self):
            return (state.base, state.lora)

        def train(self):
            state.training = True

        def __call__(self, *args, **kwargs):
            assert set(kwargs["added_cond_kwargs"]) == {"text_embeds", "time_ids"}
            return SimpleNamespace(sample=Tensor())

    class Optimizer:
        def __init__(self, trainable, *, lr):
            assert trainable == (state.lora,) and lr == 1e-4

        def step(self):
            if state.accumulator.sync_gradients:
                state.optimizer_steps += 1

        def zero_grad(self, *, set_to_none):
            assert set_to_none is True
            if state.accumulator.sync_gradients:
                state.clears += 1

    class Accelerator:
        device = "cuda"
        num_processes = 1

        def __init__(self, *, gradient_accumulation_steps, mixed_precision):
            assert gradient_accumulation_steps == 4 and mixed_precision == "fp16"
            self.micro_steps = 0
            self.sync_gradients = False
            state.accumulator = self

        def prepare(self, model, optimizer):
            return model, optimizer

        @contextmanager
        def accumulate(self, _model):
            self.micro_steps += 1
            self.sync_gradients = self.micro_steps % 4 == 0
            yield

        def backward(self, loss):
            assert loss.item() == state.loss
            state.backward += 1

        def clip_grad_norm_(self, trainable, maximum):
            assert trainable == (state.lora,) and maximum == 1.0
            state.clipped += 1
            return Tensor(state.gradient)

        def unwrap_model(self, model):
            return model

        def wait_for_everyone(self):
            pass

        @property
        def is_main_process(self):
            return True

    scheduler = SimpleNamespace(
        config=SimpleNamespace(num_train_timesteps=1000, prediction_type="epsilon"),
        add_noise=lambda *_args: Tensor(),
    )
    cuda = SimpleNamespace(
        is_available=lambda: True,
        get_device_capability=lambda _index: (12, 0),
        manual_seed_all=state.seeds.append,
        reset_peak_memory_stats=lambda _index: None,
        max_memory_allocated=lambda _index: 10,
        empty_cache=lambda: None,
    )
    functional = SimpleNamespace(mse_loss=lambda *_args: Tensor(state.loss))
    torch = SimpleNamespace(
        cuda=cuda,
        nn=SimpleNamespace(functional=functional),
        float16="fp16",
        float32="fp32",
        long="long",
        manual_seed=state.seeds.append,
        use_deterministic_algorithms=lambda value: None,
        backends=SimpleNamespace(
            cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
            cudnn=SimpleNamespace(allow_tf32=True),
        ),
        tensor=lambda *_args, **_kwargs: Tensor(),
        randn_like=lambda tensor: (state.sampled_indices.append(tensor.value), Tensor())[1],
        randint=lambda *_args, **_kwargs: Tensor(),
        isfinite=lambda tensor: Tensor(math.isfinite(tensor.item())),
    )
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", numerical.DETERMINISTIC_CUBLAS_WORKSPACE_CONFIG)
    for name, module in {
        "torch": torch,
        "torch.nn": torch.nn,
        "torch.nn.functional": functional,
        "bitsandbytes": SimpleNamespace(optim=SimpleNamespace(AdamW8bit=Optimizer)),
        "accelerate": SimpleNamespace(Accelerator=Accelerator),
        "diffusers": SimpleNamespace(
            DDPMScheduler=SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: scheduler),
            UNet2DConditionModel=SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: Unet()),
        ),
        "peft": SimpleNamespace(LoraConfig=lambda **kwargs: kwargs),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(
        numerical, "_versions", lambda: command.dependencies.model_dump(mode="json")
    )
    monkeypatch.setattr(numerical, "_runtime_snapshot", lambda **_kwargs: _runtime())
    monkeypatch.setattr(
        numerical,
        "_prompt_embeddings",
        lambda **kwargs: tuple((Tensor(), Tensor()) for _ in kwargs["captions"]),
    )
    monkeypatch.setattr(
        numerical,
        "_latents",
        lambda **kwargs: tuple(Tensor(i) for i, _ in enumerate(kwargs["samples"])),
    )
    monkeypatch.setattr(
        numerical, "_save_final_adapter", lambda **kwargs: state.saved.append(kwargs)
    )
    sample_order = numerical._sample_order

    def ordered(**kwargs):
        order = sample_order(**kwargs)
        state.sample_orders.append((kwargs["epoch"], order))
        return order

    monkeypatch.setattr(numerical, "_sample_order", ordered)
    return command, state


def _train(tmp_path: Path, command, *, checkpoint_policy=None, budget=None, sample_schedule=None):
    return numerical.DiffusersUnetLoraBackend().train(
        model_directory=tmp_path / "base",
        vae_source=numerical.VaeWeightLocation(tmp_path / "fixed-vae", None, None),
        samples=tuple(
            numerical.LoraTensorSample(
                source.training_caption_en,
                tmp_path / (source.sample_id + ".png"),
                *getattr(source, "width_height", (768, 512)),
            )
            for source in command.training_samples
        ),
        recipe=numerical.LoraTrainingRecipe(
            command.dependencies, command.hyperparameters, command.seed, sample_schedule
        ),
        output_root=tmp_path / "adapter",
        checkpoint_policy=checkpoint_policy,
        budget=budget,
    )


def test_one_shared_loop_keeps_base_frozen_and_counts_200_real_updates(
    numerical_runtime, tmp_path: Path
):
    command, state = numerical_runtime
    result = _train(tmp_path, command)
    assert result.completed_steps == 200 and result.final_loss == 0.1
    assert state.backward == 800 and state.optimizer_steps == state.clipped == state.clears == 200
    assert state.base.requires_grad is False and state.lora.requires_grad is True
    assert state.base.transfers == [] and state.lora.transfers == [(("fp32",), {})]
    assert state.seeds == [command.seed, command.seed]
    assert len(state.saved) == 1 and state.saved[0]["hyperparameters"] == command.hyperparameters
    assert [epoch for epoch, _ in state.sample_orders] == list(range(50))
    assert all(set(order) == set(range(16)) for _, order in state.sample_orders)
    assert state.sampled_indices == [i for _, order in state.sample_orders for i in order]


def test_real_shared_loop_consumes_all_3200_balanced_indices_without_uniform_fallback(
    numerical_runtime, tmp_path: Path
):
    from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommandV3
    from eom_image_trainer.style_exposure import native_style_exposure_schedule

    from tests.unit.test_native_style_exposure import _actual_distribution_value

    _old_command, state = numerical_runtime
    command = LocalImageSdxlNativeLoraCommandV3.model_validate(_actual_distribution_value())
    schedule = native_style_exposure_schedule(command)
    result = _train(tmp_path, command, sample_schedule=schedule)
    assert result.completed_steps == state.optimizer_steps == state.clipped == state.clears == 800
    assert state.backward == 3200 and tuple(state.sampled_indices) == schedule
    assert state.sample_orders == [] and len(state.saved) == 1


@pytest.mark.parametrize(
    "fault", ["short", "long", "range", "bool", "float", "mutable", "coverage", "checkpoint"]
)
def test_invalid_schedule_fails_before_dependency_or_tensor_work(
    numerical_runtime, tmp_path, fault
):
    command, state = numerical_runtime
    schedule = tuple(range(16)) * 50
    checkpoint = None
    if fault == "short":
        schedule = schedule[:-1]
    elif fault == "long":
        schedule = (*schedule, 0)
    elif fault == "range":
        schedule = (*schedule[:-1], 16)
    elif fault == "bool":
        schedule = (*schedule[:-1], True)
    elif fault == "float":
        schedule = (*schedule[:-1], 1.0)
    elif fault == "mutable":
        schedule = list(schedule)
    elif fault == "coverage":
        schedule = (0,) * len(schedule)
    else:
        checkpoint = SimpleNamespace()
    with pytest.raises(
        TrainingBackendFailure, match=r"SAMPLE_SCHEDULE_INVALID|CHECKPOINT_POLICY_INVALID"
    ):
        _train(tmp_path, command, sample_schedule=schedule, checkpoint_policy=checkpoint)
    assert not state.seeds and not state.saved and not state.sampled_indices


@pytest.mark.parametrize("actual_accumulation", [2, 8])
def test_accumulation_drift_cannot_save_a_partially_or_excessively_consumed_schedule(
    numerical_runtime, tmp_path, monkeypatch, actual_accumulation
):
    command, state = numerical_runtime
    original = sys.modules["accelerate"].Accelerator

    class DriftedAccelerator(original):
        @contextmanager
        def accumulate(self, _model):
            self.micro_steps += 1
            self.sync_gradients = self.micro_steps % actual_accumulation == 0
            yield

    monkeypatch.setattr(sys.modules["accelerate"], "Accelerator", DriftedAccelerator)
    with pytest.raises(TrainingBackendFailure, match="SAMPLE_SCHEDULE_INVALID"):
        _train(tmp_path, command, sample_schedule=tuple(range(16)) * 50)
    assert not state.saved


@pytest.mark.parametrize(
    "fault,code",
    [
        ("loss", "LOSS_NONFINITE"),
        ("gradient", "GRADIENT_NONFINITE"),
        ("budget", "RESOURCE_BUDGET_EXCEEDED"),
    ],
)
def test_numerical_failure_never_saves_an_adapter(
    numerical_runtime, tmp_path: Path, fault: str, code: str
):
    command, state = numerical_runtime
    budget = None
    if fault == "budget":
        budget = numerical.LoraTrainingBudget(30000, 9)
    else:
        setattr(state, fault, float("nan"))
    with pytest.raises(TrainingBackendFailure, match=code):
        _train(tmp_path, command, budget=budget)
    assert not state.saved and state.optimizer_steps == 0


def test_existing_checkpoint_progress_is_resumed_not_reinitialized(
    numerical_runtime, tmp_path: Path
):
    command, state = numerical_runtime

    class ExistingCheckpoint:
        def load(self, **kwargs):
            return numerical.LoraCheckpointProgress(100, 400)

        def save(self, **kwargs):
            pytest.fail("micro maximum checkpoint must not save before the final artifact")

    result = _train(tmp_path, command, checkpoint_policy=ExistingCheckpoint())
    assert result.completed_steps == 200 and state.optimizer_steps == 100 and state.backward == 400
    assert [epoch for epoch, _ in state.sample_orders] == list(range(25, 50))


@pytest.mark.parametrize("finite", [True, False])
def test_final_peft_weights_checked_before_safetensors_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, finite: bool
):
    command = LocalImageSdxlLoraMicroCommand.model_validate(_command_value()[0])
    saved = []

    class Weight(Tensor):
        def contiguous(self):
            return self

        def isfinite(self):
            return Tensor(finite)

    def save_file(value, path):
        saved.append(value)
        path.write_bytes(b"synthetic output; not a CUDA/safetensors acceptance")

    monkeypatch.setitem(
        sys.modules,
        "peft.utils",
        SimpleNamespace(
            get_peft_model_state_dict=lambda *_args, **_kwargs: {"lora.test": Weight()}
        ),
    )
    monkeypatch.setitem(sys.modules, "safetensors.torch", SimpleNamespace(save_file=save_file))
    output = tmp_path / "adapter"
    if finite:
        numerical._save_final_adapter(
            model=object(), hyperparameters=command.hyperparameters, output_root=output
        )
        assert len(saved) == 1
        assert {path.name for path in output.iterdir()} == {
            "adapter_config.json",
            "adapter_model.safetensors",
        }
        assert (output / "adapter_config.json").read_bytes() == numerical._canonical_config(
            command.hyperparameters
        )
    else:
        with pytest.raises(TrainingBackendFailure, match="ADAPTER_NONFINITE"):
            numerical._save_final_adapter(
                model=object(), hyperparameters=command.hyperparameters, output_root=output
            )
        assert not saved and not output.exists()
        assert len(tuple(tmp_path.glob(".adapter-tmp-*"))) == 1
