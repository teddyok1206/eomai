"""Reversible content shelving over existing lifecycle, event and receipt owners."""

from __future__ import annotations

import re

from eom_catalog_contracts.content_lifecycle import (
    ChangeContentLifecycle,
    ContentLifecycleAction,
    ContentLifecycleEntry,
    ContentLifecycleEvent,
    ContentLifecycleList,
    ContentLifecycleMutation,
    ContentLifecycleResult,
    ContentLifecycleTarget,
    ContentLifecycleView,
    EditionLifecycleTarget,
    LifecycleTarget,
    ListContentLifecycle,
    ReadContentLifecycle,
    parse_content_lifecycle_action,
    parse_content_lifecycle_result,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import (
    ContentPlanningError,
    authorize_content_planning,
)
from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentPlanningCommandReceiptRecord,
)
from eom_catalog_service.models import (
    DeliverableEventRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
)

_KIND = "CHANGE_LIFECYCLE"
_ACTIVE_PRODUCT_STATES = {"PLANNED", "IN_PRODUCTION", "RELEASED"}


def _sequence(session: Session, product_id: str) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.max(DeliverableEventRecord.sequence), 0)).where(
                DeliverableEventRecord.deliverable_id == product_id
            )
        )
        or 0
    )


def _entry(
    session: Session, product: DeliverableRecord, edition: ContentEditionRecord | None
) -> ContentLifecycleEntry:
    if edition is None:
        return ContentLifecycleEntry(
            target=ContentLifecycleTarget(target_kind="CONTENT", target_id=product.deliverable_id),
            deliverable_id=product.deliverable_id,
            title=product.title,
            lifecycle_state="ARCHIVED" if product.lifecycle_state == "ARCHIVED" else "ACTIVE",
            version=_sequence(session, product.deliverable_id),
            current_revision_id=None,
            parent_archived=False,
        )
    title = session.scalar(
        select(DeliverableRevisionRecord.metadata_json["edition_label"].as_string()).where(
            DeliverableRevisionRecord.deliverable_revision_id == edition.current_revision_id,
            DeliverableRevisionRecord.deliverable_id == product.deliverable_id,
        )
    )
    if not title or edition.current_revision_id is None:
        raise ContentPlanningError("CONTENT_REVISION_POINTER_INVALID")
    return ContentLifecycleEntry(
        target=EditionLifecycleTarget(target_kind="EDITION", target_id=edition.edition_id),
        deliverable_id=product.deliverable_id,
        title=title,
        lifecycle_state="ARCHIVED" if edition.lifecycle_state == "ARCHIVED" else "ACTIVE",
        version=edition.lock_version,
        current_revision_id=edition.current_revision_id,
        parent_archived=product.lifecycle_state == "ARCHIVED",
    )


def _load(
    session: Session, target: LifecycleTarget, *, lock: bool
) -> tuple[DeliverableRecord, ContentEditionRecord | None]:
    product_id: str | None = target.target_id
    if isinstance(target, EditionLifecycleTarget):
        product_id = session.scalar(
            select(ContentEditionRecord.deliverable_id).where(
                ContentEditionRecord.edition_id == target.target_id
            )
        )
    statement = select(DeliverableRecord).where(
        DeliverableRecord.deliverable_id == product_id,
        DeliverableRecord.lifecycle_state != "CANCELLED",
        select(ContentEditionRecord.edition_id)
        .where(ContentEditionRecord.deliverable_id == DeliverableRecord.deliverable_id)
        .exists(),
    )
    if lock:
        statement = statement.with_for_update()
    product = session.scalar(statement)
    if product is None:
        raise ContentPlanningError("CONTENT_LIFECYCLE_NOT_FOUND")
    if isinstance(target, ContentLifecycleTarget):
        return product, None
    edition_statement = select(ContentEditionRecord).where(
        ContentEditionRecord.edition_id == target.target_id,
        ContentEditionRecord.deliverable_id == product.deliverable_id,
    )
    if lock:
        edition_statement = edition_statement.with_for_update()
    edition = session.scalar(edition_statement)
    if edition is None:
        raise ContentPlanningError("CONTENT_LIFECYCLE_NOT_FOUND")
    return product, edition


