from __future__ import annotations

import io
from pathlib import Path

from eom_catalog_service.science_visual_subject_benchmark import (
    build_science_visual_subject_benchmark_plan,
)
from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualSubjectBenchmarkCommand,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    content_json_bytes,
)
from eom_image_trainer import science_subject_benchmark_runner
from eom_image_trainer.micro_evaluation_runner import GeneratedEvaluationImage
from PIL import Image

from tests.unit.test_science_visual_subject_benchmark_contracts import (
    NOW,
    _adapter_manifest,
    _command,
    _inventory,
)


def _pointer(
    token: str,
    *,
    member_path: str,
    schema_ref: str,
    sha256: str,
) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=f"artifact_{token * 32}",
        artifact_revision_id=f"rev_{token * 32}",
        member_path=member_path,
        schema_ref=schema_ref,
        media_type="application/json",
        sha256=sha256,
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
    def generate_subject_benchmark_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageScienceVisualSubjectBenchmarkCommand,
        plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    ) -> tuple[GeneratedEvaluationImage, ...]:
        assert model_directory.is_dir()
        assert adapter_root.is_dir()
        return tuple(
            GeneratedEvaluationImage(
                sample_id=case.case_id,
                variant=variant,
                png_bytes=_png((index, index, index)),
            )
            for index, (case, variant) in enumerate(
                (case, variant)
                for case in plan.cases
                if case.case_kind == "QUALITY"
                for variant in ("ADAPTER", "BASE")
            )
        )


def _workspace(tmp_path: Path):
    inventory = _inventory()
    adapter = _adapter_manifest()
    inventory_payload = content_json_bytes(inventory.model_dump(mode="json"))
    adapter_payload = content_json_bytes(adapter.model_dump(mode="json")) + b"\n"
    plan = build_science_visual_subject_benchmark_plan(
        inventory=inventory,
        inventory_pointer=_pointer(
            "a",
            member_path="manifests/science-visual-subject-inventory.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0"
            ),
            sha256=sha256_bytes(inventory_payload),
        ),
        adapter_manifest=adapter,
        adapter_manifest_pointer=_pointer(
            "b",
            member_path="manifests/adapter-manifest.json",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
            ),
            sha256=sha256_bytes(adapter_payload),
        ),
        created_at=NOW,
        created_by="runner_test",
    )
    command = _command(plan)
    workspace = tmp_path / command.run_id
    workspace.mkdir(mode=0o700)
    inputs = workspace / "inputs"
    adapter_root = inputs / "adapter"
    adapter_root.mkdir(parents=True)
    (inputs / "subject-benchmark-plan.json").write_bytes(
        content_json_bytes(plan.model_dump(mode="json"))
    )
    (inputs / "science-visual-subject-inventory.json").write_bytes(inventory_payload)
    (adapter_root / "adapter-manifest.json").write_bytes(adapter_payload)
    (adapter_root / "adapter_config.json").write_bytes(b"config")
    (adapter_root / "adapter_model.safetensors").write_bytes(b"weights")
    (workspace / "command.json").write_bytes(content_json_bytes(command.model_dump(mode="json")))
    for path in (
        inputs / "subject-benchmark-plan.json",
        inputs / "science-visual-subject-inventory.json",
        adapter_root / "adapter-manifest.json",
        adapter_root / "adapter_config.json",
        adapter_root / "adapter_model.safetensors",
        workspace / "command.json",
    ):
        path.chmod(0o440)
    return workspace, command, plan, adapter


def test_science_subject_benchmark_runner_closes_every_route(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace, command, plan, adapter = _workspace(tmp_path)
    model_directory = tmp_path / "model"
    model_directory.mkdir()
    monkeypatch.setattr(
        science_subject_benchmark_runner,
        "validate_adapter_files",
        lambda _root: tuple(value.model_dump(mode="json") for value in adapter.files),
    )

    result = science_subject_benchmark_runner.run_science_subject_benchmark_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), model_directory),
    )

    assert result.status == "SUCCEEDED"
    assert result.error_code is None
    assert len(result.outcomes) == len(plan.cases)
    assert {output.variant for output in result.outputs} == {
        "ADAPTER",
        "BASE",
        "DETERMINISTIC",
    }
    assert all((workspace / output.relative_path).is_file() for output in result.outputs)
    assert (workspace / "result.json").is_file()
    assert not any(
        output.case_id
        == next(case.case_id for case in plan.cases if case.case_kind == "GPU_POLICY_NEGATIVE")
        for output in result.outputs
    )


def test_science_subject_benchmark_runner_records_adapter_hash_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace, command, _plan, _adapter = _workspace(tmp_path)
    monkeypatch.setattr(
        science_subject_benchmark_runner, "validate_adapter_files", lambda _root: ()
    )

    result = science_subject_benchmark_runner.run_science_subject_benchmark_command(
        workspace=workspace,
        model_store_root=tmp_path,
        command=command,
        backend=_Backend(),
        model_resolver=lambda _root, _pointer: (object(), tmp_path),
    )

    assert result.status == "FAILED"
    assert result.error_code == "SCIENCE_SUBJECT_BENCHMARK_ADAPTER_INVALID"
    assert result.outcomes == ()
    assert result.outputs == ()
    assert not (workspace / "outputs").exists()
