"""Build a bounded benchmark plan from an immutable science-subject inventory."""

from __future__ import annotations

from datetime import datetime

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectInventory,
    ScienceVisualSubject,
    ScienceVisualSubjectBenchmarkCase,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_science_visual_subject_benchmark_plan,
)

NEGATIVE_PROMPT = (
    "color, text, letters, labels, numbers, watermark, decorative border, photographic people, "
    "faces, hands, unrelated objects, dramatic lighting, cinematic composition"
)
HUMAN_GPU_NEGATIVE_PROMPT = (
    "monochrome Korean science assessment illustration of an identifiable human student in a "
    "laboratory, plain white background, no text, no watermark"
)
HUMAN_SUBJECT_KEYS = frozenset({"HUMAN_FIGURE", "STUDENT_OR_TEACHER"})


def _case_id(subject_id: str, case_kind: str) -> str:
    identity = content_sha256({"case_kind": case_kind, "subject_id": subject_id}).removeprefix(
        "sha256:"
    )[:32]
    return f"imgscisubjectcase_{identity}"


def _seed(subject_key: str) -> int:
    return int(content_sha256(subject_key).removeprefix("sha256:")[:8], 16) % 2_147_483_648


def _primary_case(subject: ScienceVisualSubject) -> ScienceVisualSubjectBenchmarkCase | None:
    if subject.render_route == "BLOCKED":
        return None
    if subject.render_route == "PYTHON_SVG":
        return ScienceVisualSubjectBenchmarkCase(
            case_id=_case_id(subject.subject_id, "ROUTE"),
            subject_id=subject.subject_id,
            render_route=subject.render_route,
            case_kind="ROUTE",
            prompt_en=None,
            prompt_sha256=None,
            negative_prompt_en=None,
            negative_prompt_sha256=None,
            seed=None,
            renderer_primitive=subject.renderer_primitive,
            expected_outcome="DETERMINISTIC_RENDERED",
        )
    assert subject.raster_prompt_en is not None
    return ScienceVisualSubjectBenchmarkCase(
        case_id=_case_id(subject.subject_id, "QUALITY"),
        subject_id=subject.subject_id,
        render_route=subject.render_route,
        case_kind="QUALITY",
        prompt_en=subject.raster_prompt_en,
        prompt_sha256=text_sha256(subject.raster_prompt_en),
        negative_prompt_en=NEGATIVE_PROMPT,
        negative_prompt_sha256=text_sha256(NEGATIVE_PROMPT),
        seed=_seed(subject.subject_key),
        renderer_primitive=subject.renderer_primitive,
        expected_outcome="BASE_ADAPTER_PAIR",
    )


def _human_negative_case(subject: ScienceVisualSubject) -> ScienceVisualSubjectBenchmarkCase:
    return ScienceVisualSubjectBenchmarkCase(
        case_id=_case_id(subject.subject_id, "GPU_POLICY_NEGATIVE"),
        subject_id=subject.subject_id,
        render_route=subject.render_route,
        case_kind="GPU_POLICY_NEGATIVE",
        prompt_en=HUMAN_GPU_NEGATIVE_PROMPT,
        prompt_sha256=text_sha256(HUMAN_GPU_NEGATIVE_PROMPT),
        negative_prompt_en=NEGATIVE_PROMPT,
        negative_prompt_sha256=text_sha256(NEGATIVE_PROMPT),
        seed=_seed(subject.subject_key + ":human-negative"),
        renderer_primitive=subject.renderer_primitive,
        expected_outcome="POLICY_REJECTED",
    )


def build_science_visual_subject_benchmark_plan(
    *,
    inventory: LocalImageScienceVisualSubjectInventory,
    inventory_pointer: ImageEvaluationArtifactMember,
    adapter_manifest: LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    adapter_manifest_pointer: ImageEvaluationArtifactMember,
    created_at: datetime,
    created_by: str,
) -> LocalImageScienceVisualSubjectBenchmarkPlan:
    """Create exactly one primary case per renderable subject and human GPU negatives."""

    canonical_adapter = content_json_bytes(adapter_manifest.model_dump(mode="json"))
    if adapter_manifest_pointer.sha256 not in {
        sha256_bytes(canonical_adapter),
        sha256_bytes(canonical_adapter + b"\n"),
    }:
        raise ValueError("adapter manifest Artifact pointer hash mismatch")
    cases: list[ScienceVisualSubjectBenchmarkCase] = []
    for subject in inventory.subjects:
        primary = _primary_case(subject)
        if primary is not None:
            cases.append(primary)
        if subject.subject_key in HUMAN_SUBJECT_KEYS:
            cases.append(_human_negative_case(subject))
    ordered_cases = tuple(sorted(cases, key=lambda value: value.case_id))
    base = {
        "schema_version": "local-image-science-visual-subject-benchmark-plan/1.0",
        "subject_inventory": inventory_pointer.model_dump(mode="json"),
        "subject_inventory_sha256": inventory_pointer.sha256,
        "base_model": adapter_manifest.base_model.model_dump(mode="json"),
        "adapter_manifest": adapter_manifest_pointer.model_dump(mode="json"),
        "generation_width_px": 800,
        "generation_height_px": 504,
        "delivery_width_px": 800,
        "delivery_height_px": 500,
        "inference_steps": 20,
        "guidance_scale_milli": 7500,
        "cases": tuple(case.model_dump(mode="json") for case in ordered_cases),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    identity = content_sha256(
        {key: value for key, value in base.items() if key not in {"created_at", "created_by"}}
    ).removeprefix("sha256:")[:32]
    with_id = {**base, "plan_id": f"imgscisubjectbenchmark_{identity}"}
    plan = LocalImageScienceVisualSubjectBenchmarkPlan.model_validate(
        {**with_id, "plan_sha256": content_sha256(with_id)}
    )
    validate_science_visual_subject_benchmark_plan(inventory, plan)
    return plan
