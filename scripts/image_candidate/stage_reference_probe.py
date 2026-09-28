#!/usr/bin/env python3
"""Publish and stage one immutable three-case FLUX.2 evaluation probe."""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from eom_identifiers import sha256_file
from eom_image_contracts import (
    Flux2ReferenceProbeCase,
    Flux2ReferenceProbeInput,
    ImageEvaluationArtifactMember,
    LocalImageFlux2ReferenceProbeCommand,
    LocalImageFlux2ReferenceProbePlan,
    LocalImageModelCandidateManifest,
    LocalImageReferenceConditioningOutput,
    LocalImageReferenceSimplification,
    LocalImageReferenceSimplificationMetrics,
    LocalImageReferenceSimplifierRuntime,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_flux2_probe_command,
)
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine

from scripts.image_trainer.stage_crop_locator import _safe_read

MODEL_MANIFEST = Path("/opt/eom-evaluation-models/flux2-klein-base-4b.manifest.json")
FIXTURE_ROOT = Path("/tmp/eom-actual-science-crop-simplification-49e0e5f")
WORKSPACE_PARENT = Path("/tmp/eom-flux2-reference-probe")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RESULT_SHA256 = "sha256:41a6b7f15cc1a5540a23e1408c983df0ddfafe558494e8a0415f86fb89f3bbcf"
MODEL_SCHEMA_REF = "eom://schemas/image-provider/local-image-model-candidate-manifest/1.0"
PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-flux2-reference-probe-plan/1.0"
REFERENCE_SCHEMA_REF = "eom://schemas/image-provider/normalized-visual-reference/1.0"
SOURCE_CROP_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-candidate-image/1.0"
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PNG_BYTES = 16 * 1024 * 1024
SOURCE_PATTERN = re.compile(
    r"^/mnt/nas/eom/artifacts/"
    r"(?P<artifact>artifact_[0-9a-f]{32})/"
    r"(?P<revision>rev_[0-9a-f]{32})/"
    r"(?P<member>crops/imgsciviscandidate_[0-9a-f]{32}\.png)$"
)
CASES = {
    "car": ("AUTOMOBILE", "one compact automobile shown in side view", 2026092801),
    "plant": ("PLANT", "one simple flowering plant specimen", 2026092802),
    "fossil": ("FOSSIL", "one fossil specimen shown from above", 2026092803),
}
STYLE_PREFIX = (
    "Minimal black-and-white Korean science assessment line art. Preserve the exact reference "
    "composition, silhouette, part count, and viewpoint. Use a white background, uniform thin "
    "black contours, essential large internal lines only, sparse flat light gray, and generous "
    "blank space. Do not add text, labels, frames, scenery, shadows, color, people, or extra "
    "objects."
)


class Flux2ProbeStageError(RuntimeError):
    """Stable operator-facing error for candidate probe staging."""


def _require_release(source_commit: str) -> None:
    if os.geteuid() == 0:
        raise Flux2ProbeStageError("FLUX2_PROBE_STAGE_MUST_NOT_RUN_AS_ROOT")
    try:
        head = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise Flux2ProbeStageError("FLUX2_PROBE_SOURCE_RELEASE_INVALID") from exc
    if head != source_commit or dirty:
        raise Flux2ProbeStageError("FLUX2_PROBE_SOURCE_RELEASE_INVALID")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _read(path: Path, *, expected_sha256: str, maximum_bytes: int) -> bytes:
    return _safe_read(path, expected_sha256=expected_sha256, maximum_bytes=maximum_bytes)


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or payload[:8] != PNG_SIGNATURE or payload[12:16] != b"IHDR":
        raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
    return struct.unpack(">II", payload[16:24])


def _load_manifest() -> tuple[LocalImageModelCandidateManifest, bytes]:
    payload = _read(
        MODEL_MANIFEST,
        expected_sha256="sha256:ac80e54f565cb6d55cf5d1b77f2c21df28f22c34a6ba94b5f0af9371c818a089",
        maximum_bytes=MAX_JSON_BYTES,
    )
    try:
        value = json.loads(payload)
        validate_contract("model-candidate-manifest", value)
        manifest = LocalImageModelCandidateManifest.model_validate(value)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise Flux2ProbeStageError("FLUX2_PROBE_MODEL_MANIFEST_INVALID") from exc
    if payload != content_json_bytes(manifest.model_dump(mode="json")):
        raise Flux2ProbeStageError("FLUX2_PROBE_MODEL_MANIFEST_INVALID")
    return manifest, payload


