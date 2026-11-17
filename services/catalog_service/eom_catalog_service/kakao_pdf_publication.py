"""Publish stopped, validated PDF outputs with existing Artifact ownership.

No renderer execution, new byte copy, database mutation or source authority lives
here. The export use case supplies current access/fence checks and adopts exact
returned pointers in its own short transaction after publication.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from eom_kakao_archive_contracts import (
    LocalMember,
    canonical_bytes,
    sha256,
)
from eom_kakao_archive_contracts.pdf_contracts import (
    PdfCommand,
    parse_pdf_command,
    parse_pdf_layout,
    parse_pdf_manifest,
    parse_pdf_result,
)
from eom_kakao_archive_contracts.study import StudyRenderCommand
from eom_orchestrator.kakao_pdf_execution import AcceptedKakaoPdf
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.artifacts import CatalogArtifactService

PDF_REF = "eom://schemas/kakao-archive/question-pdf/1.0"
PREVIEW_REF = "eom://schemas/kakao-archive/question-preview-png/1.0"
LAYOUT_REF = "eom://schemas/kakao-archive/worker-question-layout/1.0"
STUDY_LAYOUT_REF = "eom://schemas/kakao-archive/worker-study-layout/1.0"
_MEMBER_SCHEMAS = {
    "application/pdf": PDF_REF,
    "application/json": LAYOUT_REF,
    "image/png": PREVIEW_REF,
}


@dataclass(frozen=True, slots=True)
class KakaoPdfPublication:
    export_id: str
    publication_job_id: str
    pdf: ArtifactMemberPointer
    layout: ArtifactMemberPointer
    previews: tuple[ArtifactMemberPointer, ...]


def publish_kakao_pdf(
    artifacts: CatalogArtifactService,
    *,
    command: PdfCommand,
    manifest_bytes: bytes,
    accepted: AcceptedKakaoPdf,
    authorize: Callable[[], None],
) -> KakaoPdfPublication:
    """Same accepted attempt replays publication; it never starts another render."""
    authorize()
    command = parse_pdf_command(command.model_dump(mode="json"))
    # Hash the pinned JSON bytes, not a reserialized model with newly filled
    # optional defaults. Both explicit-null and omitted optional fields are valid.
    if (
        len(manifest_bytes) != command.manifest.size_bytes
        or sha256(manifest_bytes) != command.manifest.sha256
    ):
        raise ValueError("KAKAO_ARCHIVE_PDF_MANIFEST_HASH_MISMATCH")
    # Parse raw JSON and the exact input family; model_copy proposals are not schema evidence.
    manifest = parse_pdf_manifest(command, json.loads(manifest_bytes))
    result = parse_pdf_result(command, accepted.result.model_dump(mode="json"))
    if result.status != "COMPLETED" or accepted.layout is None or accepted.staging_root is None:
        raise ValueError("KAKAO_ARCHIVE_PDF_NOT_COMPLETED")
    layout = parse_pdf_layout(command, manifest, accepted.layout.model_dump(mode="json"))
    if (
        result.execution != command.execution
        or result.export_id != command.export_id
        or result.command_sha256 != sha256(canonical_bytes(command.model_dump(mode="json")))
        or result.manifest_sha256 != command.manifest.sha256
        or accepted.files != result.outputs
        or result.page_count != len(layout.pages)
        or sum(member.size_bytes for member in result.outputs) > 256 * 1024 * 1024
    ):
        raise ValueError("KAKAO_ARCHIVE_PDF_PUBLICATION_PINS_MISMATCH")
    members = {member.relative_path: member for member in result.outputs}
    layout_bytes = canonical_bytes(layout.model_dump(mode="json"))
    if members["layout.json"].sha256 != sha256(layout_bytes) or members[
        "layout.json"
    ].size_bytes != len(layout_bytes):
        raise ValueError("KAKAO_ARCHIVE_PDF_LAYOUT_HASH_MISMATCH")
    root = accepted.staging_root
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("KAKAO_ARCHIVE_PDF_STAGING_INVALID")
    request: dict[str, object] = {
        "export_id": command.export_id,
        "source_binding_id": command.source_binding_id,
        "packet_revision_id": command.packet_revision_id,
        "student_id": command.student_id,
        "subset_sha256": command.subset_sha256,
        "mode": command.mode,
        "execution": command.execution.model_dump(mode="json"),
        "command_sha256": result.command_sha256,
        "renderer_release_sha256": command.renderer_release_sha256,
        "result_sha256": sha256(canonical_bytes(result.model_dump(mode="json"))),
    }
    member_schemas = _MEMBER_SCHEMAS
    if isinstance(command, StudyRenderCommand):
        request.update(
            schema_version=command.schema_version,
            study_revision_id=command.study_revision_id,
            layout_policy=command.layout_policy,
        )
        member_schemas = _MEMBER_SCHEMAS | {"application/json": STUDY_LAYOUT_REF}
    authorize()
    artifact = artifacts.commit_file_set(
        files={name: root / name for name in members},
        primary_file="layout.json",
        artifact_type="kakao-question-pdf",
        idempotency_key=(
            f"kakao:pdf:{command.source_binding_id}:{command.export_id}:"
            f"{command.execution.attempt_id}"
        ),
        request=request,
        result={"layout_sha256": members["layout.json"].sha256, "page_count": result.page_count},
        file_metadata={
            name: {
                "schema_ref": member_schemas[member.media_type],
                "media_type": member.media_type,
            }
            for name, member in members.items()
        },
        expected_file_sha256={name: member.sha256 for name, member in members.items()},
    )
    if artifact.content_hash != sha256(layout_bytes) or artifact.content_bytes != len(layout_bytes):
        raise ValueError("KAKAO_ARCHIVE_PUBLICATION_MISMATCH")

    def pointer(member: LocalMember) -> ArtifactMemberPointer:
        return ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=member.relative_path,
            schema_ref=member_schemas[member.media_type],
            media_type=member.media_type,
            sha256=member.sha256,
        )

    authorize()
    return KakaoPdfPublication(
        command.export_id,
        artifact.job_id,
        pointer(members["report.pdf"]),
        pointer(members["layout.json"]),
        tuple(
            pointer(members[f"page-{number:04d}.png"]) for number in range(1, result.page_count + 1)
        ),
    )
