"""Deterministic production intent for 25 independent one-Item workflow calls.

This module plans creation work.  It deliberately does not select, register, publish, or assemble
Items.  An application service can materialize each pinned call through the existing one-Item
workflow and retain the resulting immutable workflow and Item revision pointers separately.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal, Never, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.assessment_assembly import (
    MockExamAssemblyPolicyV1,
    MockExamLayoutPolicyV1,
    MockExamLayoutSlotV1,
    MockExamMaterialProfile,
    MockExamPreferredDifficulty,
    MockExamScoreBucket,
)
from eom_catalog_contracts.assessment_item import AssessmentItemContentV2, AssessmentItemContentV3
from eom_catalog_contracts.authoring_guidance import validate_reviewed_authoring_guidance
from eom_catalog_contracts.curriculum import (
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
    IntegratedScienceCurriculumResolver,
    IntegratedScienceCurriculumUnit,
    IntegratedScienceEditorialOutline,
    IntegratedScienceProductLevel,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

CONTENT_TEAM_ITEM_GUIDANCE = (
    "검토된 요청 범위 안에서 콘텐츠팀 출제 원문과 편집 프로그램 계약을 그대로 적용하여 "
    "문항을 작성해 주세요."
)
CONTENT_TEAM_ITEM_GUIDANCE_SHA256 = (
    "sha256:b60aba3badb50adf8d4b2919fa07f3d69962f06c53514cd1659d645862c48a64"
)
CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256: Literal[
    "sha256:a91aa67eb4916166681f8f58ed665253dd491bea72ccaf775036d1e6f1cc48b3"
] = "sha256:a91aa67eb4916166681f8f58ed665253dd491bea72ccaf775036d1e6f1cc48b3"
CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256: Literal[
    "sha256:8bbd6c262edef592f4779f4ba63688badbb3fe15a85eb6997a9bb1ba0c3770e8"
] = "sha256:8bbd6c262edef592f4779f4ba63688badbb3fe15a85eb6997a9bb1ba0c3770e8"
CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256_V2: Literal[
    "sha256:31f15f4811090045a92ad3a465e94f91ec430e638fe7b07f132c024e079a5792"
] = "sha256:31f15f4811090045a92ad3a465e94f91ec430e638fe7b07f132c024e079a5792"
CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256_V2: Literal[
    "sha256:977601f0e1060f9f6304c5b58be357723758359adf1b18c931d6f82a35ae4c81"
] = "sha256:977601f0e1060f9f6304c5b58be357723758359adf1b18c931d6f82a35ae4c81"
_AUTHORING_DIFFICULTY_BY_SLOT = {"LOW": "easy", "MEDIUM": "medium", "HIGH": "hard"}

__all__ = [
    "CONTENT_TEAM_ITEM_GUIDANCE",
    "CONTENT_TEAM_ITEM_GUIDANCE_SHA256",
    "CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256",
    "CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256_V2",
    "CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256",
    "CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256_V2",
    "ContentTeamItemBriefV3Input",
    "ContentTeamMockExamSlotV1",
    "MockExamOneItemGenerationBlockV1",
    "MockExamOneItemGenerationBlockV2",
    "MockExamPlannedWorkflowCallV1",
    "MockExamPlannedWorkflowCallV2",
    "MockExamProductionPlanContract",
    "MockExamProductionPlanError",
    "MockExamProductionPlanV1",
    "MockExamProductionPlanV2",
    "build_integrated_science_mock_exam_production_plan",
    "build_integrated_science_mock_exam_production_plan_v2",
    "classify_content_team_mock_exam_material_profile",
    "validate_content_team_mock_exam_slot_output",
    "validate_content_team_mock_exam_slot_output_v2",
]


class MockExamProductionPlanError(ValueError):
    """Stable failure raised when released inputs cannot form a safe production plan."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ContentTeamMockExamSlotV1(FrozenModel):
    """Immutable structured slot intent carried through the one-Item workflow."""

    schema_version: Literal["mock-exam-slot/1.0"]
    assembly_policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    assembly_policy_sha256: Sha256
    layout_policy_revision_id: str = Field(pattern=r"^layoutpolicyrev_[0-9a-f]{32}$")
    layout_policy_sha256: Sha256
    slot_id: str = Field(pattern=r"^slot-[0-9]{2,3}$")
    position: int = Field(ge=1, le=200)
    points_milli: int = Field(ge=1, le=1_000_000)
    coverage_role: Literal["REQUIRED", "BALANCE"]
    coverage_requirement_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$",
    )
    balance_large_unit_key: str | None = Field(
        default=None,
        pattern=r"^eom\.is\.large\.[1-6]$",
    )
    curriculum_selected_unit_key: str = Field(pattern=r"^eom\.is\.middle\.[1-6]-[1-7]$")
    large_unit_key: str = Field(pattern=r"^eom\.is\.large\.[1-6]$")
    inquiry_required: bool
    preferred_difficulty: MockExamPreferredDifficulty
    preferred_material_profiles: tuple[MockExamMaterialProfile, ...] = Field(
        min_length=1,
        max_length=6,
    )
    slot_sha256: Sha256

    @model_validator(mode="after")
    def coherent_slot(self) -> Self:
        is_required = self.coverage_role == "REQUIRED"
        if is_required != (self.coverage_requirement_id is not None):
            raise ValueError("required production slots must bind one coverage requirement")
        if is_required == (self.balance_large_unit_key is not None):
            raise ValueError("only balance production slots bind one large unit")
        if self.preferred_material_profiles != tuple(
            dict.fromkeys(self.preferred_material_profiles)
        ):
            raise ValueError("preferred material profiles must be unique and ordered")
        if self.inquiry_required and "INQUIRY" not in self.preferred_material_profiles:
            raise ValueError("required inquiry slots must carry the INQUIRY material profile")
        expected = content_sha256(self.model_dump(mode="json", exclude={"slot_sha256"}))
        if self.slot_sha256 != expected:
            raise ValueError("mock-exam slot hash does not match canonical content")
        return self


