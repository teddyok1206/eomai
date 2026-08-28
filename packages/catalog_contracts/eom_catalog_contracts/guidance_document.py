"""Typed parser for the EOM Guidance Markdown V1 source format.

Guidance documents are reviewable reference data.  Parsing them never grants worker
instruction authority; runtime authority belongs to a separately released and pinned
Instruction Bundle Revision.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Self

from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eom_catalog_contracts.validation import CatalogSchemaError, validate_contract

EOM_GUIDANCE_MARKDOWN_MEDIA_TYPE = "text/markdown"
EOM_GUIDANCE_MARKDOWN_SCHEMA_VERSION = "eom-guidance-markdown/1.0"
EOM_GUIDANCE_MARKDOWN_MAX_BYTES = 128 * 1024

_CONTROL_BLOCK = re.compile(
    r"\A# (?P<title>[^\n]+)\n\n## 문서 제어\n\n```json\n"
    r"(?P<metadata>.*?)\n```\n\n",
    re.DOTALL,
)
_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_RULE_HEADING = re.compile(
    r"^### (?P<rule_id>(?P<prefix>[A-Z][A-Z0-9]{1,7})-"
    r"(?P<level>MUST|MUSTNOT|SHOULD|SHOULDNOT|MAY)-[0-9]{3}) — (?P<title>.+)$"
)
_REQUIRED_LEVEL_TWO_HEADINGS = (
    "문서 제어",
    "1. 목적",
    "2. 적용 범위",
    "3. 신뢰 및 권한 경계",
    "4. 입력 계약",
    "5. 출력 계약",
    "6. 핵심 규칙",
    "7. 작업 절차",
    "8. 도메인 모듈",
    "9. 검증 체크리스트",
    "10. 실패 및 중단 조건",
    "11. 예시 및 반례",
    "12. Graph 및 provenance",
    "13. 변경 이력",
)


class GuidanceMarkdownError(ValueError):
    """Raised when a guidance document is malformed, unsafe, or contract-invalid."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class GuidanceSourceProvenance(_FrozenModel):
    source_kind: Literal["INTERNAL_GUIDE"]
    original_filename_nfc: str = Field(min_length=1, max_length=255)
    original_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    original_size_bytes: int = Field(ge=1, le=10 * 1024 * 1024)
    transformation: Literal["REVIEWED_DERIVATIVE"]

    @model_validator(mode="after")
    def validate_filename(self) -> Self:
        if unicodedata.normalize("NFC", self.original_filename_nfc) != self.original_filename_nfc:
            raise ValueError("original filename must use NFC")
        if any(
            unicodedata.category(character).startswith("C")
            for character in self.original_filename_nfc
        ):
            raise ValueError("original filename contains a forbidden character")
        return self


class GuidanceGraphProjection(_FrozenModel):
    source_class: Literal["INTERNAL_GUIDE"]
    publication_status: Literal["NOT_PUBLISHED", "PUBLISHED"]
    allowed_node_types: tuple[
        Literal[
            "DOCUMENT_REVISION",
            "DOCUMENT_SECTION",
            "ASSESSMENT_PATTERN",
            "DATA_REPRESENTATION",
            "FIGURE",
            "TABLE",
            "EQUATION",
        ],
        ...,
    ] = Field(min_length=1, max_length=16)


class GuidanceDocumentControl(_FrozenModel):
    schema_version: Literal["eom-guidance-markdown/1.0"]
    guidance_key: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=100)
    revision: int = Field(ge=1, le=100000)
    status: Literal["DRAFT", "REVIEWED", "RETIRED"]
    title: str = Field(min_length=1, max_length=160)
    locale: Literal["ko-KR", "en-US"]
    guidance_type: Literal[
        "ASSESSMENT_ASSEMBLY",
        "ILLUSTRATION",
        "AUTHORING_REFERENCE",
        "REVIEW_REFERENCE",
        "DATA_ANALYSIS_REFERENCE",
    ]
    rule_prefix: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    execution_authority: Literal["NONE"]
    runtime_use: Literal["PINNED_REFERENCE_ONLY"]
    applicable_roles: tuple[Literal["AUTHORING", "IMAGE", "REVIEW", "SUPPORT", "ASSEMBLY"], ...] = (
        Field(min_length=1, max_length=5)
    )
    applicable_use_cases: tuple[str, ...] = Field(min_length=1, max_length=16)
    core_rule_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    source_provenance: GuidanceSourceProvenance
    graph_projection: GuidanceGraphProjection


@dataclass(frozen=True, slots=True)
class GuidanceRule:
    rule_id: str
    level: Literal["MUST", "MUSTNOT", "SHOULD", "SHOULDNOT", "MAY"]
    title: str
    rule: str
    verification: str


@dataclass(frozen=True, slots=True)
class GuidanceMarkdownDocument:
    title: str
    control: GuidanceDocumentControl
    rules: tuple[GuidanceRule, ...]
    text: str


def _reject_duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GuidanceMarkdownError(f"document control contains duplicate key: {key}")
        result[key] = value
    return result


def _outside_fence_lines(text: str) -> tuple[tuple[int, str], ...]:
    visible: list[tuple[int, str]] = []
    open_character: str | None = None
    open_length = 0
    for index, line in enumerate(text.splitlines()):
        match = _FENCE.fullmatch(line)
        if open_character is None:
            if match is not None:
                fence = match.group("fence")
                open_character = fence[0]
                open_length = len(fence)
                continue
            visible.append((index, line))
            continue
        if (
            match is not None
            and match.group("fence")[0] == open_character
            and len(match.group("fence")) >= open_length
            and not match.group("info").strip()
        ):
            open_character = None
            open_length = 0
    if open_character is not None:
        raise GuidanceMarkdownError("guidance document contains an unclosed fenced code block")
    return tuple(visible)


