# 기출·창작·AI 공통 임베딩 전환 목표

작성: 2026-10-31 UTC. 사용자 승인: 공통 기준 재임베딩, GPU 사용,
검증·검색 전환 후 구형 벡터 삭제. 목표 상태 ACTIVE이며 완료 보고서가 아니다.

## 1. 확정 기준

문항 분류(기출/창작/AI)는 출처·권한·필터용 메타데이터다. 분류에 따라 임베딩의
입력 형식, 모델 또는 점수 기준을 다르게 선택하지 않는다.

공통 수치 입력은 이미 정의된 `public-solution-text/1.0` 및
`inference-transfer-view-recipe/2.0`의 **공개 가능한 풀이 단계 내용**으로 고정한다.
기출의 accepted solution report, 창작의 등록된 source solution report, AI의
검증된 전체 solution report를 같은 projection으로 보낸다. 보고서 JSON 전체,
family 이름, 문항 ID, 출처명, 편집 경고, 승인 상태는 벡터화하지 않는다.
문제 본문·단원 등 다른 자료는 원래 Graph/문항 정본과 필터에 보존한다.

- 공개 풀이 문장을 본래 순서대로 연결한다. 수치·단위·부정·첨자·지수·수식은 보존한다.
- Unicode NFC/레이아웃 공백만 정규화한다. 임의 요약·번역·빈 필드 추측·중간 절단은 금지한다.
- 같은 과학 문장의 field/step 분할·줄바꿈만 바뀐 경우 같은 입력 text/hash여야 한다.
- 전체 풀이 없는 AI review verdict를 전체 풀이로 위장하지 않는다. 해당 문항은
  REPORT_REQUIRED로 분리하고 기존 공식 보고서 작성 경로에서 보완한다.
- 같은 모델·revision·tokenizer·정밀도·normalization·DOCUMENT purpose 안에서 비교한다.
  GPU는 기존 승인된 BGE-M3 CUDA FLOAT32 공간을 사용한다. CPU fallback은 별도
  수치 공간의 명시적 경로이며, GPU 전환 완료 카운트로 합산하지 않는다.
- 공통 입력이어도 풀이 내용이 다르면 다른 벡터가 정상이다. 유사도 1을 문항 동일성의
  기준으로 쓰지 않고, 동일 문항 판정은 Item/revision/정본 hash로 한다.

위 정의가 기존 released projection 의미를 바꾸지 않는지 기존 회귀와 source capture로
확인한다. 변경이 필요하면 기존 bytes를 덮지 않고 successor를 먼저 정의한다.

## 2. 책임·식별·데이터 구조

1. **책임/경계**: Catalog가 공식 Graph source admission과 accepted/registered 보고서
   해석을 소유한다. 기존 Orchestrator/INDEX owner만 계산·검증·NAS commit을 수행한다.
2. **정본**: 기출 520개 원래 Item/accepted analysis/풀이보고서, 창작 원본·계보,
   AI Item/보고서는 불변이다. 이번 ‘손보기’는 파생 공통 입력을 만드는 것이며 원문 수정이 아니다.
3. **식별**: 대상 집합은 exact Item revisions + source/report/Graph/policy pins와 집합 hash로
   동결한다. 이후 등록되는 창작은 별도 증분 진행률이며 520 분모에 섞지 않는다.
4. **포인터 검증**: 존재·권한·승인/수명·schema/media·SHA·실제 Graph membership을
   기존 owner가 검사한다. 같은 text hash로 서로 다른 문항 identity/권한을 합치지 않는다.
5. **접근**: indexed revision/key lookup, bounded source paging, input hash set/dedup,
   ordered batch execution, append-only receipts, index head CAS를 사용한다.
6. **구조/index**: 기존 public source entry/encoding/binding/index/Artifact manifest 재사용.
   새 vector DB, 별도 검색 엔진, 복제 queue, 임시 직접 DB vector 삽입은 만들지 않는다.
7. **비용/규모**: projection은 O(공개 풀이 bytes), 입력 비교는 hash key 평균 O(1).
   기존 최대 16,384 source/bounded page/numerical batch 한도를 유지한다. 전체 재파싱·
   해시·Graph 조회의 반복은 실측해 줄이되 source/권한 검증을 제거하지 않는다.
8. **트랜잭션/동시성**: 공식 source fence → encoding reservation → numeric result commit →
   binding/index CAS 순서를 유지한다. creative registration과 INDEX는 독립 멱등 키로 연결한다.
9. **의존성**: contracts → 순수 projection → Catalog application → 기존 DB/Artifact/GPU
   adapters. UI는 공식 API만 호출한다. worker 간 직접 통신/DB/NAS 쓰기는 금지한다.
10. **실패/재실행**: 이미 같은 새 recipe/space/input hash로 완료된 encoding은 재사용한다.
    결측/길이 초과/철회/실패는 개별 사유를 기록한다. 구 벡터 relabel, 실패 이력 성공 변경,
    미완료 target의 임의 제외, 다른 문항 보고서 대입은 금지한다.
11. **단순 대안**: 기존 벡터 우회 검색만으로는 cross-format 비교가 통일되지 않는다.
    raw JSON/출처별 renderer도 양식 편향을 남긴다. 기존 공통 projection의 정식 backfill이
    새 검색 플랫폼보다 작고, 원래 source/권한/증분 프레임워크를 보존한다.

## 3. 수행 순서와 종료 조건

| 단계 | 작업 | 종료 증거 |
| --- | --- | --- |
| U01 | 현재 source/report/encoding/INDEX 실제 상태와 정확한 원래 520 대상 집합 동결 | 분류별 수, target-set hash, 현재 config/runtime pins |
| U02 | 세 분류의 공통 입력 계약·adapter·동등성/정보 보존·AI full-report coverage 검증 | 회귀 PASS, report→공통 text/hash provenance, 결측 목록 |
| U03 | 진행 중 GPU batch를 정상 drain하고 기존 owner에서 공통 namespace backfill을 우선 실행 | 실제 CUDA 결과·공식 commit/binding receipt, 대상별 처리 상태 |
| U04 | 520 전체 GPU encoding과 정식 index, 동일 기준 검색/query·metadata·GUI 연동 검증·전환 | 520/520 또는 명확한 미완료, 실제 검색/replay, 새 기본 경로 |
| U05 | 구 인덱스·벡터·조회/실험/runtime 참조 inventory → 지원되는 retirement/삭제 | exact deletion manifest, 보호 대상 불변, 삭제 후 신규 검색 PASS |

U03는 기존 public GPU 결과 중 **같은 규격**으로 이미 완료된 것을 재사용한다.
구 accepted/mixed projection 벡터를 새 형식으로 이름만 바꿔 세지 않는다.
INDEX가 현재 구형 6 namespace와 새 공통 namespace를 번갈아 처리하는 비용도 확인한다.
불필요한 구형 membership 갱신이 backfill을 계속 지연시키면 기존 지원된 owner config로
후속 수치 작업 제출을 줄이고 public 작업을 우선한다. 진행 중 수치 runtime pin은 바꾸지 않는다.

