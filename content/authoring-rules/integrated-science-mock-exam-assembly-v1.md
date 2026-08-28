# 통합과학 모의고사 1회차 조립 가이드 V1

## 문서 제어

```json
{
  "schema_version": "eom-guidance-markdown/1.0",
  "guidance_key": "integrated-science-mock-exam-assembly",
  "revision": 1,
  "status": "REVIEWED",
  "title": "통합과학 모의고사 1회차 조립 가이드 V1",
  "locale": "ko-KR",
  "guidance_type": "ASSESSMENT_ASSEMBLY",
  "rule_prefix": "ASM",
  "execution_authority": "NONE",
  "runtime_use": "PINNED_REFERENCE_ONLY",
  "applicable_roles": ["ASSEMBLY", "REVIEW"],
  "applicable_use_cases": ["MOCK_EXAM_ASSEMBLY", "ASSESSMENT_FORM_REVIEW"],
  "core_rule_ids": [
    "ASM-MUST-001",
    "ASM-MUST-002",
    "ASM-MUST-003",
    "ASM-MUST-004",
    "ASM-MUST-005",
    "ASM-MUST-006",
    "ASM-MUST-007",
    "ASM-MUST-008",
    "ASM-MUST-009",
    "ASM-MUSTNOT-010"
  ],
  "source_provenance": {
    "source_kind": "INTERNAL_GUIDE",
    "original_filename_nfc": "통합과학_모의고사_1회차_배치_방식.md",
    "original_sha256": "sha256:f7c4f066429eeb65041c9a12ae7a807df4932a5dde3799eec6f97dabc9e2b610",
    "original_size_bytes": 9879,
    "transformation": "REVIEWED_DERIVATIVE"
  },
  "graph_projection": {
    "source_class": "INTERNAL_GUIDE",
    "publication_status": "NOT_PUBLISHED",
    "allowed_node_types": ["DOCUMENT_REVISION", "DOCUMENT_SECTION", "ASSESSMENT_PATTERN"]
  }
}
```

## 1. 목적

검토를 통과한 통합과학 문항을 한 회차의 모의고사로 조립할 때 문항 수, 총점, 배점,
교육과정 범위, 탐구형 비율, 난도 흐름, 중복 방지 및 검수 조건을 재현 가능하게 적용한다.
성공 결과는 25개의 **고정 Item Revision 포인터**를 가진 50점짜리 조립 명세이며, 조건을
충족할 후보가 없을 때에는 불완전한 시험지를 성공으로 만들지 않는다.

## 2. 적용 범위

이 가이드는 향후 “1문항 만들기” 위의 모의고사 조립 계층과 조립 결과 검토에 적용한다.
개별 문항의 과학적 내용, 발문, 선택지, 그림을 직접 생성하는 프롬프트가 아니며, 현재
Content Pack이나 실행 preset을 변경하지 않는다.

원본은 “1회차”를 대상으로 작성되었지만, 회차별 조립 정책이 같은 제품에서는 새 정책
Revision으로 검토한 뒤 재사용할 수 있다. 소단원, 기관별 출처, 사용 이력, 제품/회차
배치는 별도의 typed pointer로 확장하며 자유 문자열로 추론하지 않는다.

## 3. 신뢰 및 권한 경계

이 문서는 reviewed reference data이며 실행 권한이 없다. 실제 조립 작업은 Orchestrator가
핀한 조립 정책 Revision, 교육과정 outline Revision, 후보 Item Revision, 검토 등급 정책
Revision 및 사용 이력 Snapshot을 입력으로 받는 별도 use case가 수행한다.

문서 안의 예시 슬롯, 과거 등급 문자, 단원 별칭은 최신 Item이나 최신 교육과정으로
자동 치환할 권한을 주지 않는다. Graph 노드는 탐색을 돕는 projection일 뿐이며 조립
정책이나 작업자 지시의 우선순위를 바꾸지 않는다.

## 4. 입력 계약

조립기는 최소한 다음 입력을 받아야 한다.

