# 창작 문항과 기출 520문항의 Graph 호환성

## 책임과 호환 기준

창작 원문 추출의 successor는 **입력 표현**을 보완한다. 새 Graph 저장소, 창작 전용
ontology, 새 검색 엔진을 만들지 않는다. 원문 → 승인 Item Revision → 기존 accepted
지식 분석 → 공통 Education Graph projection/publication 순서를 유지한다.

정본은 고정 source/Item Revision과 accepted 분석 Artifact다. source별 내부 worker node
ID는 proposal 안에서만 유효하고, Graph의 node ID는 기존 `(node_type, stable_key)` 규칙으로
정한다. 같은 개념은 같은 노드를 공유하며, 다른 개념을 label이나 유사도만으로 합치지 않는다.
관계도 기존 edge type/endpoint 검사와 identity 규칙을 그대로 사용한다.

기출은 `PAST_EXAM`과 시험 occurrence/문항 위치를 보존한다. 가져온 창작은
`APPROVED_ITEM`과 검증된 외부 source lineage로 식별하며, 기출 occurrence를 만들거나
첨부된 원기출의 번호·배점·해설을 창작 정본으로 빌려 쓰지 않는다. 교과서 `TEXTBOOK`도 같은
Graph 안의 별도 source pointer다. 사용자 layer는 출처의 구분이지 독립 Graph의 구분이 아니다.

원문 이미지 crop, 미표기 배점, 독립 풀이/원문 해설 불일치는 source/result lineage가 소유한다.
source-image recipe를 Graph pointer인 것처럼 저장하지 않는다. 실제 crop Artifact를
Orchestrator가 검증·commit하고 canonical Item에서 참조한 뒤에만 기존 분석에 전달한다.
주의사항은 조회 시 원래 보고서와 함께 노출하고, 수록 승인을 과학적 정확성 보증으로 바꾸지 않는다.

## 자료구조와 운영 경계

- 공통 projection의 stable-key map, source-pointer set, sorted immutable manifest를 재사용한다.
- 조회는 snapshot PK/source revision index와 기존 accepted-analysis resolver를 사용한다.
  문항별 별도 Graph를 재조회하거나 worker에 DB/NAS 접근을 주지 않는다.
- 검증은 고정 snapshot의 membership/정본 pointer 대조 O(sources), 기존 node/edge identity의
  set 비교 O(nodes + edges)다. metadata-only 검사이며 새 cache/table/index는 만들지 않는다.
- 기존 Graph head CAS, analysis/registration idempotency, revision별 immutable history를 유지한다.
  중단·재전송은 기존 application 경계로 복구하며 과거 FAILED/NEEDS_DECISION을 덮지 않는다.
- 입력 successor가 필요하다는 이유로 구 cohort/plan/지침을 제자리 수정하지 않는다.
  호환 family는 명시적으로 구분하고 기출의 schema bytes·accepted 분석은 변경하지 않는다.

## 2026-10-29 03:18 UTC 운영 읽기 전용 대조

대상 baseline은 `graphrev_7870b0fb03b7dfb64179e53182bf3999`, 창작 표본 추가 후 snapshot은
`graphrev_4b6c4e7eab8aa329c4666475085776bf`다. 설치된 maintenance wheel
`9ce6ee239e20f65b40600dedbd0b4275e9019093`의 공식 structure/accepted-analysis read contract로
검증하고 metadata를 대조했다. 새 worker 실행·Graph publication·운영 DB 수정은 하지 않았다.

| 항목 | 결과 |
|---|---|
| Graph logical ID / ontology | 동일, `education-knowledge-graph/1.1` |
| structure schema | 전후 모두 `knowledge-graph-structure-manifest/5.0` |
| accepted source membership | 1,015 → 1,016; 기존 1,015건 누락/포인터 변경 0 |
| source 구성 | 교과서 분석 범위 495 + 기출 520 + 창작 표본 1 |
| 기존 기출 상세 풀이보고서 | accepted V10 successor 520, base당 정확히 1개 |
| node identity | 17,000 → 17,026; 기존 identity 누락/재발급 0 |
| edge identity | 40,652 → 40,678; 기존 identity 누락/재발급 0 |
| 창작 source가 연결된 node | 29개, 그중 3개는 기출·교과서와 동시에 공유 |
| 대표 source 공식 해석 | 교과서·기출·창작 모두 accepted-result/proposal 해석 PASS |

