"""Publish private question/packet manifests through the existing Artifact owner.

This is not a public mutation API or source ACL. The application caller resolves
source permissions/mapping and accepts the returned pointer with a separate CAS.
No original message/photo bytes are copied into a packet or generic Job metadata.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.kakao_question import (
    QUESTION_REF,
    KakaoQuestionManifest,
    KakaoQuestionPacket,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_question_editing import (
    PublishedKakaoQuestion,
    ResolvedKakaoQuestionSource,
    build_question_packet,
    validate_question_sources,
)

PACKET_REF = "eom://schemas/kakao-archive/question-packet-v1/1.0"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class KakaoQuestionPublication:
    published: PublishedKakaoQuestion
    publication_job_id: str


@dataclass(frozen=True, slots=True)
class KakaoPacketPublication:
    packet: KakaoQuestionPacket
    pointer: ArtifactMemberPointer
    publication_job_id: str


def publish_kakao_question(
    artifacts: CatalogArtifactService,
    *,
    question: KakaoQuestionManifest,
    sources: tuple[ResolvedKakaoQuestionSource, ...],
    authorize: Callable[[], None],
) -> KakaoQuestionPublication:
    authorize()
    question = KakaoQuestionManifest.model_validate(question.model_dump(mode="json"))
    validate_question_sources(question, sources)
    pointer, job_id = _publish_manifest(
        artifacts,
        value=question,
        authorize=authorize,
    )
    return KakaoQuestionPublication(PublishedKakaoQuestion(question, pointer), job_id)


def publish_kakao_packet(
    artifacts: CatalogArtifactService,
    *,
    packet: KakaoQuestionPacket,
    questions: tuple[PublishedKakaoQuestion, ...],
    authorize: Callable[[], None],
) -> KakaoPacketPublication:
    authorize()
    packet = KakaoQuestionPacket.model_validate(packet.model_dump(mode="json"))
    # Recompute readiness from the exact published manifests, not a submitted
    # empty blockers list or a last-minute query for current question revisions.
    validated = tuple(
        PublishedKakaoQuestion(
            KakaoQuestionManifest.model_validate(item.question.model_dump(mode="json")),
            item.pointer,
        )
        for item in questions
    )
    rebuilt = build_question_packet(
        validated,
        packet_id=packet.packet_id,
        packet_revision_id=packet.packet_revision_id,
        previous_revision_id=packet.previous_revision_id,
        start_date=packet.display_start_date,
        end_date_inclusive=packet.display_end_date_inclusive,
        mode=packet.mode,
        include_replies=packet.include_replies,
        actor_id=packet.created_by,
        created_at=packet.created_at,
        collection_coverage=packet.collection_coverage,
    )
    if packet != rebuilt:
        raise ValueError("KAKAO_ARCHIVE_PACKET_MANIFEST_MISMATCH")
    pointer, job_id = _publish_manifest(artifacts, value=packet, authorize=authorize)
    return KakaoPacketPublication(packet, pointer, job_id)


def _publish_manifest(
    artifacts: CatalogArtifactService,
    *,
    value: KakaoQuestionManifest | KakaoQuestionPacket,
    authorize: Callable[[], None],
) -> tuple[ArtifactMemberPointer, str]:
    if isinstance(value, KakaoQuestionManifest):
        kind, schema, member = "question", QUESTION_REF, "question.json"
        logical_id, revision_id = value.question_id, value.question_revision_id
        count = len(value.ordered_blocks)
        artifact_type = "kakao-question-manifest"
    else:
        kind, schema, member = "packet", PACKET_REF, "packet.json"
        logical_id, revision_id = value.packet_id, value.packet_revision_id
        count = len(value.questions)
        artifact_type = "kakao-question-packet"
    payload = canonical_json_bytes(value.model_dump(mode="json"))
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("KAKAO_ARCHIVE_MANIFEST_TOO_LARGE")
    digest = sha256_bytes(payload)
    with tempfile.TemporaryDirectory(
        prefix="kakao-manifest.", dir=artifacts.settings.staging_root
    ) as folder:
        path = Path(folder) / member
        with path.open("xb") as stream:
            stream.write(payload)
        authorize()
        artifact = artifacts.commit_file_set(
            files={member: path},
            primary_file=member,
            artifact_type=artifact_type,
            idempotency_key=f"kakao:{kind}:{value.source_binding_id}:{revision_id}",
            request={
                "source_binding_id": value.source_binding_id,
                "logical_id": logical_id,
                "revision_id": revision_id,
                "schema_ref": schema,
                "manifest_sha256": digest,
            },
            result={"manifest_sha256": digest, "selection_count": count},
            file_metadata={member: {"schema_ref": schema, "media_type": "application/json"}},
            expected_file_sha256={member: digest},
        )
        if artifact.content_hash != digest or artifact.content_bytes != len(payload):
            raise ValueError("KAKAO_ARCHIVE_PUBLICATION_MISMATCH")
        pointer = ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=member,
            schema_ref=schema,
            media_type="application/json",
            sha256=digest,
        )
        authorize()
        return pointer, artifact.job_id
