from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from eom_catalog_service.science_visual_subject_benchmark import (
    build_science_visual_subject_benchmark_plan,
)
from eom_catalog_service.science_visual_subject_multiseed import (
    build_science_visual_subject_multiseed_plan,
)
from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    LocalImageScienceVisualSubjectBenchmarkCommand,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkResult,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
    LocalImageScienceVisualSubjectMultiseedCommand,
    LocalImageScienceVisualSubjectMultiseedPlan,
    LocalImageScienceVisualSubjectMultiseedResult,
    LocalImageScienceVisualSubjectMultiseedReview,
    ScienceVisualSubject,
    ScienceVisualSubjectBenchmarkCase,
    ScienceVisualSubjectBenchmarkOutcome,
    ScienceVisualSubjectBenchmarkOutput,
    ScienceVisualSubjectMultiseedCase,
    ScienceVisualSubjectMultiseedOutput,
    ScienceVisualSubjectMultiseedReviewEntry,
    ScienceVisualSubjectOmission,
    ScienceVisualSubjectQualityReviewEntry,
    ScienceVisualSubjectSeedEvaluation,
    ScienceVisualSubjectSourceReference,
    content_json_bytes,
    content_sha256,
    science_subject_multiseed_value,
    text_sha256,
    validate_contract,
    validate_science_visual_subject_benchmark_plan,
    validate_science_visual_subject_benchmark_result,
    validate_science_visual_subject_benchmark_review,
    validate_science_visual_subject_multiseed_plan,
    validate_science_visual_subject_multiseed_result,
    validate_science_visual_subject_multiseed_review,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 27, 1, 2, 3, tzinfo=UTC)


def _pointer(
    token: str,
    *,
    schema_ref: str,
    member_path: str,
    sha256: str | None = None,
) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=f"artifact_{token * 32}",
        artifact_revision_id=f"rev_{token * 32}",
        member_path=member_path,
        schema_ref=schema_ref,
        media_type="application/json",
        sha256=sha256 or f"sha256:{token * 64}",
    )


def _reference(token: str) -> ScienceVisualSubjectSourceReference:
    return ScienceVisualSubjectSourceReference(
        item_revision_id=f"itemrev_{token * 32}",
        accepted_analysis_result=_pointer(
            token,
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/9.0",
            member_path="normalized/accepted-result.json",
        ),
        extraction_result=_pointer(
            token,
            schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
            member_path="normalized/result.json",
        ),
        item_proposal_id=f"itemproposal_{token * 32}",
        visual_pattern_id=f"visualpattern_{token * 32}",
        source_anchor_ids=(f"assessmentanchor_{token * 32}",),
        representation_kind="PHOTOGRAPH" if token == "1" else "DIAGRAM",
        rendering_mode="RASTER" if token == "1" else "VECTOR_LIKE",
        composition_summary_sha256=f"sha256:{token * 64}",
        reconstruction_guidance_sha256=f"sha256:{token * 64}",
    )


def _subject(
    key: str,
    *,
    token: str,
    route: str,
    primitive: str | None,
    prompt: str | None,
) -> ScienceVisualSubject:
    subject_id = "imgscisubject_" + content_sha256(key).removeprefix("sha256:")[:32]
    return ScienceVisualSubject.model_validate(
        {
            "subject_id": subject_id,
            "subject_key": key,
            "label_ko": "화석" if key == "FOSSIL_TEXTURE" else "사람",
            "label_en": "fossil texture" if key == "FOSSIL_TEXTURE" else "human figure",
            "aliases_ko": ("삼엽충", "화석") if key == "FOSSIL_TEXTURE" else ("사람", "학생"),
            "family": "EARTH_SPACE" if key == "FOSSIL_TEXTURE" else "REAL_WORLD_SCENE",
            "render_route": route,
            "renderer_primitive": primitive,
            "raster_prompt_en": prompt,
            "raster_prompt_sha256": None if prompt is None else text_sha256(prompt),
            "blocked_reason": None,
            "references": (_reference(token),),
        }
    )


