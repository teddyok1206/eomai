# 생성 문항의 독립 검토 기록을 증분 임베딩 근거로 재사용

작성: 2026-10-19 UTC. 상위 목표는
`SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md`이다.
이 문서는 구현 방향과 검증 순서를 정하며 운영 활성화의 증거가 아니다.

## 1. 문제와 책임 경계

현재 Item profile/INDEX 입력은 승인된 기출 V9 분석의 accepted V10 풀이보고서에
닫혀 있다. 생성 문항의 V2 분석에는 그 successor를 만들 수 없어, 생성 문항을
기출로 위장하지 않는 한 같은 경로의 대기를 끝낼 수 없다. INDEX reconciler가
새 분석을 실행하는 것도 그 모듈의 책임이 아니다.

생성 과정의 `review-result@11.0/@12.0`에는 이미 독립 도출 정답, 검증 결론,
원 draft의 RFC6901 위치, 5개 선지와 선택적 ㄱ/ㄴ/ㄷ 판정이 있다.
이를 **REGISTERED_ITEM_REVIEW_SOLUTION**이라는 별도 근거로 재사용한다.
accepted KnowledgeAnalysis V10, 공식 기출 해설, 전체 풀이 DAG로 재해석하지 않는다.
추가 worker/모델 실행이나 새 solve Workflow는 필요하지 않다.

## 2. 정본

정본은 승인된 정확한 Item Revision, 그 등록 manifest의 구성요소,
성공한 최종 authoring/review Artifact와 Orchestrator의 trusted evidence-usage
receipt이다. 새 근거와 profile은 이 정본을 가리키는 검증된 파생값이다.
`runtime_context.item_registration` checkpoint나 모델이 주장한 ID만으로
등록·권한·검증을 증명하지 않는다.

## 3. 논리 ID와 revision

Item ID, Item Revision, Workflow/step/Job, Artifact/Artifact Revision/SHA를
분리한다. 새 evidence는 자체 canonical SHA를 가지며 원 revision을 덮지 않는다.
profile2의 논리/불변 revision identity는 원 Item revision과 추출기 버전에
귀속한다. 기존 profile1/accepted-V10, 520개 인코딩과 과거 실행은 변경하지 않는다.

## 4. 포인터와 검증

evidence는 exact Item source, 등록 manifest member, ITEM_CONTENT member,
authoring/review step·Job·attempt·result member, 두 trusted receipt SHA를 담는다.
지원하는 result pair는 @11/@11 또는 @12/@12뿐이다.

Catalog resolver는 실제 호출자의 기존 source authorization 경계 안에서:

- 현재 APPROVED 상태와 정확한 Item/revision 소속을 확인한다.
- 등록 manifest bytes/schema/hash, component 순서·identity와 영속 등록 occurrence를 확인한다.
- 최종 unsuperseded 성공 step/Job, result member/schema/media/hash와 input occurrence를 확인한다.
- 기존 공개 receipt resolver로 원 Graph/Evidence/plan, authoring-review pair와 receipt SHA를 확인한다.
- 원 draft를 기존 결정적 등록 materialization으로 투영한 값이 실제 ITEM_CONTENT와 일치하는지 확인한다.
- 독립 정답·각 선지/진술·검증 위치는 원 draft에 귀속시킨다. 등록 시 stem·equation-source
  정규화가 있으므로 raw draft hash를 등록 JSON hash와 같다고 강제하지 않는다.

포인터는 권한 증명이 아니다. 후속 읽기·인덱스 binding 사용 시 원 source와 권한을
재확인한다. 없는 값/해시 불일치/철회/중복 final 결과에 latest fallback은 없다.

## 5. 주요 접근 패턴

정확한 revision lookup, bounded revision 집합의 membership/deduplication,
component type lookup, final step lookup, immutable member materialization,
결정적 ordered profile projection, 기존 missing-binding reconciliation이다.
우선 검증 범위는 최대 1,024개 source/page이며 전체 corpus 무제한 scan을 추가하지 않는다.

## 6. 자료구조와 인덱스

기존 Item revision PK/소속 FK, component unique `(revision,type,ordinal)`,
Workflow/Job/Artifact PK와 occurrence 인덱스를 재사용한다. resolver는 bounded IN query와
keyed map/set으로 모은다. receipt resolver의 검증을 복제하지 않고 공개 batch 경계를
확장한다. source마다 별도 query/session을 여는 N+1 경로는 INDEX에 연결하지 않는다.
새 table, queue, vector engine, registry나 캐시는 만들지 않는다.

## 7. 복잡도와 규모

한 page의 source 수 n, 구성요소 수 c, 실제 검증 result/member bytes b에 대해
metadata 수집·해시/파싱·projection은 O(n+c+b), 메모리는 bounded page와 검증 중
member에 한정한다. source당 result member를 한 번만 materialize한다.
긴 report나 바이너리를 DB에 복제하지 않는다. 기존 영수증·manifest는 원본을 참조한다.

## 8. 트랜잭션과 동시성