DB의 유사도 조회는 출처 종류가 아닌 동일한 recipe/space/input 기준을 사용한다.
CPU/GPU current head의 Graph가 일시적으로 다르다는 사실만으로 전체 검색을 거부하지 않도록
각 pinned source/index의 실제 권한과 준비 상태를 검증하는 기존 계약 안에서 정리한다.
새 검색 준비가 확인되기 전 구형 데이터를 삭제하거나 READY로 과장하지 않는다.

## 4. 구형 벡터 삭제 범위와 안전장치

### 창작 Graph 재개의 검색 seed 범위 — 2026-11-01

책임은 기존 Catalog GraphRAG의 bounded lexical seed 선정이다. 정본은 요청에 핀된 Graph의
node/term/source-pointer이고, accepted 보고서와 원 topic keys/request/evidence는 변경하지
않는다. read-only 진단에서 새 accepted concept key가 현재 Graph의 exact key에는 없지만,
기존 lexical adapter로 실제 교과서 자료를 찾을 수 있음을 확인했다. 다른 source-class의
노드가 작은 seed budget을 먼저 채우는지 재현하고, 그렇다면 lexical 후보를 요청한
source-class membership으로 제한한 뒤 기존 rank/walk/source resolver를 그대로 사용한다.
이 조건은 권한 부여가 아니며 원 actor/정책·최종 source/hash/lifecycle 검증은 유지한다.

주 접근은 `(Graph revision, term)`의 indexed lookup 및 같은 Graph/node/source-class의
`EXISTS`다. 원 term B-tree, source-pointer unique key의 Graph/node prefix와 source-class
index를 재사용하며 N+1/materialization/Graph 복제는 없다. bounded query와 map/set ranking,
기존 max_nodes와 두 hop 한도를 유지한다. 정확한 query plan을 확인하고 새 index는 필요가
실측될 때만 검토한다. source-class가 다른 pointer를 join해 frequency를 중복 계산하지 않는다.

새 wire/worker behavior/영속 schema/queue는 없으며 dependency 방향도 Catalog application→
기존 DB adapter 그대로다. 읽기 root와 canonical evidence commit/replay transaction은 기존
소유자에 둔다. 이미 발행한 Evidence는 같은 원 key로 반환하고 새 알고리즘으로 덮지 않는다.
실제 근거가 없으면 기존 insufficient-evidence 오류를 유지한다. 실패를 성공 처리하거나
문항별 하드코딩 alias, 한국어를 ASCII topic key로 삽입, source-class 확대, 근거 생략으로
우회하지 않는다. 별도 검색 플랫폼/보고서 재작성보다 기존 seed query의 범위 수정이 작다.
배포는 source·actual pinned Graph read 회귀 뒤 isolated creative owner만 대상으로 하고,
숫자 runtime/API/QUERY/INDEX 및 그 실행 pin은 그대로 둔다.

후속 실제 단원 연결은 마지막 hop에서 불필요한 비단원 노드까지 확장해 node↔seed 관계가
한도를 넘었다. 최대3-hop의 마지막 이웃은 MINOR unit인 경우만 결과에 영향을 준다.
마지막 SQL에서만 같은 Graph의 MINOR 목적지를 제한한다. 앞선 hop·모든 가능한3-hop 단원·
seed별 최단거리·support/distance/tie ranking과 원 정책/hash/한도는 그대로다. 실제로 결과에
사용하지 않을 마지막 비단원 상태를 만들지 않는 정확한 pruning이며 임의 early-stop이나
한도 인상이 아니다. 기존 Graph/endpoint·unit unique index를 이용하고 새 round trip은 없다.
동일 ranking을 무제한 BFS oracle와 대조하고 큰 dead-end fanout에서도 원 safety bound와
정책1.0/1.1/1.2 replay를 검증한 뒤 같은 isolated owner에 반영한다.

사용자는 새 임베딩 전환 후 기존 벡터 삭제를 승인했다. 삭제 대상은 해당 기출의 구형
accepted/mixed embedding 파생 데이터이며, 기출·교과서·창작·AI Item/Graph/풀이보고서
정본은 삭제 대상이 아니다. 공유 shard에 새 벡터/비대상 벡터가 있으면 파일 전체를 지우지 않는다.

- 먼저 exact index revisions/encoding hashes/shard pointers/active consumers를 inventory한다.
- 새 GPU 데이터·검색 전환·필요한 rollback 증거가 확인된 뒤 구형 writer를 멈춘다.
- historical query/experiment 핀의 참조를 조사하고, 필요한 명시적 retirement/tombstone과
  최소 감사 manifest를 남긴다. 구 핀을 새 인덱스로 몰래 바꾸지 않는다.
- 참조가 남아 안전하게 삭제할 수 없는 범위는 원인과 필요한 지원 종료 절차를 기록한다.
  무관한 기록까지 추가 삭제하는 권한으로 확대하지 않는다.
- 실제 삭제 후 수량/byte 범위·복구 가능 여부를 보고한다. 삭제를 완료했다고 표시하려면
  새 검색 재검증과 보호 정본 hash/수량 불변 확인이 필요하다.

## 5. 진행·보고

### 원 Catalog 파일 저장의 중단 복구 — 2026-11-01

책임은 기존 core-owned `CatalogArtifactService`와 Orchestrator Job/Artifact 경계다. 정본은
원 semantic request/Job ID/Artifact ID/revision 및 검증된 source·proposal·risk pins다. 기출/
창작/AI 보고서나 worker 실행을 새로 만들지 않는다. dominant access는 원 idempotency key와
Job event sequence의 indexed lookup, 고정 크기 intent의 hash 비교, 한 file-set의 bounded
stage/commit이다. 새 queue/table/index/DB migration 없이 원 unique key와 append-only events를
사용한다. 비용은 한 번의 명시적 stage O(file bytes), metadata 검증 O(member count)다.

새 저장은 최초 COMMITTING event에 원 request/result/manifest SHA·고정 created_at을 schema-
validated intent로 남긴다. exact replay는 같은 Job/key/Artifact revision과 intent를 사용한다.
같은 publication key는 기존 Orchestrator 방식의 session advisory lock으로 직렬화하며 NAS
I/O 동안 관계 row transaction은 열어두지 않는다. 마지막 DB commit은 원 Job row를 잠가
COMMITTING→SUCCEEDED만 수행한다. FAILED/CANCELLED/기타 중간 상태의 성공 재해석은 없다.

구형 unsealed COMMITTING은 기본 fail-closed다. 단, knowledge acceptance application이 원
actor/creator/현재 permission·완료 Workflow·정본 source·proposal receipt·risk policy·result를
재검증하고 NAS final/등록 revision 모두 없음을 확인한 경우만 명시적 재구성 근거를 append해
같은 Job을 이어간다. 이 근거 DTO는 권한이 아니며 실제 application callback을 다시 호출한다.
구형 NAS final이 이미 있거나 확인이 불명확하면 채택/덮어쓰기하지 않는다. 새로운 sealed
저장은 NAS rename 전후/DB commit 전후 중단 모두 원 intent로 복구한다. 불명확한 결과를
새 key로 우회하거나 이전 로그/이력을 지우지 않는다.