def _load_fixture() -> tuple[dict[str, object], bytes]:
    path = FIXTURE_ROOT / "evaluation-result.json"
    payload = _read(path, expected_sha256=FIXTURE_RESULT_SHA256, maximum_bytes=MAX_JSON_BYTES)
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID") from exc
    if not isinstance(value, dict):
        raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
    body = {key: field for key, field in value.items() if key != "result_sha256"}
    if (
        value.get("schema_version") != "eom-actual-science-crop-simplification-evaluation/1.0"
        or value.get("classification") != "EVALUATION_ONLY"
        or value.get("activation") != "FORBIDDEN"
        or value.get("result_sha256") != content_sha256(body)
    ):
        raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
    return value, payload


def _source_pointer(
    engine: Engine,
    case: dict[str, object],
) -> ImageEvaluationArtifactMember:
    source_path = case.get("source_path")
    source_sha256 = case.get("source_sha256")
    if not isinstance(source_path, str) or not isinstance(source_sha256, str):
        raise Flux2ProbeStageError("FLUX2_PROBE_SOURCE_POINTER_INVALID")
    match = SOURCE_PATTERN.fullmatch(source_path)
    if match is None:
        raise Flux2ProbeStageError("FLUX2_PROBE_SOURCE_POINTER_INVALID")
    sessions = build_session_factory(engine)
    with sessions() as session:
        artifact = session.get(ArtifactRecord, match["artifact"])
        revision = session.get(ArtifactRevisionRecord, match["revision"])
        if (
            artifact is None
            or revision is None
            or not artifact.approved
            or not revision.approved
            or revision.logical_artifact_id != artifact.logical_artifact_id
        ):
            raise Flux2ProbeStageError("FLUX2_PROBE_SOURCE_POINTER_INVALID")
        entries = tuple(
            entry
            for entry in revision.manifest.get("files", ())
            if entry.get("file_name") == match["member"]
        )
        if len(entries) != 1:
            raise Flux2ProbeStageError("FLUX2_PROBE_SOURCE_POINTER_INVALID")
        entry = entries[0]
        if (
            entry.get("sha256") != source_sha256
            or entry.get("schema_ref") != SOURCE_CROP_SCHEMA_REF
            or entry.get("media_type") != "image/png"
        ):
            raise Flux2ProbeStageError("FLUX2_PROBE_SOURCE_POINTER_INVALID")
    return ImageEvaluationArtifactMember(
        artifact_id=match["artifact"],
        artifact_revision_id=match["revision"],
        member_path=match["member"],
        schema_ref=SOURCE_CROP_SCHEMA_REF,
        media_type="image/png",
        sha256=source_sha256,
    )


def _publish_member(
    publisher: ControlFileSetPublisher,
    *,
    source: Path,
    file_name: str,
    schema_ref: str,
    artifact_type: str,
    manifest_version: str,
    idempotency_key: str,
    source_commit: str,
    created_at: datetime,
) -> ImageEvaluationArtifactMember:
    digest = sha256_file(source)
    published = publisher.publish(
        members=(
            ControlFileSetMember(
                file_name=file_name,
                source=source,
                sha256=digest,
                bytes=source.stat().st_size,
                schema_ref=schema_ref,
                media_type="application/json" if file_name.endswith(".json") else "image/png",
            ),
        ),
        primary_file=file_name,
        artifact_type=artifact_type,
        manifest_version=manifest_version,
        idempotency_key=idempotency_key,
        source_commit=source_commit,
        created_at=created_at,
    )
    return ImageEvaluationArtifactMember(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path=file_name,
        schema_ref=schema_ref,
        media_type="application/json" if file_name.endswith(".json") else "image/png",
        sha256=published.primary_sha256,
    )


