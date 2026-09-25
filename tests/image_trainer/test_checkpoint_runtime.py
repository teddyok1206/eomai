from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest
import torch
from bitsandbytes.optim import AdamW8bit
from eom_image_contracts import LocalImageLoraTrainingCommand
from eom_image_trainer.checkpoints import load_latest_checkpoint, save_checkpoint
from peft import LoraConfig, get_peft_model
from torch import nn

from tests.unit.test_local_image_lora_training_contracts import _command_value

pytestmark = pytest.mark.image_trainer_runtime


class _TinyProjection(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.projection = nn.Linear(8, 8, bias=False)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.projection(values)


def _model() -> nn.Module:
    return get_peft_model(
        _TinyProjection(),
        LoraConfig(
            r=8,
            lora_alpha=8,
            target_modules=["projection"],
            init_lora_weights="gaussian",
        ),
    ).to("cuda")


def test_isolated_trainer_runtime_and_checkpoint_round_trip(tmp_path: Path) -> None:
    expected = {
        "accelerate": "1.10.1",
        "bitsandbytes": "0.47.0",
        "diffusers": "0.35.2",
        "peft": "0.17.1",
        "torch": "2.7.1+cu128",
        "transformers": "4.56.2",
    }
    assert {name: metadata.version(name) for name in expected} == expected
    assert torch.cuda.is_available()
    assert torch.cuda.get_device_capability(0) == (12, 0)
    torch.manual_seed(20260925)
    torch.cuda.manual_seed_all(20260925)
    model = _model()
    trainable = tuple(parameter for parameter in model.parameters() if parameter.requires_grad)
    optimizer = AdamW8bit(trainable, lr=0.0001)
    loss = model(torch.ones((1, 8), device="cuda")).float().square().mean()
    loss.backward()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    before = tuple(parameter.detach().clone() for parameter in trainable)

    root = tmp_path / "checkpoints"
    root.mkdir(mode=0o700)
    command = LocalImageLoraTrainingCommand.model_validate(_command_value())
    save_checkpoint(
        root=root,
        command=command,
        model=model,
        optimizer=optimizer,
        completed_steps=200,
        micro_steps=800,
        torch=torch,
    )
    for parameter in trainable:
        parameter.data.zero_()
    restored = load_latest_checkpoint(
        root=root,
        command=command,
        model=model,
        optimizer=optimizer,
        torch=torch,
    )
    assert restored is not None
    assert restored.completed_steps == 200
    assert restored.micro_steps == 800
    assert all(torch.equal(left, right) for left, right in zip(before, trainable, strict=True))
