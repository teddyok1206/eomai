# 생성 문항 검토 근거의 운영 증분 연결

2026-10-19 UTC. 사용자 요청으로 설정한 후속 목표의 구현 계획이다.
기초 계약·단일 source·순수 projection은 `2687b135`로 검증됐지만 운영 연결은 아니다.
상위 설계는 `REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_DESIGN.md`와
`SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md`다.

## 1. 책임과 경계

기존 INDEX/QUERY owner와 Catalog 등록·Graph 출판을 확장한다. 새 검색 엔진, queue,
worker protocol이나 분석 위조 경로를 만들지 않는다. CPU 운영을 보존하고 GPU 비교는
이 목표의 선행조건으로 삼지 않는다. 완료는 source가 아니라 실제 자동 delta/search다.

## 2. 정본

기출은 accepted V10 풀이, 생성 문항은 승인 Item+최종 REVIEW+trusted receipt가 정본이다.
생성 문항도 실제 accepted V2 분석이 기존 Graph source에 출판되어야 eligible이다.
현재 생성 Item 출판 helper는 옛25문항 occurrence 전용이므로 ordinary 최신 문항을
그 계약으로 처리하지 않는다. 별도 successor가 같은 공식 Graph owner를 사용한다.

## 3. 논리 entity와 revision

새 `embedding-source-binding/2.0`은 registered-review source 전용이다.
`embedding-index-manifest/2.0`은 검증된 binding1과 binding2를 함께 수용한다.
legacy profile1/binding1/shard1 bytes는 변경하지 않는다. source/Graph 변경으로
association이 달라져도 같은 text+space+partition의 encoding은 재사용한다.

혼합 namespace의 projection은 `mixed-solution-comparison/2.0`이다. 이는 composition
버전이고, 개별 binding의 실제 extractor는 기존 accepted1/registered-review1을 유지한다.
namespace2는 새 논리 index로 시작한다. 기존 namespace1 current/history를 바꾸거나
서로 다른 index의 revision을 FK predecessor로 꾸미지 않는다.

## 4. 포인터와 해석

binding2에는 실제 accepted V2 `base_analysis_run_id`, registered-review evidence/profile2,
Graph/정책/recipe/view, encoding과 기존 shard row가 필요하다. base ID는 실제 Graph
membership/accepted result/source pointer와 대조한다. REVIEW를 solution-analysis ID로
넣지 않는다. 등록/읽기/후속 context에서 승인·권한·revision·schema·media·hash·lifecycle을
재확인한다. native numerical worker는 이런 authority를 해석하지 않는다.

## 5. 주요 접근 패턴

bounded source 집합 membership, exact revision lookup, current Graph membership,
원 역할·영수증 batch lookup, encoding deduplication, immutable binding lookup,
CAS current-head 갱신, pinned historical context read다.

## 6. 구조와 인덱스

metadata는 bounded IN query+keyed map/set으로 모으고 source별 session/query를 열지 않는다.
`REGISTERED_REVIEW_BATCH_RESOLUTION_DESIGN.md`와
`CATALOG_ROLE_JSON_BATCH_READ_DESIGN.md`의 기존 공개 owner를 사용한다.

기존 embedding table을 확장한다. binding에 evidence_kind(legacy default),
review_job_id FK, review_evidence_sha256를 추가하고 solution-analysis/hash는 registered
분기에서만 NULL을 허용한다. 실제 base_analysis_run_id FK는 두 분기 모두 유지한다.
XOR CHECK로 legacy solution vs registered review를 강제한다. legacy UNIQUE는 보존하고
NULL 때문에 중복이 허용되지 않도록 registered association partial UNIQUE와 delta index를
추가한다. source_kind·extractor·manifest1/2의 조합도 CHECK로 닫는다.

## 7. 복잡도와 규모

최대1,024개 source/page와 최대3,072개 role 결과, 각 owner의 명시적 총 byte 한도를
사용한다. metadata O(n+c), row lookup O(n) expected, canonical sort O(n log n),
파일 검증 O(bytes)다. 전체 table scan·source별 반복 DB parse/read는 추가하지 않는다.
초과는 stable budget error이며 scientific text를 잘라 성공시키지 않는다.