def _write_exclusive(path: Path, payload: bytes, *, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, mode)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    manifest, manifest_bytes = _load_manifest()
    fixture, _fixture_bytes = _load_fixture()
    raw_cases = fixture.get("cases")
    if not isinstance(raw_cases, list):
        raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
    indexed = {value.get("case_id"): value for value in raw_cases if isinstance(value, dict)}
    if not set(CASES).issubset(indexed):
        raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")

    engine = build_engine()
    if args.preflight_only:
        try:
            for key in CASES:
                raw = indexed[key]
                _source_pointer(engine, raw)
                normalized_sha = raw.get("normalized_sha256")
                conditioning_sha = raw.get("conditioning_sha256")
                metrics = raw.get("metrics")
                if (
                    not isinstance(normalized_sha, str)
                    or not isinstance(conditioning_sha, str)
                    or not isinstance(metrics, dict)
                ):
                    raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
                reference = _read(
                    FIXTURE_ROOT / f"{key}-normalized.png",
                    expected_sha256=normalized_sha,
                    maximum_bytes=MAX_PNG_BYTES,
                )
                conditioning = _read(
                    FIXTURE_ROOT / f"{key}-conditioning.png",
                    expected_sha256=conditioning_sha,
                    maximum_bytes=MAX_PNG_BYTES,
                )
                if _png_dimensions(reference) != (800, 504) or _png_dimensions(conditioning) != (
                    800,
                    504,
                ):
                    raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
                LocalImageReferenceSimplificationMetrics.model_validate(metrics)
        finally:
            engine.dispose()
        print(
            json.dumps(
                {
                    "status": "PREFLIGHT_PASS",
                    "model_revision_id": manifest.model_revision_id,
                    "case_count": len(CASES),
                    "activation_policy": manifest.activation_policy,
                },
                sort_keys=True,
            )
        )
        return 0
    publisher = ControlFileSetPublisher(engine, Settings.from_environment())
    try:
        model_pointer = _publish_member(
            publisher,
            source=MODEL_MANIFEST,
            file_name="manifests/model-candidate.json",
            schema_ref=MODEL_SCHEMA_REF,
            artifact_type="control_local_image_model_candidate",
            manifest_version="local-image-model-candidate-files/1.0",
            idempotency_key=f"image-model-candidate:{manifest.model_revision_id}",
            source_commit=args.source_commit,
            created_at=manifest.created_at,
        )
        cases: list[Flux2ReferenceProbeCase] = []
        staged: dict[str, tuple[bytes, bytes]] = {}
        for key, (subject_key, subject, seed) in CASES.items():
            raw = indexed[key]
            source_crop = _source_pointer(engine, raw)
            reference_path = FIXTURE_ROOT / f"{key}-normalized.png"
            conditioning_path = FIXTURE_ROOT / f"{key}-conditioning.png"
            normalized_sha = raw.get("normalized_sha256")
            conditioning_sha = raw.get("conditioning_sha256")
            if not isinstance(normalized_sha, str) or not isinstance(conditioning_sha, str):
                raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
            reference = _read(
                reference_path,
                expected_sha256=normalized_sha,
                maximum_bytes=MAX_PNG_BYTES,
            )
            conditioning = _read(
                conditioning_path,
                expected_sha256=conditioning_sha,
                maximum_bytes=MAX_PNG_BYTES,
            )
            if _png_dimensions(reference) != (800, 504) or _png_dimensions(conditioning) != (
                800,
                504,
            ):
                raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
            reference_pointer = _publish_member(
                publisher,
                source=reference_path,
                file_name="references/primary.png",
                schema_ref=REFERENCE_SCHEMA_REF,
                artifact_type="control_local_image_flux2_probe_reference",
                manifest_version="local-image-flux2-probe-reference-files/1.0",
                idempotency_key=f"flux2-probe-reference:{normalized_sha}",
                source_commit=args.source_commit,
                created_at=manifest.created_at,
            )
            metrics = raw.get("metrics")
            if not isinstance(metrics, dict):
                raise Flux2ProbeStageError("FLUX2_PROBE_FIXTURE_INVALID")
            prompt = f"{STYLE_PREFIX} Subject: {subject}."
            body = {
                "subject_key": subject_key,
                "source_crop": source_crop.model_dump(mode="json"),
                "visual_reference": {
                    **reference_pointer.model_dump(mode="json"),
                    "size_bytes": len(reference),
                },
                "conditioning": LocalImageReferenceConditioningOutput(
                    sha256=conditioning_sha,
                    size_bytes=len(conditioning),
                ).model_dump(mode="json"),
                "simplification_metrics": LocalImageReferenceSimplificationMetrics.model_validate(
                    metrics
                ).model_dump(mode="json"),
                "simplifier_runtime": LocalImageReferenceSimplifierRuntime(
                    pillow_version="11.3.0"
                ).model_dump(mode="json"),
                "prompt_en": prompt,
                "prompt_sha256": text_sha256(prompt),
                "seed": seed,
            }
            case = Flux2ReferenceProbeCase.model_validate(
                {
                    **body,
                    "case_id": "imgflux2case_" + content_sha256(body)[7:39],
                }
            )
            cases.append(case)
            staged[case.case_id] = (reference, conditioning)
        ordered_cases = tuple(sorted(cases, key=lambda value: value.case_id))
        plan_body = {
            "schema_version": "local-image-flux2-reference-probe-plan/1.0",
            "candidate_model_manifest": model_pointer.model_dump(mode="json"),
            "candidate_model_manifest_sha256": model_pointer.sha256,
            "activation_policy": "FORBIDDEN",
            "generation_width_px": 800,
            "generation_height_px": 512,
            "delivery_width_px": 800,
            "delivery_height_px": 500,
            "inference_steps": 50,
            "guidance_scale_milli": 4000,
            "dtype": "bfloat16",
            "cpu_offload": True,
            "simplification": LocalImageReferenceSimplification().model_dump(mode="json"),
            "cases": [value.model_dump(mode="json") for value in ordered_cases],
            "created_at": manifest.created_at.isoformat().replace("+00:00", "Z"),
            "created_by": "codex.flux2-probe",
        }
        identity_body = {
            key: field
            for key, field in plan_body.items()
            if key not in {"created_at", "created_by"}
        }
        plan_with_id = {
            **plan_body,
            "plan_id": "imgflux2probe_" + content_sha256(identity_body)[7:39],
        }
        plan = LocalImageFlux2ReferenceProbePlan.model_validate(
            {**plan_with_id, "plan_sha256": content_sha256(plan_with_id)}
        )
        plan_bytes = content_json_bytes(plan.model_dump(mode="json"))
        plan_temp = WORKSPACE_PARENT / f".{plan.plan_id}.json"
        WORKSPACE_PARENT.mkdir(mode=0o700, parents=True, exist_ok=True)
        if plan_temp.exists():
            if plan_temp.read_bytes() != plan_bytes:
                raise Flux2ProbeStageError("FLUX2_PROBE_PLAN_CONFLICT")
        else:
            _write_exclusive(plan_temp, plan_bytes, mode=0o600)
        plan_pointer = _publish_member(
            publisher,
            source=plan_temp,
            file_name="manifests/flux2-reference-probe-plan.json",
            schema_ref=PLAN_SCHEMA_REF,
            artifact_type="control_local_image_flux2_reference_probe_plan",
            manifest_version="local-image-flux2-reference-probe-plan-files/1.0",
            idempotency_key=f"flux2-reference-probe-plan:{plan.plan_id}",
            source_commit=args.source_commit,
            created_at=manifest.created_at,
        )
    finally:
        engine.dispose()

    inputs = tuple(
        Flux2ReferenceProbeInput(
            case_id=case.case_id,
            relative_path=f"inputs/references/{case.case_id}.png",
            sha256=case.visual_reference.sha256,
            size_bytes=case.visual_reference.size_bytes,
            conditioning_relative_path=(f"inputs/references/{case.case_id}-conditioning.png"),
            conditioning_sha256=case.conditioning.sha256,
            conditioning_size_bytes=case.conditioning.size_bytes,
        )
        for case in ordered_cases
    )
    command_body = {
        "schema_version": "local-image-flux2-reference-probe-command/1.0",
        "plan": plan_pointer.model_dump(mode="json"),
        "plan_sha256": plan_pointer.sha256,
        "staged_plan_path": "inputs/probe-plan.json",
        "staged_model_manifest_path": "inputs/model-manifest.json",
        "model_root": "/opt/eom-evaluation-models/flux2-klein-base-4b",
        "inputs": [value.model_dump(mode="json") for value in inputs],
        "output_directory": "outputs",
        "source_commit": args.source_commit,
        "timeout_seconds": 7200,
    }
    command_with_id = {
        **command_body,
        "run_id": "imgflux2proberun_" + content_sha256(command_body)[7:39],
    }
    command = LocalImageFlux2ReferenceProbeCommand.model_validate(
        {**command_with_id, "command_sha256": content_sha256(command_with_id)}
    )
    validate_flux2_probe_command(manifest, plan, command)
    summary = {
        "status": "STAGED",
        "run_id": command.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "command_sha256": command.command_sha256,
        "model_revision_id": manifest.model_revision_id,
        "case_count": len(ordered_cases),
    }
    workspace = WORKSPACE_PARENT / command.run_id
    if workspace.exists() or workspace.is_symlink():
        raise Flux2ProbeStageError("FLUX2_PROBE_WORKSPACE_CONFLICT")
    references = workspace / "inputs" / "references"
    references.mkdir(mode=0o700, parents=True)
    for path in (workspace, workspace / "inputs", references):
        path.chmod(0o700)
    _write_exclusive(
        workspace / "command.json", content_json_bytes(command.model_dump(mode="json")), mode=0o600
    )
    _write_exclusive(workspace / "inputs" / "probe-plan.json", plan_bytes, mode=0o600)
    _write_exclusive(workspace / "inputs" / "model-manifest.json", manifest_bytes, mode=0o600)
    for staged_input in inputs:
        reference, conditioning = staged[staged_input.case_id]
        _write_exclusive(workspace / staged_input.relative_path, reference, mode=0o600)
        _write_exclusive(
            workspace / staged_input.conditioning_relative_path,
            conditioning,
            mode=0o600,
        )
    print(json.dumps({**summary, "workspace": str(workspace)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
