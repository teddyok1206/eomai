from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.educational_quality_models import (
    EducationalQualityReviewObservationRecord,
    EducationalQualityReviewPlanItemRecord,
    EducationalQualityReviewPlanRecord,
    EducationalQualityReviewResolutionRecord,
    EducationalQualityReviewSessionRecord,
)
from eom_api.errors import ApiError
from eom_api.services.educational_quality_service import (
    EducationalQualityReviewApplicationService,
)
from eom_api_contracts.educational_quality import (
    CreateEducationalQualityPlanCommand,
    StartEducationalQualitySessionCommand,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from sqlalchemy import create_engine

NOW = datetime(2026, 10, 2, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32
ASSEMBLY_ID = "assembly_" + "2" * 32
ASSEMBLY_REVISION_ID = "assemblyrev_" + "3" * 32
ASSEMBLY_SHA = "sha256:" + "4" * 64
ITEM_ID = "item_" + "5" * 32
ITEM_REVISION_ID = "itemrev_" + "6" * 32
ITEM_SHA = "sha256:" + "7" * 64


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "8" * 32,
        request_id="request_" + "9" * 32,
        authentication_time=NOW,
        permissions=frozenset({PermissionKey.WORKFLOW_APPROVE}),
        source=ActorSource.APPLICATION_API,
    )


class _Catalog:
    def __init__(self, manifest: Any) -> None:
        self.manifest = manifest

    def inspect_mock_exam_assembly(self, _query: object) -> Any:
        return self.manifest


class _Session:
    def __init__(self, *, scalar_value: object | None = None) -> None:
        self.added: list[object] = []
        self.scalar_value = scalar_value
        self.plan: object | None = None

    def get(self, model: object, _identity: object) -> object | None:
        if model is EducationalQualityReviewPlanRecord:
            return self.plan
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    def scalar(self, _statement: object) -> object | None:
        return self.scalar_value


def _service(manifest: Any) -> EducationalQualityReviewApplicationService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    return EducationalQualityReviewApplicationService(
        engine,
        catalog=cast(Any, _Catalog(manifest)),
    )


def _manifest() -> Any:
    placement = SimpleNamespace(
        position=1,
        display_number="1",
        item_id=ITEM_ID,
        item_revision_id=ITEM_REVISION_ID,
        item_manifest_sha256=ITEM_SHA,
        material_profile="TABLE",
        difficulty_band="MEDIUM",
    )
    return SimpleNamespace(
        assessment_assembly_id=ASSEMBLY_ID,
        assessment_assembly_revision_id=ASSEMBLY_REVISION_ID,
        manifest_sha256=ASSEMBLY_SHA,
        revision_state="RELEASED",
        plan=SimpleNamespace(placements=(placement,)),
    )


def test_create_plan_persists_only_pinned_pointer_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session = _Session()

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[_Session]:
        yield fake_session

    monkeypatch.setattr(
        "eom_api.services.educational_quality_service.transaction", fake_transaction
    )
    service = _service(_manifest())
    command = CreateEducationalQualityPlanCommand(
        operation="CREATE_PLAN",
        assembly_revision_id=ASSEMBLY_REVISION_ID,
        assembly_manifest_sha256=ASSEMBLY_SHA,
        secondary_positions=(1,),
    )
    _command_id, plan_id, version = service.create_plan(command, _actor())

    plans = [
        value
        for value in fake_session.added
        if isinstance(value, EducationalQualityReviewPlanRecord)
    ]
    items = [
        value
        for value in fake_session.added
        if isinstance(value, EducationalQualityReviewPlanItemRecord)
    ]
    assert version == 1
    assert len(plans) == 1 and len(items) == 1
    assert plans[0].plan_id == plan_id
    assert plans[0].assembly_revision_id == ASSEMBLY_REVISION_ID
    assert plans[0].item_set_sha256 == content_sha256(
        (
            {
                "position": 1,
                "item_id": ITEM_ID,
                "item_revision_id": ITEM_REVISION_ID,
                "item_manifest_sha256": ITEM_SHA,
            },
        )
    )
    assert items[0].item_revision_id == ITEM_REVISION_ID
    assert items[0].material_type == "TABLE"


def test_create_plan_rejects_legacy_assembly_without_material_profile() -> None:
    legacy = SimpleNamespace(
        assessment_assembly_id=ASSEMBLY_ID,
        assessment_assembly_revision_id=ASSEMBLY_REVISION_ID,
        manifest_sha256=ASSEMBLY_SHA,
        revision_state="RELEASED",
        placements=(),
    )
    service = _service(legacy)
    with pytest.raises(ApiError) as raised:
        service.create_plan(
            CreateEducationalQualityPlanCommand(
                operation="CREATE_PLAN",
                assembly_revision_id=ASSEMBLY_REVISION_ID,
                assembly_manifest_sha256=ASSEMBLY_SHA,
                secondary_positions=(1,),
            ),
            _actor(),
        )
    assert raised.value.error_code == "EDUCATIONAL_QUALITY_ASSEMBLY_CONTRACT_UNSUPPORTED"


def test_second_role_requires_a_distinct_human_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session = _Session(scalar_value="qualitysession_" + "a" * 32)
    fake_session.plan = SimpleNamespace(plan_id="qualityplan_" + "b" * 32, plan_sha256=ITEM_SHA)

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[_Session]:
        yield fake_session

    monkeypatch.setattr(
        "eom_api.services.educational_quality_service.transaction", fake_transaction
    )
    service = _service(_manifest())
    with pytest.raises(ApiError) as raised:
        service.start_session(
            StartEducationalQualitySessionCommand(
                operation="START_SESSION",
                plan_id=fake_session.plan.plan_id,
                plan_sha256=ITEM_SHA,
                reviewer_role="SECONDARY",
            ),
            _actor(),
        )
    assert raised.value.error_code == "EDUCATIONAL_QUALITY_INDEPENDENT_REVIEWER_REQUIRED"


def _observation(
    session_id: str, *, science_score: int
) -> EducationalQualityReviewObservationRecord:
    return EducationalQualityReviewObservationRecord(
        session_id=session_id,
        position=1,
        item_revision_id=ITEM_REVISION_ID,
        preview_checked=True,
        hwpx_checked=True,
        evidence_checked=True,
        science_score=science_score,
        critical_error=False,
        unique_answer="PASS",
        evidence_score=5,
        authoring_value_score=5,
        visual_score=None,
        visual_not_applicable_reason="시각 자료 없음",
        explanation_quality_score=5,
        disposition="NO_EDIT",
        edit_minutes=3,
        short_reason="채택 가능",
    )


def test_scorecard_requires_resolution_then_uses_chosen_review() -> None:
    plan = EducationalQualityReviewPlanRecord(
        plan_id="qualityplan_" + "a" * 32,
        plan_sha256="sha256:" + "b" * 64,
        assembly_id=ASSEMBLY_ID,
        assembly_revision_id=ASSEMBLY_REVISION_ID,
        assembly_manifest_sha256=ASSEMBLY_SHA,
        item_set_sha256="sha256:" + "c" * 64,
        item_count=1,
        secondary_positions=[1],
        created_by=OPERATOR_ID,
    )
    primary = EducationalQualityReviewSessionRecord(
        session_id="qualitysession_" + "d" * 32,
        plan_id=plan.plan_id,
        reviewer_id=OPERATOR_ID,
        reviewer_role="PRIMARY",
        state="FINALIZED",
        lock_version=2,
        submission_sha256="sha256:" + "e" * 64,
        finalized_at=NOW,
    )
    secondary = EducationalQualityReviewSessionRecord(
        session_id="qualitysession_" + "f" * 32,
        plan_id=plan.plan_id,
        reviewer_id="operator_" + "0" * 32,
        reviewer_role="SECONDARY",
        state="FINALIZED",
        lock_version=2,
        submission_sha256="sha256:" + "1" * 64,
        finalized_at=NOW,
    )
    primary_observation = _observation(primary.session_id, science_score=4)
    secondary_observation = _observation(secondary.session_id, science_score=5)
    observations = {
        primary.session_id: [primary_observation],
        secondary.session_id: [secondary_observation],
    }
    pending = EducationalQualityReviewApplicationService._scorecard(
        plan,
        (primary, secondary),
        observations,
        (),
    )
    assert pending.state == "IN_PROGRESS"
    assert pending.unresolved_disagreement_count == 1
    resolution = EducationalQualityReviewResolutionRecord(
        plan_id=plan.plan_id,
        position=1,
        chosen_session_id=secondary.session_id,
        resolved_by=OPERATOR_ID,
        notes="이중 검토의 과학 점수를 채택",
    )
    ready = EducationalQualityReviewApplicationService._scorecard(
        plan,
        (primary, secondary),
        observations,
        (resolution,),
    )
    assert ready.state == "READY"
    assert ready.metrics is not None
    assert ready.metrics.science_score_milli == 5000
    assert ready.metrics.adoptable_count == 1
