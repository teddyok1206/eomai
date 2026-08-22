"""Read-only SQLAlchemy adapter for stable API projections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Never

from eom_api_contracts.common import ArtifactPointer
from eom_api_contracts.content_intakes import (
    ContentIntakeSummary,
    IntakeDetail,
    SourceFileView,
)
from eom_api_contracts.content_packs import (
    ContentPackActivationView,
    ContentPackReleaseView,
)
from eom_api_contracts.deliverables import DeliverableView
from eom_api_contracts.events import EventView
from eom_api_contracts.hwpx import HwpxBuildView
from eom_api_contracts.items import (
    ItemComponentView,
    ItemRelationshipView,
    ItemRevisionView,
    ItemView,
)
from eom_api_contracts.usage import UsagePlanView, UsageRecordView
from eom_api_contracts.workflows import WorkflowStepView, WorkflowView
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeEventRecord,
    ContentIntakeSourceFileRecord,
    ContentPackActivationRecord,
    ContentPackEventRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
    DeliverableEventRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemComponentRecord,
    ItemEventRecord,
    ItemRecord,
    ItemRelationshipRecord,
    ItemRevisionRecord,
    UsagePlanRecord,
    UsageRecord,
)
from eom_hwpx_manager.models import HwpxApplicationBuildRecord
from eom_identity_service.models import OperatorEventRecord
from eom_orchestrator.database import build_session_factory
from eom_workflow_runner.models import (
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import Engine, Select, and_, or_, select
from sqlalchemy.orm import Session

from eom_api.errors import ApiError
from eom_api.services.hwpx_projection import project_hwpx_build


@dataclass(frozen=True)
class PageResult[ViewT]:
    data: tuple[ViewT, ...]
    next_cursor: str | None
    has_more: bool


class CursorCodec:
    def __init__(self, key: bytes) -> None:
        self._key = key

    def encode(self, resource: str, created_at: datetime, resource_id: str) -> str:
        payload = json.dumps(
            {"r": resource, "t": created_at.isoformat(), "i": resource_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return self._b64(payload + signature)

    def decode(self, cursor: str, resource: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            payload, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self._key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            if value["r"] != resource or not isinstance(value["i"], str):
                raise ValueError
            timestamp = datetime.fromisoformat(value["t"])
            if timestamp.tzinfo is None:
                raise ValueError
            return timestamp, value["i"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                400,
                "API_CURSOR_INVALID",
                "Invalid cursor",
                "The pagination cursor is invalid for this resource.",
            ) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class QueryAdapter:
    def __init__(self, engine: Engine, cursor_key: bytes) -> None:
        self.sessions = build_session_factory(engine)
        self.cursors = CursorCodec(cursor_key)

    def list_hwpx_builds(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[HwpxBuildView]:
        with self.sessions() as session:
            statement = select(HwpxApplicationBuildRecord)
            if state:
                statement = statement.where(HwpxApplicationBuildRecord.state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                HwpxApplicationBuildRecord.created_at,
                HwpxApplicationBuildRecord.build_id,
                "hwpx-build",
                limit,
                cursor,
            )
            return PageResult(
                tuple(project_hwpx_build(row) for row in rows),
                next_cursor,
                more,
            )

    def list_intakes(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[ContentIntakeSummary]:
        with self.sessions() as session:
            statement = select(ContentIntakeBatchRecord)
            if state:
                statement = statement.where(ContentIntakeBatchRecord.state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                ContentIntakeBatchRecord.created_at,
                ContentIntakeBatchRecord.intake_batch_id,
                "content-intake",
                limit,
                cursor,
            )
            return PageResult(tuple(self._intake(row) for row in rows), next_cursor, more)

    def intake(self, intake_id: str) -> IntakeDetail:
        with self.sessions() as session:
            row = session.get(ContentIntakeBatchRecord, intake_id)
            if row is None:
                self._not_found("CONTENT_INTAKE_NOT_FOUND")
            sources = session.scalars(
                select(ContentIntakeSourceFileRecord)
                .where(ContentIntakeSourceFileRecord.intake_batch_id == intake_id)
                .order_by(ContentIntakeSourceFileRecord.relative_path)
            )
            return IntakeDetail(
                intake=self._intake(row),
                source_files=tuple(self._source(source) for source in sources),
            )

    def intake_events(self, intake_id: str) -> tuple[EventView, ...]:
        with self.sessions() as session:
            rows = session.scalars(
                select(ContentIntakeEventRecord)
                .where(ContentIntakeEventRecord.intake_batch_id == intake_id)
                .order_by(ContentIntakeEventRecord.sequence)
            )
            return tuple(
                self._event(
                    "content_intake",
                    row.intake_batch_id,
                    row.event_id,
                    row.event_type,
                    row.prior_state,
                    row.new_state,
                    row.actor_id,
                    row.created_at,
                )
                for row in rows
            )

    def list_pack_releases(
        self, *, limit: int, cursor: str | None, pack_key: str | None = None
    ) -> PageResult[ContentPackReleaseView]:
        with self.sessions() as session:
            statement = select(ContentPackReleaseRecord, ContentPackRecord).join(
                ContentPackRecord,
                ContentPackRecord.content_pack_id == ContentPackReleaseRecord.content_pack_id,
            )
            if pack_key:
                statement = statement.where(ContentPackRecord.pack_key == pack_key)
            rows, next_cursor, more = self._page_joined(
                session,
                statement,
                ContentPackReleaseRecord.created_at,
                ContentPackReleaseRecord.content_pack_release_id,
                "content-pack-release",
                limit,
                cursor,
            )
            return PageResult(
                tuple(self._pack_release(release, pack) for release, pack in rows),
                next_cursor,
                more,
            )

    def pack_release(self, release_id: str) -> ContentPackReleaseView:
        with self.sessions() as session:
            row = session.execute(
                select(ContentPackReleaseRecord, ContentPackRecord)
                .join(ContentPackRecord)
                .where(ContentPackReleaseRecord.content_pack_release_id == release_id)
            ).one_or_none()
            if row is None:
                self._not_found("CONTENT_PACK_NOT_FOUND")
            return self._pack_release(row[0], row[1])

    def list_activations(
        self, *, active_only: bool = False
    ) -> tuple[ContentPackActivationView, ...]:
        with self.sessions() as session:
            statement = select(ContentPackActivationRecord).order_by(
                ContentPackActivationRecord.activated_at.desc(),
                ContentPackActivationRecord.activation_id,
            )
            if active_only:
                statement = statement.where(ContentPackActivationRecord.active.is_(True))
            return tuple(self._activation(row) for row in session.scalars(statement).all())

    def list_workflows(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[WorkflowView]:
        with self.sessions() as session:
            statement = select(WorkflowInstanceRecord)
            if state:
                statement = statement.where(WorkflowInstanceRecord.state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                WorkflowInstanceRecord.created_at,
                WorkflowInstanceRecord.workflow_id,
                "workflow",
                limit,
                cursor,
            )
            return PageResult(tuple(self._workflow(row) for row in rows), next_cursor, more)

    def workflow(self, workflow_id: str) -> WorkflowView:
        with self.sessions() as session:
            row = session.get(WorkflowInstanceRecord, workflow_id)
            if row is None:
                self._not_found("WORKFLOW_NOT_FOUND")
            return self._workflow(row)

    def workflow_steps(self, workflow_id: str) -> tuple[WorkflowStepView, ...]:
        with self.sessions() as session:
            self._require(session, WorkflowInstanceRecord, workflow_id, "WORKFLOW_NOT_FOUND")
            rows = session.scalars(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == workflow_id)
                .order_by(WorkflowStepRunRecord.attempt, WorkflowStepRunRecord.step_run_id)
            )
            return tuple(self._workflow_step(row) for row in rows)

    def workflow_events(self, workflow_id: str) -> tuple[EventView, ...]:
        with self.sessions() as session:
            self._require(session, WorkflowInstanceRecord, workflow_id, "WORKFLOW_NOT_FOUND")
            rows = session.scalars(
                select(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == workflow_id)
                .order_by(WorkflowEventRecord.sequence)
            )
            return tuple(
                self._event(
                    "workflow",
                    row.workflow_id,
                    row.event_id,
                    row.event_type,
                    row.prior_state,
                    row.new_state,
                    row.actor_id,
                    row.created_at,
                )
                for row in rows
            )

    def list_items(
        self, *, limit: int, cursor: str | None, state: str | None = None
    ) -> PageResult[ItemView]:
        with self.sessions() as session:
            statement = select(ItemRecord)
            if state:
                statement = statement.where(ItemRecord.lifecycle_state == state)
            rows, next_cursor, more = self._page(
                session,
                statement,
                ItemRecord.created_at,
                ItemRecord.item_id,
                "item",
                limit,
                cursor,
            )
            return PageResult(tuple(self._item(row) for row in rows), next_cursor, more)

    def item(self, item_id: str) -> ItemView:
        with self.sessions() as session:
            row = self._require(session, ItemRecord, item_id, "ITEM_NOT_FOUND")
            return self._item(row)

    def item_revisions(self, item_id: str) -> tuple[ItemRevisionView, ...]:
        with self.sessions() as session:
            self._require(session, ItemRecord, item_id, "ITEM_NOT_FOUND")
            rows = session.scalars(
                select(ItemRevisionRecord)
                .where(ItemRevisionRecord.item_id == item_id)
                .order_by(ItemRevisionRecord.revision_number)
            )
            return tuple(self._revision(row) for row in rows)

    def revision(self, revision_id: str) -> ItemRevisionView:
        with self.sessions() as session:
            row = self._require(session, ItemRevisionRecord, revision_id, "ITEM_REVISION_NOT_FOUND")
            return self._revision(row)

    def components(self, revision_id: str) -> tuple[ItemComponentView, ...]:
        with self.sessions() as session:
            self._require(session, ItemRevisionRecord, revision_id, "ITEM_REVISION_NOT_FOUND")
            rows = session.scalars(
                select(ItemComponentRecord)
                .where(ItemComponentRecord.item_revision_id == revision_id)
                .order_by(ItemComponentRecord.component_type, ItemComponentRecord.ordinal)
            )
            return tuple(self._component(row) for row in rows)

    def relationships(self, item_id: str) -> tuple[ItemRelationshipView, ...]:
        with self.sessions() as session:
            self._require(session, ItemRecord, item_id, "ITEM_NOT_FOUND")
            rows = session.scalars(
                select(ItemRelationshipRecord)
                .where(
                    or_(
                        ItemRelationshipRecord.source_item_id == item_id,
                        ItemRelationshipRecord.target_item_id == item_id,
                    )
                )
                .order_by(ItemRelationshipRecord.created_at)
            )
            return tuple(
                ItemRelationshipView.model_validate(row, from_attributes=True) for row in rows
            )

    def list_deliverables(self) -> tuple[DeliverableView, ...]:
        with self.sessions() as session:
            rows = session.execute(
                select(DeliverableRecord, DeliverableRevisionRecord)
                .outerjoin(
                    DeliverableRevisionRecord,
                    and_(
                        DeliverableRevisionRecord.deliverable_id
                        == DeliverableRecord.deliverable_id,
                        DeliverableRevisionRecord.revision_number == 1,
                    ),
                )
                .order_by(DeliverableRecord.created_at.desc())
                .limit(200)
            )
            return tuple(self._deliverable(row, revision) for row, revision in rows)

    def deliverable(self, deliverable_id: str) -> DeliverableView:
        with self.sessions() as session:
            row = session.execute(
                select(DeliverableRecord, DeliverableRevisionRecord)
                .outerjoin(
                    DeliverableRevisionRecord,
                    DeliverableRevisionRecord.deliverable_id == DeliverableRecord.deliverable_id,
                )
                .where(DeliverableRecord.deliverable_id == deliverable_id)
                .order_by(DeliverableRevisionRecord.revision_number.desc())
                .limit(1)
            ).one_or_none()
            if row is None:
                self._not_found("DELIVERABLE_NOT_FOUND")
            return self._deliverable(row[0], row[1])

    def list_usage_plans(self) -> tuple[UsagePlanView, ...]:
        with self.sessions() as session:
            return tuple(
                self._usage_plan(row)
                for row in session.scalars(
                    select(UsagePlanRecord).order_by(UsagePlanRecord.created_at.desc()).limit(200)
                )
            )

    def usage_plan(self, plan_id: str) -> UsagePlanView:
        with self.sessions() as session:
            return self._usage_plan(
                self._require(session, UsagePlanRecord, plan_id, "USAGE_PLAN_NOT_FOUND")
            )

    def list_usage_records(self, *, item_id: str | None = None) -> tuple[UsageRecordView, ...]:
        with self.sessions() as session:
            statement = select(UsageRecord).order_by(UsageRecord.recorded_at.desc()).limit(200)
            if item_id:
                statement = statement.where(UsageRecord.item_id == item_id)
            return tuple(self._usage_record(row) for row in session.scalars(statement))

    def usage_record(self, record_id: str) -> UsageRecordView:
        with self.sessions() as session:
            return self._usage_record(
                self._require(session, UsageRecord, record_id, "USAGE_RECORD_NOT_FOUND")
            )

    def events(self, *, limit: int) -> tuple[EventView, ...]:
        projected: list[tuple[int, EventView]] = []
        with self.sessions() as session:
            sources: tuple[tuple[int, str, Any, Any, Any], ...] = (
                (0, "workflow", WorkflowEventRecord, WorkflowEventRecord.workflow_id, None),
                (1, "item", ItemEventRecord, ItemEventRecord.item_id, None),
                (
                    2,
                    "content_intake",
                    ContentIntakeEventRecord,
                    ContentIntakeEventRecord.intake_batch_id,
                    None,
                ),
                (
                    3,
                    "content_pack",
                    ContentPackEventRecord,
                    ContentPackEventRecord.content_pack_release_id,
                    None,
                ),
                (4, "operator", OperatorEventRecord, OperatorEventRecord.operator_id, None),
                (
                    5,
                    "deliverable",
                    DeliverableEventRecord,
                    DeliverableEventRecord.deliverable_id,
                    None,
                ),
            )
            for priority, aggregate_type, model, aggregate_column, _ in sources:
                rows = session.scalars(select(model).order_by(model.created_at.desc()).limit(limit))
                for row in rows:
                    projected.append(
                        (
                            priority,
                            self._event(
                                aggregate_type,
                                getattr(row, aggregate_column.key),
                                getattr(row, "event_id", getattr(row, "operator_event_id", "")),
                                row.event_type,
                                getattr(row, "prior_state", None),
                                getattr(row, "new_state", None),
                                row.actor_id,
                                row.created_at,
                            ),
                        )
                    )
        projected.sort(key=lambda pair: (pair[1].created_at, pair[0], pair[1].event_id))
        return tuple(view for _, view in projected[-limit:])

    def _page(
        self,
        session: Session,
        statement: Select[tuple[Any]],
        time_column: Any,
        id_column: Any,
        resource: str,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Any], str | None, bool]:
        if cursor:
            timestamp, resource_id = self.cursors.decode(cursor, resource)
            statement = statement.where(
                or_(
                    time_column < timestamp, and_(time_column == timestamp, id_column < resource_id)
                )
            )
        rows = list(
            session.scalars(
                statement.order_by(time_column.desc(), id_column.desc()).limit(limit + 1)
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self.cursors.encode(
                resource, getattr(rows[-1], time_column.key), getattr(rows[-1], id_column.key)
            )
            if more and rows
            else None
        )
        return rows, next_cursor, more

    def _page_joined(
        self,
        session: Session,
        statement: Select[Any],
        time_column: Any,
        id_column: Any,
        resource: str,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Any], str | None, bool]:
        if cursor:
            timestamp, resource_id = self.cursors.decode(cursor, resource)
            statement = statement.where(
                or_(
                    time_column < timestamp, and_(time_column == timestamp, id_column < resource_id)
                )
            )
        rows = list(
            session.execute(
                statement.order_by(time_column.desc(), id_column.desc()).limit(limit + 1)
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self.cursors.encode(
                resource, rows[-1][0].created_at, rows[-1][0].content_pack_release_id
            )
            if more and rows
            else None
        )
        return rows, next_cursor, more

    @staticmethod
    def _pointer(
        artifact_id: str,
        revision_id: str,
        sha256: str,
        schema_ref: str,
        media_type: str,
        artifact_member: str | None = None,
    ) -> ArtifactPointer:
        return ArtifactPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            artifact_member=artifact_member,
            sha256=sha256,
            schema_ref=schema_ref,
            media_type=media_type,
            logical_uri=f"nas://artifacts/{artifact_id}/{revision_id}",
        )

    def _intake(self, row: ContentIntakeBatchRecord) -> ContentIntakeSummary:
        pointer = None
        if (
            row.source_manifest_artifact_id
            and row.source_manifest_artifact_revision_id
            and row.source_manifest_sha256
        ):
            pointer = self._pointer(
                row.source_manifest_artifact_id,
                row.source_manifest_artifact_revision_id,
                row.source_manifest_sha256,
                "urn:eom:schema:content-intake-manifest:1.0",
                "application/json",
            )
        return ContentIntakeSummary(
            intake_batch_id=row.intake_batch_id,
            batch_name=row.batch_name,
            state=row.state,
            purpose=row.purpose,
            received_by=row.received_by,
            resource_version=row.lock_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            source_manifest=pointer,
        )

    def _source(self, row: ContentIntakeSourceFileRecord) -> SourceFileView:
        return SourceFileView(
            source_file_id=row.source_file_id,
            filename=row.original_filename,
            media_type=row.media_type,
            size=row.size_bytes,
            sha256=row.sha256,
            artifact=self._pointer(
                row.artifact_id,
                row.artifact_revision_id,
                row.sha256,
                "urn:eom:schema:content-intake-source:1.0",
                row.media_type,
                row.relative_path,
            ),
            declared_role=row.declared_role,
        )

    def _pack_release(
        self, row: ContentPackReleaseRecord, pack: ContentPackRecord
    ) -> ContentPackReleaseView:
        return ContentPackReleaseView(
            content_pack_release_id=row.content_pack_release_id,
            content_pack_id=row.content_pack_id,
            pack_key=pack.pack_key,
            version=row.version,
            schema_version=row.schema_version,
            state=row.state,
            bundle=self._pointer(
                row.bundle_artifact_id,
                row.bundle_artifact_revision_id,
                row.bundle_sha256,
                "urn:eom:schema:content-pack-manifest:" + row.schema_version,
                "application/zip",
            ),
            resource_version=row.lock_version,
            created_at=row.created_at,
            released_at=row.released_at,
        )

    @staticmethod
    def _activation(row: ContentPackActivationRecord) -> ContentPackActivationView:
        return ContentPackActivationView(
            activation_id=row.activation_id,
            environment=row.environment,
            pack_key=row.pack_key,
            content_pack_release_id=row.content_pack_release_id,
            active=row.active,
            activated_by=row.activated_by,
            activated_at=row.activated_at,
            resource_version=row.lock_version,
        )

    @staticmethod
    def _workflow(row: WorkflowInstanceRecord) -> WorkflowView:
        return WorkflowView(
            workflow_id=row.workflow_id,
            definition_key=row.definition_key,
            definition_version=row.definition_version,
            state=row.state,
            stage=row.stage,
            current_step_key=row.current_step_key,
            resource_version=row.lock_version,
            rework_cycle_count=row.rework_cycle_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
            failure_code=row.failure_code,
        )

    @staticmethod
    def _workflow_step(row: WorkflowStepRunRecord) -> WorkflowStepView:
        return WorkflowStepView.model_validate(row, from_attributes=True)

    @staticmethod
    def _item(row: ItemRecord) -> ItemView:
        return ItemView(
            item_id=row.item_id,
            human_reference_code=row.human_reference_code,
            lifecycle_state=row.lifecycle_state,
            current_revision_id=row.current_revision_id,
            resource_version=row.lock_version,
            created_at=row.created_at,
        )

    def _revision(self, row: ItemRevisionRecord) -> ItemRevisionView:
        return ItemRevisionView(
            item_revision_id=row.item_revision_id,
            item_id=row.item_id,
            revision_number=row.revision_number,
            revision_state=row.revision_state,
            content_pack_release_id=row.content_pack_release_id,
            workflow_id=row.workflow_id,
            item_type_key=row.item_type_key,
            manifest=self._pointer(
                row.manifest_artifact_id,
                row.manifest_artifact_revision_id,
                row.manifest_sha256,
                "urn:eom:schema:item-manifest:1.0",
                "application/json",
            ),
            resource_version=row.lock_version,
            created_at=row.created_at,
        )

    def _component(self, row: ItemComponentRecord) -> ItemComponentView:
        return ItemComponentView(
            item_component_id=row.item_component_id,
            item_revision_id=row.item_revision_id,
            component_type=row.component_type,
            ordinal=row.ordinal,
            logical_name=row.logical_name,
            required=row.required,
            artifact=self._pointer(
                row.artifact_id,
                row.artifact_revision_id,
                row.sha256,
                row.schema_ref,
                row.media_type,
            ),
        )

    @staticmethod
    def _deliverable(
        row: DeliverableRecord, revision: DeliverableRevisionRecord | None
    ) -> DeliverableView:
        return DeliverableView(
            deliverable_id=row.deliverable_id,
            deliverable_key=row.deliverable_key,
            deliverable_type=row.deliverable_type,
            title=row.title,
            edition=row.edition,
            lifecycle_state=row.lifecycle_state,
            deliverable_revision_id=revision.deliverable_revision_id if revision else None,
            revision_number=revision.revision_number if revision else None,
            created_at=row.created_at,
        )

    @staticmethod
    def _usage_plan(row: UsagePlanRecord) -> UsagePlanView:
        return UsagePlanView(
            usage_plan_id=row.usage_plan_id,
            item_id=row.item_id,
            preferred_item_revision_id=row.preferred_item_revision_id,
            deliverable_id=row.deliverable_id,
            deliverable_revision_id=row.deliverable_revision_id,
            planned_section=row.planned_section,
            planned_sequence=row.planned_sequence,
            planned_points=row.planned_points,
            planned_role=row.planned_role,
            status=row.status,
            resource_version=row.lock_version,
            created_at=row.created_at,
        )

    @staticmethod
    def _usage_record(row: UsageRecord) -> UsageRecordView:
        return UsageRecordView.model_validate(row, from_attributes=True)

    @staticmethod
    def _event(
        aggregate_type: str,
        aggregate_id: str,
        event_id: int | str,
        event_type: str,
        prior_state: str | None,
        new_state: str | None,
        actor_id: str,
        created_at: datetime,
    ) -> EventView:
        return EventView(
            event_id=f"{aggregate_type}:{event_id}",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            prior_state=prior_state,
            new_state=new_state,
            actor_id=actor_id,
            created_at=created_at,
            summary=event_type.replace("_", " ").title(),
        )

    @staticmethod
    def _require(session: Session, model: Any, identifier: str, code: str) -> Any:
        row = session.get(model, identifier)
        if row is None:
            QueryAdapter._not_found(code)
        return row

    @staticmethod
    def _not_found(code: str) -> Never:
        raise ApiError(404, code, "Resource not found", "The requested resource does not exist.")
