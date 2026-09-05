"""Isolated renderer for the immutable content-team HwpQuestionEditor handoff."""

from __future__ import annotations

import importlib
import json
import os
import stat
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from eom_hwpx_contracts import (
    ContentTeamBuildResult,
    ContentTeamEditorialDraft,
    ContentTeamRenderRequest,
    parse_content_team_markdown,
    serialize_content_team_markdown,
    validate_contract,
)
from pydantic import ValidationError

from eom_hwpx_builder.analyzer import analyze_package
from eom_hwpx_builder.content_team_handoff import (
    EXPECTED_MEMBER_HASHES,
    ContentTeamHandoffEvidence,
    inspect_content_team_handoff,
)
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.handoff import (
    finalize_failure_result,
    finalize_success_handoff,
    prepare_private_handoff_file,
    write_private_json,
)
from eom_hwpx_builder.util import sha256_bytes, sha256_file

CONTENT_TEAM_RENDERER_VERSION = "1.0.0"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_SOURCE_MEMBER_BYTES = 1024 * 1024
SOURCE_PREFIX = "HwpQuestionEditor_handoff_export/source_snapshot/src/hwp_question_editor/"
PROTOTYPE_TARGETS = {
    "automation-template": "templates/automation.hwpx",
    "equation-prototypes": "templates/prototypes/v02_equation_prototypes.hwpx",
    "visual-slots-left-right": "templates/prototypes/v03_image_slot/visual_slots_left_right.hwpx",
    "visual-slots-two-tables": "templates/prototypes/v03_image_slot/visual_slots_two_tables.hwpx",
    "labeled-data-condition": (
        "templates/prototypes/v03_labeled_blocks/labeled_data_condition_basic.hwpx"
    ),
    "table-2-column": "templates/prototypes/v03_tables/table_2col_basic.hwpx",
    "table-3-column": "templates/prototypes/v03_tables/table_3col_basic.hwpx",
    "table-3-column-long-equation": (
        "templates/prototypes/v03_tables/table_3col_multibody_long_equation.hwpx"
    ),
    "table-4-column": "templates/prototypes/v03_tables/table_4col_basic.hwpx",
    "inquiry-experiment-box": (
        "templates/prototypes/v04_inquiry_experiment/inquiry_experiment_form.hwpx"
    ),
}


def _workspace_path(workspace: Path, relative: str, *, must_exist: bool = True) -> Path:
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts or "\\" in relative:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "workspace path is unsafe")
    root = workspace.resolve(strict=True)
    target = workspace.joinpath(*value.parts)
    resolved = target.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "workspace path escaped root")
    return resolved


def _read_regular(path: Path, *, max_bytes: int, expected_sha256: str) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "input cannot be opened") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= max_bytes:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "input metadata is unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "input was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "input grew while reading")
        data = b"".join(chunks)
        after = os.fstat(descriptor)

        def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after) or sha256_bytes(data) != expected_sha256:
            raise HwpxError(HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH, "input hash changed")
        return data
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("exclusive write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _extract_runtime(
    archive_path: Path,
    evidence: ContentTeamHandoffEvidence,
    runtime: Path,
) -> Path:
    runtime.mkdir(mode=0o700)
    by_purpose = {member.purpose: member for member in evidence.members}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = {info.filename: info for info in archive.infolist()}
            source_names = tuple(
                sorted(
                    name
                    for name in infos
                    if name.startswith(SOURCE_PREFIX)
                    and name.endswith(".py")
                    and not infos[name].is_dir()
                )
            )
            if not source_names or len(source_names) > 80:
                raise HwpxError(
                    HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
                    "handoff source module set is invalid",
                )
            for name in source_names:
                relative = PurePosixPath(name.removeprefix(SOURCE_PREFIX))
                info = infos[name]
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or info.file_size > MAX_SOURCE_MEMBER_BYTES
                ):
                    raise HwpxError(
                        HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
                        "handoff source member is unsafe",
                    )
                data = archive.read(info)
                if len(data) != info.file_size:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
                        "handoff source member changed",
                    )
                _write_exclusive(runtime / "src/hwp_question_editor" / relative, data)
            for purpose, target_name in PROTOTYPE_TARGETS.items():
                member = by_purpose[purpose]
                prototype_info = infos.get(member.archive_member)
                if prototype_info is None or prototype_info.file_size != member.size:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                        "handoff prototype member is unavailable",
                    )
                data = archive.read(prototype_info)
                if len(data) != member.size or sha256_bytes(data) != member.sha256:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                        "handoff prototype member changed",
                    )
                _write_exclusive(runtime / target_name, data)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
            "handoff runtime extraction failed",
        ) from exc
    return runtime / "templates/automation.hwpx"


