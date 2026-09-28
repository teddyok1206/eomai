"""Validate and execute one bounded FLUX.2 reference probe workspace."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from eom_image_contracts import (
    Flux2ReferenceProbeMeasurement,
    Flux2ReferenceProbeOutput,
    Flux2ReferenceProbeRuntime,
    LocalImageFlux2ReferenceProbeCommand,
    LocalImageFlux2ReferenceProbePlan,
    LocalImageFlux2ReferenceProbeResult,
    LocalImageModelCandidateManifest,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_flux2_probe_command,
    validate_flux2_probe_result,
)
from PIL import Image, UnidentifiedImageError  # type: ignore[import-not-found]

from eom_image_candidate_runner.backend import Flux2BackendError

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PNG_BYTES = 16 * 1024 * 1024
MAX_MODEL_FILE_BYTES = 64 * 1024 * 1024 * 1024
MODEL_ROOT = Path("/opt/eom-evaluation-models/flux2-klein-base-4b")


class CandidateRunnerError(RuntimeError):
    """Stable error at the candidate-worker boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CandidateBackend(Protocol):
    def prepare(self, model_root: Path) -> Flux2ReferenceProbeRuntime: ...

    def generate(
        self,
        *,
        conditioning: Image.Image,
        prompt: str,
        seed: int,
        width: int,
        height: int,
        inference_steps: int,
        guidance_scale: float,
    ) -> tuple[Image.Image, int]: ...


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _safe_member(root: Path, member_path: str) -> Path:
    relative = PurePosixPath(member_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
    current = root
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
    return current


def _read_regular(path: Path, *, maximum_bytes: int) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
        ):
            raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
        return b"".join(chunks)
    except CandidateRunnerError:
        raise
    except OSError as exc:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parse_canonical_json(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID") from exc
    if not isinstance(value, dict) or content_json_bytes(value) != payload:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
    return value


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o600)
    except OSError as exc:
        raise CandidateRunnerError("FLUX2_PROBE_OUTPUT_INVALID") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_workspace(workspace: Path) -> None:
    try:
        metadata = workspace.lstat()
    except OSError as exc:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID") from exc
    if (
        not workspace.is_absolute()
        or workspace.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.geteuid()
    ):
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")


def load_probe_command(path: Path) -> LocalImageFlux2ReferenceProbeCommand:
    value = _parse_canonical_json(_read_regular(path, maximum_bytes=MAX_JSON_BYTES))
    try:
        validate_contract("flux2-reference-probe-command", value)
        return LocalImageFlux2ReferenceProbeCommand.model_validate(value)
    except Exception as exc:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID") from exc


def _load_plan_and_manifest(
    workspace: Path,
    command: LocalImageFlux2ReferenceProbeCommand,
) -> tuple[LocalImageFlux2ReferenceProbePlan, LocalImageModelCandidateManifest]:
    plan_payload = _read_regular(
        _safe_member(workspace, command.staged_plan_path), maximum_bytes=MAX_JSON_BYTES
    )
    manifest_payload = _read_regular(
        _safe_member(workspace, command.staged_model_manifest_path), maximum_bytes=MAX_JSON_BYTES
    )
    if _sha256(plan_payload) != command.plan.sha256:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_HASH_MISMATCH")
    try:
        plan_value = _parse_canonical_json(plan_payload)
        manifest_value = _parse_canonical_json(manifest_payload)
        validate_contract("flux2-reference-probe-plan", plan_value)
        validate_contract("model-candidate-manifest", manifest_value)
        plan = LocalImageFlux2ReferenceProbePlan.model_validate(plan_value)
        manifest = LocalImageModelCandidateManifest.model_validate(manifest_value)
        validate_flux2_probe_command(manifest, plan, command)
    except CandidateRunnerError:
        raise
    except Exception as exc:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID") from exc
    if _sha256(manifest_payload) != plan.candidate_model_manifest.sha256:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_HASH_MISMATCH")
    return plan, manifest


