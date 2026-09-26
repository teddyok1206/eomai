"""Run one paired campaign holdout evaluation without DB or NAS access."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from eom_image_contracts import (
    LocalImageScienceCampaignLoraMicroEvaluationCommand,
    LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    LocalImageScienceCampaignLoraMicroEvaluationOutput,
    LocalImageScienceCampaignLoraMicroEvaluationResult,
    LocalImageScienceCampaignLoraMicroEvaluationResultV2,
    content_sha256,
    validate_contract,
    validate_science_campaign_micro_evaluation_result,
    validate_science_campaign_micro_evaluation_result_v2,
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


class ScienceCampaignMicroEvaluationRunnerError(RuntimeError):
    """Stable error at the isolated campaign evaluation boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ScienceCampaignEvaluationBackend(Protocol):
    def generate_campaign_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageScienceCampaignLoraMicroEvaluationCommand
        | LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    ) -> tuple[GeneratedEvaluationImage, ...]: ...


def load_science_campaign_micro_evaluation_command(
    path: Path,
) -> (
    LocalImageScienceCampaignLoraMicroEvaluationCommand
    | LocalImageScienceCampaignLoraMicroEvaluationCommandV2
):
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        if value.get("schema_version") == (
            "local-image-science-campaign-lora-micro-evaluation-command/1.1"
        ):
            validate_contract("science-campaign-lora-micro-evaluation-command-v2", value)
            return LocalImageScienceCampaignLoraMicroEvaluationCommandV2.model_validate(value)
        validate_contract("science-campaign-lora-micro-evaluation-command", value)
        return LocalImageScienceCampaignLoraMicroEvaluationCommand.model_validate(value)
    except Exception as exc:
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_COMMAND_INVALID") from exc


def _validate_adapter(
    workspace: Path,
    command: LocalImageScienceCampaignLoraMicroEvaluationCommand
    | LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
) -> Path:
    adapter_root = _require_member(workspace, command.staged_adapter_root)
    try:
        actual = validate_adapter_files(adapter_root)
    except TrainingRunnerError as exc:
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_ADAPTER_INVALID") from exc
    expected = tuple(value.model_dump(mode="json") for value in command.adapter_manifest.files)
    if actual != expected:
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_ADAPTER_HASH_MISMATCH")
    return adapter_root


def _output(
    *,
    command: LocalImageScienceCampaignLoraMicroEvaluationCommand
    | LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    generated: GeneratedEvaluationImage,
    workspace: Path,
) -> LocalImageScienceCampaignLoraMicroEvaluationOutput:
    if generated.variant not in {"ADAPTER", "BASE"}:
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID")
    member_path = (
        f"{command.output_root_member}/{generated.sample_id}-{generated.variant.lower()}.png"
    )
    if not 64 <= len(generated.png_bytes) <= 64 * 1024 * 1024:
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID")
    try:
        with Image.open(io.BytesIO(generated.png_bytes)) as image:
            image.load()
            if image.format != "PNG" or image.size != (
                command.delivery_width,
                command.delivery_height,
            ):
                raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID")
    except (OSError, UnidentifiedImageError) as exc:
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID") from exc
    try:
        output_root = _require_member(workspace, command.output_root_member)
        _write_exclusive(output_root / Path(member_path).name, generated.png_bytes)
    except TrainingRunnerError as exc:
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_INVALID") from exc
    return LocalImageScienceCampaignLoraMicroEvaluationOutput(
        sample_id=generated.sample_id,
        variant=generated.variant,
        member_path=member_path,
        sha256=_sha256(generated.png_bytes),
        size_bytes=len(generated.png_bytes),
        width_px=command.delivery_width,
        height_px=command.delivery_height,
    )


def _result(
    *,
    command: LocalImageScienceCampaignLoraMicroEvaluationCommand
    | LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    status: Literal["FAILED", "SUCCEEDED"],
    outputs: tuple[LocalImageScienceCampaignLoraMicroEvaluationOutput, ...],
    error_code: str | None,
    started_at: datetime,
) -> (
    LocalImageScienceCampaignLoraMicroEvaluationResult
    | LocalImageScienceCampaignLoraMicroEvaluationResultV2
):
    expanded = isinstance(command, LocalImageScienceCampaignLoraMicroEvaluationCommandV2)
    version = "1.1" if expanded else "1.0"
    body = {
        "schema_version": f"local-image-science-campaign-lora-micro-evaluation-result/{version}",
        "evaluation_run_id": command.evaluation_run_id,
        "command_sha256": command.command_sha256,
        "training_result_sha256": command.training_result_sha256,
        "adapter_manifest_sha256": command.adapter_manifest.manifest_sha256,
        "status": status,
        "outputs": [value.model_dump(mode="json") for value in outputs],
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "result_sha256": content_sha256(body)}
    if expanded:
        assert isinstance(command, LocalImageScienceCampaignLoraMicroEvaluationCommandV2)
        validate_contract("science-campaign-lora-micro-evaluation-result-v2", value)
        result_v2 = LocalImageScienceCampaignLoraMicroEvaluationResultV2.model_validate(value)
        validate_science_campaign_micro_evaluation_result_v2(command, result_v2)
        return result_v2
    validate_contract("science-campaign-lora-micro-evaluation-result", value)
    result_v1 = LocalImageScienceCampaignLoraMicroEvaluationResult.model_validate(value)
    validate_science_campaign_micro_evaluation_result(command, result_v1)
    return result_v1


def run_science_campaign_micro_evaluation_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageScienceCampaignLoraMicroEvaluationCommand
    | LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    backend: ScienceCampaignEvaluationBackend,
    model_resolver: Any,
) -> (
    LocalImageScienceCampaignLoraMicroEvaluationResult
    | LocalImageScienceCampaignLoraMicroEvaluationResultV2
):
    """Generate exact BASE/ADAPTER pairs and write one terminal typed result."""

    _require_workspace(workspace)
    result_path = workspace / "result.json"
    if result_path.exists() or result_path.is_symlink():
        raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_RESULT_EXISTS")
    started_at = datetime.now(UTC)
    outputs: tuple[LocalImageScienceCampaignLoraMicroEvaluationOutput, ...] = ()
    try:
        adapter_root = _validate_adapter(workspace, command)
        _manifest, model_directory = model_resolver(
            model_store_root,
            command.adapter_manifest.base_model,
        )
        output_root = workspace / command.output_root_member
        if output_root.exists() or output_root.is_symlink():
            raise ScienceCampaignMicroEvaluationRunnerError("IMAGE_EVALUATION_OUTPUT_EXISTS")
        output_root.mkdir(mode=0o700)
        generated = backend.generate_campaign_pairs(
            model_directory=model_directory,
            adapter_root=adapter_root,
            command=command,
        )
        outputs = tuple(
            sorted(
                (
                    _output(command=command, generated=value, workspace=workspace)
                    for value in generated
                ),
                key=lambda value: (value.sample_id, value.variant),
            )
        )
        result = _result(
            command=command,
            status="SUCCEEDED",
            outputs=outputs,
            error_code=None,
            started_at=started_at,
        )
    except (MicroEvaluationRunnerError, ScienceCampaignMicroEvaluationRunnerError) as exc:
        result = _result(
            command=command,
            status="FAILED",
            outputs=outputs,
            error_code=exc.code,
            started_at=started_at,
        )
    _write_exclusive(result_path, _canonical_json(result.model_dump(mode="json")))
    return result
