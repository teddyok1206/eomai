"""Shared MANUAL/collection gate and observed process lifetime, guarded disposable PG only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_collection_browser import KakaoCollectionBrowserObservation
from eom_catalog_contracts.kakao_manual import KakaoManualEnd, KakaoManualStart
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_collection_browser_models import (
    KakaoCollectionBrowserRecord as Browser,
)
from eom_catalog_service.kakao_collection_browser_service import KakaoCollectionBrowserService
from eom_catalog_service.kakao_collection_models import KakaoCollectionRunRecord as Run
from eom_catalog_service.kakao_manual_models import KakaoManualSessionRecord as Lease
from eom_catalog_service.kakao_manual_models import KakaoProfileRuntimeRecord as Profile
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import create as binding_create
from tests.integration.test_kakao_capability_storage import cap as cap
from tests.integration.test_kakao_collection_storage import collection as collection
from tests.integration.test_kakao_collection_storage import create
from tests.integration.test_kakao_room_intake import h as h
from tests.integration.test_kakao_room_intake import intake as intake

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def browser(collection):
    accepted = create(collection)
    h = collection.cap.intake.h
    current = h.service.get_current_intent()
    # The synthetic clock advances past the captured file before manual closure.
    h.now = max(h.now + timedelta(seconds=1), datetime.now(UTC))
    h.service.end_session(
        h.actor,
        current.lease_id,
        KakaoManualEnd(expected_resource_version=current.resource_version),
        idempotency_key="manual-close-" + uuid4().hex,
    )
    h.service.accept_closed(current.lease_id, observe_stopped=h.close)
    return SimpleNamespace(
        collection=collection,
        accepted=accepted,
        h=h,
        service=KakaoCollectionBrowserService(
            h.engine,
            profile_id=h.profile,
            adapter_release_sha256=collection.cap.service.adapter_sha256,
            clock=lambda: h.now,
        ),
    )


def reserve(browser, observer=None):
    return browser.service.reserve_browser(
        browser.accepted.run_id, observe_profile=observer or browser.h.profile_proof
    )


def observation(browser, intent, **changes):
    values = dict(
        profile_id=intent.profile_id,
        browser_run_id=intent.browser_run_id,
        fence_epoch=intent.fence_epoch,
        command_sha256=intent.command_sha256,
        dispatch_boot_id=intent.dispatch_boot_id,
        observed_boot_id=intent.dispatch_boot_id,
        observed_at=browser.h.now,
        kind="RUNNING",
        profile_locked=True,
        gateway_stopped=True,
        invocation_id="c" * 32,
        main_pid=1234,
        started_monotonic_us=5678,
    )
    return KakaoCollectionBrowserObservation.model_validate(values | changes)


def running(browser):
    intent = reserve(browser)
    return browser.service.accept_running(
        intent.browser_run_id, observe_runtime=lambda i: observation(browser, i)
    )


def closed(browser, intent, **changes):
    values = dict(
        kind="STOPPED" if intent.browser_invocation_id else "PRE_READY_FAILED",
        profile_locked=False,
        invocation_id=intent.browser_invocation_id,
        main_pid=intent.browser_pid,
        started_monotonic_us=intent.browser_monotonic_us,
    )
    return observation(browser, intent, **(values | changes))


def test_reservation_replay_reuses_epoch_and_existing_worker_profile_contract(browser):
    first = reserve(browser)
    replay = reserve(browser, lambda: pytest.fail("replay must not probe or restart"))
    assert replay == first and first.phase == "PREPARING" and first.epoch_number == 1
    command = ProfileFence(
        schema_version="kakao-profile-fence/1.0",
        profile_id=first.profile_id,
        browser_run_id=first.browser_run_id,
        fence_epoch=first.fence_epoch,
        mode="AUTO",
    )
    assert first.command_sha256 == sha256_bytes(
        canonical_json_bytes(command.model_dump(mode="json"))
    )
    with Session(browser.h.engine) as session:
        profile = session.get(Profile, "primary")
        run = session.get(Run, first.run_id)
        assert profile.mode == "AUTO" and profile.current_lease_id is None
        assert (
            profile.current_collection_browser_run_id
            == run.current_browser_run_id
            == first.browser_run_id
        )
        assert run.state == "QUEUED"  # Browser preparation is not item/source completion.
        assert profile.fence_epoch == first.fence_epoch == 2
    state = browser.collection.service.get_status(browser.h.actor, browser.h.binding, first.run_id)
    assert state.state == "QUEUED"


def test_concurrent_reservations_have_one_profile_holder(browser):
    barrier = Barrier(3)

    def call(_):
        return reserve(browser, lambda: (barrier.wait(timeout=10), browser.h.profile_proof())[1])

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(call, range(3)))
    assert len({r.browser_run_id for r in results}) == 1
    with Session(browser.h.engine) as session:
        assert session.scalar(select(func.count()).select_from(Browser)) == 1


def test_manual_and_collection_compete_on_the_same_gate(browser):
    barrier = Barrier(2)

    def observe():
        barrier.wait(timeout=10)
        return browser.h.profile_proof()

    def automatic():
        try:
            return reserve(browser, observe)
        except KakaoArchiveError as error:
            return error.code

    def manual():
        try:
            return browser.h.service.start_session(
                browser.h.actor,
                KakaoManualStart(source_binding_id=browser.h.binding),
                idempotency_key="manual-race-" + uuid4().hex,
                observe_profile=observe,
            )
        except KakaoArchiveError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(automatic), pool.submit(manual)
        results = (a.result(timeout=20), b.result(timeout=20))
    assert sum(isinstance(r, str) for r in results) == 1
    assert "KAKAO_ARCHIVE_REMOTE_PROFILE_BUSY" in results


@pytest.mark.parametrize(
    "change",
    [
        dict(browser_stopped=False),
        dict(gateway_stopped=False),
        dict(profile_lock_released=False),
        dict(observed_at=datetime(2020, 1, 1, tzinfo=UTC)),
    ],
)
def test_unknown_or_stale_physical_closure_cannot_reserve(browser, change):
    with pytest.raises(KakaoArchiveError, match=r"PROFILE_UNAVAILABLE|OBSERVATION_STALE"):
        reserve(browser, lambda: browser.h.profile_proof(**change))
    with Session(browser.h.engine) as session:
        assert session.scalar(select(func.count()).select_from(Browser)) == 0


def test_running_observation_is_pinned_once_and_callbacks_hold_no_db_locks(browser):
    prepared = reserve(browser)

    def inspect(intent):
        with browser.h.engine.begin() as connection:
            connection.execute(text("SELECT slot_key FROM kakao_profile_runtime FOR UPDATE NOWAIT"))
        return observation(browser, intent)

    actual = browser.service.accept_running(prepared.browser_run_id, observe_runtime=inspect)
    assert actual.phase == "RUNNING" and actual.resource_version == 2
    replay = browser.service.accept_running(actual.browser_run_id, observe_runtime=inspect)
    assert replay == actual
    with pytest.raises(KakaoArchiveError, match="OBSERVATION_MISMATCH"):
        browser.service.accept_running(
            actual.browser_run_id,
            observe_runtime=lambda i: observation(browser, i, invocation_id="d" * 32),
        )


def test_same_running_result_concurrent_acceptance_is_idempotent(browser):
    prepared = reserve(browser)
    barrier = Barrier(2)

    def call(_):
        return browser.service.accept_running(
            prepared.browser_run_id,
            observe_runtime=lambda i: (barrier.wait(timeout=10), observation(browser, i))[1],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(call, range(2)))
    assert results[0] == results[1] and results[0].resource_version == 2


@pytest.mark.parametrize(
    "change",
    [
        dict(fence_epoch=99),
        dict(command_sha256="sha256:" + "f" * 64),
        dict(profile_locked=False),
        dict(gateway_stopped=False),
    ],
)
def test_unmatched_or_incomplete_running_observation_cannot_publish_ready(browser, change):
    intent = reserve(browser)
    with pytest.raises(KakaoArchiveError, match="OBSERVATION_MISMATCH"):
        browser.service.accept_running(
            intent.browser_run_id, observe_runtime=lambda i: observation(browser, i, **change)
        )
    assert browser.service.get_intent(intent.browser_run_id).phase == "PREPARING"


def test_late_authority_revocation_after_os_observation_prevents_ready(browser):
    intent = reserve(browser)

    def revoked(i):
        with Session(browser.h.engine) as session, session.begin():
            session.execute(
                update(OperatorRecord)
                .where(OperatorRecord.operator_id == browser.h.actor.operator_id)
                .values(must_change_password=True)
            )
        return observation(browser, i)

    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        browser.service.accept_running(intent.browser_run_id, observe_runtime=revoked)
    stopped = browser.service.request_stop(intent.browser_run_id, error="OWNER_UNAVAILABLE")
    result = browser.service.accept_closed(
        stopped.browser_run_id, observe_stopped=lambda i: closed(browser, i)
    )
    assert result.phase == "CLOSED" and result.last_error == "OWNER_UNAVAILABLE"


def test_unknown_stop_keeps_profile_busy_then_closure_releases_exact_epoch(browser):
    intent = running(browser)
    stop = browser.service.request_stop(intent.browser_run_id, error="RUNTIME_LOST")
    with pytest.raises(KakaoArchiveError, match="STOP_UNCONFIRMED"):
        browser.service.accept_closed(
            stop.browser_run_id, observe_stopped=lambda i: closed(browser, i, profile_locked=True)
        )
    assert browser.service.get_intent(stop.browser_run_id).phase == "STOPPING"
    with Session(browser.h.engine) as session:
        assert session.get(Profile, "primary").mode == "PAUSING"
    result = browser.service.accept_closed(
        stop.browser_run_id, observe_stopped=lambda i: closed(browser, i)
    )
    assert result.phase == "CLOSED" and result.last_error == "RUNTIME_LOST"
    with Session(browser.h.engine) as session:
        assert session.get(Profile, "primary").mode == "STOPPED"
        assert session.get(Run, intent.run_id).current_browser_run_id is None
    assert reserve(browser, lambda: pytest.fail("closed replay must not restart")) == result
    manual = browser.h.start()
    replay = browser.service.accept_closed(
        result.browser_run_id,
        observe_stopped=lambda _: pytest.fail("never stop the newer MANUAL browser"),
    )
    assert (
        replay == result
        and browser.h.service.get_session(browser.h.actor, manual.session.lease_id).phase
        == "PREPARING"
    )


def test_terminal_epoch_and_original_worker_command_are_immutable(browser):
    prepared = reserve(browser)
    stop = browser.service.request_stop(prepared.browser_run_id, error="START_FAILED")
    result = browser.service.accept_closed(
        stop.browser_run_id, observe_stopped=lambda i: closed(browser, i)
    )
    with pytest.raises(DBAPIError), Session(browser.h.engine) as session, session.begin():
        session.execute(
            update(Browser)
            .where(Browser.browser_run_id == result.browser_run_id)
            .values(phase="RUNNING", resource_version=result.resource_version + 1)
        )
    assert browser.service.get_intent(prepared.browser_run_id) == result


def test_unclean_start_exit_is_recorded_even_without_prior_owner_error(browser):
    prepared = reserve(browser)
    stop = browser.service.request_stop(prepared.browser_run_id)
    result = browser.service.accept_closed(
        stop.browser_run_id,
        observe_stopped=lambda i: closed(browser, i, runtime_error="START_FAILED"),
    )
    assert result.phase == "CLOSED" and result.last_error == "START_FAILED"
    assert (
        reserve(browser, lambda: pytest.fail("failure must not become retry")).browser_run_id
        == result.browser_run_id
    )


def test_timeout_does_not_release_the_profile_or_allocate_a_new_epoch(browser):
    intent = running(browser)
    browser.service.request_stop(intent.browser_run_id)

    def timeout(_):
        raise TimeoutError("synthetic observation timeout")

    with pytest.raises(TimeoutError):
        browser.service.accept_closed(intent.browser_run_id, observe_stopped=timeout)
    assert browser.service.get_intent(intent.browser_run_id).phase == "STOPPING"
    with pytest.raises(KakaoArchiveError, match="PROFILE_BUSY"):
        browser.h.start()
    assert (
        reserve(browser, lambda: pytest.fail("unknown dispatch is not a new run")).browser_run_id
        == intent.browser_run_id
    )


@pytest.mark.parametrize("active", [True, False])
def test_database_channel_switch_needs_a_closed_profile_and_a_new_fence(browser, active):
    other = binding_create(KakaoArchiveService(browser.h.engine), browser.h.actor).binding
    if active:
        browser.h.start()
    with pytest.raises(DBAPIError), Session(browser.h.engine) as session, session.begin():
        profile = session.get(Profile, "primary")
        session.execute(
            update(Profile)
            .where(Profile.slot_key == "primary")
            .values(
                source_binding_id=other.source_binding_id,
                fence_epoch=profile.fence_epoch + 1 if active else profile.fence_epoch,
            )
        )


def test_same_owner_may_switch_closed_profile_without_rewriting_old_manual_history(browser):
    old = browser.collection.cap.intake.current
    other = binding_create(KakaoArchiveService(browser.h.engine), browser.h.actor).binding
    changed = browser.h.service.start_session(
        browser.h.actor,
        KakaoManualStart(source_binding_id=other.source_binding_id),
        idempotency_key="another-binding-" + uuid4().hex,
        observe_profile=browser.h.profile_proof,
    )
    current = browser.h.service.get_current_intent()
    prior = browser.h.service.get_predecessor_intent(current, fence_epoch=old.fence_epoch)
    assert prior.source_binding_id == old.source_binding_id
    assert prior.phase == "ENDED" and current.source_binding_id == other.source_binding_id
    with Session(browser.h.engine) as session:
        assert session.get(Lease, old.lease_id).source_binding_id == browser.h.binding
        assert session.get(Profile, "primary").source_binding_id == other.source_binding_id
    assert changed.session.lease_id != old.lease_id
