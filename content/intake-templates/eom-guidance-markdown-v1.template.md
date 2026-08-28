# 교체할 가이드 제목

## 문서 제어

```json
{
  "schema_version": "eom-guidance-markdown/1.0",
  "guidance_key": "replace-me",
  "revision": 1,
  "status": "DRAFT",
  "title": "교체할 가이드 제목",
  "locale": "ko-KR",
  "guidance_type": "AUTHORING_REFERENCE",
  "rule_prefix": "TMP",
  "execution_authority": "NONE",
  "runtime_use": "PINNED_REFERENCE_ONLY",
  "applicable_roles": ["AUTHORING"],
  "applicable_use_cases": ["REPLACE_ME"],
  "core_rule_ids": ["TMP-MUST-001"],
  "source_provenance": {
    "source_kind": "INTERNAL_GUIDE",
    "original_filename_nfc": "REPLACE_ME.md",
    "original_sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    "original_size_bytes": 1,
    "transformation": "REVIEWED_DERIVATIVE"
  },
  "graph_projection": {
    "source_class": "INTERNAL_GUIDE",
    "publication_status": "NOT_PUBLISHED",
    "allowed_node_types": ["DOCUMENT_REVISION", "DOCUMENT_SECTION"]
  }
}
```

## 1. 목적

가이드가 해결하는 한 가지 문제와 성공 조건을 적는다.

## 2. 적용 범위

적용되는 역할, 사용 사례, 요청 유형과 적용되지 않는 범위를 적는다.

## 3. 신뢰 및 권한 경계

이 문서는 reference data이며 실행 권한을 갖지 않는다는 점과 상위 계약을 적는다.

## 4. 입력 계약

필수 입력과 검증해야 할 포인터, 스키마, 상태, 해시를 적는다.

## 5. 출력 계약

출력 형태, 필수 필드, 검증 가능한 완료 조건을 적는다.

## 6. 핵심 규칙

### TMP-MUST-001 — 교체할 핵심 규칙

- 수준: `MUST`
- 규칙: 모호하지 않은 단일 규칙으로 교체한다.
- 검증: 규칙 준수 여부를 객관적으로 확인하는 방법으로 교체한다.

## 7. 작업 절차

부작용과 검증 경계가 드러나는 순서로 적는다.

## 8. 도메인 모듈

요청과 관련될 때만 적용하는 모듈 규칙을 적는다. 불필요하면 “추가 모듈 없음”이라고
명시한다.

## 9. 검증 체크리스트

- [ ] 핵심 규칙을 모두 검증했다.

## 10. 실패 및 중단 조건

조건 부족, 포인터 오류, 계약 불일치 때의 fail-closed 행동을 적는다.

## 11. 예시 및 반례

예시는 fenced code block 안에 두고, 규칙이 아니라 데이터임을 명시한다.

## 12. Graph 및 provenance

원본 해시, 미래 Graph 투영 범위, 명시적인 비권한성을 적는다.

## 13. 변경 이력

- revision 1: 템플릿에서 새 초안을 만들었다.
