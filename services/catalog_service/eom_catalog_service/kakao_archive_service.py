"""Owner-private binding bootstrap use cases, without browser or worker side effects."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from eom_catalog_contracts.kakao_archive_binding import (
    KakaoBindingCommand,
    KakaoBindingCreate,
    KakaoBindingMutation,
    KakaoBindingPage,
    KakaoBindingRetire,
    KakaoBindingUpdatePolicy,
    KakaoCollectionPolicy,
    KakaoCollectionPolicyRevision,
    KakaoSourceBinding,
    collection_policy_sha256,
)
from eom_operator_identity.contracts import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
)
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256 as _request_hash,
)
from eom_catalog_service.kakao_archive_commands import (
    lock_kakao_intent as _lock_intent,
)
from eom_catalog_service.kakao_archive_commands import (
    validate_kakao_idempotency_key as _idempotency_key,
)
from eom_catalog_service.kakao_archive_models import (
    KakaoBindingCommandRecord,
    KakaoChannelBindingRecord,
    KakaoCollectionPolicyRevisionRecord,
)


def _binding_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"kakaobinding_[0-9a-f]{32}", value) is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
    return value


def _policy_view(row: KakaoCollectionPolicyRevisionRecord) -> KakaoCollectionPolicyRevision:
    try:
        return KakaoCollectionPolicyRevision(
            source_binding_id=row.source_binding_id,
            policy_revision_id=row.policy_revision_id,
            previous_revision_id=row.previous_revision_id,
            revision_number=row.revision_number,
            sha256=row.sha256,
            policy=KakaoCollectionPolicy(
                interval_minutes=row.interval_minutes,
                source_timezone=cast(Literal["unknown", "Asia/Seoul"], row.source_timezone),
            ),
            created_at=row.created_at,
        )
    except ValueError:
        raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_POLICY_INVALID") from None


def _view(
    binding: KakaoChannelBindingRecord,
    policy: KakaoCollectionPolicyRevisionRecord,
    receipt: KakaoBindingCommandRecord | None = None,
) -> KakaoSourceBinding:
    try:
        return KakaoSourceBinding(
            source_binding_id=binding.source_binding_id,
            display_name=binding.display_name,
            state=cast(
                Literal["DRAFT", "RETIRED"], receipt.result_state if receipt else binding.state
            ),
            resource_version=receipt.result_version if receipt else binding.resource_version,
            policy_revision=_policy_view(policy),
            created_at=binding.created_at,
            updated_at=receipt.completed_at if receipt else binding.updated_at,
        )
    except ValueError:
        raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_BINDING_INVALID") from None


class KakaoArchiveService:
    """Binding settings only. Reads use indexed owner+ID joins, never message scans."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = build_session_factory(engine)

    @staticmethod
    def _authorize(session: Session, actor: ActorContext, *, mutate: bool) -> str:
        return authorize_kakao_actor(
            session,
            actor,
            PermissionKey.KAKAO_ARCHIVE_COLLECT if mutate else PermissionKey.KAKAO_ARCHIVE_READ,
            now=datetime.now(UTC),
            admin_only=mutate,
        )

    @staticmethod
    def _owned(
        session: Session, owner: str, binding_id: str, *, lock: bool = False
    ) -> KakaoChannelBindingRecord:
        statement = select(KakaoChannelBindingRecord).where(
            KakaoChannelBindingRecord.source_binding_id == binding_id,
            KakaoChannelBindingRecord.owner_operator_id == owner,
        )
        if lock:
            statement = statement.with_for_update()
        binding = session.scalar(statement)
        if binding is None:
            # Deliberately identical for absent and another owner's private source.
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return binding

    @staticmethod
    def _policy(
        session: Session, binding_id: str, revision_id: str
    ) -> KakaoCollectionPolicyRevisionRecord:
        row = session.scalar(
            select(KakaoCollectionPolicyRevisionRecord).where(
                KakaoCollectionPolicyRevisionRecord.source_binding_id == binding_id,
                KakaoCollectionPolicyRevisionRecord.policy_revision_id == revision_id,
            )
        )
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_POLICY_REFERENCE_INVALID")
        return row

    @staticmethod
    def _replay(
        session: Session, owner: str, scope: str, key: str, request_hash: str
    ) -> KakaoBindingMutation | None:
        receipt = session.scalar(
            select(KakaoBindingCommandRecord).where(
                KakaoBindingCommandRecord.owner_operator_id == owner,
                KakaoBindingCommandRecord.idempotency_scope == scope,
                KakaoBindingCommandRecord.idempotency_key == key,
            )
        )
        if receipt is None:
            return None
        if receipt.request_sha256 != request_hash:
            raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
        binding = KakaoArchiveService._owned(session, owner, receipt.source_binding_id)
        policy = KakaoArchiveService._policy(
            session, binding.source_binding_id, receipt.result_policy_revision_id
        )
        return KakaoBindingMutation(binding=_view(binding, policy, receipt), replayed=True)

    @staticmethod
    def _new_policy(
        session: Session,
        binding_id: str,
        owner: str,
        policy: KakaoCollectionPolicy,
        now: datetime,
        previous: KakaoCollectionPolicyRevisionRecord | None = None,
    ) -> KakaoCollectionPolicyRevisionRecord:
        row = KakaoCollectionPolicyRevisionRecord(
            policy_revision_id="kakaopolicyrev_" + uuid4().hex,
            source_binding_id=binding_id,
            previous_revision_id=previous.policy_revision_id if previous else None,
            revision_number=previous.revision_number + 1 if previous else 1,
            sha256=collection_policy_sha256(policy),
            interval_minutes=policy.interval_minutes,
            source_timezone=policy.source_timezone,
            created_by=owner,
            created_at=now,
        )
        session.add(row)
        return row

    @staticmethod
    def _record(
        session: Session,
        binding: KakaoChannelBindingRecord,
        actor: ActorContext,
        scope: str,
        key: str,
        request_hash: str,
        action: str,
    ) -> None:
        session.add(
            KakaoBindingCommandRecord(
                command_id="kakaocommand_" + uuid4().hex,
                source_binding_id=binding.source_binding_id,
                owner_operator_id=binding.owner_operator_id,
                idempotency_scope=scope,
                idempotency_key=key,
                request_sha256=request_hash,
                request_id=actor.request_id,
                action=action,
                result_state=binding.state,
                result_version=binding.resource_version,
                result_policy_revision_id=binding.current_policy_revision_id,
                completed_at=binding.updated_at,
            )
        )

    def create_binding(
        self, actor: ActorContext, command: KakaoBindingCreate, *, idempotency_key: str
    ) -> KakaoBindingMutation:
        try:
            command = KakaoBindingCreate.model_validate(command.model_dump(mode="json"))
        except (AttributeError, ValueError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID") from None
        key = _idempotency_key(idempotency_key)
        scope = "source-bindings"
        request_hash = _request_hash(command)
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=True)
            _lock_intent(session, owner, scope, key)
            self._authorize(session, actor, mutate=True)
            replay = self._replay(session, owner, scope, key, request_hash)
            if replay is not None:
                return replay
            now = datetime.now(UTC)
            binding_id = "kakaobinding_" + uuid4().hex
            policy = self._new_policy(session, binding_id, owner, command.policy, now)
            binding = KakaoChannelBindingRecord(
                source_binding_id=binding_id,
                owner_operator_id=owner,
                display_name=command.display_name,
                state="DRAFT",
                resource_version=1,
                current_policy_revision_id=policy.policy_revision_id,
                created_at=now,
                updated_at=now,
            )
            session.add(binding)
            # The binding->current policy FK is deferred; the reverse FK is immediate.
            session.flush([binding])
            session.flush([policy])
            self._record(session, binding, actor, scope, key, request_hash, command.action)
            return KakaoBindingMutation(binding=_view(binding, policy), replayed=False)

    def command_binding(
        self,
        actor: ActorContext,
        source_binding_id: str,
        command: KakaoBindingCommand,
        *,
        idempotency_key: str,
    ) -> KakaoBindingMutation:
        try:
            if isinstance(command, KakaoBindingUpdatePolicy):
                command = KakaoBindingUpdatePolicy.model_validate(command.model_dump(mode="json"))
            elif isinstance(command, KakaoBindingRetire):
                command = KakaoBindingRetire.model_validate(command.model_dump(mode="json"))
            else:
                raise ValueError("unsupported binding command")
        except ValueError:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID") from None
        binding_id = _binding_id(source_binding_id)
        key = _idempotency_key(idempotency_key)
        scope = "source-bindings/" + binding_id + "/commands"
        request_hash = _request_hash(command)
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=True)
            _lock_intent(session, owner, scope, key)
            binding = self._owned(session, owner, binding_id, lock=True)
            self._authorize(session, actor, mutate=True)
            replay = self._replay(session, owner, scope, key, request_hash)
            if replay is not None:
                return replay
            if (
                binding.resource_version != command.expected_resource_version
                or binding.current_policy_revision_id != command.parent_policy_revision_id
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            if binding.state != "DRAFT":
                raise KakaoArchiveError("KAKAO_ARCHIVE_BINDING_RETIRED")
            if binding.resource_version == 2147483647:
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            policy = self._policy(session, binding_id, binding.current_policy_revision_id)
            _policy_view(policy)  # An invalid stored hash never becomes a valid successor.
            now = datetime.now(UTC)
            if isinstance(command, KakaoBindingUpdatePolicy):
                policy = self._new_policy(session, binding_id, owner, command.policy, now, policy)
                session.flush([policy])
                binding.current_policy_revision_id = policy.policy_revision_id
            else:
                binding.state = "RETIRED"
            binding.resource_version += 1
            binding.updated_at = now
            self._record(session, binding, actor, scope, key, request_hash, command.action)
            return KakaoBindingMutation(binding=_view(binding, policy), replayed=False)

    def get_binding(self, actor: ActorContext, source_binding_id: str) -> KakaoSourceBinding:
        binding_id = _binding_id(source_binding_id)
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=False)
            binding = self._owned(session, owner, binding_id)
            return _view(
                binding, self._policy(session, binding_id, binding.current_policy_revision_id)
            )

    def list_bindings(
        self, actor: ActorContext, *, limit: int = 50, cursor: str | None = None
    ) -> KakaoBindingPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        if cursor is not None:
            _binding_id(cursor)
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=False)
            binding = KakaoChannelBindingRecord
            policy = KakaoCollectionPolicyRevisionRecord
            statement = (
                select(binding, policy)
                .join(
                    policy,
                    (
                        (policy.source_binding_id == binding.source_binding_id)
                        & (policy.policy_revision_id == binding.current_policy_revision_id)
                    ),
                )
                .where(binding.owner_operator_id == owner)
            )
            if cursor is not None:
                statement = statement.where(binding.source_binding_id > cursor)
            rows = session.execute(
                statement.order_by(binding.source_binding_id).limit(limit + 1)
            ).all()
            items = tuple(_view(row[0], row[1]) for row in rows[:limit])
            return KakaoBindingPage(
                items=items, next_cursor=items[-1].source_binding_id if len(rows) > limit else None
            )
