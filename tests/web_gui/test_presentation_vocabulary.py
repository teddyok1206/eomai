from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
VOCABULARY_PATH = ROOT / "apps/web_gui/eom_web_gui/static/presentation-vocabulary.ko-KR.json"
SCHEMA_PATH = ROOT / "schemas/web-gui/presentation-vocabulary-v1.schema.json"
APP_PATH = ROOT / "apps/web_gui/eom_web_gui/static/app.js"


def _vocabulary() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(VOCABULARY_PATH.read_text(encoding="utf-8")))


def test_presentation_vocabulary_matches_its_draft_2020_12_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    vocabulary = _vocabulary()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(vocabulary)


def test_domain_specific_states_are_human_readable() -> None:
    domains = _vocabulary()["domains"]
    expected = {
        ("workflow", "RUNNING"): "문항 제작 중",
        ("workflow", "COMPLETED"): "문항 등록 완료",
        ("knowledge_analysis", "RUNNING"): "자료 분석 중",
        ("knowledge_analysis", "ACCEPTED"): "분석 완료",
        ("hwpx_build", "VALIDATING"): "HWPX 검증 중",
        ("hwpx_build", "SUCCEEDED"): "다운로드 준비 완료",
        ("hwpx_capability", "READY"): "HWPX 제작 가능",
        ("item_revision", "APPROVED"): "사용 가능",
        ("codex_account", "DRAINING"): "새 작업 중지 중",
    }
    for (domain, raw_state), label in expected.items():
        presentation = domains[domain]["states"][raw_state]
        assert presentation["label"] == label
        assert presentation["label"] != raw_state


def test_vocabulary_preserves_distinct_pointer_identities() -> None:
    terms = _vocabulary()["terms"]
    assert terms["item_id"]["label"] == "문항 ID"
    assert terms["item_revision_id"]["label"] == "문항 버전 ID"
    assert terms["artifact_revision_id"]["label"] == "결과 파일 버전 ID"
    assert terms["sha256"]["label"] == "내용 검증값"
    assert (
        len(
            {terms[key]["label"] for key in ("item_id", "item_revision_id", "artifact_revision_id")}
        )
        == 3
    )


def test_vocabulary_names_product_surfaces_without_backend_jargon() -> None:
    terms = _vocabulary()["terms"]
    assert terms["execution_preset"]["label"] == "실행 설정"
    assert terms["analysis_batch"]["label"] == "분석 작업"
    assert terms["content_pack_release"]["label"] == "제작 기준 버전"
    assert terms["etag"]["label"] == "동시 편집 확인값"
    assert terms["application_api"]["label"] == "핵심 서비스"
    assert terms["observability"]["label"] == "운영 상태"
    assert terms["database_explorer"]["label"] == "운영 데이터 조회"


def test_known_user_errors_have_explanation_and_next_action() -> None:
    errors = _vocabulary()["errors"]
    for code in (
        "HWPX_APPLICATION_REVISION_INELIGIBLE",
        "HWPX_RENDERER_NOT_READY",
        "AUTH_REAUTHENTICATION_REQUIRED",
        "WEB_REQUEST_INVALID",
        "HTTP_500",
    ):
        assert errors[code]["label"]
        assert errors[code]["action"]
        assert code not in errors[code]["label"]


def test_gui_uses_vocabulary_only_at_the_presentation_boundary() -> None:
    javascript = APP_PATH.read_text(encoding="utf-8")
    assert "await loadPresentationVocabulary();" in javascript
    assert javascript.index("await loadPresentationVocabulary();") < javascript.index(
        "await initializeSession();"
    )
    assert "domains?.[domain]?.states?.[raw] || domains?.generic?.states?.[raw]" in javascript
    assert "element.dataset.rawState = presentation.raw;" in javascript
    assert 'label: "알 수 없는 상태"' in javascript
    assert "throw new StudioApiError(code);" in javascript
    assert "(기술 코드: ${code})" in javascript

    # Raw protocol values still drive transitions and polling. The vocabulary never changes them.
    assert '["REQUESTED", "RUNNING", "VALIDATING"].includes(value.state)' in javascript
    assert '["QUEUED", "RUNNING"].includes(value.state)' in javascript
    assert 'step.state === "SUCCEEDED"' in javascript
    assert "item_revision_id: revision" in javascript
    assert "require_native_equations: false" in javascript
    assert "require_native_tables: false" in javascript
    assert 'value.renderer_key === "item-revision-auto"' in javascript


def test_vocabulary_asset_contains_no_runtime_endpoint_or_secret_storage() -> None:
    text = VOCABULARY_PATH.read_text(encoding="utf-8")
    assert "http://" not in text
    assert "https://" not in text
    assert "Bearer " not in text
    assert "localStorage" not in text
    assert "sessionStorage" not in text
