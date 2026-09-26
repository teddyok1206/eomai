from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotCommandV2,
    LocalImageScienceCorpusVisualPilotCommandV3,
    LocalImageScienceCorpusVisualPilotPlan,
    LocalImageScienceCorpusVisualPilotPlanV2,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceLoraMicroAdapterManifest,
    LocalImageScienceLoraMicroEvaluationCommand,
    LocalImageScienceLoraMicroEvaluationResult,
    LocalImageScienceLoraMicroProbeCommand,
    LocalImageScienceLoraMicroProbePlan,
    LocalImageScienceLoraMicroProbeWorkerResult,
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageScienceVisualCampaignReviewBatchCommand,
    LocalImageScienceVisualCampaignReviewBatchResult,
    LocalImageScienceVisualCropSet,
    LocalImageScienceVisualCropSetV2,
    LocalImageScienceVisualPatternInventory,
    LocalImageScienceVisualPatternInventoryV2,
    LocalImageScienceVisualRasterRefinementPlan,
    LocalImageScienceVisualRasterSuitabilityReview,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_science_micro_evaluation_command,
    validate_science_micro_evaluation_result,
    validate_science_micro_probe_plan_sources,
    validate_science_micro_probe_worker_result,
    validate_science_visual_authorization_plan,
    validate_science_visual_campaign_pattern_inventory,
    validate_science_visual_campaign_review_batch,
    validate_science_visual_crop_set,
    validate_science_visual_crop_set_v2,
    validate_science_visual_pattern_inventory,
    validate_science_visual_pattern_inventory_v2,
    validate_science_visual_pilot_command,
    validate_science_visual_pilot_result,
    validate_science_visual_raster_refinement_plan,
    validate_science_visual_raster_suitability_review,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from scripts.image_trainer import (
    publish_science_visual_campaign_pattern_inventory as campaign_publisher,
)
from scripts.image_trainer import (
    publish_science_visual_campaign_review_batch as batch_publisher,
)
from scripts.image_trainer import (
    stage_science_visual_campaign_review_batches as batch_stager,
)

ROOT = Path(__file__).resolve().parents[2]


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _pointer(
    character: str,
    *,
    member_path: str,
    schema_ref: str,
    media_type: str = "application/json",
    sha256: str | None = None,
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + character * 32,
        "artifact_revision_id": "rev_" + character * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": sha256 or _sha(character),
    }


def _corpus_pointer() -> dict[str, object]:
    return _pointer(
        "1",
        member_path="corpus-manifest.json",
        schema_ref=("eom://schemas/legacy-assessment/science-assessment-web-corpus-manifest/2.0"),
        sha256=_sha("2"),
    )


def _authorization_value() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-training-authorization/1.0",
        "revision_number": 1,
        "previous_revision_id": None,
        "corpus_manifest": _corpus_pointer(),
        "corpus_id": "sciencecorpus_" + "3" * 32,
        "corpus_manifest_sha256": _sha("4"),
        "acquisition_sha256": _sha("5"),
        "resolution_sha256": _sha("6"),
        "resolution_policy_id": "sciencecorpuspolicy_" + "7" * 32,
        "resolution_policy_sha256": _sha("8"),
        "authorization_basis": "USER_APPROVED_INTERNAL_EXAM_MATERIALS",
        "permitted_uses": [
            "DETERMINISTIC_PATTERN_ANALYSIS",
            "INTERNAL_SSD1B_LORA_TRAINING",
        ],
        "derivative_output": "LORA_ADAPTER_ONLY",
        "raw_source_export": "FORBIDDEN",
        "state": "APPROVED",
        "approved_at": "2026-09-25T18:15:00Z",
        "approved_by": "operator_user",
    }
    identity = content_sha256(
        {
            key: value
            for key, value in body.items()
            if key
            not in {
                "revision_number",
                "previous_revision_id",
                "approved_at",
                "approved_by",
            }
        }
    ).removeprefix("sha256:")
    body["authorization_id"] = "imgscicorpusauth_" + identity[:32]
    revision_identity = content_sha256(body).removeprefix("sha256:")
    body["authorization_revision_id"] = "imgscicorpusauthrev_" + revision_identity[:32]
    return {**body, "authorization_sha256": content_sha256(body)}


def _source(index: int, partition: str) -> dict[str, object]:
    digest = hashlib.sha256(f"science-document-{index}".encode()).hexdigest()
    subject = (
        "CHEMISTRY",
        "EARTH_SCIENCE",
        "GENERAL_SCIENCE",
        "INTEGRATED_SCIENCE",
        "LIFE_SCIENCE",
        "PHYSICS",
    )[index % 6]
    issuer = "KICE" if index % 2 else "EDUCATION_AUTHORITY"
    group = content_sha256(
        {
            "issuer_type": issuer,
            "administration_year": 2010 + index,
            "grade": 3,
            "session_label": f"SESSION_{index:02d}",
        }
    )
    return {
        "document_id": "sciencedoc_" + digest[:32],
        "source_file_id": "sourcefile_" + f"{index + 100:032x}",
        "pdf": _pointer(
            f"{index % 15 + 1:x}",
            member_path=f"source/{digest}.pdf",
            schema_ref="eom://schemas/content-intake/source-file/1.0",
            media_type="application/pdf",
            sha256="sha256:" + digest,
        ),
        "bytes": 2048 + index,
        "page_count": 1,
        "subject_family": subject,
        "issuer_type": issuer,
        "administration_year": 2010 + index,
        "grade": 3,
        "session_label": f"SESSION_{index:02d}",
        "exam_group_sha256": group,
        "partition": partition,
    }


def test_source_accepts_canonical_ingest_member_name_without_inventing_hash_path() -> None:
    value = _source(0, "TRAIN")
    pointer = dict(value["pdf"])
    pointer["member_path"] = "source/original-upload-name.pdf"
    value["pdf"] = pointer

    plan = _plan_value()
    selected_sources = [
        value if source["document_id"] == value["document_id"] else source
        for source in plan["selected_sources"]
    ]
    selected_sources.sort(key=lambda source: source["document_id"])
    plan["selected_sources"] = selected_sources
    plan.pop("pilot_id")
    plan.pop("plan_sha256")
    identity = content_sha256(plan).removeprefix("sha256:")
    plan["pilot_id"] = "imgscivispilot_" + identity[:32]
    plan["plan_sha256"] = content_sha256(plan)

    LocalImageScienceCorpusVisualPilotPlan.model_validate(plan)


def _plan_value() -> dict[str, object]:
    authorization = _authorization_value()
    sources = [
        _source(index, "TRAIN" if index < 6 else "VALIDATION" if index < 9 else "HOLDOUT")
        for index in range(12)
    ]
    sources.sort(key=lambda value: value["document_id"])
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-plan/1.0",
        "corpus_manifest": _corpus_pointer(),
        "corpus_id": authorization["corpus_id"],
        "corpus_manifest_sha256": authorization["corpus_manifest_sha256"],
        "acquisition_sha256": authorization["acquisition_sha256"],
        "resolution_sha256": authorization["resolution_sha256"],
        "resolution_policy_id": authorization["resolution_policy_id"],
        "resolution_policy_sha256": authorization["resolution_policy_sha256"],
        "training_authorization": _pointer(
            "9",
            member_path="manifests/science-corpus-training-authorization.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0"
            ),
            sha256=content_sha256(authorization),
        ),
        "selection_algorithm": "SCIENCE_VISUAL_STRATIFIED_SHA256_V1",
        "selection_seed_sha256": _sha("a"),
        "selected_sources": sources,
        "max_page_images": 12,
        "max_visual_candidates": 24,
        "max_lora_training_crops": 12,
        "page_render_dpi": 144,
        "locator_revision": "science-corpus-visual-locator/1.0",
        "guidance_authorities": [
            {
                "role": "AUTHORING_TEAM_LEAD",
                "logical_name": (
                    "config/control-plane/standard-item-v5/references/guidance/"
                    "content-team-integrated-science-authoring-v05.md"
                ),
                "source_commit": "b" * 40,
                "sha256": _sha("c"),
            },
            {
                "role": "HWPX_EDITOR_TEAM_LEAD",
                "logical_name": (
                    "config/control-plane/standard-item-v6/references/guidance/"
                    "content-team-hwp-question-editor-handoff-v1.md"
                ),
                "source_commit": "b" * 40,
                "sha256": _sha("d"),
            },
            {
                "role": "KICE_ILLUSTRATION_GUIDE",
                "logical_name": "content/image-specs/kice-integrated-science-illustration-v1.md",
                "source_commit": "b" * 40,
                "sha256": _sha("e"),
            },
        ],
        "tools": {
            "pdftoppm": {
                "path": "/usr/bin/pdftoppm",
                "sha256": _sha("1"),
                "version": "pdftoppm 24.02",
            },
            "tesseract": {
                "path": "/usr/bin/tesseract",
                "sha256": _sha("2"),
                "version": "tesseract 5.3",
            },
        },
        "created_at": "2026-09-25T18:20:00Z",
        "created_by": "operator_user",
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["pilot_id"] = "imgscivispilot_" + identity[:32]
    return {**body, "plan_sha256": content_sha256(body)}


def _plan_v2_value() -> dict[str, object]:
    value = copy.deepcopy(_plan_value())
    value["schema_version"] = "local-image-science-corpus-visual-pilot-plan/1.1"
    value["locator_revision"] = "science-corpus-visual-locator/1.1"
    value["locator_policy"] = {
        "max_candidates_per_page": 4,
        "max_candidates_per_source": 12,
        "maximum_redaction_area_milli": 450,
        "minimum_interior_ink_milli": 8,
        "maximum_border_ink_fraction_milli": 800,
        "minimum_aspect_ratio_milli": 125,
        "maximum_aspect_ratio_milli": 8000,
    }
    body = {key: item for key, item in value.items() if key not in {"pilot_id", "plan_sha256"}}
    identity = content_sha256(body).removeprefix("sha256:")
    value["pilot_id"] = "imgscivispilot_" + identity[:32]
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def _plan_v3_value() -> dict[str, object]:
    value = copy.deepcopy(_plan_v2_value())
    value["schema_version"] = "local-image-science-corpus-visual-pilot-plan/1.2"
    value["selection_algorithm"] = "SCIENCE_VISUAL_STRATIFIED_SHA256_V2_CAMPAIGN"
    value["campaign_shard_index"] = 1
    value["campaign_shard_count"] = 3
    campaign_identity = content_sha256(
        {
            "corpus_id": value["corpus_id"],
            "corpus_manifest_sha256": value["corpus_manifest_sha256"],
            "acquisition_sha256": value["acquisition_sha256"],
            "resolution_sha256": value["resolution_sha256"],
            "resolution_policy_id": value["resolution_policy_id"],
            "resolution_policy_sha256": value["resolution_policy_sha256"],
            "selection_seed_sha256": value["selection_seed_sha256"],
            "campaign_shard_count": value["campaign_shard_count"],
        }
    ).removeprefix("sha256:")
    value["campaign_id"] = "imgsciviscampaign_" + campaign_identity[:32]
    body = {key: item for key, item in value.items() if key not in {"pilot_id", "plan_sha256"}}
    value["pilot_id"] = "imgscivispilot_" + content_sha256(body).removeprefix("sha256:")[:32]
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def _candidate(document_id: str, page_hash: str, index: int) -> dict[str, object]:
    authority = (
        "AUTHORITATIVE_DETERMINISTIC_GEOMETRY" if index < 2 else "NON_AUTHORITATIVE_RASTER_STYLE"
    )
    body = {
        "document_id": document_id,
        "physical_page": 1,
        "page_image_sha256": page_hash,
        "bounding_box": {"left": 1000, "top": 1200, "right": 8000, "bottom": 7200},
        "representation_kind": "PLOT" if index < 2 else "PHOTOGRAPH",
        "rendering_mode": "VECTOR_LIKE" if index < 2 else "RASTER",
        "visual_features": ["AXES", "LABELS"] if index < 2 else [],
        "authority_class": authority,
        "review_state": "PENDING",
        "locator_score_milli": 800,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    candidate_id = "imgsciviscandidate_" + identity[:32]
    return {
        "candidate_id": candidate_id,
        **body,
        "member_path": f"crops/{candidate_id}.png",
        "sha256": "sha256:" + f"{index + 200:064x}",
        "size_bytes": 4096 + index,
    }


def _command_value() -> dict[str, object]:
    plan = _plan_value()
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-command/1.0",
        "plan": _pointer(
            "7",
            member_path="manifests/visual-pilot-plan.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.0"
            ),
        ),
        "plan_sha256": plan["plan_sha256"],
        "staged_plan_member": "input/visual-pilot-plan.json",
        "staged_sources": [
            {
                "document_id": source["document_id"],
                "staged_pdf_member": f"input/pdfs/{source['document_id']}.pdf",
                "sha256": source["pdf"]["sha256"],
                "bytes": source["bytes"],
                "page_count": source["page_count"],
            }
            for source in plan["selected_sources"]
        ],
        "result_member": "manifests/visual-pilot-result.json",
        "requested_at": "2026-09-25T18:25:00Z",
        "requested_by": "operator_user",
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["attempt_id"] = "imgscivisattempt_" + identity[:32]
    return {**body, "command_sha256": content_sha256(body)}