class ContentTeamItemBriefV3Input(FrozenModel):
    """Content-neutral presentation input accepted by the existing one-Item block."""

    schema_version: Literal["3.0"] = "3.0"
    subject: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=160)
    task_type: MockExamMaterialProfile
    difficulty: MockExamPreferredDifficulty
    authoring_guidance: Literal[
        "검토된 요청 범위 안에서 콘텐츠팀 출제 원문과 편집 프로그램 계약을 그대로 적용하여 "
        "문항을 작성해 주세요."
    ]
    authoring_guidance_sha256: Literal[
        "sha256:b60aba3badb50adf8d4b2919fa07f3d69962f06c53514cd1659d645862c48a64"
    ]
    curriculum_selected_unit_key: str = Field(pattern=r"^eom\.is\.middle\.[1-6]-[1-7]$")
    mock_exam_slot: ContentTeamMockExamSlotV1
    original_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_guidance(self) -> Self:
        validate_reviewed_authoring_guidance(
            self.authoring_guidance,
            self.authoring_guidance_sha256,
        )
        if (
            self.curriculum_selected_unit_key != self.mock_exam_slot.curriculum_selected_unit_key
            or self.difficulty != self.mock_exam_slot.preferred_difficulty
            or self.task_type != self.mock_exam_slot.preferred_material_profiles[0]
        ):
            raise ValueError("content-team V3 brief differs from its typed mock-exam slot")
        return self


class MockExamOneItemGenerationBlockV1(FrozenModel):
    """Pinned source-level identity of the existing one-Item workflow block."""

    block_key: Literal["content-team-one-item-generation"]
    block_revision: Literal["1.0"]
    workflow_definition_key: Literal["generic-item-development"]
    workflow_definition_version: Literal["1.8.0"]
    request_name: Literal["GENERATED_KNOWLEDGE_ITEM_REQUEST"]
    image_mode: Literal["required"]
    content_pack_key: Literal["generated-knowledge-item"]
    content_pack_version: Literal["1.13.0"]
    content_pack_source_tree_sha256: Literal[
        "sha256:a91aa67eb4916166681f8f58ed665253dd491bea72ccaf775036d1e6f1cc48b3"
    ]
    execution_preset_key: Literal["knowledge-grounded-item"]
    registry_mode: Literal["CREATE_ITEM"]
    block_sha256: Literal["sha256:8bbd6c262edef592f4779f4ba63688badbb3fe15a85eb6997a9bb1ba0c3770e8"]

    @model_validator(mode="after")
    def self_hash_matches(self) -> Self:
        body = self.model_dump(mode="json", exclude={"block_sha256"})
        if content_sha256(body) != self.block_sha256:
            raise ValueError("one-Item generation block hash does not match canonical content")
        return self