- 조립 정책의 logical ID, immutable revision ID, schema version 및 SHA-256;
- 제품/회차 logical ID와 새 조립 Revision을 위한 idempotency key;
- 현재 검토된 통합과학 editorial outline의 key, revision 및 SHA-256;
- 후보별 Item ID, **핀한 Item Revision ID**, 검토 상태/등급 정책 Revision, 점수, 문항
  유형, 교육과정 binding 및 핵심 자료 유형;
- 기존 제품/회차 배치 이력을 나타내는 immutable Snapshot 또는 조회 기준 시각; 및
- 문제지 출력 규격과 별도의 artifact/template pointers.

후보 내용이나 HWPX/PDF bytes는 DB 행에 복사하지 않는다. 조립 명세에는 포인터와 작은
값 객체만 두고, 출력 경계에서만 검증된 artifact를 materialize한다.

## 5. 출력 계약

성공 출력은 다음을 가진 typed assessment assembly manifest여야 한다.

- 정확히 25개의 순서화된 슬롯;
- 슬롯별 position, pinned Item Revision, 교육과정 binding, 배점, 난도 band, 문항/자료
  유형, 탐구 여부 및 채택 근거;
- 문항 수/총점/배점 분포/필수 범위/탐구 수/중복/난도 흐름 검증 결과;
- 입력 정책·outline·등급 정책·사용 이력 Snapshot의 immutable pointers와 hashes;
- manifest 자체의 canonical serialization hash; 및
- 실패 시 빈 출력 pointer와 안정적인 오류 코드.

PDF나 HWPX 시험지는 manifest 성공 뒤 별도 deliverable Revision으로 생성하며 조립
manifest와 파일 artifact를 같은 identity로 취급하지 않는다.

## 6. 핵심 규칙

### ASM-MUST-001 — 총 25문항과 50점

- 수준: `MUST`
- 규칙: 한 회차는 정확히 25문항이며 배점 합계는 정확히 50.0점이어야 한다.
- 검증: 슬롯 개수를 세고 정수 milli-point 합계를 계산하여 각각 25와 50000인지 확인한다.

### ASM-MUST-002 — 배점 분포 고정

- 수준: `MUST`
- 규칙: 1.5점 8문항, 2.0점 9문항, 2.5점 8문항으로 배정한다.
- 검증: 배점별 빈도 map이 `{1500: 8, 2000: 9, 2500: 8}`과 정확히 같은지 확인한다.

### ASM-MUST-003 — 필수 범위 슬롯 21개

- 수준: `MUST`
- 규칙: 과학의 기초 4개 중 서로 다른 중단원 최소 2개, 과학과 미래 사회 4개 중 서로 다른 중단원 최소 2개, 그리고 아래 17개 필수 주제 조건을 각각 한 슬롯 이상으로 충족한다.
- 검증: 검토된 curriculum binding을 기준으로 2개 선택 집합과 17개 조건의 coverage bitset이 모두 참인지 확인한다.

### ASM-MUST-004 — 균형 슬롯 4개

- 수준: `MUST`
- 규칙: 필수 범위 21개를 고정한 뒤 남은 4개만 대단원 균형을 조정하는 슬롯으로 사용한다.
- 검증: 각 슬롯의 근거가 `REQUIRED` 또는 `BALANCE` 중 하나이고 그 빈도가 정확히 21과 4인지 확인한다.

### ASM-MUST-005 — 탐구·실험형 4~5문항

- 수준: `MUST`
- 규칙: 전체 25문항 중 탐구·실험형은 4개 또는 5개이며 실험 과정, 관찰, 변인 통제, 표·그래프 해석 중 하나 이상의 판별 가능한 탐구 요소를 가져야 한다.
- 검증: 탐구 flag 수가 4..5이고 각 해당 Item Revision의 reviewed item-type binding이 허용된 탐구 유형인지 확인한다.

### ASM-MUST-006 — 교육과정 identity 검증

