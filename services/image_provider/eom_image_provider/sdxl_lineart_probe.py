"""Application boundary for bounded lineart diagnostics and immutable workspace receipts."""

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
    LocalImageRuntime,
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLineartProbeResult,
    LocalImageSdxlLineartPromptPolicy,
    SdxlLineartProbeConditioning,
    SdxlLineartProbeOutput,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_sdxl_lineart_probe_result,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from PIL import Image, ImageOps

from eom_image_provider.provider import GeneratedBackground, ProviderError
from eom_image_provider.sdxl_lora_material import SdxlLoraAdapterMaterial
from eom_image_provider.sdxl_model_resolution import ResolvedSdxlStack, resolve_sdxl_stack
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)

MAX_PNG_BYTES = 16 * 1024**2
_ERROR_CODES = frozenset(get_args(SdxlProbeErrorCode))


class SdxlProbeSession(Protocol):
    def generate(
        self,
        *,
        conditioning: bytes,
        prompt: str,
        negative_prompt: str,
        seed: int,
        command: LocalImageSdxlLineartProbeCommand,
    ) -> GeneratedBackground: ...


class SdxlProbeBackend(Protocol):
    def open(
        self, stack: ResolvedSdxlStack, *, style_adapter: SdxlLoraAdapterMaterial | None = None
    ) -> AbstractContextManager[SdxlProbeSession]: ...


@dataclass(frozen=True, slots=True)
class SdxlProbeEvidence:
    conditionings: tuple[SdxlLineartProbeConditioning, ...]
    outputs: tuple[SdxlLineartProbeOutput, ...]
    runtime: LocalImageRuntime | None
    error_code: SdxlProbeErrorCode | None
    started_at: datetime
    completed_at: datetime
    duration_ms: int


def _png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=9)
    return stream.getvalue()