def _load_draft(raw: bytes) -> ContentTeamEditorialDraft:
    try:
        value: object = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != "2.0":
            raise ValueError("item content schema version mismatch")
        editorial = dict(value)
        editorial.pop("schema_version")
        return ContentTeamEditorialDraft.model_validate(editorial)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
            "content-team item JSON is invalid",
        ) from exc


def _content_team_engine(engine_module: Any) -> Any:
    """Adapt one reviewed handoff defect without modifying its immutable source.

    The handoff's labeled-block path asks for the Q_STEM marker's paragraph after
    its mixed-content renderer has replaced (and detached) that marker element.
    Other mixed-content paths retain the paragraph before rendering. Preserve
    that same paragraph identity while leaving parsing, XML mutation, prototype
    cloning, and validation owned by the reviewed handoff engine.
    """

    class CompatibleEngine(engine_module.HwpxTemplateEngine):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self._detached_marker_context: tuple[Any, Any] | None = None

        def _render_q_stem_paragraph_prefix(
            self,
            *,
            root: Any,
            marker_text: Any,
            marker: str,
            paragraph_text: str,
            template_path: Path,
        ) -> None:
            paragraph = self._paragraph_for_element(marker_text)
            super()._render_q_stem_paragraph_prefix(
                root=root,
                marker_text=marker_text,
                marker=marker,
                paragraph_text=paragraph_text,
                template_path=template_path,
            )
            if marker_text.getparent() is None:
                self._detached_marker_context = (marker_text, paragraph)

        def _paragraph_for_element(self, element: Any) -> Any:
            try:
                return super()._paragraph_for_element(element)
            except engine_module.HwpxTemplateError:
                context = self._detached_marker_context
                if context is None or context[0] is not element:
                    raise
                return context[1]

    return CompatibleEngine()


def _content_team_validator_class(validator_module: Any, question: Any) -> Any:
    """Disambiguate authored ``[풀이] 참조`` from removed template samples."""

    intentional_references = frozenset(
        f"{label}. [풀이] 참조"
        for label, body in (
            ("ㄱ", question.solution_ga),
            ("ㄴ", question.solution_na),
            ("ㄷ", question.solution_da),
        )
        if body.strip() == "[풀이] 참조"
    )

    class InputAwareValidator(validator_module.HwpxValidator):  # type: ignore[misc]
        def validate(self, *args: Any, **kwargs: Any) -> Any:
            result = super().validate(*args, **kwargs)
            issues = tuple(
                issue
                for issue in result.issues
                if not (
                    issue.code == "SAMPLE_CONTENT_REMAINING"
                    and issue.member == validator_module.SECTION_MEMBER
                    and any(
                        issue.message == f"table 7 sample explanation paragraph remains: {text!r}"
                        for text in intentional_references
                    )
                )
            )
            return validator_module.ValidationResult(path=result.path, issues=issues)

    return InputAwareValidator


