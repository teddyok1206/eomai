"""Run the corpus-grounded science-subject benchmark without DB or NAS access."""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from eom_image_contracts import (
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    LocalImageScienceVisualSubjectBenchmarkCommand,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkResult,
    LocalImageScienceVisualSubjectInventory,
    ScienceVisualSubject,
    ScienceVisualSubjectBenchmarkOutcome,
    ScienceVisualSubjectBenchmarkOutput,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_science_visual_subject_benchmark_plan,
    validate_science_visual_subject_benchmark_result,
)
from PIL import Image, ImageDraw, UnidentifiedImageError

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


class ScienceSubjectBenchmarkRunnerError(RuntimeError):
    """Stable error at the isolated science-subject benchmark boundary."""

    def __init__(
        self,
        code: str,
        *,
        plan: LocalImageScienceVisualSubjectBenchmarkPlan | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.plan = plan


class SubjectBenchmarkBackend(Protocol):
    def generate_subject_benchmark_pairs(
        self,
        *,
        model_directory: Path,
        adapter_root: Path,
        command: LocalImageScienceVisualSubjectBenchmarkCommand,
        plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    ) -> tuple[GeneratedEvaluationImage, ...]: ...


def load_science_subject_benchmark_command(
    path: Path,
) -> LocalImageScienceVisualSubjectBenchmarkCommand:
    value = _parse_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        validate_contract("science-visual-subject-benchmark-command", value)
        return LocalImageScienceVisualSubjectBenchmarkCommand.model_validate(value)
    except Exception as exc:
        raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID") from exc


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
        raise ScienceSubjectBenchmarkRunnerError(error_code) from exc
    canonical = content_json_bytes(parsed.model_dump(mode="json"))
    if payload not in {canonical, canonical + b"\n"}:
        raise ScienceSubjectBenchmarkRunnerError(error_code)
    return payload, parsed


def _load_inputs(
    workspace: Path,
    command: LocalImageScienceVisualSubjectBenchmarkCommand,
) -> tuple[
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectInventory,
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    Path,
]:
    plan: LocalImageScienceVisualSubjectBenchmarkPlan | None = None
    try:
        plan_path = _require_member(workspace, command.staged_plan_path)
        inventory_path = _require_member(workspace, command.staged_subject_inventory_path)
        adapter_manifest_path = _require_member(workspace, command.staged_adapter_manifest_path)
        plan_payload, plan = _typed_json(
            plan_path,
            contract="science-visual-subject-benchmark-plan",
            model=LocalImageScienceVisualSubjectBenchmarkPlan,
            error_code="SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID",
        )
        inventory_payload, inventory = _typed_json(
            inventory_path,
            contract="science-visual-subject-inventory",
            model=LocalImageScienceVisualSubjectInventory,
            error_code="SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID",
        )
        adapter_payload = _read_regular(adapter_manifest_path, maximum_bytes=MAX_JSON_BYTES)
        adapter_value = _parse_json(adapter_payload)
        validate_contract("science-campaign-lora-micro-adapter-manifest-v2", adapter_value)
        adapter = LocalImageScienceCampaignLoraMicroAdapterManifestV2.model_validate(adapter_value)
        canonical_adapter = content_json_bytes(adapter.model_dump(mode="json"))
        if adapter_payload not in {canonical_adapter, canonical_adapter + b"\n"}:
            raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_ADAPTER_INVALID")
        if (
            _sha256(plan_payload) != command.plan.sha256
            or plan.plan_sha256 != command.plan_sha256
            or _sha256(inventory_payload) != plan.subject_inventory.sha256
            or _sha256(adapter_payload) != plan.adapter_manifest.sha256
            or adapter.base_model != plan.base_model
        ):
            raise ScienceSubjectBenchmarkRunnerError(
                "SCIENCE_SUBJECT_BENCHMARK_INPUT_HASH_MISMATCH"
            )
        validate_science_visual_subject_benchmark_plan(inventory, plan)
        adapter_root = adapter_manifest_path.parent
        actual_files = validate_adapter_files(adapter_root)
        expected_files = tuple(value.model_dump(mode="json") for value in adapter.files)
        if actual_files != expected_files:
            raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_ADAPTER_INVALID")
        return plan, inventory, adapter, adapter_root
    except ScienceSubjectBenchmarkRunnerError as exc:
        if exc.plan is not None or plan is None:
            raise
        raise ScienceSubjectBenchmarkRunnerError(exc.code, plan=plan) from exc
    except TrainingRunnerError as exc:
        raise ScienceSubjectBenchmarkRunnerError(
            "SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID", plan=plan
        ) from exc
    except Exception as exc:
        raise ScienceSubjectBenchmarkRunnerError(
            "SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID", plan=plan
        ) from exc


def _line(
    draw: ImageDraw.ImageDraw, points: tuple[tuple[int, int], ...], *, width: int = 4
) -> None:
    draw.line(points, fill="black", width=width, joint="curve")


def _deterministic_png(subject: ScienceVisualSubject) -> bytes:
    """Rasterize a bounded route diagnostic; production remains the Python/SVG path."""

    image = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(image)
    primitive = subject.renderer_primitive
    key = subject.subject_key
    if key == "VEHICLE_CAR":
        draw.rounded_rectangle((205, 230, 595, 350), 28, outline="black", width=6)
        draw.polygon(((300, 230), (365, 160), (500, 160), (555, 230)), outline="black")
        for x in (295, 515):
            draw.ellipse((x - 42, 320, x + 42, 404), fill="white", outline="black", width=7)
            draw.ellipse((x - 12, 350, x + 12, 374), fill="black")
    elif key in {"HUMAN_FIGURE", "STUDENT_OR_TEACHER"}:
        draw.ellipse((355, 65, 445, 155), outline="black", width=6)
        _line(draw, ((400, 155), (400, 330)), width=7)
        _line(draw, ((400, 210), (300, 270)), width=7)
        _line(draw, ((400, 210), (500, 270)), width=7)
        _line(draw, ((400, 330), (325, 440)), width=7)
        _line(draw, ((400, 330), (475, 440)), width=7)
    elif key in {"BEAKER", "CHEMICAL_FLASK", "TEST_TUBE", "SOLUTION_LIQUID"}:
        _line(draw, ((290, 85), (290, 360), (335, 420), (465, 420), (510, 360), (510, 85)))
        _line(draw, ((270, 85), (530, 85)), width=7)
        draw.rectangle((296, 265, 504, 360), fill="#d9d9d9")
        _line(draw, ((296, 265), (504, 265)), width=5)
    elif primitive == "APPARATUS":
        draw.rectangle((170, 350, 630, 390), outline="black", width=5)
        draw.ellipse((260, 110, 390, 240), outline="black", width=5)
        draw.rectangle((440, 130, 555, 330), outline="black", width=5)
        _line(draw, ((325, 240), (325, 350), (495, 350), (495, 330)))
    elif primitive == "AXIS_PLOT":
        _line(draw, ((130, 410), (690, 410)), width=5)
        _line(draw, ((150, 440), (150, 70)), width=5)
        _line(draw, ((150, 385), (270, 330), (385, 345), (500, 205), (650, 120)), width=7)
    elif primitive == "CELL_CROSS_SECTION":
        draw.ellipse((150, 70, 650, 430), outline="black", width=7)
        draw.ellipse((310, 150, 490, 330), fill="#e4e4e4", outline="black", width=5)
        for x, y in ((240, 170), (540, 185), (250, 330), (535, 320)):
            draw.ellipse((x - 35, y - 18, x + 35, y + 18), outline="black", width=4)
    elif primitive == "CIRCUIT":
        draw.rectangle((145, 105, 655, 395), outline="black", width=5)
        _line(draw, ((145, 250), (245, 250)), width=5)
        _line(draw, ((245, 215), (245, 285)), width=5)
        _line(draw, ((270, 230), (270, 270)), width=9)
        _line(draw, ((270, 250), (380, 250)), width=5)
        draw.rectangle((380, 205, 520, 295), outline="black", width=5)
        _line(draw, ((520, 250), (655, 250)), width=5)
    elif primitive == "CONTENT_TABLE":
        draw.rectangle((120, 90, 680, 410), outline="black", width=5)
        for y in (170, 250, 330):
            _line(draw, ((120, y), (680, y)), width=3)
        for x in (310, 500):
            _line(draw, ((x, 90), (x, 410)), width=3)
    elif primitive == "FLOW_DIAGRAM":
        for x in (90, 315, 540):
            draw.rounded_rectangle((x, 185, x + 170, 315), 18, outline="black", width=5)
        for x in (260, 485):
            _line(draw, ((x, 250), (x + 55, 250)), width=5)
            draw.polygon(((x + 55, 250), (x + 35, 235), (x + 35, 265)), fill="black")
    elif primitive == "GEOLOGIC_SECTION":
        layers = (((80, 160), (720, 115)), ((80, 250), (720, 220)), ((80, 340), (720, 330)))
        for start, end in layers:
            _line(draw, (start, end), width=7)
        draw.polygon(((80, 410), (80, 160), (720, 115), (720, 410)), outline="black")
    elif primitive == "MAP_BOUNDARY":
        draw.polygon(
            (
                (180, 115),
                (330, 70),
                (440, 150),
                (610, 125),
                (665, 300),
                (520, 420),
                (320, 370),
                (150, 250),
            ),
            outline="black",
        )
        _line(draw, ((330, 70), (350, 235), (520, 420)), width=4)
        _line(draw, ((150, 250), (350, 235), (665, 300)), width=4)
    elif primitive == "ORBITAL_SYSTEM":
        draw.ellipse((345, 195, 455, 305), fill="#d0d0d0", outline="black", width=5)
        for box in ((155, 80, 645, 420), (225, 125, 575, 375), (295, 165, 505, 335)):
            draw.ellipse(box, outline="black", width=3)
        draw.ellipse((615, 230, 655, 270), fill="black")
    elif primitive == "PARTICLE_SYSTEM":
        for row in range(4):
            for column in range(7):
                x = 190 + column * 70 + (row % 2) * 22
                y = 125 + row * 85
                draw.ellipse((x - 22, y - 22, x + 22, y + 22), outline="black", width=4)
    elif primitive == "RAY_DIAGRAM":
        draw.polygon(((390, 90), (505, 390), (275, 390)), outline="black")
        _line(draw, ((80, 160), (390, 230), (700, 150)), width=5)
        _line(draw, ((80, 300), (390, 250), (700, 340)), width=5)
    elif primitive == "VECTOR_FIELD":
        for y in (120, 220, 320, 420):
            for x in (120, 270, 420, 570):
                _line(draw, ((x, y), (x + 75, y - 35)), width=4)
                draw.polygon(((x + 75, y - 35), (x + 54, y - 36), (x + 66, y - 17)), fill="black")
    else:
        draw.ellipse((155, 85, 375, 305), outline="black", width=6)
        draw.rectangle((470, 195, 675, 390), outline="black", width=6)
        _line(draw, ((375, 195), (470, 260)), width=5)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def _validate_png(payload: bytes, *, width: int, height: int) -> None:
    if not 64 <= len(payload) <= 64 * 1024 * 1024:
        raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_OUTPUT_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.format != "PNG" or image.size != (width, height):
                raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_OUTPUT_INVALID")
    except (OSError, UnidentifiedImageError) as exc:
        raise ScienceSubjectBenchmarkRunnerError(
            "SCIENCE_SUBJECT_BENCHMARK_OUTPUT_INVALID"
        ) from exc


def _result(
    *,
    command: LocalImageScienceVisualSubjectBenchmarkCommand,
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    status: Literal["FAILED", "SUCCEEDED"],
    error_code: str | None,
    outcomes: tuple[ScienceVisualSubjectBenchmarkOutcome, ...],
    outputs: tuple[ScienceVisualSubjectBenchmarkOutput, ...],
    started_at: datetime,
) -> LocalImageScienceVisualSubjectBenchmarkResult:
    body = {
        "schema_version": "local-image-science-visual-subject-benchmark-result/1.0",
        "run_id": command.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "command_sha256": command.command_sha256,
        "status": status,
        "error_code": error_code,
        "outcomes": [value.model_dump(mode="json") for value in outcomes],
        "outputs": [value.model_dump(mode="json") for value in outputs],
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("science-visual-subject-benchmark-result", value)
    result = LocalImageScienceVisualSubjectBenchmarkResult.model_validate(value)
    validate_science_visual_subject_benchmark_result(plan, command, result)
    return result


def run_science_subject_benchmark_command(
    *,
    workspace: Path,
    model_store_root: Path,
    command: LocalImageScienceVisualSubjectBenchmarkCommand,
    backend: SubjectBenchmarkBackend,
    model_resolver: Callable[[Path, object], tuple[object, Path]],
) -> LocalImageScienceVisualSubjectBenchmarkResult:
    """Execute all routes once and publish no partial canonical output directory."""

    _require_workspace(workspace)
    result_path = workspace / "result.json"
    if result_path.exists() or result_path.is_symlink():
        raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_RESULT_EXISTS")
    started_at = datetime.now(UTC)
    plan: LocalImageScienceVisualSubjectBenchmarkPlan | None = None
    try:
        plan, inventory, _adapter, adapter_root = _load_inputs(workspace, command)
        try:
            _manifest, model_directory = model_resolver(model_store_root, plan.base_model)
        except Exception as exc:
            raise ScienceSubjectBenchmarkRunnerError(
                "SCIENCE_SUBJECT_BENCHMARK_MODEL_INVALID"
            ) from exc
        subjects = {subject.subject_id: subject for subject in inventory.subjects}
        generated_by_key: dict[tuple[str, str], bytes] = {}
        for case in plan.cases:
            if case.case_kind == "ROUTE":
                generated_by_key[(case.case_id, "DETERMINISTIC")] = _deterministic_png(
                    subjects[case.subject_id]
                )
        try:
            generated = backend.generate_subject_benchmark_pairs(
                model_directory=model_directory,
                adapter_root=adapter_root,
                command=command,
                plan=plan,
            )
        except MicroEvaluationRunnerError as exc:
            mapped = {
                "IMAGE_EVALUATION_ADAPTER_INVALID": ("SCIENCE_SUBJECT_BENCHMARK_ADAPTER_INVALID"),
                "IMAGE_EVALUATION_MODEL_INVALID": "SCIENCE_SUBJECT_BENCHMARK_MODEL_INVALID",
                "IMAGE_EVALUATION_OOM": "SCIENCE_SUBJECT_BENCHMARK_OOM",
                "IMAGE_EVALUATION_RUNTIME_DRIFT": ("SCIENCE_SUBJECT_BENCHMARK_GPU_RUNTIME_DRIFT"),
            }.get(exc.code, "SCIENCE_SUBJECT_BENCHMARK_EXEC_FAILED")
            raise ScienceSubjectBenchmarkRunnerError(mapped) from exc
        for value in generated:
            key = (value.sample_id, value.variant)
            if key in generated_by_key:
                raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_OUTPUT_INVALID")
            generated_by_key[key] = value.png_bytes
        expected_keys = {
            (case.case_id, variant)
            for case in plan.cases
            for variant in (
                ("BASE", "ADAPTER")
                if case.case_kind == "QUALITY"
                else ("DETERMINISTIC",)
                if case.case_kind == "ROUTE"
                else ()
            )
        }
        if set(generated_by_key) != expected_keys:
            raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_OUTPUT_INVALID")
        pending = workspace / f".outputs-{command.run_id}"
        if (
            pending.exists()
            or pending.is_symlink()
            or (workspace / command.output_directory).exists()
        ):
            raise ScienceSubjectBenchmarkRunnerError("SCIENCE_SUBJECT_BENCHMARK_OUTPUT_INVALID")
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
                ScienceVisualSubjectBenchmarkOutput(
                    case_id=case_id,
                    variant=cast(Literal["ADAPTER", "BASE", "DETERMINISTIC"], variant),
                    relative_path=f"outputs/{filename}",
                    media_type="image/png",
                    bytes=len(payload),
                    sha256=_sha256(payload),
                    width_px=plan.delivery_width_px,
                    height_px=plan.delivery_height_px,
                )
            )
        os.rename(pending, workspace / command.output_directory)
        outcomes = tuple(
            ScienceVisualSubjectBenchmarkOutcome(
                case_id=case.case_id,
                outcome=case.expected_outcome,
                stable_code=(
                    "LOCAL_IMAGE_HUMAN_SUBJECT_FORBIDDEN"
                    if case.case_kind == "GPU_POLICY_NEGATIVE"
                    else None
                ),
            )
            for case in plan.cases
        )
        result = _result(
            command=command,
            plan=plan,
            status="SUCCEEDED",
            error_code=None,
            outcomes=outcomes,
            outputs=tuple(outputs),
            started_at=started_at,
        )
    except ScienceSubjectBenchmarkRunnerError as exc:
        if plan is None:
            plan = exc.plan
        if plan is None:
            raise
        result = _result(
            command=command,
            plan=plan,
            status="FAILED",
            error_code=exc.code,
            outcomes=(),
            outputs=(),
            started_at=started_at,
        )
    _write_exclusive(result_path, _canonical_json(result.model_dump(mode="json")))
    return result
