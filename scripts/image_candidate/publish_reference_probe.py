#!/usr/bin/env python3
"""Validate and publish one completed FLUX.2 reference probe file set."""

from __future__ import annotations

import argparse
import json
import re
import struct
import zlib
from pathlib import Path, PurePosixPath

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageFlux2ReferenceProbeCommand,
    LocalImageFlux2ReferenceProbeCommandV2,
    LocalImageFlux2ReferenceProbePlan,
    LocalImageFlux2ReferenceProbePlanV2,
    LocalImageFlux2ReferenceProbeResult,
    LocalImageFlux2ReferenceProbeResultV2,
    LocalImageModelCandidateManifest,
    content_json_bytes,
    validate_contract,
    validate_flux2_probe_command,
    validate_flux2_probe_command_v2,
    validate_flux2_probe_result,
    validate_flux2_probe_result_v2,
)
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_candidate.stage_reference_probe import _require_release
from scripts.image_trainer.publication_io import PublicationFileReadError, read_regular_file

WORKSPACE_PARENT = Path("/tmp/eom-flux2-probe-completed")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PNG_BYTES = 16 * 1024 * 1024
RUN_ID = re.compile(r"^imgflux2proberun_[0-9a-f]{32}$")
RESULT_SCHEMA_REF = "eom://schemas/image-provider/local-image-flux2-reference-probe-result/1.0"
RESULT_V2_SCHEMA_REF = "eom://schemas/image-provider/local-image-flux2-reference-probe-result/1.1"
SOURCE_CROP_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-candidate-image/1.0"
)