class MockExamOneItemGenerationBlockV2(MockExamOneItemGenerationBlockV1):
    """Generation block pinning only the score/provenance-correct V3 path."""

    block_revision: Literal["2.0"]  # type: ignore[assignment]
    workflow_definition_version: Literal["1.9.0"]  # type: ignore[assignment]
    content_pack_version: Literal["1.14.0"]  # type: ignore[assignment]
    content_pack_source_tree_sha256: Literal[  # type: ignore[assignment]
        "sha256:31f15f4811090045a92ad3a465e94f91ec430e638fe7b07f132c024e079a5792"
    ]
    block_sha256: Literal[  # type: ignore[assignment]
        "sha256:977601f0e1060f9f6304c5b58be357723758359adf1b18c931d6f82a35ae4c81"
    ]


class MockExamPlannedWorkflowCallV1(FrozenModel):
    """One independent CREATE_ITEM invocation assigned to one exam position."""

    workflow_call_id: str = Field(pattern=r"^workflowcall_[0-9a-f]{32}$")
    generation_block_key: Literal["content-team-one-item-generation"]
    generation_block_revision: Literal["1.0"]
    generation_block_sha256: Literal[
        "sha256:8bbd6c262edef592f4779f4ba63688badbb3fe15a85eb6997a9bb1ba0c3770e8"
    ]
    item_brief: ContentTeamItemBriefV3Input

    @model_validator(mode="after")
    def coherent_call(self) -> Self:
        expected_request_sha256 = _original_request_sha256(self.item_brief)
        if self.item_brief.original_request_sha256 != expected_request_sha256:
            raise ValueError("one-Item original request hash does not match its planned intent")
        expected_call_id = _workflow_call_id(
            self.model_dump(mode="json", exclude={"workflow_call_id"})
        )
        if self.workflow_call_id != expected_call_id:
            raise ValueError("workflow call identity does not match canonical content")
        return self


class MockExamPlannedWorkflowCallV2(MockExamPlannedWorkflowCallV1):
    generation_block_revision: Literal["2.0"]  # type: ignore[assignment]
    generation_block_sha256: Literal[  # type: ignore[assignment]
        "sha256:977601f0e1060f9f6304c5b58be357723758359adf1b18c931d6f82a35ae4c81"
    ]