def _command_v2_value() -> dict[str, object]:
    plan = _plan_v2_value()
    value = copy.deepcopy(_command_value())
    value["schema_version"] = "local-image-science-corpus-visual-pilot-command/1.1"
    value["plan"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.1"
    )
    value["plan"]["sha256"] = plan["plan_sha256"]
    value["plan_sha256"] = plan["plan_sha256"]
    value["staged_sources"] = [
        {
            "document_id": source["document_id"],
            "staged_pdf_member": f"input/pdfs/{source['document_id']}.pdf",
            "sha256": source["pdf"]["sha256"],
            "bytes": source["bytes"],
            "page_count": source["page_count"],
        }
        for source in plan["selected_sources"]
    ]
    body = {key: item for key, item in value.items() if key not in {"attempt_id", "command_sha256"}}
    identity = content_sha256(body).removeprefix("sha256:")
    value["attempt_id"] = "imgscivisattempt_" + identity[:32]
    value["command_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "command_sha256"}
    )
    return value


def _command_v3_value() -> dict[str, object]:
    plan = _plan_v3_value()
    value = copy.deepcopy(_command_v2_value())
    value["schema_version"] = "local-image-science-corpus-visual-pilot-command/1.2"
    value["plan"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.2"
    )
    value["plan"]["sha256"] = plan["plan_sha256"]
    value["plan_sha256"] = plan["plan_sha256"]
    value["staged_sources"] = [
        {
            "document_id": source["document_id"],
            "staged_pdf_member": f"input/pdfs/{source['document_id']}.pdf",
            "sha256": source["pdf"]["sha256"],
            "bytes": source["bytes"],
            "page_count": source["page_count"],
        }
        for source in plan["selected_sources"]
    ]
    body = {key: item for key, item in value.items() if key not in {"attempt_id", "command_sha256"}}
    value["attempt_id"] = "imgscivisattempt_" + content_sha256(body).removeprefix("sha256:")[:32]
    value["command_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "command_sha256"}
    )
    return value


def _result_value() -> dict[str, object]:
    plan = _plan_value()
    pages = []
    candidates = []
    for index, source in enumerate(plan["selected_sources"]):
        page_hash = "sha256:" + f"{index + 300:064x}"
        document_id = str(source["document_id"])
        pages.append(
            {
                "document_id": document_id,
                "physical_page": 1,
                "member_path": f"pages/{document_id}/page-1.png",
                "sha256": page_hash,
                "size_bytes": 8192 + index,
                "width_px": 1191,
                "height_px": 1684,
            }
        )
        candidates.append(_candidate(document_id, page_hash, index))
    candidates.sort(key=lambda value: value["candidate_id"])
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-result/1.0",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": plan["plan_sha256"],
        "status": "SUCCEEDED",
        "page_images": pages,
        "visual_candidates": candidates,
        "omissions": [],
        "runtime": {
            "python_version": "3.11",
            "pillow_version": "11.3",
            "opencv_version": "4.11",
            "tesseract_version": "5.3",
            "pdftoppm_version": "24.02",
        },
        "error_code": None,
        "started_at": "2026-09-25T18:21:00Z",
        "completed_at": "2026-09-25T18:22:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _inventory_value() -> dict[str, object]:
    result = _result_value()
    reviews = []
    for index, candidate in enumerate(result["visual_candidates"]):
        if candidate["authority_class"] == "AUTHORITATIVE_DETERMINISTIC_GEOMETRY":
            decision = "DETERMINISTIC_RENDERER_ONLY"
            family = "PLOT"
            caption = None
        else:
            decision = "LORA_ELIGIBLE"
            family = "ORGANISM"
            caption = f"black and white science assessment organism illustration {index}"
        reviews.append(
            {
                "candidate_id": candidate["candidate_id"],
                "decision": decision,
                "pattern_family": family,
                "visual_features": candidate["visual_features"],
                "caption_en": caption,
                "caption_sha256": None if caption is None else text_sha256(caption),
                "reviewed_by": "reviewer_user",
                "reviewed_at": "2026-09-25T18:25:00Z",
            }
        )
    reviews.sort(key=lambda value: value["candidate_id"])
    result_sha = str(result["result_sha256"])
    body: dict[str, object] = {
        "schema_version": "local-image-science-visual-pattern-inventory/1.0",
        "pilot_result": _pointer(
            "f",
            member_path="manifests/visual-pilot-result.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0"
            ),
            sha256=result_sha,
        ),
        "pilot_result_sha256": result_sha,
        "reviews": reviews,
        "primitive_recommendations": [
            {
                "primitive_key": "AXIS_PLOT",
                "support_count": 2,
                "visual_features": ["AXES", "LABELS"],
                "geometry_authority": "AUTHORITATIVE",
                "render_route": "PYTHON_SVG",
            }
        ],
        "lora_eligible_count": 10,
        "deterministic_renderer_count": 2,
        "excluded_count": 0,
        "created_at": "2026-09-25T18:26:00Z",
        "created_by": "reviewer_user",
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["inventory_id"] = "imgscivisinventory_" + identity[:32]
    return {**body, "inventory_sha256": content_sha256(body)}


def _inventory_v2_value() -> dict[str, object]:
    result = _result_value()
    value = copy.deepcopy(_inventory_value())
    value["schema_version"] = "local-image-science-visual-pattern-inventory/1.1"
    value.pop("pilot_result_sha256")
    result_file_sha256 = _sha("9")
    value["pilot_result"]["sha256"] = result_file_sha256
    value["pilot_result_file_sha256"] = result_file_sha256
    value["pilot_result_semantic_sha256"] = result["result_sha256"]
    body = {
        key: item for key, item in value.items() if key not in {"inventory_id", "inventory_sha256"}
    }
    identity = content_sha256(body).removeprefix("sha256:")
    value["inventory_id"] = "imgscivisinventory_" + identity[:32]
    value["inventory_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "inventory_sha256"}
    )
    return value


def _campaign_plan_result_value(shard_index: int) -> tuple[dict[str, object], dict[str, object]]:
    """Three disjoint V1.2 fixture shards with their own source/result identities."""

    plan = copy.deepcopy(_plan_v3_value())
    plan["campaign_shard_index"] = shard_index
    plan["selected_sources"] = sorted(
        [
            _source(
                shard_index * 12 + index,
                "TRAIN" if index < 6 else "VALIDATION" if index < 9 else "HOLDOUT",
            )
            for index in range(12)
        ],
        key=lambda value: value["document_id"],
    )
    plan_body = {
        key: value for key, value in plan.items() if key not in {"pilot_id", "plan_sha256"}
    }
    plan["pilot_id"] = "imgscivispilot_" + content_sha256(plan_body).removeprefix("sha256:")[:32]
    plan["plan_sha256"] = content_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )

    pages: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for index, source in enumerate(plan["selected_sources"]):
        page_hash = "sha256:" + f"{shard_index * 100 + index + 900:064x}"
        document_id = str(source["document_id"])
        pages.append(
            {
                "document_id": document_id,
                "physical_page": 1,
                "member_path": f"pages/{document_id}/page-1.png",
                "sha256": page_hash,
                "size_bytes": 8192 + index,
                "width_px": 1191,
                "height_px": 1684,
            }
        )
        candidates.append(_candidate(document_id, page_hash, index))
    candidates.sort(key=lambda value: value["candidate_id"])
    result_body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-result/1.0",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": plan["plan_sha256"],
        "status": "SUCCEEDED",
        "page_images": pages,
        "visual_candidates": candidates,
        "omissions": [],
        "runtime": {
            "python_version": "3.11",
            "pillow_version": "11.3",
            "opencv_version": "4.11",
            "tesseract_version": "5.3",
            "pdftoppm_version": "24.02",
        },
        "error_code": None,
        "started_at": "2026-09-26T12:00:00Z",
        "completed_at": "2026-09-26T12:01:00Z",
    }
    return plan, {**result_body, "result_sha256": content_sha256(result_body)}


def _campaign_inventory_value() -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    plans: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    plan_pointers: list[dict[str, object]] = []
    result_pointers: list[dict[str, object]] = []
    pilots: list[dict[str, object]] = []
    reviews: list[dict[str, object]] = []
    for shard_index in range(3):
        plan, result = _campaign_plan_result_value(shard_index)
        plan_pointer = _pointer(
            f"{shard_index + 1:x}",
            member_path="manifests/visual-pilot-plan.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.2"
            ),
            sha256=_sha(f"{shard_index + 1:x}"),
        )
        result_pointer = _pointer(
            f"{shard_index + 7:x}",
            member_path="manifests/visual-pilot-result.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0"
            ),
            sha256=_sha(f"{shard_index + 7:x}"),
        )
        pilots.append(
            {
                "attempt_id": "imgscivisattempt_" + f"{shard_index + 1:032x}",
                "campaign_shard_index": shard_index,
                "campaign_shard_count": 3,
                "pilot_plan": plan_pointer,
                "pilot_plan_file_sha256": plan_pointer["sha256"],
                "pilot_plan_semantic_sha256": plan["plan_sha256"],
                "pilot_result": result_pointer,
                "pilot_result_file_sha256": result_pointer["sha256"],
                "pilot_result_semantic_sha256": result["result_sha256"],
            }
        )
        for candidate in result["visual_candidates"]:
            if candidate["authority_class"] == "AUTHORITATIVE_DETERMINISTIC_GEOMETRY":
                decision, family, caption = "DETERMINISTIC_RENDERER_ONLY", "PLOT", None
            else:
                decision = "LORA_ELIGIBLE"
                family = "ORGANISM"
                caption = "black and white science assessment organism illustration"
            reviews.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "decision": decision,
                    "pattern_family": family,
                    "visual_features": candidate["visual_features"],
                    "caption_en": caption,
                    "caption_sha256": None if caption is None else text_sha256(caption),
                    "reviewed_by": "reviewer_user",
                    "reviewed_at": "2026-09-26T12:02:00Z",
                }
            )
        plans.append(plan)
        results.append(result)
        plan_pointers.append(plan_pointer)
        result_pointers.append(result_pointer)
    reviews.sort(key=lambda value: value["candidate_id"])
    body: dict[str, object] = {
        "schema_version": "local-image-science-visual-campaign-pattern-inventory/1.0",
        "campaign_id": plans[0]["campaign_id"],
        "pilot_results": pilots,
        "reviews": reviews,
        "primitive_recommendations": [
            {
                "primitive_key": "AXIS_PLOT",
                "support_count": 6,
                "visual_features": ["AXES", "LABELS"],
                "geometry_authority": "AUTHORITATIVE",
                "render_route": "PYTHON_SVG",
            }
        ],
        "lora_eligible_count": 30,
        "deterministic_renderer_count": 6,
        "excluded_count": 0,
        "created_at": "2026-09-26T12:03:00Z",
        "created_by": "reviewer_user",
    }
    body["inventory_id"] = (
        "imgsciviscampaigninventory_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    return (
        {**body, "inventory_sha256": content_sha256(body)},
        plans,
        results,
        plan_pointers,
        result_pointers,
    )