Protocol의 작은 frozen intent/basis는 schema-first이며 질문/보고서/bytes를 event에 복제하지
않는다. DB/NAS/locking은 기존 infrastructure adapter에 두고 domain은 filesystem/SQL을
import하지 않는다. 최초 실패의 NAS 원인은 아직 미확정이며, 재현 가능한 결함은 adapter에
원 COMMITTING 복구와 고정 manifest epoch가 없다는 점이다. schema/event·pointer/hash/
lifecycle·동시성·rename 전후/DB commit 중단은 unit 및 disposable PostgreSQL에서 검증한 뒤
isolated creative owner에 반영한다. 직접 row UPDATE나 새 Artifact key보다 기존 owner의
검증된 original-identity replay가 작고 원 이력을 보존한다.

30분 기존 관측을 재사용하고 phase 전환·실패·완료만 Slack 중요 보고한다.

### 채팅 검색의 공통 수치 형식 중단 복구 — 2026-11-01

책임은 기존 private Chat QUERY의 네 단계(ALLOCATION/EXECUTED/PUBLISHED/COMPLETED)와
원 Job/event store다. 정본은 실제 Chat origin/원 Workflow request2/launch1/작은 원 실행
record2와 committed receipt2이며, 비공개 질문은 history에 복제하지 않는다. logical/revision/
hash/producer IDs는 그대로 분리한다. coordinator2는 기존 allocation·실제 private CPU unit
observation을 재사용하되 PUBLISHED는 private execution-record2 + 공통 numerical result2,
COMPLETED는 private output2만 허용한다. PUBLIC REFERENCE purpose로 바꾸거나 private1
frame을 relabel해 채택하지 않는다. 실제 고정 private unit의 template hash와 runtime bundle/
환경·source pin 검증은 기존 physical owner에 남긴다. source model만 추가해 실행을 허가하지
않으며 실제 numeric entrypoint/owner/runtime 설치·역할 권한/현재 origin을 별도로 검증한다.

주 접근은 원 launch Job PK lookup, sequence가 연속인 최대4 event의 ordered history와 작은
hash 비교다. 기존 unique Job/sequence, 원 Job row lock와 per-original command/root transaction을
재사용하므로 O(1) bounded metadata/space이며 새 table/index/queue는 없다. pure contract는
SQL/NAS/Chat client를 import하지 않고 기존 Orchestrator adapter만 영속화를 소유한다.
중단은 같은 원 launch/producer/member와 pinned receipt로 재개하며 FAILED를 성공으로
바꾸거나 새 identity로 우회하지 않는다. 기존1 bytes/hash·판정은 유지하고 private1/2·public
purpose 혼합을 거부한다. 별도 coordinator/queue를 만드는 대안보다 기존 순수 invariant와
같은 store의 명시적 successor가 작다. 최초 contract/fixture 단계는 source-only이고 운영
activation이나 old vector 삭제의 근거가 아니다.

릴리스의 비편집 설치본 검사는 과거 head0066을 하드코딩해 새 소스67도 거부하고 있었다.
빌드한 exact Git archive의 `migration.py`에서 단일 정적 문자열을 AST로 읽어 설치본의
선언과 정확히 비교한다. 소스를 import/실행하지 않으며 누락·중복·표현식·symlink·크기 초과나
잘못된 버전 표기는 거부한다. 기존 build commit/tree/archive SHA/RECORD 검증과 별도
root release-operator의 migration allowlist는 그대로다. 이는 패키지 일치 검사일 뿐 DB67
업그레이드 승인이나 운영 호환성 증명이 아니다. 실제67 배포는 기존 operator successor와
drain/rollback·활성 consumer 검증을 마친 후에만 수행한다.

다음 physical leaf는 기존 private CPU unit/owner directory/고정 FD·host capacity lock을
공유한다. Prepared value는 private request1/policy1/native1 또는 private request2/policy2/
common numerical2의 정확한 조합만 받는다. public REFERENCE Workflow를 private 권한으로
채택하지 않는다. unknown family의 최초 읽기는 기존 common QUERY 상한1MiB 안에서만
수행하고, private1의 기존128KiB 상한은 원 schema 및 후속 family 검사로 그대로 유지한다.
private2에는 이미 정의된 common1MiB 상한을 적용하며 truncation은 없다. 파일 identity/mode/
hash와 원 launch marker·실제 unit invocation·벡터 차원/유한성/L2 검증을 생략하지 않는다.
질문은 owner-local input에만 있고 canonical intent/result/shard/binary publication은 기존
소유자를 사용한다. 새 service/template/실행 권한/DB·queue를 만들지 않으며 actual owner/
admission이 준비되기 전 numerical leaf 지원만으로 운영2를 켜지 않는다.
기존 `run_native_private_chat_query_descriptors`는1-only/128KiB로 남긴다. 새 supported leaf만
1/2를 받으며, 고정 private entrypoint는 설치된 source pin 아래 이 leaf를 선택한다. 기존
reference leaf/INDEX purpose로 바꾸지 않고, 라이브 구형 private owner는 계속1-only를 검사한다.
현 private QUERY unit은 다른 CPU 작업과 동일한 보호 Conda 실행환경과
`/etc/eom/embedding-native-cpu.env`를 쓴다. 실제 private2 전환 때에는 이 공용 프로그램/
configuration/receipt/runtime bundle과 소비자 정책을 함께 검증·조율해야 하며, 실행 중인
수치 작업 밑에서 package나 env를 바꿔치기하지 않는다. GPU 실행 파일·환경의 원 pin도
유지한다. source-only FD 테스트는 이 운영 호환성 증명을 대신하지 않는다.
Slack 첫 문장은 한국어 요약이며 문항 내용·보고서 전문·인증 정보는 보내지 않는다.
goal 완료는 GPU 프로세스 active나 설치 PASS가 아니라 U01–U05의 실제 결과로 판단한다.

### 채팅의 공통 DOCUMENT 실제 읽기 경계 — 2026-11-01

책임은 기존 `CatalogPublicSolutionSimilarityRead`의 공식 Graph/source/index 읽기다.
이미 정의한 private similarity request2의 exact Graph/policy/index/recipe/space pins를 사용하고,
개인 질문을 approved Item anchor로 만들지 않는다. 정본은 원 accepted/registered 보고서와
기존 encoding/index Artifact이며, 이 작업은 새 corpus/index/queue/schema를 추가하지 않는다.
동일한 actor-fenced Catalog owner의 `resolve_lookup`와 pinned index reader를 사용한다.
새 private read만 closed request2를 받고, 기존 Item-to-Item request3/4의 의미는 유지한다.