def _stream_file_sha256(path: Path, expected_size: int) -> str:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size != expected_size
            or not 0 < before.st_size <= MAX_MODEL_FILE_BYTES
        ):
            raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 4 * 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")
        return "sha256:" + digest.hexdigest()
    except CandidateRunnerError:
        raise
    except OSError as exc:
        raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _verify_model(model_root: Path, manifest: LocalImageModelCandidateManifest) -> None:
    if model_root != MODEL_ROOT:
        raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")
    try:
        root_metadata = model_root.lstat()
    except OSError as exc:
        raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID") from exc
    if model_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")
    actual_paths: set[str] = set()
    try:
        for path in model_root.rglob("*"):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")
            if stat.S_ISREG(metadata.st_mode):
                actual_paths.add(path.relative_to(model_root).as_posix())
            elif not stat.S_ISDIR(metadata.st_mode):
                raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")
    except OSError as exc:
        raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID") from exc
    if actual_paths != {member.relative_path for member in manifest.files}:
        raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")
    for member in manifest.files:
        try:
            path = _safe_member(model_root, member.relative_path)
        except CandidateRunnerError as exc:
            raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID") from exc
        if _stream_file_sha256(path, member.size_bytes) != member.sha256:
            raise CandidateRunnerError("FLUX2_PROBE_MODEL_INVALID")


def _decode_png(payload: bytes, *, expected_size: tuple[int, int]) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.format != "PNG" or image.size != expected_size:
                raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
            return image.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID") from exc


def _png_bytes(image: Image.Image) -> bytes:
    target = io.BytesIO()
    image.save(target, format="PNG", compress_level=9, optimize=False)
    return target.getvalue()


def _failed_result(
    *,
    command: LocalImageFlux2ReferenceProbeCommand,
    plan: LocalImageFlux2ReferenceProbePlan,
    manifest: LocalImageModelCandidateManifest,
    error_code: str,
    started_at: datetime,
) -> LocalImageFlux2ReferenceProbeResult:
    value: dict[str, object] = {
        "schema_version": "local-image-flux2-reference-probe-result/1.0",
        "run_id": command.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "command_sha256": command.command_sha256,
        "model_revision_id": manifest.model_revision_id,
        "activation_policy": "FORBIDDEN",
        "status": "FAILED",
        "error_code": error_code,
        "outputs": [],
        "measurements": [],
        "runtime": None,
        "started_at": _utc_text(started_at),
        "completed_at": _utc_text(datetime.now(UTC)),
    }
    value["result_sha256"] = content_sha256(value)
    return LocalImageFlux2ReferenceProbeResult.model_validate(value)


