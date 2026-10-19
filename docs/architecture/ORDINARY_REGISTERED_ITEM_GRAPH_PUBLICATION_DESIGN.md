# Ordinary 등록 문항의 Graph 출판 successor

2026-10-19 UTC. `REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_DESIGN.md`의 upstream
source 작업이며 설치·활성화·실제 source 도착의 증거가 아니다.

## 1. 책임과 경계

현재 @11/@12 ordinary 생성 문항 1–16개를 기존 공식 Graph owner로 출판한다.
옛 `PublishApprovedItemAnalysesCommand`의 25개 시험 slot/occurrence 계약은 바꾸지 않는다.
생성·새 풀이·새 accepted analysis·INDEX/vector 실행은 이 use case가 하지 않는다.

## 2. 정본과 선행조건

정본은 실제 APPROVED Item revision, 실제 ACCEPTED V2 분석, 최종 등록된
authoring/review 및 trusted receipt다. ordinary 등록만으로 accepted V2가 생기는 것은
아니다. 없으면 기존 `CreateKnowledgeAnalysisCommand`를 통한 첫 분석이 별도의 선행조건이며,
이 publisher가 V2 row를 만들거나 REVIEW를 V10으로 바꾸지 않는다.

## 3. 논리 ID와 revision

새 command/result family는 source별 analysis run, Item revision, originating Workflow,
expected product unit, registered-review evidence SHA를 pin한다. predecessor Graph의
raw manifest pointer와 semantic snapshot hash는 구분한다. 기존 Graph/current/history는
기존 CAS를 통해서만 전진하며 exact replay가 다른 Graph를 새로 선택하지 않는다.

## 4. 포인터와 검증

원 @11/@11 또는 @12/@12 pair, source의 실제 accepted V2 및 등록 provenance,
Workflow definition/initial request/business hash/pinned plan, 원 curriculum scope를 검증한다.
등록 승인·최종 결과·receipt는 공개 batch registered-review resolver를 재사용한다.
command의 unit은 model claim이 아니라 실제 persisted request/plan의 product key와 같아야 한다.
현재 공통 origin-scoped alignment 정책에 맞는 정확한 MIDDLE/MINOR unit만 지원한다.
검토 JSON에서 Graph node를 새로 추론하거나 시험 occurrence를 만들어 넣지 않는다.

## 5. 주요 접근 패턴

최대16개 exact run/revision/Workflow lookup, source 집합 membership, final role/result/receipt
batch resolution, pinned predecessor unit lookup, ordered alignment 및 same-key publication replay다.
전체 corpus scan이나 source별 새 session/query는 이 adapter에 추가하지 않는다.

## 6. 자료구조와 기존 인덱스

bounded IN query와 run/revision/Workflow keyed map을 사용한다. 기존 PK/FK와
Graph publication idempotency unique key를 재사용한다. 새 table/queue/cache는 없다.
출판은 `AutomaticItemGraphPublicationService`의 공식 retrieval→origin-scoped alignment→
structure→Graph 경계에 맡기고, 기존 25-item publisher 검증을 복사·완화하지 않는다.

## 7. 복잡도와 규모

metadata는 O(n+c), 정렬 O(n log n), 실제 member 검증 O(bytes)다.
batch source/result/receipt 한도를 그대로 지키고 n<=16으로 제한한다.
공통 Graph owner의 전체 Graph projection 비용은 기존 정책과 같다.

## 8. 트랜잭션과 동시성

공통 Graph owner의 advisory lock/current-head CAS와 exact-source 재검증을 유지한다.
새 REVIEW approval도 최종 publication까지 보호해야 한다. 기존 typed analysis validator를
공통 publisher가 candidate 집합에 한정해 Graph owner의 공개 final-validation 인자로 전달한다.
Graph owner는 NAS 준비가 끝난 후 advisory lock/current-head CAS를 확인한 최종 DB
트랜잭션에서 이 callback을 실행한다. 새 adapter는 그 root에서 현재 actor/policy/source와
등록 proof의 bounded row만 잠그고 다시 해석한다. 별도 outer transaction을 NAS/중첩
session 동안 유지하지 않는다. callback 실패는 corpus revision/snapshot/head 생성 전에
중단한다. old None 동작은 그대로이고 callback은 wire/worker가 선택할 수 없다.
원 source/policy/actor의 현재 권한은 replay에도 다시 확인한다.

## 9. 의존 방향과 소유권

새 JSON Schema→frozen command/result→Catalog application→기존 owner/SQL/NAS adapter 순서다.
계약은 Workflow나 infrastructure를 import하지 않는다. 실제 actor의 현재 ADMIN/read/publish
권한과 released policy를 검증한 뒤 기존 ADMIN-scoped alignment 정책을 호출한다.
worker가 보낸 role/permission 문자열은 권한 증명이 아니다.

## 10. 실패·재시도·idempotency

없는 V2, 미승인/철회 source, stale predecessor, 다른 원 unit/Workflow, 바뀐 receipt는
공식 오류로 중단한다. exact command의 publication key만 replay한다. source가 이미 다른
publication에 속한 경우 implicit adoption/latest fallback은 없다. crash 중 이미 출판됐으면
원 immutable publication과 predecessor/member set을 확인해 같은 receipt를 반환한다.
검증 중 만들어진 alignment evidence는 기존 idempotency로 재사용한다.
재시도에서 원 alignment 시각은 그대로 유지하되 Graph의 requested_at은 원 alignment 시각과
명시적인 새 publication_authorized_at 중 늦은 시각을 사용한다. 승인 시각을 생략한 기존 경로는
그대로다.

## 11. 더 단순한 대안과 배제 이유

옛 25-item publisher에 버전만 추가하면 ordinary 문항에 없는 slot/production occurrence를
위조해야 하므로 불가하다. accepted V2를 생략하면 현재 Graph membership 계약을 바꾼다.
새 publisher engine/registry를 만들면 기존 commit/CAS 경계를 중복한다.
따라서 새 bounded selection adapter만 추가하고 기존 Graph owner를 재사용한다.

binding2/index2/namespace2/DB XOR migration의 소유권과 순서는 상위 integration 설계에 따른다.
legacy520개의 immutable source/binding/shard와 encoding을 이 작업에서 바꾸지 않는다.

같은 registered REVIEW 증명의 publication용 row-lock leaf는 readonly resolver와 분리한다.
Graph publisher와 mixed INDEX capture만 이를 명시적으로 호출하며, 현재 root/session/thread와
있다면 정확한 savepoint에 묶인 bounded row 참조를 보존한다. savepoint 종료 뒤에는 재사용할 수
없다. actual source/actor 권한이나 immutable member 검증을 대신하지 않는다. mixed capture는
공식 admission의 전체 source(V3 past-exam provenance 포함)를 보존하고 기존 profile1을 그대로
유지하며, 현재 ordinary grounded family만 batch REVIEW resolver와 pure projector로 보충한다.
지원하지 않는 과거 family는 명시적인 missing이고 현재 지원 family의 손상은 실패다. 새 role/Job/
receipt 의존성은 기존 population cache로 재사용하지 않고 caller의 같은 root에서 새로 확인한다.