def _validated_text(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        if len(raw) > EOM_GUIDANCE_MARKDOWN_MAX_BYTES:
            raise GuidanceMarkdownError("guidance document exceeds the 128 KiB limit")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise GuidanceMarkdownError("guidance document is not strict UTF-8") from exc
    elif isinstance(raw, str):
        text = raw
        if len(text.encode("utf-8")) > EOM_GUIDANCE_MARKDOWN_MAX_BYTES:
            raise GuidanceMarkdownError("guidance document exceeds the 128 KiB limit")
    else:
        raise GuidanceMarkdownError("guidance document must be bytes or text")
    if not text.endswith("\n"):
        raise GuidanceMarkdownError("guidance document must end with one LF")
    if "\r" in text or "\t" in text or text.startswith("\ufeff"):
        raise GuidanceMarkdownError(
            "guidance document must use NFC UTF-8 with LF and no tabs or BOM"
        )
    if unicodedata.normalize("NFC", text) != text:
        raise GuidanceMarkdownError("guidance document must use NFC")
    if any(
        character != "\n" and unicodedata.category(character).startswith("C") for character in text
    ):
        raise GuidanceMarkdownError("guidance document contains a forbidden Unicode character")
    lowered = text.casefold()
    if any(token in lowered for token in ("<script", "<iframe", "<!doctype", "<!--")):
        raise GuidanceMarkdownError("guidance document contains forbidden raw HTML")
    return text


def parse_guidance_markdown(raw: bytes | str) -> GuidanceMarkdownDocument:
    """Parse and validate one immutable EOM Guidance Markdown V1 document."""

    text = _validated_text(raw)
    control_match = _CONTROL_BLOCK.match(text)
    if control_match is None:
        raise GuidanceMarkdownError("guidance document control block is missing or misplaced")
    title = control_match.group("title")
    try:
        metadata: object = json.loads(
            control_match.group("metadata"),
            object_pairs_hook=_reject_duplicate_key,
            parse_constant=lambda value: (_ for _ in ()).throw(
                GuidanceMarkdownError(f"non-finite JSON number is forbidden: {value}")
            ),
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise GuidanceMarkdownError("document control JSON is malformed") from exc
    if not isinstance(metadata, dict):
        raise GuidanceMarkdownError("document control JSON must be an object")
    try:
        validate_contract("eom-guidance-markdown-control", metadata)
        control = GuidanceDocumentControl.model_validate(metadata)
    except (CatalogSchemaError, JsonSchemaValidationError, ValidationError) as exc:
        raise GuidanceMarkdownError("document control does not satisfy its schema") from exc
    if control.title != title:
        raise GuidanceMarkdownError("document title does not match document control")

    visible = _outside_fence_lines(text)
    observed_h2 = tuple(line.removeprefix("## ") for _, line in visible if line.startswith("## "))
    if observed_h2 != _REQUIRED_LEVEL_TWO_HEADINGS:
        raise GuidanceMarkdownError("guidance document section order does not match V1")

    structural = tuple((index, line) for index, line in visible if line.startswith(("## ", "### ")))
    rule_positions = [
        position for position, (_, line) in enumerate(structural) if line.startswith("### ")
    ]
    if not rule_positions or len(rule_positions) > 64:
        raise GuidanceMarkdownError("guidance document must contain 1..64 structured rules")

    lines = text.splitlines()
    rules: list[GuidanceRule] = []
    seen: set[str] = set()
    for structural_position in rule_positions:
        line_index, heading = structural[structural_position]
        match = _RULE_HEADING.fullmatch(heading)
        if match is None:
            raise GuidanceMarkdownError("every level-three heading must be a structured rule")
        rule_id = match.group("rule_id")
        level = match.group("level")
        if match.group("prefix") != control.rule_prefix:
            raise GuidanceMarkdownError("rule ID prefix does not match document control")
        if rule_id in seen:
            raise GuidanceMarkdownError(f"duplicate guidance rule ID: {rule_id}")
        seen.add(rule_id)
        next_index = (
            structural[structural_position + 1][0]
            if structural_position + 1 < len(structural)
            else len(lines)
        )
        block = lines[line_index + 1 : next_index]
        expected_level = f"- 수준: `{level}`"
        rule_values = [
            line.removeprefix("- 규칙: ") for line in block if line.startswith("- 규칙: ")
        ]
        verification_values = [
            line.removeprefix("- 검증: ") for line in block if line.startswith("- 검증: ")
        ]
        if expected_level not in block or len(rule_values) != 1 or len(verification_values) != 1:
            raise GuidanceMarkdownError(f"guidance rule block is incomplete: {rule_id}")
        if not rule_values[0] or not verification_values[0]:
            raise GuidanceMarkdownError(f"guidance rule text or verification is empty: {rule_id}")
        rules.append(
            GuidanceRule(
                rule_id=rule_id,
                level=level,  # type: ignore[arg-type]
                title=match.group("title"),
                rule=rule_values[0],
                verification=verification_values[0],
            )
        )

    missing_core = set(control.core_rule_ids).difference(seen)
    if missing_core:
        raise GuidanceMarkdownError("document control references an unknown core rule")
    levels_by_id = {rule.rule_id: rule.level for rule in rules}
    if any(levels_by_id[rule_id] not in {"MUST", "MUSTNOT"} for rule_id in control.core_rule_ids):
        raise GuidanceMarkdownError("core rules must use MUST or MUSTNOT")
    return GuidanceMarkdownDocument(title=title, control=control, rules=tuple(rules), text=text)