- 수준: `MUST`
- 규칙: 대단원·중단원은 검토된 editorial outline의 stable key로 결합하며 원본의 별칭이나 하위 주제를 중단원 identity로 가장하지 않는다.
- 검증: 모든 curriculum pointer를 핀한 outline Revision에 resolve하고 parent chain, label projection 및 hash가 일치하는지 확인한다.

### ASM-MUST-007 — Item Revision 중복 금지

- 수준: `MUST`
- 규칙: 한 회차에서 같은 Item Revision을 두 번 사용할 수 없으며 mutable current revision을 암묵적으로 다시 resolve하지 않는다.
- 검증: 25개 pinned Item Revision ID의 set cardinality가 25이고 각 revision이 허용 상태와 정확한 Item에 속하는지 확인한다.

### ASM-MUST-008 — 검토 품질 정책 적용

- 수준: `MUST`
- 규칙: 원본의 `C 이상` 의도는 별도의 versioned review-rating policy가 허용한 후보만 채택한다는 뜻으로 적용하며 자유 문자열 등급 비교를 사용하지 않는다.
- 검증: 각 후보의 review decision이 핀한 등급 정책 Revision에서 `ELIGIBLE`로 resolve되는지 확인한다.

### ASM-MUST-009 — 전체 검산의 원자성

- 수준: `MUST`
- 규칙: 문항 수, 총점, 배점 분포, 범위, 탐구 수, 중복, pointer 상태를 모두 통과하기 전에는 조립 manifest를 성공 상태로 커밋하지 않는다.
- 검증: 독립 검증 결과가 모두 PASS일 때만 한 transaction에서 immutable manifest Revision과 성공 event가 생성되는지 확인한다.

### ASM-MUSTNOT-010 — 후보 부족 임의 보충 금지

- 수준: `MUSTNOT`
- 규칙: 적격 후보가 없는 슬롯을 저품질·범위 밖·중복 문항으로 채우거나 가장 가까운 최신 Revision으로 대체하지 않는다.
- 검증: 후보 부족 시 `ASSEMBLY_CANDIDATE_SHORTAGE`로 종료되고 출력 artifact/revision pointer가 비어 있는지 확인한다.

## 7. 작업 절차

1. 정책, outline, rating policy, usage snapshot의 exact revisions와 hashes를 검증한다.
2. 후보 Item Revision을 한 번의 bounded query로 가져와 curriculum/type/difficulty/score별
   indexed lookup map과 사용된 revision ID set을 만든다.
3. 아래 17개 필수 주제 조건과 두 선택 집합을 합쳐 21개의 필수 슬롯을 생성한다.
4. 아직 적게 배치된 대단원을 기준으로 4개의 균형 슬롯을 추가한다.
5. 전체 슬롯에서 탐구·실험형 4~5개와 정확한 배점 빈도를 만족시키는 후보를 선택한다.
6. 같은 대단원·자료 형식·난도가 과도하게 연속되지 않도록 최종 순서를 정한다.
7. 모든 독립 검산을 수행하고 하나라도 실패하면 성공 manifest를 만들지 않는다.
8. 성공 manifest를 핀한 뒤에만 별도 시험지/HWPX/PDF deliverable 생성을 요청한다.

후보 선택은 작은 고정 슬롯 집합에 대한 제약 충족 문제다. 구현 시 전체 후보를 반복
스캔하지 말고 curriculum/type/score별 index와 사용 set을 사용한다. 최적화가 필요하면
후보 수와 탐색 노드 수를 측정한 뒤 deterministic backtracking 또는 constraint solver를
검토한다.

## 8. 도메인 모듈

원본의 17개 조건을 현재 reviewed outline에 연결하면 다음과 같다. `REVIEW_REQUIRED`는
하위 주제의 공식 binding이 아직 없다는 뜻이지 임의 매핑 권한이 아니다.

