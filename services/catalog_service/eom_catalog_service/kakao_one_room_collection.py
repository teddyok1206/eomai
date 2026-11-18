"""Trusted composition for one accepted room; no new queue, profile or source owner."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.kakao_collection_attempt import KakaoCollectionAttempt
from eom_catalog_contracts.kakao_manual import KakaoManualFreshProfile
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.kakao_capture_inputs import KakaoCaptureInputError, KakaoCaptureOutputReader
from eom_orchestrator.kakao_collection_browser_runtime import (
    FixedKakaoCollectionBrowserRuntime,
    KakaoCollectionBrowserRuntimeError,
    collection_profile_fence,
)
from sqlalchemy import Engine

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_browser_history import closed_kakao_browser_pin
from .kakao_collection_attempt_service import KakaoCollectionAttemptService
from .kakao_collection_browser_service import KakaoCollectionBrowserService
from .kakao_collection_input_publication import PreparedKakaoRoom, prepare_kakao_registered_room
from .kakao_collection_service import KakaoCollectionService
from .kakao_collection_source_composition import (
    admit_staged_kakao_open_room,
    dispatch_staged_kakao_open_room,
)
from .kakao_source_service import AcceptedKakaoSource


@dataclass(frozen=True, slots=True)
class KakaoOneRoomCollection:
    engine: Engine = field(repr=False)
    collections: KakaoCollectionService
    browsers: KakaoCollectionBrowserService
    attempts: KakaoCollectionAttemptService
    runtime: FixedKakaoCollectionBrowserRuntime
    observe_profile: Callable[[], KakaoManualFreshProfile]
    result_publisher: ControlFileSetPublisher
    source_commit: str
    output_root: Path = field(repr=False)
    worker_uid: int
    control_gid: int

    def start_registered_room(self, run_id: str) -> PreparedKakaoRoom:
        """Start the one accepted room without a caller-supplied provider URL or identity."""
        attempt = self.begin(run_id)
        prepared = prepare_kakao_registered_room(
            self.collections,
            self.attempts,
            attempt,
            publisher=self.result_publisher,
            source_commit=self.source_commit,
        )
        self.dispatch(prepared.attempt.attempt_id, space_key=prepared.space_key, room=prepared.room)
        return prepared

    def begin(self, run_id: str) -> KakaoCollectionAttempt:
        accepted = self.collections.read_background_intent(run_id).accepted
        reserved = self.browsers.reserve_browser(run_id, observe_profile=self.observe_profile)
        current_fence = collection_profile_fence(reserved)
        self.runtime.ensure_started(
            reserved,
            assert_current=self.browsers.assert_current_start,
            resolve_predecessor=lambda previous: closed_kakao_browser_pin(
                self.engine, current_fence, previous
            ),
        )
        running = self.browsers.accept_running(
            reserved.browser_run_id, observe_runtime=self.runtime.observe_running
        )
        return self.attempts.reserve_attempt(
            accepted.task_id, browser_run_id=running.browser_run_id
        )

    def dispatch(self, attempt_id: str, *, space_key: str, room: tuple[str, str]) -> None:
        """An already pinned C1 command is required; no fresh browser on lost response."""
        attempt = self.attempts.get_attempt(attempt_id)
        intent = self.browsers.get_intent(attempt.browser_run_id)
        if attempt.state != "COMMAND_READY" or intent.phase != "RUNNING":
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        actual = self.runtime.running_handle(intent)
        dispatch_staged_kakao_open_room(
            self.attempts,
            self.runtime.browser,
            actual,
            attempt_id,
            space_key=space_key,
            expected_room=room,
        )

    def finish(
        self,
        attempt_id: str,
        *,
        room: tuple[str, str],
        idempotency_key: str,
        expected_source_revision_id: str | None,
        expected_resource_version: int,
    ) -> AcceptedKakaoSource | None:
        """None means a confirmed live worker without a receipt, never a restarted run."""
        attempt = self.attempts.get_attempt(attempt_id)
        if attempt.state == "RESERVED":
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        intent = self.browsers.get_intent(attempt.browser_run_id)
        if attempt.state != "RESULT_ACCEPTED":
            reader = KakaoCaptureOutputReader(
                self.output_root, attempt_id, self.worker_uid, self.control_gid
            )
            try:
                reader.open_room_download()
            except KakaoCaptureInputError as error:
                if str(error) != "KAKAO_CAPTURE_INPUT_MISSING":
                    raise
                if intent.phase == "RUNNING":
                    try:
                        self.runtime.running_handle(intent)
                    except KakaoCollectionBrowserRuntimeError as stopped:
                        if stopped.code != "KAKAO_COLLECTION_BROWSER_ATTEMPT_CLOSED":
                            raise
                    else:
                        return None
                elif intent.phase not in {"STOPPING", "CLOSED"}:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED") from None
                # Receipt could have appeared in between the first lookup and the final exit.
                self.close(attempt.browser_run_id)
                try:
                    reader.open_room_download()
                except KakaoCaptureInputError as final:
                    if str(final) != "KAKAO_CAPTURE_INPUT_MISSING":
                        raise
                    raise KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_OUTPUT_MISSING") from None

        self.close(attempt.browser_run_id)
        accepted = admit_staged_kakao_open_room(
            self.attempts,
            attempt_id,
            output_root=self.output_root,
            worker_uid=self.worker_uid,
            control_gid=self.control_gid,
            expected_room=room,
            result_publisher=self.result_publisher,
            source_commit=self.source_commit,
            idempotency_key=idempotency_key,
            expected_source_revision_id=expected_source_revision_id,
            expected_resource_version=expected_resource_version,
        )
        self.attempts.finalize_one_room(attempt_id)
        return accepted

    def close(self, browser_run_id: str) -> None:
        self.browsers.request_stop(browser_run_id)
        self.browsers.accept_closed(browser_run_id, observe_stopped=self.runtime.close)
