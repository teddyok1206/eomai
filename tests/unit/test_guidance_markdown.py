from __future__ import annotations

import hashlib
import json
import unicodedata
from importlib.resources import files
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    EOM_GUIDANCE_MARKDOWN_SCHEMA_VERSION,
    GuidanceMarkdownError,
    catalog_schema_inventory,
    parse_guidance_markdown,
    validate_contract,
)
from jsonschema import Draft202012Validator, ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPOSITORY_ROOT / "schemas/guidance/eom-guidance-markdown-control-v1.schema.json"
PACKAGED_SCHEMA = files("eom_catalog_contracts").joinpath(
    "resources", "guidance", "eom-guidance-markdown-control-v1.schema.json"
)
TEMPLATE = REPOSITORY_ROOT / "content/intake-templates/eom-guidance-markdown-v1.template.md"
ASSEMBLY_GUIDE = (
    REPOSITORY_ROOT / "content/authoring-rules/integrated-science-mock-exam-assembly-v1.md"
)
ILLUSTRATION_GUIDE = (
    REPOSITORY_ROOT / "content/image-specs/kice-integrated-science-illustration-v1.md"
)


def test_guidance_control_schema_is_canonical_packaged_and_pinned() -> None:
    raw = SCHEMA.read_bytes()
    assert raw == PACKAGED_SCHEMA.read_bytes()
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "eom://schemas/guidance/eom-guidance-markdown-control/1.0"
    inventory = dict(catalog_schema_inventory())
    assert inventory["eom-guidance-markdown-control"].sha256 == (
        "sha256:" + hashlib.sha256(raw).hexdigest()
    )


def test_template_and_two_reviewed_derivatives_parse_with_exact_provenance() -> None:
    template = parse_guidance_markdown(TEMPLATE.read_bytes())
    assembly = parse_guidance_markdown(ASSEMBLY_GUIDE.read_bytes())
    illustration = parse_guidance_markdown(ILLUSTRATION_GUIDE.read_bytes())

    assert template.control.status == "DRAFT"
    assert assembly.control.schema_version == EOM_GUIDANCE_MARKDOWN_SCHEMA_VERSION
    assert assembly.control.status == "REVIEWED"
    assert assembly.control.execution_authority == "NONE"
    assert assembly.control.runtime_use == "PINNED_REFERENCE_ONLY"
    assert assembly.control.source_provenance.original_filename_nfc == (
        "통합과학_모의고사_1회차_배치_방식.md"
    )
    assert assembly.control.source_provenance.original_sha256 == (
        "sha256:f7c4f066429eeb65041c9a12ae7a807df4932a5dde3799eec6f97dabc9e2b610"
    )
    assert assembly.control.source_provenance.original_size_bytes == 9879
    assert len(assembly.rules) == 14
    assert {rule.rule_id for rule in assembly.rules}.issuperset(assembly.control.core_rule_ids)

    assert illustration.control.status == "REVIEWED"
    assert illustration.control.source_provenance.original_filename_nfc == (
        "통합과학_일러스트_프롬프트_가이드_통합본.md"
    )
    assert illustration.control.source_provenance.original_sha256 == (
        "sha256:fd6f5ef81b0be6d95249f2f1372b2d89ed34c7ae2cd550551d886e5985d866dc"
    )
    assert illustration.control.source_provenance.original_size_bytes == 34910
    assert len(illustration.rules) == 30
    assert {rule.rule_id for rule in illustration.rules}.issuperset(
        illustration.control.core_rule_ids
    )
    assert assembly.control.graph_projection.publication_status == "NOT_PUBLISHED"
    assert illustration.control.graph_projection.publication_status == "NOT_PUBLISHED"