def _inventory() -> LocalImageScienceVisualSubjectInventory:
    fossil = _subject(
        "FOSSIL_TEXTURE",
        token="1",
        route="LORA_RASTER",
        primitive=None,
        prompt=(
            "monochrome Korean science assessment illustration of a compact trilobite fossil, "
            "plain white background, clean contour, no text"
        ),
    )
    human = _subject(
        "HUMAN_FIGURE",
        token="2",
        route="PYTHON_SVG",
        primitive="GENERIC_LABELLED_DIAGRAM",
        prompt=None,
    )
    body = {
        "schema_version": "local-image-science-visual-subject-inventory/1.0",
        "inventory_id": "imgscisubjectinventory_" + "3" * 32,
        "inventory_revision_id": "imgscisubjectinventoryrev_" + "4" * 32,
        "revision_number": 1,
        "previous_revision_id": None,
        "training_authorization": _pointer(
            "5",
            schema_ref="eom://schemas/image-provider/local-image-training-authorization/1.0",
            member_path="manifests/training-authorization.json",
        ).model_dump(mode="json"),
        "pattern_inventory": _pointer(
            "6",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-visual-campaign-pattern-inventory/1.0"
            ),
            member_path="manifests/science-visual-campaign-pattern-inventory.json",
        ).model_dump(mode="json"),
        "target_set_sha256": "sha256:" + "7" * 64,
        "source_item_count": 520,
        "source_visual_observation_count": 3,
        "covered_visual_observation_count": 2,
        "subjects": tuple(
            subject.model_dump(mode="json")
            for subject in sorted((fossil, human), key=lambda value: value.subject_key)
        ),
        "omissions": (
            ScienceVisualSubjectOmission(
                item_revision_id="itemrev_" + "9" * 32,
                item_proposal_id="itemproposal_" + "9" * 32,
                visual_pattern_id="visualpattern_" + "9" * 32,
                reason="NO_RENDERED_SUBJECT",
            ).model_dump(mode="json"),
        ),
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "created_by": "contract_test",
    }
    return LocalImageScienceVisualSubjectInventory.model_validate(
        {**body, "inventory_sha256": content_sha256(body)}
    )


def _case(
    subject: ScienceVisualSubject,
    *,
    kind: str,
    prompt: str | None,
    negative: str | None,
    seed: int | None,
    expected: str,
) -> ScienceVisualSubjectBenchmarkCase:
    case_id = (
        "imgscisubjectcase_"
        + content_sha256({"subject_id": subject.subject_id, "case_kind": kind}).removeprefix(
            "sha256:"
        )[:32]
    )
    return ScienceVisualSubjectBenchmarkCase.model_validate(
        {
            "case_id": case_id,
            "subject_id": subject.subject_id,
            "render_route": subject.render_route,
            "case_kind": kind,
            "prompt_en": prompt,
            "prompt_sha256": None if prompt is None else text_sha256(prompt),
            "negative_prompt_en": negative,
            "negative_prompt_sha256": None if negative is None else text_sha256(negative),
            "seed": seed,
            "renderer_primitive": subject.renderer_primitive,
            "expected_outcome": expected,
        }
    )


def _plan(
    inventory: LocalImageScienceVisualSubjectInventory,
) -> LocalImageScienceVisualSubjectBenchmarkPlan:
    by_key = {subject.subject_key: subject for subject in inventory.subjects}
    fossil = by_key["FOSSIL_TEXTURE"]
    human = by_key["HUMAN_FIGURE"]
    cases = (
        _case(
            fossil,
            kind="QUALITY",
            prompt=fossil.raster_prompt_en,
            negative="color, text, watermark, human",
            seed=73,
            expected="BASE_ADAPTER_PAIR",
        ),
        _case(
            human,
            kind="ROUTE",
            prompt=None,
            negative=None,
            seed=None,
            expected="DETERMINISTIC_RENDERED",
        ),
        _case(
            human,
            kind="GPU_POLICY_NEGATIVE",
            prompt="a realistic human student standing in a science laboratory",
            negative="color, text, watermark",
            seed=91,
            expected="POLICY_REJECTED",
        ),
    )
    inventory_sha = content_sha256(inventory.model_dump(mode="json"))
    base = {
        "schema_version": "local-image-science-visual-subject-benchmark-plan/1.0",
        "subject_inventory": _pointer(
            "a",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0"
            ),
            member_path="manifests/science-visual-subject-inventory.json",
            sha256=inventory_sha,
        ).model_dump(mode="json"),
        "subject_inventory_sha256": inventory_sha,
        "base_model": {
            "model_id": "imgmodel_" + "b" * 32,
            "model_revision_id": "imgmodelrev_" + "b" * 32,
            "manifest_sha256": "sha256:" + "b" * 64,
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        },
        "adapter_manifest": _pointer(
            "c",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
            ),
            member_path="manifests/adapter-manifest.json",
        ).model_dump(mode="json"),
        "generation_width_px": 800,
        "generation_height_px": 504,
        "delivery_width_px": 800,
        "delivery_height_px": 500,
        "inference_steps": 25,
        "guidance_scale_milli": 7500,
        "cases": tuple(
            case.model_dump(mode="json") for case in sorted(cases, key=lambda value: value.case_id)
        ),
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "created_by": "contract_test",
    }
    identity = content_sha256(
        {key: value for key, value in base.items() if key not in {"created_at", "created_by"}}
    ).removeprefix("sha256:")[:32]
    with_id = {**base, "plan_id": f"imgscisubjectbenchmark_{identity}"}
    return LocalImageScienceVisualSubjectBenchmarkPlan.model_validate(
        {**with_id, "plan_sha256": content_sha256(with_id)}
    )