def test_campaign_pattern_inventory_binds_complete_disjoint_campaign() -> None:
    value, plan_values, result_values, plan_pointer_values, result_pointer_values = (
        _campaign_inventory_value()
    )
    validate_contract("science-visual-campaign-pattern-inventory", value)
    inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(value)
    validate_science_visual_campaign_pattern_inventory(
        plans=tuple(
            LocalImageScienceCorpusVisualPilotPlanV3.model_validate(plan) for plan in plan_values
        ),
        plan_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(pointer) for pointer in plan_pointer_values
        ),
        results=tuple(
            LocalImageScienceCorpusVisualPilotResult.model_validate(result)
            for result in result_values
        ),
        result_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(pointer)
            for pointer in result_pointer_values
        ),
        inventory=inventory,
    )


def test_campaign_pattern_inventory_rejects_missing_candidate_review() -> None:
    value, _, _, _, _ = _campaign_inventory_value()
    reviews = value["reviews"]
    assert isinstance(reviews, list)
    removed = reviews.pop()
    assert isinstance(removed, dict)
    decision = str(removed["decision"])
    count_key = {
        "LORA_ELIGIBLE": "lora_eligible_count",
        "DETERMINISTIC_RENDERER_ONLY": "deterministic_renderer_count",
        "EXCLUDED": "excluded_count",
    }[decision]
    value[count_key] = int(value[count_key]) - 1
    body = {
        key: item for key, item in value.items() if key not in {"inventory_id", "inventory_sha256"}
    }
    value["inventory_id"] = (
        "imgsciviscampaigninventory_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    value["inventory_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "inventory_sha256"}
    )
    inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(value)
    _, plan_values, result_values, plan_pointer_values, result_pointer_values = (
        _campaign_inventory_value()
    )
    with pytest.raises(ValueError, match="does not review every candidate"):
        validate_science_visual_campaign_pattern_inventory(
            plans=tuple(
                LocalImageScienceCorpusVisualPilotPlanV3.model_validate(plan)
                for plan in plan_values
            ),
            plan_pointers=tuple(
                ImageEvaluationArtifactMember.model_validate(pointer)
                for pointer in plan_pointer_values
            ),
            results=tuple(
                LocalImageScienceCorpusVisualPilotResult.model_validate(result)
                for result in result_values
            ),
            result_pointers=tuple(
                ImageEvaluationArtifactMember.model_validate(pointer)
                for pointer in result_pointer_values
            ),
            inventory=inventory,
        )


def _campaign_review_batch_values() -> tuple[
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    inventory, plans, results, plan_pointers, result_pointers = _campaign_inventory_value()
    reviews = inventory["reviews"]
    pilots = inventory["pilot_results"]
    assert isinstance(reviews, list)
    assert isinstance(pilots, list)
    selected = copy.deepcopy(reviews[:12])
    candidate_ids = [str(value["candidate_id"]) for value in selected]
    command_body: dict[str, object] = {
        "schema_version": "local-image-science-visual-campaign-review-batch-command/1.0",
        "campaign_id": inventory["campaign_id"],
        "pilot_results": copy.deepcopy(pilots),
        "candidate_ids": candidate_ids,
        "created_at": "2026-09-26T12:04:00Z",
        "created_by": "reviewer_user",
    }
    command_body["batch_id"] = (
        "imgscivisreviewbatch_" + content_sha256(command_body).removeprefix("sha256:")[:32]
    )
    command = {**command_body, "command_sha256": content_sha256(command_body)}
    command_pointer = _pointer(
        "f",
        member_path="manifests/science-visual-campaign-review-batch-command.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-campaign-review-batch-command/1.0"
        ),
    )
    result_body: dict[str, object] = {
        "schema_version": "local-image-science-visual-campaign-review-batch-result/1.0",
        "batch_id": command["batch_id"],
        "review_batch": command_pointer,
        "command_sha256": command["command_sha256"],
        "reviews": selected,
        "completed_at": "2026-09-26T12:05:00Z",
        "completed_by": "reviewer_user",
    }
    return (
        command,
        {**result_body, "result_sha256": content_sha256(result_body)},
        plans,
        results,
        plan_pointers,
        result_pointers,
    )


def test_campaign_review_batch_binds_exact_candidate_subset() -> None:
    command_value, result_value, plans, results, plan_pointers, result_pointers = (
        _campaign_review_batch_values()
    )
    validate_contract("science-visual-campaign-review-batch-command", command_value)
    validate_contract("science-visual-campaign-review-batch-result", result_value)
    command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(command_value)
    result = LocalImageScienceVisualCampaignReviewBatchResult.model_validate(result_value)
    validate_science_visual_campaign_review_batch(
        command=command,
        command_pointer=result.review_batch,
        plans=tuple(
            LocalImageScienceCorpusVisualPilotPlanV3.model_validate(value) for value in plans
        ),
        plan_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(value) for value in plan_pointers
        ),
        results=tuple(
            LocalImageScienceCorpusVisualPilotResult.model_validate(value) for value in results
        ),
        result_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(value) for value in result_pointers
        ),
        review_result=result,
    )


def test_campaign_review_batch_rejects_extra_candidate() -> None:
    command_value, result_value, plans, results, plan_pointers, result_pointers = (
        _campaign_review_batch_values()
    )
    reviews = result_value["reviews"]
    assert isinstance(reviews, list)
    reviews[-1]["candidate_id"] = "imgsciviscandidate_" + "f" * 32
    reviews.sort(key=lambda value: str(value["candidate_id"]))
    result_body = {key: value for key, value in result_value.items() if key != "result_sha256"}
    result_value["result_sha256"] = content_sha256(result_body)
    command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(command_value)
    result = LocalImageScienceVisualCampaignReviewBatchResult.model_validate(result_value)
    with pytest.raises(ValueError, match="coverage differs"):
        validate_science_visual_campaign_review_batch(
            command=command,
            command_pointer=result.review_batch,
            plans=tuple(
                LocalImageScienceCorpusVisualPilotPlanV3.model_validate(value) for value in plans
            ),
            plan_pointers=tuple(
                ImageEvaluationArtifactMember.model_validate(value) for value in plan_pointers
            ),
            results=tuple(
                LocalImageScienceCorpusVisualPilotResult.model_validate(value) for value in results
            ),
            result_pointers=tuple(
                ImageEvaluationArtifactMember.model_validate(value) for value in result_pointers
            ),
            review_result=result,
        )


def test_campaign_review_batch_publisher_preflights_exact_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command_value, _, plans, results, plan_pointers, result_pointers = (
        _campaign_review_batch_values()
    )
    command_path = tmp_path / "command.json"
    command_path.write_bytes(content_json_bytes(command_value))
    command_path.chmod(0o600)
    command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(command_value)
    resolved = batch_stager.ResolvedScienceVisualCampaign(
        campaign_id=command.campaign_id,
        pilots=command.pilot_results,
        candidate_ids=tuple(
            sorted(
                candidate["candidate_id"]
                for result in results
                for candidate in result["visual_candidates"]
            )
        ),
        plans=tuple(
            LocalImageScienceCorpusVisualPilotPlanV3.model_validate(value) for value in plans
        ),
        plan_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(value) for value in plan_pointers
        ),
        results=tuple(
            LocalImageScienceCorpusVisualPilotResult.model_validate(value) for value in results
        ),
        result_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(value) for value in result_pointers
        ),
    )
    monkeypatch.setattr(batch_publisher.os, "geteuid", lambda: 0)
    monkeypatch.setattr(batch_publisher, "_load_campaign", lambda _attempts: resolved)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_science_visual_campaign_review_batch.py",
            "--attempt-id",
            "imgscivisattempt_" + "1" * 32,
            "--attempt-id",
            "imgscivisattempt_" + "2" * 32,
            "--attempt-id",
            "imgscivisattempt_" + "3" * 32,
            "--command",
            str(command_path),
            "--source-commit",
            "a" * 40,
            "--preflight-only",
        ],
    )
    assert batch_publisher.main() == 0
    assert json.loads(capsys.readouterr().out)["preflight"] == "PASS"


def test_campaign_review_batch_publisher_imports_under_isolated_python() -> None:
    bootstrap = (
        "import runpy,sys;"
        "service_root,script=sys.argv[1:3];"
        "sys.path.insert(0,service_root);"
        "sys.argv=[script,'--help'];"
        "runpy.run_path(script,run_name='__main__')"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            bootstrap,
            str(ROOT / "services/orchestrator"),
            str(ROOT / "scripts/image_trainer/publish_science_visual_campaign_review_batch.py"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--preflight-only" in completed.stdout


def test_campaign_review_batch_publisher_preflights_exact_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command_value, result_value, plans, results, plan_pointers, result_pointers = (
        _campaign_review_batch_values()
    )
    command_payload = content_json_bytes(command_value)
    command_path = tmp_path / "command.json"
    command_path.write_bytes(command_payload)
    command_path.chmod(0o600)
    command_pointer_value = _pointer(
        "e",
        member_path="manifests/science-visual-campaign-review-batch-command.json",
        schema_ref=(
            "eom://schemas/image-provider/"
            "local-image-science-visual-campaign-review-batch-command/1.0"
        ),
        sha256=sha256_bytes(command_payload),
    )
    result_value["review_batch"] = command_pointer_value
    result_body = {key: value for key, value in result_value.items() if key != "result_sha256"}
    result_value["result_sha256"] = content_sha256(result_body)
    result_path = tmp_path / "result.json"
    result_path.write_bytes(content_json_bytes(result_value))
    result_path.chmod(0o600)

    command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(command_value)
    resolved = batch_stager.ResolvedScienceVisualCampaign(
        campaign_id=command.campaign_id,
        pilots=command.pilot_results,
        candidate_ids=tuple(
            sorted(
                candidate["candidate_id"]
                for result in results
                for candidate in result["visual_candidates"]
            )
        ),
        plans=tuple(
            LocalImageScienceCorpusVisualPilotPlanV3.model_validate(value) for value in plans
        ),
        plan_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(value) for value in plan_pointers
        ),
        results=tuple(
            LocalImageScienceCorpusVisualPilotResult.model_validate(value) for value in results
        ),
        result_pointers=tuple(
            ImageEvaluationArtifactMember.model_validate(value) for value in result_pointers
        ),
    )
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    receipt_path = state_root / (f"science-visual-campaign-review-command-{command.batch_id}.json")
    receipt_path.write_bytes(
        content_json_bytes(
            {
                "schema_version": (
                    "science-visual-campaign-review-command-publication-receipt/1.0"
                ),
                "batch_id": command.batch_id,
                "command_sha256": command.command_sha256,
                "command_artifact": command_pointer_value,
                "source_commit": "a" * 40,
            }
        )
    )
    receipt_path.chmod(0o600)

    monkeypatch.setattr(batch_publisher.os, "geteuid", lambda: 0)
    monkeypatch.setattr(batch_publisher, "STATE_ROOT", state_root)
    monkeypatch.setattr(batch_publisher, "_load_campaign", lambda _attempts: resolved)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_science_visual_campaign_review_batch.py",
            "--attempt-id",
            "imgscivisattempt_" + "1" * 32,
            "--attempt-id",
            "imgscivisattempt_" + "2" * 32,
            "--attempt-id",
            "imgscivisattempt_" + "3" * 32,
            "--command",
            str(command_path),
            "--result",
            str(result_path),
            "--source-commit",
            "a" * 40,
            "--preflight-only",
        ],
    )
    assert batch_publisher.main() == 0
    assert json.loads(capsys.readouterr().out)["preflight"] == "PASS"


