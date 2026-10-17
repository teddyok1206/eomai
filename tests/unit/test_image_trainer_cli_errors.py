"""Presentation-only trainer failures: no device, model, dataset or worker launch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_image_trainer import cli
from eom_image_trainer.runner import TrainingRunnerError


def configure_train(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    args = SimpleNamespace(
        operation="train",
        command=Path("/synthetic/command.json"),
        workspace=Path("/synthetic/imgtrainrun_test"),
        gpu_lock=Path("/run/eom-gpu-lease/gpu0.lock"),
        model_store_root=Path("/synthetic/model"),
    )
    monkeypatch.setattr(cli, "_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(
        cli,
        "load_training_command",
        lambda path: SimpleNamespace(training_run_id=args.workspace.name),
    )
    calls: list[str] = []

    def unexpected_run(**kwargs: Any) -> None:
        pytest.fail("A pre-lease error reached model/data execution")

    monkeypatch.setattr(cli, "run_training_command", unexpected_run)
    return calls


@pytest.mark.parametrize("code", ("IMAGE_TRAINING_GPU_BUSY", "IMAGE_TRAINING_GPU_LOCK_INVALID"))
def test_actual_default_train_prelease_error_becomes_only_stable_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], code: str
) -> None:
    calls = configure_train(monkeypatch)

    def unavailable(path: Path) -> None:
        calls.append("claim")
        raise TrainingRunnerError(code)

    monkeypatch.setattr(cli, "_lock_gpu", unavailable)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == code
    assert calls == ["claim"]
    assert capsys.readouterr() == ("", "")


def test_untyped_failure_is_not_misrepresented_as_supported_busy_or_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_train(monkeypatch)

    def unknown(path: Path) -> None:
        raise RuntimeError("synthetic unknown failure")

    monkeypatch.setattr(cli, "_lock_gpu", unknown)
    with pytest.raises(RuntimeError, match="synthetic unknown"):
        cli.main()


def test_argparse_exit_is_preserved_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def parse() -> None:
        calls.append("parse")
        raise SystemExit(2)

    monkeypatch.setattr(cli, "_parser", lambda: SimpleNamespace(parse_args=parse))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2 and calls == ["parse"]