def _adapter_manifest() -> LocalImageScienceCampaignLoraMicroAdapterManifestV2:
    body = {
        "schema_version": "local-image-science-campaign-lora-micro-adapter-manifest/1.1",
        "adapter_id": "imgadapter_" + "1" * 32,
        "adapter_revision_id": "imgadapterrev_" + "2" * 32,
        "state": "EVALUATION_ONLY",
        "activation_policy": "FORBIDDEN",
        "base_model": {
            "model_id": "imgmodel_" + "3" * 32,
            "model_revision_id": "imgmodelrev_" + "4" * 32,
            "manifest_sha256": "sha256:" + "5" * 64,
            "provider_family": "diffusers-ssd-1b",
            "runtime_contract_version": "eom-local-image-provider/1.0",
        },
        "probe_plan": _pointer(
            "6",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-campaign-lora-micro-probe-plan/1.1"
            ),
            member_path="manifests/science-campaign-micro-probe-plan.json",
        ).model_dump(mode="json"),
        "sample_set_sha256": "sha256:" + "7" * 64,
        "files": (
            {
                "relative_path": "adapter_config.json",
                "size_bytes": 100,
                "sha256": "sha256:" + "8" * 64,
            },
            {
                "relative_path": "adapter_model.safetensors",
                "size_bytes": 1000,
                "sha256": "sha256:" + "9" * 64,
            },
        ),
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    return LocalImageScienceCampaignLoraMicroAdapterManifestV2.model_validate(
        {**body, "manifest_sha256": content_sha256(body)}
    )


def _command(
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
) -> LocalImageScienceVisualSubjectBenchmarkCommand:
    base = {
        "schema_version": "local-image-science-visual-subject-benchmark-command/1.0",
        "plan": _pointer(
            "d",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-plan/1.0"
            ),
            member_path="manifests/science-visual-subject-benchmark-plan.json",
            sha256=content_sha256(plan.model_dump(mode="json")),
        ).model_dump(mode="json"),
        "plan_sha256": plan.plan_sha256,
        "staged_plan_path": "inputs/subject-benchmark-plan.json",
        "staged_subject_inventory_path": "inputs/science-visual-subject-inventory.json",
        "staged_adapter_manifest_path": "inputs/adapter/adapter-manifest.json",
        "staged_adapter_model_path": "inputs/adapter/adapter_model.safetensors",
        "staged_adapter_config_path": "inputs/adapter/adapter_config.json",
        "output_directory": "outputs",
        "source_commit": "f" * 40,
    }
    identity = content_sha256(base).removeprefix("sha256:")[:32]
    with_id = {**base, "run_id": f"imgscisubjectbenchmarkrun_{identity}"}
    return LocalImageScienceVisualSubjectBenchmarkCommand.model_validate(
        {**with_id, "command_sha256": content_sha256(with_id)}
    )


def _result(
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    command: LocalImageScienceVisualSubjectBenchmarkCommand,
) -> LocalImageScienceVisualSubjectBenchmarkResult:
    outputs: list[ScienceVisualSubjectBenchmarkOutput] = []
    outcomes: list[ScienceVisualSubjectBenchmarkOutcome] = []
    for case in plan.cases:
        outcomes.append(
            ScienceVisualSubjectBenchmarkOutcome(
                case_id=case.case_id,
                outcome=case.expected_outcome,
                stable_code=(
                    "LOCAL_IMAGE_HUMAN_SUBJECT_FORBIDDEN"
                    if case.expected_outcome == "POLICY_REJECTED"
                    else None
                ),
            )
        )
        variants = (
            ("BASE", "ADAPTER")
            if case.expected_outcome == "BASE_ADAPTER_PAIR"
            else ("DETERMINISTIC",)
            if case.expected_outcome == "DETERMINISTIC_RENDERED"
            else ()
        )
        for variant in variants:
            outputs.append(
                ScienceVisualSubjectBenchmarkOutput(
                    case_id=case.case_id,
                    variant=variant,
                    relative_path=f"outputs/{case.case_id}-{variant.lower()}.png",
                    media_type="image/png",
                    bytes=100,
                    sha256="sha256:" + ("e" if variant == "BASE" else "f") * 64,
                    width_px=800,
                    height_px=500,
                )
            )
    body = {
        "schema_version": "local-image-science-visual-subject-benchmark-result/1.0",
        "run_id": command.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "command_sha256": command.command_sha256,
        "status": "SUCCEEDED",
        "error_code": None,
        "outcomes": tuple(
            value.model_dump(mode="json")
            for value in sorted(outcomes, key=lambda item: item.case_id)
        ),
        "outputs": tuple(
            value.model_dump(mode="json")
            for value in sorted(outputs, key=lambda item: (item.case_id, item.variant))
        ),
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "completed_at": (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
    }
    return LocalImageScienceVisualSubjectBenchmarkResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )


def _review(
    inventory: LocalImageScienceVisualSubjectInventory,
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    result: LocalImageScienceVisualSubjectBenchmarkResult,
) -> LocalImageScienceVisualSubjectBenchmarkReview:
    cases_by_subject: dict[str, list[str]] = {}
    for case in plan.cases:
        cases_by_subject.setdefault(case.subject_id, []).append(case.case_id)
    entries = []
    for subject in inventory.subjects:
        if subject.subject_key == "HUMAN_FIGURE":
            entry = ScienceVisualSubjectQualityReviewEntry(
                subject_id=subject.subject_id,
                subject_key=subject.subject_key,
                render_route=subject.render_route,
                benchmark_case_ids=tuple(sorted(cases_by_subject[subject.subject_id])),
                quality_status="DIAGNOSTIC_ONLY",
                preferred_variant=None,
                failure_reasons=("PRODUCTION_PATH_NOT_EXERCISED",),
                next_actions=("BUILD_PRODUCTION_VECTOR_FIXTURE",),
            )
        else:
            entry = ScienceVisualSubjectQualityReviewEntry(
                subject_id=subject.subject_id,
                subject_key=subject.subject_key,
                render_route=subject.render_route,
                benchmark_case_ids=tuple(sorted(cases_by_subject[subject.subject_id])),
                quality_status="BASE_PREFERRED",
                preferred_variant="BASE",
                failure_reasons=("ADAPTER_SEMANTIC_MISMATCH",),
                next_actions=("KEEP_BASE_ONLY", "MULTI_SEED_REEVALUATION"),
            )
        entries.append(entry)
    reviews = tuple(sorted(entries, key=lambda value: value.subject_key))
    benchmark_plan = _pointer(
        "1",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-plan/1.0"
        ),
        member_path="manifests/science-visual-subject-benchmark-plan.json",
        sha256=content_sha256(plan.model_dump(mode="json")),
    )
    benchmark_result = _pointer(
        "2",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-result/1.0"
        ),
        member_path="result.json",
        sha256=content_sha256(result.model_dump(mode="json")),
    )
    identity_body = {
        "subject_inventory": plan.subject_inventory.model_dump(mode="json"),
        "benchmark_plan": benchmark_plan.model_dump(mode="json"),
        "benchmark_result": benchmark_result.model_dump(mode="json"),
        "benchmark_result_sha256": result.result_sha256,
        "reviews": [entry.model_dump(mode="json") for entry in reviews],
    }
    body = {
        "schema_version": "local-image-science-visual-subject-benchmark-review/1.0",
        "review_id": (
            "imgscisubjectreview_" + content_sha256(identity_body).removeprefix("sha256:")[:32]
        ),
        **identity_body,
        "diagnostic_only_count": 1,
        "base_preferred_count": 1,
        "adapter_preferred_count": 0,
        "neither_acceptable_count": 0,
        "adapter_activation_recommendation": "FORBIDDEN",
        "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
        "reviewed_by": "contract_test",
    }
    return LocalImageScienceVisualSubjectBenchmarkReview.model_validate(
        {**body, "review_sha256": content_sha256(body)}
    )


def test_subject_inventory_and_benchmark_round_trip_through_both_contract_layers() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    command = _command(plan)
    result = _result(plan, command)

    validate_contract("science-visual-subject-inventory", inventory.model_dump(mode="json"))
    validate_contract("science-visual-subject-benchmark-plan", plan.model_dump(mode="json"))
    validate_contract("science-visual-subject-benchmark-command", command.model_dump(mode="json"))
    validate_contract("science-visual-subject-benchmark-result", result.model_dump(mode="json"))
    validate_science_visual_subject_benchmark_plan(inventory, plan)
    validate_science_visual_subject_benchmark_result(plan, command, result)


def test_subject_quality_review_closes_exact_subject_and_case_population() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    command = _command(plan)
    result = _result(plan, command)
    review = _review(inventory, plan, result)

    validate_contract("science-visual-subject-benchmark-review", review.model_dump(mode="json"))
    validate_science_visual_subject_benchmark_review(inventory, plan, result, review)
    assert review.adapter_activation_recommendation == "FORBIDDEN"


def test_subject_quality_review_rejects_missing_subject() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    result = _result(plan, _command(plan))
    review = _review(inventory, plan, result)
    value = review.model_dump(mode="json")
    value["reviews"] = value["reviews"][:-1]
    value["diagnostic_only_count"] = 0
    identity_body = {
        key: value[key]
        for key in (
            "subject_inventory",
            "benchmark_plan",
            "benchmark_result",
            "benchmark_result_sha256",
            "reviews",
        )
    }
    value["review_id"] = (
        "imgscisubjectreview_" + content_sha256(identity_body).removeprefix("sha256:")[:32]
    )
    value["review_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "review_sha256"}
    )
    parsed = LocalImageScienceVisualSubjectBenchmarkReview.model_validate(value)
    with pytest.raises(ValueError, match="population mismatch"):
        validate_science_visual_subject_benchmark_review(inventory, plan, result, parsed)


