from __future__ import annotations

import io
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceCampaignLoraMicroEvaluationCommand,
    LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
)
from eom_image_trainer import (
    micro_evaluation_runner,
    science_campaign_micro_evaluation_runner,
)
from PIL import Image

from tests.unit.test_science_campaign_expanded_training_contracts import (
    _expanded_evaluation_command_value,
)
from tests.unit.test_science_campaign_micro_training_contracts import (
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
    def generate_campaign_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageScienceCampaignLoraMicroEvaluationCommand,
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


def _workspace(
    monkeypatch,
    tmp_path: Path,
) -> tuple[LocalImageScienceCampaignLoraMicroEvaluationCommand, Path, Path]:
    command = LocalImageScienceCampaignLoraMicroEvaluationCommand.model_validate(
        _evaluation_command_value()
    )
    workspace = tmp_path / command.evaluation_run_id
    workspace.mkdir(mode=0o700)
    (workspace / command.staged_adapter_root).mkdir(parents=True)
    model_directory = tmp_path / "model"
    model_directory.mkdir()
    expected = tuple(value.model_dump(mode="json") for value in command.adapter_manifest.files)
    monkeypatch.setattr(
        science_campaign_micro_evaluation_runner,
        "validate_adapter_files",
        lambda _root: expected,
    )
    return command, workspace, model_directory


def test_campaign_evaluation_writes_exact_holdout_pairs(monkeypatch, tmp_path: Path) -> None:
    command, workspace, model_directory = _workspace(monkeypatch, tmp_path)

    result = science_campaign_micro_evaluation_runner.run_science_campaign_micro_evaluation_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.status == "SUCCEEDED"
    assert result.error_code is None
    assert len(result.outputs) == 4
    assert {value.sample_id for value in result.outputs} == {
        value.sample_id for value in command.cases
    }
    assert all((workspace / value.member_path).is_file() for value in result.outputs)


def test_campaign_evaluation_rejects_adapter_hash_drift(monkeypatch, tmp_path: Path) -> None:
    command, workspace, _model_directory = _workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        science_campaign_micro_evaluation_runner,
        "validate_adapter_files",
        lambda _root: (),
    )

    result = science_campaign_micro_evaluation_runner.run_science_campaign_micro_evaluation_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), tmp_path),
    )

    assert result.status == "FAILED"
    assert result.error_code == "IMAGE_EVALUATION_ADAPTER_HASH_MISMATCH"
    assert result.outputs == ()


def test_expanded_campaign_evaluation_dispatches_v2_and_writes_four_pairs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    command = LocalImageScienceCampaignLoraMicroEvaluationCommandV2.model_validate(
        _expanded_evaluation_command_value()
    )
    workspace = tmp_path / command.evaluation_run_id
    workspace.mkdir(mode=0o700)
    (workspace / command.staged_adapter_root).mkdir(parents=True)
    model_directory = tmp_path / "model"
    model_directory.mkdir()
    expected = tuple(value.model_dump(mode="json") for value in command.adapter_manifest.files)
    monkeypatch.setattr(
        science_campaign_micro_evaluation_runner,
        "validate_adapter_files",
        lambda _root: expected,
    )

    result = science_campaign_micro_evaluation_runner.run_science_campaign_micro_evaluation_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),  # type: ignore[arg-type]
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.schema_version.endswith("/1.1")
    assert result.status == "SUCCEEDED"
    assert result.error_code is None
    assert len(result.outputs) == 8
    assert {value.sample_id for value in result.outputs} == {
        value.sample_id for value in command.cases
    }
    assert all((workspace / value.member_path).is_file() for value in result.outputs)
