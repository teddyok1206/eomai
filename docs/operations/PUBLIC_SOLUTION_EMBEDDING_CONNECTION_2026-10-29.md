# 기출·창작 공통 풀이 임베딩 연결 — 검증 체크포인트

2026-10-29 UTC. 이 문서는 구현 후보와 운영 활성화를 구분한다.
설계 정본은 [풀이 양식 호환 설계](../architecture/SOLUTION_EMBEDDING_FORMAT_COMPATIBILITY.md)다.

## 현재 판정

`SOLUTION_EMBEDDING_ALIGNMENT_PENDING`.

Catalog의 실제 Graph/source admission 후 공개 풀이를 같은 텍스트로 투영하는 capture,
source-plan3, index/binding3, native request/ownership/completion3를 구현했다. 숫자 계산의
input/result/shard1과 기존 INDEX2 DAG·기존 encoding 예약·CAS·Artifact commit owner를
재사용한다. 새 검색 엔진, DB, queue, 모델 dependency는 없다.

이 candidate를 운영 활성화 완료 또는 GPU INDEX 재개로 표현하지 않는다. 과거 인덱스의
namespace/recipe를 바꾸거나 창작을 V10/AI review로 위장하지 않는다.

## 확인한 검사

- JSON Schema 2020-12 canonical/package mirror 8개 생성 분기의 `--check` PASS.
- 새 public entry schema도 canonical/package mirror 및 pinned hash로 검증한다.
- disposable PostgreSQL에서 migration 0062 → 0063 → 0062 → 0063 PASS.
- registry/native 기존 트랜잭션 묶음: **47 PASS**.
- 새 public native 경로: **3 PASS**. 실제 Workflow/Job/encoding/Artifact/index 등록과
  terminal completion, encoding 완료 직후·등록 직후 중단/재개에서 재인코딩 없음 확인.
- source/기존 adapter/owner/carrier/handoff 등 focused unit 묶음: **509 PASS**.
- 별도 모듈 의존성·설계·similarity consumer 경계 검사: **54 PASS**.
- restricted runtime role을 포함한 전체 model-free embedding persistence 묶음: **148 PASS**.
- 변경 core **68개 파일 mypy PASS**, Ruff PASS. 최종 diff가 늘면 다시 확인한다.

위 native 검사는 실제 disposable PostgreSQL과 임시 파일을 사용하지만 IAM/source admission,
installed runtime 및 모델 추론은 명시적인 합성 seam이다. 실제 운영·GPU 수치 추론 증거가 아니다.
FULL embedding persistence에도 skip·setup 오류 없이 148개가 통과했다. 테스트용 제한 계정은
운영 계정이 아니라 guarded disposable DB의 reconcile 단계에서 준비한 계정이다.

### 검사 중 수정한 결함

- `PopulationSource`의 V3 occurrence/page provenance를 base source로 직렬화하며 잃지 않도록
  실제 subtype을 보존한다. V10의 core source와는 정해진 identity 비교만 한다.
- service source capture와 publication authority의 typed scope를 보존한다. 예전 unit fixture의
  `SimpleNamespace`를 실제 read-scope 값으로 바꾸었으며 운영 권한 검사를 느슨하게 하지 않았다.
- public namespace를 Catalog verifier 구성 단계부터 정확한 recipe2와 짝지어 허용한다.
- PEP 695 type alias를 `isinstance`에 전달하지 않는다. 지원 request의 runtime class 집합은
  기존 closed request dispatch 한 곳에서 관리한다. item workflow로 잘못 분기하지 않는다.
- fixed native handoff도 같은 closed association parser를 사용한다. request3 숫자 입력은
  기존 numerical1이며, request1/2의 handoff 검사와 source/lease 경계는 유지한다.
- frozen INDEX1 admission 회귀는 원래 snapshot hash를 그대로 보존한다. 이후 릴리스된 자료 검토
  1.4/1.5, 창작 학습 1.0/2.0 네 successor만 정확한 protocol과 별도로 검증한다.

## 유지해야 하는 실행 경계

- 새 public 전체 metadata head 상한 16,384; source page·실제 native batch 상한 1,024.
- 기존 manifest/plan family 1/2의 1,024 한도를 제자리 확대하지 않는다.
- 창작 report IO는 16개씩, 공개 풀이 캡처는 합계 64 MiB. 인코더의 개별 262,144 UTF-8 byte
  한도를 넘으면 unavailable이며 자르거나 다른 보고서로 채우지 않는다.
