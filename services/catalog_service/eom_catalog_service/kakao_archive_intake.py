"""Publish bounded private captures through the existing Artifact owner.

This adapter is not a collector or a public endpoint. Its caller must resolve the
current actor/binding/room/fence and reauthorize through the required callback.
The separate domain acceptance transaction links these immutable receipts; retry
uses the same logical capture IDs, not a new download or a repaired FAILED Job.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.kakao_archive import KakaoMessageNormalization, KakaoMessageObservation
from eom_catalog_contracts.kakao_snapshot import CSV_FORMAT_REF, SNAPSHOT_REF, KakaoRoomSnapshot
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.kakao_csv_parser import parse_kakao_csv

NORMALIZATION_REF = "eom://schemas/kakao-archive/message-normalization-v1/1.0"


@dataclass(frozen=True, slots=True)
class KakaoCapturePublication:
    source: ArtifactMemberPointer
    snapshot: ArtifactMemberPointer
    normalization: ArtifactMemberPointer
    snapshot_publication_job_id: str
    normalization_publication_job_id: str


def publish_kakao_capture(
    artifacts: CatalogArtifactService,
    *,
    snapshot: KakaoRoomSnapshot,
    source: bytes,
    normalization: KakaoMessageNormalization,
    authorize: Callable[[], None],
) -> KakaoCapturePublication:
    """Two idempotent publications, no message/name text in generic Job metadata."""
    authorize()
    snapshot = KakaoRoomSnapshot.model_validate(snapshot.model_dump(mode="json"))
    normalization = KakaoMessageNormalization.model_validate(normalization.model_dump(mode="json"))
    shared = (
        "source_binding_id",
        "room_id",
        "snapshot_revision_id",
        "source_sha256",
        "source_bytes",
        "observed_at_utc",
    )
    if any(getattr(snapshot, key) != getattr(normalization, key) for key in shared):
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_IDENTITY_MISMATCH")
    if len(source) != snapshot.source_bytes or sha256_bytes(source) != snapshot.source_sha256:
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_HASH_MISMATCH")
    # A matching raw hash alone does not prove the submitted text was parsed from it.
    reparsed = parse_kakao_csv(
        source,
        source_binding_id=snapshot.source_binding_id,
        room_id=snapshot.room_id,
        snapshot_revision_id=snapshot.snapshot_revision_id,
        normalization_revision_id=normalization.normalization_revision_id,
        observed_at_utc=snapshot.observed_at_utc,
        source_timezone=normalization.source_timezone,
        source_order=normalization.source_order,
        context_start_verified=normalization.context_start_verified,
        context_end_verified=normalization.context_end_verified,
        observations=tuple(
            KakaoMessageObservation.model_validate(
                message.model_dump(include=set(KakaoMessageObservation.model_fields))
            )
            for message in normalization.messages
        ),
    )
    if reparsed != normalization:
        raise ValueError("KAKAO_ARCHIVE_NORMALIZATION_MISMATCH")
    snapshot_bytes = canonical_json_bytes(snapshot.model_dump(mode="json"))
    normalized_bytes = canonical_json_bytes(normalization.model_dump(mode="json"))
    # JSON escaping can expand CSV input. Bound the actual encoded payload before staging.
    if len(normalized_bytes) > 128 * 1024 * 1024:
        raise ValueError("KAKAO_ARCHIVE_NORMALIZATION_TOO_LARGE")
    with tempfile.TemporaryDirectory(
        prefix="kakao-capture.", dir=artifacts.settings.staging_root
    ) as folder:
        root = Path(folder)
        members = {"source.csv": source, "snapshot.json": snapshot_bytes}
        _write_members(root, members)
        authorize()
        capture = artifacts.commit_file_set(
            files={name: root / name for name in members},
            primary_file="snapshot.json",
            artifact_type="kakao-room-snapshot",
            idempotency_key=f"kakao:snapshot:{snapshot.source_binding_id}:{snapshot.snapshot_revision_id}",
            request={"snapshot": snapshot.model_dump(mode="json")},
            result={"snapshot_sha256": sha256_bytes(snapshot_bytes)},
            file_metadata={
                "source.csv": {"schema_ref": CSV_FORMAT_REF, "media_type": "text/csv"},
                "snapshot.json": {"schema_ref": SNAPSHOT_REF, "media_type": "application/json"},
            },
            expected_file_sha256={name: sha256_bytes(value) for name, value in members.items()},
        )
        _check_primary(capture, snapshot_bytes)
        source_pointer = _pointer(capture, "source.csv", CSV_FORMAT_REF, "text/csv", source)
        snapshot_pointer = _pointer(
            capture, "snapshot.json", SNAPSHOT_REF, "application/json", snapshot_bytes
        )
        authorize()
        _write_members(root, {"normalization.json": normalized_bytes})
        normalized = artifacts.commit_file_set(
            files={"normalization.json": root / "normalization.json"},
            primary_file="normalization.json",
            artifact_type="kakao-message-normalization",
            idempotency_key=(
                f"kakao:normalization:{snapshot.source_binding_id}:"
                f"{normalization.normalization_revision_id}"
            ),
            request={
                "source_binding_id": snapshot.source_binding_id,
                "snapshot": snapshot_pointer.model_dump(mode="json"),
                "source": source_pointer.model_dump(mode="json"),
                "sha256": sha256_bytes(normalized_bytes),
            },
            result={"normalization_sha256": sha256_bytes(normalized_bytes)},
            file_metadata={
                "normalization.json": {
                    "schema_ref": NORMALIZATION_REF,
                    "media_type": "application/json",
                }
            },
            expected_file_sha256={"normalization.json": sha256_bytes(normalized_bytes)},
        )
        _check_primary(normalized, normalized_bytes)
        authorize()
        return KakaoCapturePublication(
            source_pointer,
            snapshot_pointer,
            _pointer(
                normalized,
                "normalization.json",
                NORMALIZATION_REF,
                "application/json",
                normalized_bytes,
            ),
            capture.job_id,
            normalized.job_id,
        )


def _write_members(root: Path, members: dict[str, bytes]) -> None:
    for name, value in members.items():
        with (root / name).open("xb") as stream:
            stream.write(value)


def _check_primary(artifact: CatalogArtifact, payload: bytes) -> None:
    if artifact.content_hash != sha256_bytes(payload) or artifact.content_bytes != len(payload):
        raise ValueError("KAKAO_ARCHIVE_PUBLICATION_MISMATCH")


def _pointer(
    artifact: CatalogArtifact, name: str, schema: str, media: str, payload: bytes
) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.revision_id,
        member_path=name,
        schema_ref=schema,
        media_type=media,
        sha256=sha256_bytes(payload),
    )
