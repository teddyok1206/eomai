"""Trusted staged-output composition, not a public upload or collection launcher."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Engine

if TYPE_CHECKING:
    from eom_kakao_archive_contracts.capture import CsvMember
    from eom_kakao_archive_contracts.render import LocalMember
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
    from eom_orchestrator.kakao_browser_runtime import BrowserRunHandle, FixedKakaoBrowserRuntime

    from .kakao_capture_proposal import RoomCaptureDocuments
    from .kakao_collection_attempt_service import KakaoCollectionAttemptService
    from .kakao_source_service import AcceptedKakaoSource


def build_configured_kakao_collection_attempts(
    engine: Engine, environment: Mapping[str, str]
) -> KakaoCollectionAttemptService | None:
    """Compose an exact admission owner, without launching or admitting any work."""
    key = "EOM_KAKAO_COLLECTION_ADAPTER_SHA256"
    if key not in environment:
        return None
    adapter = environment[key]
    profile = environment.get("EOM_KAKAO_PROFILE_ID", "")
    if (
        re.fullmatch(r"sha256:[0-9a-f]{64}", adapter) is None
        or re.fullmatch(r"kakaoprofile_[0-9a-f]{32}", profile) is None
    ):
        raise ValueError("KAKAO_COLLECTION_CONFIGURATION_INVALID")
    from .artifacts import CatalogArtifactService
    from .kakao_collection_attempt_service import KakaoCollectionAttemptService

    return KakaoCollectionAttemptService(
        engine,
        artifacts=CatalogArtifactService(engine),
        profile_id=profile,
        adapter_release_sha256=adapter,
    )


def dispatch_staged_kakao_open_room(
    attempts: KakaoCollectionAttemptService,
    runtime: FixedKakaoBrowserRuntime,
    browser: BrowserRunHandle,
    attempt_id: str,
    *,
    space_key: str,
    expected_room: tuple[str, str],
) -> None:
    """Send the bound C1 command to that AUTO browser, never launch another one."""

    def current() -> None:
        if (
            attempts.prepare_auto_room(attempt_id, space_key=space_key, expected_room=expected_room)
            != command
        ):
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_IDENTITY_MISMATCH")

    command = attempts.prepare_auto_room(
        attempt_id, space_key=space_key, expected_room=expected_room
    )
    runtime.stage_auto_room(browser, command, assert_current=current)


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
    return _admit_staged(
        attempts,
        attempt_id,
        read_result=reader.read_result,
        read_member=reader,
        result_publisher=result_publisher,
        source_commit=source_commit,
        idempotency_key=idempotency_key,
        expected_source_revision_id=expected_source_revision_id,
        expected_resource_version=expected_resource_version,
    )


def admit_staged_kakao_open_room(
    attempts: KakaoCollectionAttemptService,
    attempt_id: str,
    *,
    output_root: Path,
    worker_uid: int,
    control_gid: int,
    expected_room: tuple[str, str],
    result_publisher: ControlFileSetPublisher,
    source_commit: str,
    idempotency_key: str,
    expected_source_revision_id: str | None,
    expected_resource_version: int,
) -> AcceptedKakaoSource:
    """Compose C1 from the fixed worker receipt without rewriting worker-owned files."""
    from eom_orchestrator.kakao_capture_inputs import KakaoCaptureOutputReader

    reader = KakaoCaptureOutputReader(output_root, attempt_id, worker_uid, control_gid)

    @cache
    def proposal() -> RoomCaptureDocuments:
        return attempts.open_room_documents(
            attempt_id,
            expected_room=expected_room,
            read_receipt=reader.open_room_download,
            read_csv=reader,
            read_photo=reader.read_open_room_photo,
        )

    def read_member(member: LocalMember | CsvMember) -> bytes:
        if member.relative_path == "outputs/room-report.json":
            return proposal().report_bytes
        if member.relative_path == "outputs/normalization.json":
            return proposal().normalization_bytes
        return reader(member)

    return _admit_staged(
        attempts,
        attempt_id,
        read_result=lambda: proposal().result_bytes,
        read_member=read_member,
        result_publisher=result_publisher,
        source_commit=source_commit,
        idempotency_key=idempotency_key,
        expected_source_revision_id=expected_source_revision_id,
        expected_resource_version=expected_resource_version,
    )


def _admit_staged(
    attempts: KakaoCollectionAttemptService,
    attempt_id: str,
    *,
    read_result: Callable[[], bytes],
    read_member: Callable[[LocalMember | CsvMember], bytes],
    result_publisher: ControlFileSetPublisher,
    source_commit: str,
    idempotency_key: str,
    expected_source_revision_id: str | None,
    expected_resource_version: int,
) -> AcceptedKakaoSource:
    attempts.publish_and_accept_result(
        attempt_id,
        publisher=result_publisher,
        source_commit=source_commit,
        read_result=read_result,
        read_member=read_member,
    )
    access = attempts.accepted_source_access(attempt_id)
    return attempts.publish_and_admit_capture_source(
        access,
        attempt_id,
        read_member=read_member,
        idempotency_key=idempotency_key,
        expected_source_revision_id=expected_source_revision_id,
        expected_resource_version=expected_resource_version,
    )
