"""Durable manual-login admission. OS execution remains outside Catalog transactions."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from eom_catalog_contracts.kakao_manual import (
    EndReason,
    KakaoManualClosureObservation,
    KakaoManualEnd,
    KakaoManualFreshProfile,
    KakaoManualIntent,
    KakaoManualMutation,
    KakaoManualRenew,
    KakaoManualRuntimeObservation,
    KakaoManualSession,
    KakaoManualStart,
    ManualError,
    Phase,
)
from eom_catalog_contracts.kakao_manual_runtime_values import (
    manual_profile_fence as manual_profile_fence,
)
from eom_catalog_contracts.kakao_manual_runtime_values import recorded_manual_gateway_grant
from eom_kakao_archive_contracts.kakao_remote import (
    AUTHORITY_MAX_AGE,
    LEASE_MAX_LIFETIME,
    LEASE_TTL,
    CurrentRemoteAuthority,
    GatewayLeaseGrant,
    ProfileFence,
    RemoteLease,
    RemoteRuntime,
    renew_remote_lease,
)
from eom_operator_identity.contracts import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_identity_session,
)
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_archive_models import KakaoChannelBindingRecord
from .kakao_manual_models import (
    KakaoManualSessionRecord as Lease,
)
from .kakao_manual_models import (
    KakaoProfileRuntimeRecord as Profile,
)
from .kakao_manual_models import (
    KakaoRemoteCommandRecord as Receipt,
)

RuntimeObserver = Callable[[KakaoManualIntent], KakaoManualRuntimeObservation]
ClosureObserver = Callable[[KakaoManualIntent], KakaoManualClosureObservation]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _error(suffix: str) -> KakaoArchiveError:
    return KakaoArchiveError("KAKAO_ARCHIVE_" + suffix)


def _lease_id(value: str) -> str:
    if re.fullmatch(r"kakaoremotelease_[0-9a-f]{32}", value) is None:
        raise _error("REQUEST_INVALID")
    return value


def _view(row: Lease, now: datetime, receipt: Receipt | None = None) -> KakaoManualSession:
    try:
        return KakaoManualSession(
            lease_id=row.lease_id,
            source_binding_id=row.source_binding_id,
            phase=cast(Phase, receipt.result_phase if receipt else row.phase),
            resource_version=receipt.result_version if receipt else row.resource_version,
            grant_revision=receipt.result_grant_revision if receipt else row.grant_revision,
            created_at=row.created_at,
            expires_at=receipt.result_expires_at if receipt else row.expires_at,
            absolute_expires_at=row.absolute_expires_at,
            ready=receipt.result_ready
            if receipt
            else (row.phase == "ACTIVE" and row.expires_at is not None and now < row.expires_at),
            last_error=cast(
                ManualError | None, receipt.result_error if receipt else row.last_error
            ),
            ended_reason=cast(
                EndReason | None, receipt.result_ended_reason if receipt else row.ended_reason
            ),
            closed_at=receipt.result_closed_at if receipt else row.closed_at,
        )
    except ValueError:
        raise _error("STORED_MANUAL_SESSION_INVALID") from None


def manual_gateway_grant(intent: KakaoManualIntent) -> GatewayLeaseGrant:
    """Internal gateway value, never a public authority claim or standalone permission."""
    if (
        intent.authorized_at is None
        or intent.expires_at is None
        or intent.phase not in {"PREPARING", "ACTIVE"}
    ):
        raise _error("REMOTE_NOT_READY")
    return recorded_manual_gateway_grant(intent)


def _intent(row: Lease) -> KakaoManualIntent:
    pins = dict(
        lease_id=row.lease_id,
        profile_id=row.profile_id,
        browser_run_id=row.browser_run_id,
        command_sha256=row.command_sha256,
        fence_epoch=row.fence_epoch,
        gateway_epoch=row.gateway_epoch,
    )
    try:
        browser = None
        if row.browser_invocation_id is not None:
            browser = KakaoManualRuntimeObservation.model_validate(
                {
                    **pins,
                    "observed_at": row.browser_observed_at,
                    "boot_id": row.dispatch_boot_id,
                    "invocation_id": row.browser_invocation_id,
                    "main_pid": row.browser_pid,
                    "started_monotonic_us": row.browser_monotonic_us,
                    "browser_running": True,
                    "profile_locked": True,
                    "gateway_running": row.gateway_invocation_id is not None,
                    "gateway_invocation_id": row.gateway_invocation_id,
                }
            )
        result = KakaoManualIntent.model_validate(
            {
                **pins,
                "source_binding_id": row.source_binding_id,
                "owner_operator_id": row.owner_operator_id,
                "identity_session_id": row.identity_session_id,
                "dispatch_boot_id": row.dispatch_boot_id,
                "phase": row.phase,
                "resource_version": row.resource_version,
                "grant_revision": row.grant_revision,
                "created_at": row.created_at,
                "authorized_at": row.authorized_at,
                "expires_at": row.expires_at,
                "absolute_expires_at": row.absolute_expires_at,
                "browser": browser,
                "last_error": row.last_error,
                "ended_reason": row.ended_reason,
            }
        )
        if kakao_command_sha256(manual_profile_fence(result)) != result.command_sha256:
            raise ValueError("hash")
        return result
    except ValueError:
        raise _error("STORED_MANUAL_SESSION_INVALID") from None


class KakaoManualService:
    """Fixed-profile indexed lookup/CAS; callbacks are always outside DB transactions.

    Profile ownership never transfers implicitly. The same profile row is the single
    AUTO/MANUAL fence gate; this slice admits MANUAL only from positively closed STOPPED.
    """

    def __init__(
        self, engine: Engine, *, profile_id: str, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        if re.fullmatch(r"kakaoprofile_[0-9a-f]{32}", profile_id) is None:
            raise _error("REQUEST_INVALID")
        self._sessions = build_session_factory(engine)
        self._profile_id = profile_id
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise _error("REQUEST_INVALID")
        return now

    @staticmethod
    def _authorize(session: Session, actor: ActorContext, now: datetime) -> str:
        return authorize_kakao_actor(
            session, actor, PermissionKey.KAKAO_ARCHIVE_REMOTE, now=now, admin_only=True
        )

    @staticmethod
    def _binding(
        session: Session, owner: str, binding_id: str, *, lock: bool = False
    ) -> KakaoChannelBindingRecord:
        query = select(KakaoChannelBindingRecord).where(
            KakaoChannelBindingRecord.owner_operator_id == owner,
            KakaoChannelBindingRecord.source_binding_id == binding_id,
        )
        row = session.scalar(query.with_for_update(read=True) if lock else query)
        if row is None:
            raise _error("RESOURCE_NOT_FOUND")
        return row

    def _profile(self, session: Session, *, lock: bool = False) -> Profile | None:
        query = select(Profile).where(Profile.slot_key == "primary")
        row = session.scalar(query.with_for_update() if lock else query)
        if row is not None and row.profile_id != self._profile_id:
            raise _error("REMOTE_PROFILE_UNAVAILABLE")
        return row

    @staticmethod
    def _owned(session: Session, actor: ActorContext, lease_id: str, owner: str) -> Lease:
        row = session.scalar(
            select(Lease).where(
                Lease.lease_id == _lease_id(lease_id), Lease.owner_operator_id == owner
            )
        )
        if row is None or row.identity_session_id != actor.session_id:
            raise _error("RESOURCE_NOT_FOUND")
        return row

    @staticmethod
    def _fresh(observed_at: datetime, now: datetime) -> None:
        if not timedelta(0) <= now - observed_at <= AUTHORITY_MAX_AGE:
            raise _error("REMOTE_OBSERVATION_STALE")

    def _locked(
        self, session: Session, lease_id: str
    ) -> tuple[Lease, Profile, KakaoChannelBindingRecord]:
        current = session.get(Lease, _lease_id(lease_id))
        if current is None:
            raise _error("RESOURCE_NOT_FOUND")
        binding = self._binding(
            session, current.owner_operator_id, current.source_binding_id, lock=True
        )
        profile = self._profile(session, lock=True)
        row = session.scalar(
            select(Lease)
            .where(Lease.lease_id == lease_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert row is not None
        if (
            profile is None
            or profile.current_lease_id != lease_id
            or profile.fence_epoch != row.fence_epoch
            or profile.gateway_epoch != row.gateway_epoch
        ):
            raise _error("REMOTE_FENCE_STALE")
        return row, profile, binding

    @staticmethod
    def _authority(
        session: Session, row: Lease, binding: KakaoChannelBindingRecord, now: datetime
    ) -> None:
        authorize_kakao_identity_session(
            session,
            operator_id=row.owner_operator_id,
            identity_session_id=row.identity_session_id,
            permission=PermissionKey.KAKAO_ARCHIVE_REMOTE,
            now=now,
            admin_only=True,
        )
        # DRAFT permits first login; it does not imply source-channel verification.
        if binding.state == "RETIRED":
            raise _error("BINDING_RETIRED")

    @staticmethod
    def _live(row: Lease, profile: Profile, now: datetime) -> None:
        if profile.mode != "MANUAL":
            raise _error("REMOTE_FENCE_STALE")
        if (
            row.phase not in {"PREPARING", "ACTIVE"}
            or now >= row.absolute_expires_at
            or (row.expires_at is not None and now >= row.expires_at)
        ):
            raise _error("REMOTE_LEASE_EXPIRED")

    def _replay(
        self,
        session: Session,
        actor: ActorContext,
        owner: str,
        scope: str,
        key: str,
        digest: str,
        now: datetime,
    ) -> KakaoManualMutation | None:
        receipt = session.scalar(
            select(Receipt).where(
                Receipt.owner_operator_id == owner,
                Receipt.idempotency_scope == scope,
                Receipt.idempotency_key == key,
            )
        )
        if receipt is None:
            return None
        if receipt.request_sha256 != digest:
            raise _error("IDEMPOTENCY_CONFLICT")
        row = self._owned(session, actor, receipt.lease_id, owner)
        self._authority(session, row, self._binding(session, owner, row.source_binding_id), now)
        return KakaoManualMutation(session=_view(row, now, receipt), replayed=True)

    @staticmethod
    def _record(
        session: Session,
        row: Lease,
        *,
        scope: str,
        key: str,
        digest: str,
        action: str,
        now: datetime,
    ) -> KakaoManualMutation:
        view = _view(row, now)
        session.add(
            Receipt(
                command_id="kakaocommand_" + uuid4().hex,
                owner_operator_id=row.owner_operator_id,
                lease_id=row.lease_id,
                idempotency_scope=scope,
                idempotency_key=key,
                request_sha256=digest,
                action=action,
                result_phase=view.phase,
                result_version=view.resource_version,
                result_grant_revision=view.grant_revision,
                result_expires_at=view.expires_at,
                result_ready=view.ready,
                result_error=view.last_error,
                result_ended_reason=view.ended_reason,
                result_closed_at=view.closed_at,
                completed_at=now,
            )
        )
        return KakaoManualMutation(session=view, replayed=False)

    def start_session(
        self,
        actor: ActorContext,
        command: KakaoManualStart,
        *,
        idempotency_key: str,
        observe_profile: Callable[[], KakaoManualFreshProfile],
    ) -> KakaoManualMutation:
        key, digest = validate_kakao_idempotency_key(idempotency_key), kakao_command_sha256(command)
        scope = "manual-start/" + command.source_binding_id
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            binding = self._binding(session, owner, command.source_binding_id)
            if binding.state == "RETIRED":
                raise _error("BINDING_RETIRED")
            replay = self._replay(session, actor, owner, scope, key, digest, now)
            if replay:
                return replay
        observation = observe_profile()  # Protected runtime/installer proof, not browser input.
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            binding = self._binding(session, owner, command.source_binding_id, lock=True)
            if binding.state == "RETIRED":
                raise _error("BINDING_RETIRED")
            lock_kakao_intent(session, "installed-profile", "manual-start", "primary")
            replay = self._replay(session, actor, owner, scope, key, digest, now)
            if replay:
                return replay
            self._fresh(observation.observed_at, now)
            if observation.profile_id != self._profile_id or not (
                observation.browser_stopped
                and observation.gateway_stopped
                and observation.profile_lock_released
            ):
                raise _error("REMOTE_PROFILE_UNAVAILABLE")
            profile = self._profile(session, lock=True)
            if profile is None:
                if not observation.never_used or not observation.profile_empty:
                    raise _error("REMOTE_PROFILE_UNASSIGNED")
                profile = Profile(
                    slot_key="primary",
                    profile_id=self._profile_id,
                    owner_operator_id=owner,
                    source_binding_id=binding.source_binding_id,
                    mode="STOPPED",
                    fence_epoch=0,
                    gateway_epoch=0,
                    resource_version=1,
                    current_lease_id=None,
                    created_at=now,
                )
                session.add(profile)
                session.flush()
            if profile.owner_operator_id != owner:
                raise _error("REMOTE_PROFILE_UNAVAILABLE")
            if (
                profile.mode != "STOPPED"
                or profile.current_lease_id is not None
                or profile.current_collection_browser_run_id is not None
            ):
                raise _error("REMOTE_PROFILE_BUSY")
            # Historical sessions pin their own binding; only the positively
            # closed current assignment moves, never an old lease or source.
            profile.source_binding_id = binding.source_binding_id
            fence = ProfileFence(
                schema_version="kakao-profile-fence/1.0",
                profile_id=self._profile_id,
                browser_run_id="kakaobrowserrun_" + uuid4().hex,
                fence_epoch=profile.fence_epoch + 1,
                mode="MANUAL",
            )
            row = Lease(
                lease_id="kakaoremotelease_" + uuid4().hex,
                owner_operator_id=owner,
                source_binding_id=binding.source_binding_id,
                identity_session_id=actor.session_id,
                profile_id=profile.profile_id,
                browser_run_id=fence.browser_run_id,
                command_sha256=kakao_command_sha256(fence),
                dispatch_boot_id=observation.boot_id,
                fence_epoch=fence.fence_epoch,
                gateway_epoch=profile.gateway_epoch + 1,
                phase="PREPARING",
                resource_version=1,
                grant_revision=0,
                created_at=now,
                absolute_expires_at=now + LEASE_MAX_LIFETIME,
            )
            session.add(row)
            profile.mode, profile.current_lease_id = "MANUAL", row.lease_id
            profile.fence_epoch, profile.gateway_epoch = row.fence_epoch, row.gateway_epoch
            profile.resource_version += 1
            session.flush()
            return self._record(
                session, row, scope=scope, key=key, digest=digest, action="START", now=now
            )

    def get_session(self, actor: ActorContext, lease_id: str) -> KakaoManualSession:
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            row = self._owned(session, actor, lease_id, owner)
            self._authority(session, row, self._binding(session, owner, row.source_binding_id), now)
            return _view(row, now)

    def authorize_session(
        self, actor: ActorContext, lease_id: str, *, observe_runtime: RuntimeObserver
    ) -> KakaoManualSession:
        """Read-only proxy admission, distinct from a possibly stale history view.

        The actual runtime probe runs without row locks. Recheck both the current
        actor and exact accepted revision afterward; never launch, renew or reconcile.
        """
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            self._owned(session, actor, lease_id, owner)
            row, profile, binding = self._locked(session, lease_id)
            self._authority(session, row, binding, now)
            self._live(row, profile, now)
            if row.phase != "ACTIVE":
                raise _error("REMOTE_NOT_READY")
            before = _intent(row)
        observed = observe_runtime(before)
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            self._owned(session, actor, lease_id, owner)
            row, profile, binding = self._locked(session, lease_id)
            self._authority(session, row, binding, now)
            self._live(row, profile, now)
            if row.phase != "ACTIVE" or row.resource_version != before.resource_version:
                raise _error("PRECONDITION_FAILED")
            self._observation(row, observed, now, gateway=True)
            return _view(row, now)

    def get_current_intent(self) -> KakaoManualIntent | None:
        """Internal fixed-profile coordinator lookup, never public request authorization."""
        with self._sessions() as session, session.begin():
            profile = self._profile(session)
            if profile is None or profile.current_lease_id is None:
                return None
            row = session.get(Lease, profile.current_lease_id)
            if row is None or row.profile_id != profile.profile_id:
                raise _error("REMOTE_FENCE_STALE")
            return _intent(row)

    def get_predecessor_intent(
        self, intent: KakaoManualIntent, *, fence_epoch: int | None = None
    ) -> KakaoManualIntent | None:
        """Exact earlier closed fence, optionally from protected staged input; not latest."""
        epoch = intent.fence_epoch - 1 if fence_epoch is None else fence_epoch
        if epoch == 0 and intent.fence_epoch == 1:
            return None
        if isinstance(epoch, bool) or not 0 < epoch < intent.fence_epoch:
            raise _error("REMOTE_FENCE_STALE")
        with self._sessions() as session, session.begin():
            profile = self._profile(session)
            if (
                profile is None
                or profile.profile_id != intent.profile_id
                or (
                    profile.owner_operator_id != intent.owner_operator_id
                    or profile.source_binding_id != intent.source_binding_id
                )
            ):
                raise _error("REMOTE_FENCE_STALE")
            row = session.scalar(
                select(Lease).where(
                    Lease.profile_id == profile.profile_id, Lease.fence_epoch == epoch
                )
            )
            if (
                row is None
                or row.phase != "ENDED"
                or row.closed_at is None
                or row.owner_operator_id != intent.owner_operator_id
            ):
                raise _error("REMOTE_FENCE_STALE")
            return _intent(row)

    def get_intent(self, lease_id: str, *, require_live: bool = True) -> KakaoManualIntent:
        """Internal coordinator lookup. Not a request-authentication alternative."""
        with self._sessions() as session, session.begin():
            row, profile, binding = self._locked(session, lease_id)
            if require_live:
                self._authority(session, row, binding, self._now())
                self._live(row, profile, self._now())
            return _intent(row)

    def _observation(
        self, row: Lease, observed: KakaoManualRuntimeObservation, now: datetime, *, gateway: bool
    ) -> None:
        self._fresh(observed.observed_at, now)
        if (
            any(
                getattr(row, name) != getattr(observed, name)
                for name in (
                    "lease_id",
                    "profile_id",
                    "browser_run_id",
                    "command_sha256",
                    "fence_epoch",
                    "gateway_epoch",
                )
            )
            or observed.boot_id != row.dispatch_boot_id
        ):
            raise _error("REMOTE_OBSERVATION_MISMATCH")
        if (
            not observed.browser_running
            or not observed.profile_locked
            or observed.gateway_running != gateway
        ):
            raise _error("REMOTE_RUNTIME_UNAVAILABLE")
        if row.browser_invocation_id is not None and (
            observed.invocation_id != row.browser_invocation_id
            or observed.main_pid != row.browser_pid
            or observed.started_monotonic_us != row.browser_monotonic_us
        ):
            raise _error("REMOTE_OBSERVATION_MISMATCH")
        if (
            row.gateway_invocation_id is not None
            and observed.gateway_invocation_id != row.gateway_invocation_id
        ):
            raise _error("REMOTE_OBSERVATION_MISMATCH")

    def prepare_gateway(
        self, lease_id: str, *, observe_browser: RuntimeObserver
    ) -> KakaoManualIntent:
        before = self.get_intent(lease_id)
        observed = observe_browser(before)
        with self._sessions() as session, session.begin():
            now = self._now()
            row, profile, binding = self._locked(session, lease_id)
            self._authority(session, row, binding, now)
            self._live(row, profile, now)
            if (
                row.resource_version != before.resource_version
                or row.phase != "PREPARING"
                or row.grant_revision
            ):
                raise _error("PRECONDITION_FAILED")
            self._observation(row, observed, now, gateway=False)
            row.browser_invocation_id, row.browser_pid = observed.invocation_id, observed.main_pid
            row.browser_monotonic_us, row.browser_observed_at = (
                observed.started_monotonic_us,
                observed.observed_at,
            )
            row.authorized_at, row.expires_at = now, min(now + LEASE_TTL, row.absolute_expires_at)
            row.grant_revision, row.resource_version = 1, row.resource_version + 1
            return _intent(row)

    def accept_ready(self, lease_id: str, *, observe_runtime: RuntimeObserver) -> KakaoManualIntent:
        before = self.get_intent(lease_id)
        observed = observe_runtime(before)
        with self._sessions() as session, session.begin():
            now = self._now()
            row, profile, binding = self._locked(session, lease_id)
            self._authority(session, row, binding, now)
            self._live(row, profile, now)
            if (
                row.resource_version != before.resource_version
                or row.phase != "PREPARING"
                or row.grant_revision != 1
            ):
                raise _error("PRECONDITION_FAILED")
            self._observation(row, observed, now, gateway=True)
            row.gateway_invocation_id, row.browser_observed_at = (
                observed.gateway_invocation_id,
                observed.observed_at,
            )
            row.phase, row.resource_version = "ACTIVE", row.resource_version + 1
            return _intent(row)

    def renew_session(
        self,
        actor: ActorContext,
        lease_id: str,
        command: KakaoManualRenew,
        *,
        idempotency_key: str,
        observe_runtime: RuntimeObserver,
    ) -> KakaoManualMutation:
        key, digest = validate_kakao_idempotency_key(idempotency_key), kakao_command_sha256(command)
        scope = "manual-renew/" + _lease_id(lease_id)
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            self._owned(session, actor, lease_id, owner)
            replay = self._replay(session, actor, owner, scope, key, digest, now)
            if replay:
                return replay
        before = self.get_intent(lease_id)
        observed = observe_runtime(before)
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            self._owned(session, actor, lease_id, owner)
            row, profile, binding = self._locked(session, lease_id)
            replay = self._replay(session, actor, owner, scope, key, digest, now)
            if replay:
                return replay
            self._authority(session, row, binding, now)
            self._live(row, profile, now)
            if (
                row.phase != "ACTIVE"
                or row.grant_revision != command.expected_grant_revision
                or row.resource_version != before.resource_version
            ):
                raise _error("PRECONDITION_FAILED")
            self._observation(row, observed, now, gateway=True)
            # Reuse the existing lease rule after deriving authority from current Identity.
            lease = RemoteLease.model_validate(
                {
                    **manual_gateway_grant(_intent(row)).model_dump(),
                    "schema_version": "kakao-remote-lease/1.0",
                    "operator_id": row.owner_operator_id,
                    "identity_session_id": row.identity_session_id,
                    "state": "ACTIVE",
                    "ended_at": None,
                }
            )
            authority = CurrentRemoteAuthority(
                schema_version="kakao-remote-authority/1.0",
                operator_id=row.owner_operator_id,
                identity_session_id=row.identity_session_id,
                source_binding_id=row.source_binding_id,
                binding_owner_operator_id=binding.owner_operator_id,
                operator_active=True,
                session_active=True,
                is_admin=True,
                remote_permission=True,
                source_active=binding.state != "RETIRED",
                source_access=True,
                checked_at=now,
            )
            runtime = RemoteRuntime(
                schema_version="kakao-remote-runtime/1.0",
                source_binding_id=row.source_binding_id,
                profile_id=row.profile_id,
                mode="MANUAL",  # _live checked the actual durable profile mode above.
                fence_epoch=row.fence_epoch,
                gateway_epoch=row.gateway_epoch,
                browser_run_id=row.browser_run_id,
                process_state="RUNNING",
                profile_locked=observed.profile_locked,
                available=observed.browser_running and observed.gateway_running,
            )
            renewed = renew_remote_lease(lease, authority, runtime, now=now)
            row.authorized_at, row.expires_at = renewed.authorized_at, renewed.expires_at
            row.grant_revision = renewed.grant_revision
            row.resource_version += 1
            row.browser_observed_at = observed.observed_at
            return self._record(
                session, row, scope=scope, key=key, digest=digest, action="RENEW", now=now
            )

    def end_session(
        self, actor: ActorContext, lease_id: str, command: KakaoManualEnd, *, idempotency_key: str
    ) -> KakaoManualMutation:
        key, digest = validate_kakao_idempotency_key(idempotency_key), kakao_command_sha256(command)
        scope = "manual-end/" + _lease_id(lease_id)
        with self._sessions() as session, session.begin():
            now = self._now()
            owner = self._authorize(session, actor, now)
            self._owned(session, actor, lease_id, owner)
            replay = self._replay(session, actor, owner, scope, key, digest, now)
            if replay:
                return replay
            row, _, _ = self._locked(session, lease_id)
            if row.resource_version != command.expected_resource_version:
                raise _error("PRECONDITION_FAILED")
            row.phase, row.resource_version = "STOPPING", row.resource_version + 1
            row.ended_reason = row.ended_reason or "USER_ENDED"
            return self._record(
                session, row, scope=scope, key=key, digest=digest, action="END", now=now
            )

    def reconcile_authority(self, lease_id: str) -> KakaoManualIntent:
        """Deny expired/revoked access first; coordinator performs OS teardown afterward."""
        with self._sessions() as session, session.begin():
            row, _, binding = self._locked(session, lease_id)
            if row.phase not in {"PREPARING", "ACTIVE"}:
                return _intent(row)
            now, reason = self._now(), None
            try:
                self._authority(session, row, binding, now)
            except KakaoArchiveError as exc:
                reason = (
                    "SOURCE_REVOKED"
                    if exc.code == "KAKAO_ARCHIVE_BINDING_RETIRED"
                    else "SESSION_REVOKED"
                )
            if reason is None and (
                now >= row.absolute_expires_at
                or (row.expires_at is not None and now >= row.expires_at)
            ):
                reason = "EXPIRED"
            if reason is not None:
                row.phase, row.ended_reason, row.resource_version = (
                    "STOPPING",
                    reason,
                    row.resource_version + 1,
                )
            return _intent(row)

    def fail_session(
        self, lease_id: str, *, expected_resource_version: int, error: ManualError
    ) -> KakaoManualIntent:
        if error not in {
            "START_FAILED",
            "RUNTIME_LOST",
            "GATEWAY_START_FAILED",
            "STOP_UNCONFIRMED",
            "OWNER_UNAVAILABLE",
            "REBOOT_UNCLEAN",
        }:
            raise _error("REQUEST_INVALID")
        with self._sessions() as session, session.begin():
            row, profile, _ = self._locked(session, lease_id)
            if row.resource_version != expected_resource_version:
                raise _error("PRECONDITION_FAILED")
            row.phase, row.last_error, row.ended_reason = (
                "ERROR",
                row.last_error or error,
                row.ended_reason or "RUNTIME_FAILED",
            )
            row.resource_version += 1
            profile.mode, profile.resource_version = "ERROR", profile.resource_version + 1
            return _intent(row)

    def accept_closed(
        self, lease_id: str, *, observe_stopped: ClosureObserver
    ) -> KakaoManualIntent:
        before = self.get_intent(lease_id, require_live=False)
        observed = observe_stopped(before)
        with self._sessions() as session, session.begin():
            row, profile, _ = self._locked(session, lease_id)
            now = self._now()
            self._fresh(observed.observed_at, now)
            if row.resource_version != before.resource_version or row.phase not in {
                "STOPPING",
                "ERROR",
            }:
                raise _error("PRECONDITION_FAILED")
            if any(
                getattr(row, name) != getattr(observed, name)
                for name in (
                    "lease_id",
                    "profile_id",
                    "browser_run_id",
                    "command_sha256",
                    "fence_epoch",
                    "gateway_epoch",
                    "dispatch_boot_id",
                )
            ):
                raise _error("REMOTE_OBSERVATION_MISMATCH")
            if not (
                observed.browser_stopped
                and observed.gateway_stopped
                and observed.profile_lock_released
            ):
                raise _error("REMOTE_STOP_UNCONFIRMED")
            if (
                observed.kind != "REBOOT_UNCLEAN"
                and observed.observed_boot_id != row.dispatch_boot_id
            ):
                raise _error("REMOTE_OBSERVATION_MISMATCH")
            if observed.kind == "PRE_READY_FAILED" and row.browser_invocation_id is not None:
                raise _error("REMOTE_OBSERVATION_MISMATCH")
            if observed.kind == "REBOOT_UNCLEAN":
                row.last_error = row.last_error or "REBOOT_UNCLEAN"
            row.phase, row.closed_at, row.resource_version = "ENDED", now, row.resource_version + 1
            profile.mode, profile.current_lease_id = "STOPPED", None
            profile.resource_version += 1
            return _intent(row)
