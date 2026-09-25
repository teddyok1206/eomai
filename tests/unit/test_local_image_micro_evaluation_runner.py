from __future__ import annotations

import io
from pathlib import Path

from eom_image_contracts import LocalImageLoraMicroEvaluationCommand
from eom_image_trainer import micro_evaluation_runner
from PIL import Image

from tests.unit.test_local_image_lora_micro_probe_contracts import (
    _evaluation_command_value,
)


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (800, 500), color).save(
        output,
        format="PNG",
        optimize=False,
        compress_level=9,
    )
    return output.getvalue()


class _Backend:
    def generate_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageLoraMicroEvaluationCommand,
    ) -> tuple[micro_evaluation_runner.GeneratedEvaluationImage, ...]:
        assert model_directory.is_dir()
        assert adapter_root.is_dir()
        return tuple(
            micro_evaluation_runner.GeneratedEvaluationImage(
                sample_id=case.sample_id,
                variant=variant,
                png_bytes=_png((index, index, index)),
            )
            for index, (case, variant) in enumerate(
                (case, variant) for case in command.cases for variant in ("ADAPTER", "BASE")
            )
        )


def test_micro_evaluation_runner_writes_exact_paired_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    command = LocalImageLoraMicroEvaluationCommand.model_validate(_evaluation_command_value())
    workspace = tmp_path / command.evaluation_run_id
    workspace.mkdir(mode=0o700)
    adapter_root = workspace / command.staged_adapter_root
    adapter_root.mkdir(parents=True)
    model_directory = tmp_path / "model"
    model_directory.mkdir()
    expected_files = tuple(
        value.model_dump(mode="json") for value in command.adapter_manifest.files
    )
    monkeypatch.setattr(
        micro_evaluation_runner,
        "validate_adapter_files",
        lambda _root: expected_files,
    )

    result = micro_evaluation_runner.run_micro_evaluation_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.status == "SUCCEEDED"
    assert result.error_code is None
    assert len(result.outputs) == 6
    assert (workspace / "result.json").is_file()
    assert all((workspace / value.member_path).is_file() for value in result.outputs)


def test_micro_evaluation_runner_rejects_adapter_hash_drift(
    monkeypatch,
    tmp_path: Path,
) -> None:
    command = LocalImageLoraMicroEvaluationCommand.model_validate(_evaluation_command_value())
    workspace = tmp_path / command.evaluation_run_id
    workspace.mkdir(mode=0o700)
    (workspace / command.staged_adapter_root).mkdir(parents=True)
    monkeypatch.setattr(
        micro_evaluation_runner,
        "validate_adapter_files",
        lambda _root: (),
    )

    result = micro_evaluation_runner.run_micro_evaluation_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), tmp_path),
    )

    assert result.status == "FAILED"
    assert result.error_code == "IMAGE_EVALUATION_ADAPTER_HASH_MISMATCH"
    assert result.outputs == ()
