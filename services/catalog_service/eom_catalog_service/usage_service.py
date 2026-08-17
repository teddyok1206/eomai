"""Deliverable planning and immutable actual-usage application service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_catalog_contracts import CreateDeliverable, CreateUsagePlan, FulfillUsagePlan
from eom_identifiers import content_sha256
from eom_item_registry import (
    DeliverableState,
    ItemRevisionState,
    RegistryError,
    RegistryErrorCode,
    UsagePlanState,
    new_deliverable_id,
    new_deliverable_revision_id,
    new_usage_plan_id,
    new_usage_record_id,
    require_usage_plan_transition,
)
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from eom_catalog_service.models import (
    DeliverableEventRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemRecord,
    ItemRevisionRecord,
    UsagePlanRecord,
    UsageRecord,
)


class UsageLedgerService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def create_deliverable(
        self, command: CreateDeliverable
    ) -> tuple[DeliverableRecord, DeliverableRevisionRecord]:
        with transaction(self.sessions) as session:
            existing = session.scalar(
                select(DeliverableRecord).where(
                    DeliverableRecord.deliverable_key == command.deliverable_key
                )
            )
            if existing is not None:
                revision = session.scalar(
                    select(DeliverableRevisionRecord).where(
                        DeliverableRevisionRecord.deliverable_id == existing.deliverable_id,
                        DeliverableRevisionRecord.revision_number == 1,
                    )
                )
                assert revision is not None
                session.expunge(existing)
                session.expunge(revision)
                return existing, revision
            deliverable = DeliverableRecord(
                deliverable_id=new_deliverable_id(),
                deliverable_key=command.deliverable_key,
                deliverable_type=command.deliverable_type,
                title=command.title,
                edition=command.edition,
                lifecycle_state=DeliverableState.PLANNED.value,
                created_by=command.actor_id,
            )
            revision = DeliverableRevisionRecord(
                deliverable_revision_id=new_deliverable_revision_id(),
                deliverable_id=deliverable.deliverable_id,
                revision_number=1,
                state=DeliverableState.PLANNED.value,
                metadata_json=command.metadata,
                metadata_sha256=content_sha256(command.metadata),
            )
            session.add_all((deliverable, revision))
            session.flush()
            self._append_deliverable_event(
                session,
                deliverable,
                revision,
                event_type="DELIVERABLE_CREATED",
                prior_state=None,
                new_state=DeliverableState.PLANNED.value,
                actor_id=command.actor_id,
            )
            session.expunge(deliverable)
            session.expunge(revision)
            return deliverable, revision

    def create_plan(self, command: CreateUsagePlan) -> UsagePlanRecord:
        with transaction(self.sessions) as session:
            item = session.get(ItemRecord, command.item_id)
            deliverable = session.get(DeliverableRecord, command.deliverable_id)
            if item is None:
                raise RegistryError(RegistryErrorCode.ITEM_NOT_FOUND, "item not found")
            if deliverable is None:
                raise RegistryError(
                    RegistryErrorCode.DELIVERABLE_NOT_FOUND, "deliverable not found"
                )
            revision_id = command.preferred_item_revision_id or item.current_revision_id
            revision = session.get(ItemRevisionRecord, revision_id) if revision_id else None
            if (
                revision is None
                or revision.item_id != item.item_id
                or revision.revision_state != ItemRevisionState.APPROVED.value
            ):
                raise RegistryError(
                    RegistryErrorCode.ITEM_REVISION_NOT_APPROVED,
                    "preferred item revision is not approved",
                )
            deliverable_revision = self._resolve_deliverable_revision(
                session, deliverable, command.deliverable_revision_id
            )
            plan = UsagePlanRecord(
                usage_plan_id=new_usage_plan_id(),
                item_id=item.item_id,
                preferred_item_revision_id=revision.item_revision_id,
                deliverable_id=deliverable.deliverable_id,
                deliverable_revision_id=deliverable_revision.deliverable_revision_id,
                planned_section=command.planned_section,
                planned_sequence=command.planned_sequence,
                planned_points=command.planned_points,
                planned_role=command.planned_role,
                status=UsagePlanState.PLANNED.value,
                created_by=command.actor_id,
                notes=None,
                lock_version=1,
            )
            session.add(plan)
            session.flush()
            session.expunge(plan)
            return plan

    def reserve(self, usage_plan_id: str, *, actor_id: str) -> UsagePlanRecord:
        del actor_id
        with transaction(self.sessions) as session:
            plan = self._locked_plan(session, usage_plan_id)
            if plan.status == UsagePlanState.RESERVED.value:
                session.expunge(plan)
                return plan
            require_usage_plan_transition(UsagePlanState(plan.status), UsagePlanState.RESERVED)
            plan.status = UsagePlanState.RESERVED.value
            plan.reserved_at = datetime.now(UTC)
            plan.lock_version += 1
            session.flush()
            session.expunge(plan)
            return plan

    def cancel(self, usage_plan_id: str, *, actor_id: str) -> UsagePlanRecord:
        del actor_id
        with transaction(self.sessions) as session:
            plan = self._locked_plan(session, usage_plan_id)
            if plan.status == UsagePlanState.CANCELLED.value:
                session.expunge(plan)
                return plan
            require_usage_plan_transition(UsagePlanState(plan.status), UsagePlanState.CANCELLED)
            plan.status = UsagePlanState.CANCELLED.value
            plan.lock_version += 1
            session.flush()
            session.expunge(plan)
            return plan

    def fulfill(self, command: FulfillUsagePlan) -> UsageRecord:
        with transaction(self.sessions) as session:
            plan = self._locked_plan(session, command.usage_plan_id)
            existing = session.scalar(
                select(UsageRecord).where(UsageRecord.source_usage_plan_id == command.usage_plan_id)
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            require_usage_plan_transition(UsagePlanState(plan.status), UsagePlanState.FULFILLED)
            revision = session.get(ItemRevisionRecord, plan.preferred_item_revision_id)
            deliverable_revision = session.get(
                DeliverableRevisionRecord, plan.deliverable_revision_id
            )
            if (
                revision is None
                or revision.item_id != plan.item_id
                or revision.revision_state
                not in {ItemRevisionState.APPROVED.value, ItemRevisionState.SUPERSEDED.value}
            ):
                raise RegistryError(
                    RegistryErrorCode.USAGE_ITEM_NOT_APPROVED,
                    "usage item revision is not an approved immutable revision",
                )
            if (
                deliverable_revision is None
                or deliverable_revision.deliverable_id != plan.deliverable_id
            ):
                raise RegistryError(
                    RegistryErrorCode.DELIVERABLE_REVISION_NOT_FOUND,
                    "deliverable revision pointer does not resolve",
                )
            record = UsageRecord(
                usage_record_id=new_usage_record_id(),
                item_id=plan.item_id,
                item_revision_id=revision.item_revision_id,
                deliverable_id=plan.deliverable_id,
                deliverable_revision_id=deliverable_revision.deliverable_revision_id,
                section=plan.planned_section,
                sequence=plan.planned_sequence,
                page=command.page,
                points=plan.planned_points,
                usage_role=command.usage_role,
                source_usage_plan_id=plan.usage_plan_id,
                recorded_by=command.actor_id,
                metadata_json=command.metadata,
            )
            session.add(record)
            plan.status = UsagePlanState.FULFILLED.value
            plan.fulfilled_at = datetime.now(UTC)
            plan.lock_version += 1
            session.flush()
            session.expunge(record)
            return record

    def list_deliverables(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(
                select(DeliverableRecord).order_by(DeliverableRecord.created_at.desc())
            )
            return [self.deliverable_dict(row) for row in rows]

    def inspect_deliverable(self, deliverable_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            deliverable = session.get(DeliverableRecord, deliverable_id)
            if deliverable is None:
                raise RegistryError(
                    RegistryErrorCode.DELIVERABLE_NOT_FOUND, "deliverable not found"
                )
            revisions = list(
                session.scalars(
                    select(DeliverableRevisionRecord)
                    .where(DeliverableRevisionRecord.deliverable_id == deliverable_id)
                    .order_by(DeliverableRevisionRecord.revision_number)
                )
            )
            return self.deliverable_dict(deliverable) | {
                "revisions": [self.deliverable_revision_dict(row) for row in revisions]
            }

    def list_plans(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(
                select(UsagePlanRecord).order_by(UsagePlanRecord.created_at.desc())
            )
            return [self.plan_dict(row) for row in rows]

    def list_records(self, *, item_id: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            query = select(UsageRecord)
            if item_id is not None:
                query = query.where(UsageRecord.item_id == item_id)
            rows = session.scalars(
                query.order_by(UsageRecord.recorded_at.desc(), UsageRecord.usage_record_id)
            )
            return [self.record_dict(row) for row in rows]

    @staticmethod
    def _locked_plan(session: Session, usage_plan_id: str) -> UsagePlanRecord:
        plan = session.execute(
            select(UsagePlanRecord)
            .where(UsagePlanRecord.usage_plan_id == usage_plan_id)
            .with_for_update()
        ).scalar_one_or_none()
        if plan is None:
            raise RegistryError(RegistryErrorCode.USAGE_PLAN_NOT_FOUND, "usage plan not found")
        return plan

    @staticmethod
    def _resolve_deliverable_revision(
        session: Session,
        deliverable: DeliverableRecord,
        revision_id: str | None,
    ) -> DeliverableRevisionRecord:
        if revision_id is not None:
            revision = session.get(DeliverableRevisionRecord, revision_id)
        else:
            revision = session.scalar(
                select(DeliverableRevisionRecord)
                .where(DeliverableRevisionRecord.deliverable_id == deliverable.deliverable_id)
                .order_by(DeliverableRevisionRecord.revision_number.desc())
                .limit(1)
            )
        if revision is None or revision.deliverable_id != deliverable.deliverable_id:
            raise RegistryError(
                RegistryErrorCode.DELIVERABLE_REVISION_NOT_FOUND,
                "deliverable revision pointer does not resolve",
            )
        return revision

    @staticmethod
    def _append_deliverable_event(
        session: Session,
        deliverable: DeliverableRecord,
        revision: DeliverableRevisionRecord,
        *,
        event_type: str,
        prior_state: str | None,
        new_state: str,
        actor_id: str,
    ) -> None:
        sequence = (
            session.scalar(
                select(func.max(DeliverableEventRecord.sequence)).where(
                    DeliverableEventRecord.deliverable_id == deliverable.deliverable_id
                )
            )
            or 0
        ) + 1
        session.add(
            DeliverableEventRecord(
                deliverable_id=deliverable.deliverable_id,
                deliverable_revision_id=revision.deliverable_revision_id,
                sequence=sequence,
                event_type=event_type,
                prior_state=prior_state,
                new_state=new_state,
                actor_id=actor_id,
                payload={"revision_number": revision.revision_number},
            )
        )

    @staticmethod
    def deliverable_dict(record: DeliverableRecord) -> dict[str, Any]:
        return {
            "deliverable_id": record.deliverable_id,
            "deliverable_key": record.deliverable_key,
            "deliverable_type": record.deliverable_type,
            "title": record.title,
            "edition": record.edition,
            "lifecycle_state": record.lifecycle_state,
            "created_at": record.created_at,
            "created_by": record.created_by,
        }

    @staticmethod
    def deliverable_revision_dict(record: DeliverableRevisionRecord) -> dict[str, Any]:
        return {
            "deliverable_revision_id": record.deliverable_revision_id,
            "deliverable_id": record.deliverable_id,
            "revision_number": record.revision_number,
            "state": record.state,
            "metadata_sha256": record.metadata_sha256,
            "created_at": record.created_at,
        }

    @staticmethod
    def plan_dict(record: UsagePlanRecord) -> dict[str, Any]:
        return {
            "usage_plan_id": record.usage_plan_id,
            "item_id": record.item_id,
            "preferred_item_revision_id": record.preferred_item_revision_id,
            "deliverable_id": record.deliverable_id,
            "deliverable_revision_id": record.deliverable_revision_id,
            "planned_section": record.planned_section,
            "planned_sequence": record.planned_sequence,
            "planned_points": record.planned_points,
            "planned_role": record.planned_role,
            "status": record.status,
            "created_at": record.created_at,
        }

    @staticmethod
    def record_dict(record: UsageRecord) -> dict[str, Any]:
        return {
            "usage_record_id": record.usage_record_id,
            "item_id": record.item_id,
            "item_revision_id": record.item_revision_id,
            "deliverable_id": record.deliverable_id,
            "deliverable_revision_id": record.deliverable_revision_id,
            "section": record.section,
            "sequence": record.sequence,
            "page": record.page,
            "points": record.points,
            "usage_role": record.usage_role,
            "source_usage_plan_id": record.source_usage_plan_id,
            "recorded_by": record.recorded_by,
            "recorded_at": record.recorded_at,
        }