def run_probe(
    *,
    workspace: Path,
    command: LocalImageFlux2ReferenceProbeCommand,
    backend: CandidateBackend,
) -> LocalImageFlux2ReferenceProbeResult:
    """Run one exact command; output publication remains an Orchestrator responsibility."""

    _require_workspace(workspace)
    if workspace.name != command.run_id:
        raise CandidateRunnerError("FLUX2_PROBE_INPUT_INVALID")
    plan, manifest = _load_plan_and_manifest(workspace, command)
    _verify_model(Path(command.model_root), manifest)
    staged_inputs = {value.case_id: value for value in command.inputs}
    pending = workspace / "outputs.pending"
    final = workspace / command.output_directory
    if pending.exists() or pending.is_symlink() or final.exists() or final.is_symlink():
        raise CandidateRunnerError("FLUX2_PROBE_OUTPUT_INVALID")
    pending.mkdir(mode=0o700)
    started_at = datetime.now(UTC)
    try:
        runtime = backend.prepare(Path(command.model_root))
        outputs: list[Flux2ReferenceProbeOutput] = []
        measurements: list[Flux2ReferenceProbeMeasurement] = []
        for case in plan.cases:
            staged = staged_inputs[case.case_id]
            reference_payload = _read_regular(
                _safe_member(workspace, staged.relative_path), maximum_bytes=MAX_PNG_BYTES
            )
            conditioning_payload = _read_regular(
                _safe_member(workspace, staged.conditioning_relative_path),
                maximum_bytes=MAX_PNG_BYTES,
            )
            if (
                len(reference_payload) != staged.size_bytes
                or _sha256(reference_payload) != staged.sha256
                or len(conditioning_payload) != staged.conditioning_size_bytes
                or _sha256(conditioning_payload) != staged.conditioning_sha256
            ):
                raise CandidateRunnerError("FLUX2_PROBE_INPUT_HASH_MISMATCH")
            _decode_png(reference_payload, expected_size=(800, 504))
            conditioning = _decode_png(conditioning_payload, expected_size=(800, 504))
            started = time.monotonic_ns()
            generated, peak = backend.generate(
                conditioning=conditioning,
                prompt=case.prompt_en,
                seed=case.seed,
                width=plan.generation_width_px,
                height=plan.generation_height_px,
                inference_steps=plan.inference_steps,
                guidance_scale=plan.guidance_scale_milli / 1000,
            )
            if generated.size != (800, 512):
                raise CandidateRunnerError("FLUX2_PROBE_OUTPUT_INVALID")
            candidate_payload = _png_bytes(generated.convert("RGB").crop((0, 6, 800, 506)))
            candidate_name = f"{case.case_id}-candidate.png"
            conditioning_name = f"{case.case_id}-conditioning.png"
            _write_exclusive(pending / candidate_name, candidate_payload)
            _write_exclusive(pending / conditioning_name, conditioning_payload)
            outputs.extend(
                (
                    Flux2ReferenceProbeOutput(
                        case_id=case.case_id,
                        kind="CANDIDATE",
                        relative_path=f"outputs/{candidate_name}",
                        media_type="image/png",
                        size_bytes=len(candidate_payload),
                        sha256=_sha256(candidate_payload),
                        width_px=800,
                        height_px=500,
                    ),
                    Flux2ReferenceProbeOutput(
                        case_id=case.case_id,
                        kind="CONDITIONING",
                        relative_path=f"outputs/{conditioning_name}",
                        media_type="image/png",
                        size_bytes=len(conditioning_payload),
                        sha256=_sha256(conditioning_payload),
                        width_px=800,
                        height_px=504,
                    ),
                )
            )
            measurements.append(
                Flux2ReferenceProbeMeasurement(
                    case_id=case.case_id,
                    elapsed_milliseconds=max(1, (time.monotonic_ns() - started) // 1_000_000),
                    peak_gpu_memory_bytes=peak,
                )
            )
        outputs.sort(key=lambda value: (value.case_id, value.kind))
        measurements.sort(key=lambda value: value.case_id)
        result_value: dict[str, object] = {
            "schema_version": "local-image-flux2-reference-probe-result/1.0",
            "run_id": command.run_id,
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "command_sha256": command.command_sha256,
            "model_revision_id": manifest.model_revision_id,
            "activation_policy": "FORBIDDEN",
            "status": "SUCCEEDED",
            "error_code": None,
            "outputs": [value.model_dump(mode="json") for value in outputs],
            "measurements": [value.model_dump(mode="json") for value in measurements],
            "runtime": runtime.model_dump(mode="json"),
            "started_at": _utc_text(started_at),
            "completed_at": _utc_text(datetime.now(UTC)),
        }
        result_value["result_sha256"] = content_sha256(result_value)
        result = LocalImageFlux2ReferenceProbeResult.model_validate(result_value)
        validate_flux2_probe_result(plan, command, manifest, result)
        validate_contract("flux2-reference-probe-result", result.model_dump(mode="json"))
        _write_exclusive(
            pending / "result.json", content_json_bytes(result.model_dump(mode="json"))
        )
        pending.rename(final)
        return result
    except (CandidateRunnerError, Flux2BackendError) as exc:
        if pending.exists() and not pending.is_symlink():
            shutil.rmtree(pending)
        final.mkdir(mode=0o700)
        error_code = exc.code
        failed = _failed_result(
            command=command,
            plan=plan,
            manifest=manifest,
            error_code=error_code,
            started_at=started_at,
        )
        _write_exclusive(final / "result.json", content_json_bytes(failed.model_dump(mode="json")))
        return failed