def test_campaign_inventory_publisher_resolves_stage_and_result_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory_value, plan_values, result_values, plan_pointers, result_pointers = (
        _campaign_inventory_value()
    )
    pilots = inventory_value["pilot_results"]
    assert isinstance(pilots, list)
    for index, (plan, plan_pointer, result_pointer) in enumerate(
        zip(plan_values, plan_pointers, result_pointers, strict=True)
    ):
        plan_pointer["sha256"] = sha256_bytes(content_json_bytes(plan))
        pilot = pilots[index]
        assert isinstance(pilot, dict)
        pilot["pilot_plan"] = plan_pointer
        pilot["pilot_plan_file_sha256"] = plan_pointer["sha256"]
        pilot["pilot_result"] = result_pointer
        pilot["pilot_result_file_sha256"] = result_pointer["sha256"]
    body = {
        key: value
        for key, value in inventory_value.items()
        if key not in {"inventory_id", "inventory_sha256"}
    }
    inventory_value["inventory_id"] = (
        "imgsciviscampaigninventory_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    inventory_value["inventory_sha256"] = content_sha256(
        {key: value for key, value in inventory_value.items() if key != "inventory_sha256"}
    )
    inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(inventory_value)

    workspace_parent = tmp_path / "workspaces"
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o750)
    attempt_ids = tuple(str(pilot["attempt_id"]) for pilot in pilots)
    for attempt_id, plan, result, plan_pointer, result_pointer in zip(
        attempt_ids, plan_values, result_values, plan_pointers, result_pointers, strict=True
    ):
        workspace = workspace_parent / attempt_id
        (workspace / "input").mkdir(parents=True, mode=0o700)
        (workspace / "manifests").mkdir(mode=0o700)
        plan_payload = content_json_bytes(plan)
        result_payload = content_json_bytes(result)
        (workspace / "input/visual-pilot-plan.json").write_bytes(plan_payload)
        (workspace / "manifests/visual-pilot-result.json").write_bytes(result_payload)
        (workspace / "input/visual-pilot-plan.json").chmod(0o600)
        (workspace / "manifests/visual-pilot-result.json").chmod(0o600)
        (state_root / f"science-visual-pilot-stage-{attempt_id}.json").write_bytes(
            content_json_bytes(
                {
                    "schema_version": "science-visual-pilot-stage-receipt/1.0",
                    "attempt_id": attempt_id,
                    "command_sha256": _sha("a"),
                    "plan": plan_pointer,
                    "training_authorization": plan["training_authorization"],
                    "workspace": str(workspace),
                    "systemd_unit": f"eom-image-science-visual-pilot@{attempt_id}.service",
                }
            )
        )
        (state_root / f"science-visual-pilot-publication-{attempt_id}.json").write_bytes(
            content_json_bytes(
                {
                    "schema_version": "science-visual-pilot-publication-receipt/1.0",
                    "attempt_id": attempt_id,
                    "result_sha256": result["result_sha256"],
                    "result_file_sha256": sha256_bytes(result_payload),
                    "result_artifact": result_pointer,
                    "file_set_manifest_sha256": _sha("b"),
                    "source_commit": "c" * 40,
                }
            )
        )
        (state_root / f"science-visual-pilot-stage-{attempt_id}.json").chmod(0o600)
        (state_root / f"science-visual-pilot-publication-{attempt_id}.json").chmod(0o600)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_bytes(content_json_bytes(inventory.model_dump(mode="json")))
    inventory_path.chmod(0o600)
    monkeypatch.setattr(campaign_publisher, "WORKSPACE_PARENT", workspace_parent)
    monkeypatch.setattr(campaign_publisher, "STATE_ROOT", state_root)

    loaded, plans, _, results, _ = campaign_publisher._load_inputs(
        attempt_ids=attempt_ids,
        inventory_path=inventory_path,
    )
    assert loaded.inventory_id == inventory.inventory_id
    assert len(plans) == len(results) == 3


def _crop_set_sources() -> list[dict[str, object]]:
    return [
        _source(index, "TRAIN" if index < 12 else "VALIDATION" if index < 15 else "HOLDOUT")
        for index in range(18)
    ]


def _crop_set_plan_value() -> dict[str, object]:
    value = copy.deepcopy(_plan_v2_value())
    sources = sorted(_crop_set_sources(), key=lambda item: item["document_id"])
    value["selected_sources"] = sources
    value["max_page_images"] = 18
    value["max_visual_candidates"] = 36
    value["max_lora_training_crops"] = 18
    body = {key: item for key, item in value.items() if key not in {"pilot_id", "plan_sha256"}}
    value["pilot_id"] = "imgscivispilot_" + content_sha256(body).removeprefix("sha256:")[:32]
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    return value


def _crop_set_result_value() -> dict[str, object]:
    plan = _crop_set_plan_value()
    pages: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for index, source in enumerate(plan["selected_sources"]):
        page_hash = "sha256:" + f"{index + 500:064x}"
        document_id = str(source["document_id"])
        pages.append(
            {
                "document_id": document_id,
                "physical_page": 1,
                "member_path": f"pages/{document_id}/page-1.png",
                "sha256": page_hash,
                "size_bytes": 16384 + index,
                "width_px": 1191,
                "height_px": 1684,
            }
        )
        candidates.append(_candidate(document_id, page_hash, index + 20))
    candidates.sort(key=lambda item: item["candidate_id"])
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-result/1.0",
        "pilot_id": plan["pilot_id"],
        "plan_sha256": plan["plan_sha256"],
        "status": "SUCCEEDED",
        "page_images": pages,
        "visual_candidates": candidates,
        "omissions": [],
        "runtime": {
            "python_version": "3.12",
            "pillow_version": "11.3",
            "opencv_version": "4.11",
            "tesseract_version": "5.3",
            "pdftoppm_version": "24.02",
        },
        "error_code": None,
        "started_at": "2026-09-26T06:00:00Z",
        "completed_at": "2026-09-26T06:01:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _crop_set_inventory_value() -> dict[str, object]:
    result = _crop_set_result_value()
    families = (
        "ASTRONOMICAL_SCENE",
        "FOSSIL",
        "GEOLOGIC_TEXTURE",
        "MICROSCOPIC_TEXTURE",
        "NATURAL_TEXTURE",
        "ORGANISM",
    )
    reviews = []
    for index, candidate in enumerate(result["visual_candidates"]):
        caption = f"grayscale science assessment natural reference image {index}"
        reviews.append(
            {
                "candidate_id": candidate["candidate_id"],
                "decision": "LORA_ELIGIBLE",
                "pattern_family": families[index % len(families)],
                "visual_features": [],
                "caption_en": caption,
                "caption_sha256": text_sha256(caption),
                "reviewed_by": "reviewer_user",
                "reviewed_at": "2026-09-26T06:02:00Z",
            }
        )
    result_file_sha256 = _sha("9")
    body: dict[str, object] = {
        "schema_version": "local-image-science-visual-pattern-inventory/1.1",
        "pilot_result": _pointer(
            "f",
            member_path="manifests/visual-pilot-result.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0"
            ),
            sha256=result_file_sha256,
        ),
        "pilot_result_file_sha256": result_file_sha256,
        "pilot_result_semantic_sha256": result["result_sha256"],
        "reviews": reviews,
        "primitive_recommendations": [],
        "lora_eligible_count": 18,
        "deterministic_renderer_count": 0,
        "excluded_count": 0,
        "created_at": "2026-09-26T06:03:00Z",
        "created_by": "reviewer_user",
    }
    body["inventory_id"] = "imgscivisinventory_" + content_sha256(body).removeprefix("sha256:")[:32]
    return {**body, "inventory_sha256": content_sha256(body)}


def _raster_suitability_review_value() -> dict[str, object]:
    inventory = _crop_set_inventory_value()
    reviews = inventory["reviews"]
    assert isinstance(reviews, list)
    entries: list[dict[str, object]] = []
    for index, source_review in enumerate(reviews):
        assert isinstance(source_review, dict)
        if index < 15:
            entries.append(
                {
                    "candidate_id": source_review["candidate_id"],
                    "decision": "GPU_RASTER_ELIGIBLE",
                    "semantic_alignment": "VERIFIED",
                    "reasons": [],
                    "caption_en": source_review["caption_en"],
                    "caption_sha256": source_review["caption_sha256"],
                }
            )
        else:
            entries.append(
                {
                    "candidate_id": source_review["candidate_id"],
                    "decision": "EXCLUDED",
                    "semantic_alignment": "NOT_APPLICABLE",
                    "reasons": ["PANEL_COMPOSITION"],
                    "caption_en": None,
                    "caption_sha256": None,
                }
            )
    entries.sort(key=lambda item: str(item["candidate_id"]))
    inventory_file_sha256 = _sha("e")
    body: dict[str, object] = {
        "schema_version": "local-image-science-raster-suitability-review/1.0",
        "pattern_inventory": _pointer(
            "e",
            member_path="manifests/science-visual-pattern-inventory.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-pattern-inventory/1.1"
            ),
            sha256=inventory_file_sha256,
        ),
        "pattern_inventory_file_sha256": inventory_file_sha256,
        "pattern_inventory_semantic_sha256": inventory["inventory_sha256"],
        "entries": entries,
        "gpu_raster_eligible_count": 15,
        "python_svg_required_count": 0,
        "excluded_count": 3,
        "reviewed_at": "2026-09-26T06:05:00Z",
        "reviewed_by": "reviewer_user",
    }
    body["review_id"] = "imgscivisrasterreview_" + content_sha256(body).removeprefix("sha256:")[:32]
    return {**body, "review_sha256": content_sha256(body)}


def _crop_set_value() -> dict[str, object]:
    plan = _crop_set_plan_value()
    result = _crop_set_result_value()
    inventory = _crop_set_inventory_value()
    sources = {value["document_id"]: value for value in plan["selected_sources"]}
    reviews = {value["candidate_id"]: value for value in inventory["reviews"]}
    selected_by_partition = {"TRAIN": 0, "VALIDATION": 0, "HOLDOUT": 0}
    members = []
    for candidate in result["visual_candidates"]:
        source = sources[candidate["document_id"]]
        partition = str(source["partition"])
        limit = 12 if partition == "TRAIN" else 1 if partition == "VALIDATION" else 2
        if selected_by_partition[partition] >= limit:
            continue
        selected_by_partition[partition] += 1
        review = reviews[candidate["candidate_id"]]
        members.append(
            {
                "candidate_id": candidate["candidate_id"],
                "document_id": candidate["document_id"],
                "physical_page": candidate["physical_page"],
                "exam_group_sha256": source["exam_group_sha256"],
                "partition": partition,
                "pattern_family": review["pattern_family"],
                "member_path": candidate["member_path"],
                "media_type": "image/png",
                "width_px": 768,
                "height_px": 512,
                "size_bytes": candidate["size_bytes"],
                "sha256": candidate["sha256"],
                "caption_en": review["caption_en"],
                "caption_sha256": review["caption_sha256"],
                "perceptual_hash": f"{len(members) + 1:016x}",
            }
        )
    members.sort(key=lambda item: item["candidate_id"])
    body: dict[str, object] = {
        "schema_version": "local-image-science-visual-crop-set/1.0",
        "pattern_inventory": _pointer(
            "7",
            member_path="manifests/science-visual-pattern-inventory.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-pattern-inventory/1.1"
            ),
        ),
        "pattern_inventory_semantic_sha256": inventory["inventory_sha256"],
        "pilot_plan": _pointer(
            "6",
            member_path="manifests/visual-pilot-plan.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.1"
            ),
        ),
        "pilot_plan_sha256": plan["plan_sha256"],
        "pilot_result": inventory["pilot_result"],
        "pilot_result_semantic_sha256": result["result_sha256"],
        "training_authorization": plan["training_authorization"],
        "members": members,
        "created_at": "2026-09-26T06:04:00Z",
        "created_by": "reviewer_user",
    }
    body["crop_set_id"] = "imgsciviscropset_" + content_sha256(body).removeprefix("sha256:")[:32]
    return {**body, "crop_set_sha256": content_sha256(body)}