def test_subject_quality_review_rejects_diagnostic_as_production_variant() -> None:
    with pytest.raises(ValidationError, match="status, route, variant"):
        ScienceVisualSubjectQualityReviewEntry(
            subject_id="imgscisubject_" + "1" * 32,
            subject_key="HUMAN_FIGURE",
            render_route="PYTHON_SVG",
            benchmark_case_ids=("imgscisubjectcase_" + "2" * 32,),
            quality_status="DIAGNOSTIC_ONLY",
            preferred_variant="BASE",
            failure_reasons=("PRODUCTION_PATH_NOT_EXERCISED",),
            next_actions=("BUILD_PRODUCTION_VECTOR_FIXTURE",),
        )


def _multiseed_initials() -> tuple[
    LocalImageScienceVisualSubjectInventory,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkReview,
]:
    inventory = _inventory()
    adapter = _adapter_manifest()
    inventory_pointer = _pointer(
        "a",
        schema_ref="eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0",
        member_path="manifests/science-visual-subject-inventory.json",
        sha256=content_sha256(inventory.model_dump(mode="json")),
    )
    adapter_pointer = _pointer(
        "b",
        schema_ref=(
            "eom://schemas/image-provider/"
            "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
        ),
        member_path="manifests/adapter-manifest.json",
        sha256=content_sha256(adapter.model_dump(mode="json")),
    )
    initial_plan = build_science_visual_subject_benchmark_plan(
        inventory=inventory,
        inventory_pointer=inventory_pointer,
        adapter_manifest=adapter,
        adapter_manifest_pointer=adapter_pointer,
        created_at=NOW,
        created_by="contract_test",
    )
    initial_result = _result(initial_plan, _command(initial_plan))
    initial_review = _review(inventory, initial_plan, initial_result)
    return inventory, initial_plan, initial_review


def _multiseed_plan(
    inventory: LocalImageScienceVisualSubjectInventory,
    initial_plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    initial_review: LocalImageScienceVisualSubjectBenchmarkReview,
) -> LocalImageScienceVisualSubjectMultiseedPlan:
    subjects = {
        value.subject_id: value
        for value in inventory.subjects
        if value.render_route in {"HYBRID", "LORA_RASTER"}
    }
    originals = {
        value.subject_id: value for value in initial_plan.cases if value.case_kind == "QUALITY"
    }
    cases = []
    for subject_id, subject in subjects.items():
        original = originals[subject_id]
        assert subject.raster_prompt_en is not None
        assert original.negative_prompt_en is not None
        for ordinal in (1, 2):
            seed = science_subject_multiseed_value(subject.subject_key, ordinal)
            identity = content_sha256(
                {"seed": seed, "seed_ordinal": ordinal, "subject_id": subject.subject_id}
            ).removeprefix("sha256:")[:32]
            cases.append(
                ScienceVisualSubjectMultiseedCase(
                    case_id=f"imgscisubjectseedcase_{identity}",
                    subject_id=subject.subject_id,
                    subject_key=subject.subject_key,
                    render_route=subject.render_route,
                    seed_ordinal=ordinal,
                    seed=seed,
                    prompt_en=subject.raster_prompt_en,
                    prompt_sha256=text_sha256(subject.raster_prompt_en),
                    negative_prompt_en=original.negative_prompt_en,
                    negative_prompt_sha256=text_sha256(original.negative_prompt_en),
                )
            )
    body = {
        "schema_version": "local-image-science-visual-subject-multiseed-plan/1.0",
        "subject_inventory": initial_plan.subject_inventory.model_dump(mode="json"),
        "initial_benchmark_plan": initial_review.benchmark_plan.model_dump(mode="json"),
        "initial_quality_review": _pointer(
            "4",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-visual-subject-benchmark-review/1.0"
            ),
            member_path="manifests/science-visual-subject-benchmark-review.json",
            sha256=content_sha256(initial_review.model_dump(mode="json")),
        ).model_dump(mode="json"),
        "base_model": initial_plan.base_model.model_dump(mode="json"),
        "adapter_manifest": initial_plan.adapter_manifest.model_dump(mode="json"),
        "generation_width_px": 800,
        "generation_height_px": 504,
        "delivery_width_px": 800,
        "delivery_height_px": 500,
        "inference_steps": 20,
        "guidance_scale_milli": 7500,
        "seeds_per_subject": 2,
        "cases": tuple(
            value.model_dump(mode="json") for value in sorted(cases, key=lambda item: item.case_id)
        ),
        "activation_policy": "FORBIDDEN",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "created_by": "contract_test",
    }
    identity = content_sha256(
        {key: value for key, value in body.items() if key not in {"created_at", "created_by"}}
    ).removeprefix("sha256:")[:32]
    with_id = {**body, "plan_id": f"imgscisubjectmultiseed_{identity}"}
    return LocalImageScienceVisualSubjectMultiseedPlan.model_validate(
        {**with_id, "plan_sha256": content_sha256(with_id)}
    )