class Flux2ProbePublicationError(RuntimeError):
    """Stable operator-facing publication error."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _workspace(run_id: str) -> Path:
    if RUN_ID.fullmatch(run_id) is None:
        raise Flux2ProbePublicationError("FLUX2_PROBE_RUN_INVALID")
    workspace = WORKSPACE_PARENT / run_id
    if workspace.is_symlink() or not workspace.is_dir():
        raise Flux2ProbePublicationError("FLUX2_PROBE_RUN_INVALID")
    return workspace


def _read_json(path: Path) -> tuple[bytes, dict[str, object]]:
    payload = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Flux2ProbePublicationError("FLUX2_PROBE_RESULT_INVALID") from exc
    if not isinstance(value, dict):
        raise Flux2ProbePublicationError("FLUX2_PROBE_RESULT_INVALID")
    return payload, value


def _load(
    workspace: Path,
) -> tuple[
    LocalImageFlux2ReferenceProbeCommand | LocalImageFlux2ReferenceProbeCommandV2,
    LocalImageFlux2ReferenceProbePlan | LocalImageFlux2ReferenceProbePlanV2,
    LocalImageModelCandidateManifest,
    LocalImageFlux2ReferenceProbeResult | LocalImageFlux2ReferenceProbeResultV2,
    bytes,
]:
    try:
        command_payload, command_value = _read_json(workspace / "command.json")
        plan_payload, plan_value = _read_json(workspace / "inputs" / "probe-plan.json")
        manifest_payload, manifest_value = _read_json(workspace / "inputs" / "model-manifest.json")
        result_payload, result_value = _read_json(workspace / "outputs" / "result.json")
        validate_contract("model-candidate-manifest", manifest_value)
        manifest = LocalImageModelCandidateManifest.model_validate(manifest_value)
        if command_value.get("schema_version") == "local-image-flux2-reference-probe-command/1.1":
            validate_contract("flux2-reference-probe-command-v2", command_value)
            validate_contract("flux2-reference-probe-plan-v2", plan_value)
            validate_contract("flux2-reference-probe-result-v2", result_value)
            command_v2 = LocalImageFlux2ReferenceProbeCommandV2.model_validate(command_value)
            plan_v2 = LocalImageFlux2ReferenceProbePlanV2.model_validate(plan_value)
            result_v2 = LocalImageFlux2ReferenceProbeResultV2.model_validate(result_value)
            validate_flux2_probe_command_v2(manifest, plan_v2, command_v2)
            validate_flux2_probe_result_v2(plan_v2, command_v2, manifest, result_v2)
            command: (
                LocalImageFlux2ReferenceProbeCommand | LocalImageFlux2ReferenceProbeCommandV2
            ) = command_v2
            plan: LocalImageFlux2ReferenceProbePlan | LocalImageFlux2ReferenceProbePlanV2 = plan_v2
            result: LocalImageFlux2ReferenceProbeResult | LocalImageFlux2ReferenceProbeResultV2 = (
                result_v2
            )
        else:
            validate_contract("flux2-reference-probe-command", command_value)
            validate_contract("flux2-reference-probe-plan", plan_value)
            validate_contract("flux2-reference-probe-result", result_value)
            command_v1 = LocalImageFlux2ReferenceProbeCommand.model_validate(command_value)
            plan_v1 = LocalImageFlux2ReferenceProbePlan.model_validate(plan_value)
            result_v1 = LocalImageFlux2ReferenceProbeResult.model_validate(result_value)
            validate_flux2_probe_command(manifest, plan_v1, command_v1)
            validate_flux2_probe_result(plan_v1, command_v1, manifest, result_v1)
            command = command_v1
            plan = plan_v1
            result = result_v1
    except (
        Flux2ProbePublicationError,
        PublicationFileReadError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise Flux2ProbePublicationError("FLUX2_PROBE_RESULT_INVALID") from exc
    if (
        command.run_id != workspace.name
        or result.status != "SUCCEEDED"
        or sha256_bytes(plan_payload) != command.plan.sha256
        or sha256_bytes(manifest_payload) != plan.candidate_model_manifest.sha256
        or content_json_bytes(command.model_dump(mode="json")) != command_payload
        or content_json_bytes(plan.model_dump(mode="json")) != plan_payload
        or content_json_bytes(manifest.model_dump(mode="json")) != manifest_payload
        or content_json_bytes(result.model_dump(mode="json")) != result_payload
    ):
        raise Flux2ProbePublicationError("FLUX2_PROBE_RESULT_INVALID")
    return command, plan, manifest, result, result_payload


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
    offset = 8
    dimensions: tuple[int, int] | None = None
    saw_end = False
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > MAX_PNG_BYTES or end > len(payload):
            raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
        chunk = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
            raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
            dimensions = struct.unpack(">II", chunk[:8])
        if chunk_type == b"IEND":
            if length != 0 or end != len(payload):
                raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
            saw_end = True
        offset = end
    if dimensions is None or not saw_end:
        raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
    return dimensions


def _validate_source_pointers(engine: Engine, plan: LocalImageFlux2ReferenceProbePlan) -> None:
    sessions = build_session_factory(engine)
    with sessions() as session:
        for case in plan.cases:
            pointer = case.source_crop
            artifact = session.get(ArtifactRecord, pointer.artifact_id)
            revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
            if (
                artifact is None
                or revision is None
                or not artifact.approved
                or not revision.approved
                or revision.logical_artifact_id != artifact.logical_artifact_id
            ):
                raise Flux2ProbePublicationError("FLUX2_PROBE_SOURCE_POINTER_INVALID")
            entries = tuple(
                entry
                for entry in revision.manifest.get("files", ())
                if entry.get("file_name") == pointer.member_path
            )
            if (
                len(entries) != 1
                or entries[0].get("sha256") != pointer.sha256
                or entries[0].get("schema_ref") != SOURCE_CROP_SCHEMA_REF
                or entries[0].get("media_type") != "image/png"
            ):
                raise Flux2ProbePublicationError("FLUX2_PROBE_SOURCE_POINTER_INVALID")


def _read_png(
    path: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    expected_dimensions: tuple[int, int],
    error_code: str,
) -> bytes:
    try:
        payload = read_regular_file(
            path,
            expected_sha256=expected_sha256,
            maximum_bytes=MAX_PNG_BYTES,
        )
    except PublicationFileReadError as exc:
        raise Flux2ProbePublicationError(error_code) from exc
    if len(payload) != expected_size or _png_dimensions(payload) != expected_dimensions:
        raise Flux2ProbePublicationError(error_code)
    return payload


def _members(
    workspace: Path,
    command: LocalImageFlux2ReferenceProbeCommand | LocalImageFlux2ReferenceProbeCommandV2,
    plan: LocalImageFlux2ReferenceProbePlan | LocalImageFlux2ReferenceProbePlanV2,
    result: LocalImageFlux2ReferenceProbeResult | LocalImageFlux2ReferenceProbeResultV2,
    result_payload: bytes,
) -> tuple[ControlFileSetMember, ...]:
    cases = {case.case_id: case for case in plan.cases}
    inputs = {value.case_id: value for value in command.inputs}
    for case_id, staged in inputs.items():
        case = cases[case_id]
        for relative_path, expected_sha, expected_size, expected_dimensions in (
            (
                staged.relative_path,
                staged.sha256,
                staged.size_bytes,
                (800, 504),
            ),
            (
                staged.conditioning_relative_path,
                staged.conditioning_sha256,
                staged.conditioning_size_bytes,
                (800, 504),
            ),
        ):
            _read_png(
                workspace / relative_path,
                expected_sha256=expected_sha,
                expected_size=expected_size,
                expected_dimensions=expected_dimensions,
                error_code="FLUX2_PROBE_INPUT_INVALID",
            )
        if case.conditioning.sha256 != staged.conditioning_sha256:
            raise Flux2ProbePublicationError("FLUX2_PROBE_INPUT_INVALID")

    declared_paths = {value.relative_path for value in result.outputs}
    output_root = workspace / "outputs"
    actual_paths = {
        path.relative_to(workspace).as_posix() for path in output_root.rglob("*") if path.is_file()
    }
    if actual_paths != declared_paths | {"outputs/result.json"}:
        raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
    result_schema_ref = (
        RESULT_V2_SCHEMA_REF
        if isinstance(result, LocalImageFlux2ReferenceProbeResultV2)
        else RESULT_SCHEMA_REF
    )
    members = [
        ControlFileSetMember(
            file_name="result.json",
            source=output_root / "result.json",
            sha256=sha256_bytes(result_payload),
            bytes=len(result_payload),
            schema_ref=result_schema_ref,
            media_type="application/json",
        )
    ]
    for output in result.outputs:
        relative = PurePosixPath(output.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID")
        _read_png(
            workspace.joinpath(*relative.parts),
            expected_sha256=output.sha256,
            expected_size=output.size_bytes,
            expected_dimensions=(output.width_px, output.height_px),
            error_code="FLUX2_PROBE_OUTPUT_INVALID",
        )
        members.append(
            ControlFileSetMember(
                file_name=output.relative_path.removeprefix("outputs/"),
                source=workspace.joinpath(*relative.parts),
                sha256=output.sha256,
                bytes=output.size_bytes,
                schema_ref=(
                    "eom://schemas/image-provider/"
                    "local-image-flux2-reference-probe-"
                    f"{output.kind.lower().replace('_', '-')}-image/1.0"
                ),
                media_type="image/png",
            )
        )
    return tuple(sorted(members, key=lambda value: value.file_name))


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    workspace = _workspace(args.run_id)
    command, plan, manifest, result, result_payload = _load(workspace)
    try:
        members = _members(workspace, command, plan, result, result_payload)
    except PublicationFileReadError as exc:
        raise Flux2ProbePublicationError("FLUX2_PROBE_OUTPUT_INVALID") from exc
    engine = build_engine()
    try:
        _validate_source_pointers(engine, plan)
        summary = {
            "activation_policy": result.activation_policy,
            "case_count": len(result.measurements),
            "generation_source_commit": command.source_commit,
            "model_revision_id": manifest.model_revision_id,
            "result_sha256": result.result_sha256,
            "run_id": result.run_id,
        }
        if args.preflight_only:
            print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        published = ControlFileSetPublisher(engine, Settings.from_environment()).publish(
            members=members,
            primary_file="result.json",
            artifact_type="control_local_image_flux2_reference_probe_result",
            manifest_version=(
                "local-image-flux2-reference-probe-result-files/1.1"
                if isinstance(result, LocalImageFlux2ReferenceProbeResultV2)
                else "local-image-flux2-reference-probe-result-files/1.0"
            ),
            idempotency_key=f"flux2-reference-probe-result:{result.run_id}",
            source_commit=args.source_commit,
            created_at=result.completed_at,
        )
    finally:
        engine.dispose()
    pointer = ImageEvaluationArtifactMember(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path="result.json",
        schema_ref=(
            RESULT_V2_SCHEMA_REF
            if isinstance(result, LocalImageFlux2ReferenceProbeResultV2)
            else RESULT_SCHEMA_REF
        ),
        media_type="application/json",
        sha256=published.primary_sha256,
    )
    print(
        json.dumps(
            {
                **summary,
                "file_set_manifest_sha256": published.manifest_sha256,
                "result_artifact": pointer.model_dump(mode="json"),
                "status": "PUBLISHED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
