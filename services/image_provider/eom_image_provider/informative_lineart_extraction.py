"""Bounded learned preprocessing with original-input admission and immutable replay receipts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast, get_args

from eom_image_contracts import (
    InformativeLineartExtractionOutput,
    InformativeLineartExtractionRuntime,
    LocalImageInformativeLineartExtractionCommand,
    LocalImageInformativeLineartExtractionResult,
    LocalImageInformativeLineartManifest,
    LocalImageSdxlLineartProbeCommand,
    content_json_bytes,
    content_sha256,
    select_informative_lineart_cases,
    validate_contract,
    validate_informative_lineart_extraction_result,
    validate_informative_lineart_pointer,
)
from eom_image_contracts.informative_lineart_extraction import ExtractionErrorCode
from jsonschema import ValidationError as JsonSchemaValidationError
from PIL import Image, ImageOps

from eom_image_provider.informative_lineart_resolution import (
    ResolvedInformativeLineartMaterial,
    resolve_informative_lineart_material,
)
from eom_image_provider.provider import ProviderError, acquire_gpu_lease
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)

MAX_PNG_BYTES = 16 * 1024**2
_ERRORS = frozenset(get_args(ExtractionErrorCode))


@dataclass(frozen=True, slots=True)
class ExtractedLineart:
    png_bytes: bytes
    peak_gpu_memory_bytes: int


class InformativeLineartSession(Protocol):
    runtime: InformativeLineartExtractionRuntime

    def extract(self, fitted_rgb_png: bytes) -> ExtractedLineart: ...


class InformativeLineartBackend(Protocol):
    def open(
        self, material: ResolvedInformativeLineartMaterial
    ) -> AbstractContextManager[InformativeLineartSession]: ...


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=9)
    return stream.getvalue()


def _error(exc: ProviderError) -> ExtractionErrorCode:
    if exc.code in _ERRORS:
        return cast(ExtractionErrorCode, exc.code)
    if exc.code.endswith("HASH_MISMATCH"):
        return "LINEART_EXTRACTION_HASH_MISMATCH"
    if exc.code.startswith("LINEART_EXTRACTOR_"):
        return "LINEART_EXTRACTION_MODEL_INVALID"
    if exc.code == "SDXL_PROBE_OUTPUT_INVALID":
        return "LINEART_EXTRACTION_OUTPUT_INVALID"
    if exc.code == "SDXL_PROBE_INPUT_INVALID":
        return "LINEART_EXTRACTION_INPUT_INVALID"
    return "LINEART_EXTRACTION_EXEC_FAILED"


def _document(
    root: int, member: str, schema: str, ceiling: int, sha: str | None = None
) -> dict[str, object]:
    raw = read_staged_member(root, member, maximum_bytes=ceiling, expected_sha256=sha)
    value = json.loads(raw)
    validate_contract(schema, value)
    if raw != content_json_bytes(value):
        raise ValueError("noncanonical extraction document")
    return cast(dict[str, object], value)


def load_informative_lineart_extraction_command(
    workspace: Path, command_path: Path
) -> LocalImageInformativeLineartExtractionCommand:
    if command_path != workspace / "command.json":
        raise ProviderError("LINEART_EXTRACTION_INPUT_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            value = _document(
                root, "command.json", "informative-lineart-extraction-command", 128 * 1024
            )
        return LocalImageInformativeLineartExtractionCommand.model_validate(value)
    except (ProviderError, ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise ProviderError("LINEART_EXTRACTION_INPUT_INVALID") from exc


def fitted_informative_lineart_input(payload: bytes, *, expected_size: tuple[int, int]) -> bytes:
    """Keep the baseline geometry; learning, not a raster threshold, extracts the contours."""
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if (
                source.format != "PNG"
                or source.size != expected_size
                or source.mode not in ("L", "RGB")
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ProviderError("LINEART_EXTRACTION_INPUT_INVALID")
            source.load()
            image = source.convert("RGB")
        fitted = ImageOps.contain(image, (800, 500), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (832, 512), "white")
        canvas.paste(fitted, ((832 - fitted.width) // 2, (512 - fitted.height) // 2))
        return _png(canvas)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("LINEART_EXTRACTION_INPUT_INVALID") from exc


def _decoded(payload: bytes, mode: str) -> Image.Image:
    try:
        if not 0 < len(payload) <= MAX_PNG_BYTES:
            raise ValueError("invalid PNG byte bound")
        with Image.open(io.BytesIO(payload)) as source:
            if (
                source.format != "PNG"
                or source.size != (832, 512)
                or source.mode != mode
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ValueError("invalid extracted PNG structure")
            source.load()
            return source.copy()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("LINEART_EXTRACTION_OUTPUT_INVALID") from exc


def _baseline(
    root: int, command: LocalImageInformativeLineartExtractionCommand
) -> LocalImageSdxlLineartProbeCommand:
    baseline = LocalImageSdxlLineartProbeCommand.model_validate(
        _document(
            root,
            "inputs/baseline-command.json",
            "sdxl-lineart-probe-command",
            128 * 1024,
            command.baseline_command.sha256,
        )
    )
    manifest = LocalImageInformativeLineartManifest.model_validate(
        _document(
            root,
            "inputs/extractor-manifest.json",
            "informative-lineart-manifest",
            64 * 1024,
            command.extractor_manifest.sha256,
        )
    )
    validate_informative_lineart_pointer(command.extractor, manifest)
    select_informative_lineart_cases(command, baseline)
    return baseline


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageInformativeLineartExtractionCommand,
    baseline: LocalImageSdxlLineartProbeCommand,
) -> LocalImageInformativeLineartExtractionResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("LINEART_EXTRACTION_OUTPUT_INVALID")
        return None
    try:
        result = LocalImageInformativeLineartExtractionResult.model_validate(
            _document(root, "result.json", "informative-lineart-extraction-result", 128 * 1024)
        )
        validate_informative_lineart_extraction_result(command, baseline, result)
        for output in result.outputs:
            raw = read_staged_member(
                root,
                output.lineart_member_path,
                maximum_bytes=output.lineart_size_bytes,
                expected_sha256=output.lineart_sha256,
            )
            conditioning = read_staged_member(
                root,
                output.conditioning_member_path,
                maximum_bytes=output.conditioning_size_bytes,
                expected_sha256=output.conditioning_sha256,
            )
            if (
                len(raw) != output.lineart_size_bytes
                or len(conditioning) != output.conditioning_size_bytes
            ):
                raise ValueError("extraction output size differs from receipt")
            image = _decoded(raw, "L")
            conditioned = _decoded(conditioning, "RGB")
            if conditioned.tobytes() != ImageOps.invert(image).convert("RGB").tobytes():
                raise ValueError("extraction conditioning is not the declared inversion")
        return result
    except (ProviderError, ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise ProviderError("LINEART_EXTRACTION_OUTPUT_INVALID") from exc


def run_informative_lineart_extraction(
    *,
    command: LocalImageInformativeLineartExtractionCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend: InformativeLineartBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageInformativeLineartExtractionResult:
    """Admit before model load; replay before GPU lease; never retry a partial execution."""
    try:
        command = LocalImageInformativeLineartExtractionCommand.model_validate_json(
            command.model_dump_json()
        )
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            # The staged command, not a caller's mutable object, is the invocation authority.
            if (
                load_informative_lineart_extraction_command(workspace, workspace / "command.json")
                != command
            ):
                raise ValueError("staged extraction command differs")
            baseline = _baseline(root, command)
            replay = _replay(root, workspace, command, baseline)
            if replay is not None:
                return replay
            started_at, start = datetime.now(UTC), time.monotonic()
            cases = select_informative_lineart_cases(command, baseline)
            inputs = {
                case.case_id: fitted_informative_lineart_input(
                    read_staged_member(
                        root,
                        case.staged_member_path,
                        maximum_bytes=MAX_PNG_BYTES,
                        expected_sha256=case.reference_image.sha256,
                    ),
                    expected_size=(case.reference_width_px, case.reference_height_px),
                )
                for case in cases
            }
            material = resolve_informative_lineart_material(
                model_store_root, command.extractor, expected_owner_uid=expected_model_owner_uid
            )
            create_staged_directory(root, "outputs")
            with verified_directory(
                workspace / "outputs", expected_owner_uid=os.geteuid()
            ) as outputs_root:
                create_staged_directory(outputs_root, "lineart")
                create_staged_directory(outputs_root, "conditioning")
            produced: list[InformativeLineartExtractionOutput] = []
            runtime = None
            peak = 0
            error: ExtractionErrorCode | None = None
            try:
                with acquire_gpu_lease(gpu_lock), backend.open(material) as session:
                    runtime = InformativeLineartExtractionRuntime.model_validate_json(
                        session.runtime.model_dump_json()
                    )
                    for case in cases:
                        if (time.monotonic() - start) * 1000 >= command.budget.maximum_duration_ms:
                            raise ProviderError("LINEART_EXTRACTION_BUDGET_EXCEEDED")
                        call_start = time.monotonic()
                        generated = session.extract(inputs[case.case_id])
                        if (
                            type(generated.peak_gpu_memory_bytes) is not int
                            or not 0 < generated.peak_gpu_memory_bytes <= 16 * 1024**3
                        ):
                            raise ProviderError("LINEART_EXTRACTION_OUTPUT_INVALID")
                        peak = max(peak, generated.peak_gpu_memory_bytes)
                        image = _decoded(generated.png_bytes, "L")
                        conditioning = _png(ImageOps.invert(image).convert("RGB"))
                        elapsed = max(1, int((time.monotonic() - start) * 1000))
                        if (
                            elapsed > command.budget.maximum_duration_ms
                            or peak > command.budget.maximum_peak_gpu_memory_bytes
                        ):
                            raise ProviderError("LINEART_EXTRACTION_BUDGET_EXCEEDED")
                        output = InformativeLineartExtractionOutput(
                            case_id=case.case_id,
                            reference_sha256=case.reference_image.sha256,
                            lineart_member_path=f"outputs/lineart/{case.case_id}.png",
                            lineart_sha256=_sha(generated.png_bytes),
                            lineart_size_bytes=len(generated.png_bytes),
                            conditioning_member_path=f"outputs/conditioning/{case.case_id}.png",
                            conditioning_sha256=_sha(conditioning),
                            conditioning_size_bytes=len(conditioning),
                            width_px=832,
                            height_px=512,
                            lineart_mode="L",
                            conditioning_mode="RGB",
                            duration_ms=max(1, int((time.monotonic() - call_start) * 1000)),
                            peak_gpu_memory_bytes=generated.peak_gpu_memory_bytes,
                        )
                        write_staged_member(root, output.lineart_member_path, generated.png_bytes)
                        write_staged_member(root, output.conditioning_member_path, conditioning)
                        produced.append(output)
            except ProviderError as exc:
                error = _error(exc)
            except Exception:
                error = "LINEART_EXTRACTION_EXEC_FAILED"
            value = {
                "schema_version": "local-image-informative-lineart-extraction-result/1.0",
                "run_id": command.run_id,
                "command_sha256": command.command_sha256,
                "extractor": command.extractor.model_dump(mode="json"),
                "preprocessing_policy": command.preprocessing_policy,
                "status": "SUCCEEDED" if error is None else "FAILED",
                "error_code": error,
                "runtime": runtime.model_dump(mode="json") if runtime is not None else None,
                "outputs": [output.model_dump(mode="json") for output in produced],
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "duration_ms": max(1, int((time.monotonic() - start) * 1000)),
                "peak_gpu_memory_bytes": peak,
            }
            value["result_sha256"] = content_sha256(value)
            validate_contract("informative-lineart-extraction-result", value)
            result = LocalImageInformativeLineartExtractionResult.model_validate(value)
            validate_informative_lineart_extraction_result(command, baseline, result)
            write_staged_member(root, "result.json", content_json_bytes(value))
            return result
    except ProviderError as exc:
        raise ProviderError(_error(exc)) from exc
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise ProviderError("LINEART_EXTRACTION_INPUT_INVALID") from exc