| 번호 | 원본 주제 조건 | 검토된 중단원 binding |
| ---: | --- | --- |
| 1 | 별의 진화 또는 태양계 형성 | `2-(2) 별의 진화`; 태양계 형성 단독 사용은 `REVIEW_REQUIRED` |
| 2 | 원소의 주기성 | `2-(3) 원소의 주기성` |
| 3 | 이온 결합·공유 결합 | `2-(4) 이온 결합과 공유 결합` |
| 4 | 규산염 광물 또는 지각·생명체 물질의 규칙성 | `2-(5) 지각과 생명체 구성 물질의 규칙성` |
| 5 | 지구시스템 | `3-(1) 지구시스템의 구성과 상호작용` |
| 6 | 중력장 내의 운동 | `3-(3) 중력장 내의 운동` |
| 7 | 충격량과 운동량 | `3-(4) 충격량과 운동량` |
| 8 | 생명체 기본 단위 | `3-(5) 생명 시스템의 기본 단위` |
| 9 | 효소 / 삼투 / 확산 | 효소는 `3-(6) 물질대사`; 삼투·확산은 exact binding `REVIEW_REQUIRED` |
| 10 | 코돈 | `3-(7) 유전자와 단백질` |
| 11 | 지질 시대 | `4-(1) 지질 시대의 환경과 생물` |
| 12 | 자연선택 또는 생물다양성 | `4-(2) 자연선택` 또는 `4-(3) 생물다양성` |
| 13 | 산화·환원 | `4-(4) 산화와 환원` |
| 14 | 중화 반응 | `4-(6) 중화 반응` |
| 15 | 생태계 | `5-(1) 생태계 구성 요소` 또는 `5-(2) 생태계 평형` |
| 16 | 엘니뇨 | `5-(3) 대기와 해양의 상호작용` |
| 17 | 전자기 유도 | `5-(6) 발전` |

원본의 `감염병 진단 기술`, `빅데이터`, `인공지능`, `과학윤리`는 canonical middle labels가
아니다. 선택 집합은 각각 `6-(1) 감염병과 병원체`, `6-(2) 인공지능과 과학 탐구`,
`6-(3) 로봇`, `6-(4) 과학기술과 윤리` 중 서로 다른 2개 이상으로 계산한다. 하위 주제
태그가 필요하면 후속 taxonomy Revision을 사용한다.

### ASM-SHOULD-011 — 기본 대단원 균형

- 수준: `SHOULD`
- 규칙: 별도 회차 정책이 없으면 대단원별 목표를 `4 / 4 / 6 / 4 / 4 / 3`으로 삼되 필수 조건과 정확한 총점을 우선한다.
- 검증: 실제 분포와 목표 차이를 기록하고 벗어난 경우 검토 사유를 manifest에 남긴다.

### ASM-SHOULD-012 — 난도와 배점의 정렬

- 수준: `SHOULD`
- 규칙: 1.5점은 짧고 안정적인 문항, 2.0점은 표준 자료 해석·개념 적용, 2.5점은 조건 결합·계산·고난도 자료 해석·탐구 중심으로 배치한다.
- 검증: 핀한 difficulty policy의 score-band compatibility 결과와 예외 사유를 확인한다.

### ASM-SHOULD-013 — 인접 다양성

- 수준: `SHOULD`
- 규칙: 같은 대단원, 같은 핵심 자료 형식, 같은 난도 band가 한 구간에 과도하게 연속되지 않도록 순서를 조정한다.
- 검증: versioned adjacency policy로 연속 run 길이를 계산하고 초과 구간의 검토 사유를 남긴다.

### ASM-MAY-014 — 탐구형 5번째 슬롯

- 수준: `MAY`
- 규칙: 전체 제약을 유지하고 후보 품질과 난도 흐름이 더 좋아지는 경우 탐구·실험형을 기본 4개에서 5개로 늘릴 수 있다.
- 검증: 탐구 수가 5일 때 다른 핵심 규칙이 모두 PASS이고 선택 근거가 기록되었는지 확인한다.

## 9. 검증 체크리스트

