from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import LocalImageLoraTrainingCommand
from eom_image_trainer.checkpoints import load_latest_checkpoint, save_checkpoint
from eom_image_trainer.runner import TrainingBackendFailure

from tests.unit.test_local_image_lora_training_contracts import _command_value


class _FakeTensor:
    shape = (1,)
    dtype = "float32"

    def detach(self) -> _FakeTensor:
        return self

    def to(self, _device: str) -> _FakeTensor:
        return self

    def contiguous(self) -> _FakeTensor:
        return self


class _FakeOptimizer:
    def __init__(self) -> None:
        self.loaded: object | None = None

    def state_dict(self) -> dict[str, object]:
        return {
            "state": {0: {"step": 1, "value": _FakeTensor()}},
            "param_groups": [{"params": [0], "lr": 0.0001}],
        }

    def load_state_dict(self, value: object) -> None:
        self.loaded = value


class _FakeCuda:
    def get_rng_state_all(self) -> list[_FakeTensor]:
        return [_FakeTensor()]

    def set_rng_state_all(self, value: list[object]) -> None:
        assert len(value) == 1


class _FakeTorch:
    def __init__(self) -> None:
        self.cuda = _FakeCuda()
        self.saved_state: object | None = None
        self.loaded_state: object | None = None

    def get_rng_state(self) -> _FakeTensor:
        return _FakeTensor()

    def set_rng_state(self, value: object) -> None:
        assert isinstance(value, _FakeTensor)

    def save(self, value: object, target: object) -> None:
        self.saved_state = value
        target.write(b"bounded-optimizer-state")

    def load(self, *_args: object, **_kwargs: object) -> object:
        assert self.loaded_state is not None
        return self.loaded_state


def _install_fake_serializers(monkeypatch: pytest.MonkeyPatch) -> None:
    peft = types.ModuleType("peft")
    peft.__path__ = []  # type: ignore[attr-defined]
    peft_utils = types.ModuleType("peft.utils")
    peft_utils.get_peft_model_state_dict = lambda *_args, **_kwargs: {  # type: ignore[attr-defined]
        "lora.weight": _FakeTensor()
    }
    peft_utils.set_peft_model_state_dict = (  # type: ignore[attr-defined]
        lambda *_args, **_kwargs: SimpleNamespace(unexpected_keys=())
    )
    safetensors = types.ModuleType("safetensors")
    safetensors.__path__ = []  # type: ignore[attr-defined]
    safetensors_torch = types.ModuleType("safetensors.torch")
    safetensors_torch.save = lambda _value: b"bounded-adapter-state"  # type: ignore[attr-defined]
    safetensors_torch.load = lambda _value: {  # type: ignore[attr-defined]
        "lora.weight": _FakeTensor()
    }
    monkeypatch.setitem(sys.modules, "peft", peft)
    monkeypatch.setitem(sys.modules, "peft.utils", peft_utils)
    monkeypatch.setitem(sys.modules, "safetensors", safetensors)
    monkeypatch.setitem(sys.modules, "safetensors.torch", safetensors_torch)


def _command() -> LocalImageLoraTrainingCommand:
    return LocalImageLoraTrainingCommand.model_validate(_command_value())


def test_checkpoint_round_trip_binds_exact_command_and_optimizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_serializers(monkeypatch)
    root = tmp_path / "checkpoints"
    root.mkdir(mode=0o700)
    torch = _FakeTorch()
    optimizer = _FakeOptimizer()
    manifest = save_checkpoint(
        root=root,
        command=_command(),
        model=object(),
        optimizer=optimizer,
        completed_steps=200,
        micro_steps=800,
        torch=torch,
    )
    assert manifest.completed_steps == 200
    assert (root / "checkpoint-00000200/checkpoint-manifest.json").is_file()
    torch.loaded_state = torch.saved_state
    restored = load_latest_checkpoint(
        root=root,
        command=_command(),
        model=object(),
        optimizer=optimizer,
        torch=torch,
    )
    assert restored is not None
    assert restored.completed_steps == 200
    assert restored.micro_steps == 800
    assert optimizer.loaded is not None


def test_checkpoint_hash_tamper_fails_before_deserialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_serializers(monkeypatch)
    root = tmp_path / "checkpoints"
    root.mkdir(mode=0o700)
    torch = _FakeTorch()
    save_checkpoint(
        root=root,
        command=_command(),
        model=object(),
        optimizer=_FakeOptimizer(),
        completed_steps=200,
        micro_steps=800,
        torch=torch,
    )
    state_path = root / "checkpoint-00000200/optimizer-rng-state.pt"
    state_path.write_bytes(state_path.read_bytes() + b"tamper")
    state_path.chmod(0o600)
    with pytest.raises(TrainingBackendFailure, match="IMAGE_TRAINING_CHECKPOINT_HASH_MISMATCH"):
        load_latest_checkpoint(
            root=root,
            command=_command(),
            model=object(),
            optimizer=_FakeOptimizer(),
            torch=torch,
        )