class MockExamProductionPlanV1(FrozenModel):
    """One immutable exam-production plan containing exactly 25 CREATE_ITEM calls."""

    schema_version: Literal["mock-exam-production-plan/1.0"]
    production_plan_id: str = Field(pattern=r"^productionplan_[0-9a-f]{32}$")
    policy_revision_id: str = Field(pattern=r"^assemblypolicyrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    layout_policy_revision_id: str = Field(pattern=r"^layoutpolicyrev_[0-9a-f]{32}$")
    layout_policy_sha256: Sha256
    outline_key: Literal["eom-integrated-science-editorial-outline"]
    outline_revision: Literal["1.0"]
    outline_sha256: Sha256
    item_count: Literal[25]
    total_points_milli: Literal[50_000]
    score_distribution: tuple[MockExamScoreBucket, ...] = Field(min_length=1, max_length=20)
    required_slot_count: Literal[21]
    balance_slot_count: Literal[4]
    inquiry_count: Literal[4]
    one_item_generation_block: MockExamOneItemGenerationBlockV1
    workflow_calls: tuple[MockExamPlannedWorkflowCallV1, ...] = Field(
        min_length=25,
        max_length=25,
    )
    plan_sha256: Sha256

    @model_validator(mode="after")
    def coherent_plan(self) -> Self:
        calls = self.workflow_calls
        slots = tuple(row.item_brief.mock_exam_slot for row in calls)
        if tuple(row.position for row in slots) != tuple(range(1, self.item_count + 1)):
            raise ValueError("production workflow calls must be contiguous and ordered")
        if len({row.slot_id for row in slots}) != self.item_count:
            raise ValueError("production workflow slot IDs must be unique")
        if len({row.workflow_call_id for row in calls}) != self.item_count:
            raise ValueError("production workflow call IDs must be unique")
        score_counts = Counter(row.points_milli for row in slots)
        expected_scores = Counter({row.points_milli: row.count for row in self.score_distribution})
        if score_counts != expected_scores or sum(row.points_milli for row in slots) != (
            self.total_points_milli
        ):
            raise ValueError("production workflow score distribution is incoherent")
        required_count = sum(row.coverage_role == "REQUIRED" for row in slots)
        balance_count = sum(row.coverage_role == "BALANCE" for row in slots)
        inquiry_count = sum(row.inquiry_required for row in slots)
        if (
            required_count != self.required_slot_count
            or balance_count != self.balance_slot_count
            or inquiry_count != self.inquiry_count
        ):
            raise ValueError("production workflow role or inquiry counts are incoherent")
        block = self.one_item_generation_block
        for call, slot in zip(calls, slots, strict=True):
            if (
                call.generation_block_key != block.block_key
                or call.generation_block_revision != block.block_revision
                or call.generation_block_sha256 != block.block_sha256
            ):
                raise ValueError("production workflow call has a stale generation block pointer")
            if (
                slot.assembly_policy_revision_id != self.policy_revision_id
                or slot.assembly_policy_sha256 != self.policy_sha256
                or slot.layout_policy_revision_id != self.layout_policy_revision_id
                or slot.layout_policy_sha256 != self.layout_policy_sha256
            ):
                raise ValueError("production workflow call has a stale policy pointer")
        identity_body = self.model_dump(
            mode="json",
            exclude={"production_plan_id", "plan_sha256"},
        )
        expected_sha256 = content_sha256(identity_body)
        if self.plan_sha256 != expected_sha256 or self.production_plan_id != (
            "productionplan_" + expected_sha256.removeprefix("sha256:")[:32]
        ):
            raise ValueError("production plan identity does not match canonical content")
        return self


class MockExamProductionPlanV2(MockExamProductionPlanV1):
    """Production plan whose 25 calls all pin workflow 1.9 and Content Pack 1.14."""

    schema_version: Literal["mock-exam-production-plan/2.0"]  # type: ignore[assignment]
    one_item_generation_block: MockExamOneItemGenerationBlockV2
    workflow_calls: tuple[MockExamPlannedWorkflowCallV2, ...] = Field(
        min_length=25,
        max_length=25,
    )


MockExamProductionPlanContract = MockExamProductionPlanV1 | MockExamProductionPlanV2


def build_integrated_science_mock_exam_production_plan(
    *,
    policy: MockExamAssemblyPolicyV1,
    layout_policy: MockExamLayoutPolicyV1,
    outline: IntegratedScienceEditorialOutline,
) -> MockExamProductionPlanV1:
    """Derive 25 new one-Item calls solely from released policy and curriculum inputs."""

    _validate_released_inputs(policy=policy, layout_policy=layout_policy, outline=outline)
    resolver = IntegratedScienceCurriculumResolver.build(outline)
    requirement_by_id = {row.requirement_id: row for row in policy.coverage_requirements}
    unit_rank = {unit.key: index for index, unit in enumerate(outline.units)}
    selected_by_slot: dict[str, IntegratedScienceCurriculumUnit] = {}
    selected_units_by_requirement: dict[str, set[str]] = {}

    for slot in layout_policy.slots:
        if slot.coverage_role != "REQUIRED":
            continue
        assert slot.coverage_requirement_id is not None
        requirement = requirement_by_id[slot.coverage_requirement_id]
        candidates = sorted(
            (_middle_unit(resolver, key) for key in requirement.allowed_unit_keys),
            key=lambda unit: unit_rank[unit.key],
        )
        used = selected_units_by_requirement.setdefault(requirement.requirement_id, set())
        selected = next(
            (unit for unit in candidates if not requirement.distinct_units or unit.key not in used),
            None,
        )
        if selected is None:
            _fail(
                "PRODUCTION_REQUIRED_UNIT_DISTINCTNESS_UNSATISFIED",
                f"no unused curriculum unit remains for {slot.slot_id}",
            )
        selected_by_slot[slot.slot_id] = selected
        used.add(selected.key)

    balance_offsets: Counter[str] = Counter()
    for slot in layout_policy.slots:
        if slot.coverage_role != "BALANCE":
            continue
        assert slot.balance_large_unit_key is not None
        children = tuple(
            unit
            for unit in resolver.ordered_children(slot.balance_large_unit_key)
            if unit.level == IntegratedScienceProductLevel.MIDDLE
        )
        if not children:
            _fail(
                "PRODUCTION_BALANCE_UNIT_MISSING",
                f"no MIDDLE curriculum unit exists for {slot.slot_id}",
            )
        offset = balance_offsets[slot.balance_large_unit_key]
        selected = children[offset % len(children)]
        balance_offsets[slot.balance_large_unit_key] += 1
        selected_by_slot[slot.slot_id] = selected

    block = _one_item_generation_block()
    policy_sha256 = content_sha256(policy.model_dump(mode="json"))
    layout_policy_sha256 = content_sha256(layout_policy.model_dump(mode="json"))
    calls = tuple(
        _build_workflow_call(
            slot=slot,
            unit=selected_by_slot[slot.slot_id],
            subject_label=outline.subject_label,
            block=block,
            assembly_policy_revision_id=policy.policy_revision_id,
            assembly_policy_sha256=policy_sha256,
            layout_policy_revision_id=layout_policy.layout_policy_revision_id,
            layout_policy_sha256=layout_policy_sha256,
        )
        for slot in layout_policy.slots
    )
    plan_body = {
        "schema_version": "mock-exam-production-plan/1.0",
        "policy_revision_id": policy.policy_revision_id,
        "policy_sha256": policy_sha256,
        "layout_policy_revision_id": layout_policy.layout_policy_revision_id,
        "layout_policy_sha256": layout_policy_sha256,
        "outline_key": outline.outline_key,
        "outline_revision": outline.outline_revision,
        "outline_sha256": policy.outline_sha256,
        "item_count": policy.item_count,
        "total_points_milli": policy.total_points_milli,
        "score_distribution": [row.model_dump(mode="json") for row in policy.score_distribution],
        "required_slot_count": policy.required_slot_count,
        "balance_slot_count": policy.balance_slot_count,
        "inquiry_count": sum(row.item_brief.mock_exam_slot.inquiry_required for row in calls),
        "one_item_generation_block": block.model_dump(mode="json"),
        "workflow_calls": [row.model_dump(mode="json") for row in calls],
    }
    plan_sha256 = content_sha256(plan_body)
    return MockExamProductionPlanV1.model_validate(
        {
            **plan_body,
            "production_plan_id": ("productionplan_" + plan_sha256.removeprefix("sha256:")[:32]),
            "plan_sha256": plan_sha256,
        }
    )


def build_integrated_science_mock_exam_production_plan_v2(
    *,
    policy: MockExamAssemblyPolicyV1,
    layout_policy: MockExamLayoutPolicyV1,
    outline: IntegratedScienceEditorialOutline,
) -> MockExamProductionPlanV2:
    """Upgrade the deterministic 25-slot intent onto the immutable V3 generation block."""

    historical = build_integrated_science_mock_exam_production_plan(
        policy=policy,
        layout_policy=layout_policy,
        outline=outline,
    )
    block = _one_item_generation_block_v2()
    calls = tuple(_upgrade_workflow_call_v2(call, block) for call in historical.workflow_calls)
    plan_body = historical.model_dump(
        mode="json",
        exclude={
            "production_plan_id",
            "plan_sha256",
            "one_item_generation_block",
            "workflow_calls",
        },
    )
    plan_body.update(
        schema_version="mock-exam-production-plan/2.0",
        one_item_generation_block=block.model_dump(mode="json"),
        workflow_calls=[call.model_dump(mode="json") for call in calls],
    )
    plan_sha256 = content_sha256(plan_body)
    return MockExamProductionPlanV2.model_validate(
        {
            **plan_body,
            "production_plan_id": "productionplan_" + plan_sha256.removeprefix("sha256:")[:32],
            "plan_sha256": plan_sha256,
        }
    )


def validate_content_team_mock_exam_slot_output(
    *,
    slot: ContentTeamMockExamSlotV1,
    content: AssessmentItemContentV2 | AssessmentItemContentV3,
    authoring_difficulty: str,
) -> MockExamMaterialProfile:
    """Fail closed before registration when authored content violates structured slot intent.

    ``points_milli`` is intentionally not compared with ``content.score_display``. It is an
    assembly-assignment value and the whole-exam renderer owns its final display.
    """

    expected_difficulty = _AUTHORING_DIFFICULTY_BY_SLOT[slot.preferred_difficulty]
    if authoring_difficulty != expected_difficulty:
        _fail(
            "PRODUCTION_AUTHORING_DIFFICULTY_MISMATCH",
            "authoring metadata difficulty differs from the mock-exam slot",
        )
    if (content.inquiry is not None) != slot.inquiry_required:
        _fail(
            "PRODUCTION_AUTHORING_INQUIRY_MISMATCH",
            "authored inquiry presence differs from the mock-exam slot",
        )
    material_profile = classify_content_team_mock_exam_material_profile(content)
    if material_profile not in slot.preferred_material_profiles:
        _fail(
            "PRODUCTION_AUTHORING_MATERIAL_PROFILE_MISMATCH",
            "authored material profile is outside the slot's allowed profiles",
        )
    return material_profile


def validate_content_team_mock_exam_slot_output_v2(
    *,
    slot: ContentTeamMockExamSlotV1,
    content: AssessmentItemContentV3,
    authoring_difficulty: str,
) -> MockExamMaterialProfile:
    """Validate V3 content against the exact source/final score assigned to its slot."""

    material_profile = validate_content_team_mock_exam_slot_output(
        slot=slot,
        content=content,
        authoring_difficulty=authoring_difficulty,
    )
    if material_profile != slot.preferred_material_profiles[0]:
        _fail(
            "PRODUCTION_AUTHORING_MATERIAL_PROFILE_MISMATCH",
            "authored material profile differs from the exact primary mock-exam slot profile",
        )
    expected_score = {
        1500: "1.5",
        2000: "2",
        2500: "2.5",
        3000: "3",
    }.get(slot.points_milli)
    if expected_score is None:
        _fail(
            "PRODUCTION_SLOT_SCORE_UNSUPPORTED",
            "mock-exam slot points cannot be represented by the content-team score contract",
        )
    if content.score_display != expected_score:
        _fail(
            "PRODUCTION_AUTHORING_SCORE_MISMATCH",
            "authored score differs from the exact mock-exam slot score",
        )
    return material_profile


def _validate_released_inputs(
    *,
    policy: MockExamAssemblyPolicyV1,
    layout_policy: MockExamLayoutPolicyV1,
    outline: IntegratedScienceEditorialOutline,
) -> None:
    policy_sha256 = content_sha256(policy.model_dump(mode="json"))
    if (
        policy.state != "RELEASED"
        or layout_policy.state != "RELEASED"
        or policy.subject_key != layout_policy.subject_key
        or policy.subject_key != outline.subject_key
    ):
        _fail("PRODUCTION_POLICY_NOT_RELEASED", "released policy subjects are incoherent")
    if (
        layout_policy.assembly_policy_revision_id != policy.policy_revision_id
        or layout_policy.assembly_policy_sha256 != policy_sha256
        or layout_policy.guidance_revision != policy.guidance_pointer.revision
        or layout_policy.guidance_reviewed_document_sha256
        != policy.guidance_pointer.reviewed_document_sha256
    ):
        _fail("PRODUCTION_LAYOUT_POINTER_STALE", "layout does not pin the supplied policy")
    if (
        policy.outline_key != outline.outline_key
        or policy.outline_revision != outline.outline_revision
        or policy.outline_sha256 != INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256
    ):
        _fail("PRODUCTION_OUTLINE_POINTER_STALE", "policy does not pin the supplied outline")
    if (
        policy.item_count != 25
        or policy.total_points_milli != 50_000
        or policy.required_slot_count != 21
        or policy.balance_slot_count != 4
        or len(layout_policy.slots) != policy.item_count
    ):
        _fail("PRODUCTION_PLAN_SHAPE_UNSUPPORTED", "production-plan/1.0 requires 25 Items")
    inquiry_count = sum(slot.inquiry_required for slot in layout_policy.slots)
    if inquiry_count != 4 or inquiry_count != policy.inquiry_min_count:
        _fail(
            "PRODUCTION_INQUIRY_COUNT_INVALID",
            "released layout must require exactly 4 inquiries",
        )

    slots_by_requirement: Counter[str] = Counter()
    requirement_ids = {row.requirement_id for row in policy.coverage_requirements}
    required_count = 0
    balance_count = 0
    for slot in layout_policy.slots:
        if slot.coverage_role == "REQUIRED":
            required_count += 1
            assert slot.coverage_requirement_id is not None
            if slot.coverage_requirement_id not in requirement_ids:
                _fail(
                    "PRODUCTION_COVERAGE_REQUIREMENT_MISSING",
                    f"unknown coverage requirement: {slot.coverage_requirement_id}",
                )
            slots_by_requirement[slot.coverage_requirement_id] += 1
        else:
            balance_count += 1
    if required_count != policy.required_slot_count or balance_count != policy.balance_slot_count:
        _fail("PRODUCTION_COVERAGE_ROLE_COUNT_INVALID", "layout coverage roles are incoherent")
    for requirement in policy.coverage_requirements:
        if slots_by_requirement[requirement.requirement_id] != requirement.selection_count:
            _fail(
                "PRODUCTION_COVERAGE_SELECTION_COUNT_INVALID",
                f"layout count differs for {requirement.requirement_id}",
            )


def _middle_unit(
    resolver: IntegratedScienceCurriculumResolver,
    unit_key: str,
) -> IntegratedScienceCurriculumUnit:
    try:
        unit = resolver.units_by_key[unit_key]
    except KeyError:
        _fail("PRODUCTION_CURRICULUM_UNIT_MISSING", f"unknown curriculum unit: {unit_key}")
    if unit.level != IntegratedScienceProductLevel.MIDDLE:
        _fail("PRODUCTION_CURRICULUM_LEVEL_INVALID", f"unit is not MIDDLE: {unit_key}")
    return unit


def classify_content_team_mock_exam_material_profile(
    content: AssessmentItemContentV2 | AssessmentItemContentV3,
) -> MockExamMaterialProfile:
    """Classify one content-team draft using the canonical mock-exam material rule."""

    if content.inquiry is not None:
        return "INQUIRY"
    signals: set[Literal["DATA", "TABLE", "IMAGE"]] = set()
    if any(block.kind == "DATA" for block in content.labeled_blocks):
        signals.add("DATA")
    for visual in content.visuals:
        if visual.kind == "TABLE":
            signals.add("TABLE")
        elif visual.kind == "IMAGE":
            signals.add("IMAGE")
    if not signals:
        return "TEXT"
    if len(signals) > 1:
        return "MIXED"
    if "DATA" in signals:
        return "DATA"
    if "TABLE" in signals:
        return "TABLE"
    return "IMAGE"


def _one_item_generation_block() -> MockExamOneItemGenerationBlockV1:
    return MockExamOneItemGenerationBlockV1(
        block_key="content-team-one-item-generation",
        block_revision="1.0",
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.8.0",
        request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
        image_mode="required",
        content_pack_key="generated-knowledge-item",
        content_pack_version="1.13.0",
        content_pack_source_tree_sha256=CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256,
        execution_preset_key="knowledge-grounded-item",
        registry_mode="CREATE_ITEM",
        block_sha256=CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256,
    )


def _one_item_generation_block_v2() -> MockExamOneItemGenerationBlockV2:
    return MockExamOneItemGenerationBlockV2(
        block_key="content-team-one-item-generation",
        block_revision="2.0",
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.9.0",
        request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
        image_mode="required",
        content_pack_key="generated-knowledge-item",
        content_pack_version="1.14.0",
        content_pack_source_tree_sha256=CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256_V2,
        execution_preset_key="knowledge-grounded-item",
        registry_mode="CREATE_ITEM",
        block_sha256=CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256_V2,
    )


def _upgrade_workflow_call_v2(
    call: MockExamPlannedWorkflowCallV1,
    block: MockExamOneItemGenerationBlockV2,
) -> MockExamPlannedWorkflowCallV2:
    call_body: dict[str, object] = {
        "generation_block_key": block.block_key,
        "generation_block_revision": block.block_revision,
        "generation_block_sha256": block.block_sha256,
        "item_brief": call.item_brief.model_dump(mode="json"),
    }
    return MockExamPlannedWorkflowCallV2.model_validate(
        {**call_body, "workflow_call_id": _workflow_call_id(call_body)}
    )


def _build_workflow_call(
    *,
    slot: MockExamLayoutSlotV1,
    unit: IntegratedScienceCurriculumUnit,
    subject_label: str,
    block: MockExamOneItemGenerationBlockV1,
    assembly_policy_revision_id: str,
    assembly_policy_sha256: str,
    layout_policy_revision_id: str,
    layout_policy_sha256: str,
) -> MockExamPlannedWorkflowCallV1:
    slot_body = {
        "schema_version": "mock-exam-slot/1.0",
        "assembly_policy_revision_id": assembly_policy_revision_id,
        "assembly_policy_sha256": assembly_policy_sha256,
        "layout_policy_revision_id": layout_policy_revision_id,
        "layout_policy_sha256": layout_policy_sha256,
        "slot_id": slot.slot_id,
        "position": slot.position,
        "points_milli": slot.points_milli,
        "coverage_role": slot.coverage_role,
        "coverage_requirement_id": slot.coverage_requirement_id,
        "balance_large_unit_key": slot.balance_large_unit_key,
        "curriculum_selected_unit_key": unit.key,
        "large_unit_key": unit.parent_key,
        "inquiry_required": slot.inquiry_required,
        "preferred_difficulty": slot.preferred_difficulty,
        "preferred_material_profiles": list(slot.preferred_material_profiles),
    }
    mock_exam_slot = ContentTeamMockExamSlotV1.model_validate(
        {**slot_body, "slot_sha256": content_sha256(slot_body)}
    )
    brief_without_request_hash: dict[str, object] = {
        "schema_version": "3.0",
        "subject": subject_label,
        "topic": unit.label,
        "task_type": slot.preferred_material_profiles[0],
        "difficulty": slot.preferred_difficulty,
        "authoring_guidance": CONTENT_TEAM_ITEM_GUIDANCE,
        "authoring_guidance_sha256": CONTENT_TEAM_ITEM_GUIDANCE_SHA256,
        "curriculum_selected_unit_key": unit.key,
        "mock_exam_slot": mock_exam_slot.model_dump(mode="json"),
    }
    request_sha256 = _original_request_sha256_from_values(brief_without_request_hash)
    brief = ContentTeamItemBriefV3Input.model_validate(
        {**brief_without_request_hash, "original_request_sha256": request_sha256}
    )
    call_body: dict[str, object] = {
        "generation_block_key": block.block_key,
        "generation_block_revision": block.block_revision,
        "generation_block_sha256": block.block_sha256,
        "item_brief": brief.model_dump(mode="json"),
    }
    return MockExamPlannedWorkflowCallV1.model_validate(
        {**call_body, "workflow_call_id": _workflow_call_id(call_body)}
    )


def _original_request_sha256(item_brief: ContentTeamItemBriefV3Input) -> str:
    return _original_request_sha256_from_values(
        item_brief.model_dump(
            mode="json",
            exclude={"original_request_sha256"},
        )
    )


def _original_request_sha256_from_values(
    item_brief_without_request_hash: dict[str, object],
) -> str:
    request_body = {
        "schema_version": "mock-exam-one-item-request/1.0",
        "item_brief": item_brief_without_request_hash,
    }
    return content_sha256(request_body).removeprefix("sha256:")


def _workflow_call_id(call_body: dict[str, object]) -> str:
    return "workflowcall_" + content_sha256(call_body).removeprefix("sha256:")[:32]


def _fail(code: str, message: str) -> Never:
    raise MockExamProductionPlanError(code, message)