주 접근은 bounded source capture, revision/hash map과 indexed Artifact lookup, 한 index의
ordered numerical rows다. 같은 materialization boundary에서 원 capture/document 값을 반환하며
보고서나 파일을 새로 복제·영속화하지 않는다. 공유 pure document proof를 재사용해 등록된
기출/창작/AI 계보·base/report hash·binding·finite/L2 vector closure를 동일하게 검사한다.
비용은 기존 bounded O(공개 풀이 bytes + N*D), 공간 O(N*D), 최대16,384 source다. 새 index나
list 반복 탐색은 없다. source/permission/lifecycle은 읽기 전후 같은 caller root에서 새로 확인하고
원 index pin을 latest로 대체하지 않는다. private origin/현재 turn 검증은 별도 Chat owner 책임이다.

Catalog application→기존 Registry/Artifact adapters 의존 방향과 read-only transaction을 유지한다.
source-only read는 실행·권한 부여가 아니며 실제 private source owner/native admission 연결이
완료되기 전 활성화하지 않는다. 실패는 기존 redacted source/index/authority 오류를 반환하고
write/retry/new query를 만들지 않는다. 더 단순해 보이는 가짜 Item anchor나 legacy CONTENT_ONLY
read 재사용은 공통 report/index4 및 비공개 질문의 의미를 보존하지 못하므로 사용하지 않는다.

### 실제 Chat origin과 공통 풀이 source owner 연결 — 2026-11-01

기존 `CatalogPrivateChatQuerySourceOwner`의 원 operator/현재 turn/claim 및 canonical policy/
runtime bundle 읽기를 공유한다. 작은 closed policy2는 기존 Orchestrator file-set publisher의
명시적 새 publication으로만 저장하고, 기존 policy1 publication/read API는1-only로 보존한다.
설정의 policy schema와 Registry namespace family가 일치해야 한다. question은 실제 Chat
owner에서만 materialize하며 Job/control Artifact/DB/로그에 복제하지 않는다.

원 request1/2와 origin/Graph/policy/space/report pointers를 핀하고 동일 root에서 원 actor를
읽기 전후 확인한다. 공통 request2는 기존 Catalog DOCUMENT owner를 사용하며, 마지막
Chat authorization RPC 뒤 source/index closure를 다시 확인해 중간 철회·교체를 거부한다.
전후 O(공개 풀이 bytes + N*D)의 bounded capture와 immutable pointer/hash 비교이며 새 DB/
queue/index/cache는 없다. canonical question의 NFC/공백 등 내용도 이 단계에서 다시 쓰지 않는다.
materialization scope가 끝나면 권한을 재사용할 수 없다.

legacy와 common의 resolved value 및 native input builder는 명시적으로 구별한다. 공통형은
기존 numerical QUERY2를 생성하고 원 launch/input hash와 재구성 비교한다. 실제 source
owner 검증이 native 실행 허가는 아니며 executor/dispatch/install/admission은 별도 연결한다.
기존 application→Catalog/Chat/Artifact adapters 방향, caller transaction, 멱등 publication과
실패 이력을 유지한다. 결측/철회/잘못된 family/hash는 stable redacted 오류이며 latest/retry/
새 Job로 우회하지 않는다. 모델이 준 actor나 가짜 approved Item으로 만드는 대안은 실제
사용자 권한·계보를 보존하지 못하므로 사용하지 않는다. 새 의존성·운영 schema 변경은 없다.

### common private 요청의 기존 명령·lease/step 연결 — 2026-11-01

책임은 원 private START/ADVANCE row lineage와 source owner admission이며 새 실행 scheduler가
아니다. 이미 정의한 request/definition/protocol2와 numerical result2를 같은 원 Workflow/step/
command/launch Job에 연결한다. 정본은 원 initial request·고정 definition bytes/hash·Chat origin/
operator와 append-only 원 command/checkpoint다. metadata support만으로 전역 admission2를
열지 않으며 실제 executor/완료/dispatch/runtime 조립 전에는 새 운영 요청을 받지 않는다.

PK/원 idempotency key/command parent의 indexed lookup과 최대4개 checkpoint 순서를 공유한다.
step의 expected result schema와 Workflow protocol은 canonical pure family 규칙에서 선택하고
legacy row를2로 relabel하지 않는다. 상태·계보·attempt/generation·현재 lease/원 producer/
현재 actor/claim/Graph/source를 같은 caller root에서 확인한다. application source admission은
두 resolved family의 정확한 typed 결과만 돌려주고 어느 family의 현재 권한도 캐시하지 않는다.
원 transaction/CAS/unique constraints/DB67 guard를 사용하므로 작은 O(1) metadata와 기존
bounded source read 외 새 queue/index/table/migration이 없다. 원 command/advisory lock 순서는
바꾸지 않는다. 종료/FAILED/다른 parent/hash/만료 claim을 새 key나 성공 재해석으로 우회하지 않는다.

pure family 선택은 contracts에, attached ORM/lease 검사는 기존 runner application/adapters에
둔다. 별도2 전용 queue/runner와 복제 상태기계를 만드는 대안보다 동일 원 명령 경계의 명시적
successor 지원이 작다. 실제 임시 PostgreSQL의1/2 중단·재전송·중복 claim을 확인하며 운영 DB
pytest/실제 native 추론 없이 먼저 검증한다. 실제 deployment/operator/runtime 승인은 별도다.

### private2 계산·네 단계 canonical 완료 연결 — 2026-11-01

기존 `CatalogNativePrivateChatQueryExecutor`와 completion/publication reader를1/2가 공유한다.
정본은 원 request/launch Job, 최대4개 ALLOCATION/EXECUTED/PUBLISHED/COMPLETED 기록과
원 producer의 validated Artifact/receipt다. family dispatch는 pure/기존 source adapter에 두고
새 runner/queue/상태기계를 복제하지 않는다. request1은 native1/result1/receipt1만, request2는
common numerical2/result2/receipt2만 받으며 predecessor bytes/hash와 원 key는 바꾸지 않는다.

접근은 원 launch key/Job PK·최대4 event·typed file-set pointer lookup이다. O(1) metadata와
기존 bounded source 재확인/단일 numerical row 검증이며 새 DB/index/migration은 없다. alias/
문항/Graph/report를 복사하지 않고 question은 owner-local 입력에만 둔다. canonical private
결과는 기존 intent/result/shard/binary, 완료는 기존 one-member receipt publication만 사용한다.
원 source와 recipe/model/space/runtime/worker-purpose pins, 실제 file identity/hash/finite/L2와
producer/manifest provenance를 Catalog·Orchestrator의 원 경계에서 검증한다.

