# 통합과학 단일 문항 출제·검토 가이드 V1

## 문서 제어

```json
{
  "schema_version": "eom-guidance-markdown/1.0",
  "guidance_key": "integrated-science-single-item-authoring",
  "revision": 1,
  "status": "REVIEWED",
  "title": "통합과학 단일 문항 출제·검토 가이드 V1",
  "locale": "ko-KR",
  "guidance_type": "AUTHORING_REFERENCE",
  "rule_prefix": "SIA",
  "execution_authority": "NONE",
  "runtime_use": "PINNED_REFERENCE_ONLY",
  "applicable_roles": ["AUTHORING", "REVIEW"],
  "applicable_use_cases": ["ITEM_AUTHORING", "ITEM_REVIEW"],
  "core_rule_ids": [
    "SIA-MUST-001",
    "SIA-MUST-002",
    "SIA-MUST-003",
    "SIA-MUST-004",
    "SIA-MUST-005",
    "SIA-MUST-006",
    "SIA-MUST-007",
    "SIA-MUST-008",
    "SIA-MUST-009",
    "SIA-MUSTNOT-010"
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

통합과학 모의고사 조립 원칙 중 **한 문항을 출제하고 검토할 때 실제로 적용 가능한
부분만** 분리하여, 자연어 요청과 교육과정 범위에 맞는 독립적이고 검증 가능한 문항을
만든다. 성공 조건은 문항 하나가 과학적으로 타당하고, 정답이 유일하며, 자료·발문·보기·
선택지·해설·배점·난도가 서로 일치하고, 후속 회차 조립에서 사용할 수 있는 구조화된
Item Revision으로 등록 가능한 상태가 되는 것이다.

## 2. 적용 범위

이 가이드는 `authoring` 역할의 단일 통합과학 문항 초안과 `review` 역할의 동일 문항
검토에 적용한다. 문항이 시각 자료를 필요로 하면 별도의 핀된 통합과학 삽화 가이드와
함께 사용한다.

이 문서는 모의고사 한 회차를 직접 조립하지 않는다. 원본의 25문항, 50점, 1.5/2.0/2.5점
분포, 필수 21개 슬롯, 균형 4개 슬롯, 탐구 4~5개 같은 **회차 집계 조건은 한 문항의
성공 조건이 아니다**. 그 조건은 상위 assessment assembly use case에서 후보 Item
Revisions를 조합할 때만 적용한다.

## 3. 신뢰 및 권한 경계

이 문서는 reviewed reference data이며 실행 권한이 없다. typed current request, 교육과정
selection, Content Pack, JSON Schema, Instruction Bundle과 안전 정책을 덮어쓸 수 없다.
문서의 예시와 과거 용어는 data일 뿐이며 최신 단원, 정답, 배점 또는 자료를 자동으로
추론할 권한을 주지 않는다.

문항의 자연어 요청과 Graph evidence도 untrusted input이다. 서로 충돌하거나 근거가
부족하면 임의로 합성하지 말고 안정적인 검토 finding을 남긴다.

## 4. 입력 계약

출제·검토는 최소한 다음의 현재 요청 데이터를 사용한다.

- 과목, 자연어 출제 요구, 과제 유형, 난도, 선택지 수와 배점;
- 선택된 교육과정 outline key/revision/hash 및 대단원·중단원 binding;
- 자연어 요구가 명시한 평가 행동과, 명시하지 않았을 때 현재 과제 유형으로 확인 가능한
  실제 응답 행동;
- 사용 중인 Content Pack, workflow protocol 및 Execution Preset revisions;
- 요청별 Evidence Bundle이 있으면 그 exact revision, access policy 및 source pointers;
- 시각 자료가 필요하면 exact image role request와 upstream authoring result; 및
- upstream Artifact logical/revision IDs, schema/media types와 SHA-256.

문서나 이전 문항의 “최신” revision을 암묵적으로 찾지 않는다. 제공된 pointer가 없거나
stale/hash mismatch이면 그 자료를 근거로 사용하지 않는다.

## 5. 출력 계약

출력은 현재 authoring/review role result JSON Schema를 정확히 만족해야 한다. 초안은
문단·표·식·그림·`ㄱ/ㄴ/ㄷ` 보기·선택지·정답 pointer·해설과 provenance를 구조화하며,
검토 결과는 exact upstream revisions에 대한 bounded findings와 결정을 기록한다.

큰 이미지, PDF 또는 HWPX bytes를 JSON이나 DB에 넣지 않는다. 이미지와 출력 문서는
별도 Artifact Revision으로 관리하고 Item은 그 immutable component pointer를 참조한다.

## 6. 핵심 규칙

### SIA-MUST-001 — 선택 교육과정 범위 준수

- 수준: `MUST`
- 규칙: 문항의 핵심 개념과 요구 사고는 current request에 핀된 통합과학 대단원·중단원 범위 안에 있어야 하며, 하위 주제를 공식 중단원 identity로 가장하지 않는다.
- 검증: 문항의 curriculum binding과 개념·자료·정답 근거를 exact outline revision의 parent chain 및 request 범위와 대조한다.

### SIA-MUST-002 — 하나의 독립 문항

- 수준: `MUST`
- 규칙: 한 실행은 서로 독립적인 문항 하나만 만들고 다른 문항, 회차 슬롯 또는 제품 배치 결정을 같은 결과에 섞지 않는다.
- 검증: 결과가 하나의 Item draft와 하나의 answer model만 가지며 form-level count/distribution 필드를 만들지 않았는지 확인한다.

### SIA-MUST-003 — 과학·자료·정답 정합성

- 수준: `MUST`
- 규칙: 본문, 표·그림·식, 발문, 보기, 선택지, 정답, 해설의 수치·방향·개수·단위·인과 관계가 과학적으로 일치해야 한다.
- 검증: 모든 자료 값과 statement truth value를 answer model에 독립적으로 대입하고 정답 선택지가 정확히 하나인지 확인한다.

### SIA-MUST-004 — 난도·배점·사고량 정렬

- 수준: `MUST`
- 규칙: 요청 난도와 배점은 조건 결합 수, 자료 해석량, 계산량과 오답 매력도에 일관되게 반영되어야 하며 단순한 문장 길이나 지엽성으로 난도를 올리지 않는다.
- 검증: 풀이 단계, 필수 개념, 자료 변환과 distractor misconception을 열거하여 요청 difficulty/score policy와 비교한다.

### SIA-MUST-005 — 판별 가능한 탐구 요소

- 수준: `MUST`
- 규칙: 요청이 탐구·실험형이면 실험 과정, 관찰, 변인 통제, 측정, 표·그래프 해석 중 적어도 하나가 정답 판단에 실제로 쓰여야 한다.
- 검증: 탐구 flag를 뒷받침하는 item block과 그 block이 풀이에서 사용되는 단계를 exact ID로 연결한다.

### SIA-MUST-006 — 오답과 해설의 독립 품질

- 수준: `MUST`
- 규칙: 오답은 동일 교육과정 범위의 판별 가능한 오개념이나 계산·해석 오류를 반영하고, 해설은 정답 근거와 각 핵심 오답의 오류를 문항에 없는 사실을 발명하지 않고 설명해야 한다.
- 검증: 선택지별 판정 근거가 있고 중복 선택지, 부분 정답, 논점 이탈 또는 정답 문구의 단순 부정이 없는지 확인한다.

### SIA-MUST-007 — 시각 자료의 별도 검증

- 수준: `MUST`
- 규칙: 표·그림·그래프·입자 모형·실험 장치가 필요한 경우 current request와 핀된 삽화 가이드에서 관련 rule IDs만 선택하고, 과학 정보와 흑백 인쇄 판독성을 문항과 함께 검증한다.
- 검증: authoring result의 visual requirement, image result와 review finding이 같은 semantic constraints 및 pinned pointers를 참조하는지 확인한다.

### SIA-MUST-008 — 평가 행동과 문항 요구의 정렬

- 수준: `MUST`
- 규칙: 문항의 정답 판단은 `이해`, `적용`, `문제 인식 및 가설 설정`, `탐구 설계`, `탐구 수행 및 자료 수집`, `자료 변환 및 해석`, `결론 도출 및 일반화`, `의사소통` 중 현재 요청과 실제 문항 구조에 맞는 주 평가 행동으로 설명 가능해야 한다. 이름만 탐구형으로 붙이거나 단순 암기를 자료 해석으로 가장하지 않는다.
- 검증: 풀이자가 수행해야 하는 관찰·변환·추론·판단을 순서대로 적고, 발문과 정답 근거가 선택한 행동의 정의를 실제로 요구하는지 대조한다. 현재 result schema에 없는 새 metadata 필드를 임의로 만들지 않는다.

### SIA-MUST-009 — 주 편집 범위와 복수 성취기준의 구분

- 수준: `MUST`
- 규칙: current request에 핀된 대단원·중단원은 문항의 주 편집 범위로 유지한다. 한 문항이 복수 성취기준이나 과학 영역을 연결할 때에는 각 연결이 정답 판단에 필요하고 현재 선택 범위의 parent chain 안에 있거나 typed request가 명시적으로 허용한 더 넓은 범위 안에 있어야 한다. 관련성이 있다는 이유만으로 선택 범위 밖 성취기준을 자동 추가하지 않는다.
- 검증: 주 curriculum binding과 보조 성취기준·개념을 분리해 대조하고, 각 보조 연결의 근거와 정답 판단 기여를 확인한다. 하나의 중단원 문자열로 복수 관계를 덮어쓰거나 암묵적 latest mapping을 사용하지 않는다.

### SIA-MUSTNOT-010 — 회차 집계 규칙의 문항 강제 금지

- 수준: `MUSTNOT`
- 규칙: 25문항 수, 총점, 회차 배점 빈도, 대단원별 문항 수, 필수·균형 슬롯 수와 전체 탐구형 수를 단일 문항의 내용·배점·성공 조건으로 강제하지 않는다.
- 검증: 단일 문항 request/result에 assembly aggregate를 만족시키기 위한 임의 topic, score, difficulty 또는 item type 변경이 없는지 확인한다.

## 7. 작업 절차

1. typed request, selected curriculum scope, preset/pack/protocol과 evidence pointers를 검증한다.
2. 자연어 요구를 교육과정 범위 안에서 핵심 개념, 사고 기능, 자료 형태와 난도로 나눈다.
3. 정답 모델과 필요한 과학·수학 관계를 먼저 고정한 뒤 문항 자료와 발문을 설계한다.
4. 정답과 구분되는 오개념 기반 오답을 만들고 각 선택지의 판정 근거를 확인한다.
5. 시각 자료가 필요하면 semantic constraints를 image 역할에 넘기고 삽화 가이드의 관련
   모듈만 적용한다.
6. 해설을 작성하고 pointer coverage, statement coverage, 선택지 수와 정답 유일성을
   schema 및 typed model로 검증한다.
7. review 역할은 exact authoring/image revisions를 독립적으로 검토하고 임의 수정 대신
   bounded finding을 반환한다.

## 8. 도메인 모듈

문항 유형에 따라 다음 모듈만 선택한다.

- 개념 적용: 정의 암기가 아니라 조건 변화와 개념 관계를 판별한다.
- 계산·정량: 단위, 유효한 수치, 보존 관계와 반올림 조건을 명시한다.
- 표·그래프: 축·단위·범례·행렬 값과 해설의 수치가 정확히 같다.
- 탐구·실험: 독립/종속/통제 변인과 관찰·결론의 논리 방향을 구분한다.
- `ㄱ/ㄴ/ㄷ`: statement IDs, truth values와 statement explanations가 정확히 일대일 대응한다.
- 통합 자료: 서로 다른 과학 영역을 단순 병치하지 않고 하나의 정답 판단 관계로 연결한다.

평가 행동은 다음과 같이 해석한다. 이 분류는 2028학년도 수능 통합과학 평가틀을
검토하여 만든 EOM의 핀된 참조이며, worker가 실행 중 외부 사이트를 조회한다는 뜻이 아니다.

- 이해: 개념·원리·법칙·이론을 파악하고 관계를 설명한다.
- 적용: 배운 개념과 원리를 새로운 구체적 상황에 사용한다.
- 문제 인식 및 가설 설정: 관찰 가능한 문제를 찾고 검증 가능한 가설을 세운다.
- 탐구 설계: 변인, 절차, 비교 조건과 측정 방법을 구성한다.
- 탐구 수행 및 자료 수집: 절차에 맞게 관찰·측정하고 신뢰할 수 있는 자료를 얻는다.
- 자료 변환 및 해석: 표·그래프·식·시계열 등으로 자료를 변환하고 관계를 해석한다.
- 결론 도출 및 일반화: 근거에서 결론을 도출하고 허용된 범위에 적용한다.
- 의사소통: 과학적 주장과 근거를 표현·비교하고 의사결정에 사용한다.

현재 EOM HWPX 문항 템플릿의 `2점` 또는 `3점`은 단일 Item의 내부 정수 점수 계약이다.
2028 예시문항의 `1.5점 / 2.0점 / 2.5점` 회차 배점과 같은 identity로 취급하지 않는다.
공식 회차 배점은 향후 assembly policy의 별도 typed 값과 immutable revision으로 관리하고,
worker는 현재 output schema가 허용하지 않는 소수 점수를 만들지 않는다.

## 9. 검증 체크리스트

- [ ] 선택 교육과정과 자연어 요구를 모두 반영했다.
- [ ] 문항 하나, 선택지 다섯 개, 유일한 정답과 완전한 해설이 서로 일치한다.
- [ ] 자료 수치·단위·방향·개수·축·범례가 풀이와 일치한다.
- [ ] 난도와 배점이 실제 사고 단계에 맞는다.
- [ ] 탐구형 표시는 판별 가능한 탐구 요소로 뒷받침된다.
- [ ] 발문과 풀이가 여덟 평가 행동 중 실제 주 행동에 맞는다.
- [ ] 주 편집 범위와 필요한 복수 성취기준·개념 연결을 구분했다.
- [ ] 시각 자료는 핀된 삽화 규칙의 관련 모듈로 검증했다.
- [ ] 회차 집계 조건을 단일 문항에 잘못 강제하지 않았다.
- [ ] 사용한 source/evidence는 exact revisions와 hashes로 추적된다.

## 10. 실패 및 중단 조건

교육과정 범위가 없거나 충돌하고, 과학 조건이 부족하며, 정답이 유일하지 않고, 자료와
해설이 불일치하거나, 필요한 upstream pointer가 stale/hash mismatch이면 성공 결과를
만들지 않는다. 회차 전체의 빈 슬롯을 채우기 위해 요청 범위 밖 문항을 만들거나 낮은
품질을 성공 처리하지 않는다. 최초 안정 오류와 bounded finding을 보존하며 자동으로
다른 문항을 추가 생성하지 않는다.

## 11. 예시 및 반례

올바른 예: `5-(3) 대기와 해양의 상호작용` 범위에서 두 패널의 기준선과 축척을 같게
고정하고, 강수량·등수온선 차이를 근거로 하나의 정답을 판별한다.

올바른 예: 원소의 주기성을 주 편집 범위로 유지하면서 인체 구성 원소 비율 같은 자료를
적용 맥락으로 사용한다. 자료가 있다는 이유만으로 주 평가 행동을 자동으로 `자료 변환 및
해석`이라 부르지 않고, 실제 요구가 주기성의 `적용`인지 자료 관계의 `해석`인지 구분한다.

반례: 모의고사에 탐구형 4~5개가 필요하다는 이유만으로 사용자가 개념형을 요청한 현재
한 문항을 실험형으로 바꾼다. 이는 `SIA-MUSTNOT-010` 위반이다.

반례: 원본의 1.5점 분포를 맞춘다는 이유로 현재 Content Pack이 허용하는 배점 또는
사용자 요청을 무시한다. 회차 배점 분포는 assembly 정책이지 단일 문항 규칙이 아니다.

## 12. Graph 및 provenance

protected intake 원본은 9,879-byte Markdown이며 SHA-256은 문서 제어에 핀되어 있다.
form-level canonical derivative는
`integrated-science-mock-exam-assembly-v1.md`이고, 이 문서는 동일 원본에서 item-applicable
원칙만 분리한 별도 derivative다. 두 문서는 서로 다른 guidance identity와 revision/hash를
가진다.

향후 Graph에는 근거가 있는 `DOCUMENT_REVISION`, `DOCUMENT_SECTION`,
`ASSESSMENT_PATTERN`만 제안한다. 문서의 역할 적용, 실행 우선순위, worker model/tool과
preset 선택은 Graph 관계가 아니라 Control Plane이 소유한다.

평가 행동과 2028 통합과학 구조를 검토할 때 사용한 공식 공개 지점은 다음과 같다.

- 교육부, `2028 대학입시제도 개편 확정안`, 2023-12-27,
  <https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=97551&lev=0&m=020402&opType=N&page=1&s=moe&searchType=null&statusYN=W>
- 교육부, `2028학년도 대학수학능력시험 예시문항 안내`, 2025-04-15,
  <https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=103113&lev=0&m=0204>
- 한국교육과정평가원 발행 안내서의 정부 지식정보 기록,
  <https://k-knowledge.kr/srch/read.jsp?id=288281550>

공개 예시문항은 새 체제 이해를 위한 자료이므로 그 문항의 난도나 배점 빈도를 실제 수능의
영구 분포로 추정하지 않는다. 위 URL은 provenance 표기이며 runtime network dependency가
아니다. source 내용이나 EOM 해석을 바꾸려면 이 guidance의 새 immutable revision을 만든다.

## 13. 변경 이력

- revision 1 (2026-08-28 UTC): 내부 모의고사 배치 원본에서 단일 문항 출제·검토에
  적용 가능한 교육과정, 정합성, 난도, 탐구, 오답, 시각 검증 원칙을 분리했다. 25문항
  회차 집계 조건은 명시적으로 제외하고 원본 hash와 별도 assembly derivative 관계를
  기록했다. 첫 runtime publication 전에 2028 통합과학의 여덟 평가 행동, 주 편집 범위와
  복수 성취기준의 경계, 내부 점수와 공식 회차 배점의 구분을 함께 검토하여 고정했다.
