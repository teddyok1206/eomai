from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotCommand,
    LocalImageScienceCorpusVisualPilotPlan,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceVisualPatternInventory,
    content_sha256,
    text_sha256,
    validate_contract,
    validate_science_visual_authorization_plan,
    validate_science_visual_pattern_inventory,
    validate_science_visual_pilot_command,
    validate_science_visual_pilot_result,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

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
            "science-corpus-visual-pilot-command",
            LocalImageScienceCorpusVisualPilotCommand,
            _command_value,
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
    assert authorization.authorization_sha256 != plan.training_authorization.sha256
    assert (
        content_sha256(authorization.model_dump(mode="json")) == plan.training_authorization.sha256
    )


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


def test_science_visual_schema_mirrors_are_exact_and_hash_pinned() -> None:
    expected = {
        "local-image-science-corpus-training-authorization-v1.schema.json": (
            "8f84ee0e5485e01a04dd1746a2baa2210aaeb9e0f5182755a198402149d895e2"
        ),
        "local-image-science-corpus-visual-pilot-plan-v1.schema.json": (
            "76a48e59f9d9fb9777467bf8466f915a7cface0d04a0383bdb68ec4dea2f4708"
        ),
        "local-image-science-corpus-visual-pilot-command-v1.schema.json": (
            "9093b8e0c621cd12e978570eb1e5582097a8a70a73628b6fe182dfdaed3b8090"
        ),
        "local-image-science-corpus-visual-pilot-result-v1.schema.json": (
            "8b2dccc1f567922917912eb5025e1fbf9256f2361e4ac6918602c504749246a1"
        ),
        "local-image-science-visual-pattern-inventory-v1.schema.json": (
            "191235a93c0b53830cb54e34341f2f893b570510624ac1486e76be16270a3fb4"
        ),
    }
    for filename, digest in expected.items():
        canonical = ROOT / "schemas" / "image-provider" / filename
        packaged = (
            ROOT / "packages" / "image_contracts" / "eom_image_contracts" / "schemas" / filename
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        assert hashlib.sha256(canonical.read_bytes()).hexdigest() == digest