def _crop_set_v2_value() -> dict[str, object]:
    """Build a successor fixture with an audit pointer bound to this inventory."""

    crop_set = _crop_set_value()
    review_value = _raster_suitability_review_value()
    review_value["pattern_inventory"] = crop_set["pattern_inventory"]
    review_value["pattern_inventory_file_sha256"] = crop_set["pattern_inventory"]["sha256"]
    members = crop_set["members"]
    audit_entries = review_value["entries"]
    assert isinstance(members, list)
    assert isinstance(audit_entries, list)
    selected_ids = {str(member["candidate_id"]) for member in members}
    broad_reviews = _crop_set_inventory_value()["reviews"]
    assert isinstance(broad_reviews, list)
    broad_by_id = {str(entry["candidate_id"]): entry for entry in broad_reviews}
    for entry in audit_entries:
        candidate_id = str(entry["candidate_id"])
        if candidate_id in selected_ids:
            broad = broad_by_id[candidate_id]
            entry.update(
                {
                    "decision": "GPU_RASTER_ELIGIBLE",
                    "semantic_alignment": "VERIFIED",
                    "reasons": [],
                    "caption_en": broad["caption_en"],
                    "caption_sha256": broad["caption_sha256"],
                }
            )
        else:
            entry.update(
                {
                    "decision": "EXCLUDED",
                    "semantic_alignment": "NOT_APPLICABLE",
                    "reasons": ["PANEL_COMPOSITION"],
                    "caption_en": None,
                    "caption_sha256": None,
                }
            )
    audit_entries.sort(key=lambda entry: str(entry["candidate_id"]))
    review_value["gpu_raster_eligible_count"] = len(selected_ids)
    review_value["python_svg_required_count"] = 0
    review_value["excluded_count"] = len(audit_entries) - len(selected_ids)
    review_body = {
        key: value
        for key, value in review_value.items()
        if key not in {"review_id", "review_sha256"}
    }
    review_value["review_id"] = (
        "imgscivisrasterreview_" + content_sha256(review_body).removeprefix("sha256:")[:32]
    )
    review_value["review_sha256"] = content_sha256(
        {key: value for key, value in review_value.items() if key != "review_sha256"}
    )
    body = {
        key: value
        for key, value in crop_set.items()
        if key not in {"schema_version", "crop_set_id", "crop_set_sha256"}
    }
    body["schema_version"] = "local-image-science-visual-crop-set/1.1"
    body["raster_suitability_review"] = _pointer(
        "a",
        member_path="manifests/science-raster-suitability-review.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-raster-suitability-review/1.0"
        ),
        sha256=content_sha256(review_value),
    )
    body["raster_suitability_review_sha256"] = review_value["review_sha256"]
    identity = content_sha256(body).removeprefix("sha256:")
    body["crop_set_id"] = "imgsciviscropset_" + identity[:32]
    value = {**body, "crop_set_sha256": content_sha256(body)}
    value["_raster_suitability_review"] = review_value
    return value


