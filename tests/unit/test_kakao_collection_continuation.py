"""Catalog continuation never uses client re-reads or OS timeouts as work claims."""

from types import SimpleNamespace
from unittest.mock import Mock

from eom_catalog_service import kakao_collection_continuation as module
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_collection_service import PendingKakaoRoomRun


def test_restart_restores_same_pending_attempt_and_does_not_relaunch(monkeypatch):
    owner = Mock()
    owner.collections.next_pending_room.return_value = PendingKakaoRoomRun(
        "run", "attempt", "browser"
    )
    owner.attempts.get_attempt.return_value = SimpleNamespace(state="COMMAND_READY")
    owner.attempts.source_adoption_pin.return_value = ("original-predecessor", 3)
    owner.finish.side_effect = [None, None, object()]
    proof = SimpleNamespace(
        space_key="space",
        proof=SimpleNamespace(
            confirmation=SimpleNamespace(
                expected_channel_key="channel",
                expected_room_key="room",
            )
        ),
    )
    read = Mock(return_value=(None, proof))
    monkeypatch.setattr(module, "read_registered_collection_room", read)
    continuation = module.KakaoCollectionContinuation(owner)
    assert [continuation.advance_once() for _ in range(3)] == ["DISPATCHED", "WAITING", "STORED"]
    owner.start_registered_room.assert_not_called()
    owner.dispatch.assert_called_once_with("attempt", space_key="space", room=("channel", "room"))
    read.assert_called_once_with(owner.collections, "run")
    for call in owner.finish.call_args_list:
        assert call.args == ("attempt",)
        assert call.kwargs["idempotency_key"] == "kakao:room-adoption:attempt"
        assert call.kwargs["expected_source_revision_id"] == "original-predecessor"


def test_observed_missing_receipt_finishes_as_failure_instead_of_retry():
    owner = Mock()
    owner.collections.next_pending_room.return_value = PendingKakaoRoomRun(
        "run", "attempt", "browser"
    )
    owner.attempts.get_attempt.return_value = SimpleNamespace(state="COMMAND_READY")
    owner.attempts.source_adoption_pin.return_value = (None, 0)
    owner.finish.side_effect = KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_OUTPUT_MISSING")
    continuation = module.KakaoCollectionContinuation(owner)
    continuation._scope = ("run", "space", ("channel", "room"))
    assert continuation.advance_once() == "FAILED"
    owner.browsers.record_missing_one_room_output.assert_called_once_with("browser")
    owner.start_registered_room.assert_not_called()
    owner.dispatch.assert_not_called()
