"""Accept/replay one-room collection intents; no browser launch or fabricated actor.

This owner prepares a durable identity and ordered checkpoint. Actual profile
claim, fresh provider observation, command/attempt and source admission are separate
gates; resolving a stored intent below grants none of those operations.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from eom_catalog_contracts.kakao_capability import ConfirmKakaoCapability
from eom_catalog_contracts.kakao_collection import (
    AcceptedKakaoRoomCollection,
    KakaoCollectionStatus,
    KakaoCollectionStatusView,
    KakaoRoomCollectionCreate,
)
from eom_identifiers import sha256_bytes
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_binding_scope,
    authorize_kakao_room_scope,
)
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_archive_models import KakaoChannelBindingRecord, KakaoCollectionPolicyRevisionRecord
from .kakao_capability_service import KakaoCapabilityService
from .kakao_collection_attempt_models import KakaoCollectionAttemptRecord as Attempt
from .kakao_collection_authorization import (
    authorize_kakao_collection_preparation,
    validate_kakao_collection_pins,
)
from .kakao_collection_browser_models import KakaoCollectionBrowserRecord as Browser
from .kakao_collection_models import KakaoCollectionRunRecord as Run
from .kakao_collection_models import KakaoCollectionTaskRecord as Task

_TERMINAL = frozenset({"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class StoredKakaoCollectionIntent:
    """Metadata for trusted owner preparation, never a public/worker credential."""

    accepted: AcceptedKakaoRoomCollection
    capability_manifest: ArtifactMemberPointer
    status: KakaoCollectionStatus


@dataclass(frozen=True, slots=True)
class PendingKakaoRoomRun:
    run_id: str
    attempt_id: str | None
    browser_run_id: str | None


class KakaoCollectionService:
    def __init__(self, engine: Engine, *, capabilities: KakaoCapabilityService) -> None:
        self._sessions = build_session_factory(engine)
        self.capabilities = capabilities

    def next_pending_room(self) -> PendingKakaoRoomRun | None:
        """Bounded durable discovery only; every effect still rechecks the run and fence."""
        with self._sessions.begin() as session:
            for state in ("COLLECTING", "QUEUED"):
                run = session.scalar(
                    select(Run)
                    .where(
                        Run.state == state,
                        Run.adapter_release_sha256 == self.capabilities.adapter_sha256,
                    )
                    .order_by(Run.created_at, Run.run_id)
                    .limit(1)
                )
                if run is None:
                    continue
                attempt = session.scalar(
                    select(Attempt)
                    .join(Task, Task.task_id == Attempt.task_id)
                    .where(Task.run_id == run.run_id, Task.ordinal == 1)
                )
                browser_id = (
                    run.current_browser_run_id if attempt is None else attempt.browser_run_id
                )
                if browser_id is None:
                    browser_id = session.scalar(
                        select(Browser.browser_run_id)
                        .where(Browser.run_id == run.run_id)
                        .order_by(Browser.epoch_number.desc())
                        .limit(1)
                    )
                return PendingKakaoRoomRun(
                    run.run_id, None if attempt is None else attempt.attempt_id, browser_id
                )
        return None

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
        session: Session, actor: ActorContext, binding_id: str, room_id: str, *, lock: bool
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
            binding_id,
            room_id,
            PermissionKey.KAKAO_ARCHIVE_READ,
            lock=lock,
        )
        binding = session.get(KakaoChannelBindingRecord, binding_id)
        if binding is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return owner, binding

    def start_registered_room(
        self,
        actor: ActorContext,
        selection: ConfirmKakaoCapability,
        *,
        expected_policy_revision_id: str,
        idempotency_key: str,
    ) -> KakaoCollectionStatus:
        key = validate_kakao_idempotency_key(idempotency_key)
        binding_id, room_id = selection.source_binding_id, selection.room_id
        with self._sessions.begin() as session:
            owner, binding = self._write_scope(session, actor, binding_id, room_id, lock=False)
            prior = self._prior(session, owner, binding_id, key)
            if prior is not None:
                if (
                    prior.anchor_room_id,
                    prior.accepted_binding_version,
                    prior.policy_revision_id,
                ) != (
                    room_id,
                    selection.expected_binding_version,
                    expected_policy_revision_id,
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                validate_kakao_collection_pins(session, prior)
                return self._status(prior)
            if (binding.resource_version, binding.current_policy_revision_id) != (
                selection.expected_binding_version,
                expected_policy_revision_id,
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        capability = self.capabilities.confirm_capability(
            actor,
            selection,
            idempotency_key="kakao:collect-cap:" + sha256_bytes(key.encode())[7:],
        )
        receipt = self.create_room_collection(
            actor,
            KakaoRoomCollectionCreate(
                source_binding_id=binding_id,
                room_id=room_id,
                capability_revision_id=capability.capability.capability_revision_id,
                expected_binding_version=selection.expected_binding_version,
                expected_policy_revision_id=expected_policy_revision_id,
            ),
            idempotency_key=key,
        )
        return self.get_status(actor, binding_id, receipt.run_id)

    def create_room_collection(
        self, actor: ActorContext, command: KakaoRoomCollectionCreate, *, idempotency_key: str
    ) -> AcceptedKakaoRoomCollection:
        command = KakaoRoomCollectionCreate.model_validate(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        digest = kakao_command_sha256(command)
        with self._sessions.begin() as session:
            owner, binding = self._write_scope(
                session, actor, command.source_binding_id, command.room_id, lock=False
            )
            prior = self._prior(session, owner, command.source_binding_id, key)
            if prior is not None:
                if prior.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                validate_kakao_collection_pins(session, prior)
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
            owner, binding = self._write_scope(
                session, actor, command.source_binding_id, command.room_id, lock=True
            )
            prior = self._prior(session, owner, command.source_binding_id, key)
            if prior is not None:
                if prior.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                validate_kakao_collection_pins(session, prior)
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
            validate_kakao_collection_pins(session, row)
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

    @staticmethod
    def _authorized_status_run(
        session: Session, actor: ActorContext, binding: str, run_id: str
    ) -> Run:
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
        validate_kakao_collection_pins(session, row)
        return row

    def get_status(self, actor: ActorContext, binding: str, run_id: str) -> KakaoCollectionStatus:
        with self._sessions.begin() as session:
            return self._status(self._authorized_status_run(session, actor, binding, run_id))

    def get_status_view(
        self, actor: ActorContext, binding: str, run_id: str
    ) -> KakaoCollectionStatusView:
        with self._sessions.begin() as session:
            row = self._authorized_status_run(session, actor, binding, run_id)
            needs_login = (
                row.state == "FAILED"
                and session.scalar(
                    select(Attempt.attempt_id)
                    .join(Task, Task.task_id == Attempt.task_id)
                    .where(
                        Task.run_id == row.run_id,
                        Task.ordinal == 1,
                        Task.room_id == row.anchor_room_id,
                        Task.state == "FAILED",
                        Attempt.state == "RESULT_ACCEPTED",
                        Attempt.result_status == "FAILED",
                        Attempt.error_code == "AUTH_REQUIRED",
                    )
                    .limit(1)
                )
                is not None
            )
            return KakaoCollectionStatusView(
                collection=self._status(row),
                failure_reason="KAKAO_LOGIN_REQUIRED" if needs_login else None,
            )

    def read_background_intent(self, run_id: str) -> StoredKakaoCollectionIntent:
        """Trusted composition only: reauthorize accepted intent, not expired HTTP auth.

        This metadata result is insufficient to launch a browser or admit sources.
        Those consumers must also require their actual current attempt/profile fence.
        """
        with self._sessions.begin() as session:
            row = session.get(Run, run_id)
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            pointer = authorize_kakao_collection_preparation(
                session, row, adapter_release_sha256=self.capabilities.adapter_sha256
            )
            return StoredKakaoCollectionIntent(
                self._receipt(session, row, replayed=True), pointer, self._status(row)
            )
