"""Trusted staged-output composition, not a public upload or collection launcher."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher

    from .kakao_collection_attempt_service import KakaoCollectionAttemptService
    from .kakao_source_service import AcceptedKakaoSource


def admit_staged_kakao_capture_source(
    attempts: KakaoCollectionAttemptService,
    attempt_id: str,
    *,
    output_root: Path,
    worker_uid: int,
    control_gid: int,
    result_publisher: ControlFileSetPublisher,
    source_commit: str,
    idempotency_key: str,
    expected_source_revision_id: str | None,
    expected_resource_version: int,
) -> AcceptedKakaoSource:
    """Reauthorize the stored accepted run, then reuse canonical publication/adoption.

    Root and identities come from trusted installation, never API/worker input.
    The lazy reader is not invoked for a completed same-request source replay.
    This use case performs no browser dispatch or source-precondition guessing.
    """
    from eom_orchestrator.kakao_capture_inputs import KakaoCaptureOutputReader

    reader = KakaoCaptureOutputReader(output_root, attempt_id, worker_uid, control_gid)
    attempts.publish_and_accept_result(
        attempt_id,
        publisher=result_publisher,
        source_commit=source_commit,
        read_result=reader.read_result,
        read_member=reader,
    )
    access = attempts.accepted_source_access(attempt_id)
    return attempts.publish_and_admit_capture_source(
        access,
        attempt_id,
        read_member=reader,
        idempotency_key=idempotency_key,
        expected_source_revision_id=expected_source_revision_id,
        expected_resource_version=expected_resource_version,
    )
