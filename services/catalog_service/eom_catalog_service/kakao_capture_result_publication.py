"""C1 result/report publication through the existing immutable file-set owner."""

import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from eom_catalog_contracts.kakao_source import CAPTURE_REF
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import (
    CaptureCapability,
    CaptureCommand,
    CaptureResult,
    CaptureRoomReport,
    validate_capture_result,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.state_machine import JobState
from eom_protocol.artifact_members import ArtifactMemberPointer

from .kakao_archive_authorization import KakaoArchiveError

RESULT_ARTIFACT_TYPE = "control_kakao_capture_result"


def result_publication_key(attempt_id: str) -> str:
    if (
        not isinstance(attempt_id, str)
        or re.fullmatch(r"kakaoattempt_[0-9a-f]{32}", attempt_id) is None
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_EVIDENCE_INVALID")
    return "kakao:capture-result:" + attempt_id


def find_kakao_capture_result(
    publisher: ControlFileSetPublisher, attempt_id: str
) -> ArtifactMemberPointer | None:
    """Read exact completed publication; interrupted originals are not new attempts."""
    key = result_publication_key(attempt_id)
    try:
        return publisher.find_published_primary_member(
            idempotency_key=key, artifact_type=RESULT_ARTIFACT_TYPE
        )
    except ControlPlaneError as error:
        if error.code != "CONTROL_FILE_SET_INCOMPLETE":
            raise
        state = publisher.publication_state(idempotency_key=key, artifact_type=RESULT_ARTIFACT_TYPE)
        if state in {None, JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            raise
        return None


def publish_kakao_capture_result(
    publisher: ControlFileSetPublisher,
    *,
    staging_root: Path,
    command: CaptureCommand,
    capability: CaptureCapability,
    result: CaptureResult,
    report: CaptureRoomReport | None,
    source_commit: str,
    authorize: Callable[[], None],
) -> ArtifactMemberPointer:
    authorize()
    validate_capture_result(
        command, result, report, capability=capability, current_fence=command.execution.fence
    )
    files = {"result.json": canonical_json_bytes(result.model_dump(mode="json"))}
    if len(files["result.json"]) > 32768:
        raise ValueError("KAKAO_CAPTURE_RESULT_SIZE_INVALID")
    if report is not None:
        files["room-report.json"] = canonical_json_bytes(report.model_dump(mode="json"))
        if len(files["room-report.json"]) > 4 * 1024 * 1024:
            raise ValueError("KAKAO_CAPTURE_REPORT_SIZE_INVALID")
    with tempfile.TemporaryDirectory(prefix="kakao-result.", dir=staging_root) as temporary:
        root = Path(temporary)
        members = []
        for name, raw in files.items():
            path = root / name
            with path.open("xb") as stream:
                stream.write(raw)
            members.append(
                ControlFileSetMember(
                    name, path, sha256_bytes(raw), len(raw), CAPTURE_REF, "application/json"
                )
            )
        authorize()
        published = publisher.publish_first_observation(
            members=tuple(members),
            primary_file="result.json",
            artifact_type=RESULT_ARTIFACT_TYPE,
            manifest_version="catalog-file-set/1.0",
            idempotency_key=result_publication_key(command.execution.attempt_id),
            source_commit=source_commit,
        )
    authorize()
    if published.primary_file != "result.json" or published.primary_sha256 != sha256_bytes(
        files["result.json"]
    ):
        raise ValueError("KAKAO_CAPTURE_RESULT_PUBLICATION_INVALID")
    return ArtifactMemberPointer(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path="result.json",
        schema_ref=CAPTURE_REF,
        media_type="application/json",
        sha256=published.primary_sha256,
    )