def _multiseed_command(
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
) -> LocalImageScienceVisualSubjectMultiseedCommand:
    body = {
        "schema_version": "local-image-science-visual-subject-multiseed-command/1.0",
        "plan": _pointer(
            "5",
            schema_ref=(
                "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-plan/1.0"
            ),
            member_path="manifests/science-visual-subject-multiseed-plan.json",
            sha256=content_sha256(plan.model_dump(mode="json")),
        ).model_dump(mode="json"),
        "plan_sha256": plan.plan_sha256,
        "staged_plan_path": "inputs/subject-multiseed-plan.json",
        "staged_subject_inventory_path": "inputs/science-visual-subject-inventory.json",
        "staged_initial_benchmark_plan_path": "inputs/science-visual-subject-benchmark-plan.json",
        "staged_initial_quality_review_path": (
            "inputs/science-visual-subject-benchmark-review.json"
        ),
        "staged_adapter_manifest_path": "inputs/adapter/adapter-manifest.json",
        "staged_adapter_model_path": "inputs/adapter/adapter_model.safetensors",
        "staged_adapter_config_path": "inputs/adapter/adapter_config.json",
        "output_directory": "outputs",
        "source_commit": "f" * 40,
    }
    identity = content_sha256(body).removeprefix("sha256:")[:32]
    with_id = {**body, "run_id": f"imgscisubjectmultiseedrun_{identity}"}
    return LocalImageScienceVisualSubjectMultiseedCommand.model_validate(
        {**with_id, "command_sha256": content_sha256(with_id)}
    )


def _multiseed_result(
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
    command: LocalImageScienceVisualSubjectMultiseedCommand,
) -> LocalImageScienceVisualSubjectMultiseedResult:
    outputs = tuple(
        ScienceVisualSubjectMultiseedOutput(
            case_id=case.case_id,
            variant=variant,
            relative_path=f"outputs/{case.case_id}-{variant.lower()}.png",
            media_type="image/png",
            bytes=100,
            sha256="sha256:" + ("a" if variant == "ADAPTER" else "b") * 64,
            width_px=800,
            height_px=500,
        )
        for case in plan.cases
        for variant in ("ADAPTER", "BASE")
    )
    ordered = tuple(sorted(outputs, key=lambda value: (value.case_id, value.variant)))
    body = {
        "schema_version": "local-image-science-visual-subject-multiseed-result/1.0",
        "run_id": command.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "command_sha256": command.command_sha256,
        "status": "SUCCEEDED",
        "error_code": None,
        "outputs": tuple(value.model_dump(mode="json") for value in ordered),
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "completed_at": (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
    }
    return LocalImageScienceVisualSubjectMultiseedResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )


def test_subject_multiseed_contract_closes_exact_raster_population() -> None:
    inventory, initial_plan, initial_review = _multiseed_initials()
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    command = _multiseed_command(plan)
    result = _multiseed_result(plan, command)

    validate_contract("science-visual-subject-multiseed-plan", plan.model_dump(mode="json"))
    validate_contract("science-visual-subject-multiseed-command", command.model_dump(mode="json"))
    validate_contract("science-visual-subject-multiseed-result", result.model_dump(mode="json"))
    validate_science_visual_subject_multiseed_plan(inventory, initial_plan, initial_review, plan)
    validate_science_visual_subject_multiseed_result(plan, command, result)
    assert len(plan.cases) == 2
    assert len(result.outputs) == 4
    assert plan.activation_policy == "FORBIDDEN"


def test_subject_multiseed_builder_derives_only_fixed_additional_seeds() -> None:
    inventory, initial_plan, initial_review = _multiseed_initials()
    review_pointer = _pointer(
        "4",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-review/1.0"
        ),
        member_path="manifests/science-visual-subject-benchmark-review.json",
        sha256=content_sha256(initial_review.model_dump(mode="json")),
    )

    plan = build_science_visual_subject_multiseed_plan(
        inventory=inventory,
        initial_plan=initial_plan,
        initial_plan_pointer=initial_review.benchmark_plan,
        initial_review=initial_review,
        initial_review_pointer=review_pointer,
        created_at=NOW,
        created_by="contract_test",
    )

    assert plan.initial_quality_review == review_pointer
    assert len(plan.cases) == 2
    assert {case.seed_ordinal for case in plan.cases} == {1, 2}
    original_seed = next(case.seed for case in initial_plan.cases if case.case_kind == "QUALITY")
    assert all(case.seed != original_seed for case in plan.cases)
    assert plan.activation_policy == "FORBIDDEN"
    validate_science_visual_subject_multiseed_plan(
        inventory,
        initial_plan,
        initial_review,
        plan,
    )


def test_subject_multiseed_plan_rejects_original_seed_reuse() -> None:
    inventory, initial_plan, initial_review = _multiseed_initials()
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    value = plan.model_dump(mode="json")
    original = next(case for case in initial_plan.cases if case.case_kind == "QUALITY")
    value["cases"][0]["seed"] = original.seed
    with pytest.raises(ValidationError, match="prompt or seed mismatch"):
        LocalImageScienceVisualSubjectMultiseedPlan.model_validate(value)