def _external_render(
    runtime: Path,
    template: Path,
    markdown: bytes,
    output: Path,
    draft: ContentTeamEditorialDraft,
) -> dict[str, Any]:
    source_root = runtime / "src"
    sys.path.insert(0, str(source_root))
    try:
        parser_module = importlib.import_module("hwp_question_editor.services.question_parser")
        equation_module = importlib.import_module("hwp_question_editor.services.equation_preflight")
        engine_module = importlib.import_module("hwp_question_editor.services.hwpx_template_engine")
        validator_module = importlib.import_module("hwp_question_editor.services.hwpx_validator")
        question = parser_module.QuestionParser().parse(
            markdown.decode("utf-8"),
            question_name=f"item-{draft.item_number}",
        )
        equation_report = equation_module.EquationPreflight().assert_supported(question)
        dynamic_validator_module: Any = validator_module
        validator_class = _content_team_validator_class(dynamic_validator_module, question)
        engine = _content_team_engine(engine_module)
        original_validator = dynamic_validator_module.HwpxValidator
        dynamic_validator_module.HwpxValidator = validator_class
        try:
            engine.create_document(template, output, question)
        finally:
            dynamic_validator_module.HwpxValidator = original_validator
        validator_class(template).assert_valid(
            output,
            expected_labeled_blocks=tuple(block.kind for block in draft.labeled_blocks),
            expected_answer_combination=question.answer_combination,
        )
        return {
            "status": "PASS",
            "equation_count": equation_report.total_equation_count,
            "table_count": len(engine.last_table_render_reports),
            "visual_count": len(draft.visuals),
            "labeled_block_count": len(draft.labeled_blocks),
            "inquiry": draft.inquiry is not None,
            "visual_layout": draft.visual_layout,
        }
    except Exception as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED,
            "content-team handoff renderer rejected the item",
        ) from exc
    finally:
        if sys.path and sys.path[0] == str(source_root):
            sys.path.pop(0)


def _manifest(
    output: Path,
    request: ContentTeamRenderRequest,
    report: dict[str, Any],
) -> dict[str, Any]:
    analysis = analyze_package(output)
    if (
        analysis.mimetype != "application/hwp+zip"
        or analysis.active_content
        or analysis.external_links
        or not analysis.sections
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team HWPX failed the EOM package safety boundary",
        )
    return {
        "manifest_version": "content-team-hwpx/1.0",
        "renderer_profile": request.renderer_profile,
        "renderer_version": CONTENT_TEAM_RENDERER_VERSION,
        "source": request.source.model_dump(mode="json"),
        "handoff": request.handoff.model_dump(mode="json"),
        "file_name": output.name,
        "media_type": "application/hwp+zip",
        "package_sha256": analysis.package_sha256,
        "renderer_report": report,
        "entries": [entry.model_dump(mode="json") for entry in analysis.entries],
        "warnings": list(analysis.warnings),
    }