같은 caller-root command/lease/source fence 안에서 allocate·checkpoint·publish하고 물리 CPU
실행은 DB root 밖에서 한다. 저장/전달 전에는 actual origin/source/lease를 다시 확인한다.
terminal completion은 canonical bytes와 현재 권한으로 재조회하며 이전 unit이 사라졌다고
재추론하지 않는다. uncertain/BUSY는 같은 원 작업으로 대기하고 FAILED/CANCELLED는 성공으로
바꾸거나 새 identity로 우회하지 않는다. 공유 protected CPU 환경과 runtime bundle 변경은
별도 drain·호환 rollout 후에만 가능하며 이 source 연결로 admission2를 열지 않는다.

contracts→기존 application→고정 launcher/FS/Artifact adapters 방향을 유지한다. 공통 builder/
receipt/checkpoint의 명시적 family dispatch를 재사용하는 것이 두 실행기를 복제하거나 public
REFERENCE 목적을 private 권한으로 채택하는 대안보다 작다.1/2 정상·중단 후 재전송·권한 철회·
known failure·원 producer/해시 불일치와 임시 PG canonical 저장을 확인하고, 실제 runtime/
모델·authenticated Chat 검증은 설치·activation 이후의 별도 증거로 남긴다.

### private1/2 Runner step·terminal 공유 — 2026-11-01

기존 private application step과 공통 native terminal이 원 request family에 맞는 output만
받도록 확장한다. 정본은 같은 Workflow/step/command/launch/receipt이고 current origin과
lease 권한은 기존 owner가 계속 검사한다. 원 definition/request/result family·hash를 맞춘 뒤
하나의 attempt에서만 READY→RUNNING→SUCCEEDED→기존 terminal을 진행한다. 최대4 checkpoint와
step/Job PK lookup은 기존 indexed O(1)·bounded 구조이며 새 DB/index/queue/migration은 없다.
질문·풀이·binary를 Workflow context에 복제하지 않고 private origin context를 그대로 보존한다.

application-defined port는 supported request/output union을 받고, 순수 계약의 family selector와
schema validator를 재사용한다. adapter가 규칙을 복제하지 않는다. DB root 밖 numerical 실행,
완료 전후 root fence, 동일 command continuation·idempotent replay 및 original ALLOCATION
검증은 그대로다. uncertain은 원 작업 대기, FAILED는 terminal로 유지한다. 다른 family output,
잘못된 actor·step·receipt·늦은 lease 철회는 전이를 거부한다. 두 Runner/terminal을 복제하는
대안보다 기존 책임 소유자에 명시적 family 검사를 추가하는 쪽이 작다. 이 연결만으로 global2
admission이나 새로운 runtime/SQL 권한을 열지 않으며, 실제 dispatch/submit/설치는 별도다.

### private2 원 접수·START 저장 경계 — 2026-11-01

기존 private submission과 Workflow repository에 supported1/2 request를 연결한다. canonical
source는 exact validated request/origin context·released definition·current source/정책/runtime
pins이며 새 최신값 대입은 없다. 원 actor/turn 기반 key로 indexed Workflow lookup 및 unique
request fingerprint를 재사용한다. 신규 생성/동일 replay/late source withdrawal은 같은 root와
기존 savepoint에서 처리하고, 다른 family/hash/origin은 conflict다. START는 원 Workflow에
하나만 연결되며 late 거부는 caller root 전체를 rollback한다. 큰 payload/질문/binary를 새 DB
필드에 저장하지 않으며 새 schema/migration/index/queue는 없다. bounded indexed metadata와
기존 권한·Artifact 해시 검증으로 동작한다. contracts→application→기존 repository/Artifact
adapters 방향을 유지한다. 별도 submission framework보다 기존 owner의 family 검증과 저장
타입을 확장하는 편이 작다. global2 admission은 전체 dispatch/runtime 검증 전에는 열지 않는다.

### DB 검색 준비의 root-local 불변 해석 재사용 — 2026-11-01

07:20–07:24 UTC 실제 GUI 요청은210.655초 걸렸고, 같은 준비 작업의 source admission이21회
관측됐으며 아직 QUERY Workflow는 없었다. 별도 read-only canonical control profile에서
selection1.5 최초 해석8.26초(cProfile overhead 포함)와 schema registry 초기화가 확인됐다.
전체 원인이나 운영 개선률을 이 수치만으로 단정하지 않는다. 기존 권한/Graph/현재 상태
검사를 생략하거나 timeout만 올리지 않고, 반복되는 불변 schema 해석을 먼저 줄인다.

책임은 기존 `PinnedArtifactReadContext`의 bounded root-local decoding이다. canonical source는
계속 Artifact revision/member/raw SHA와 매번 읽는 현재 DB metadata다. logical/revision/hash를
합치지 않는다. page reader는 원 metadata·physical member/FD/hash·현재 source/권한 검증을
각자 수행하고, 오직 같은 Session/root/thread/settings의 decoder만 root reader에 위임한다.
큰 corpus의 page별 provenance budget과 root decoder32MiB/2048 LRU 한도를 그대로 유지한다.
임의 source/auth/result DTO나 mutable model은 재사용하지 않는다. key는 exact member tuple
또는 complete canonical current-value SHA와 stable decoder identity다. lookup 평균O(1),
space는 기존 bounded LRU이며 root 종료·다른 Session/thread/settings에는 재사용하지 않는다.

공통 operator source capture만 기존 `for_session` root reader를 사용하고256-source page는
별도 provenance reader를 유지한다. shared decoding은 actual validation을 통과한 불변 모델만
대상이며 현재 source recapture·metadata/provenance recheck·late withdrawal guard는 유지한다.
worker/protocol/DB/schema/migration/queue/영속 cache/전역registry를 추가하지 않는다. dependency
방향은 기존 application→Catalog artifact adapter다. 같은 canonical 해석을 source별로 매번
반복하는 대안보다 기존 decoder owner를 공유하는 쪽이 작다. cache hit/eviction/변조/현재권한/
root·Session·thread 경계/대규모 paging과 설치본을 검사한다. end-to-end210초 개선 여부는
실제 authorized same-request 검증 전까지 PENDING이며 단위 PASS로 운영 성공을 대신하지 않는다.

기존 미배포 legacy stored-read 후보는
`staging/unified-embedding-goal-20261031/deferred-legacy-read.patch` 및 같은 폴더
`deferred/`에 복구 가능하게 보존했다. 이번 공통 전환과 섞어 활성화하지 않는다.

### U01/U02 체크포인트 — 2026-10-31 09:00 UTC

- 원래 기출 520개 exact Item revisions/manifest hashes를 고정했다. target-set hash:
  `sha256:57a227ea705bedb73cc7573b38f1baf995fa3f697f81c323f251cf4e8e228678`.
  원본 target 목록은 root 보호 운영 기록 `/var/lib/eom-unified-embedding-migration-20261031/baseline.json`.
- 같은 snapshot의 Graph는 기출520/창작283이다. AI source는 해당 Graph에 0건이다.
  이것을 전체 Registry AI가 0건이라는 뜻으로 확대하지 않는다. AI full-report source capture와
  공통 CUDA 입력 동등성은 별도의 synthetic 회귀로 검증하고 실제 등록 범위는 추가 확인한다.
