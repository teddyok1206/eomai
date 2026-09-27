"""Run fixed additional-seed science-subject evaluation without DB or NAS access."""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from eom_image_contracts import (
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
    LocalImageScienceVisualSubjectMultiseedCommand,
    LocalImageScienceVisualSubjectMultiseedPlan,
    LocalImageScienceVisualSubjectMultiseedResult,
    ScienceVisualSubjectMultiseedOutput,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_science_visual_subject_multiseed_plan,
    validate_science_visual_subject_multiseed_result,
)
from PIL import Image, UnidentifiedImageError

from eom_image_trainer.micro_evaluation_runner import (
    GeneratedEvaluationImage,
    MicroEvaluationRunnerError,
)
from eom_image_trainer.runner import (
    MAX_JSON_BYTES,
    TrainingRunnerError,
    _canonical_json,
    _parse_json,
    _read_regular,
    _require_member,
    _require_workspace,
    _sha256,
    _write_exclusive,
    validate_adapter_files,
)


class ScienceSubjectMultiseedRunnerError(RuntimeError):
    """Stable error at the isolated multi-seed boundary."""

    def __init__(
        self,
        code: str,
        *,
        plan: LocalImageScienceVisualSubjectMultiseedPlan | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.plan = plan


class SubjectMultiseedBackend(Protocol):
    def generate_subject_multiseed_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageScienceVisualSubjectMultiseedCommand,
        plan: LocalImageScienceVisualSubjectMultiseedPlan,
    ) -> tuple[GeneratedEvaluationImage, ...]: ...


def load_science_subject_multiseed_command(
    path: Path,
) -> LocalImageScienceVisualSubjectMultiseedCommand:
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        validate_contract("science-visual-subject-multiseed-command", value)
        return LocalImageScienceVisualSubjectMultiseedCommand.model_validate(value)
    except Exception as exc:
        raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID") from exc


def _typed_json(
    path: Path,
    *,
    contract: str,
    model: type[Any],
    error_code: str,
) -> tuple[bytes, Any]:
    payload = _read_regular(path, maximum_bytes=MAX_JSON_BYTES)
    value = _parse_json(payload)
    try:
        validate_contract(contract, value)
        parsed = model.model_validate(value)
    except Exception as exc:
        raise ScienceSubjectMultiseedRunnerError(error_code) from exc
    canonical = content_json_bytes(parsed.model_dump(mode="json"))
    if payload not in {canonical, canonical + b"\n"}:
        raise ScienceSubjectMultiseedRunnerError(error_code)
    return payload, parsed


def _load_inputs(
    workspace: Path,
    command: LocalImageScienceVisualSubjectMultiseedCommand,
) -> tuple[
    LocalImageScienceVisualSubjectMultiseedPlan,
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    Path,
]:
    plan: LocalImageScienceVisualSubjectMultiseedPlan | None = None
    try:
        plan_payload, plan = _typed_json(
            _require_member(workspace, command.staged_plan_path),
            contract="science-visual-subject-multiseed-plan",
            model=LocalImageScienceVisualSubjectMultiseedPlan,
            error_code="SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID",
        )
        inventory_payload, inventory = _typed_json(
            _require_member(workspace, command.staged_subject_inventory_path),
            contract="science-visual-subject-inventory",
            model=LocalImageScienceVisualSubjectInventory,
            error_code="SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID",
        )
        initial_plan_payload, initial_plan = _typed_json(
            _require_member(workspace, command.staged_initial_benchmark_plan_path),
            contract="science-visual-subject-benchmark-plan",
            model=LocalImageScienceVisualSubjectBenchmarkPlan,
            error_code="SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID",
        )
        initial_review_payload, initial_review = _typed_json(
            _require_member(workspace, command.staged_initial_quality_review_path),
            contract="science-visual-subject-benchmark-review",
            model=LocalImageScienceVisualSubjectBenchmarkReview,
            error_code="SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID",
        )
        adapter_path = _require_member(workspace, command.staged_adapter_manifest_path)
        adapter_payload, adapter = _typed_json(
            adapter_path,
            contract="science-campaign-lora-micro-adapter-manifest-v2",
            model=LocalImageScienceCampaignLoraMicroAdapterManifestV2,
            error_code="SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID",
        )
        if (
            _sha256(plan_payload) != command.plan.sha256
            or plan.plan_sha256 != command.plan_sha256
            or _sha256(inventory_payload) != plan.subject_inventory.sha256
            or _sha256(initial_plan_payload) != plan.initial_benchmark_plan.sha256
            or _sha256(initial_review_payload) != plan.initial_quality_review.sha256
            or _sha256(adapter_payload) != plan.adapter_manifest.sha256
            or adapter.base_model != plan.base_model
        ):
            raise ScienceSubjectMultiseedRunnerError(
                "SCIENCE_SUBJECT_MULTISEED_INPUT_HASH_MISMATCH"
            )
        validate_science_visual_subject_multiseed_plan(
            inventory,
            initial_plan,
            initial_review,
            plan,
        )
        adapter_root = adapter_path.parent
        actual_files = validate_adapter_files(adapter_root)
        expected_files = tuple(value.model_dump(mode="json") for value in adapter.files)
        if actual_files != expected_files:
            raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID")
        return plan, adapter, adapter_root
    except ScienceSubjectMultiseedRunnerError as exc:
        if exc.plan is not None or plan is None:
            raise
        raise ScienceSubjectMultiseedRunnerError(exc.code, plan=plan) from exc
    except TrainingRunnerError as exc:
        raise ScienceSubjectMultiseedRunnerError(
            "SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID", plan=plan
        ) from exc
    except Exception as exc:
        raise ScienceSubjectMultiseedRunnerError(
            "SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID", plan=plan
        ) from exc


