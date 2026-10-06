"""Raw-only TRAIN geometry comparison using the existing offline loader and GPU lease."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast, get_args

from eom_image_contracts import (
    LocalImageRuntime,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_evaluation_codec import (
    parse_sdxl_evaluation_command,
    parse_sdxl_evaluation_result,
)
from eom_image_contracts.sdxl_geometry_baseline_reuse import (
    LocalImageSdxlReusedGeometryCommand,
    parse_reused_geometry_baseline,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.sdxl_native_evaluation import (
    SdxlNativeEvaluationSources,
    parse_sdxl_native_evaluation_sources,
)
from eom_image_contracts.sdxl_native_geometry import (
    GeometryCanvas,
    LocalImageSdxlNativeGeometryCommand,
    LocalImageSdxlNativeGeometryResult,
    SdxlNativeGeometryNumerics,
    SdxlNativeGeometryOutput,
    geometry_dimensions,
    validate_sdxl_native_geometry_result,
    validate_sdxl_native_geometry_sources,
)
from jsonschema.exceptions import ValidationError as SchemaError
from PIL import Image

from eom_image_provider.provider import GeneratedBackground, ProviderError, acquire_gpu_lease
from eom_image_provider.sdxl_lineart_probe import MAX_PNG_BYTES
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial, load_sdxl_lora_material
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack, resolve_sdxl_stack
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    verify_staged_member,
    write_staged_member,
)

_ERRORS = frozenset(get_args(SdxlProbeErrorCode))


class SdxlGeometrySession(Protocol):
    def generate_geometry(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        canvas: GeometryCanvas,
        numerics: SdxlNativeGeometryNumerics,
    ) -> GeneratedBackground: ...


class SdxlGeometryBackend(Protocol):
    def open(
        self,
        stack: ResolvedSdxlStack,
        *,
        style_adapter: SdxlLoraAdapterMaterial | None = None,
    ) -> AbstractContextManager[SdxlGeometrySession]: ...


def validate_geometry_png(payload: bytes, canvas: GeometryCanvas) -> None:
    """Validate bounded PNG framing/CRC without a pixel decode or image transform."""
    try:
        if not 0 < len(payload) <= MAX_PNG_BYTES:
            raise ValueError("oversized PNG")
        with Image.open(io.BytesIO(payload)) as image:
            if (
                image.format != "PNG"
                or image.mode != "RGB"
                or image.size != geometry_dimensions(canvas)
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ValueError("geometry PNG header mismatch")
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def _read_sources(
    root: int, command: LocalImageSdxlNativeGeometryCommand
) -> SdxlNativeEvaluationSources:
    pin = command.evaluation
    payloads = {
        name: read_staged_member(
            root,
            "inputs/" + name + ".json",
            maximum_bytes=256 * 1024,
            expected_sha256=pointer.sha256,
        )
        for name, pointer in (
            ("baseline-command", pin.baseline_command),
            ("training-command", pin.training_command),
            ("training-result", pin.training_result),
            ("adapter-manifest", pin.adapter_manifest),
        )
    }
    sources = parse_sdxl_native_evaluation_sources(
        command,
        baseline_payload=payloads["baseline-command"],
        training_command_payload=payloads["training-command"],
        training_result_payload=payloads["training-result"],
        manifest_payload=payloads["adapter-manifest"],
    )
    validate_sdxl_native_geometry_sources(command, sources)
    if isinstance(command, LocalImageSdxlReusedGeometryCommand):
        payloads = {
            name: read_staged_member(
                root,
                "inputs/" + name + ".json",
                maximum_bytes=256 * 1024,
                expected_sha256=pointer.sha256,
            )
            for name, pointer in (
                ("reuse-command", command.baseline_reuse.prior_command),
                ("reuse-result", command.baseline_reuse.prior_result),
            )
        }
        parse_reused_geometry_baseline(
            command,
            sources,
            prior_command_payload=payloads["reuse-command"],
            prior_result_payload=payloads["reuse-result"],
        )
    return sources


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlNativeGeometryCommand,
    sources: SdxlNativeEvaluationSources,
) -> LocalImageSdxlNativeGeometryResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        return None
    try:
        raw = read_staged_member(root, "result.json", maximum_bytes=256 * 1024)
        value = json.loads(raw)
        result = parse_sdxl_evaluation_result(value)
        if not isinstance(result, LocalImageSdxlNativeGeometryResult):
            raise ValueError("geometry receipt family mismatch")
        validate_sdxl_native_geometry_result(command, sources, result)
        if raw != content_json_bytes(result.model_dump(mode="json")):
            raise ValueError("noncanonical geometry receipt")
        with (
            verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()),
            verified_directory(workspace / "outputs/raw", expected_owner_uid=os.geteuid()),
        ):
            if {p.name for p in (workspace / "outputs").iterdir()} != {"raw"}:
                raise ValueError("extra geometry directory")
            if {"outputs/raw/" + p.name for p in (workspace / "outputs/raw").iterdir()} != {
                output.member_path for output in result.outputs
            }:
                raise ValueError("extra/missing geometry output")
        for output in result.outputs:
            payload = read_staged_member(
                root,
                output.member_path,
                maximum_bytes=output.size_bytes,
                expected_sha256=output.sha256,
                expected_owner_uid=os.geteuid(),
            )
            if len(payload) != output.size_bytes:
                raise ValueError("geometry member size mismatch")
            validate_geometry_png(payload, output.canvas)
        return result
    except (ProviderError, ValueError, TypeError, OSError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def run_sdxl_native_geometry(
    *,
    command: LocalImageSdxlNativeGeometryCommand,
    model_store_root: Path,
    workspace: Path,
    gpu_lock: Path,
    backend: SdxlGeometryBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlNativeGeometryResult:
    try:
        parsed = parse_sdxl_evaluation_command(command.model_dump(mode="json"))
        if not isinstance(parsed, LocalImageSdxlNativeGeometryCommand):
            raise ValueError("geometry command family mismatch")
        command = parsed
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            sources = _read_sources(root, command)
            for file in sources.manifest.files:
                verify_staged_member(
                    root,
                    "inputs/adapter/" + file.relative_path,
                    size_bytes=file.size_bytes,
                    sha256=file.sha256,
                    expected_owner_uid=0,
                )
            existing = _replay(root, workspace, command, sources)
            if existing is not None:
                return existing
            material = load_sdxl_lora_material(
                root, sources.manifest, strength=command.evaluation.adapter_strength
            )
            create_staged_directory(root, "outputs")
            with verified_directory(
                workspace / "outputs", expected_owner_uid=os.geteuid()
            ) as outputs_root:
                create_staged_directory(outputs_root, "raw")
    except (ValueError, TypeError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc

    started, start = datetime.now(UTC), time.monotonic()
    outputs: list[SdxlNativeGeometryOutput] = []
    runtime: LocalImageRuntime | None = None
    error: SdxlProbeErrorCode | None = None
    calls = 0
    samples = {sample.sample_id: sample for sample in sources.training_command.training_samples}
    negative = sources.baseline.cases[0].negative_prompt_en
    try:
        stack = resolve_sdxl_stack(
            model_store_root, sources.baseline.model, expected_owner_uid=expected_model_owner_uid
        )
        with acquire_gpu_lease(gpu_lock):
            for arm in command.generated_arms():
                if (time.monotonic() - start) * 1000 >= command.budget.maximum_duration_ms:
                    raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
                with backend.open(
                    stack, style_adapter=material if arm == "LORA" else None
                ) as session:
                    for case in command.cases:
                        canvases: tuple[GeometryCanvas, ...] = (
                            "LEGACY_832X512",
                            case.native_canvas,
                        )
                        for canvas in canvases:
                            if (
                                time.monotonic() - start
                            ) * 1000 >= command.budget.maximum_duration_ms:
                                raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
                            call_start = time.monotonic()
                            calls += 1
                            generated = session.generate_geometry(
                                prompt=samples[case.sample_id].training_caption_en,
                                negative_prompt=negative,
                                canvas=canvas,
                                numerics=command.numerics,
                            )
                            current = LocalImageRuntime.model_validate_json(
                                generated.runtime.model_dump_json()
                            )
                            if (
                                runtime is None
                                or current.peak_gpu_memory_bytes > runtime.peak_gpu_memory_bytes
                            ):
                                runtime = current
                            if any(
                                getattr(current, name)
                                != getattr(sources.training_command.dependencies, name)
                                for name in (
                                    "python_version",
                                    "torch_version",
                                    "diffusers_version",
                                    "transformers_version",
                                )
                            ):
                                raise ProviderError("SDXL_PROBE_MODEL_INVALID")
                            if (
                                current.peak_gpu_memory_bytes
                                > command.budget.maximum_peak_gpu_memory_bytes
                                or (time.monotonic() - start) * 1000
                                > command.budget.maximum_duration_ms
                            ):
                                raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
                            validate_geometry_png(generated.png_bytes, canvas)
                            width, height = geometry_dimensions(canvas)
                            output = SdxlNativeGeometryOutput(
                                sample_id=case.sample_id,
                                arm=arm,
                                canvas=canvas,
                                width_px=width,
                                height_px=height,
                                prompt_sha256=case.training_caption_sha256,
                                negative_prompt_sha256=command.negative_prompt_sha256,
                                member_path=f"outputs/raw/{case.sample_id}-{canvas.lower()}-{arm.lower()}.png",
                                sha256="sha256:" + hashlib.sha256(generated.png_bytes).hexdigest(),
                                size_bytes=len(generated.png_bytes),
                                duration_ms=max(1, int((time.monotonic() - call_start) * 1000)),
                            )
                            with verified_directory(
                                workspace, expected_owner_uid=os.geteuid()
                            ) as root:
                                write_staged_member(root, output.member_path, generated.png_bytes)
                            outputs.append(output)
    except ProviderError as exc:
        error = (
            cast(SdxlProbeErrorCode, exc.code) if exc.code in _ERRORS else "SDXL_PROBE_EXEC_FAILED"
        )
    except Exception:
        error = "SDXL_PROBE_EXEC_FAILED"
    value = {
        "schema_version": command.schema_version.replace("-command/", "-result/"),
        "run_id": command.run_id,
        "command_sha256": command.command_sha256,
        "evaluation": command.evaluation.model_dump(mode="json"),
        "baseline_command_sha256": sources.baseline.command_sha256,
        "model": sources.baseline.model.model_dump(mode="json"),
        "case_relation": command.case_relation,
        "conditioning_policy": command.conditioning_policy,
        "numerics": command.numerics.model_dump(mode="json"),
        "status": "SUCCEEDED" if error is None else "FAILED",
        "error_code": error,
        "runtime": None if runtime is None else runtime.model_dump(mode="json"),
        "generation_calls": calls,
        "outputs": [o.model_dump(mode="json") for o in outputs],
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "duration_ms": max(1, int((time.monotonic() - start) * 1000)),
    }
    if isinstance(command, LocalImageSdxlReusedGeometryCommand):
        value["baseline_reuse"] = command.baseline_reuse.model_dump(mode="json")
    value["result_sha256"] = content_sha256(value)
    result = parse_sdxl_evaluation_result(value)
    if not isinstance(result, LocalImageSdxlNativeGeometryResult):
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
    validate_sdxl_native_geometry_result(command, sources, result)
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        write_staged_member(root, "result.json", content_json_bytes(value))
    return result