- 같은 풀이 text/space/partition의 수치 row를 재사용해도 source/lineage/base analysis/Graph/
  policy/Artifact revision proof는 각각 유지한다.
- Graph membership 변경은 keyset traversal 후 다시 검사한다. 중간 capture를 전체 coverage로
  오인하지 않는다. 부분 등록과 missing report는 사실대로 남긴다.
- numeric batch를 만들지 않는 membership 갱신도 기존 native owner에서 수행한다. plan3에는
  실제 available witness 하나만 넣고 completion이 전체 current population을 독립 재캡처한다.

## 다음 구현·배포 범위

1. 동일 public recipe/text로 QUERY와 candidate를 연결하는 명시적 read/query successor.
   기존 similarity1/2와 query input1/1.1/result1은 그대로 유지한다. 새 profile을 기존
   accepted-analysis anchor나 독립 AI review anchor로 가장하지 않는다.
2. 실제 GPU-first/CPU fallback owner selection의 public family 지원. 기존 owner5 JSON에
   미지원 namespace를 넣거나 source grant를 확대하는 방식은 사용하지 않는다.
3. frozen installed wheel·policy·runtime pins의 호환 release. production migration 0063은
   실제 0063을 지원하는 보호된 release 절차로만 수행한다. 현재 0062 callback을 0063으로
   이름만 바꾸지 않는다.
4. 실제 bounded document/query·registry binding·공식 검색 및 replay 검증 후에만
   alignment 완료를 선언하고 GPU INDEX 재개를 별도로 확인한다.

### 배포 패키지 검사에서 찾은 admission 누락

첫 후보 `6cf425ad`의 wheel RECORD는 통과했지만 installed simulation이 이전 0062 head를
고정 검사하여 전체 build gate는 실패했다. 운영 mutation은 없었다. 기존 배포 owner에
정확한 0062 → 0063 callback과 context/admission 1.12를 추가한다. 이전 schema bytes와
0062 callback은 그대로이며, 옛 callback으로 새 migration을 실행할 수 없다.

기존 migration별 테스트의 frozen callback/receipt 검사는 유지하고 현재 release selector와
head에 대한 기대만 authoritative runtime head를 참조한다. 실제 검증이 YAML 두 파일을
staging하는 코드와 일치하도록 creative definition의 오래된 문자열 단정도 보정했다.
관련 operator/runtime/기존 migration/API 배포 경계 **320 PASS**, script mypy PASS.
새 패키지 검사의 결과와 운영 설치는 별도로 남긴다.

`85854c63`에서 build-only를 다시 실행하여 wheel RECORD와 비편집 설치본의 schema·import·
definition/admission 검사가 모두 PASS했다. 운영 migration·서비스 교체는 수행하지 않았다.
빌드 출력은 `/tmp/eom-api-build/85854c63011de6e5be742ee3c7e3e0df0a2d655d.HCBpK6/dist`다.

### QUERY의 같은 풀이 입력 — 다음 source 체크포인트

공개 풀이 recipe2를 담는 별도 query input/result2와 실행 결과 pointer를 추가했다.
기존 query1/1.1/result1은 새 recipe를 받아들이지 않는다. 새 encoder wrapper는 기존
QUERY purpose 호출·backend 전후 대조·수치 shard1 packer를 공유하며 한 행을 padding하거나
재시도하지 않는다. 기출·창작의 같은 공개 풀이가 같은 QUERY 입력이 되는 것도 확인했다.

합성 CPU/CUDA backend를 사용하는 기존·신규 QUERY/증분 수치 회귀 **162 PASS**, 관련
core 3개 파일 mypy PASS, 새 schema canonical/package mirror 및 generator `--query --check`
PASS다. 이것은 실제 GPU 실행·native QUERY 활성화·공식 유사도 검색 완료가 아니다.
후속 similarity/source read와 fixed native definition/owner 선택 연결이 남아 있다.

## 병행 운영 확인

