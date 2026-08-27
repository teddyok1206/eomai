from __future__ import annotations

import hashlib

import pytest
from eom_catalog_contracts import (
    ReviewedAuthoringGuidanceError,
    normalize_reviewed_authoring_guidance,
    validate_reviewed_authoring_guidance,
)


def test_guidance_uses_one_nfc_whitespace_normalized_utf8_hash() -> None:
    value = "  문항을   자연스럽게   만들어 주세요  "
    normalized = normalize_reviewed_authoring_guidance(value)
    assert normalized == "문항을 자연스럽게 만들어 주세요"
    sha256 = "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    reviewed = validate_reviewed_authoring_guidance(value, sha256)
    assert reviewed.text == normalized
    assert reviewed.sha256 == sha256


@pytest.mark.parametrize("forbidden", ["\x01", "\u200b", "\ue000", "\u0378", "\ud800"])
def test_guidance_rejects_every_unicode_other_category(forbidden: str) -> None:
    with pytest.raises(ReviewedAuthoringGuidanceError, match="forbidden Unicode character"):
        normalize_reviewed_authoring_guidance(f"충분히 긴 문항 요청{forbidden}입니다")


@pytest.mark.parametrize("value", ["짧음", "가" * 2_001])
def test_guidance_enforces_normalized_length(value: str) -> None:
    with pytest.raises(ReviewedAuthoringGuidanceError, match=r"10\.\.2000"):
        normalize_reviewed_authoring_guidance(value)


@pytest.mark.parametrize("sha256", ["bad", "sha256:" + "0" * 64])
def test_guidance_hash_must_be_well_formed_and_match(sha256: str) -> None:
    with pytest.raises(ReviewedAuthoringGuidanceError, match="SHA-256"):
        validate_reviewed_authoring_guidance("문항을 자연스럽게 만들어 주세요", sha256)
