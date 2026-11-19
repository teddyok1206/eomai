"""Advance one accepted room in the existing Catalog process, never from a status request."""

from threading import Lock
from typing import Literal

from eom_orchestrator.kakao_collection_browser_runtime import KakaoCollectionBrowserRuntimeError

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_collection_attempt_service import UnusableKakaoOpenRoomOutput
from .kakao_collection_input_publication import read_registered_collection_room
from .kakao_one_room_collection import KakaoOneRoomCollection

type Progress = Literal["IDLE", "WAITING", "DISPATCHED", "STORED", "FAILED", "ERROR"]


class KakaoCollectionContinuation:
    def __init__(self, collection: KakaoOneRoomCollection) -> None:
        self.collection = collection
        self._tick = Lock()
        # A lookup hint only. After restart, the protected command writer proves
        # exact replay before it can touch the same immutable per-epoch command.
        self._scope: tuple[str, str, tuple[str, str]] | None = None
        self._dispatched: str | None = None

    def advance_once(self) -> Progress:
        if not self._tick.acquire(blocking=False):
            return "WAITING"
        try:
            return self._advance()
        finally:
            self._tick.release()

    def _advance(self) -> Progress:
        owner = self.collection
        pending = owner.collections.next_pending_room()
        if pending is None:
            self._scope, self._dispatched = None, None
            return "IDLE"
        attempt_id = pending.attempt_id
        try:
            if attempt_id is None or owner.attempts.get_attempt(attempt_id).state == "RESERVED":
                if (
                    pending.browser_run_id is not None
                    and owner.browsers.get_intent(pending.browser_run_id).phase == "CLOSED"
                ):
                    owner.browsers.record_unusable_one_room_output(pending.browser_run_id)
                    return "FAILED"
                prepared = owner.start_registered_room(pending.run_id)
                self._scope = pending.run_id, prepared.space_key, prepared.room
                self._dispatched = prepared.attempt.attempt_id
                return "DISPATCHED"
            if self._scope is None or self._scope[0] != pending.run_id:
                _, verified = read_registered_collection_room(owner.collections, pending.run_id)
                confirmation = verified.proof.confirmation
                self._scope = (
                    pending.run_id,
                    verified.space_key,
                    (
                        confirmation.expected_channel_key,
                        confirmation.expected_room_key,
                    ),
                )
            _, space, room = self._scope
            predecessor, version = owner.attempts.source_adoption_pin(attempt_id)
            accepted = owner.finish(
                attempt_id,
                room=room,
                idempotency_key=f"kakao:room-adoption:{attempt_id}",
                expected_source_revision_id=predecessor,
                expected_resource_version=version,
            )
            if accepted is not None:
                self._scope, self._dispatched = None, None
                return "STORED"
            if self._dispatched != attempt_id:
                owner.dispatch(attempt_id, space_key=space, room=room)
                self._dispatched = attempt_id
                return "DISPATCHED"
            return "WAITING"
        except KakaoCollectionBrowserRuntimeError as error:
            if error.code == "KAKAO_COLLECTION_BROWSER_ATTEMPT_CLOSED" and pending.browser_run_id:
                # A closed browser can race with publishing a receipt. If there
                # is an attempt, let the next tick observe the exact receipt again.
                if (
                    attempt_id is not None
                    and owner.attempts.get_attempt(attempt_id).state != "RESERVED"
                ):
                    return "WAITING"
                owner.close(pending.browser_run_id)
                owner.browsers.record_unusable_one_room_output(pending.browser_run_id)
                return "FAILED"
            return "ERROR"
        except KakaoArchiveError as error:
            if (
                isinstance(error, UnusableKakaoOpenRoomOutput)
                or error.code
                in {
                    "KAKAO_ARCHIVE_CAPTURE_OUTPUT_MISSING",
                    "KAKAO_ARCHIVE_CAPTURE_RECEIPT_INVALID",
                }
            ) and pending.browser_run_id:
                owner.browsers.record_unusable_one_room_output(pending.browser_run_id)
                return "FAILED"
            if error.code in {
                "KAKAO_ARCHIVE_REMOTE_PROFILE_BUSY",
                "KAKAO_ARCHIVE_REMOTE_RUNTIME_UNAVAILABLE",
            }:
                return "WAITING"
            return "ERROR"