def _validate_png(payload: bytes, *, width: int, height: int) -> None:
    if not 64 <= len(payload) <= 64 * 1024 * 1024:
        raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.format != "PNG" or image.size != (width, height):
                raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
    except (OSError, UnidentifiedImageError) as exc:
        raise ScienceSubjectMultiseedRunnerError(
            "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID"
        ) from exc


def _result(
    *,
    command: LocalImageScienceVisualSubjectMultiseedCommand,
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
    status: Literal["FAILED", "SUCCEEDED"],
    error_code: str | None,
    outputs: tuple[ScienceVisualSubjectMultiseedOutput, ...],
    started_at: datetime,
) -> LocalImageScienceVisualSubjectMultiseedResult:
    body = {
        "schema_version": "local-image-science-visual-subject-multiseed-result/1.0",
        "run_id": command.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "command_sha256": command.command_sha256,
        "status": status,
        "error_code": error_code,
        "outputs": [value.model_dump(mode="json") for value in outputs],
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("science-visual-subject-multiseed-result", value)
    result = LocalImageScienceVisualSubjectMultiseedResult.model_validate(value)
    validate_science_visual_subject_multiseed_result(plan, command, result)
    return result


def run_science_subject_multiseed_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageScienceVisualSubjectMultiseedCommand,
    backend: SubjectMultiseedBackend,
    model_resolver: Callable[[Path, object], tuple[object, Path]],
) -> LocalImageScienceVisualSubjectMultiseedResult:
    """Generate all additional pairs and expose no partial final output directory."""

    _require_workspace(workspace)
    result_path = workspace / "result.json"
    if result_path.exists() or result_path.is_symlink():
        raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_RESULT_EXISTS")
    started_at = datetime.now(UTC)
    plan: LocalImageScienceVisualSubjectMultiseedPlan | None = None
    try:
        plan, _adapter, adapter_root = _load_inputs(workspace, command)
        try:
            _manifest, model_directory = model_resolver(model_store_root, plan.base_model)
        except Exception as exc:
            raise ScienceSubjectMultiseedRunnerError(
                "SCIENCE_SUBJECT_MULTISEED_MODEL_INVALID"
            ) from exc
        try:
            generated = backend.generate_subject_multiseed_pairs(
                model_directory=model_directory,
                adapter_root=adapter_root,
                command=command,
                plan=plan,
            )
        except MicroEvaluationRunnerError as exc:
            mapped = {
                "IMAGE_EVALUATION_ADAPTER_INVALID": "SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID",
                "IMAGE_EVALUATION_MODEL_INVALID": "SCIENCE_SUBJECT_MULTISEED_MODEL_INVALID",
                "IMAGE_EVALUATION_OOM": "SCIENCE_SUBJECT_MULTISEED_OOM",
                "IMAGE_EVALUATION_RUNTIME_DRIFT": "SCIENCE_SUBJECT_MULTISEED_GPU_RUNTIME_DRIFT",
            }.get(exc.code, "SCIENCE_SUBJECT_MULTISEED_EXEC_FAILED")
            raise ScienceSubjectMultiseedRunnerError(mapped) from exc
        generated_by_key: dict[tuple[str, str], bytes] = {}
        for value in generated:
            key = (value.sample_id, value.variant)
            if key in generated_by_key:
                raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
            generated_by_key[key] = value.png_bytes
        expected_keys = {
            (case.case_id, variant) for case in plan.cases for variant in ("ADAPTER", "BASE")
        }
        if set(generated_by_key) != expected_keys:
            raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
        pending = workspace / f".outputs-{command.run_id}"
        if pending.exists() or pending.is_symlink() or (workspace / "outputs").exists():
            raise ScienceSubjectMultiseedRunnerError("SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID")
        pending.mkdir(mode=0o700)
        outputs = []
        for (case_id, variant), payload in sorted(generated_by_key.items()):
            _validate_png(
                payload,
                width=plan.delivery_width_px,
                height=plan.delivery_height_px,
            )
            filename = f"{case_id}-{variant.lower()}.png"
            _write_exclusive(pending / filename, payload)
            outputs.append(
                ScienceVisualSubjectMultiseedOutput(
                    case_id=case_id,
                    variant=cast(Literal["ADAPTER", "BASE"], variant),
                    relative_path=f"outputs/{filename}",
                    media_type="image/png",
                    bytes=len(payload),
                    sha256=_sha256(payload),
                    width_px=plan.delivery_width_px,
                    height_px=plan.delivery_height_px,
                )
            )
        os.rename(pending, workspace / command.output_directory)
        result = _result(
            command=command,
            plan=plan,
            status="SUCCEEDED",
            error_code=None,
            outputs=tuple(outputs),
            started_at=started_at,
        )
    except ScienceSubjectMultiseedRunnerError as exc:
        if plan is None:
            plan = exc.plan
        if plan is None:
            raise
        result = _result(
            command=command,
            plan=plan,
            status="FAILED",
            error_code=exc.code,
            outputs=(),
            started_at=started_at,
        )
    _write_exclusive(result_path, _canonical_json(result.model_dump(mode="json")))
    return result
