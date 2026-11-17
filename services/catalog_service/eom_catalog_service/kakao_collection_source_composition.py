"""Trusted staged-output composition, not a public upload or collection launcher."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Engine

if TYPE_CHECKING:
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher

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