- 공통 CUDA `39bc2c310299...`에서 기출16/등록 문항12의 binding이 이미 있었다.
  CPU의 기출3/등록1은 별도 공간이고 overlap이 가능하므로 GPU 완료 수에 더하지 않는다.
  원래 기출520 목표에서 새 GPU 형식 미완료는 이 snapshot 기준504개다.
- installed config6 decoder는 `legacy_configuration=null` 및 `maximum_targets=16`을 지원한다.
  기존 공통 recipe/모델/space/자원/서비스 권한/QUERY/API는 그대로 둔 채, 구형6 namespace의
  추가 maintenance만 제외하는 protected selection을 preflight했다. 원래 최대4건에서16건은
  discovery target 묶음이며 실제 model forward의 minibatch/resource profile은 변경하지 않는다.
  config 전환은 아직 runtime activation 증거가 아니다.
- DB initial 검색 범위는 **하나의 실제 published GPU head 전체**에서 Graph/policy를 선택한다.
  독립적으로 늦게 발행된 CPU head와 Graph가 다르다는 이유만으로 GPU 검색까지 차단하지 않는다.
  source 해석은 같은 공통 recipe이며, 실제 QUERY owner의 device/index/CPU fallback 검증은
  그대로 유지한다. replay는 원래 Graph/policy pin을 보존한다.

### U02 추가 발견 — AI 전체 풀이보고서의 실제 producer 경계

2026-10-31 10:16 UTC source/installed inventory를 대조했다. 공통 projection의 입력
동등성 테스트는 세 분류에 대해 통과했지만, 그것은 **AI의 실제 보고서 생성·등록 경로가
활성화됐다는 증거가 아니다**. 기존 `knowledge-analysis-request/10.0` 및 base pointer는
occurrence/page evidence를 가진 기출 V9만 허용한다. 일반 승인 AI의 분석 V2를 V9/V10으로
이름만 바꾸거나, `source_class=PAST_EXAM`으로 바꾸어 통과시켜서는 안 된다.
이를 JSON Schema/Pydantic 양쪽에서 거부하는 회귀를 추가한다.

현재 source_kind 미기록 APPROVED1/IN_REVIEW1은 accepted analysis와 Graph source가
모두0이다. 실제 생성 Workflow provenance를 확인하기 전 미기록을 AI로 단정하지 않는다.
이 문항을 향후 같은 basis로 자동 처리하려면 다음 경계를 닫아야 한다.

1. 기존 Catalog 승인 Item 분석 → accepted base → 공개 가능한 전체 풀이보고서 → 같은
   Graph source/index admission 순서를 재사용한다. 별도 학습 queue나 Graph는 만들지 않는다.
2. 기출 V9/V10 및 report1 bytes는 그대로 보존한다. 일반 승인 Item의 accepted base와
   포인터를 실제로 허용하는 additive successor를 먼저 정의한다. AI origin은 실제
   생성 Workflow/Item revision provenance로 검증하며 분류명만 믿지 않는다.
3. 공개 풀이보고서는 기존 `KnowledgeAnalysisSolutionReport`의 검증 가능한 풀이 단계,
   개념 연결, 선지 진단, 해설 비교와 불확실성 기록을 재사용한다. 독립 검토의 결론이나
   짧은 정답 문구를 전체 풀이로 승격하지 않는다. 모델의 비공개 사고 기록을 요구하지 않는다.
4. 새 evidence pointer는 실제 accepted-result/receipt/report schema와 hash를 가리킨다.
   기존 public entry/index의 closed evidence family에 새 의미를 몰래 추가하지 않고
   필요한 successor를 사용한다. **텍스트 recipe/encoder는 동일**하며 이미 계산한
   공통 text/space/hash의 수치 벡터는 재사용한다. provenance 변경을 수치 재계산과 혼동하지 않는다.
5. source/read authority, 기존 원자적 claim, append-only 분석 이력과 accepted successor
   uniqueness를 그대로 유지한다. 필요한 uniqueness 확장은 disposable DB에서 검증한다.
   요청·분석 base·승인·Artifact revisions와 hash가 idempotency와 transaction 경계다.
6. producer/Graph/public capture/INDEX/QUERY가 실제로 호환되는 조합으로 활성화되기 전에는
   AI 입력 지원 전체 PASS라고 보고하지 않는다. 현재 GPU 재임베딩 runtime은 이 개발 때문에
   중단·교체하지 않으며, 호환 전환은 수치 배치의 정상 종료 경계에서만 수행한다.

이는 새 문항 생산 기능이나 검토 엔진 재설계가 아니라 이번 목표의 ‘AI도 같은 실제 풀이
자료를 사용한다’는 조건을 닫기 위한 후속이다. 검토 요약을 재사용하는 더 작은 대안은
보고서 내용 기준을 달리하므로 이번 목표의 대체가 될 수 없다. 구현 전 정확한 successor
번호는 현재 registry를 확인해 선택하며, 이 문서만으로 새 release를 활성화하지 않는다.

### 일반 승인 Item의 전체 풀이보고서 연결 설계 — source 후보

- 책임: 기존 Catalog KnowledgeAnalysis application이 accepted V2 base를 검증하고
  V11 풀이보고서 요청·reconcile·risk·accept를 처리한다. Orchestrator의 기존 support
  worker/Artifact commit을 재사용한다. 새 queue/Graph/DB 보고서 본문 테이블은 만들지 않는다.
- 정본/identity: 원래 Item revision, V2 accepted-result Artifact와 receipt1/7개 normalized
  members는 불변이다. V11은 새 분석 run/revision과 report1 한 개만 추가한다. accepted-result의
  self-hash와 실제 JSON 파일의 SHA는 다른 핀으로 각각 검증한다. reference index는 작은 파생
  값이며 정확한 base members와 request hash에 고정된다.
- source 역할: 새 일반 Item base의 locator는 실제 canonical Item JSON의 RFC6901 pointer다.
  excerpt hash는 그 위치의 **canonical JSON value** SHA다. V1 `body`/`interaction`과
  `solution`, V2/V3의 발문·자료·선지와 `answer`/`explanations`를 구조로 구분한다.
  anchor 이름/출처명으로 답안 위치를 추측하지 않는다. 모델이 pixels를 보지 않은 JSON-only
  입력에는 시각 검수/기출 페이지를 만들어 넣지 않는다. 예전 다른 locator 관례의 accepted
  base를 제자리에서 변환하지 않으며 명시적으로 호환되지 않는 입력으로 남긴다.
- access pattern: predecessor의 indexed lookup, successor history의 ordered iteration,
  accepted successor uniqueness, anchor/node membership map, append-only events다. base-row
  lock으로 요청 생성과 replay를 직렬화하고 기존 unique idempotency/workflow 제약을 유지한다.
  새 V11 accepted successor에는 `predecessor_analysis_run_id`의 별도 partial unique B-tree를
  추가한다. 기존 V10 index/predicate와 기존 승인 이력을 바꾸지 않는다. lookup/insert는
  O(log N), pointer depth가 제한된 source index 생성은 O(A * D + V log V), 작은 파생 metadata만
  저장한다. 수천/수만 문항으로 늘어도 전체 report/NAS 스캔을 요청별 lookup에 쓰지 않는다.