읽기 경계에서 기존 등록·승인 state를 검증하고, profile/encoding/index publication은
기존 claim/lease/idempotency/CAS 경계를 사용한다. 읽기 후 승인 철회나 source 변경이
있으면 publication 직전 재검증에서 차단한다. 이 기능을 위해 Item state나 실패 이력을
직접 갱신하지 않는다. profile identity와 encoding key가 같은 replay는 기존 결과를 재사용한다.

## 9. 의존 방향과 소유권

Catalog contracts는 storage-neutral typed pointer와 bounded conclusion만 정의한다.
workflow/domain/infrastructure를 역으로 import하지 않는다. Catalog application이
등록/영수증/정본 읽기 adapter를 조합하고, 순수 projection은 검증된 값만 변환한다.
worker에게 PostgreSQL/NAS 접근을 주지 않는다. NAS commit owner는 Orchestrator다.

## 10. 실패·재시도·idempotency

독립 report가 없는 구버전, 승인이 없는 문항, 불충분한 closure는 구분된 unavailable
결과다. raw draft path를 임의로 바꾸거나 선지 근거를 새로 생성하지 않는다.
`model_copy/model_construct`로 만든 값도 경계에서 재검증한다.
누락은 근거 없는 성공으로 승격하지 않는다. transient read failure와 영구 pointer/hash
불일치는 구분하며 현재 지원되는 기존 reconcile/retry만 사용한다.

## 11. 더 단순한 대안과 배제 이유

- 생성 문항을 PAST_EXAM/V9/V10으로 취급: 출처·anchor·schema 의미가 달라 금지.
- 기존 profile1의 solution pointer를 조용히 확장: released closure를 변경하므로 금지.
- 새 V11 분석/worker로 전부 다시 풀이: 기존 독립 검토를 활용하지 못하고 모델 사용량·
  control/prompt/materialization/state-machine 증가가 불필요하다.
- 원본 해설만 임베딩: 검토 근거와 독립 도출을 누락하므로 이번 요구를 충족하지 못한다.

## 표현과 정직한 한계

profile2는 원 review의 answer claims/choice/statement conclusion을 그대로 보존한다.
근거는 원 result 안의 JSON pointer와 원 draft의 scalar pointer로 구분한다.
없는 `solutionstep_*`, Graph node/anchor, decisive inference, 오개념 분류나
ordered dependency를 만들어 넣지 않는다. 모든 profile에 전체 풀이 DAG와 핵심 착상
확정 근거가 없다는 limitation을 포함한다. 이는 비공개 사고 과정이 아니라 이미
저장된 공개 검증 결론의 재사용이다. 두 문항의 풀이가 같다는 확률로 설명하지 않는다.

## 구현·검증 순서

1. 이 설계와 additive JSON Schema 2020-12 evidence/profile2를 먼저 정의한다.
2. Pydantic 동등성, exact-source closure, 순수 projection과 negative tests를 추가한다.
3. Catalog의 등록 REVIEW resolver와 공개 batch receipt 해석을 구현·검증한다.
4. source plan/profile/binding/index/registry/query의 **실제 hardpin 경계만** successor로
   연결한다. index successor는 legacy binding/shard를 그대로 수용해 기존520개를 재인코딩하지 않는다.
   encoding request/f32 shard/native numerical protocol/model space는 바꾸지 않는다.
5. 기존 registry의 evidence-kind 관계와 CHECK successor를 additive migration으로 검증한다.
   현재 `solution_analysis_run_id`는 NOT NULL FK라 REVIEW의 step을 그 칸에 넣을 수 없다.
   legacy-V10 관계는 그대로 유지하고 registered-review의 실제 step/Artifact 관계를 별도
   discriminator·FK·branch CHECK로 표현한다. nullable successor 분기를 추가한다면
   NULL을 포함한 기존 unique key가 중복 방지를 잃지 않도록 branch별 unique/partial
   index와 concurrency 테스트를 함께 설계한다. 무조건적인 nullable 완화나 가짜 analysis
   row 생성은 금지한다. 이 영속 successor는 이번 첫 source slice에서 구현하지 않는다.
6. compatible INDEX+QUERY/runtime identity를 준비한 뒤에만 설치·활성화한다. 기존 INDEX18의
   immutable identity를 새 코드로 덮지 않는다. 승인 source delta/replay/read를 실제로 검증한다.

1–3의 source/test 완료는 4–6이나 운영 증분 성공의 대체 증거가 아니다.
source→installed→active→live evidence를 별도로 기록한다.

## GPU 작업과의 분리

사용자의 2026-10-19 승인에 따라 정상 CPU INDEX/QUERY를 유지하며, 준비 단계가
`VALIDATION_OR_TRANSPORT_FAILED`로 종료된 full GPU 절차를 반복하지 않는다.
진단은 좁은 준비 단계에서 분리한다. 원래 CPU/CUDA 여섯 수치 측정과 gate는
삭제·성공 처리하지 않고 **NOT_STARTED**로 유지한다. 비교로 우수함이 입증되지 않은
GPU를 기본값으로 바꾸지 않는다. 이 source 작업에는 새 사용자 로그인이나 모델 실행이 없다.
