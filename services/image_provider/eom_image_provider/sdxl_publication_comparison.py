"""CPU-only publication candidates from pinned native outputs; no model or GPU path."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Protocol, cast, get_args

from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.sdxl_publication_comparison import (
    LocalImageSdxlPublicationComparisonCommand,
    LocalImageSdxlPublicationComparisonResult,
    PublicationErrorCode,
    SdxlPublicationOutput,
    SdxlPublicationSources,
    sdxl_publication_member,
    sdxl_publication_source_pointer,
    validate_sdxl_publication_result,
    validate_sdxl_publication_sources,
)
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    LocalImageSdxlTargetComparisonResult,
)
from eom_image_contracts.validation import validate_contract
from eom_image_contracts.visual_reference import (
    LocalImageAssessmentLineArtMetricsV2,
    LocalImageAssessmentLineArtPostprocessV2,
    LocalImageAssessmentLineArtRuntimeV2,
)
from jsonschema import ValidationError as SchemaError
from PIL import Image

from eom_image_provider.assessment_line_art import AssessmentLineArtResult, assessment_line_art_v2
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_target_source_io import read_sdxl_target_comparison_sources
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    read_staged_member,
    verified_directory,
    write_staged_member,
)

_ERRORS = frozenset(get_args(PublicationErrorCode))


class LineArtPostprocessor(Protocol):
    def __call__(
        self, payload: bytes, *, policy: LocalImageAssessmentLineArtPostprocessV2
    ) -> AssessmentLineArtResult: ...


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def publication_png_tones(payload: bytes, *, mode: str) -> tuple[int, ...]:
    """Bounded publication validation, not a transform or quality judgment."""
    with Image.open(io.BytesIO(payload)) as image:
        if (
            image.format != "PNG"
            or image.size != (800, 500)
            or image.mode != mode
            or getattr(image, "n_frames", 1) != 1
        ):
            raise ValueError("publication PNG media/dimensions/mode mismatch")
        image.load()
        gray = image.convert("L")
        if mode == "RGB" and gray.convert("RGB").tobytes() != image.tobytes():
            raise ValueError("publication PNG contains color")
        return tuple(sorted(set(gray.tobytes())))


def load_sdxl_publication_command(
    workspace: Path, command_path: Path
) -> LocalImageSdxlPublicationComparisonCommand:
    if command_path != workspace / "command.json":
        raise ProviderError("SDXL_PUBLICATION_INPUT_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(root, "command.json", maximum_bytes=128 * 1024)
        validate_contract("sdxl-publication-comparison-command", json.loads(raw))
        command = LocalImageSdxlPublicationComparisonCommand.model_validate_json(raw)
        if raw != content_json_bytes(command.model_dump(mode="json")):
            raise ValueError("noncanonical publication command")
        return command
    except (ValueError, TypeError, OSError, SchemaError, ProviderError) as exc:
        raise ProviderError("SDXL_PUBLICATION_INPUT_INVALID") from exc


def _sources(
    root: int, command: LocalImageSdxlPublicationComparisonCommand
) -> SdxlPublicationSources:
    raw_command = read_staged_member(
        root,
        "inputs/parent-command.json",
        maximum_bytes=256 * 1024,
        expected_sha256=command.source_command.sha256,
    )
    raw_result = read_staged_member(
        root,
        "inputs/parent-result.json",
        maximum_bytes=256 * 1024,
        expected_sha256=command.source_result.sha256,
    )
    parent_command = LocalImageSdxlTargetComparisonCommand.model_validate_json(raw_command)
    parent_result = LocalImageSdxlTargetComparisonResult.model_validate_json(raw_result)
    for kind, raw, parent in (
        ("command", raw_command, parent_command),
        ("result", raw_result, parent_result),
    ):
        validate_contract(f"sdxl-target-comparison-{kind}", parent.model_dump(mode="json"))
        if raw != content_json_bytes(parent.model_dump(mode="json")):
            raise ValueError("noncanonical publication source")
    lineage = read_sdxl_target_comparison_sources(root, parent_command)
    sources = SdxlPublicationSources(parent_command, parent_result, lineage)
    validate_sdxl_publication_sources(command, sources)
    return sources


def _replay(
    root: int,
    workspace: Path,
    command: LocalImageSdxlPublicationComparisonCommand,
    sources: SdxlPublicationSources,
) -> LocalImageSdxlPublicationComparisonResult | None:
    if not os.path.lexists(workspace / "result.json"):
        if os.path.lexists(workspace / "outputs"):
            raise ProviderError("SDXL_PUBLICATION_OUTPUT_INVALID")
        return None
    try:
        raw = read_staged_member(
            root, "result.json", maximum_bytes=128 * 1024, expected_owner_uid=os.geteuid()
        )
        validate_contract("sdxl-publication-comparison-result", json.loads(raw))
        result = LocalImageSdxlPublicationComparisonResult.model_validate_json(raw)
        validate_sdxl_publication_result(command, sources, result)
        if raw != content_json_bytes(result.model_dump(mode="json")):
            raise ValueError("noncanonical publication receipt")
        for output in result.outputs:
            pixels = read_staged_member(
                root,
                output.member_path,
                maximum_bytes=output.size_bytes,
                expected_sha256=output.sha256,
                expected_owner_uid=os.geteuid(),
            )
            if (
                len(pixels) != output.size_bytes
                or publication_png_tones(pixels, mode="RGB") != output.output_tones
            ):
                raise ValueError("publication output size/tones mismatch")
        expected_members: dict[str, set[str]] = {"BASE": set(), "LORA": set()}
        for output in result.outputs:
            expected_members[output.arm].add(output.member_path.rsplit("/", 1)[1])
        with verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()) as out:
            if set(os.listdir(out)) != {"base", "lora"}:
                raise ValueError("publication output contains unreceipted members")
        for arm, names in expected_members.items():
            with verified_directory(
                workspace / "outputs" / arm.lower(), expected_owner_uid=os.geteuid()
            ) as directory:
                if set(os.listdir(directory)) != names:
                    raise ValueError("publication output contains unreceipted members")
        return result
    except (ValueError, TypeError, OSError, SchemaError, ProviderError) as exc:
        raise ProviderError("SDXL_PUBLICATION_OUTPUT_INVALID") from exc


def run_sdxl_publication_comparison(
    *,
    command: LocalImageSdxlPublicationComparisonCommand,
    workspace: Path,
    postprocessor: LineArtPostprocessor = assessment_line_art_v2,
) -> LocalImageSdxlPublicationComparisonResult:
    try:
        command = LocalImageSdxlPublicationComparisonCommand.model_validate_json(
            command.model_dump_json()
        )
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            if load_sdxl_publication_command(workspace, workspace / "command.json") != command:
                raise ValueError("invoked publication command differs from staged command")
            sources = _sources(root, command)
            inputs = {}
            for native in sources.result.outputs:
                pixels = read_staged_member(
                    root,
                    sdxl_publication_member(native, staged=True),
                    maximum_bytes=native.size_bytes,
                    expected_sha256=native.sha256,
                )
                if len(pixels) != native.size_bytes:
                    raise ValueError("native publication source size mismatch")
                publication_png_tones(pixels, mode="L")
                inputs[(native.arm, native.case_id, native.seed)] = pixels
            replay = _replay(root, workspace, command, sources)
            if replay is not None:
                return replay
            runtime = LocalImageAssessmentLineArtRuntimeV2(
                pillow_version=metadata.version("Pillow")
            )
            if runtime.pillow_version != command.pillow_version:
                raise ValueError("publication Pillow runtime differs from pin")
            started_at, start = datetime.now(UTC), time.monotonic()
            create_staged_directory(root, "outputs")
            with verified_directory(workspace / "outputs", expected_owner_uid=os.geteuid()) as out:
                create_staged_directory(out, "base")
                create_staged_directory(out, "lora")
            produced = []
            error: PublicationErrorCode | None = None
            try:
                for source in sources.result.outputs:
                    if (time.monotonic() - start) * 1000 > command.budget.maximum_duration_ms:
                        raise ValueError("SDXL_PUBLICATION_BUDGET_EXCEEDED")
                    processed = postprocessor(
                        inputs[(source.arm, source.case_id, source.seed)],
                        policy=command.postprocess,
                    )
                    if processed.runtime != runtime:
                        raise ValueError("postprocessor runtime differs from pin")
                    if not isinstance(processed.metrics, LocalImageAssessmentLineArtMetricsV2):
                        raise ValueError("postprocessor metric contract differs from pin")
                    if (time.monotonic() - start) * 1000 > command.budget.maximum_duration_ms:
                        raise ValueError("SDXL_PUBLICATION_BUDGET_EXCEEDED")
                    processed.metrics.validate_policy(command.postprocess)
                    output = SdxlPublicationOutput.model_validate(
                        dict(
                            case_id=source.case_id,
                            arm=source.arm,
                            seed=source.seed,
                            source=sdxl_publication_source_pointer(command, source),
                            member_path=sdxl_publication_member(source, staged=False),
                            sha256=_sha(processed.png_bytes),
                            size_bytes=len(processed.png_bytes),
                            output_tones=publication_png_tones(processed.png_bytes, mode="RGB"),
                            metrics=processed.metrics,
                        )
                    )
                    write_staged_member(root, output.member_path, processed.png_bytes)
                    produced.append(output)
            except Exception as exc:
                error = (
                    cast(PublicationErrorCode, str(exc))
                    if str(exc) in _ERRORS
                    else "SDXL_PUBLICATION_EXEC_FAILED"
                )
            value = dict(
                schema_version="local-image-sdxl-publication-comparison-result/1.0",
                run_id=command.run_id,
                command_sha256=command.command_sha256,
                source_result_sha256=sources.result.result_sha256,
                policy_sha256=command.policy_sha256,
                status="SUCCEEDED" if error is None else "FAILED",
                error_code=error,
                case_relation=command.case_relation,
                quality_state="UNREVIEWED_PUBLICATION_CANDIDATES",
                activation_policy="FORBIDDEN",
                runtime=runtime.model_dump(mode="json"),
                outputs=[output.model_dump(mode="json") for output in produced],
                started_at=started_at.isoformat().replace("+00:00", "Z"),
                completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                duration_ms=max(1, int((time.monotonic() - start) * 1000)),
            )
            result = LocalImageSdxlPublicationComparisonResult.model_validate(
                {**value, "result_sha256": content_sha256(value)}
            )
            validate_sdxl_publication_result(command, sources, result)
            validate_contract("sdxl-publication-comparison-result", result.model_dump(mode="json"))
            write_staged_member(
                root, "result.json", content_json_bytes(result.model_dump(mode="json"))
            )
            return result
    except ProviderError as exc:
        if exc.code in {"SDXL_PUBLICATION_INPUT_INVALID", "SDXL_PUBLICATION_OUTPUT_INVALID"}:
            raise
        raise ProviderError("SDXL_PUBLICATION_INPUT_INVALID") from exc
    except (ValueError, TypeError, OSError, KeyError, SchemaError) as exc:
        raise ProviderError("SDXL_PUBLICATION_INPUT_INVALID") from exc
