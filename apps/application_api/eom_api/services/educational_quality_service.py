"""Application use case for human educational-quality review of pinned Assemblies."""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast

from eom_api_contracts.educational_quality import (
    CreateEducationalQualityPlanCommand,
    EducationalQualityAssemblyCandidateView,
    EducationalQualityObservationView,
    EducationalQualityPlanDetailView,
    EducationalQualityPlanItemView,
    EducationalQualityPlanSummaryView,
    EducationalQualityResolutionView,
    EducationalQualityReviewCommand,
    EducationalQualityReviewWorkbenchView,
    EducationalQualityScorecardView,
    EducationalQualityScoreMetricsView,
    EducationalQualitySessionView,
    FinalizeEducationalQualitySessionCommand,
    QualityReviewerRole,
    QualitySessionState,
    ResolveEducationalQualityDisagreementCommand,
    StartEducationalQualitySessionCommand,
    UpsertEducationalQualityObservationCommand,
)
from eom_catalog_contracts import InspectMockExamAssemblyQuery
from eom_catalog_service.legacy_usage_models import (
    AssessmentAssemblyRevisionRecord,
    AssessmentItemPlacementRecord,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_api.educational_quality_models import (
    EducationalQualityReviewObservationRecord,
    EducationalQualityReviewPlanItemRecord,
    EducationalQualityReviewPlanRecord,
    EducationalQualityReviewResolutionRecord,
    EducationalQualityReviewSessionRecord,
)
from eom_api.errors import ApiError
from eom_api.services.catalog_application_client import CatalogApplicationClient


def _command_id() -> str:
    return "qualitycmd_" + secrets.token_hex(16)


class EducationalQualityReviewApplicationService:
    """Persist evaluations without changing Catalog Item or Assembly lifecycle."""

    def __init__(self, engine: Engine, *, catalog: CatalogApplicationClient) -> None:
        self.sessions = build_session_factory(engine)
        self.catalog = catalog

    @staticmethod
    def _not_found(code: str, detail: str) -> ApiError:
        return ApiError(404, code, "Educational quality review not found", detail)

    @staticmethod
    def _conflict(code: str, detail: str) -> ApiError:
        return ApiError(409, code, "Educational quality review conflict", detail)

    @staticmethod
    def _actor_id(actor: ActorContext) -> str:
        if actor.operator_id is None:
            raise ApiError(
                403,
                "EDUCATIONAL_QUALITY_OPERATOR_REQUIRED",
                "Operator identity required",
                "Educational quality review requires an authenticated human operator.",
            )
        return actor.operator_id

    @staticmethod
    def _plan_body(
        *,
        assembly_id: str,
        assembly_revision_id: str,
        assembly_manifest_sha256: str,
        item_set_sha256: str,
        item_count: int,
        secondary_positions: tuple[int, ...],
    ) -> dict[str, object]:
        return {
            "schema_version": "educational-quality-review-plan/1.0",
            "assembly_id": assembly_id,
            "assembly_revision_id": assembly_revision_id,
            "assembly_manifest_sha256": assembly_manifest_sha256,
            "item_set_sha256": item_set_sha256,
            "item_count": item_count,
            "secondary_positions": list(secondary_positions),
        }

    def create_plan(
        self,
        command: CreateEducationalQualityPlanCommand,
        actor: ActorContext,
    ) -> tuple[str, str, int]:
        manifest = self.catalog.inspect_mock_exam_assembly(
            InspectMockExamAssemblyQuery(
                assessment_assembly_revision_id=command.assembly_revision_id
            )
        )
        if (
            manifest.assessment_assembly_revision_id != command.assembly_revision_id
            or manifest.manifest_sha256 != command.assembly_manifest_sha256
            or manifest.revision_state != "RELEASED"
        ):
            raise self._conflict(
                "EDUCATIONAL_QUALITY_ASSEMBLY_POINTER_MISMATCH",
                "The Assembly revision is missing, not released, or differs from its pinned hash.",
            )
        if not hasattr(manifest, "plan"):
            raise self._conflict(
                "EDUCATIONAL_QUALITY_ASSEMBLY_CONTRACT_UNSUPPORTED",
                "Educational quality review requires an Assembly manifest with material-profile "
                "placements.",
            )
        placements = manifest.plan.placements
        positions = tuple(row.position for row in placements)
        if positions != tuple(range(1, len(placements) + 1)):
            raise self._conflict(
                "EDUCATIONAL_QUALITY_ASSEMBLY_ORDER_INVALID",
                "The Assembly does not contain a contiguous ordered Item set.",
            )
        if len({row.item_revision_id for row in placements}) != len(placements):
            raise self._conflict(
                "EDUCATIONAL_QUALITY_ASSEMBLY_ITEM_DUPLICATE",
                "The Assembly repeats an immutable Item revision.",
            )
        if command.secondary_positions[-1] > len(placements):
            raise self._conflict(
                "EDUCATIONAL_QUALITY_SECONDARY_POSITION_INVALID",
                "A secondary-review position is outside the pinned Assembly.",
            )
        item_pointers = tuple(
            {
                "position": row.position,
                "item_id": row.item_id,
                "item_revision_id": row.item_revision_id,
                "item_manifest_sha256": row.item_manifest_sha256,
            }
            for row in placements
        )
        item_set_sha256 = content_sha256(item_pointers)
        plan_body = self._plan_body(
            assembly_id=manifest.assessment_assembly_id,
            assembly_revision_id=manifest.assessment_assembly_revision_id,
            assembly_manifest_sha256=manifest.manifest_sha256,
            item_set_sha256=item_set_sha256,
            item_count=len(placements),
            secondary_positions=command.secondary_positions,
        )
        plan_sha256 = content_sha256(plan_body)
        plan_id = "qualityplan_" + plan_sha256.removeprefix("sha256:")[:32]
        operator_id = self._actor_id(actor)
        try:
            with transaction(self.sessions) as session:
                assembly_plan = session.scalar(
                    select(EducationalQualityReviewPlanRecord)
                    .where(
                        EducationalQualityReviewPlanRecord.assembly_revision_id
                        == command.assembly_revision_id
                    )
                    .limit(1)
                )
                if assembly_plan is not None:
                    if assembly_plan.plan_sha256 != plan_sha256:
                        raise self._conflict(
                            "EDUCATIONAL_QUALITY_ASSEMBLY_PLAN_EXISTS",
                            "This immutable Assembly revision already has a different quality "
                            "review plan.",
                        )
                    return _command_id(), assembly_plan.plan_id, 1
                existing = session.get(EducationalQualityReviewPlanRecord, plan_id)
                if existing is not None:
                    if existing.plan_sha256 != plan_sha256:
                        raise self._conflict(
                            "EDUCATIONAL_QUALITY_PLAN_ID_CONFLICT",
                            "The deterministic plan identity already binds different content.",
                        )
                    return _command_id(), plan_id, 1
                session.add(
                    EducationalQualityReviewPlanRecord(
                        plan_id=plan_id,
                        plan_sha256=plan_sha256,
                        assembly_id=manifest.assessment_assembly_id,
                        assembly_revision_id=manifest.assessment_assembly_revision_id,
                        assembly_manifest_sha256=manifest.manifest_sha256,
                        item_set_sha256=item_set_sha256,
                        item_count=len(placements),
                        secondary_positions=list(command.secondary_positions),
                        created_by=operator_id,
                    )
                )
                for row in placements:
                    session.add(
                        EducationalQualityReviewPlanItemRecord(
                            plan_id=plan_id,
                            position=row.position,
                            display_number=row.display_number,
                            item_id=row.item_id,
                            item_revision_id=row.item_revision_id,
                            item_manifest_sha256=row.item_manifest_sha256,
                            material_type=row.material_profile,
                            difficulty_band=row.difficulty_band,
                        )
                    )
        except IntegrityError as exc:
            raise self._conflict(
                "EDUCATIONAL_QUALITY_PLAN_CONCURRENT_CONFLICT",
                "A quality plan for this Assembly revision was created concurrently.",
            ) from exc
        return _command_id(), plan_id, 1

    def start_session(
        self,
        command: StartEducationalQualitySessionCommand,
        actor: ActorContext,
    ) -> tuple[str, str, int]:
        operator_id = self._actor_id(actor)
        unsigned = {
            "plan_id": command.plan_id,
            "reviewer_id": operator_id,
            "reviewer_role": command.reviewer_role,
        }
        session_id = "qualitysession_" + content_sha256(unsigned).removeprefix("sha256:")[:32]
        try:
            with transaction(self.sessions) as session:
                plan = session.get(EducationalQualityReviewPlanRecord, command.plan_id)
                if plan is None:
                    raise self._not_found(
                        "EDUCATIONAL_QUALITY_PLAN_NOT_FOUND", "The selected quality plan is absent."
                    )
                if plan.plan_sha256 != command.plan_sha256:
                    raise self._conflict(
                        "EDUCATIONAL_QUALITY_PLAN_HASH_MISMATCH",
                        "The selected quality plan hash does not match.",
                    )
                conflicting_session = session.scalar(
                    select(EducationalQualityReviewSessionRecord.session_id)
                    .where(
                        EducationalQualityReviewSessionRecord.plan_id == plan.plan_id,
                        (
                            EducationalQualityReviewSessionRecord.reviewer_role
                            == command.reviewer_role
                        )
                        | (EducationalQualityReviewSessionRecord.reviewer_id == operator_id),
                    )
                    .limit(1)
                )
                existing = session.get(EducationalQualityReviewSessionRecord, session_id)
                if existing is not None:
                    return _command_id(), session_id, existing.lock_version
                if conflicting_session is not None:
                    raise self._conflict(
                        "EDUCATIONAL_QUALITY_INDEPENDENT_REVIEWER_REQUIRED",
                        "Each plan has one reviewer per role, and the second role must use a "
                        "different human operator.",
                    )
                session.add(
                    EducationalQualityReviewSessionRecord(
                        session_id=session_id,
                        plan_id=plan.plan_id,
                        reviewer_id=operator_id,
                        reviewer_role=command.reviewer_role,
                        state="DRAFT",
                        lock_version=1,
                    )
                )
        except IntegrityError as exc:
            raise self._conflict(
                "EDUCATIONAL_QUALITY_SESSION_CONCURRENT_CONFLICT",
                "This reviewer session was created concurrently.",
            ) from exc
        return _command_id(), session_id, 1

    @staticmethod
    def _locked_session(
        session: Session,
        session_id: str,
    ) -> EducationalQualityReviewSessionRecord:
        value = session.scalar(
            select(EducationalQualityReviewSessionRecord)
            .where(EducationalQualityReviewSessionRecord.session_id == session_id)
            .with_for_update()
        )
        if value is None:
            raise EducationalQualityReviewApplicationService._not_found(
                "EDUCATIONAL_QUALITY_SESSION_NOT_FOUND",
                "The selected review session is absent.",
            )
        return value

    def upsert_observation(
        self,
        command: UpsertEducationalQualityObservationCommand,
        actor: ActorContext,
    ) -> tuple[str, str, int]:
        operator_id = self._actor_id(actor)
        with transaction(self.sessions) as session:
            review_session = self._locked_session(session, command.session_id)
            if review_session.reviewer_id != operator_id:
                raise ApiError(
                    403,
                    "EDUCATIONAL_QUALITY_SESSION_FORBIDDEN",
                    "Review session access denied",
                    "Only the session reviewer may change a draft observation.",
                )
            if review_session.state != "DRAFT":
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_SESSION_FINALIZED",
                    "A finalized review session cannot be changed.",
                )
            if review_session.lock_version != command.expected_lock_version:
                raise ApiError(
                    412,
                    "EDUCATIONAL_QUALITY_VERSION_MISMATCH",
                    "Review session version mismatch",
                    "Reload the workbench before saving this observation.",
                )
            expected_item = session.get(
                EducationalQualityReviewPlanItemRecord,
                (review_session.plan_id, command.observation.position),
            )
            if (
                expected_item is None
                or expected_item.item_revision_id != command.observation.item_revision_id
            ):
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_ITEM_POINTER_MISMATCH",
                    "The observation does not bind the pinned Item revision at this position.",
                )
            if review_session.reviewer_role == "SECONDARY":
                plan = session.get(EducationalQualityReviewPlanRecord, review_session.plan_id)
                assert plan is not None
                if command.observation.position not in set(plan.secondary_positions):
                    raise self._conflict(
                        "EDUCATIONAL_QUALITY_POSITION_NOT_ASSIGNED",
                        "This position is not assigned to the secondary reviewer.",
                    )
            values = command.observation.model_dump(mode="python")
            row = session.get(
                EducationalQualityReviewObservationRecord,
                (review_session.session_id, command.observation.position),
            )
            if row is None:
                row = EducationalQualityReviewObservationRecord(
                    session_id=review_session.session_id,
                    **values,
                )
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.updated_at = datetime.now(UTC)
            review_session.lock_version += 1
            review_session.updated_at = datetime.now(UTC)
            version = review_session.lock_version
        return _command_id(), command.session_id, version

    @staticmethod
    def _required_positions(
        plan: EducationalQualityReviewPlanRecord,
        review_session: EducationalQualityReviewSessionRecord,
    ) -> tuple[int, ...]:
        if review_session.reviewer_role == "PRIMARY":
            return tuple(range(1, plan.item_count + 1))
        return tuple(plan.secondary_positions)

    def finalize_session(
        self,
        command: FinalizeEducationalQualitySessionCommand,
        actor: ActorContext,
    ) -> tuple[str, str, int]:
        operator_id = self._actor_id(actor)
        with transaction(self.sessions) as session:
            review_session = self._locked_session(session, command.session_id)
            if review_session.reviewer_id != operator_id:
                raise ApiError(
                    403,
                    "EDUCATIONAL_QUALITY_SESSION_FORBIDDEN",
                    "Review session access denied",
                    "Only the session reviewer may finalize it.",
                )
            if review_session.state == "FINALIZED":
                return _command_id(), review_session.session_id, review_session.lock_version
            if review_session.lock_version != command.expected_lock_version:
                raise ApiError(
                    412,
                    "EDUCATIONAL_QUALITY_VERSION_MISMATCH",
                    "Review session version mismatch",
                    "Reload the workbench before finalizing this session.",
                )
            plan = session.get(EducationalQualityReviewPlanRecord, review_session.plan_id)
            assert plan is not None
            required = self._required_positions(plan, review_session)
            rows = tuple(
                session.scalars(
                    select(EducationalQualityReviewObservationRecord)
                    .where(
                        EducationalQualityReviewObservationRecord.session_id
                        == review_session.session_id
                    )
                    .order_by(EducationalQualityReviewObservationRecord.position)
                )
            )
            if tuple(row.position for row in rows) != required or any(
                not row.preview_checked or not row.hwpx_checked or not row.evidence_checked
                for row in rows
            ):
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_SESSION_INCOMPLETE",
                    "Every assigned Item must have Preview, HWPX, evidence, and rubric checks.",
                )
            review_session.submission_sha256 = content_sha256(
                [self._observation_payload(row) for row in rows]
            )
            review_session.state = "FINALIZED"
            review_session.lock_version += 1
            review_session.updated_at = datetime.now(UTC)
            review_session.finalized_at = review_session.updated_at
            version = review_session.lock_version
        return _command_id(), command.session_id, version

    def resolve_disagreement(
        self,
        command: ResolveEducationalQualityDisagreementCommand,
        actor: ActorContext,
    ) -> tuple[str, str, int]:
        operator_id = self._actor_id(actor)
        with transaction(self.sessions) as session:
            plan = session.get(EducationalQualityReviewPlanRecord, command.plan_id)
            if plan is None:
                raise self._not_found(
                    "EDUCATIONAL_QUALITY_PLAN_NOT_FOUND", "The selected quality plan is absent."
                )
            if plan.plan_sha256 != command.plan_sha256:
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_PLAN_HASH_MISMATCH",
                    "The selected quality plan hash does not match.",
                )
            if command.position not in set(plan.secondary_positions):
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_RESOLUTION_POSITION_INVALID",
                    "Only a secondary-review position can have a resolution.",
                )
            chosen = session.get(EducationalQualityReviewSessionRecord, command.chosen_session_id)
            if chosen is None or chosen.plan_id != plan.plan_id or chosen.state != "FINALIZED":
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_RESOLUTION_SESSION_INVALID",
                    "The chosen session is not a finalized session for this plan.",
                )
            primary = session.scalar(
                select(EducationalQualityReviewSessionRecord.session_id)
                .join(
                    EducationalQualityReviewObservationRecord,
                    EducationalQualityReviewObservationRecord.session_id
                    == EducationalQualityReviewSessionRecord.session_id,
                )
                .where(
                    EducationalQualityReviewSessionRecord.plan_id == plan.plan_id,
                    EducationalQualityReviewSessionRecord.reviewer_role == "PRIMARY",
                    EducationalQualityReviewSessionRecord.state == "FINALIZED",
                    EducationalQualityReviewObservationRecord.position == command.position,
                )
                .limit(1)
            )
            secondary = session.scalar(
                select(EducationalQualityReviewSessionRecord.session_id)
                .join(
                    EducationalQualityReviewObservationRecord,
                    EducationalQualityReviewObservationRecord.session_id
                    == EducationalQualityReviewSessionRecord.session_id,
                )
                .where(
                    EducationalQualityReviewSessionRecord.plan_id == plan.plan_id,
                    EducationalQualityReviewSessionRecord.reviewer_role == "SECONDARY",
                    EducationalQualityReviewSessionRecord.state == "FINALIZED",
                    EducationalQualityReviewObservationRecord.position == command.position,
                )
                .limit(1)
            )
            if primary is None or secondary is None:
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_RESOLUTION_REVIEWS_INCOMPLETE",
                    "Both primary and secondary finalized observations are required.",
                )
            if chosen.session_id not in {primary, secondary}:
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_RESOLUTION_SESSION_INVALID",
                    "The chosen session does not own either independent observation.",
                )
            primary_observation = session.get(
                EducationalQualityReviewObservationRecord,
                (primary, command.position),
            )
            secondary_observation = session.get(
                EducationalQualityReviewObservationRecord,
                (secondary, command.position),
            )
            if primary_observation is None or secondary_observation is None:
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_RESOLUTION_REVIEWS_INCOMPLETE",
                    "Both independent observations are required at this position.",
                )
            if self._observation_payload(primary_observation) == self._observation_payload(
                secondary_observation
            ):
                raise self._conflict(
                    "EDUCATIONAL_QUALITY_RESOLUTION_NOT_REQUIRED",
                    "Identical independent observations do not require a resolution.",
                )
            existing = session.get(
                EducationalQualityReviewResolutionRecord,
                (plan.plan_id, command.position),
            )
            if existing is not None:
                if (
                    existing.chosen_session_id != command.chosen_session_id
                    or existing.notes != command.notes
                ):
                    raise self._conflict(
                        "EDUCATIONAL_QUALITY_RESOLUTION_IMMUTABLE",
                        "This disagreement already has a different immutable resolution.",
                    )
                return _command_id(), plan.plan_id, 1
            session.add(
                EducationalQualityReviewResolutionRecord(
                    plan_id=plan.plan_id,
                    position=command.position,
                    chosen_session_id=command.chosen_session_id,
                    resolved_by=operator_id,
                    notes=command.notes,
                )
            )
        return _command_id(), command.plan_id, 1

    def execute(
        self,
        command: EducationalQualityReviewCommand,
        actor: ActorContext,
    ) -> tuple[str, str, int, str]:
        if isinstance(command, CreateEducationalQualityPlanCommand):
            command_id, resource_id, version = self.create_plan(command, actor)
            return command_id, resource_id, version, "educational_quality_review_plan"
        if isinstance(command, StartEducationalQualitySessionCommand):
            command_id, resource_id, version = self.start_session(command, actor)
            return command_id, resource_id, version, "educational_quality_review_session"
        if isinstance(command, UpsertEducationalQualityObservationCommand):
            command_id, resource_id, version = self.upsert_observation(command, actor)
            return command_id, resource_id, version, "educational_quality_review_session"
        if isinstance(command, FinalizeEducationalQualitySessionCommand):
            command_id, resource_id, version = self.finalize_session(command, actor)
            return command_id, resource_id, version, "educational_quality_review_session"
        command_id, resource_id, version = self.resolve_disagreement(command, actor)
        return command_id, resource_id, version, "educational_quality_review_plan"

    @staticmethod
    def _observation_payload(
        row: EducationalQualityReviewObservationRecord,
    ) -> dict[str, object]:
        return {
            "position": row.position,
            "item_revision_id": row.item_revision_id,
            "preview_checked": row.preview_checked,
            "hwpx_checked": row.hwpx_checked,
            "evidence_checked": row.evidence_checked,
            "science_score": row.science_score,
            "critical_error": row.critical_error,
            "unique_answer": row.unique_answer,
            "evidence_score": row.evidence_score,
            "authoring_value_score": row.authoring_value_score,
            "visual_score": row.visual_score,
            "visual_not_applicable_reason": row.visual_not_applicable_reason,
            "explanation_quality_score": row.explanation_quality_score,
            "disposition": row.disposition,
            "edit_minutes": row.edit_minutes,
            "short_reason": row.short_reason,
        }

    @classmethod
    def _observation_view(
        cls, row: EducationalQualityReviewObservationRecord
    ) -> EducationalQualityObservationView:
        return EducationalQualityObservationView.model_validate(
            cls._observation_payload(row) | {"updated_at": row.updated_at}
        )

    @staticmethod
    def _summary(
        plan: EducationalQualityReviewPlanRecord,
        sessions: Iterable[EducationalQualityReviewSessionRecord],
        resolved_count: int,
    ) -> EducationalQualityPlanSummaryView:
        session_rows = tuple(sessions)
        return EducationalQualityPlanSummaryView(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            assembly_revision_id=plan.assembly_revision_id,
            assembly_manifest_sha256=plan.assembly_manifest_sha256,
            item_count=plan.item_count,
            primary_finalized=any(
                row.reviewer_role == "PRIMARY" and row.state == "FINALIZED" for row in session_rows
            ),
            secondary_finalized=any(
                row.reviewer_role == "SECONDARY" and row.state == "FINALIZED"
                for row in session_rows
            ),
            resolved_count=resolved_count,
            created_at=plan.created_at,
        )

    @staticmethod
    def _milli_mean(values: tuple[int, ...]) -> int:
        return (sum(values) * 1000 + len(values) // 2) // len(values)

    @classmethod
    def _scorecard(
        cls,
        plan: EducationalQualityReviewPlanRecord,
        sessions: tuple[EducationalQualityReviewSessionRecord, ...],
        observations_by_session: dict[str, list[EducationalQualityReviewObservationRecord]],
        resolutions: tuple[EducationalQualityReviewResolutionRecord, ...],
    ) -> EducationalQualityScorecardView:
        primary = next((row for row in sessions if row.reviewer_role == "PRIMARY"), None)
        secondary = next((row for row in sessions if row.reviewer_role == "SECONDARY"), None)
        primary_rows = (
            () if primary is None else tuple(observations_by_session.get(primary.session_id, ()))
        )
        secondary_rows = (
            ()
            if secondary is None
            else tuple(observations_by_session.get(secondary.session_id, ()))
        )
        if (
            primary is None
            or secondary is None
            or primary.state != "FINALIZED"
            or secondary.state != "FINALIZED"
        ):
            return EducationalQualityScorecardView(
                state="IN_PROGRESS",
                primary_observation_count=len(primary_rows),
                secondary_observation_count=len(secondary_rows),
                unresolved_disagreement_count=0,
                metrics=None,
            )
        primary_by_position = {row.position: row for row in primary_rows}
        secondary_by_position = {row.position: row for row in secondary_rows}
        resolution_by_position = {row.position: row for row in resolutions}
        if len(primary_by_position) != plan.item_count or set(secondary_by_position) != set(
            plan.secondary_positions
        ):
            raise ApiError(
                500,
                "EDUCATIONAL_QUALITY_FINALIZED_STATE_INVALID",
                "Educational quality state is invalid",
                "A finalized review does not cover its exact pinned Item positions.",
            )
        canonical = dict(primary_by_position)
        unresolved = 0
        for position in plan.secondary_positions:
            primary_row = primary_by_position[position]
            secondary_row = secondary_by_position[position]
            if cls._observation_payload(primary_row) == cls._observation_payload(secondary_row):
                continue
            resolution = resolution_by_position.get(position)
            if resolution is None:
                unresolved += 1
                continue
            if resolution.chosen_session_id == primary.session_id:
                canonical[position] = primary_row
            elif resolution.chosen_session_id == secondary.session_id:
                canonical[position] = secondary_row
            else:
                raise ApiError(
                    500,
                    "EDUCATIONAL_QUALITY_RESOLUTION_STATE_INVALID",
                    "Educational quality resolution is invalid",
                    "A resolution does not point to either independent finalized review.",
                )
        if unresolved:
            return EducationalQualityScorecardView(
                state="IN_PROGRESS",
                primary_observation_count=len(primary_rows),
                secondary_observation_count=len(secondary_rows),
                unresolved_disagreement_count=unresolved,
                metrics=None,
            )
        ordered = tuple(canonical[position] for position in range(1, plan.item_count + 1))
        dispositions = {value: 0 for value in ("NO_EDIT", "MINOR_EDIT", "MAJOR_EDIT", "DISCARD")}
        unique_answers = {value: 0 for value in ("PASS", "AMBIGUOUS", "FAIL")}
        for row in ordered:
            dispositions[row.disposition] += 1
            unique_answers[row.unique_answer] += 1
        visual_scores = tuple(row.visual_score for row in ordered if row.visual_score is not None)
        edit_minutes = tuple(row.edit_minutes for row in ordered)
        metrics = EducationalQualityScoreMetricsView(
            item_count=len(ordered),
            no_edit_count=dispositions["NO_EDIT"],
            minor_edit_count=dispositions["MINOR_EDIT"],
            major_edit_count=dispositions["MAJOR_EDIT"],
            discard_count=dispositions["DISCARD"],
            adoptable_count=dispositions["NO_EDIT"] + dispositions["MINOR_EDIT"],
            critical_error_count=sum(1 for row in ordered if row.critical_error),
            unique_answer_pass_count=unique_answers["PASS"],
            unique_answer_ambiguous_count=unique_answers["AMBIGUOUS"],
            unique_answer_fail_count=unique_answers["FAIL"],
            total_edit_minutes=sum(edit_minutes),
            mean_edit_minutes_milli=cls._milli_mean(edit_minutes),
            science_score_milli=cls._milli_mean(tuple(row.science_score for row in ordered)),
            evidence_score_milli=cls._milli_mean(tuple(row.evidence_score for row in ordered)),
            authoring_value_score_milli=cls._milli_mean(
                tuple(row.authoring_value_score for row in ordered)
            ),
            explanation_quality_score_milli=cls._milli_mean(
                tuple(row.explanation_quality_score for row in ordered)
            ),
            visual_scored_item_count=len(visual_scores),
            visual_score_milli=cls._milli_mean(visual_scores) if visual_scores else None,
        )
        return EducationalQualityScorecardView(
            state="READY",
            primary_observation_count=len(primary_rows),
            secondary_observation_count=len(secondary_rows),
            unresolved_disagreement_count=0,
            metrics=metrics,
        )

    def workbench(self, plan_id: str | None = None) -> EducationalQualityReviewWorkbenchView:
        with self.sessions() as session:
            placement_counts = (
                select(
                    AssessmentItemPlacementRecord.assessment_assembly_revision_id.label(
                        "assembly_revision_id"
                    ),
                    func.count().label("item_count"),
                )
                .group_by(AssessmentItemPlacementRecord.assessment_assembly_revision_id)
                .subquery()
            )
            candidates = tuple(
                session.execute(
                    select(
                        AssessmentAssemblyRevisionRecord,
                        placement_counts.c.item_count,
                        EducationalQualityReviewPlanRecord.plan_id,
                    )
                    .join(
                        placement_counts,
                        placement_counts.c.assembly_revision_id
                        == AssessmentAssemblyRevisionRecord.assessment_assembly_revision_id,
                    )
                    .outerjoin(
                        EducationalQualityReviewPlanRecord,
                        EducationalQualityReviewPlanRecord.assembly_revision_id
                        == AssessmentAssemblyRevisionRecord.assessment_assembly_revision_id,
                    )
                    .where(
                        AssessmentAssemblyRevisionRecord.revision_state == "RELEASED",
                        AssessmentAssemblyRevisionRecord.canonical_document["schema_version"]
                        .as_string()
                        .in_(
                            (
                                "mock-exam-assembly-manifest/2.0",
                                "mock-exam-assembly-manifest/3.0",
                            )
                        ),
                    )
                    .order_by(
                        AssessmentAssemblyRevisionRecord.created_at.desc(),
                        AssessmentAssemblyRevisionRecord.assessment_assembly_revision_id,
                    )
                    .limit(50)
                )
            )
            plans = tuple(
                session.scalars(
                    select(EducationalQualityReviewPlanRecord)
                    .order_by(
                        EducationalQualityReviewPlanRecord.created_at.desc(),
                        EducationalQualityReviewPlanRecord.plan_id,
                    )
                    .limit(100)
                )
            )
            plan_ids = tuple(row.plan_id for row in plans)
            all_sessions = (
                tuple(
                    session.scalars(
                        select(EducationalQualityReviewSessionRecord).where(
                            EducationalQualityReviewSessionRecord.plan_id.in_(plan_ids)
                        )
                    )
                )
                if plan_ids
                else ()
            )
            all_resolutions = (
                tuple(
                    session.scalars(
                        select(EducationalQualityReviewResolutionRecord).where(
                            EducationalQualityReviewResolutionRecord.plan_id.in_(plan_ids)
                        )
                    )
                )
                if plan_ids
                else ()
            )
            sessions_by_plan: dict[str, list[EducationalQualityReviewSessionRecord]] = {}
            for review_session_row in all_sessions:
                sessions_by_plan.setdefault(review_session_row.plan_id, []).append(
                    review_session_row
                )
            resolution_count: dict[str, int] = {}
            for resolution_row in all_resolutions:
                resolution_count[resolution_row.plan_id] = (
                    resolution_count.get(resolution_row.plan_id, 0) + 1
                )
            summaries = tuple(
                self._summary(
                    row,
                    sessions_by_plan.get(row.plan_id, ()),
                    resolution_count.get(row.plan_id, 0),
                )
                for row in plans
            )
            selected = self._plan_detail(session, plan_id) if plan_id is not None else None
            return EducationalQualityReviewWorkbenchView(
                schema_version="educational-quality-review-workbench/1.0",
                candidate_assemblies=tuple(
                    EducationalQualityAssemblyCandidateView(
                        assembly_id=row.assessment_assembly_id,
                        assembly_revision_id=row.assessment_assembly_revision_id,
                        manifest_sha256=row.manifest_sha256,
                        revision_state=row.revision_state,
                        item_count=item_count,
                        created_at=row.created_at,
                        existing_plan_id=existing_plan_id,
                    )
                    for row, item_count, existing_plan_id in candidates
                ),
                plans=summaries,
                selected_plan=selected,
            )

    def _plan_detail(
        self,
        session: Session,
        plan_id: str,
    ) -> EducationalQualityPlanDetailView:
        plan = session.get(EducationalQualityReviewPlanRecord, plan_id)
        if plan is None:
            raise self._not_found(
                "EDUCATIONAL_QUALITY_PLAN_NOT_FOUND", "The selected quality plan is absent."
            )
        items = tuple(
            session.scalars(
                select(EducationalQualityReviewPlanItemRecord)
                .where(EducationalQualityReviewPlanItemRecord.plan_id == plan_id)
                .order_by(EducationalQualityReviewPlanItemRecord.position)
            )
        )
        session_rows = tuple(
            session.scalars(
                select(EducationalQualityReviewSessionRecord)
                .where(EducationalQualityReviewSessionRecord.plan_id == plan_id)
                .order_by(
                    EducationalQualityReviewSessionRecord.created_at,
                    EducationalQualityReviewSessionRecord.session_id,
                )
            )
        )
        session_ids = tuple(row.session_id for row in session_rows)
        observations = (
            tuple(
                session.scalars(
                    select(EducationalQualityReviewObservationRecord)
                    .where(EducationalQualityReviewObservationRecord.session_id.in_(session_ids))
                    .order_by(
                        EducationalQualityReviewObservationRecord.session_id,
                        EducationalQualityReviewObservationRecord.position,
                    )
                )
            )
            if session_ids
            else ()
        )
        observations_by_session: dict[str, list[EducationalQualityReviewObservationRecord]] = {}
        for row in observations:
            observations_by_session.setdefault(row.session_id, []).append(row)
        resolutions = tuple(
            session.scalars(
                select(EducationalQualityReviewResolutionRecord)
                .where(EducationalQualityReviewResolutionRecord.plan_id == plan_id)
                .order_by(EducationalQualityReviewResolutionRecord.position)
            )
        )
        summary = self._summary(plan, session_rows, len(resolutions))
        return EducationalQualityPlanDetailView(
            summary=summary,
            assembly_id=plan.assembly_id,
            secondary_positions=tuple(plan.secondary_positions),
            items=tuple(
                EducationalQualityPlanItemView(
                    position=row.position,
                    display_number=row.display_number,
                    item_id=row.item_id,
                    item_revision_id=row.item_revision_id,
                    item_manifest_sha256=row.item_manifest_sha256,
                    material_type=row.material_type,
                    difficulty_band=row.difficulty_band,
                )
                for row in items
            ),
            sessions=tuple(
                EducationalQualitySessionView(
                    session_id=row.session_id,
                    reviewer_id=row.reviewer_id,
                    reviewer_role=cast(QualityReviewerRole, row.reviewer_role),
                    state=cast(QualitySessionState, row.state),
                    lock_version=row.lock_version,
                    required_positions=self._required_positions(plan, row),
                    observations=tuple(
                        self._observation_view(observation)
                        for observation in observations_by_session.get(row.session_id, ())
                    ),
                    created_at=row.created_at,
                    finalized_at=row.finalized_at,
                )
                for row in session_rows
            ),
            resolutions=tuple(
                EducationalQualityResolutionView(
                    position=row.position,
                    chosen_session_id=row.chosen_session_id,
                    resolved_by=row.resolved_by,
                    notes=row.notes,
                    resolved_at=row.resolved_at,
                )
                for row in resolutions
            ),
            scorecard=self._scorecard(
                plan,
                session_rows,
                observations_by_session,
                resolutions,
            ),
        )