- [ ] 입력 정책·outline·등급 정책·사용 이력의 revision과 SHA-256이 핀되어 있다.
- [ ] 슬롯 25개, 총점 50000 milli-point이다.
- [ ] 배점 빈도는 8 / 9 / 8이다.
- [ ] 필수 21개와 균형 4개가 독립적으로 확인된다.
- [ ] 탐구·실험형은 4개 또는 5개이다.
- [ ] 25개 Item Revision ID가 모두 고유하고 허용 lifecycle이다.
- [ ] 교육과정 parent chain과 별칭 매핑이 검토된 outline과 일치한다.
- [ ] 적격 후보 부족, 미검토 하위 주제, dangling/hash mismatch가 없다.
- [ ] 대단원·자료 형식·난도 흐름을 검토했다.
- [ ] 성공 manifest가 모든 검사 뒤 한 번만 커밋되었다.

## 10. 실패 및 중단 조건

다음 중 하나라도 발생하면 조립을 중단하고 후보/manifest/deliverable을 임의 수정하거나
자동 재시도하지 않는다.

- 필수 슬롯을 충족할 적격 후보가 없음;
- 검토되지 않은 legacy topic을 canonical unit으로 resolve하려 함;
- Item 또는 Revision이 없거나, current/approved 정책과 맞지 않거나, SHA가 불일치함;
- 동일 Revision 중복, 총점/분포/탐구 수/범위 검산 실패;
- rating/curriculum/usage policy revision이 요청 중 바뀜; 또는
- 동일 idempotency key에 다른 조립 specification이 들어옴.

실패 기록은 최초 안정 오류 코드, 입력 revision pointers, 검증 요약을 보존하되 문항
본문이나 대형 artifact bytes를 복사하지 않는다.

## 11. 예시 및 반례

아래 분포는 원본의 **비규범 기본 예시**다. 필수 규칙을 만족하는 다른 회차 분포를 막지
않는다.

| 대단원 | 예시 문항 수 |
| --- | ---: |
| 과학의 기초 | 4 |
| 물질과 규칙성 | 4 |
| 시스템과 상호작용 | 6 |
| 변화와 다양성 | 4 |
| 환경과 에너지 | 4 |
| 과학과 미래 사회 | 3 |

올바른 예: 슬롯 16이 Item A의 `itemrev_x`를 사용하면 다른 슬롯은 Item A의 current
revision을 다시 resolve하지 않고 다른 pinned revision을 선택한다.

반례: “엘니뇨” 문자열이 비슷하다는 이유만으로 현재 outline을 확인하지 않고 임의
중단원 key를 부여한다. 이는 `ASM-MUST-006` 위반이다.

반례: 2.5점 후보가 부족하므로 검토 D등급 문항을 넣고 총점만 맞춘다. 이는
`ASM-MUST-008`과 `ASM-MUSTNOT-010` 위반이다.

## 12. Graph 및 provenance

원본은 protected intake에 보존된 9,879-byte Markdown이며 SHA-256은 문서 제어에 핀되어
있다. 이 derivative는 원문을 그대로 복제하지 않고, 반복을 제거하고 현재 reviewed
outline과 legacy topic의 차이를 명시했다.

향후 등록 시 원본과 derivative를 별도 Artifact Revisions로 보존한다. Graph에는
`DOCUMENT_REVISION`, `DOCUMENT_SECTION`, `ASSESSMENT_PATTERN`만 제안할 수 있으며, 실제
근거 section pointer와 hash를 포함해야 한다. 조립 규칙의 실행 권한, preset 선택, 모델,
도구 권한은 Graph edge로 표현하지 않는다.

문항의 제품/회차/position 사용 이력은 별도의 usage graph projection이 소유한다. 이
가이드는 그 이력을 복제하지 않고 조립 시점의 immutable usage Snapshot을 참조한다.

## 13. 변경 이력

- revision 1 (2026-08-28 UTC): 내부 1회차 배치 문서를 EOM Guidance Markdown V1으로
  정제했다. 25문항/50점/배점/필수 21/균형 4/탐구 4~5 규칙을 보존하고, 현재 6/35
  outline과 충돌하는 legacy topic을 명시적으로 분리했다. 런타임 등록·Graph publication·
  preset 적용은 수행하지 않았다.