def test_subject_multiseed_result_rejects_missing_pair() -> None:
    inventory, initial_plan, initial_review = _multiseed_initials()
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    command = _multiseed_command(plan)
    result = _multiseed_result(plan, command)
    value = result.model_dump(mode="json")
    value["outputs"] = value["outputs"][:-1]
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    parsed = LocalImageScienceVisualSubjectMultiseedResult.model_validate(value)
    with pytest.raises(ValueError, match="exact paired coverage"):
        validate_science_visual_subject_multiseed_result(plan, command, parsed)


def _multiseed_review(
    initial_plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    initial_review: LocalImageScienceVisualSubjectBenchmarkReview,
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
    result: LocalImageScienceVisualSubjectMultiseedResult,
) -> LocalImageScienceVisualSubjectMultiseedReview:
    original_by_subject = {
        value.subject_id: value for value in initial_plan.cases if value.case_kind == "QUALITY"
    }
    additional_by_subject: dict[str, list[ScienceVisualSubjectMultiseedCase]] = {}
    for case in plan.cases:
        additional_by_subject.setdefault(case.subject_id, []).append(case)
    entries = []
    for subject_id, additional in additional_by_subject.items():
        original = original_by_subject[subject_id]
        entries.append(
            ScienceVisualSubjectMultiseedReviewEntry(
                subject_id=subject_id,
                subject_key=additional[0].subject_key,
                render_route=additional[0].render_route,
                evaluations=(
                    ScienceVisualSubjectSeedEvaluation(
                        source="INITIAL",
                        case_id=original.case_id,
                        seed=original.seed,
                        decision="BASE",
                    ),
                    *(
                        ScienceVisualSubjectSeedEvaluation(
                            source="ADDITIONAL",
                            case_id=value.case_id,
                            seed=value.seed,
                            decision="BASE",
                        )
                        for value in additional
                    ),
                ),
                stability_status="STABLE_BASE_PREFERRED",
                next_actions=("KEEP_BASE_ONLY",),
            )
        )
    plan_pointer = _pointer(
        "8",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-plan/1.0"
        ),
        member_path="manifests/science-visual-subject-multiseed-plan.json",
        sha256=content_sha256(plan.model_dump(mode="json")),
    )
    result_pointer = _pointer(
        "9",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-result/1.0"
        ),
        member_path="result.json",
        sha256=content_sha256(result.model_dump(mode="json")),
    )
    identity_body = {
        "multiseed_plan": plan_pointer.model_dump(mode="json"),
        "multiseed_result": result_pointer.model_dump(mode="json"),
        "initial_quality_review": plan.initial_quality_review.model_dump(mode="json"),
        "reviews": [
            value.model_dump(mode="json")
            for value in sorted(entries, key=lambda item: item.subject_key)
        ],
        "stable_adapter_preferred_count": 0,
        "stable_base_preferred_count": len(entries),
        "mixed_count": 0,
        "neither_acceptable_count": 0,
        "adapter_activation_recommendation": "FORBIDDEN",
    }
    identity = content_sha256(
        {
            "schema_version": "local-image-science-visual-subject-multiseed-review/1.0",
            **identity_body,
        }
    ).removeprefix("sha256:")[:32]
    body = {
        "schema_version": "local-image-science-visual-subject-multiseed-review/1.0",
        "review_id": f"imgscisubjectmultiseedreview_{identity}",
        **identity_body,
        "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
        "reviewed_by": "contract_test",
    }
    return LocalImageScienceVisualSubjectMultiseedReview.model_validate(
        {**body, "review_sha256": content_sha256(body)}
    )


def test_subject_multiseed_review_binds_exact_predecessors_and_seed_population() -> None:
    inventory, initial_plan, initial_review = _multiseed_initials()
    plan = _multiseed_plan(inventory, initial_plan, initial_review)
    result = _multiseed_result(plan, _multiseed_command(plan))
    review = _multiseed_review(initial_plan, initial_review, plan, result)

    validate_contract("science-visual-subject-multiseed-review", review.model_dump(mode="json"))
    validate_science_visual_subject_multiseed_review(
        initial_plan,
        _result(initial_plan, _command(initial_plan)),
        initial_review,
        plan,
        result,
        review,
        plan_pointer=review.multiseed_plan,
        result_pointer=review.multiseed_result,
        initial_review_pointer=review.initial_quality_review,
    )
    assert review.adapter_activation_recommendation == "FORBIDDEN"


def test_subject_benchmark_failed_result_is_typed_and_empty() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    command = _command(plan)
    body = {
        "schema_version": "local-image-science-visual-subject-benchmark-result/1.0",
        "run_id": command.run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "command_sha256": command.command_sha256,
        "status": "FAILED",
        "error_code": "SCIENCE_SUBJECT_BENCHMARK_INPUT_HASH_MISMATCH",
        "outcomes": (),
        "outputs": (),
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    result = LocalImageScienceVisualSubjectBenchmarkResult.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )

    validate_contract("science-visual-subject-benchmark-result", result.model_dump(mode="json"))
    validate_science_visual_subject_benchmark_result(plan, command, result)