495는 **교과서 문서 수가 아니라 accepted 분석 범위 수**다. 520은 기존 기출 base의 수다.
이들을 문항 수나 파일 수 하나로 합산하지 않는다. metadata evidence는
`/tmp/eom-creative-graph-compatibility-20261029.json`에 보존했다. 작업 완료 시 영속 evidence
manifest에 포함하며, 임시 파일 자체를 정본으로 삼거나 Git에 생성 산출물을 넣지 않는다.

## 형식이 달라도 되는 부분과 아직 같다고 말할 수 없는 부분

공식 resolver가 실제로 읽은 대표 입력은 다음과 같다.

| source | proposal | accepted result | anchor authority |
|---|---|---|---|
| 교과서 | 6.0 | 8.0 | 승인 문서의 실제 페이지/영역 |
| 기출 | 7.0 | 9.0 | 승인 기출 Item과 고정 원본 페이지 |
| 창작 표본 | 1.0 | 2.0 | 승인된 canonical Item 요소, 외부 원문 lineage |

버전 번호를 억지로 같게 만드는 것이 호환성이 아니다. 같은 Graph ontology/projection과
검증된 pointer로 해석되고, 원문에 맞는 anchor authority를 유지하는 것이 기준이다.

다만 기출 V10의 `knowledge-analysis-solution-report/1.0`은 base node/anchor를 참조하는
개념→평가 요소·단계 의존·선지 진단·해설 대조까지 구조화한다. 현재 창작 source report는
독립 풀이와 원문 불일치를 보존하지만 **accepted V10과 동일한 보고서라는 뜻은 아니다**.
기존 `create_solution`은 V9 base에 한정되므로 창작 V2 base를 V9라고 위장하거나
해당 계약을 느슨하게 만들어 통과시키지 않는다.

현재 3건 검증의 필수선은 source-faithful Item + accepted base + 공유 Graph + 공식 풀이·모든
주의사항 조회다. 원래 창작 successor 설계의 상세 보고서 고도화에서는 공통 공개 풀이 value
types를 재사용하되, 정확한 창작 base node/anchor를 참조하는 additive successor를 사용한다.
현재 source report를 기존 기출 V10과 동일한 구조적 상세도로 보고하지 않는다.

## 회귀 검증

`tests/unit/test_creative_past_exam_graph_compatibility.py`는 합성 기출 520건의 V9 accepted
pointer, 창작의 V2 pointer와 교과서 분석을 기존 projector에 함께 넣는다. 서로 다른 입력
family의 공통 개념 병합, 기존 node/edge/pointer 보존, 시험 occurrence 보존, 창작 occurrence
위조 방지, canonical serialization/schema 검증, 충돌·중복 거부를 확인한다.

이 검사는 합성 회귀이며 운영 520건을 재생성하지 않는다. 위 운영 읽기 결과와 별개 증거다.
U10311의 crop/배점 successor 및 실제 3건 끝단 검증이 아직 완료됐다는 뜻도 아니다.

2026-10-29 집중 실행 결과: 새 혼합 Graph 회귀 4개 PASS. 기존 Graph projector/교육과정
structure/공유 publisher/창작 등록 보고서/role V2 호환 회귀를 함께 실행한 **99개 PASS**
(4개 포함, 독립 합산하지 않음). 신규 test 파일의 Ruff·format·mypy 및 diff 검사 PASS.
초기 fixture는 V9 pointer를 V2-only human-reviewed helper로 만들다 거부됐으며,
production validator를 완화하지 않고 현행 automatic-alignment fixture로 고쳐 재실행했다.