- transaction: 기존 원자적 Workflow/plan/run/event/command 생성과 Artifact commit 후
  acceptance CAS를 재사용한다. V11 partial uniqueness의 migration 왕복과 동시 승인은
  disposable PostgreSQL에서 검증하고 운영 GPU pin이 유지되는 릴리스 경계에서만 적용한다.
- dependency/실패: typed contracts → application → 기존 Catalog byte reader/DB adapter 방향이다.
  missing/stale/schema/media/hash/source-role 불일치는 bounded error로 거부한다. 같은 key는 원래
  request/result를 replay하고 다른 입력은 conflict다. FAILED 이력은 성공으로 고치지 않는다.
- 더 작은 대안인 기존 V10을 일반 Item까지 넓히기/검토 요약을 전체 풀이로 대신하기는 각각
  released source 의미 또는 공통 수치 입력 기준을 깨므로 사용하지 않는다. 운영 활성화 전
  source candidate를 production-ready로 표시하지 않는다.

### AI 보고서의 공통 evidence/index 연결 — 다음 구현 경계

기준은 ‘세 분류가 같은 공개 풀이 텍스트/recipe/encoder/수치 공간을 사용한다’는 것이다.
출처별 정본이 다른데 evidence envelope까지 같은 과거 schema라고 위장하는 것은 기준이 아니다.
다음 successor는 수치 입력을 다시 설계하는 작업이 아니라 실제 승인된 V11 보고서의 출처 핀을
전달하는 작업이다. 2026-10-31 11:54 UTC registry에서 아래 제안 번호의 기존 사용0을 확인했다.

- canonical source: 승인 Item revision + accepted V2 base + accepted V11/report1 + 공식 Graph
  admission. 기존 기출 V10/창작 source report도 그대로 정본이다. 새 AI evidence kind는
  `ACCEPTED_REGISTERED_SOLUTION_ANALYSIS`로 구분하고 result11/receipt10/report1의 exact
  Artifact member/semantic hash/raw SHA를 가진다. PAST_EXAM이나 creative lineage로 재분류하지 않는다.
- JSON Schema-first: 제안 entry2/profile2/binding4/index4는 별도 closed 계약이다. 과거
  entry1/binding3/index3 bytes는 바꾸지 않는다. 새 입력 해석은 entry1(기출·창작)과 entry2(AI)를
  명시적으로 dispatch하되 **공통 public text1/recipe2만** encoder에 보낸다. type 이름·kind·ID·
  hash·분류·경고는 임베딩하지 않는다. 숫자/수식/부정어를 바꾸거나 본문을 잘라 길이를 맞추지 않는다.
- metadata 재포장 때문에 이미 계산한 기출/창작 vector를 또 만들지 않는다. index4는 원래
  binding3를 그 identity/hash/schema 그대로 참조하고 신규 AI binding4만 추가할 수 있어야 한다.
  previous manifest는 정확한 index3/index4 핀만 허용한다. source 중복/row/shard 정렬과 hash,
  schema/media/lifecycle/permission 검증은 기존 owner에서 유지한다.
- access pattern은 기존 indexed Graph/source lookup, keyset paging, text/space hash encoding
  deduplication, immutable ordered manifests, atomic registration/CAS다. 새 queue/DB/vector store를
  만들지 않는다. 기존 index/unique constraints가 새 provenance를 실제 수용하는지 먼저 대조하고
  필요한 좁은 successor만 추가한다. 목표 규모와 paging 상한은 현재16,384/페이지256을 유지한다.
  lookup/dedup은 indexed O(log N), rank는 기존 실제 cosine의 bounded O(ND)다.
- shared schema/model/projection → Catalog capture/application → 기존 DB/Artifact/native adapter
  의존 방향을 유지한다. actual operator/pinned policy로 source를 재허가하며 metadata 계약을
  새 권한으로 취급하지 않는다. worker는 staged local input만 읽고 Orchestrator만 commit한다.
- 동일 text hash + partition + numerical space는 같은 encoding identity를 사용한다. 서로 다른
  source/report revision은 별도 binding으로 보존한다. missing/변조/revoked/report 불완전은
  explicit unavailable/error다. review 요약이나 최신 revision으로 fallback하지 않는다.
- INDEX/QUERY/registry/read/실제 DB 검색이 같은 successor를 지원하는 조합을 검증하고
  실행 중인 GPU 배치의 정상 종료 경계에서만 선택한다. 과거 history나 현재 request pin을
  몰래 새 schema로 바꾸지 않는다. 실패하면 새 head의 발행을 막고 기존 검증된 head를 보존한다.
- 더 작은 대안인 entry1의 frozen evidence union에 AI를 끼워 넣기 또는 AI를 creative/past로
  가장하기는 lineage를 깨므로 사용하지 않는다. 모든 과거 binding을 새 metadata로 일괄
  복제하는 것도 불필요하므로 하지 않는다. 이 설계는 아직 운영 activation 증거가 아니다.

#### 실제 DB/carrier 대조 결과 — 12:10 UTC

`PUBLIC_SOLUTION_REPORT`의 기존 evidence 제약은 APPROVED_ITEM과 실제 solution run을 이미
수용한다. 별도 AI encoding table이나 새 evidence-kind DB column은 필요하지 않다. 다만
binding/index revision의 manifest schema whitelist와16384 coverage 조건은 index3에
고정돼 있어 index4를 발행하기 전 그 세 CHECK만 명시적으로 확장하는 migration이 필요하다.
기존 binding3/encoding rows는 수정·복제하지 않는다. downgrade는 신규 index4 이력이 있으면
거부해야 하며, concurrent head CAS와 immutable predecessor 보존을 disposable DB에서 검증한다.

현재 source plan/native work carrier는 entry1의 closed shape다. entry2를 무리하게 통과시키는
대신 해당 carrier와 registry/QUERY까지 필요한 successor를 먼저 정의한다. entry2 parser와
공통 encoder의 지원만으로 현재 INDEX runtime이 새 AI 입력을 지원한다고 선언하지 않는다.
이전 결과를 새 계약으로 재해석하거나 JSON schema 검사를 우회하지 않는다.

#### 변경하지 않을 수치·실행 경계 — 12:18 UTC

실제 참조를 대조하니 INDEX의 native work-batch와 아래 수치 계약에는 AI provenance가
들어가지 않는다. entry2를 지원한다는 이유만으로 이 계약/실행 그래프를 새로 만들지 않는다.

- numerical space/recipe, unit-f32le vector binary와 shard1;
- incremental embedding input/result1과 실제 tokenizer/encoder/pooling/L2;
- GPU 할당·host-capacity lock·자원 상한·유한 배치 수명;
- `local-embedding-index@2.0.0`의 동일한 application step 그래프.