def test_subject_benchmark_failed_result_rejects_partial_outputs() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    command = _command(plan)
    succeeded = _result(plan, command)
    body = succeeded.model_dump(mode="json", exclude={"result_sha256"})
    body["status"] = "FAILED"
    body["error_code"] = "SCIENCE_SUBJECT_BENCHMARK_EXEC_FAILED"
    with pytest.raises(ValidationError, match="must be empty"):
        LocalImageScienceVisualSubjectBenchmarkResult.model_validate(
            {**body, "result_sha256": content_sha256(body)}
        )


def test_plan_builder_covers_every_subject_and_adds_human_gpu_negative() -> None:
    inventory = _inventory()
    inventory_pointer = _pointer(
        "a",
        schema_ref="eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0",
        member_path="manifests/science-visual-subject-inventory.json",
        sha256=content_sha256(inventory.model_dump(mode="json")),
    )
    adapter = _adapter_manifest()
    adapter_pointer = _pointer(
        "b",
        schema_ref=(
            "eom://schemas/image-provider/"
            "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
        ),
        member_path="manifests/adapter-manifest.json",
        sha256=sha256_bytes(content_json_bytes(adapter.model_dump(mode="json")) + b"\n"),
    )

    plan = build_science_visual_subject_benchmark_plan(
        inventory=inventory,
        inventory_pointer=inventory_pointer,
        adapter_manifest=adapter,
        adapter_manifest_pointer=adapter_pointer,
        created_at=NOW,
        created_by="contract_test",
    )

    assert len(plan.cases) == 3
    assert sum(case.case_kind == "GPU_POLICY_NEGATIVE" for case in plan.cases) == 1
    assert plan.base_model == adapter.base_model
    validate_science_visual_subject_benchmark_plan(inventory, plan)


def test_plan_builder_rejects_adapter_artifact_hash_drift() -> None:
    inventory = _inventory()
    adapter = _adapter_manifest()
    with pytest.raises(ValueError, match="adapter manifest Artifact pointer hash mismatch"):
        build_science_visual_subject_benchmark_plan(
            inventory=inventory,
            inventory_pointer=_pointer(
                "a",
                schema_ref=(
                    "eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0"
                ),
                member_path="manifests/science-visual-subject-inventory.json",
                sha256=content_sha256(inventory.model_dump(mode="json")),
            ),
            adapter_manifest=adapter,
            adapter_manifest_pointer=_pointer(
                "b",
                schema_ref=(
                    "eom://schemas/image-provider/"
                    "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
                ),
                member_path="manifests/adapter-manifest.json",
                sha256="sha256:" + "0" * 64,
            ),
            created_at=NOW,
            created_by="contract_test",
        )


def test_subject_inventory_rejects_unclosed_observation_population() -> None:
    inventory = _inventory()
    value = inventory.model_dump(mode="json")
    value["source_visual_observation_count"] = 4
    value["inventory_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "inventory_sha256"}
    )
    with pytest.raises(ValidationError, match="does not close"):
        LocalImageScienceVisualSubjectInventory.model_validate(value)


def test_subject_benchmark_requires_human_gpu_policy_negative() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    without_negative = tuple(case for case in plan.cases if case.case_kind != "GPU_POLICY_NEGATIVE")
    value = plan.model_dump(mode="json")
    value["cases"] = tuple(case.model_dump(mode="json") for case in without_negative)
    identity = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"plan_id", "created_at", "created_by", "plan_sha256"}
        }
    ).removeprefix("sha256:")[:32]
    value["plan_id"] = f"imgscisubjectbenchmark_{identity}"
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    parsed = LocalImageScienceVisualSubjectBenchmarkPlan.model_validate(value)
    with pytest.raises(ValueError, match="human subjects require"):
        validate_science_visual_subject_benchmark_plan(inventory, parsed)


def test_subject_benchmark_result_rejects_gpu_output_for_policy_rejection() -> None:
    inventory = _inventory()
    plan = _plan(inventory)
    command = _command(plan)
    result = _result(plan, command)
    rejected = next(case for case in plan.cases if case.expected_outcome == "POLICY_REJECTED")
    extra = ScienceVisualSubjectBenchmarkOutput(
        case_id=rejected.case_id,
        variant="BASE",
        relative_path=f"outputs/{rejected.case_id}-base.png",
        media_type="image/png",
        bytes=100,
        sha256="sha256:" + "0" * 64,
        width_px=800,
        height_px=500,
    )
    value = result.model_dump(mode="json")
    value["outputs"] = tuple(
        output.model_dump(mode="json")
        for output in sorted(
            (*result.outputs, extra), key=lambda item: (item.case_id, item.variant)
        )
    )
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    parsed = LocalImageScienceVisualSubjectBenchmarkResult.model_validate(value)
    with pytest.raises(ValueError, match="output variants"):
        validate_science_visual_subject_benchmark_result(plan, command, parsed)
