"""Publish accepted capture members using existing original/media Artifact owners.

Only a trusted application composition supplies the current owner authorizer and
the Orchestrator's bounded local reader. These values are not public upload input
or a worker-provided execution grant. No browser, DB or direct NAS access here.
"""

from collections.abc import Callable
from dataclasses import dataclass

from eom_catalog_contracts.kakao_archive import KakaoMessageNormalization
from eom_catalog_contracts.kakao_snapshot import KakaoRoomSnapshot
from eom_catalog_contracts.kakao_source import (
    KakaoCaptureAuthority,
    KakaoSourceAdmission,
    KakaoSourceAttachment,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import (
    CaptureCapability,
    CaptureCommand,
    CaptureResult,
    CaptureRoomReport,
    CsvMember,
    room_capture_members,
    validate_capture_result,
)
from eom_kakao_archive_contracts.render import LocalMember

from .artifacts import CatalogArtifactService
from .kakao_archive_intake import publish_kakao_capture
from .kakao_media_publication import KakaoMediaPublication, publish_kakao_media
from .kakao_source_resolution import capture_attachment_quality

CaptureMemberReader = Callable[[LocalMember | CsvMember], bytes]


@dataclass(frozen=True, slots=True)
class AcceptedCapturePublication:
    """Exact accepted owner projection; its mandatory authorizer remains authoritative."""

    authority: KakaoCaptureAuthority
    command: CaptureCommand
    capability: CaptureCapability
    result: CaptureResult
    report: CaptureRoomReport


def publish_kakao_capture_source(
    artifacts: CatalogArtifactService,
    *,
    capture: AcceptedCapturePublication,
    read_member: CaptureMemberReader,
    authorize: Callable[[], None],
    expected_source_revision_id: str | None,
    expected_resource_version: int,
) -> KakaoSourceAdmission:
    authorize()
    report, authority = capture.report, capture.authority
    validate_capture_result(
        capture.command,
        capture.result,
        report,
        capability=capture.capability,
        current_fence=authority.fence,
    )
    if capture.result.status not in {"COMPLETED", "PARTIAL"}:
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_EVIDENCE_INVALID")
    # Validate the closed member set before any local read. Each declared path is
    # checked even when two paths happen to contain the same image bytes.
    room_capture_members(report)

    def read(member: LocalMember | CsvMember) -> bytes:
        authorize()
        raw = read_member(member)
        if (
            type(raw) is not bytes
            or len(raw) != member.size_bytes
            or sha256_bytes(raw) != member.sha256
        ):
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_HASH_MISMATCH")
        authorize()
        return raw

    source = read(report.raw_csv)
    raw_normalization = read(report.normalization)
    normalization = KakaoMessageNormalization.model_validate_json(raw_normalization)
    if canonical_json_bytes(normalization.model_dump(mode="json")) != raw_normalization:
        raise ValueError("KAKAO_ARCHIVE_NORMALIZATION_MISMATCH")
    snapshot = KakaoRoomSnapshot(
        source_binding_id=report.source_binding_id,
        room_id=report.room_id,
        snapshot_revision_id=report.snapshot_revision_id,
        source_sha256=report.raw_csv.sha256,
        source_bytes=report.raw_csv.size_bytes,
        observed_at_utc=report.observed_end_at,
        csv_scope=report.csv_scope,
    )
    publication = publish_kakao_capture(
        artifacts,
        snapshot=snapshot,
        source=source,
        normalization=normalization,
        authorize=authorize,
    )
    media: dict[tuple[str, str, int], KakaoMediaPublication] = {}
    members: dict[str, KakaoMediaPublication] = {}
    attachments = []
    for attachment in report.attachments:
        original = None
        if attachment.member is not None:
            member = attachment.member
            original = members.get(member.relative_path)
            if original is None:
                raw = read(member)
                key = (member.sha256, member.media_type, member.size_bytes)
                original = media.get(key)
                if original is None:
                    original = publish_kakao_media(
                        artifacts,
                        source_binding_id=report.source_binding_id,
                        source=raw,
                        authorize=authorize,
                    )
                    media[key] = original
                members[member.relative_path] = original
            if (
                original.receipt.media_type,
                original.receipt.width_px,
                original.receipt.height_px,
            ) != (member.media_type, attachment.width_px, attachment.height_px):
                raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_MEDIA_INVALID")
        attachments.append(
            KakaoSourceAttachment(
                attachment_id=attachment.attachment_id,
                attachment_revision_id=attachment.attachment_revision_id,
                original=None if original is None else original.original,
                media_receipt=None if original is None else original.manifest,
                quality=capture_attachment_quality(attachment.quality_level),
            )
        )
    authorize()
    return KakaoSourceAdmission(
        source_binding_id=report.source_binding_id,
        room_id=report.room_id,
        snapshot_revision_id=report.snapshot_revision_id,
        normalization_revision_id=report.normalization_revision_id,
        expected_source_revision_id=expected_source_revision_id,
        expected_resource_version=expected_resource_version,
        source=publication.source,
        snapshot=publication.snapshot,
        normalization=publication.normalization,
        authority=authority,
        attachments=tuple(attachments),
    )
