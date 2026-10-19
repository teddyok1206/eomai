# Registered REVIEW 근거의 bounded batch 해석

작성: 2026-10-19 UTC. 상위 계약은
`REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_DESIGN.md`이며, 이 문서는 source 구현
경계다. 설치·INDEX claim·운영 증분 성공을 증명하지 않는다.

1. **책임/경계:** Catalog의 승인된 생성 Item 근거 해석을 최대 1,024개 exact source
   tuple 단위로 실행한다. 실제 operator owner가 제공하는 필수 authorization callback을
   모든 source의 읽기 전/반환 전에 호출한다. DTO나 DB approval은 권한이 아니다.
2. **정본:** 현재 Item/Revision/component/final step/Job/Artifact와 등록 manifest,
   원 authoring/review 결과, Orchestrator의 terminal trusted receipt/plan이다.
   materialization과 source/evidence/profile의 기존 의미는 변경하지 않는다.
3. **ID/revision:** source revision, Workflow/step/Job, Artifact/revision/SHA를 별도 key로
   유지한다. 중복 source revision/충돌 pointer는 거부하고 입력 순서로 결과를 반환한다.
4. **포인터 검사:** 기존 단일 resolver의 승인·final occurrence·schema/media/raw SHA·
   typed producer manifest hash·receipt·원 draft 위치·결정적 등록 content 대조를 같은
   검증 함수로 재사용한다. 누락/철회/중복 final/한 source의 오류는 전체 batch 오류다.
5. **접근 패턴:** bounded PK/FK IN lookup, type/ordinal component lookup, exact terminal
   event membership, immutable result member 해석, 입력 순서의 결정적 출력이다.
6. **자료구조/인덱스:** Item/Revision/Workflow/Job/Artifact PK, component revision FK,
   step Workflow FK, event Job FK, unique plan Workflow를 사용한다. batch로 수집한
   map/set은 현재 호출에만 존재한다. 새 table/index/cache/framework는 추가하지 않는다.
7. **규모/복잡도:** source n<=1,024, role<=3n, file-set<=2n이다. metadata query 수는
   n과 독립이고, CPU/IO는 O(metadata+실제 member bytes), 출력 정렬 없이 입력 tuple을
   보존한다. component는 source당 100, final role step은 정확히 세 개로 제한한다.
   파일 읽기는 기존 reader의 member/aggregate byte budget을 지킨다.
8. **트랜잭션/동시성:** caller Session의 fresh metadata batch와 root-local file-set
   reader를 사용한다. receipt batch는 caller Session에서 최신 rows를 읽고 순수 검증한다.
   role JSON public reader는 별도 bounded snapshot에서 같은 exact immutable pins를 확인한다.
   publication 전 기존 late source/IAM/lease/CAS 재검증은 별도로 유지한다.
9. **소유권/의존:** `evidence_usage_receipts`가 frozen internal pair request와 public
   in-session receipt batch를 소유한다. registered-review resolver는 metadata 수집과
   기존 검증을 조합한다. `CatalogArtifactService.load_json_revisions`는 Artifact adapter
   owner가 bulk metadata와 동일 FD/epoch/hash 읽기를 구현한다. 새 wire schema는 없다.
10. **실패/retry/idempotency:** 빈 tuple은 IO 없이 빈 결과다. bounds, 중복, pending
    Session mutation, missing/invalid source는 즉시 실패하며 skip/최신 대체/자동 retry는 없다.
    성공한 동일 원본은 동일 evidence를 산출한다. 부분 결과를 authority로 반환하지 않는다.
11. **단순 대안:** 단일 resolver를 n번 호출하면 role/receipt/file-set마다 Session/SQL을
    반복한다. 대신 metadata와 receipt는 batch 수집하고 기존 정확한 단일 검증 함수만
    반복한다. 단일 공개 API는 같은 batch 경로의 one-element composition으로 유지하며
    released profile/index/query wire, DB evidence-kind 관계와 runtime activation은 이 단계
    밖의 후속 경계다.

## 내부 API

`EvidenceUsagePairRequest`는 Workflow/authoring-review occurrence, exact ArtifactPointer,
선택적 provenance와 receipt SHA를 가진 frozen application input이다.
`resolve_pairs_in_session(session, requests)`는 같은 순서의 receipt pair tuple을 반환한다.

`resolve_registered_item_review_solutions(session, *, sources, artifacts, receipts,
authorize_source)`는 같은 순서의 `ResolvedRegisteredItemReviewSolution` tuple을 반환한다.
원 typed authoring/review 값을 유지하여 projection/embedding delta가 결과를 다시 읽지 않는다.

## 검증 계획

실제 임시 Artifact/typed producer와 공개 receipt owner로 단일/다중 동등성, 두 role family,
현재 approval/permission/manifest/Job/result/receipt/plan 실패와 unknown/missing/duplicate를
검증한다. 1/다중/1,024 입력에서 metadata query count가 고정이며 PK/FK IN 형태이고
single-source API loop/session.get가 없음을 확인한다. 새 운영/모델 실행 증거로 표현하지 않는다.

## Source 검증 기록

2026-10-19 UTC, 실제 임시 파일/typed producer/public receipt owner를 사용하는 batch와
기존 단일 resolver·receipt·profile·delta 다섯 suite가 **151 PASS / 43.59s**였다.
`/tmp/registered-review-batch-final-closure.xml`에 기록했다. 1/2/1,024 source에서 모두
metadata query는 17회이며 exact IN 조건과 `populate_existing`을 검증했다. 1,024 case도
실제 임시 member를 읽지만 Session은 SQL-shape를 기록하는 source fixture이므로 실제
PostgreSQL query plan/latency 또는 운영 incremental 완료 증거가 아니다. 혼합 role 11/12,
최종 권한 거절, 누락·중복 receipt/plan/final step/member, forged pointer 및 bounds를 포함한다.
별도 dependency/application boundary 두 suite **30 PASS / 17.03s**,
`/tmp/registered-review-batch-boundaries.xml`; strict mypy 네 파일과 Ruff/format 네 파일 통과.
설치·서비스·DB 변경·인증·모델 실행은 하지 않았다.
