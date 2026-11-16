"""Late metadata-only pointer check shared by private room/source acceptance.

This does not authorize access or read bytes. Owners resolve bytes outside their
write transaction, then recheck mutable publication/lifecycle here before adoption.
"""

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError


def validate_source_pointer_metadata(
    session: Session, evidence: ArtifactMemberPointer
) -> tuple[ArtifactRecord, ArtifactRevisionRecord]:
    return validate_source_pointer_metadata_batch(session, (evidence,))[
        (evidence.artifact_id, evidence.artifact_revision_id)
    ]


def validate_source_pointer_metadata_batch(
    session: Session, pointers: tuple[ArtifactMemberPointer, ...]
) -> dict[tuple[str, str], tuple[ArtifactRecord, ArtifactRevisionRecord]]:
    """One indexed join, one hash per revision; not one DB query per photograph."""
    grouped: dict[tuple[str, str], list[ArtifactMemberPointer]] = {}
    for pointer in pointers:
        grouped.setdefault((pointer.artifact_id, pointer.artifact_revision_id), []).append(pointer)
    if len(grouped) > 8192:
        raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
    if not grouped:
        return {}
    rows = session.execute(
        select(ArtifactRecord, ArtifactRevisionRecord, JobRecord.status)
        .join(
            ArtifactRevisionRecord,
            ArtifactRevisionRecord.logical_artifact_id == ArtifactRecord.logical_artifact_id,
        )
        .join(JobRecord, JobRecord.job_id == ArtifactRevisionRecord.job_id)
        .where(
            tuple_(ArtifactRecord.logical_artifact_id, ArtifactRevisionRecord.revision_id).in_(
                tuple(grouped)
            )
        )
        .execution_options(populate_existing=True)
    ).all()
    if len(rows) != len(grouped):
        raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
    result = {}
    for logical, revision, status in rows:
        identity = (logical.logical_artifact_id, revision.revision_id)
        _validate_metadata(logical, revision, status, grouped[identity])
        result[identity] = logical, revision
    return result


def _validate_metadata(
    logical: ArtifactRecord,
    revision: ArtifactRevisionRecord,
    status: str,
    pointers: list[ArtifactMemberPointer],
) -> None:
    manifest = revision.manifest
    if not isinstance(manifest, dict):
        raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
    files = manifest.get("files")
    members: dict[str, list[dict[str, object]]] = {}
    if isinstance(files, list):
        for entry in files:
            if isinstance(entry, dict) and isinstance(entry.get("file_name"), str):
                members.setdefault(entry["file_name"], []).append(entry)
    if (
        not logical.approved
        or not revision.approved
        or status != "SUCCEEDED"
        or logical.job_id != revision.job_id
        or revision.manifest_hash != sha256_bytes(canonical_json_bytes(manifest))
        or manifest.get("job_id") != revision.job_id
        or manifest.get("logical_artifact_id") != logical.logical_artifact_id
        or manifest.get("revision_id") != revision.revision_id
        or manifest.get("artifact_type") != logical.artifact_type
        or manifest.get("content_hash") != revision.content_hash
        or manifest.get("content_bytes") != revision.content_bytes
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
    for pointer in pointers:
        matching = members.get(pointer.member_path, [])
        if (
            len(matching) != 1
            or matching[0].get("sha256") != pointer.sha256
            or matching[0].get("schema_ref") != pointer.schema_ref
            or matching[0].get("media_type") != pointer.media_type
            or type(matching[0].get("bytes")) is not int
            or int(str(matching[0]["bytes"])) < 0
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
