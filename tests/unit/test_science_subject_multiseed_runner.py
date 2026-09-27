from __future__ import annotations

import io
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceVisualSubjectMultiseedCommand,
    LocalImageScienceVisualSubjectMultiseedPlan,
    content_json_bytes,
)
from eom_image_trainer import science_subject_multiseed_runner
from eom_image_trainer.micro_evaluation_runner import GeneratedEvaluationImage
from PIL import Image

from tests.unit.test_science_visual_subject_benchmark_contracts import (
    _adapter_manifest,
    _multiseed_command,
    _multiseed_initials,
    _multiseed_plan,
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
    def generate_subject_multiseed_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageScienceVisualSubjectMultiseedCommand,
        plan: LocalImageScienceVisualSubjectMultiseedPlan,
    ) -> tuple[GeneratedEvaluationImage, ...]:
        assert model_directory.is_dir()
        assert adapter_root.is_dir()
        assert command.plan_sha256 == plan.plan_sha256
        return tuple(
            GeneratedEvaluationImage(
                sample_id=case.case_id,
                variant=variant,
                png_bytes=_png((index, index, index)),
            )
            for index, (case, variant) in enumerate(
                (case, variant) for case in plan.cases for variant in ("ADAPTER", "BASE")
            )
        )


def _workspace(tmp_path: Path):
    inventory, initial_plan, initial_review = _multiseed_initials()
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    command = _multiseed_command(plan)
    adapter = _adapter_manifest()
    workspace = tmp_path / command.run_id
    adapter_root = workspace / "inputs" / "adapter"
    adapter_root.mkdir(parents=True)
    files = {
        workspace / "inputs" / "subject-multiseed-plan.json": content_json_bytes(
            plan.model_dump(mode="json")
        ),
        workspace / "inputs" / "science-visual-subject-inventory.json": content_json_bytes(
            inventory.model_dump(mode="json")
        ),
        workspace / "inputs" / "science-visual-subject-benchmark-plan.json": (
            content_json_bytes(initial_plan.model_dump(mode="json"))
        ),
        workspace / "inputs" / "science-visual-subject-benchmark-review.json": (
            content_json_bytes(initial_review.model_dump(mode="json"))
        ),
        adapter_root / "adapter-manifest.json": content_json_bytes(adapter.model_dump(mode="json")),
        adapter_root / "adapter_config.json": b"config",
        adapter_root / "adapter_model.safetensors": b"weights",
        workspace / "command.json": content_json_bytes(command.model_dump(mode="json")),
    }
    for path, payload in files.items():
        path.write_bytes(payload)
        path.chmod(0o440)
    workspace.chmod(0o700)
    return workspace, command, plan, adapter


def test_science_subject_multiseed_runner_closes_exact_pairs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace, command, plan, adapter = _workspace(tmp_path)
    model_directory = tmp_path / "model"
    model_directory.mkdir()
    monkeypatch.setattr(
        science_subject_multiseed_runner,
        "validate_adapter_files",
        lambda _root: tuple(value.model_dump(mode="json") for value in adapter.files),
    )

    result = science_subject_multiseed_runner.run_science_subject_multiseed_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.status == "SUCCEEDED"
    assert result.error_code is None
    assert len(result.outputs) == len(plan.cases) * 2
    assert all((workspace / output.relative_path).is_file() for output in result.outputs)
    assert (workspace / "result.json").is_file()
    assert not tuple(workspace.glob(".outputs-*"))


def test_science_subject_multiseed_runner_fails_without_partial_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace, command, _plan, _adapter = _workspace(tmp_path)
    monkeypatch.setattr(
        science_subject_multiseed_runner,
        "validate_adapter_files",
        lambda _root: (),
    )

    result = science_subject_multiseed_runner.run_science_subject_multiseed_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), tmp_path),
    )

    assert result.status == "FAILED"
    assert result.error_code == "SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID"
    assert result.outputs == ()
    assert not (workspace / "outputs").exists()