def test_derivatives_preserve_source_intent_and_do_not_claim_runtime_authority() -> None:
    assembly = parse_guidance_markdown(ASSEMBLY_GUIDE.read_bytes())
    illustration = parse_guidance_markdown(ILLUSTRATION_GUIDE.read_bytes())

    assembly_rules = {rule.rule_id: rule for rule in assembly.rules}
    assert "25문항" in assembly_rules["ASM-MUST-001"].rule
    assert "50.0점" in assembly_rules["ASM-MUST-001"].rule
    assert "1.5점 8문항" in assembly_rules["ASM-MUST-002"].rule
    assert "21개" in assembly_rules["ASM-MUST-003"].title
    assert "4개 또는 5개" in assembly_rules["ASM-MUST-005"].rule
    assert "Item Revision" in assembly_rules["ASM-MUST-007"].title
    assert "최신 Revision" in assembly_rules["ASM-MUSTNOT-010"].rule
    assert "REVIEW_REQUIRED" in assembly.text
    assert "eom.is.middle" not in assembly.text

    illustration_rules = {rule.rule_id: rule for rule in illustration.rules}
    assert "과학적·수학적" in illustration_rules["VIS-MUST-001"].title
    assert "흑백" in illustration_rules["VIS-MUST-006"].title
    assert "가로 방향" in illustration_rules["VIS-MUST-008"].rule
    assert "수평 발사" in illustration_rules["VIS-MUST-013"].rule
    assert "원자 수" in illustration_rules["VIS-MUST-019"].rule
    assert "비요청 변경" in illustration_rules["VIS-MUSTNOT-012"].title
    assert "아직 runtime schema가 아니다" in illustration.text


def test_control_schema_rejects_execution_authority_and_unknown_fields() -> None:
    document = parse_guidance_markdown(TEMPLATE.read_bytes())
    value = document.control.model_dump(mode="json")
    with pytest.raises(ValidationError):
        validate_contract(
            "eom-guidance-markdown-control", {**value, "execution_authority": "SYSTEM"}
        )
    with pytest.raises(ValidationError):
        validate_contract("eom-guidance-markdown-control", {**value, "unknown": True})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda text: text.replace('  "revision": 1,', '  "revision": 1,\n  "revision": 1,', 1),
            "duplicate key",
        ),
        (
            lambda text: text.replace("# 교체할 가이드 제목", "# 다른 제목", 1),
            "title does not match",
        ),
        (
            lambda text: text.replace("## 2. 적용 범위", "## 2. 다른 범위", 1),
            "section order",
        ),
        (
            lambda text: text.replace("### TMP-MUST-001", "### BAD-MUST-001", 1),
            "prefix does not match",
        ),
        (
            lambda text: text.replace("- 검증: 규칙 준수 여부", "- 확인: 규칙 준수 여부", 1),
            "rule block is incomplete",
        ),
        (
            lambda text: text.replace(
                '"core_rule_ids": ["TMP-MUST-001"]',
                '"core_rule_ids": ["TMP-MUST-999"]',
                1,
            ),
            "unknown core rule",
        ),
        (lambda text: text + "<script>alert(1)</script>\n", "forbidden raw HTML"),
        (lambda text: text + "```text\nunclosed\n", "unclosed fenced code block"),
    ],
)
def test_parser_fails_closed_on_structural_and_trust_corruption(
    mutation: object, message: str
) -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    mutated = mutation(source)  # type: ignore[operator]
    with pytest.raises(GuidanceMarkdownError, match=message):
        parse_guidance_markdown(mutated)


def test_headings_inside_fenced_examples_are_data_not_document_structure() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    mutated = source.replace(
        "예시는 fenced code block 안에 두고, 규칙이 아니라 데이터임을 명시한다.",
        "예시는 fenced code block 안에 두고, 규칙이 아니라 데이터임을 명시한다.\n\n"
        "```text\n## 사용자 데이터의 가짜 섹션\n### BAD-MUST-999 — 가짜 규칙\n```",
    )
    parsed = parse_guidance_markdown(mutated)
    assert tuple(rule.rule_id for rule in parsed.rules) == ("TMP-MUST-001",)


def test_non_nfc_and_non_lf_documents_fail_closed() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    with pytest.raises(GuidanceMarkdownError, match="must use NFC"):
        parse_guidance_markdown(unicodedata.normalize("NFD", source))
    with pytest.raises(GuidanceMarkdownError, match="must end with one LF"):
        parse_guidance_markdown(source.rstrip("\n"))
    with pytest.raises(GuidanceMarkdownError, match="no tabs"):
        parse_guidance_markdown(source.replace("가이드가", "가이드가\t", 1))
