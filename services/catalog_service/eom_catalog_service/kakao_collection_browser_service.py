"""Reserve/observe/close browser lifetimes through the existing shared profile gate.

This does not activate a collector, issue a capture command or admit source bytes.
Runtime callbacks are trusted composition-owned OS observers, never worker/user input.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from eom_catalog_contracts.kakao_collection_browser import (
    BrowserError,
)
from eom_catalog_contracts.kakao_collection_browser import (
    KakaoCollectionBrowserIntent as Intent,
)
from eom_catalog_contracts.kakao_collection_browser import (
    KakaoCollectionBrowserObservation as Observation,
)
from eom_catalog_contracts.kakao_manual import KakaoManualFreshProfile
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_collection_attempt_models import KakaoCollectionAttemptRecord as Attempt
from .kakao_collection_authorization import (
    authorize_kakao_collection_preparation,
    lock_kakao_collection_browser,
    lock_kakao_collection_profile_gate,
)
from .kakao_collection_browser_models import KakaoCollectionBrowserRecord as Browser
from .kakao_collection_models import KakaoCollectionRunRecord as Run
from .kakao_collection_models import KakaoCollectionTaskRecord as Task
from .kakao_manual_models import KakaoProfileRuntimeRecord as Profile

_TERMINAL = frozenset({"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"})
_PINS = ("profile_id", "browser_run_id", "fence_epoch", "command_sha256", "dispatch_boot_id")


def _intent(row: Browser) -> Intent:
    return Intent.model_validate(
        {name: getattr(row, name) for name in Intent.model_fields if name != "schema_version"}
    )


def _profile_command(profile: str, browser: str, epoch: int) -> dict[str, object]:
    # This is the existing worker ProfileFence, not a second command identity.
    return dict(
        schema_version="kakao-profile-fence/1.0",
        profile_id=profile,
        browser_run_id=browser,
        fence_epoch=epoch,
        mode="AUTO",
    )


class KakaoCollectionBrowserService:
    def __init__(
        self,
        engine: Engine,
        *,
        profile_id: str,
        adapter_release_sha256: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (
            re.fullmatch(r"kakaoprofile_[0-9a-f]{32}", profile_id) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", adapter_release_sha256) is None
        ):
            raise ValueError("KAKAO_ARCHIVE_COLLECTION_RUNTIME_CONFIGURATION_INVALID")
        self._sessions = build_session_factory(engine)
        self.profile_id, self.adapter_sha256, self.clock = profile_id, adapter_release_sha256, clock

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        return value

    def _fresh(self, observed: datetime) -> None:
        if not timedelta(0) <= self._now() - observed <= timedelta(seconds=5):
            raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_OBSERVATION_STALE")

    def _authorize(self, session: Session, run: Run) -> None:
        authorize_kakao_collection_preparation(
            session, run, adapter_release_sha256=self.adapter_sha256
        )

    @staticmethod
    def _binding_gate(session: Session, run: Run) -> None:
        lock_kakao_collection_profile_gate(session, run)

    def _profile(self, session: Session) -> Profile:
        row = session.scalar(select(Profile).where(Profile.slot_key == "primary").with_for_update())
        if row is None or row.profile_id != self.profile_id:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REMOTE_PROFILE_UNAVAILABLE")
        return row

    def _locked(self, session: Session, browser: str) -> tuple[Browser, Profile, Run]:
        row, profile, run = lock_kakao_collection_browser(
            session, browser, profile_id=self.profile_id
        )
        if (
            profile.current_lease_id is not None
            or profile.current_collection_browser_run_id != browser
            or profile.fence_epoch != row.fence_epoch
            or profile.owner_operator_id != row.owner_operator_id
            or profile.source_binding_id != row.source_binding_id
            or run.current_browser_run_id != browser
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_FENCE_STALE")
        return row, profile, run

    def get_intent(self, browser: str) -> Intent:
        """Internal exact metadata for cleanup too; not a public authorization alternative."""
        with self._sessions.begin() as session:
            row = session.get(Browser, browser)
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            return _intent(row)

    def assert_current_start(self, intent: Intent) -> None:
        """Final Catalog fence check outside any OS wait or file materialization."""
        with self._sessions.begin() as session:
            row, profile, run = self._locked(session, intent.browser_run_id)
            self._authorize(session, run)
            if (
                _intent(row) != intent
                or intent.phase != "PREPARING"
                or profile.mode != "AUTO"
                or run.state != "QUEUED"
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

    def reserve_browser(
        self, run_id: str, *, observe_profile: Callable[[], KakaoManualFreshProfile]
    ) -> Intent:
        with self._sessions.begin() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            self._authorize(session, run)
            # A retained closed/unknown dispatch does not become a fresh start on
            # replay. Supported capture retry must explicitly own its successor.
            prior = session.scalar(
                select(Browser)
                .where(Browser.run_id == run_id)
                .order_by(Browser.epoch_number.desc())
                .limit(1)
            )
            if prior is not None:
                return _intent(prior)
        observed = KakaoManualFreshProfile.model_validate(observe_profile().model_dump(mode="json"))
        with self._sessions.begin() as session:
            seed = session.get(Run, run_id)
            if seed is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            self._binding_gate(session, seed)
            profile = self._profile(session)
            run = session.scalar(
                select(Run)
                .where(Run.run_id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert run is not None
            self._authorize(session, run)
            prior = session.scalar(
                select(Browser)
                .where(Browser.run_id == run_id)
                .order_by(Browser.epoch_number.desc())
                .limit(1)
            )
            if prior is not None:
                return _intent(prior)
            self._fresh(observed.observed_at)
            if (
                observed.profile_id != self.profile_id
                or not observed.browser_stopped
                or not observed.gateway_stopped
                or not observed.profile_lock_released
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_REMOTE_PROFILE_UNAVAILABLE")
            if profile.owner_operator_id != run.owner_operator_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_REMOTE_PROFILE_UNAVAILABLE")
            if (
                profile.mode != "STOPPED"
                or profile.current_lease_id is not None
                or profile.current_collection_browser_run_id is not None
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_REMOTE_PROFILE_BUSY")
            if run.state != "QUEUED":
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            if profile.fence_epoch >= 2147483647:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_FENCE_EXHAUSTED")
            fence, browser = profile.fence_epoch + 1, "kakaobrowserrun_" + uuid4().hex
            now = self._now()
            row = Browser(
                browser_run_id=browser,
                run_id=run.run_id,
                owner_operator_id=run.owner_operator_id,
                source_binding_id=run.source_binding_id,
                profile_id=profile.profile_id,
                fence_epoch=fence,
                epoch_number=1,
                command_sha256=sha256_bytes(
                    canonical_json_bytes(_profile_command(self.profile_id, browser, fence))
                ),
                dispatch_boot_id=observed.boot_id,
                phase="PREPARING",
                resource_version=1,
                created_at=now,
            )
            session.add(row)
            profile.source_binding_id = run.source_binding_id
            profile.mode, profile.current_collection_browser_run_id = "AUTO", browser
            profile.fence_epoch, profile.resource_version = fence, profile.resource_version + 1
            run.current_browser_run_id = browser
            run.resource_version, run.updated_at = run.resource_version + 1, now
            session.flush()
            return _intent(row)

    def accept_running(
        self, browser: str, *, observe_runtime: Callable[[Intent], Observation]
    ) -> Intent:
        with self._sessions.begin() as session:
            row, profile, run = self._locked(session, browser)
            self._authorize(session, run)
            before = _intent(row)
            if before.phase not in {"PREPARING", "RUNNING"} or profile.mode != "AUTO":
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        observed = Observation.model_validate(observe_runtime(before).model_dump(mode="json"))
        with self._sessions.begin() as session:
            row, profile, run = self._locked(session, browser)
            self._authorize(session, run)
            self._match(before, observed)
            if (
                observed.kind != "RUNNING"
                or profile.mode != "AUTO"
                or not observed.profile_locked
                or not observed.gateway_stopped
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_OBSERVATION_MISMATCH")
            handle = (observed.invocation_id, observed.main_pid, observed.started_monotonic_us)
            if row.phase == "RUNNING" and row.browser_invocation_id is not None:
                if handle != (row.browser_invocation_id, row.browser_pid, row.browser_monotonic_us):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_OBSERVATION_MISMATCH")
                return _intent(row)
            if row.resource_version != before.resource_version or row.phase != "PREPARING":
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            row.phase, row.resource_version = "RUNNING", row.resource_version + 1
            row.browser_invocation_id, row.browser_pid, row.browser_monotonic_us = handle
            row.browser_observed_at = observed.observed_at
            session.flush()
            return _intent(row)

    def _match(self, before: Intent, observed: Observation) -> None:
        self._fresh(observed.observed_at)
        if observed.observed_at < before.created_at or any(
            getattr(before, field) != getattr(observed, field) for field in _PINS
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_OBSERVATION_MISMATCH")

    def request_stop(self, browser: str, *, error: BrowserError | None = None) -> Intent:
        if error not in {
            None,
            "START_FAILED",
            "RUNTIME_LOST",
            "OWNER_UNAVAILABLE",
            "REBOOT_UNCLEAN",
        }:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        before = self.get_intent(browser)
        if before.phase == "CLOSED":
            return before
        with self._sessions.begin() as session:
            row, profile, _ = self._locked(session, browser)
            if row.phase == "STOPPING":
                return _intent(row)
            row.phase, row.resource_version = "STOPPING", row.resource_version + 1
            row.last_error = row.last_error or error
            profile.mode, profile.resource_version = "PAUSING", profile.resource_version + 1
            session.flush()
            return _intent(row)

    def record_missing_one_room_output(self, browser: str) -> None:
        """Record confirmed closure without output; never overwrite a worker result."""
        with self._sessions.begin() as session:
            row, _, run = lock_kakao_collection_browser(
                session, browser, profile_id=self.profile_id
            )
            if row.phase != "CLOSED" or run.current_browser_run_id is not None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_STOP_UNCONFIRMED")
            if run.state == "FAILED":
                return
            self._authorize(session, run)
            tasks = tuple(
                session.scalars(
                    select(Task)
                    .where(Task.run_id == run.run_id)
                    .order_by(Task.ordinal)
                    .limit(2)
                    .with_for_update()
                )
            )
            if (
                run.state not in {"QUEUED", "COLLECTING"}
                or len(tasks) != 1
                or tasks[0].room_id != run.anchor_room_id
                or tasks[0].state not in {"QUEUED", "RUNNING"}
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            attempt = session.scalar(select(Attempt).where(Attempt.task_id == tasks[0].task_id))
            if attempt is not None and (
                attempt.browser_run_id != browser or attempt.state == "RESULT_ACCEPTED"
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            tasks[0].state, run.state = "FAILED", "FAILED"
            run.updated_at, run.resource_version = self._now(), run.resource_version + 1

    def accept_closed(
        self, browser: str, *, observe_stopped: Callable[[Intent], Observation]
    ) -> Intent:
        before = self.get_intent(browser)
        if before.phase == "CLOSED":
            return before
        if before.phase != "STOPPING":
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        observed = Observation.model_validate(observe_stopped(before).model_dump(mode="json"))
        with self._sessions.begin() as session:
            # A concurrent closure may already have returned this profile to
            # MANUAL. Replay must not inspect/stop that newer process.
            existing = session.get(Browser, browser)
            if existing is not None and existing.phase == "CLOSED":
                return _intent(existing)
            row, profile, run = self._locked(session, browser)
            self._match(before, observed)
            if (
                row.resource_version != before.resource_version
                or profile.mode not in {"PAUSING", "ERROR"}
                or observed.kind == "RUNNING"
                or observed.profile_locked
                or not observed.gateway_stopped
                or (observed.kind == "STOPPED" and before.browser_invocation_id is None)
                or (
                    observed.kind == "PRE_READY_FAILED" and before.browser_invocation_id is not None
                )
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_STOP_UNCONFIRMED")
            if before.browser_invocation_id is not None and (
                observed.invocation_id,
                observed.main_pid,
                observed.started_monotonic_us,
            ) != (before.browser_invocation_id, before.browser_pid, before.browser_monotonic_us):
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_OBSERVATION_MISMATCH")
            now = self._now()
            row.phase, row.closed_at, row.close_kind = "CLOSED", now, observed.kind
            row.resource_version += 1
            row.last_error = row.last_error or observed.runtime_error
            if observed.kind == "REBOOT_UNCLEAN":
                row.last_error = row.last_error or "REBOOT_UNCLEAN"
            profile.mode, profile.current_collection_browser_run_id = "STOPPED", None
            profile.resource_version += 1
            if run.state not in _TERMINAL:
                run.current_browser_run_id = None
                run.resource_version, run.updated_at = run.resource_version + 1, now
            session.flush()
            return _intent(row)
