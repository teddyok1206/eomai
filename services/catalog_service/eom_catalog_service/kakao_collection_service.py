"""Accept/replay one-room collection intents; no browser launch or fabricated actor.

This owner prepares a durable identity and ordered checkpoint. Actual profile
claim, fresh provider observation, command/attempt and source admission are separate
gates; resolving a stored intent below grants none of those operations.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from eom_catalog_contracts.kakao_capability import CAPABILITY_VERIFICATION_REF
from eom_catalog_contracts.kakao_collection import (
    AcceptedKakaoRoomCollection,
    KakaoCollectionStatus,
    KakaoRoomCollectionCreate,
)
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_binding_scope,
    authorize_kakao_current_operator,
    authorize_kakao_room_scope,
)
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_archive_models import KakaoChannelBindingRecord, KakaoCollectionPolicyRevisionRecord
from .kakao_capability_models import KakaoCapabilityAcceptanceRecord
from .kakao_capability_service import KakaoCapabilityService
from .kakao_collection_models import KakaoCollectionRunRecord as Run
from .kakao_collection_models import KakaoCollectionTaskRecord as Task
from .kakao_room_models import KakaoRoomRecord
from .kakao_source_pointers import validate_source_pointer_metadata_batch

_TERMINAL = frozenset({"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class StoredKakaoCollectionIntent:
    """Metadata for trusted owner preparation, never a public/worker credential."""

    accepted: AcceptedKakaoRoomCollection
    capability_manifest: ArtifactMemberPointer
    status: KakaoCollectionStatus


class KakaoCollectionService:
    def __init__(self, engine: Engine, *, capabilities: KakaoCapabilityService) -> None:
        self._sessions = build_session_factory(engine)
        self.capabilities = capabilities

    @staticmethod
    def _precondition(
        binding: KakaoChannelBindingRecord, command: KakaoRoomCollectionCreate
    ) -> None:
        if (
            binding.resource_version != command.expected_binding_version
            or binding.current_policy_revision_id != command.expected_policy_revision_id
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

    @staticmethod
    def _status(row: Run) -> KakaoCollectionStatus:
        return KakaoCollectionStatus.model_validate(
            dict(
                run_id=row.run_id,
                source_binding_id=row.source_binding_id,
                state=row.state,
                resource_version=row.resource_version,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    @staticmethod
    def _pins(session: Session, row: Run) -> ArtifactMemberPointer:
        capability = session.get(KakaoCapabilityAcceptanceRecord, row.capability_revision_id)
        policy = session.get(KakaoCollectionPolicyRevisionRecord, row.policy_revision_id)
        if (
            capability is None
            or capability.owner_operator_id != row.owner_operator_id
            or capability.source_binding_id != row.source_binding_id
            or capability.room_id != row.anchor_room_id
            or capability.adapter_release_sha256 != row.adapter_release_sha256
            or policy is None
            or policy.source_binding_id != row.source_binding_id
            or policy.sha256 != row.policy_sha256
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_PIN_INVALID")
        pointer = ArtifactMemberPointer(
            artifact_id=capability.manifest_artifact_id,
            artifact_revision_id=capability.manifest_artifact_revision_id,
            member_path="verification.json",
            schema_ref=CAPABILITY_VERIFICATION_REF,
            media_type="application/json",
            sha256=capability.manifest_sha256,
        )
        validate_source_pointer_metadata_batch(session, (pointer,))
        return pointer

    @staticmethod
    def _receipt(session: Session, row: Run, *, replayed: bool) -> AcceptedKakaoRoomCollection:
        task = session.scalar(select(Task).where(Task.run_id == row.run_id, Task.ordinal == 1))
        if task is None or task.room_id != row.anchor_room_id:
            raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_TASK_MISSING")
        return AcceptedKakaoRoomCollection(
            request=KakaoRoomCollectionCreate(
                source_binding_id=row.source_binding_id,
                room_id=row.anchor_room_id,
                capability_revision_id=row.capability_revision_id,
                expected_binding_version=row.accepted_binding_version,
                expected_policy_revision_id=row.policy_revision_id,
            ),
            run_id=row.run_id,
            task_id=task.task_id,
            request_sha256=row.request_sha256,
            policy_sha256=row.policy_sha256,
            adapter_release_sha256=row.adapter_release_sha256,
            created_at=row.created_at,
            replayed=replayed,
        )

    @staticmethod
    def _prior(session: Session, owner: str, binding: str, key: str) -> Run | None:
        return session.scalar(
            select(Run).where(
                Run.owner_operator_id == owner,
                Run.source_binding_id == binding,
                Run.idempotency_key == key,
            )
        )

    @staticmethod
    def _write_scope(
        session: Session, actor: ActorContext, command: KakaoRoomCollectionCreate, *, lock: bool
    ) -> tuple[str, KakaoChannelBindingRecord]:
        owner = authorize_kakao_actor(
            session,
            actor,
            PermissionKey.KAKAO_ARCHIVE_COLLECT,
            now=datetime.now(UTC),
            admin_only=True,
        )
        authorize_kakao_room_scope(
            session,
            actor,
            command.source_binding_id,
            command.room_id,
            PermissionKey.KAKAO_ARCHIVE_READ,
            lock=lock,
        )
        binding = session.get(KakaoChannelBindingRecord, command.source_binding_id)
        if binding is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return owner, binding

    def create_room_collection(
        self, actor: ActorContext, command: KakaoRoomCollectionCreate, *, idempotency_key: str
    ) -> AcceptedKakaoRoomCollection:
        command = KakaoRoomCollectionCreate.model_validate(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        digest = kakao_command_sha256(command)
        with self._sessions.begin() as session:
            owner, binding = self._write_scope(session, actor, command, lock=False)
            prior = self._prior(session, owner, command.source_binding_id, key)
            if prior is not None:
                if prior.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                self._pins(session, prior)
                return self._receipt(session, prior, replayed=True)
            self._precondition(binding, command)

        # Resolve actual canonical evidence outside DB locks; an accepted capability
        # row alone must not admit arbitrary worker/client capability bytes.
        accepted_capability = self.capabilities.get_capability(
            actor, command.source_binding_id, command.capability_revision_id
        )
        if (
            accepted_capability.verification.request.room_id != command.room_id
            or accepted_capability.capability.visible_scope_ids != ("MANUAL_SELECTED_ROOM",)
            or accepted_capability.capability.adapter_release_sha256
            != self.capabilities.adapter_sha256
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_CAPABILITY_MISMATCH")
        with self._sessions.begin() as session:
            lock_kakao_intent(session, owner, "collection/" + command.source_binding_id, key)
            owner, binding = self._write_scope(session, actor, command, lock=True)
            prior = self._prior(session, owner, command.source_binding_id, key)
            if prior is not None:
                if prior.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                self._pins(session, prior)
                return self._receipt(session, prior, replayed=True)
            self._precondition(binding, command)
            policy = session.get(
                KakaoCollectionPolicyRevisionRecord, command.expected_policy_revision_id
            )
            if policy is None or policy.source_binding_id != command.source_binding_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_PIN_INVALID")
            active = session.scalar(
                select(Run.run_id)
                .where(
                    Run.source_binding_id == binding.source_binding_id, Run.state.not_in(_TERMINAL)
                )
                .limit(1)
            )
            if active is not None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_ALREADY_PENDING")
            now = datetime.now(UTC)
            row = Run(
                run_id="kakaorun_" + uuid4().hex,
                owner_operator_id=owner,
                source_binding_id=binding.source_binding_id,
                anchor_room_id=command.room_id,
                capability_revision_id=command.capability_revision_id,
                policy_revision_id=policy.policy_revision_id,
                policy_sha256=policy.sha256,
                adapter_release_sha256=accepted_capability.capability.adapter_release_sha256,
                accepted_binding_version=binding.resource_version,
                idempotency_key=key,
                request_sha256=digest,
                state="QUEUED",
                stop_target=None,
                resource_version=1,
                created_at=now,
                updated_at=now,
            )
            self._pins(session, row)
            session.add(row)
            session.flush()
            session.add(
                Task(
                    task_id="kakaotask_" + uuid4().hex,
                    run_id=row.run_id,
                    owner_operator_id=owner,
                    source_binding_id=binding.source_binding_id,
                    room_id=command.room_id,
                    ordinal=1,
                    state="QUEUED",
                )
            )
            session.flush()
            return self._receipt(session, row, replayed=False)

    def get_status(self, actor: ActorContext, binding: str, run_id: str) -> KakaoCollectionStatus:
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            row = session.scalar(
                select(Run).where(
                    Run.run_id == run_id,
                    Run.source_binding_id == binding,
                    Run.owner_operator_id == owner,
                )
            )
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            authorize_kakao_room_scope(
                session,
                actor,
                binding,
                row.anchor_room_id,
                PermissionKey.KAKAO_ARCHIVE_READ,
                lock=False,
            )
            self._pins(session, row)
            return self._status(row)

    def read_background_intent(self, run_id: str) -> StoredKakaoCollectionIntent:
        """Trusted composition only: reauthorize accepted intent, not expired HTTP auth.

        This metadata result is insufficient to launch a browser or admit sources.
        Those consumers must also require their actual current attempt/profile fence.
        """
        with self._sessions.begin() as session:
            row = session.get(Run, run_id)
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            for permission in (
                PermissionKey.KAKAO_ARCHIVE_READ,
                PermissionKey.KAKAO_ARCHIVE_COLLECT,
            ):
                authorize_kakao_current_operator(
                    session,
                    operator_id=row.owner_operator_id,
                    permission=permission,
                    admin_only=True,
                )
            binding = session.get(KakaoChannelBindingRecord, row.source_binding_id)
            if binding is None or binding.owner_operator_id != row.owner_operator_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            if binding.state == "RETIRED":
                raise KakaoArchiveError("KAKAO_ARCHIVE_BINDING_RETIRED")
            if row.state in _TERMINAL:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_TERMINAL")
            if binding.current_policy_revision_id != row.policy_revision_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_POLICY_CHANGED")
            if row.adapter_release_sha256 != self.capabilities.adapter_sha256:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_ADAPTER_CHANGED")
            pointer = self._pins(session, row)
            # Room lifecycle is checked without synthesizing an OPERATOR actor.
            room = session.get(KakaoRoomRecord, row.anchor_room_id)
            if (
                room is None
                or room.owner_operator_id != row.owner_operator_id
                or room.source_binding_id != row.source_binding_id
                or room.state != "ACTIVE"
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_RETIRED")
            return StoredKakaoCollectionIntent(
                self._receipt(session, row, replayed=True), pointer, self._status(row)
            )