## 8. 트랜잭션과 동시성

기존 claim/lease·source reauthorization·registration transaction·head CAS를 재사용한다.
native 결과는 기존 Artifact commit 후 metadata publication 경계에서 검증한다.
새 FK/UNIQUE의 concurrent duplicate, same-key replay, crash/late commit을 disposable
PostgreSQL에서 검증한다. 운영 DB에 pytest를 실행하거나 실패 이력을 고치지 않는다.

## 9. 의존 방향과 소유권

JSON Schema→frozen 계약→application use case→기존 PostgreSQL/NAS/Codex adapter 순서다.
Catalog 계약은 workflow/service를 import하지 않는다. 새로운 wire는 필요한 carrier만
successor로 추가하고 내부 union은 실제 지원 branch만 허용한다. common helper 추출은
실제 old/new 두 use case의 동일 규칙을 공유할 때만 한다.

## 10. 실패·retry·idempotency

old request는 old namespace/index/pins로 replay한다. 최신 조합을 선택하는 것은 새 요청뿐이다.
missing/stale/hash mismatch/철회/지원 안 되는 old REVIEW는 명시적으로 거부한다.
native numeric protocol·space·shard는 그대로라 새 source만 encode/reuse를 결정한다.
전체 GPU 절차, 새25문항/HWPX 생산이나 같은 문항의 반복 풀이를 검증 편의로 실행하지 않는다.

## 11. 더 단순한 대안

기존 V1 pointer/namespace의 묵시적 확장은 released 의미를 바꾸고, 가짜 V10 FK는 정본을
위조하므로 불가하다. 새 registry/queue는 기존 transaction/idempotency를 중복하므로 불가하다.
single resolver를 1,024번 호출하는 방식은 N+1과 반복 파일 조회 때문에 채택하지 않는다.

## 단계와 exit evidence

1. 원 role JSON public batch reader 및 metadata/receipt batch, 기존 one-source 호환 회귀.
2. ordinary approved Item의 공식 Graph publication successor와 실제 accepted V2 대조.
3. binding2/index2/namespace2/source-plan2와 실제 필요한 query/carrier successor.
4. branch-safe DB migration·repository·application·disposable DB concurrency/replay.
5. owner runtime/release·read projection·소비자 연결의 호환 installed 검증과 배포.
6. 승인된 실제 source delta의 encode/reuse count·검색·같은-key replay·권한 철회/복구.

각 단계의 SOURCE/DISPOSABLE_DB/INSTALLED/ACTIVE/LIVE 상태를 별도로 기록한다.
단순 테스트 개수·새 schema 수를 완료의 대체 지표로 쓰지 않는다.

## Runner 완료 carrier의 요청 계열 검증

2026-10-19 실제 연결 점검에서 native owner는 완료2를 게시하지만 Runner의 execute 반환
검사가 완료1 class만 허용하는 누락을 확인했다. 새 JSON Schema나 전환 상태를 추가하는
문제가 아니라 이미 출시된 request2/output2 대응을 기존 완료 검증에 연결하는 수정이다.
`_checked_completion` 한 곳에서 supported parser와 request/output 계열 대응을 확인하고,
그 뒤 원 Workflow/step/attempt/owner Job 및 receipt를 기존 owner가 검증한다. execute,
성공 step 재조회, terminal 완료와 exact replay가 같은 규칙을 사용한다. 반대 계열의
결과를 변환하거나 기존 실패/완료 기록을 제자리 수정하지 않는다.

이 변경은 수치 protocol/space/shard, DB schema/권한과 source/Graph 의미를 바꾸지 않는다.
실제 입력·영수증은 기존 immutable pointers가 정본이며 새 cache/queue/registry는 없다.
고정 class 분기와 bounded parsing 비용은 기존 완료 carrier 크기에 선형이다. 수정 SDK는
별도 immutable release와 INDEX service successor로 선택하고 기존 API/QUERY/Chat이
같은 commit이어야 한다고 강제하지 않는다. 기존 source의 진행 작업은 정상 종료와
공식 미착수 취소 경계로 처리하며 강제 재실행이나 SDK 파일 덮어쓰기를 하지 않는다.
