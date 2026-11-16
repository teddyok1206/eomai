"""Real guarded disposable PostgreSQL only; all runtime observations are synthetic."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire
from eom_catalog_contracts.kakao_manual import (
    KakaoManualClosureObservation,
    KakaoManualEnd,
    KakaoManualFreshProfile,
    KakaoManualIntent,
    KakaoManualRenew,
    KakaoManualRuntimeObservation,
    KakaoManualStart,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_manual_models import (
    KakaoManualSessionRecord,
    KakaoProfileRuntimeRecord,
    KakaoRemoteCommandRecord,
)
from eom_catalog_service.kakao_manual_service import KakaoManualService, manual_gateway_grant
from eom_identity_service.models import ApiSessionRecord
from eom_operator_identity.contracts import ActorContext
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import create, make_actor

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
BOOT = "12345678-1234-1234-1234-123456789abc"


@dataclass
class Harness:
    engine: Engine
    service: KakaoManualService
    actor: ActorContext
    binding: str
    profile: str
    now: datetime

    def profile_proof(self, **changes: object) -> KakaoManualFreshProfile:
        return KakaoManualFreshProfile.model_validate(
            dict(
                profile_id=self.profile,
                observed_at=self.now,
                boot_id=BOOT,
                never_used=True,
                profile_empty=True,
                browser_stopped=True,
                gateway_stopped=True,
                profile_lock_released=True,
            )
            | changes
        )

    def start(self, *, key: str | None = None):
        return self.service.start_session(
            self.actor,
            KakaoManualStart(source_binding_id=self.binding),
            idempotency_key=key or "manual-start-" + uuid4().hex,
            observe_profile=self.profile_proof,
        )

    def observe(self, item: KakaoManualIntent, *, gateway: bool, **changes: object):
        fields = item.model_dump(
            include={
                "lease_id",
                "profile_id",
                "browser_run_id",
                "command_sha256",
                "fence_epoch",
                "gateway_epoch",
            }
        )
        fields.update(
            observed_at=self.now,
            boot_id=BOOT,
            invocation_id="a" * 32,
            main_pid=100,
            started_monotonic_us=1000,
            browser_running=True,
            profile_locked=True,
            gateway_running=gateway,
            gateway_invocation_id="b" * 32 if gateway else None,
        )
        fields.update(changes)
        return KakaoManualRuntimeObservation.model_validate(fields)

    def ready(self) -> KakaoManualIntent:
        lease = self.start().session.lease_id
        prepared = self.service.prepare_gateway(
            lease, observe_browser=lambda i: self.observe(i, gateway=False)
        )
        assert not self.service.get_session(self.actor, lease).ready
        assert manual_gateway_grant(prepared).grant_revision == 1
        return self.service.accept_ready(
            lease, observe_runtime=lambda i: self.observe(i, gateway=True)
        )

    def close(self, item: KakaoManualIntent, **changes: object):
        pins = item.model_dump(
            include={
                "lease_id",
                "profile_id",
                "browser_run_id",
                "command_sha256",
                "fence_epoch",
                "gateway_epoch",
                "dispatch_boot_id",
            }
        )
        return KakaoManualClosureObservation.model_validate(
            pins
            | dict(
                observed_at=self.now,
                kind="STOPPED",
                observed_boot_id=BOOT,
                browser_stopped=True,
                gateway_stopped=True,
                profile_lock_released=True,
            )
            | changes
        )


@pytest.fixture
def h(creative_engine: Engine):
    # One installed profile is intentionally global. Isolate only these new test-owned tables.
    def clear() -> None:
        with creative_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE kakao_remote_commands, kakao_manual_sessions, kakao_profile_runtime, "
                    "kakao_collection_browsers, kakao_collection_runs, kakao_collection_tasks"
                )
            )

    clear()
    actor = make_actor(creative_engine)
    binding = create(KakaoArchiveService(creative_engine), actor).binding.source_binding_id
    profile = "kakaoprofile_" + uuid4().hex
    item = Harness(
        creative_engine,
        KakaoManualService(creative_engine, profile_id=profile),
        actor,
        binding,
        profile,
        datetime.now(UTC),
    )
    item.service = KakaoManualService(creative_engine, profile_id=profile, clock=lambda: item.now)
    try:
        yield item
    finally:
        clear()


def test_draft_start_is_not_ready_or_channel_verification_and_replays_without_observation(
    h: Harness,
) -> None:
    key = "manual-start-" + uuid4().hex
    first = h.start(key=key)
    assert first.session.phase == "PREPARING" and not first.session.ready
    assert first.session.expires_at is None and first.session.grant_revision == 0
    again = h.service.start_session(
        h.actor,
        KakaoManualStart(source_binding_id=h.binding),
        idempotency_key=key,
        observe_profile=lambda: pytest.fail("replay invoked runtime"),
    )
    assert again.replayed and again.session == first.session
    assert KakaoArchiveService(h.engine).get_binding(h.actor, h.binding).state == "DRAFT"


@pytest.mark.parametrize(
    "field",
    ["never_used", "profile_empty", "browser_stopped", "gateway_stopped", "profile_lock_released"],
)
def test_initial_profile_requires_real_empty_closed_proof(h: Harness, field: str) -> None:
    with pytest.raises(KakaoArchiveError, match="REMOTE_PROFILE"):
        h.service.start_session(
            h.actor,
            KakaoManualStart(source_binding_id=h.binding),
            idempotency_key="manual-start-" + uuid4().hex,
            observe_profile=lambda: h.profile_proof(**{field: False}),
        )
    with Session(h.engine) as session:
        assert session.scalar(select(func.count()).select_from(KakaoManualSessionRecord)) == 0


def test_start_observation_stale_or_future_denied(h: Harness) -> None:
    for offset in (-6, 1):
        with pytest.raises(KakaoArchiveError, match="OBSERVATION_STALE"):
            h.service.start_session(
                h.actor,
                KakaoManualStart(source_binding_id=h.binding),
                idempotency_key="manual-start-" + uuid4().hex,
                observe_profile=lambda offset=offset: h.profile_proof(
                    observed_at=h.now + timedelta(seconds=offset)
                ),
            )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_start_one_holder(h: Harness, same_key: bool) -> None:
    barrier = Barrier(2)
    key = "manual-start-" + uuid4().hex

    def run(index: int):
        try:
            return h.service.start_session(
                h.actor,
                KakaoManualStart(source_binding_id=h.binding),
                idempotency_key=key if same_key else key + str(index),
                observe_profile=lambda: (barrier.wait(timeout=10), h.profile_proof())[1],
            )
        except KakaoArchiveError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    with Session(h.engine) as session:
        assert session.scalar(select(func.count()).select_from(KakaoManualSessionRecord)) == 1
    if same_key:
        assert sum(result.replayed for result in results) == 1
    else:
        assert "KAKAO_ARCHIVE_REMOTE_PROFILE_BUSY" in results


def test_runtime_callbacks_are_outside_db_locks_and_ready_requires_gateway(h: Harness) -> None:
    lease = h.start().session.lease_id

    def observe(item: KakaoManualIntent):
        with h.engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            connection.execute(text("SELECT slot_key FROM kakao_profile_runtime FOR UPDATE NOWAIT"))
        return h.observe(item, gateway=False)

    prepared = h.service.prepare_gateway(lease, observe_browser=observe)
    assert prepared.phase == "PREPARING" and prepared.grant_revision == 1
    with pytest.raises(KakaoArchiveError, match="RUNTIME_UNAVAILABLE"):
        h.service.accept_ready(lease, observe_runtime=observe)
    result = h.service.accept_ready(
        lease, observe_runtime=lambda item: h.observe(item, gateway=True)
    )
    assert result.phase == "ACTIVE" and h.service.get_session(h.actor, lease).ready


def test_browser_boot_and_invocation_pins_must_match(h: Harness) -> None:
    lease = h.start().session.lease_id
    with pytest.raises(KakaoArchiveError, match="OBSERVATION_MISMATCH"):
        h.service.prepare_gateway(
            lease, observe_browser=lambda i: h.observe(i, gateway=False, boot_id=str(uuid4()))
        )
    h.service.prepare_gateway(lease, observe_browser=lambda i: h.observe(i, gateway=False))
    with pytest.raises(KakaoArchiveError, match="OBSERVATION_MISMATCH"):
        h.service.accept_ready(
            lease, observe_runtime=lambda i: h.observe(i, gateway=True, invocation_id="c" * 32)
        )


def test_renewal_replay_does_not_extend_ttl_or_reobserve(h: Harness) -> None:
    item = h.ready()
    h.now += timedelta(seconds=10)
    key = "manual-renew-" + uuid4().hex
    command = KakaoManualRenew(expected_grant_revision=1)
    first = h.service.renew_session(
        h.actor,
        item.lease_id,
        command,
        idempotency_key=key,
        observe_runtime=lambda i: h.observe(i, gateway=True),
    )
    h.now += timedelta(seconds=5)
    again = h.service.renew_session(
        h.actor,
        item.lease_id,
        command,
        idempotency_key=key,
        observe_runtime=lambda _: pytest.fail("renew replay invoked runtime"),
    )
    assert again.replayed and again.session == first.session
    assert first.session.expires_at == h.now + timedelta(seconds=25)
    assert first.session.absolute_expires_at == item.absolute_expires_at
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        h.service.renew_session(
            h.actor,
            item.lease_id,
            KakaoManualRenew(expected_grant_revision=2),
            idempotency_key=key,
            observe_runtime=lambda _: pytest.fail("conflict invoked runtime"),
        )


def test_competing_renewals_one_cas(h: Harness) -> None:
    item = h.ready()
    barrier = Barrier(2)

    def run(index: int):
        try:
            return h.service.renew_session(
                h.actor,
                item.lease_id,
                KakaoManualRenew(expected_grant_revision=1),
                idempotency_key="manual-renew-" + uuid4().hex,
                observe_runtime=lambda i: (barrier.wait(timeout=10), h.observe(i, gateway=True))[1],
            )
        except KakaoArchiveError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results.count("KAKAO_ARCHIVE_PRECONDITION_FAILED") == 1
    assert h.service.get_session(h.actor, item.lease_id).grant_revision == 2


def test_expiry_revokes_before_release_and_never_reopens_expired_grant(h: Harness) -> None:
    item = h.ready()
    h.now += timedelta(seconds=31)
    assert not h.service.get_session(h.actor, item.lease_id).ready
    with pytest.raises(KakaoArchiveError, match="LEASE_EXPIRED"):
        h.service.renew_session(
            h.actor,
            item.lease_id,
            KakaoManualRenew(expected_grant_revision=1),
            idempotency_key="manual-renew-" + uuid4().hex,
            observe_runtime=lambda i: h.observe(i, gateway=True),
        )
    stopped = h.service.reconcile_authority(item.lease_id)
    assert stopped.phase == "STOPPING"
    with pytest.raises(KakaoArchiveError, match="PROFILE_BUSY"):
        h.start()
    closed = h.service.accept_closed(item.lease_id, observe_stopped=h.close)
    assert closed.phase == "ENDED"
    successor = h.start().session
    assert h.service.get_intent(successor.lease_id).fence_epoch == item.fence_epoch + 1


def test_revoked_identity_session_is_checked_by_background_without_fake_actor(h: Harness) -> None:
    item = h.ready()
    with Session(h.engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == h.actor.session_id)
            .values(revoked_at=h.now)
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        h.service.get_session(h.actor, item.lease_id)
    assert h.service.reconcile_authority(item.lease_id).phase == "STOPPING"
    assert h.service.accept_closed(item.lease_id, observe_stopped=h.close).phase == "ENDED"


def test_retired_binding_denies_ready_and_background_reconciles(h: Harness) -> None:
    lease = h.start().session.lease_id
    service = KakaoArchiveService(h.engine)
    binding = service.get_binding(h.actor, h.binding)
    service.command_binding(
        h.actor,
        h.binding,
        KakaoBindingRetire(
            expected_resource_version=binding.resource_version,
            parent_policy_revision_id=binding.policy_revision.policy_revision_id,
        ),
        idempotency_key="binding-retire-" + uuid4().hex,
    )
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        h.service.prepare_gateway(lease, observe_browser=lambda i: h.observe(i, gateway=False))
    assert h.service.reconcile_authority(lease).phase == "STOPPING"


def test_failed_start_requires_positive_closure_and_preserves_failure(h: Harness) -> None:
    lease = h.start().session.lease_id
    failed = h.service.fail_session(lease, expected_resource_version=1, error="START_FAILED")
    with pytest.raises(KakaoArchiveError, match="STOP_UNCONFIRMED"):
        h.service.accept_closed(
            lease, observe_stopped=lambda i: h.close(i, profile_lock_released=False)
        )
    with pytest.raises(KakaoArchiveError, match="PROFILE_BUSY"):
        h.start()
    closed = h.service.accept_closed(
        lease, observe_stopped=lambda i: h.close(i, kind="PRE_READY_FAILED")
    )
    assert closed.phase == "ENDED"
    assert h.service.get_session(h.actor, lease).last_error == "START_FAILED"
    assert failed.resource_version == 2


def test_reboot_closed_dispatch_retains_error_and_changes_fence(h: Harness) -> None:
    item = h.start().session
    h.service.fail_session(item.lease_id, expected_resource_version=1, error="REBOOT_UNCLEAN")
    closed = h.service.accept_closed(
        item.lease_id,
        observe_stopped=lambda i: h.close(i, kind="REBOOT_UNCLEAN", observed_boot_id=str(uuid4())),
    )
    assert closed.phase == "ENDED"
    assert h.service.get_session(h.actor, item.lease_id).last_error == "REBOOT_UNCLEAN"


def test_other_owner_cannot_adopt_used_profile_even_after_stop(h: Harness) -> None:
    item = h.start().session
    h.service.end_session(
        h.actor,
        item.lease_id,
        KakaoManualEnd(expected_resource_version=1),
        idempotency_key="manual-end-" + uuid4().hex,
    )
    h.service.accept_closed(item.lease_id, observe_stopped=h.close)
    other = make_actor(h.engine)
    binding = create(KakaoArchiveService(h.engine), other).binding.source_binding_id
    with pytest.raises(KakaoArchiveError, match="PROFILE_UNAVAILABLE"):
        h.service.start_session(
            other,
            KakaoManualStart(source_binding_id=binding),
            idempotency_key="manual-start-" + uuid4().hex,
            observe_profile=h.profile_proof,
        )
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        h.service.get_session(other, item.lease_id)


def test_old_end_replay_cannot_stop_successor(h: Harness) -> None:
    original = h.start().session
    command, key = KakaoManualEnd(expected_resource_version=1), "manual-end-" + uuid4().hex
    first = h.service.end_session(h.actor, original.lease_id, command, idempotency_key=key)
    h.service.accept_closed(original.lease_id, observe_stopped=h.close)
    new = h.start().session
    replay = h.service.end_session(h.actor, original.lease_id, command, idempotency_key=key)
    assert replay.replayed and replay.session == first.session
    assert h.service.get_intent(new.lease_id).phase == "PREPARING"


def test_immutable_identity_and_receipts_reject_direct_rewrite(h: Harness) -> None:
    item = h.start().session
    for model, values in [
        (KakaoManualSessionRecord, {"dispatch_boot_id": str(uuid4())}),
        (KakaoProfileRuntimeRecord, {"created_at": h.now + timedelta(seconds=1)}),
        (KakaoRemoteCommandRecord, {"result_version": 99}),
    ]:
        with pytest.raises(DBAPIError), Session(h.engine) as session, session.begin():
            session.execute(update(model).values(**values))
    assert h.service.get_session(h.actor, item.lease_id).resource_version == 1


def test_metadata_has_no_large_payloads_or_duplicate_profile_indexes() -> None:
    for model in (KakaoManualSessionRecord, KakaoProfileRuntimeRecord, KakaoRemoteCommandRecord):
        assert not any(
            type(c.type).__name__ in {"JSON", "JSONB", "LargeBinary", "Text"}
            for c in model.__table__.columns
        )
    assert not KakaoProfileRuntimeRecord.__table__.indexes


def test_expired_http_session_cannot_start_or_run_observer(h: Harness) -> None:
    with Session(h.engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == h.actor.session_id)
            .values(idle_expires_at=h.now - timedelta(seconds=1))
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        h.service.start_session(
            h.actor,
            KakaoManualStart(source_binding_id=h.binding),
            idempotency_key="manual-start-" + uuid4().hex,
            observe_profile=lambda: pytest.fail("unauthenticated observer"),
        )


def test_same_owner_other_identity_session_cannot_replay_lease(h: Harness) -> None:
    first = h.start(key="manual-start-identity-session")
    with Session(h.engine) as session, session.begin():
        old = session.get(ApiSessionRecord, h.actor.session_id)
        assert old is not None
        new_id = "apisession_" + uuid4().hex
        session.add(
            ApiSessionRecord(
                api_session_id=new_id,
                operator_id=old.operator_id,
                token_family_id="tokenfamily_" + uuid4().hex,
                client_name="other synthetic browser",
                authenticated_at=h.now,
                created_at=h.now,
                last_seen_at=h.now,
                absolute_expires_at=h.now + timedelta(hours=1),
                idle_expires_at=h.now + timedelta(hours=1),
            )
        )
    other_session = h.actor.model_copy(update={"session_id": new_id})
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        h.service.get_session(other_session, first.session.lease_id)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        h.service.start_session(
            other_session,
            KakaoManualStart(source_binding_id=h.binding),
            idempotency_key="manual-start-identity-session",
            observe_profile=h.profile_proof,
        )


def test_live_intent_cannot_ignore_durable_profile_mode(h: Harness) -> None:
    item = h.ready()
    with Session(h.engine) as session, session.begin():
        session.execute(update(KakaoProfileRuntimeRecord).values(mode="PAUSING"))
    with pytest.raises(KakaoArchiveError, match="FENCE_STALE"):
        h.service.get_intent(item.lease_id)
    # Cleanup observation remains available; changing mode is not physical closure.
    assert h.service.get_intent(item.lease_id, require_live=False).lease_id == item.lease_id


def test_proxy_admission_is_read_only_and_observer_has_no_db_lock(h: Harness) -> None:
    item = h.ready()

    def observe(intent):
        with h.engine.begin() as connection:
            connection.execute(text("SELECT slot_key FROM kakao_profile_runtime FOR UPDATE NOWAIT"))
        return h.observe(intent, gateway=True)

    result = h.service.authorize_session(h.actor, item.lease_id, observe_runtime=observe)
    assert result.ready and result.resource_version == item.resource_version
    assert h.service.get_intent(item.lease_id) == item


def test_proxy_admission_rechecks_authority_after_runtime_probe(h: Harness) -> None:
    item = h.ready()

    def observe(intent):
        with Session(h.engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == h.actor.session_id)
                .values(revoked_at=h.now)
            )
        return h.observe(intent, gateway=True)

    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        h.service.authorize_session(h.actor, item.lease_id, observe_runtime=observe)


def test_proxy_admission_fails_if_end_occurs_during_probe(h: Harness) -> None:
    item = h.ready()

    def observe(intent):
        h.service.end_session(
            h.actor,
            item.lease_id,
            KakaoManualEnd(expected_resource_version=item.resource_version),
            idempotency_key="end-during-probe-" + uuid4().hex,
        )
        return h.observe(intent, gateway=True)

    with pytest.raises(KakaoArchiveError, match=r"LEASE_EXPIRED|PRECONDITION_FAILED"):
        h.service.authorize_session(h.actor, item.lease_id, observe_runtime=observe)


def test_history_read_is_not_proxy_admission(h: Harness) -> None:
    item = h.start().session
    assert h.service.get_session(h.actor, item.lease_id).phase == "PREPARING"
    with pytest.raises(KakaoArchiveError, match="NOT_READY"):
        h.service.authorize_session(
            h.actor,
            item.lease_id,
            observe_runtime=lambda _: pytest.fail("pending session runtime probe"),
        )
    assert h.service.get_current_intent().lease_id == item.lease_id


def test_exact_predecessor_lookup_preserves_failed_record(h: Harness) -> None:
    first = h.start().session
    h.service.fail_session(first.lease_id, expected_resource_version=1, error="START_FAILED")
    h.service.accept_closed(
        first.lease_id, observe_stopped=lambda i: h.close(i, kind="PRE_READY_FAILED")
    )
    assert h.service.get_current_intent() is None
    current = h.service.get_intent(h.start().session.lease_id)
    old = h.service.get_predecessor_intent(current)
    assert old.lease_id == first.lease_id and old.phase == "ENDED"
    with pytest.raises(KakaoArchiveError, match="FENCE_STALE"):
        h.service.get_predecessor_intent(current, fence_epoch=current.fence_epoch)
