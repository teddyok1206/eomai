"""Study family uses the existing measured PDF writer, not a second rendering engine."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pymupdf  # type: ignore[import-untyped]
from eom_kakao_archive_contracts import canonical_bytes, sha256
from eom_kakao_archive_contracts.study import (
    StudyRenderCommand,
    StudyRenderManifest,
    StudyRenderResult,
    study_input_members,
)
from eom_kakao_archive_contracts.study_layout import (
    StudyLayoutReceipt,
    StudyPageReceipt,
    check_study_layout,
)
from eom_kakao_archive_contracts.study_validation import validate_study_contract

from .local_members import directory_descriptor, read_member
from .question_pdf import (
    LayoutReview,
    RenderImageCache,
    render_planned_question_pages,
    write_rendered_outputs,
)
from .study_pages import plan_study_pages


def render_study(
    command: StudyRenderCommand,
    *,
    input_root: Path,
    output_root: Path,
    renderer_release_sha256: str,
) -> StudyRenderResult:
    """Read only pinned local input; report review-needed without success artifacts."""
    validate_study_contract("command", command.model_dump(mode="json"))
    command_hash = sha256(canonical_bytes(command.model_dump(mode="json")))
    base = dict(
        execution=command.execution,
        schema_version="kakao-study-render-result/1.0",
        export_id=command.export_id,
        command_sha256=command_hash,
        manifest_sha256=command.manifest.sha256,
    )
    try:
        if input_root.is_relative_to(output_root) or output_root.is_relative_to(input_root):
            raise ValueError("KAKAO_RENDER_WORKSPACE_OVERLAP")
        with directory_descriptor(output_root) as directory:
            if os.listdir(directory):
                raise ValueError("KAKAO_RENDER_OUTPUT_NOT_EMPTY")
        if command.renderer_release_sha256 != renderer_release_sha256:
            raise ValueError("KAKAO_RENDER_RELEASE_MISMATCH")
        decoded = json.loads(read_member(input_root, command.manifest))
        validate_study_contract("manifest", decoded)
        manifest = StudyRenderManifest.model_validate(decoded)
        study_input_members(command, manifest)
        font_bytes = read_member(input_root, command.font)
        font = pymupdf.Font(fontbuffer=font_bytes)
        plans = plan_study_pages(manifest, font=font, cache=RenderImageCache(input_root))
        rendered = render_planned_question_pages(
            tuple(value.page for value in plans), font=font, font_bytes=font_bytes
        )
        receipt = StudyLayoutReceipt(
            schema_version="kakao-study-layout-receipt/1.0",
            command_sha256=command_hash,
            manifest_sha256=command.manifest.sha256,
            font_sha256=command.font.sha256,
            source_binding_id=command.source_binding_id,
            packet_revision_id=command.packet_revision_id,
            study_revision_id=command.study_revision_id,
            student_id=command.student_id,
            subset_sha256=command.subset_sha256,
            layout_policy=command.layout_policy,
            renderer_release_sha256=command.renderer_release_sha256,
            mode=command.mode,
            pages=tuple(
                StudyPageReceipt(
                    section=value.section.kind,
                    supplement_id=value.section.supplement_id,
                    spans=value.spans,
                    layout=page,
                )
                for value, page in zip(plans, rendered.pages, strict=True)
            ),
        )
        check_study_layout(command, manifest, receipt)
        outputs = write_rendered_outputs(
            output_root, rendered, canonical_bytes(receipt.model_dump(mode="json"))
        )
        return StudyRenderResult.model_validate(
            base
            | dict(
                status="COMPLETED",
                page_count=len(plans),
                outputs=outputs,
                error_code=None,
                question_revision_id=None,
            )
        )
    except LayoutReview as exc:
        return StudyRenderResult.model_validate(
            base
            | dict(
                status="NEEDS_LAYOUT_REVIEW",
                page_count=0,
                outputs=(),
                error_code=exc.code,
                question_revision_id=exc.revision_id,
            )
        )
    except (OSError, ValueError, RuntimeError) as exc:
        # Parser exceptions can contain private source content; never echo those details.
        code = str(exc)
        if not code.startswith(("KAKAO_RENDER_", "KAKAO_STUDY_RENDER_")) or len(code) > 80:
            code = "KAKAO_RENDER_INPUT_OR_OUTPUT_INVALID"
        return StudyRenderResult.model_validate(
            base
            | dict(
                status="INVALID_INPUT",
                page_count=0,
                outputs=(),
                error_code=code,
                question_revision_id=None,
            )
        )