새 shape를 실제 포함하는 source plan, request의 source-plan schema pin, ownership/receipt,
registry/index 참조와 검색 anchor/result의 metadata carrier만 successor가 필요하다. QUERY
work-batch2는 query2를 직접 포함하므로 그 경로는 별도 검증 대상이다. INDEX의 수치 실행
frame과 QUERY의 근거 metadata frame을 구분하고, 모든 carrier를 일괄 재버전하지 않는다.
번호는 실제 registry와 충돌하지 않는지 확인한 후 정한다. 기존 common pure validators,
atomic claim/CAS/동일 text encoding lookup과 exact source permission boundary를 재사용한다.

#### Source plan4 구현 시 확인한 경계 — 12:46 UTC

- 기존 raw parser/native metadata는 배열1,024개까지만 읽지만 public index의 선언된 상한은
 16,384다. 기존 parser/계약의 상한은 유지한다. 신규 source plan4/index4만 별도 bounded raw
  진입점으로16,384개와8M node/깊이32/각 계약 byte budget을 적용한다. 수치 native Job의
  row/batch 상한은 늘리지 않는다. source plan4는 기존 native처럼 raw float를 정수로
  coercion하지 않고 거부한다. source1,025개가 모두 보고서 미준비인 경우에도 임의 encoding을
  만들지 않고 명시적 missing으로 보존하는 scale fixture를 사용한다.
- plan3/4의 coverage/source-set/encoding-set/Graph/namespace/hash 규칙과 staged entry/index
  대조는 같은 순수 validator를 사용한다. map/set/index join을 유지하며 새 queue/lookup store를
  만들지 않는다. source plan4는 기존 기출/창작 profile1/evidence와 AI profile2/evidence의 정확한
  짝만 받는다. 같은 text/space는 하나의 encoding row, source/report는 별도의 demand다.
- AI Graph 등록 경로를 재대조했다. 과거25문항용 `ApprovedItemGraphPublicationService`의
  production whitelist를 최신 single-item Workflow에 맞춰 넓힐 필요가 없다. 기존
  `OrdinaryItemGraphPublicationService`가 이미 generic1.11–1.16의 실제 review/plan/Workflow
  origin과 권한을 검증해 공식 공통 Graph publisher에 연결한다. V2 base를 그 경로로 등록하고
  V11 additive report를 정확히 조회하는 방식을 재사용한다. 실제 운영 operation 활성화와
  대상 sample provenance는 activation 때 별도 확인한다. source 확인을 live PASS로 간주하지 않는다.

#### Index4 저장 경계의 후보 migration0066 — 12:59 UTC

기존 Registry application transaction/operation replay/head CAS와 PUBLIC_SOLUTION_REPORT
binding의 indexed key를 그대로 사용한다. canonical source는 승인된 보고서/Graph와 immutable
index/shard Artifacts이며 command4/receipt4는 그 exact pins와 이전/현재 head 관측만 전달한다.
`20261031_0066`은 binding manifest/schema, index revision manifest/schema, public coverage의
세 CHECK에 index4를 추가하는 후보다. 기존1–3과 다른 evidence kind 제약, FK, unique B-tree,
불변 trigger와 canonical 데이터는 바꾸지 않는다. 새 테이블·queue·vector store·DB payload는 없다.

lookup은 기존 indexed O(log N), association 구성은 기존 map/set 및 canonical sort다. 같은
text/space의 numeric row는 재사용하며 원 binding3의 최초 manifest와 SHA는 갱신하지 않는다.
기존 lock/savepoint/CAS가 transaction/concurrent boundary다. migration 왕복·기존3→4 전환·
동시 등록·중단 rollback/replay는 disposable DB에서 검증한다. index4/binding4 이력이 있으면
downgrade가 이를 지우거나 기존 계약으로 재해석하지 못하게 거부한다. 새 운영 schema 적용은
호환 release/operator qualification 이후에만 한다. 더 작은 대안인 manifest3 위장은 실제
V11/receipt10 provenance를 표현하지 못하므로 사용하지 않는다.

#### 공통 source capture의 실제 registered-report 연결

기존 Catalog public-solution capture의 Graph/source/operator admission을 재사용한다.
창작은 기존 등록 lineage 보고서, 기출은 accepted V10, 나머지 APPROVED_ITEM은 실제 accepted
V11을 읽는다. `metadata.source_kind` 문자열을 AI 권한·근거로 믿거나 V10 기출 pointer로
위장하지 않는다. 각 resolver는 accepted predecessor run을 indexed bulk lookup하고 원본
Artifact bytes/hash/receipt/report를 검증한다. metadata 누락이나 report 부재는 missing으로
남긴다. text는 동일한 projection 함수 한 곳에서만 만든다. candidate map/set과 bounded
capture를 유지하여 N+1을 추가하지 않는다. 이 변경 자체로 source-plan3 runtime에 entry2를
허용하지 않으며, native/QUERY successor의 exact pins와 호환 release 검증 전까지 활성화하지
않는다. 원본 보고서·Graph·DB schema 변경은 없다.

#### Native metadata4 연결 경계

source-plan4를 native request4가 exact pointer/raw SHA/semantic hash로 고정한다. 기존 request3
wire/schema bytes와 INDEX2 실행 graph 및 numeric Job/input/result1은 변경하지 않는다.
request3/4의 공통 field와 service/policy/reference 검증은 한 pure body/helper로 재사용하며
최상위 released literal와 source-plan schema 선택은 각 concrete parser가 소유한다. 계산 batch
상한1,024와 기존 GPU/host lease·실행 정책은 그대로다. ownership/receipt/coordinator의
provenance carrier만 필요한 successor를 이어서 추가하고 기존 transaction/claim/replay/CAS를
재사용한다. source-plan3로 실제 V11 evidence를 위장하는 단순 대안은 허용하지 않는다.
원본 source lookup·권한과 canonical Artifact 저장은 기존 owner 경계이며 새 DB table·queue는
없다. 새 metadata4의 installed/recovery/negative qualification 전에는 운영 활성화하지 않는다.

Completion4는 registry4의 exact command/result와 plan4/request4/ownership4를 묶는다.
기존 receipt3/4의 공통 closure는 typed body와 pure validator 한 곳에서 검사하고, concrete
schema parser는 서로 교환하지 않는다. INDEX4 조립은 기존 map 기반 row/shard 선택과 binding
생성 경계를 재사용한다. 원본 report text를 재구성하거나 DB/NAS를 직접 쓰지 않으며,
entry 기반 최초 조립과 plan 기반 후속 조립은 같은 manifest builder를 이용한다.
동일 encoding은 수치 row1개·provenance별 binding으로 유지하고 ordered hash는 결정적이다.
중단 후에는 기존 append-only coordinator 순서와 exact original producer pointers를 재사용한다.