def _raster_refinement_plan_value() -> dict[str, object]:
    """One panel split from a pinned, broadly eligible parent crop."""

    result = _crop_set_result_value()
    inventory = _crop_set_inventory_value()
    review = _raster_suitability_review_value()
    entries = review["entries"]
    assert isinstance(entries, list)
    panel_entry = next(entry for entry in entries if entry["decision"] == "EXCLUDED")
    caption = "grayscale volcanic crater reference photograph"
    proposal: dict[str, object] = {
        "parent_candidate_id": panel_entry["candidate_id"],
        "crop_bounding_box": {"left": 600, "top": 700, "right": 9200, "bottom": 9100},
        "caption_en": caption,
        "caption_sha256": text_sha256(caption),
        "partition": "TRAIN",
        "refinement_reasons": ["PANEL_SPLIT"],
    }
    proposal["refinement_id"] = (
        "imgscivisrefine_" + content_sha256(proposal).removeprefix("sha256:")[:32]
    )
    body: dict[str, object] = {
        "schema_version": "local-image-science-raster-refinement-plan/1.0",
        "pattern_inventory": review["pattern_inventory"],
        "pattern_inventory_semantic_sha256": inventory["inventory_sha256"],
        "raster_suitability_review": _pointer(
            "c",
            member_path="manifests/science-raster-suitability-review.json",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-raster-suitability-review/1.0"
            ),
            sha256=content_sha256(review),
        ),
        "raster_suitability_review_sha256": review["review_sha256"],
        "pilot_result": inventory["pilot_result"],
        "pilot_result_semantic_sha256": result["result_sha256"],
        "proposals": [proposal],
        "created_at": "2026-09-26T07:00:00Z",
        "created_by": "reviewer_user",
    }
    body["refinement_plan_id"] = (
        "imgscivisrefineplan_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    value = {**body, "plan_sha256": content_sha256(body)}
    value["_raster_suitability_review"] = review
    return value


def _science_micro_plan_value() -> dict[str, object]:
    crop_set = _crop_set_value()
    members = crop_set["members"]
    assert isinstance(members, list)
    by_partition = {
        partition: sorted(
            str(value["candidate_id"]) for value in members if value["partition"] == partition
        )
        for partition in ("TRAIN", "VALIDATION", "HOLDOUT")
    }
    body: dict[str, object] = {
        "schema_version": "local-image-science-lora-micro-probe-plan/1.0",
        "crop_set": _pointer(
            "a",
            member_path="manifests/science-visual-crop-set.json",
            schema_ref=("eom://schemas/image-provider/local-image-science-visual-crop-set/1.0"),
        ),
        "crop_set_sha256": crop_set["crop_set_sha256"],
        "base_model": {
            "model_id": "imgmodel_" + "b" * 32,
            "model_revision_id": "imgmodelrev_" + "c" * 32,
            "manifest_sha256": _sha("d"),
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        },
        "training_member_ids": by_partition["TRAIN"],
        "validation_member_ids": by_partition["VALIDATION"],
        "holdout_member_ids": by_partition["HOLDOUT"],
        "preprocessing_revision": "local-image-science-crop-preprocess/1.0",
        "trainer_contract": "eom-local-image-science-lora-micro-trainer/1.0",
        "dependencies": {
            "python_version": "3.11.13",
            "torch_version": "2.8.0",
            "diffusers_version": "0.35.1",
            "transformers_version": "4.56.1",
            "accelerate_version": "1.10.1",
            "peft_version": "0.17.1",
            "bitsandbytes_version": "0.47.0",
        },
        "hyperparameters": {
            "adapter_type": "UNET_LORA",
            "rank": 8,
            "alpha": 8,
            "resolution_width": 768,
            "resolution_height": 512,
            "train_batch_size": 1,
            "gradient_accumulation_steps": 4,
            "gradient_checkpointing": True,
            "mixed_precision": "fp16",
            "optimizer": "adamw_8bit",
            "learning_rate": "1e-4",
            "max_train_steps": 200,
            "checkpointing_steps": 200,
            "random_flip": False,
            "train_text_encoders": False,
            "train_vae": False,
        },
        "seed": 20260926,
        "purpose": "EVALUATION_ONLY_SCIENCE_MICRO_PROBE",
        "activation_policy": "FORBIDDEN",
        "authorized_at": "2026-09-26T00:00:00Z",
        "authorized_by": "operator_eom",
        "authorization_reference_sha256": _sha("e"),
        "created_at": "2026-09-26T00:01:00Z",
        "created_by": "operator_eom",
        "source_commit": "f" * 40,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "probe_id": "imgscimicroprobe_" + identity[:32]}
    return {**with_id, "plan_sha256": content_sha256(with_id)}


def _science_micro_command_value() -> dict[str, object]:
    plan = _science_micro_plan_value()
    pointer = _pointer(
        "1",
        member_path="manifests/science-micro-probe-plan.json",
        schema_ref=("eom://schemas/image-provider/local-image-science-lora-micro-probe-plan/1.0"),
    )
    identity = content_sha256(
        {
            "probe_plan_pointer": pointer,
            "probe_plan_sha256": plan["plan_sha256"],
            "attempt": 1,
        }
    ).removeprefix("sha256:")
    body: dict[str, object] = {
        "schema_version": "local-image-science-lora-micro-probe-command/1.0",
        "training_run_id": "imgscimicrotrainrun_" + identity[:32],
        "probe_plan_pointer": pointer,
        "probe_plan_sha256": plan["plan_sha256"],
        "probe_plan": plan,
        "attempt": 1,
        "staged_plan_member": "inputs/science-micro-probe-plan.json",
        "staged_crop_set_member": "inputs/science-visual-crop-set.json",
        "staged_crops_root": "inputs/crops",
        "runtime_dataset_root": "runtime-dataset",
        "output_root_member": "outputs",
        "checkpoint_root_member": "checkpoints",
        "timeout_seconds": 7200,
    }
    return {**body, "command_sha256": content_sha256(body)}


def _science_micro_result_value() -> dict[str, object]:
    command = _science_micro_command_value()
    plan = command["probe_plan"]
    assert isinstance(plan, dict)
    member_ids = plan["training_member_ids"]
    assert isinstance(member_ids, list)
    crop_set_members = _crop_set_value()["members"]
    assert isinstance(crop_set_members, list)
    members = {str(value["candidate_id"]): value for value in crop_set_members}
    realized = [
        {
            "candidate_id": candidate_id,
            "document_id": members[candidate_id]["document_id"],
            "exam_group_sha256": members[candidate_id]["exam_group_sha256"],
            "training_sample_id": f"imgtrainsample_{index + 1:032x}",
            "source_crop_sha256": members[candidate_id]["sha256"],
            "realized_crop_sha256": f"sha256:{index + 100:064x}",
            "caption_sha256": members[candidate_id]["caption_sha256"],
            "perceptual_hash": f"{index + 1000:016x}",
        }
        for index, candidate_id in enumerate(member_ids)
    ]
    realized.sort(key=lambda value: str(value["training_sample_id"]))
    sample_set_sha256 = content_sha256(realized)
    adapter_body: dict[str, object] = {
        "schema_version": "local-image-science-lora-micro-adapter-manifest/1.0",
        "adapter_id": "imgadapter_" + "2" * 32,
        "adapter_revision_id": "imgadapterrev_" + "3" * 32,
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "base_model": plan["base_model"],
        "probe_plan": command["probe_plan_pointer"],
        "sample_set_sha256": sample_set_sha256,
        "files": [
            {
                "relative_path": "adapter_config.json",
                "size_bytes": 128,
                "sha256": _sha("4"),
            },
            {
                "relative_path": "adapter_model.safetensors",
                "size_bytes": 1024,
                "sha256": _sha("5"),
            },
        ],
        "created_at": "2026-09-26T00:10:00Z",
    }
    adapter = {**adapter_body, "manifest_sha256": content_sha256(adapter_body)}
    body: dict[str, object] = {
        "schema_version": "local-image-science-lora-micro-probe-worker-result/1.0",
        "training_run_id": command["training_run_id"],
        "probe_plan_pointer": command["probe_plan_pointer"],
        "probe_plan_sha256": command["probe_plan_sha256"],
        "command_sha256": command["command_sha256"],
        "attempt": 1,
        "status": "SUCCEEDED",
        "adapter_manifest": adapter,
        "realized_samples": realized,
        "sample_set_sha256": sample_set_sha256,
        "error_code": None,
        "runtime": {
            **plan["dependencies"],
            "cuda_version": "13.0",
            "gpu_name": "NVIDIA RTX PRO 6000 Blackwell",
            "compute_capability": "12.0",
            "peak_gpu_memory_bytes": 1024,
        },
        "completed_steps": 200,
        "final_loss": 0.125,
        "started_at": "2026-09-26T00:02:00Z",
        "completed_at": "2026-09-26T00:10:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _science_micro_evaluation_command_value() -> dict[str, object]:
    training = _science_micro_command_value()
    plan = training["probe_plan"]
    assert isinstance(plan, dict)
    result = _science_micro_result_value()
    crop_set = _crop_set_value()
    crop_members = crop_set["members"]
    assert isinstance(crop_members, list)
    members = {str(value["candidate_id"]): value for value in crop_members}
    holdout_ids = plan["holdout_member_ids"]
    assert isinstance(holdout_ids, list)
    negative = (
        "people, portrait, photorealistic scene, decorative text, watermark, color, "
        "answer markings, cropped subject, clutter"
    )
    cases = [
        {
            "candidate_id": candidate_id,
            "document_id": members[candidate_id]["document_id"],
            "exam_group_sha256": members[candidate_id]["exam_group_sha256"],
            "positive_prompt": members[candidate_id]["caption_en"],
            "positive_prompt_sha256": members[candidate_id]["caption_sha256"],
            "negative_prompt": negative,
            "negative_prompt_sha256": text_sha256(negative),
            "seed": 20261026 + index,
        }
        for index, candidate_id in enumerate(holdout_ids)
    ]
    cases.sort(key=lambda value: str(value["candidate_id"]))
    body: dict[str, object] = {
        "schema_version": "local-image-science-lora-micro-evaluation-command/1.0",
        "training_run_id": training["training_run_id"],
        "probe_plan_pointer": training["probe_plan_pointer"],
        "probe_plan_sha256": training["probe_plan_sha256"],
        "crop_set": plan["crop_set"],
        "crop_set_sha256": plan["crop_set_sha256"],
        "training_result_sha256": result["result_sha256"],
        "adapter_manifest": result["adapter_manifest"],
        "cases": cases,
        "inference_steps": 20,
        "guidance_scale": 7.5,
        "generation_width": 800,
        "generation_height": 504,
        "delivery_width": 800,
        "delivery_height": 500,
        "staged_adapter_root": "inputs/adapter",
        "output_root_member": "outputs",
        "source_commit": "f" * 40,
        "timeout_seconds": 3600,
    }
    identity = content_sha256(body).removeprefix("sha256:")
    with_id = {**body, "evaluation_run_id": "imgscimicroevalrun_" + identity[:32]}
    return {**with_id, "command_sha256": content_sha256(with_id)}


def _science_micro_evaluation_result_value() -> dict[str, object]:
    command = _science_micro_evaluation_command_value()
    cases = command["cases"]
    assert isinstance(cases, list)
    outputs = [
        {
            "candidate_id": case["candidate_id"],
            "variant": variant,
            "member_path": (f"outputs/{case['candidate_id']}-{str(variant).lower()}.png"),
            "sha256": f"sha256:{index + 1:064x}",
            "size_bytes": 4096,
            "width_px": 800,
            "height_px": 500,
        }
        for index, (case, variant) in enumerate(
            (value, variant) for value in cases for variant in ("ADAPTER", "BASE")
        )
    ]
    outputs.sort(key=lambda value: (str(value["candidate_id"]), str(value["variant"])))
    adapter = command["adapter_manifest"]
    assert isinstance(adapter, dict)
    body = {
        "schema_version": "local-image-science-lora-micro-evaluation-result/1.0",
        "evaluation_run_id": command["evaluation_run_id"],
        "command_sha256": command["command_sha256"],
        "training_result_sha256": command["training_result_sha256"],
        "adapter_manifest_sha256": adapter["manifest_sha256"],
        "status": "SUCCEEDED",
        "outputs": outputs,
        "error_code": None,
        "started_at": "2026-09-26T00:11:00Z",
        "completed_at": "2026-09-26T00:20:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


@pytest.mark.parametrize(
    ("contract", "model", "value_factory"),
    [
        (
            "science-corpus-training-authorization",
            LocalImageScienceCorpusTrainingAuthorization,
            _authorization_value,
        ),
        (
            "science-corpus-visual-pilot-plan",
            LocalImageScienceCorpusVisualPilotPlan,
            _plan_value,
        ),
        (
            "science-corpus-visual-pilot-plan-v2",
            LocalImageScienceCorpusVisualPilotPlanV2,
            _plan_v2_value,
        ),
        (
            "science-corpus-visual-pilot-plan-v3",
            LocalImageScienceCorpusVisualPilotPlanV3,
            _plan_v3_value,
        ),
        (
            "science-corpus-visual-pilot-command",
            LocalImageScienceCorpusVisualPilotCommand,
            _command_value,
        ),
        (
            "science-corpus-visual-pilot-command-v2",
            LocalImageScienceCorpusVisualPilotCommandV2,
            _command_v2_value,
        ),
        (
            "science-corpus-visual-pilot-command-v3",
            LocalImageScienceCorpusVisualPilotCommandV3,
            _command_v3_value,
        ),
        (
            "science-corpus-visual-pilot-result",
            LocalImageScienceCorpusVisualPilotResult,
            _result_value,
        ),
        (
            "science-visual-pattern-inventory",
            LocalImageScienceVisualPatternInventory,
            _inventory_value,
        ),
        (
            "science-visual-pattern-inventory-v2",
            LocalImageScienceVisualPatternInventoryV2,
            _inventory_v2_value,
        ),
        (
            "science-visual-campaign-pattern-inventory",
            LocalImageScienceVisualCampaignPatternInventory,
            lambda: _campaign_inventory_value()[0],
        ),
        (
            "science-visual-crop-set",
            LocalImageScienceVisualCropSet,
            _crop_set_value,
        ),
        (
            "science-lora-micro-probe-plan",
            LocalImageScienceLoraMicroProbePlan,
            _science_micro_plan_value,
        ),
        (
            "science-lora-micro-probe-command",
            LocalImageScienceLoraMicroProbeCommand,
            _science_micro_command_value,
        ),
        (
            "science-lora-micro-adapter-manifest",
            LocalImageScienceLoraMicroAdapterManifest,
            lambda: _science_micro_result_value()["adapter_manifest"],
        ),
        (
            "science-lora-micro-probe-worker-result",
            LocalImageScienceLoraMicroProbeWorkerResult,
            _science_micro_result_value,
        ),
        (
            "science-lora-micro-evaluation-command",
            LocalImageScienceLoraMicroEvaluationCommand,
            _science_micro_evaluation_command_value,
        ),
        (
            "science-lora-micro-evaluation-result",
            LocalImageScienceLoraMicroEvaluationResult,
            _science_micro_evaluation_result_value,
        ),
    ],
)
def test_science_visual_contract_schema_and_model_parity(contract, model, value_factory) -> None:
    value = value_factory()
    validate_contract(contract, value)
    assert model.model_validate(value).model_dump(mode="json") == value


def test_science_visual_cross_contract_bindings() -> None:
    authorization = LocalImageScienceCorpusTrainingAuthorization.model_validate(
        _authorization_value()
    )
    plan = LocalImageScienceCorpusVisualPilotPlan.model_validate(_plan_value())
    command = LocalImageScienceCorpusVisualPilotCommand.model_validate(_command_value())
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(_result_value())
    inventory = LocalImageScienceVisualPatternInventory.model_validate(_inventory_value())

    validate_science_visual_authorization_plan(authorization, plan)
    validate_science_visual_pilot_command(plan, command)
    validate_science_visual_pilot_result(plan, result)
    validate_science_visual_pattern_inventory(result, inventory)
    inventory_v2 = LocalImageScienceVisualPatternInventoryV2.model_validate(_inventory_v2_value())
    validate_science_visual_pattern_inventory_v2(result, inventory_v2)
    assert authorization.authorization_sha256 != plan.training_authorization.sha256
    assert (
        content_sha256(authorization.model_dump(mode="json")) == plan.training_authorization.sha256
    )

    plan_v2 = LocalImageScienceCorpusVisualPilotPlanV2.model_validate(_plan_v2_value())
    command_v2 = LocalImageScienceCorpusVisualPilotCommandV2.model_validate(_command_v2_value())
    validate_science_visual_authorization_plan(authorization, plan_v2)
    validate_science_visual_pilot_command(plan_v2, command_v2)


def test_science_visual_crop_set_binds_reviewed_group_deduplicated_members() -> None:
    authorization = LocalImageScienceCorpusTrainingAuthorization.model_validate(
        _authorization_value()
    )
    plan = LocalImageScienceCorpusVisualPilotPlanV2.model_validate(_crop_set_plan_value())
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(_crop_set_result_value())
    inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(
        _crop_set_inventory_value()
    )
    crop_set = LocalImageScienceVisualCropSet.model_validate(_crop_set_value())

    validate_science_visual_crop_set(
        authorization=authorization,
        plan=plan,
        result=result,
        inventory=inventory,
        crop_set=crop_set,
    )
    assert len(crop_set.members) == 15
    assert len({value.exam_group_sha256 for value in crop_set.members}) == 15


def test_science_raster_suitability_review_covers_exact_broad_population() -> None:
    inventory_value = _crop_set_inventory_value()
    review_value = _raster_suitability_review_value()
    validate_contract("science-raster-suitability-review", review_value)
    inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(inventory_value)
    review = LocalImageScienceVisualRasterSuitabilityReview.model_validate(review_value)

    validate_science_visual_raster_suitability_review(inventory, review)
    assert review.gpu_raster_eligible_count == 15
    assert review.excluded_count == 3


def test_science_raster_suitability_review_rejects_missing_or_unsafe_member() -> None:
    inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(
        _crop_set_inventory_value()
    )
    missing = _raster_suitability_review_value()
    entries = missing["entries"]
    assert isinstance(entries, list)
    missing["entries"] = entries[:-1]
    counts = Counter(str(value["decision"]) for value in missing["entries"])
    missing["gpu_raster_eligible_count"] = counts["GPU_RASTER_ELIGIBLE"]
    missing["python_svg_required_count"] = counts["PYTHON_SVG_REQUIRED"]
    missing["excluded_count"] = counts["EXCLUDED"]
    body = {
        key: value for key, value in missing.items() if key not in {"review_id", "review_sha256"}
    }
    missing["review_id"] = (
        "imgscivisrasterreview_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    missing["review_sha256"] = content_sha256(
        {key: value for key, value in missing.items() if key != "review_sha256"}
    )
    review = LocalImageScienceVisualRasterSuitabilityReview.model_validate(missing)
    with pytest.raises(ValueError, match="does not cover every broad raster candidate"):
        validate_science_visual_raster_suitability_review(inventory, review)

    unsafe = _raster_suitability_review_value()
    unsafe_entries = unsafe["entries"]
    assert isinstance(unsafe_entries, list)
    gpu_entry = next(
        value for value in unsafe_entries if value["decision"] == "GPU_RASTER_ELIGIBLE"
    )
    gpu_entry["semantic_alignment"] = "MISMATCH"
    body = {
        key: value for key, value in unsafe.items() if key not in {"review_id", "review_sha256"}
    }
    unsafe["review_id"] = (
        "imgscivisrasterreview_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    unsafe["review_sha256"] = content_sha256(
        {key: value for key, value in unsafe.items() if key != "review_sha256"}
    )
    with pytest.raises(ValidationError, match="GPU raster eligibility requires"):
        LocalImageScienceVisualRasterSuitabilityReview.model_validate(unsafe)


def test_raster_reviewed_crop_set_requires_verified_gpu_raster_evidence() -> None:
    authorization = LocalImageScienceCorpusTrainingAuthorization.model_validate(
        _authorization_value()
    )
    plan = LocalImageScienceCorpusVisualPilotPlanV2.model_validate(_crop_set_plan_value())
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(_crop_set_result_value())
    inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(
        _crop_set_inventory_value()
    )
    value = _crop_set_v2_value()
    review_value = value.pop("_raster_suitability_review")
    assert isinstance(review_value, dict)
    review = LocalImageScienceVisualRasterSuitabilityReview.model_validate(review_value)
    validate_contract("science-visual-crop-set-v2", value)
    crop_set = LocalImageScienceVisualCropSetV2.model_validate(value)

    validate_science_visual_crop_set_v2(
        authorization=authorization,
        plan=plan,
        result=result,
        inventory=inventory,
        raster_suitability_review=review,
        crop_set=crop_set,
    )

    unsafe = copy.deepcopy(value)
    members = unsafe["members"]
    assert isinstance(members, list)
    review_entries = review_value["entries"]
    assert isinstance(review_entries, list)
    selected_id = members[0]["candidate_id"]
    matching = next(entry for entry in review_entries if entry["candidate_id"] == selected_id)
    matching["decision"] = "EXCLUDED"
    matching["semantic_alignment"] = "NOT_APPLICABLE"
    matching["reasons"] = ["PANEL_COMPOSITION"]
    matching["caption_en"] = None
    matching["caption_sha256"] = None
    changed_counts = Counter(str(entry["decision"]) for entry in review_entries)
    review_value["gpu_raster_eligible_count"] = changed_counts["GPU_RASTER_ELIGIBLE"]
    review_value["python_svg_required_count"] = changed_counts["PYTHON_SVG_REQUIRED"]
    review_value["excluded_count"] = changed_counts["EXCLUDED"]
    review_body = {
        key: item for key, item in review_value.items() if key not in {"review_id", "review_sha256"}
    }
    review_value["review_id"] = (
        "imgscivisrasterreview_" + content_sha256(review_body).removeprefix("sha256:")[:32]
    )
    review_value["review_sha256"] = content_sha256(
        {key: item for key, item in review_value.items() if key != "review_sha256"}
    )
    unsafe["raster_suitability_review_sha256"] = review_value["review_sha256"]
    unsafe["raster_suitability_review"]["sha256"] = content_sha256(review_value)
    unsafe_body = {
        key: item for key, item in unsafe.items() if key not in {"crop_set_id", "crop_set_sha256"}
    }
    unsafe["crop_set_id"] = (
        "imgsciviscropset_" + content_sha256(unsafe_body).removeprefix("sha256:")[:32]
    )
    unsafe["crop_set_sha256"] = content_sha256(
        {key: item for key, item in unsafe.items() if key != "crop_set_sha256"}
    )
    with pytest.raises(ValueError, match="differs from raster suitability evidence"):
        validate_science_visual_crop_set_v2(
            authorization=authorization,
            plan=plan,
            result=result,
            inventory=inventory,
            raster_suitability_review=LocalImageScienceVisualRasterSuitabilityReview.model_validate(
                review_value
            ),
            crop_set=LocalImageScienceVisualCropSetV2.model_validate(unsafe),
        )


def test_raster_refinement_plan_binds_only_reviewed_train_panel_splits() -> None:
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(_crop_set_result_value())
    inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(
        _crop_set_inventory_value()
    )
    value = _raster_refinement_plan_value()
    review_value = value.pop("_raster_suitability_review")
    assert isinstance(review_value, dict)
    review = LocalImageScienceVisualRasterSuitabilityReview.model_validate(review_value)
    validate_contract("science-raster-refinement-plan", value)
    plan = LocalImageScienceVisualRasterRefinementPlan.model_validate(value)

    validate_science_visual_raster_refinement_plan(
        result=result,
        inventory=inventory,
        raster_suitability_review=review,
        plan=plan,
    )
    assert plan.proposals[0].partition == "TRAIN"

    unsafe = copy.deepcopy(value)
    proposals = unsafe["proposals"]
    assert isinstance(proposals, list)
    proposals[0]["refinement_reasons"] = ["BORDER_TRIM"]
    proposal_body = {key: item for key, item in proposals[0].items() if key != "refinement_id"}
    proposals[0]["refinement_id"] = (
        "imgscivisrefine_" + content_sha256(proposal_body).removeprefix("sha256:")[:32]
    )
    plan_body = {
        key: item
        for key, item in unsafe.items()
        if key not in {"refinement_plan_id", "plan_sha256"}
    }
    unsafe["refinement_plan_id"] = (
        "imgscivisrefineplan_" + content_sha256(plan_body).removeprefix("sha256:")[:32]
    )
    unsafe["plan_sha256"] = content_sha256(
        {key: item for key, item in unsafe.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValueError, match="requires PANEL_SPLIT"):
        validate_science_visual_raster_refinement_plan(
            result=result,
            inventory=inventory,
            raster_suitability_review=review,
            plan=LocalImageScienceVisualRasterRefinementPlan.model_validate(unsafe),
        )


def test_science_micro_probe_binds_all_partitioned_crop_members_and_result() -> None:
    crop_set = LocalImageScienceVisualCropSet.model_validate(_crop_set_value())
    plan = LocalImageScienceLoraMicroProbePlan.model_validate(_science_micro_plan_value())
    command = LocalImageScienceLoraMicroProbeCommand.model_validate(_science_micro_command_value())
    result = LocalImageScienceLoraMicroProbeWorkerResult.model_validate(
        _science_micro_result_value()
    )

    validate_science_micro_probe_plan_sources(plan, crop_set)
    validate_science_micro_probe_worker_result(command, result)
    assert len(plan.training_member_ids) == 12
    assert len(plan.validation_member_ids) == 1
    assert len(plan.holdout_member_ids) == 2


def test_science_micro_evaluation_binds_exact_holdout_and_pairs() -> None:
    crop_set = LocalImageScienceVisualCropSet.model_validate(_crop_set_value())
    plan = LocalImageScienceLoraMicroProbePlan.model_validate(_science_micro_plan_value())
    training_result = LocalImageScienceLoraMicroProbeWorkerResult.model_validate(
        _science_micro_result_value()
    )
    command = LocalImageScienceLoraMicroEvaluationCommand.model_validate(
        _science_micro_evaluation_command_value()
    )
    result = LocalImageScienceLoraMicroEvaluationResult.model_validate(
        _science_micro_evaluation_result_value()
    )

    validate_science_micro_evaluation_command(plan, crop_set, training_result, command)
    validate_science_micro_evaluation_result(command, result)
    assert {value.candidate_id for value in command.cases} == set(plan.holdout_member_ids)
    assert len(result.outputs) == 4


def test_science_micro_probe_rejects_partition_leakage() -> None:
    value = _science_micro_plan_value()
    value["validation_member_ids"] = [value["training_member_ids"][0]]
    body = {key: item for key, item in value.items() if key not in {"probe_id", "plan_sha256"}}
    value["probe_id"] = "imgscimicroprobe_" + content_sha256(body).removeprefix("sha256:")[:32]
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="partitions overlap"):
        LocalImageScienceLoraMicroProbePlan.model_validate(value)


def test_science_visual_crop_set_rejects_repeated_exam_group() -> None:
    value = _crop_set_value()
    value["members"][1]["exam_group_sha256"] = value["members"][0]["exam_group_sha256"]
    body = {
        key: item for key, item in value.items() if key not in {"crop_set_id", "crop_set_sha256"}
    }
    value["crop_set_id"] = "imgsciviscropset_" + content_sha256(body).removeprefix("sha256:")[:32]
    value["crop_set_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "crop_set_sha256"}
    )
    with pytest.raises(ValidationError, match="repeats exam groups"):
        LocalImageScienceVisualCropSet.model_validate(value)


def test_science_visual_v2_rejects_version_mismatch_and_invalid_locator_caps() -> None:
    plan_v2 = LocalImageScienceCorpusVisualPilotPlanV2.model_validate(_plan_v2_value())
    command_v1 = LocalImageScienceCorpusVisualPilotCommand.model_validate(_command_value())
    with pytest.raises(ValueError, match="contract versions differ"):
        validate_science_visual_pilot_command(plan_v2, command_v1)

    value = _plan_v2_value()
    value["locator_policy"]["max_candidates_per_page"] = 8
    value["locator_policy"]["max_candidates_per_source"] = 4
    with pytest.raises(ValidationError, match="source cap is smaller"):
        LocalImageScienceCorpusVisualPilotPlanV2.model_validate(value)


def test_science_visual_v3_requires_coherent_campaign_coordinates() -> None:
    plan_v3 = LocalImageScienceCorpusVisualPilotPlanV3.model_validate(_plan_v3_value())
    command_v3 = LocalImageScienceCorpusVisualPilotCommandV3.model_validate(_command_v3_value())
    validate_science_visual_pilot_command(plan_v3, command_v3)

    value = _plan_v3_value()
    value["campaign_shard_index"] = value["campaign_shard_count"]
    body = {key: item for key, item in value.items() if key not in {"pilot_id", "plan_sha256"}}
    value["pilot_id"] = "imgscivispilot_" + content_sha256(body).removeprefix("sha256:")[:32]
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="shard index"):
        LocalImageScienceCorpusVisualPilotPlanV3.model_validate(value)


def test_science_visual_command_rejects_staged_pdf_drift() -> None:
    plan = LocalImageScienceCorpusVisualPilotPlan.model_validate(_plan_value())
    value = _command_value()
    value["staged_sources"][0]["sha256"] = _sha("f")
    body = {key: item for key, item in value.items() if key not in {"attempt_id", "command_sha256"}}
    identity = content_sha256(body).removeprefix("sha256:")
    value["attempt_id"] = "imgscivisattempt_" + identity[:32]
    value["command_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "command_sha256"}
    )
    command = LocalImageScienceCorpusVisualPilotCommand.model_validate(value)

    with pytest.raises(ValueError, match="staged PDFs differ"):
        validate_science_visual_pilot_command(plan, command)


def test_science_visual_plan_rejects_partition_leakage_and_over_96_sources() -> None:
    leaked = _plan_value()
    leaked_sources = leaked["selected_sources"]
    train_source = next(value for value in leaked_sources if value["partition"] == "TRAIN")
    holdout_source = next(value for value in leaked_sources if value["partition"] == "HOLDOUT")
    for field in ("issuer_type", "administration_year", "grade", "session_label"):
        holdout_source[field] = train_source[field]
    holdout_source["exam_group_sha256"] = train_source["exam_group_sha256"]
    body = {key: value for key, value in leaked.items() if key not in {"pilot_id", "plan_sha256"}}
    identity = content_sha256(body).removeprefix("sha256:")
    leaked["pilot_id"] = "imgscivispilot_" + identity[:32]
    leaked["plan_sha256"] = content_sha256(
        {key: value for key, value in leaked.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="crosses a partition"):
        LocalImageScienceCorpusVisualPilotPlan.model_validate(leaked)

    too_many = _plan_value()
    too_many_sources = [
        _source(index, "TRAIN" if index < 88 else "VALIDATION" if index < 93 else "HOLDOUT")
        for index in range(97)
    ]
    too_many_sources.sort(key=lambda value: value["document_id"])
    too_many["selected_sources"] = too_many_sources
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("science-corpus-visual-pilot-plan", too_many)


def test_science_visual_result_rejects_unplanned_page_and_duplicate_crop() -> None:
    plan = LocalImageScienceCorpusVisualPilotPlan.model_validate(_plan_value())
    value = _result_value()
    value["page_images"][0]["physical_page"] = 2
    value["page_images"][0]["member_path"] = (
        f"pages/{value['page_images'][0]['document_id']}/page-2.png"
    )
    changed_document = value["page_images"][0]["document_id"]
    value["visual_candidates"] = [
        candidate
        for candidate in value["visual_candidates"]
        if candidate["document_id"] != changed_document
    ]
    body = {key: item for key, item in value.items() if key != "result_sha256"}
    value["result_sha256"] = content_sha256(body)
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(value)
    with pytest.raises(ValueError, match="does not render every selected page"):
        validate_science_visual_pilot_result(plan, result)

    duplicate = _result_value()
    duplicate["visual_candidates"][1]["sha256"] = duplicate["visual_candidates"][0]["sha256"]
    duplicate["result_sha256"] = content_sha256(
        {key: item for key, item in duplicate.items() if key != "result_sha256"}
    )
    with pytest.raises(ValidationError, match="repeat crop bytes"):
        LocalImageScienceCorpusVisualPilotResult.model_validate(duplicate)


def test_science_visual_result_v2_rejects_locator_candidate_caps() -> None:
    plan_value = _plan_v2_value()
    plan_value["locator_policy"]["max_candidates_per_page"] = 2
    plan_value["locator_policy"]["max_candidates_per_source"] = 2
    plan_body = {
        key: item for key, item in plan_value.items() if key not in {"pilot_id", "plan_sha256"}
    }
    plan_identity = content_sha256(plan_body).removeprefix("sha256:")
    plan_value["pilot_id"] = "imgscivispilot_" + plan_identity[:32]
    plan_value["plan_sha256"] = content_sha256(
        {key: item for key, item in plan_value.items() if key != "plan_sha256"}
    )
    plan = LocalImageScienceCorpusVisualPilotPlanV2.model_validate(plan_value)

    result_value = _result_value()
    result_value["pilot_id"] = plan.pilot_id
    result_value["plan_sha256"] = plan.plan_sha256
    first = copy.deepcopy(result_value["visual_candidates"][0])
    additions = []
    for offset in (100, 200):
        candidate_body = {
            key: item
            for key, item in first.items()
            if key not in {"candidate_id", "member_path", "sha256", "size_bytes"}
        }
        candidate_body["bounding_box"] = {
            "left": 1000 + offset,
            "top": 1200,
            "right": 8000,
            "bottom": 7200,
        }
        candidate_identity = content_sha256(candidate_body).removeprefix("sha256:")
        candidate_id = "imgsciviscandidate_" + candidate_identity[:32]
        additions.append(
            {
                "candidate_id": candidate_id,
                **candidate_body,
                "member_path": f"crops/{candidate_id}.png",
                "sha256": "sha256:" + f"{offset + 900:064x}",
                "size_bytes": 5000 + offset,
            }
        )
    result_value["visual_candidates"].extend(additions)
    result_value["visual_candidates"].sort(key=lambda item: item["candidate_id"])
    result_value["result_sha256"] = content_sha256(
        {key: item for key, item in result_value.items() if key != "result_sha256"}
    )
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)

    with pytest.raises(ValueError, match="exceeds locator limits"):
        validate_science_visual_pilot_result(plan, result)


def test_science_visual_inventory_rejects_authoritative_lora_and_missing_review() -> None:
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(_result_value())
    value = _inventory_value()
    authoritative_id = next(
        candidate.candidate_id
        for candidate in result.visual_candidates
        if candidate.authority_class == "AUTHORITATIVE_DETERMINISTIC_GEOMETRY"
    )
    review = next(item for item in value["reviews"] if item["candidate_id"] == authoritative_id)
    review.update(
        {
            "decision": "LORA_ELIGIBLE",
            "pattern_family": "ORGANISM",
            "caption_en": "black and white organism illustration",
            "caption_sha256": text_sha256("black and white organism illustration"),
        }
    )
    value["lora_eligible_count"] = 11
    value["deterministic_renderer_count"] = 1
    value["primitive_recommendations"] = []
    body = {
        key: item for key, item in value.items() if key not in {"inventory_id", "inventory_sha256"}
    }
    identity = content_sha256(body).removeprefix("sha256:")
    value["inventory_id"] = "imgscivisinventory_" + identity[:32]
    value["inventory_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "inventory_sha256"}
    )
    inventory = LocalImageScienceVisualPatternInventory.model_validate(value)
    with pytest.raises(ValueError, match="authoritative content"):
        validate_science_visual_pattern_inventory(result, inventory)

    missing = LocalImageScienceVisualPatternInventory.model_validate(_inventory_value())
    shortened = copy.deepcopy(missing.model_dump(mode="json"))
    shortened["reviews"] = shortened["reviews"][:-1]
    shortened["lora_eligible_count"] -= 1
    body = {
        key: item
        for key, item in shortened.items()
        if key not in {"inventory_id", "inventory_sha256"}
    }
    identity = content_sha256(body).removeprefix("sha256:")
    shortened["inventory_id"] = "imgscivisinventory_" + identity[:32]
    shortened["inventory_sha256"] = content_sha256(
        {key: item for key, item in shortened.items() if key != "inventory_sha256"}
    )
    partial = LocalImageScienceVisualPatternInventory.model_validate(shortened)
    with pytest.raises(ValueError, match="every candidate exactly once"):
        validate_science_visual_pattern_inventory(result, partial)


def test_science_visual_inventory_v2_keeps_file_and_semantic_hashes_distinct() -> None:
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(_result_value())
    inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(_inventory_v2_value())
    assert inventory.pilot_result_file_sha256 == inventory.pilot_result.sha256
    assert inventory.pilot_result_file_sha256 != inventory.pilot_result_semantic_sha256
    validate_science_visual_pattern_inventory_v2(result, inventory)

    wrong_semantic = copy.deepcopy(_inventory_v2_value())
    wrong_semantic["pilot_result_semantic_sha256"] = _sha("8")
    body = {
        key: item
        for key, item in wrong_semantic.items()
        if key not in {"inventory_id", "inventory_sha256"}
    }
    identity = content_sha256(body).removeprefix("sha256:")
    wrong_semantic["inventory_id"] = "imgscivisinventory_" + identity[:32]
    wrong_semantic["inventory_sha256"] = content_sha256(
        {key: item for key, item in wrong_semantic.items() if key != "inventory_sha256"}
    )
    invalid = LocalImageScienceVisualPatternInventoryV2.model_validate(wrong_semantic)
    with pytest.raises(ValueError, match="successful pilot result"):
        validate_science_visual_pattern_inventory_v2(result, invalid)

    wrong_file = copy.deepcopy(_inventory_v2_value())
    wrong_file["pilot_result_file_sha256"] = _sha("8")
    with pytest.raises(ValidationError, match="file hash differs"):
        LocalImageScienceVisualPatternInventoryV2.model_validate(wrong_file)


def test_science_visual_inventory_v2_allows_human_classification_of_unknown_candidates() -> None:
    result_value = _result_value()
    first_candidate = result_value["visual_candidates"][0]
    first_candidate["authority_class"] = "UNKNOWN_REVIEW_REQUIRED"
    first_candidate["representation_kind"] = "UNKNOWN"
    first_candidate["rendering_mode"] = "MIXED"
    identity_body = {
        key: item
        for key, item in first_candidate.items()
        if key not in {"candidate_id", "member_path", "sha256", "size_bytes"}
    }
    identity = content_sha256(identity_body).removeprefix("sha256:")
    previous_id = first_candidate["candidate_id"]
    first_candidate["candidate_id"] = "imgsciviscandidate_" + identity[:32]
    first_candidate["member_path"] = f"crops/{first_candidate['candidate_id']}.png"
    result_value["visual_candidates"].sort(key=lambda item: item["candidate_id"])
    result_value["result_sha256"] = content_sha256(
        {key: item for key, item in result_value.items() if key != "result_sha256"}
    )
    result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)

    inventory_value = _inventory_v2_value()
    review = next(
        item for item in inventory_value["reviews"] if item["candidate_id"] == previous_id
    )
    review["candidate_id"] = first_candidate["candidate_id"]
    inventory_value["reviews"].sort(key=lambda item: item["candidate_id"])
    inventory_value["pilot_result_semantic_sha256"] = result.result_sha256
    body = {
        key: item
        for key, item in inventory_value.items()
        if key not in {"inventory_id", "inventory_sha256"}
    }
    inventory_value["inventory_id"] = (
        "imgscivisinventory_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    inventory_value["inventory_sha256"] = content_sha256(
        {key: item for key, item in inventory_value.items() if key != "inventory_sha256"}
    )
    inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(inventory_value)
    validate_science_visual_pattern_inventory_v2(result, inventory)


def test_science_visual_schema_mirrors_are_exact_and_hash_pinned() -> None:
    expected = {
        "local-image-science-corpus-training-authorization-v1.schema.json": (
            "8f84ee0e5485e01a04dd1746a2baa2210aaeb9e0f5182755a198402149d895e2"
        ),
        "local-image-science-corpus-visual-pilot-plan-v1.schema.json": (
            "76a48e59f9d9fb9777467bf8466f915a7cface0d04a0383bdb68ec4dea2f4708"
        ),
        "local-image-science-corpus-visual-pilot-plan-v2.schema.json": (
            "90b6e463e31978d63d95ea045cec6a5b6ca7b4bb5c91e6f417eea83203af4057"
        ),
        "local-image-science-corpus-visual-pilot-plan-v3.schema.json": (
            "cf3e1ad771eba8ffb32a62f367970955f3aea74109dd519debc01504b77add4b"
        ),
        "local-image-science-corpus-visual-pilot-command-v1.schema.json": (
            "9093b8e0c621cd12e978570eb1e5582097a8a70a73628b6fe182dfdaed3b8090"
        ),
        "local-image-science-corpus-visual-pilot-command-v2.schema.json": (
            "5dae2e101d539b2eabbe40abaa96d91e0e850eab08cf437d51f696b6f424b4cc"
        ),
        "local-image-science-corpus-visual-pilot-command-v3.schema.json": (
            "953143fe884c4ff39c7a3cfe9c66d1337c153433dc5ce9d2c9deeac755e706c6"
        ),
        "local-image-science-corpus-visual-pilot-result-v1.schema.json": (
            "8b2dccc1f567922917912eb5025e1fbf9256f2361e4ac6918602c504749246a1"
        ),
        "local-image-science-visual-pattern-inventory-v1.schema.json": (
            "191235a93c0b53830cb54e34341f2f893b570510624ac1486e76be16270a3fb4"
        ),
        "local-image-science-visual-pattern-inventory-v2.schema.json": (
            "e2c89de1a67b461a7eb0c6e59a7fdcb9d9dae95e597fa80c6b989e02021ba646"
        ),
        "local-image-science-visual-campaign-pattern-inventory-v1.schema.json": (
            "912839c7fa1cdda4701c1a1aecf865f1fc94368510863de64a1b3e7b1b538b1b"
        ),
        "local-image-science-visual-campaign-review-batch-command-v1.schema.json": (
            "f62d1ee93dcd4125634ac4ddd1d89edb1b11c3f6f19fd197b94b13164bd375fd"
        ),
        "local-image-science-visual-campaign-review-batch-result-v1.schema.json": (
            "c81561b3de9fc99fc198a3bae61ffe5d4423263804d07440aa7195973722652d"
        ),
        "local-image-science-visual-crop-set-v1.schema.json": (
            "bc3f82e49d96dc6fe467d659c700c6a9bd12d044873b806d4b6017a8bde4d574"
        ),
        "local-image-science-lora-micro-probe-plan-v1.schema.json": (
            "70629fa7c1c2d427ace089cdfd0089c0f110e28a10627499da2ed1d1c5f5e1f8"
        ),
        "local-image-science-lora-micro-probe-command-v1.schema.json": (
            "d4ab0f2f962f84c18422b32030ac13feb5fd82e5036e0e8f8348b2fad5f7aae6"
        ),
        "local-image-science-lora-micro-adapter-manifest-v1.schema.json": (
            "fab3939a63f27123811c129335841e2a927bc88757828708775de599a84d1d8e"
        ),
        "local-image-science-lora-micro-probe-worker-result-v1.schema.json": (
            "4dc0aa5f491448d27f24c652250bdb3eed7098a9d590fa7bc262dd3215876080"
        ),
        "local-image-science-lora-micro-evaluation-command-v1.schema.json": (
            "715e3f8495698b9e3db7601ec954a38774011ab67a649c19190e9bfe6774b019"
        ),
        "local-image-science-lora-micro-evaluation-result-v1.schema.json": (
            "2477a3f12e6396b3224d1812ce84d513eec607a768cb69f3f66d78ceafe76399"
        ),
    }
    for filename, digest in expected.items():
        canonical = ROOT / "schemas" / "image-provider" / filename
        packaged = (
            ROOT / "packages" / "image_contracts" / "eom_image_contracts" / "schemas" / filename
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        assert hashlib.sha256(canonical.read_bytes()).hexdigest() == digest
