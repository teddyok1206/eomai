"""Exact closed PDF families shared by staging, stopped-output recovery and publication.

These functions validate already defined wire schemas; they grant no execution,
source or storage authority and never select an implicit latest family.
"""

from .layout import RenderLayoutReceipt, check_layout_receipt
from .render import LocalMember, RenderCommand, RenderManifest, RenderResult, render_input_members
from .study import StudyRenderCommand, StudyRenderManifest, StudyRenderResult, study_input_members
from .study_layout import StudyLayoutReceipt, check_study_layout
from .study_validation import validate_study_contract
from .validation import validate_contract

PdfCommand = RenderCommand | StudyRenderCommand
PdfManifest = RenderManifest | StudyRenderManifest
PdfResult = RenderResult | StudyRenderResult
PdfLayout = RenderLayoutReceipt | StudyLayoutReceipt


def parse_pdf_command(value: object) -> PdfCommand:
    if isinstance(value, dict) and value.get("schema_version") == "kakao-study-render/1.0":
        validate_study_contract("command", value)
        return StudyRenderCommand.model_validate(value)
    validate_contract("command", value)
    return RenderCommand.model_validate(value)


def parse_pdf_manifest(command: PdfCommand, value: object) -> PdfManifest:
    if isinstance(command, StudyRenderCommand):
        validate_study_contract("manifest", value)
        result: PdfManifest = StudyRenderManifest.model_validate(value)
    else:
        validate_contract("manifest", value)
        result = RenderManifest.model_validate(value)
    pdf_input_members(command, result)
    return result


def pdf_input_members(command: PdfCommand, manifest: PdfManifest) -> tuple[LocalMember, ...]:
    if isinstance(command, StudyRenderCommand) and isinstance(manifest, StudyRenderManifest):
        return study_input_members(command, manifest)
    if isinstance(command, RenderCommand) and isinstance(manifest, RenderManifest):
        return render_input_members(command, manifest)
    raise ValueError("KAKAO_PDF_CONTRACT_FAMILY_MISMATCH")


def parse_pdf_result(command: PdfCommand, value: object) -> PdfResult:
    if isinstance(command, StudyRenderCommand):
        validate_study_contract("result", value)
        return StudyRenderResult.model_validate(value)
    validate_contract("result", value)
    return RenderResult.model_validate(value)


def parse_pdf_layout(command: PdfCommand, manifest: PdfManifest, value: object) -> PdfLayout:
    if isinstance(command, StudyRenderCommand) and isinstance(manifest, StudyRenderManifest):
        validate_study_contract("layout", value)
        study_layout = StudyLayoutReceipt.model_validate(value)
        check_study_layout(command, manifest, study_layout)
        return study_layout
    if isinstance(command, RenderCommand) and isinstance(manifest, RenderManifest):
        validate_contract("layout", value)
        question_layout = RenderLayoutReceipt.model_validate(value)
        check_layout_receipt(command, manifest, question_layout)
        return question_layout
    raise ValueError("KAKAO_PDF_CONTRACT_FAMILY_MISMATCH")
