"""One typed PDF dispatch shared by the local CLI and fixed-unit entry point."""

from pathlib import Path

from eom_kakao_archive_contracts.pdf_contracts import PdfCommand, PdfResult
from eom_kakao_archive_contracts.study import StudyRenderCommand

from .question_pdf import render_questions
from .study_pdf import render_study


def render_pdf(
    command: PdfCommand,
    *,
    input_root: Path,
    output_root: Path,
    renderer_release_sha256: str,
) -> PdfResult:
    # Keep the two command types narrowed at their renderer boundary, not an untyped registry.
    if isinstance(command, StudyRenderCommand):
        return render_study(
            command,
            input_root=input_root,
            output_root=output_root,
            renderer_release_sha256=renderer_release_sha256,
        )
    return render_questions(
        command,
        input_root=input_root,
        output_root=output_root,
        renderer_release_sha256=renderer_release_sha256,
    )