class ContentLifecycleService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def execute(
        self,
        action: ContentLifecycleAction,
        *,
        actor: ActorContext,
        idempotency_key: str | None = None,
    ) -> ContentLifecycleResult:
        action = parse_content_lifecycle_action(action.model_dump(mode="json"))
        if isinstance(action, ChangeContentLifecycle):
            if idempotency_key is None or re.fullmatch(r"[!-~]{16,128}", idempotency_key) is None:
                raise ContentPlanningError("CONTENT_IDEMPOTENCY_KEY_INVALID")
            result: ContentLifecycleResult = self._change(action, actor, idempotency_key)
        else:
            if idempotency_key is not None:
                raise ContentPlanningError("CONTENT_LIFECYCLE_REQUEST_INVALID")
            with self.sessions() as session:
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                authorize_content_planning(session, actor, PermissionKey.DELIVERABLE_READ)
                result = self._read(session, action)
        return parse_content_lifecycle_result(result.model_dump(mode="json"))

    def _read(
        self, session: Session, action: ReadContentLifecycle | ListContentLifecycle
    ) -> ContentLifecycleView | ContentLifecycleList:
        if isinstance(action, ListContentLifecycle):
            return self._list(session, action)
        product, edition = _load(session, action.target, lock=False)
        events = session.scalars(
            select(DeliverableEventRecord)
            .where(
                DeliverableEventRecord.deliverable_id == product.deliverable_id,
                DeliverableEventRecord.event_type == "CONTENT_LIFECYCLE_CHANGED",
                DeliverableEventRecord.payload["target_id"].as_string() == action.target.target_id,
            )
            .order_by(DeliverableEventRecord.sequence.desc())
            .limit(50)
        ).all()
        return ContentLifecycleView(
            entry=_entry(session, product, edition),
            events=tuple(
                ContentLifecycleEvent(
                    sequence=row.sequence,
                    prior_state=row.prior_state or "",
                    new_state=row.new_state,
                    actor_id=row.actor_id,
                    created_at=row.created_at,
                    reason=row.payload["reason"],
                )
                for row in events
            ),
        )

    @staticmethod
    def _list(session: Session, action: ListContentLifecycle) -> ContentLifecycleList:
        product, edition, revision = (
            DeliverableRecord,
            ContentEditionRecord,
            DeliverableRevisionRecord,
        )
        if action.target_kind == "CONTENT":
            version = (
                select(func.coalesce(func.max(DeliverableEventRecord.sequence), 0))
                .where(DeliverableEventRecord.deliverable_id == product.deliverable_id)
                .correlate(product)
                .scalar_subquery()
            )
            statement = select(product, version).where(
                product.lifecycle_state != "CANCELLED",
                select(edition.edition_id)
                .where(edition.deliverable_id == product.deliverable_id)
                .exists(),
            )
            if action.lifecycle_state != "ALL":
                statement = statement.where(
                    product.lifecycle_state == "ARCHIVED"
                    if action.lifecycle_state == "ARCHIVED"
                    else product.lifecycle_state.in_(_ACTIVE_PRODUCT_STATES)
                )
            if action.after_id:
                statement = statement.where(product.deliverable_id > action.after_id)
            values = session.execute(
                statement.order_by(product.deliverable_id).limit(action.limit + 1)
            ).all()
            entries = tuple(
                ContentLifecycleEntry(
                    target=ContentLifecycleTarget(
                        target_kind="CONTENT", target_id=row.deliverable_id
                    ),
                    deliverable_id=row.deliverable_id,
                    title=row.title,
                    lifecycle_state="ARCHIVED" if row.lifecycle_state == "ARCHIVED" else "ACTIVE",
                    version=number,
                    current_revision_id=None,
                    parent_archived=False,
                )
                for row, number in values
            )
        else:
            statement = (
                select(
                    edition,
                    product.lifecycle_state,
                    revision.metadata_json["edition_label"].as_string(),
                )
                .join(product, product.deliverable_id == edition.deliverable_id)
                .join(revision, revision.deliverable_revision_id == edition.current_revision_id)
                .where(
                    edition.deliverable_id == action.deliverable_id,
                    product.lifecycle_state != "CANCELLED",
                )
            )
            if action.lifecycle_state != "ALL":
                statement = statement.where(edition.lifecycle_state == action.lifecycle_state)
            if action.after_id:
                statement = statement.where(edition.edition_id > action.after_id)
            values = session.execute(
                statement.order_by(edition.edition_id).limit(action.limit + 1)
            ).all()
            entries = tuple(
                ContentLifecycleEntry(
                    target=EditionLifecycleTarget(target_kind="EDITION", target_id=row.edition_id),
                    deliverable_id=row.deliverable_id,
                    title=title,
                    lifecycle_state="ARCHIVED" if row.lifecycle_state == "ARCHIVED" else "ACTIVE",
                    version=row.lock_version,
                    current_revision_id=row.current_revision_id,
                    parent_archived=parent == "ARCHIVED",
                )
                for row, parent, title in values
            )
        return ContentLifecycleList(
            rows=entries[: action.limit],
            next_id=entries[action.limit - 1].target.target_id
            if len(entries) > action.limit
            else None,
        )

    @staticmethod
    def _replay(
        session: Session, actor: ActorContext, key: str, digest: str
    ) -> ContentLifecycleMutation | None:
        receipt = session.get(ContentPlanningCommandReceiptRecord, (actor.actor_id, _KIND, key))
        if receipt is None:
            return None
        if receipt.request_sha256 != digest:
            raise ContentPlanningError("CONTENT_IDEMPOTENCY_CONFLICT")
        result = ContentLifecycleMutation.model_validate(receipt.result_pointer)
        _load(session, result.entry.target, lock=False)
        return result.model_copy(update={"replayed": True})

    def _change(
        self, command: ChangeContentLifecycle, actor: ActorContext, key: str
    ) -> ContentLifecycleMutation:
        digest = content_sha256(command.model_dump(mode="json"))
        try:
            return self._change_transaction(command, actor, key, digest)
        except IntegrityError as exc:
            with self.sessions() as session:
                authorized = authorize_content_planning(
                    session, actor, PermissionKey.DELIVERABLE_UPDATE
                )
                if replay := self._replay(session, authorized, key, digest):
                    return replay
            raise ContentPlanningError("CONTENT_LIFECYCLE_PERSISTENCE_CONFLICT") from exc

    def _change_transaction(
        self, command: ChangeContentLifecycle, actor: ActorContext, key: str, digest: str
    ) -> ContentLifecycleMutation:
        with transaction(self.sessions) as session:
            authorized = authorize_content_planning(
                session, actor, PermissionKey.DELIVERABLE_UPDATE
            )
            if replay := self._replay(session, authorized, key, digest):
                return replay
            product, edition = _load(session, command.target, lock=True)
            if replay := self._replay(session, authorized, key, digest):
                return replay
            before = _entry(session, product, edition)
            if (before.lifecycle_state, before.version) != (
                command.expected_state,
                command.expected_version,
            ):
                raise ContentPlanningError("CONTENT_LIFECYCLE_STALE")
            if edition is not None and product.lifecycle_state == "ARCHIVED":
                raise ContentPlanningError("CONTENT_PARENT_ARCHIVED")
            changed = before.lifecycle_state != command.desired_state
            if changed:
                target = product if edition is None else edition
                prior = target.lifecycle_state
                new_state = "ARCHIVED"
                if command.desired_state == "ACTIVE":
                    new_state = (
                        "ACTIVE" if edition is not None else self._restore_product(session, product)
                    )
                target.lifecycle_state = new_state
                if edition is not None:
                    edition.lock_version += 1
                session.add(
                    DeliverableEventRecord(
                        deliverable_id=product.deliverable_id,
                        deliverable_revision_id=None
                        if edition is None
                        else edition.current_revision_id,
                        sequence=_sequence(session, product.deliverable_id) + 1,
                        event_type="CONTENT_LIFECYCLE_CHANGED",
                        prior_state=prior,
                        new_state=new_state,
                        actor_id=authorized.actor_id,
                        payload={
                            "target_id": command.target.target_id,
                            "target_kind": command.target.target_kind,
                            "reason": command.reason,
                        },
                    )
                )
                session.flush()
            result = ContentLifecycleMutation(
                entry=_entry(session, product, edition),
                replayed=False,
                disposition="CHANGED" if changed else "NO_CHANGE",
            )
            session.add(
                ContentPlanningCommandReceiptRecord(
                    actor_id=authorized.actor_id,
                    command_kind=_KIND,
                    idempotency_key=key,
                    request_sha256=digest,
                    result_pointer=result.model_dump(mode="json"),
                )
            )
            session.flush()
            return result

    @staticmethod
    def _restore_product(session: Session, product: DeliverableRecord) -> str:
        last = session.scalar(
            select(DeliverableEventRecord)
            .where(
                DeliverableEventRecord.deliverable_id == product.deliverable_id,
                DeliverableEventRecord.event_type == "CONTENT_LIFECYCLE_CHANGED",
                DeliverableEventRecord.payload["target_id"].as_string() == product.deliverable_id,
            )
            .order_by(DeliverableEventRecord.sequence.desc())
            .limit(1)
        )
        if (
            last is None
            or last.new_state != "ARCHIVED"
            or last.prior_state not in _ACTIVE_PRODUCT_STATES
        ):
            raise ContentPlanningError("CONTENT_RESTORE_STATE_UNRECORDED")
        assert last.prior_state is not None
        return last.prior_state