def render_content_team_workspace(
    request_path: Path,
    result_path: Path,
) -> ContentTeamBuildResult:
    started = datetime.now(UTC)
    workspace = request_path.parent.resolve(strict=True)
    if result_path.resolve(strict=False).parent != workspace or result_path.name != "result.json":
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "result path escaped workspace")
    try:
        request_raw: dict[str, Any] = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "render request is invalid") from exc
    validate_contract("content-team-render-request", request_raw)
    request = ContentTeamRenderRequest.model_validate(request_raw)

    source_json = _workspace_path(workspace, request.source.json_file)
    source_markdown = _workspace_path(workspace, request.source.markdown_file)
    handoff_archive = _workspace_path(workspace, request.handoff.archive_file)
    json_bytes = _read_regular(
        source_json, max_bytes=MAX_JSON_BYTES, expected_sha256=request.source.json_sha256
    )
    markdown_bytes = _read_regular(
        source_markdown,
        max_bytes=MAX_MARKDOWN_BYTES,
        expected_sha256=request.source.markdown_sha256,
    )
    _read_regular(
        handoff_archive,
        max_bytes=64 * 1024 * 1024,
        expected_sha256=request.handoff.archive_sha256,
    )
    draft = _load_draft(json_bytes)
    if serialize_content_team_markdown(draft) != markdown_bytes:
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
            "content-team JSON and Markdown do not describe the same item",
        )
    parsed = parse_content_team_markdown(markdown_bytes)
    if parsed.source_sha256 != request.source.markdown_sha256:
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
            "content-team Markdown hash differs from its parsed identity",
        )
    evidence = inspect_content_team_handoff(handoff_archive)
    actual_members = tuple(
        (member.purpose, member.sha256, member.size) for member in evidence.members
    )
    declared_members = tuple(
        (member.purpose, member.sha256, member.size) for member in request.handoff.members
    )
    if (
        evidence.entry_count != request.handoff.entry_count
        or evidence.uncompressed_bytes != request.handoff.uncompressed_bytes
        or actual_members != declared_members
        or {member.purpose: member.sha256 for member in evidence.members}
        != dict(EXPECTED_MEMBER_HASHES)
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
            "content-team handoff evidence differs from the request snapshot",
        )
    runtime = _workspace_path(workspace, "runtime", must_exist=False)
    template = _extract_runtime(handoff_archive, evidence, runtime)
    output_dir = _workspace_path(workspace, request.output_directory, must_exist=False)
    if output_dir.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "output must be fresh")
    output_dir.mkdir(mode=0o700)
    output = output_dir / "content-team-item.hwpx"
    report = _external_render(runtime, template, markdown_bytes, output, draft)
    package_manifest = _manifest(output, request, report)
    write_private_json(output_dir / "content-team-validation.json", report)
    write_private_json(output_dir / "package-manifest.json", package_manifest)
    prepare_private_handoff_file(output)
    result = ContentTeamBuildResult(
        build_id=request.build_id,
        item_revision_id=request.item_revision_id,
        source_artifact_id=request.source.artifact_id,
        source_artifact_revision_id=request.source.artifact_revision_id,
        source_json_sha256=request.source.json_sha256,
        source_markdown_sha256=request.source.markdown_sha256,
        handoff_archive_sha256=request.handoff.archive_sha256,
        status="SUCCEEDED",
        output_file="output/content-team-item.hwpx",
        output_sha256=sha256_file(output),
        package_manifest_file="output/package-manifest.json",
        renderer_report_file="output/content-team-validation.json",
        equation_count=int(report["equation_count"]),
        table_count=int(report["table_count"]),
        visual_count=int(report["visual_count"]),
        labeled_block_count=int(report["labeled_block_count"]),
        warnings=(),
        errors=(),
        started_at=started,
        completed_at=datetime.now(UTC),
    )
    validate_contract("content-team-build-result", result.model_dump(mode="json"))
    write_private_json(result_path, result.model_dump(mode="json"))
    finalize_success_handoff(
        workspace,
        result_path,
        output_file_names=(
            "content-team-item.hwpx",
            "content-team-validation.json",
            "package-manifest.json",
        ),
    )
    return result


def failed_content_team_result(
    request_path: Path,
    result_path: Path,
    started: datetime,
    error: Exception,
) -> ContentTeamBuildResult | None:
    try:
        request = ContentTeamRenderRequest.model_validate_json(
            request_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError):
        return None
    code = error.code.value if isinstance(error, HwpxError) else "HWPX_CONTENT_TEAM_RENDER_FAILED"
    result = ContentTeamBuildResult(
        build_id=request.build_id,
        item_revision_id=request.item_revision_id,
        source_artifact_id=request.source.artifact_id,
        source_artifact_revision_id=request.source.artifact_revision_id,
        source_json_sha256=request.source.json_sha256,
        source_markdown_sha256=request.source.markdown_sha256,
        handoff_archive_sha256=request.handoff.archive_sha256,
        status="FAILED",
        output_file=None,
        output_sha256=None,
        package_manifest_file=None,
        renderer_report_file=None,
        equation_count=0,
        table_count=0,
        visual_count=0,
        labeled_block_count=0,
        warnings=(),
        errors=(code,),
        started_at=started,
        completed_at=datetime.now(UTC),
    )
    validate_contract("content-team-build-result", result.model_dump(mode="json"))
    write_private_json(result_path, result.model_dump(mode="json"))
    finalize_failure_result(request_path.parent.resolve(strict=True), result_path)
    return result