def lineart_conditioning(payload: bytes, *, expected_size: tuple[int, int]) -> bytes:
    """Preserve aspect ratio and explicitly invert approved black-on-white contours."""
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if (
                source.format != "PNG"
                or source.size != expected_size
                or source.mode not in ("L", "RGB")
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            source.load()
            gray = source.convert("L")
        fitted = ImageOps.contain(gray, (800, 500), Image.Resampling.LANCZOS)
        canvas = Image.new("L", (832, 512), 255)
        canvas.paste(fitted, ((832 - fitted.width) // 2, (512 - fitted.height) // 2))
        return _png(ImageOps.invert(canvas).convert("RGB"))
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc


def _publication(raw: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format != "PNG" or source.size != (832, 512) or source.mode != "RGB":
                raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
            source.load()
            return _png(source.crop((16, 6, 816, 506)).convert("L"))
    except (OSError, ValueError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def load_sdxl_probe_command(
    workspace: Path, command_path: Path
) -> LocalImageSdxlLineartProbeCommand:
    if command_path != workspace / "command.json":
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as descriptor:
        raw = read_staged_member(descriptor, "command.json", maximum_bytes=128 * 1024)
    try:
        value = json.loads(raw)
        validate_contract("sdxl-lineart-probe-command", value)
        command = LocalImageSdxlLineartProbeCommand.model_validate(value)
        canonical = content_json_bytes(command.model_dump(mode="json"))
        if raw not in (canonical, canonical + b"\n"):
            raise ValueError("noncanonical command")
        return command
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlLineartProbeCommand,
) -> LocalImageSdxlLineartProbeResult | None:
    # A partial/unreceipted workspace is never a reason to invoke the model again.
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
        return None
    raw = read_staged_member(root, "result.json", maximum_bytes=256 * 1024)
    try:
        value = json.loads(raw)
        validate_contract("sdxl-lineart-probe-result", value)
        result = LocalImageSdxlLineartProbeResult.model_validate(value)
        validate_sdxl_lineart_probe_result(command, result)
        canonical = content_json_bytes(result.model_dump(mode="json"))
        if raw not in (canonical, canonical + b"\n"):
            raise ValueError("noncanonical result")
    except (ValueError, TypeError, JsonSchemaValidationError) as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc
    members = tuple((entry.member_path, entry.sha256) for entry in result.conditionings) + tuple(
        member
        for entry in result.outputs
        for member in ((entry.member_path, entry.sha256), (entry.raw_member_path, entry.raw_sha256))
    )
    for member, sha in members:
        read_staged_member(root, member, maximum_bytes=MAX_PNG_BYTES, expected_sha256=sha)
    return result


def generate_sdxl_probe_evidence(
    *,
    command: LocalImageSdxlLineartProbeCommand,
    model_store_root: Path,
    workspace: Path,
    backend: SdxlProbeBackend,
    expected_model_owner_uid: int = 0,
    style_adapter: SdxlLoraAdapterMaterial | None = None,
) -> SdxlProbeEvidence:
    started_at = datetime.now(UTC)
    start = time.monotonic()
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        create_staged_directory(root, "outputs")
        with verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()) as outputs:
            for name in ("conditioning", "raw", "final"):
                create_staged_directory(outputs, name)
        conditionings: list[SdxlLineartProbeConditioning] = []
        produced: list[SdxlLineartProbeOutput] = []
        error: SdxlProbeErrorCode | None = None
        runtime = None
        try:
            policy_raw = read_staged_member(
                root,
                "inputs/prompt-policy.json",
                maximum_bytes=256 * 1024,
                expected_sha256=command.prompt_policy.sha256,
            )
            try:
                policy_value = json.loads(policy_raw)
                validate_contract("sdxl-lineart-prompt-policy", policy_value)
                policy = LocalImageSdxlLineartPromptPolicy.model_validate(policy_value)
                if policy.cases != command.cases or policy_raw != content_json_bytes(
                    policy.model_dump(mode="json")
                ):
                    raise ValueError("compiled provenance differs from command")
            except (ValueError, TypeError, JsonSchemaValidationError) as exc:
                raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
            stack = resolve_sdxl_stack(
                model_store_root, command.model, expected_owner_uid=expected_model_owner_uid
            )
            # Validate all bounded staged inputs before loading any tensor or acquiring CUDA memory.
            inputs = {
                case.case_id: lineart_conditioning(
                    read_staged_member(
                        root,
                        case.staged_member_path,
                        maximum_bytes=MAX_PNG_BYTES,
                        expected_sha256=case.reference_image.sha256,
                    ),
                    expected_size=(case.reference_width_px, case.reference_height_px),
                )
                for case in command.cases
            }
            session = (
                backend.open(stack)
                if style_adapter is None
                else backend.open(stack, style_adapter=style_adapter)
            )
            with session as inference:
                for case in command.cases:
                    conditioning = inputs[case.case_id]
                    member = f"outputs/conditioning/{case.case_id}.png"
                    write_staged_member(root, member, conditioning)
                    conditionings.append(
                        SdxlLineartProbeConditioning(
                            case_id=case.case_id,
                            member_path=member,
                            sha256=_sha(conditioning),
                            width_px=832,
                            height_px=512,
                        )
                    )
                    for seed in case.seeds:
                        if (time.monotonic() - start) * 1000 >= command.budget.maximum_duration_ms:
                            raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
                        call_start = time.monotonic()
                        generated = inference.generate(
                            conditioning=conditioning,
                            prompt=case.prompt_en,
                            negative_prompt=case.negative_prompt_en,
                            seed=seed,
                            command=command,
                        )
                        publication = _publication(generated.png_bytes)
                        name = f"{case.case_id}-{seed:010d}.png"
                        raw_member, final_member = f"outputs/raw/{name}", f"outputs/final/{name}"
                        write_staged_member(root, raw_member, generated.png_bytes)
                        write_staged_member(root, final_member, publication)
                        produced.append(
                            SdxlLineartProbeOutput(
                                case_id=case.case_id,
                                seed=seed,
                                member_path=final_member,
                                sha256=_sha(publication),
                                raw_member_path=raw_member,
                                raw_sha256=_sha(generated.png_bytes),
                                width_px=800,
                                height_px=500,
                                duration_ms=max(1, int((time.monotonic() - call_start) * 1000)),
                                peak_gpu_memory_bytes=generated.runtime.peak_gpu_memory_bytes,
                            )
                        )
                        if (
                            runtime is None
                            or generated.runtime.peak_gpu_memory_bytes
                            > runtime.peak_gpu_memory_bytes
                        ):
                            runtime = generated.runtime
                        if (
                            generated.runtime.peak_gpu_memory_bytes
                            > command.budget.maximum_peak_gpu_memory_bytes
                            or (time.monotonic() - start) * 1000
                            > command.budget.maximum_duration_ms
                        ):
                            raise ProviderError("SDXL_PROBE_BUDGET_EXCEEDED")
        except ProviderError as exc:
            error = (
                cast(SdxlProbeErrorCode, exc.code)
                if exc.code in _ERROR_CODES
                else "SDXL_PROBE_EXEC_FAILED"
            )
        except Exception:
            error = "SDXL_PROBE_EXEC_FAILED"
        return SdxlProbeEvidence(
            tuple(conditionings),
            tuple(produced),
            runtime,
            error,
            started_at,
            datetime.now(UTC),
            max(1, int((time.monotonic() - start) * 1000)),
        )


def run_sdxl_lineart_probe(
    *,
    command: LocalImageSdxlLineartProbeCommand,
    model_store_root: Path,
    workspace: Path,
    backend: SdxlProbeBackend,
    expected_model_owner_uid: int = 0,
) -> LocalImageSdxlLineartProbeResult:
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        replay = _replay(root, workspace, command)
        if replay is not None:
            return replay
    evidence = generate_sdxl_probe_evidence(
        command=command,
        model_store_root=model_store_root,
        workspace=workspace,
        backend=backend,
        expected_model_owner_uid=expected_model_owner_uid,
    )
    with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
        value = {
            "schema_version": "local-image-sdxl-lineart-probe-result/1.0",
            "run_id": command.run_id,
            "command_sha256": command.command_sha256,
            "model": command.model.model_dump(mode="json"),
            "status": "SUCCEEDED" if evidence.error_code is None else "FAILED",
            "error_code": evidence.error_code,
            "runtime": None
            if evidence.runtime is None
            else evidence.runtime.model_dump(mode="json"),
            "conditionings": [entry.model_dump(mode="json") for entry in evidence.conditionings],
            "outputs": [entry.model_dump(mode="json") for entry in evidence.outputs],
            "started_at": evidence.started_at.isoformat().replace("+00:00", "Z"),
            "completed_at": evidence.completed_at.isoformat().replace("+00:00", "Z"),
            "duration_ms": evidence.duration_ms,
        }
        value["result_sha256"] = content_sha256(value)
        validate_contract("sdxl-lineart-probe-result", value)
        result = LocalImageSdxlLineartProbeResult.model_validate(value)
        validate_sdxl_lineart_probe_result(command, result)
        write_staged_member(root, "result.json", content_json_bytes(value))
        return result