2026-10-29 11:47 UTC의 read-only metadata 대조에서 기존 미완료 CUDA Workflow의
space/runtime bundle/resource/native policy pointer·hash/corpus/namespace 및 definition hash는
현재 선택과 모두 일치했다. 기존 실패의 executor readiness는 이 대조만으로 해결됐다고
주장할 수 없다. backend/runtime 실패의 정확한 하위 원인과 supported recovery가 남아 있다.

INDEX는 2026-10-28 20:10 UTC 실패 이후 중단, QUERY는 고정 07ec 설치본에서 실행 중이다.
단순 restart, FAILED history 재해석 또는 진행 중 pin 교체는 하지 않았다.

2026-10-29 11:50 UTC에는 창작 14/1,053 Graph 검증 완료, 10324 풀이 분석 ACCEPTED,
held worker lease 0·active slot Job 0을 확인했다. 이때 슬롯 6개가 사용 가능인 것은 실제
상태와 맞는다. Graph 반영/조회 검증은 Codex 슬롯을 점유하지 않는다. 이후 사용자가
실제 ‘작업 중’ 표시 전환도 확인했다. 한 문항씩 처리하므로 여섯 슬롯을 모두 쓰지 않는다.

등록 감시는 기존 30분 timer를 유지한다. 이번 세션의 embedding follow-up timer는 재부팅까지
유지되는 read-only systemd metadata 관측이다. PID/상태 관측을 인코딩 coverage로 부르지 않는다.

실제 source 정본·과거 FAILED·운영 GPU/QUERY pin은 보존했다. 공개 풀이 원문과 실험 장문 로그,
인증/env 파일은 Git/Slack에 기록하지 않는다.

## 2026-10-29 INDEX 재개 후 확인한 조회 병목

같은 07ec owner를 재개했으나 실제 GPU 계산 전에 LOCK_POPULATION 616초,
ADMIT_CANDIDATES 651초가 걸렸다. 단순 PID 활성화는 GPU 재개 PASS가 아니다. 기술 metadata의
read-only EXPLAIN에서 custom plan은 pointer 집합을 한 번 집계했지만 generic prepared plan은
Nested Loop Semi Join과 전체 pointer 행 Materialize를 골랐다. source 조건을 반복 대조하는
잘못된 실행 형태를 확인했으며, 운영에서 EXPLAIN ANALYZE/load test를 수행하지 않았다.

수정 책임은 기존 Catalog `candidate_pool_analysis_statement`의 SQL 구성 한 곳이다. 기존
Graph revision/source class/node 존재/answer-bearing 조건으로 eligible analysis ID의 DISTINCT
집합을 한 번 MATERIALIZED CTE로 만든 뒤 association과 join한다. 정본·pointer·권한·policy·
source hash·순서·LIMIT·occurrence/revision 조건·최종 source admission은 바꾸지 않는다.
실제 source를 읽는 권한이 없는 SQL builder가 새 권한을 만들지도 않는다.

접근은 Graph-local membership/dedup과 indexed joins이며 pointer P와 source N에 대해
집합 구성 O(P), 작은 key 집합 공간 O(N)을 의도한다. 이미 선택된 analysis/revision 조건은
같은 association 의미로 CTE 안에도 전달한다. 새 DB/index/cache/queue/migration은 없다.
기존 transaction·source fence·idempotent request와 dependency 방향을 유지하며 오류는
기존 explicit failure다. LIMIT 이후 필터링하거나 node join을 없애는 대안은 의미가 달라져
채택하지 않는다. pointer 원문 전체를 매 source마다 재탐색하는 기존 계획보다 작은 ID 집합이
안정적이다. 임시 PostgreSQL의 force-generic/custom 결과 동등성·분기·중복/orphan·계획 검증 후
별도 owner 릴리스 시점에만 활성화한다. 실행 중 numeric bundle/QUERY pin을 hot patch하지 않는다.

동일 builder의 focused unit/권한/경계 154개 PASS, disposable source admission 55개 PASS
(다른 66개는 명시한 `-k` 범위 밖). 520 target·additive report·72,800 중복 pointer 합성 fixture에서
실제 PREPARE + force_custom_plan/force_generic_plan 모두 target 520개, pointer CTE/scan 각 1회,
실행 10초 미만을 확인했다. lifecycle/answer-bearing/orphan/occurrence/선택 revision/페이지 분기도
유지한다. 이는 운영 SQL 개선 활성화나 GPU 계산 완료가 아니며 새 모델 실행은 없었다.
