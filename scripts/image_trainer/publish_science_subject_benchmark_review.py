#!/usr/bin/env python3
"""Publish one exact science-subject benchmark quality review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkResult,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
    content_json_bytes,
    validate_contract,
    validate_science_visual_subject_benchmark_review,
)
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_member,
)
from eom_orchestrator.database import build_engine
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.publication_io import PublicationFileReadError, read_regular_file
from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    _parse_json,
    _require_release,
    _write_exclusive,
)

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
REVIEW_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-review/1.0"
)


class ScienceSubjectBenchmarkReviewPublicationError(RuntimeError):
    """Stable operator-facing quality-review publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _typed[T: BaseModel](payload: bytes, *, contract: str, model: type[T]) -> T:
    try:
        value = _parse_json(payload)
        validate_contract(contract, value)
        parsed = model.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceSubjectBenchmarkReviewPublicationError(
            "SCIENCE_SUBJECT_BENCHMARK_REVIEW_INVALID"
        ) from exc
    if payload not in {
        content_json_bytes(parsed.model_dump(mode="json")),
        content_json_bytes(parsed.model_dump(mode="json")) + b"\n",
    }:
        raise ScienceSubjectBenchmarkReviewPublicationError(
            "SCIENCE_SUBJECT_BENCHMARK_REVIEW_INVALID"
        )
    return parsed


def _resolve(engine: Engine, pointer: ImageEvaluationArtifactMember) -> bytes:
    try:
        return resolve_control_artifact_member(
            engine,
            pointer,
            maximum_bytes=MAX_JSON_BYTES,
        )
    except ControlArtifactResolutionError as exc:
        raise ScienceSubjectBenchmarkReviewPublicationError(
            "SCIENCE_SUBJECT_BENCHMARK_REVIEW_POINTER_INVALID"
        ) from exc


def _write_receipt(path: Path, payload: bytes) -> None:
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        existing = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
        if existing != payload:
            raise ScienceSubjectBenchmarkReviewPublicationError(
                "SCIENCE_SUBJECT_BENCHMARK_REVIEW_RECEIPT_CONFLICT"
            )
        return
    _write_exclusive(path, payload, mode=0o600)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    try:
        review_payload = read_regular_file(args.review, maximum_bytes=MAX_JSON_BYTES)
    except PublicationFileReadError as exc:
        raise ScienceSubjectBenchmarkReviewPublicationError(
            "SCIENCE_SUBJECT_BENCHMARK_REVIEW_INVALID"
        ) from exc
    review = _typed(
        review_payload,
        contract="science-visual-subject-benchmark-review",
        model=LocalImageScienceVisualSubjectBenchmarkReview,
    )
    engine = build_engine()
    try:
        inventory = _typed(
            _resolve(engine, review.subject_inventory),
            contract="science-visual-subject-inventory",
            model=LocalImageScienceVisualSubjectInventory,
        )
        plan = _typed(
            _resolve(engine, review.benchmark_plan),
            contract="science-visual-subject-benchmark-plan",
            model=LocalImageScienceVisualSubjectBenchmarkPlan,
        )
        result = _typed(
            _resolve(engine, review.benchmark_result),
            contract="science-visual-subject-benchmark-result",
            model=LocalImageScienceVisualSubjectBenchmarkResult,
        )
        try:
            validate_science_visual_subject_benchmark_review(inventory, plan, result, review)
        except ValueError as exc:
            raise ScienceSubjectBenchmarkReviewPublicationError(
                "SCIENCE_SUBJECT_BENCHMARK_REVIEW_INVALID"
            ) from exc
        summary = {
            "review_id": review.review_id,
            "review_sha256": review.review_sha256,
            "subject_count": len(review.reviews),
        }
        if args.preflight_only:
            print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        published = ControlFileSetPublisher(engine, Settings.from_environment()).publish(
            members=(
                ControlFileSetMember(
                    file_name="manifests/science-visual-subject-benchmark-review.json",
                    source=args.review,
                    sha256=sha256_bytes(review_payload),
                    bytes=len(review_payload),
                    schema_ref=REVIEW_SCHEMA_REF,
                    media_type="application/json",
                ),
            ),
            primary_file="manifests/science-visual-subject-benchmark-review.json",
            artifact_type="control_local_image_science_subject_benchmark_review",
            manifest_version="local-image-science-subject-benchmark-review-files/1.0",
            idempotency_key=f"science-subject-benchmark-review:{review.review_sha256}",
            source_commit=args.source_commit,
            created_at=review.reviewed_at,
        )
    finally:
        engine.dispose()
    receipt = {
        "schema_version": "science-subject-benchmark-review-publication-receipt/1.0",
        **summary,
        "review_artifact": {
            "artifact_id": published.artifact_id,
            "artifact_revision_id": published.artifact_revision_id,
            "member_path": "manifests/science-visual-subject-benchmark-review.json",
            "schema_ref": REVIEW_SCHEMA_REF,
            "media_type": "application/json",
            "sha256": published.primary_sha256,
        },
        "file_set_manifest_sha256": published.manifest_sha256,
        "publication_source_commit": args.source_commit,
    }
    receipt_path = STATE_ROOT / f"science-subject-benchmark-review-{review.review_id}.json"
    _write_receipt(receipt_path, content_json_bytes(receipt))
    print(
        json.dumps({**summary, "receipt": str(receipt_path), "status": "PUBLISHED"}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
