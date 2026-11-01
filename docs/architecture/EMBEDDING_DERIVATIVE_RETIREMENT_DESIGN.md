# 구형 임베딩 파생 데이터의 안전한 지원 종료

2026-10-31 UTC. 공통 임베딩 목표 U05의 설계/진행 기록이며 삭제 승인이 아니다.
상위 범위: `UNIFIED_ITEM_EMBEDDING_GPU_MIGRATION_GOAL_2026-10-31.md`.

## 책임과 정본

Catalog는 encoding/binding/index의 소유 관계와 수명 검증을 담당한다. Orchestrator는
계산 Job/Artifact/worker 결과 및 NAS 저장 경계를 담당한다. 운영 owner의 명시적
유지보수만 삭제를 수행할 수 있다. worker·모델·일반 API 요청은 삭제 권한을 갖지 않는다.

기출 520개 Item revisions/manifest hashes, accepted 분석·풀이보고서, 교과서, 창작/AI 정본,
Graph와 무관한 이력은 보호한다. 원래 target-set hash를 그대로 사용하며 현재 Graph에
추가된 창작을 520 분모나 구형 기출 삭제 대상에 섞지 않는다.

## 식별과 포인터

- 정리 범위는 logical Item ID + exact Item revision + manifest SHA의 정렬된 동결 집합이다.
- encoding hash, binding hash, index ID/revision, Artifact ID/revision은 서로 다른 개념이다.
- shard의 소유 범위는 `(artifact_id, artifact_revision_id)`다. 경로 또는 logical Artifact
  ID만으로 묶지 않는다. 내부 소유권 계산은 이 작은 불변 key만 비교하며 bytes를 읽지 않는다.
- 실제 파일 해석/삭제 전에는 원래 owner resolver가 schema/media/hash/권한/수명과 실제
  디렉터리/파일 identity를 검증해야 한다. 소유권 계산 결과는 이 검증이나 삭제 권한이 아니다.

## 접근 패턴·구조·규모

주 접근은 동결 revision membership, encoding→bindings 및 shard→encodings의 key lookup,
중복 검출과 의존 관계의 보호 집합 계산이다. set/map을 사용하고 결과는 정렬된 tuple이다.
등록된 encoding/binding 각 행을 한 번 읽고, registry 소유권 분류는 O(E+B), 결정적인 출력
정렬까지 O(E log E+B log B), 메모리는 O(E+B)다. target 상한은 기존 public scope 16,384를
넘기지 않는다. 읽기 adapter는 기존 indexed revision/encoding/shard 조회를 재사용한다.

같은 encoding을 다른 문항이 참조할 수 있고, 같은 shard에는 서로 다른 encoding이 들어갈
수 있다. 따라서 target binding, target만 사용하는 encoding, target만 사용하는 shard를
각각 계산한다. binding 수나 source_class 한 개로 shard 전체 삭제를 추정하지 않는다.
binding이 없어진 미귀속 row도 공유 shard의 실제 잔여 encoding이므로 보호한다.

## 최소 구현 순서

1. 읽기 전용 registry 소유권 분류기를 먼저 구현·검증한다.
   이는 새 wire message나 worker 동작이 아닌 내부 frozen value/순수 함수다. 새 schema,
   DB migration, queue, runtime feature flag는 만들지 않는다.
2. 실제 동결 집합에 대해 metadata inventory를 얻는다. legacy partition과 accepted
   binding만 후보로 잡고, public partition/new projection/비대상 source는 보호한다.
   mixed index도 이 원래 binding을 재사용하므로 index 이름과 binding 의미를 혼동하지 않는다.
3. 기존 index의 canonical manifest membership 및 previous-revision 관계를 owner resolver로
   검사한다. 최초 binding manifest는 모든 후속 index의 membership 목록을 대체하지 않는다.
4. 실제 FK와 구조화된 JSON carrier, 설치된 INDEX/QUERY/출제·변형/Chat 소비자를 조사한다.
   임의 문자열 등장만으로 canonical 참조나 삭제 대상이라고 판단하지 않는다. 알려지지 않은
   carrier는 명시적으로 미분류로 남기며 자동 삭제하지 않는다.
5. 새 GPU 520 coverage/대상별 해시·권한·실제 검색/read/replay를 확인한 뒤에만 writer와
   소비자의 지원 종료를 선택한다. 활성 기능을 없애거나 과거 request를 새 recipe로 위장해
   삭제 조건을 충족시키지 않는다. 필요한 실제 소비자 successor만 별도 schema-first로 정의한다.
6. 실제 lifecycle/삭제 command·receipt는 inventory 결과에 맞춰 최소 범위로 정의한다.
   기존 canonical Artifact와 owner transaction 경계를 재사용하는 방법을 먼저 검토한다.
   새 영속 구조가 필요하면 그 필요성을 먼저 증명하고 disposable DB에서 검증한다.
   이 문서로 아직 결정하지 않은 tombstone table/framework를 선행 구현하지 않는다.

## 트랜잭션·동시성·실패

inventory는 쓰기를 하지 않는다. 계획을 실제 삭제에 사용할 때는 대상 집합/hash와 현재
소유 관계를 transaction 안에서 다시 검사하고, 활성 lease/claim/Job와 원래 물리 handle을
대조한다. 오래된 inventory 파일이나 PID0 한 항목을 삭제 권한으로 사용하지 않는다.

Catalog는 자기 테이블만 변경하고, Orchestrator는 자기 Artifact 경계만 변경한다.
서로의 private 모듈/테이블을 우회 변경하지 않는다. 모호한 timeout 뒤에는 실제 적용 상태를
읽고 같은 identity로 재확인한다. failed 이력을 성공으로 바꾸지 않는다.

완료 기록에는 exact 삭제/보존 ID·hash·파일 byte 범위와 사유, 실제 적용 순서, 복구 가능
여부가 필요하다. 공유/비대상 shard는 파일 전체를 지우지 않는다. 보호 정본과 무관한 이력을
추가 삭제하는 방식으로 공유 참조를 없애지 않는다. 구형 벡터 삭제는 아직 실행하지 않는다.

## 단순 대안과 제외

`partition` 전체 삭제, 520×3 같은 추산 수량 삭제, broad prelaunch AI reset 재호출은
비대상 canary/공유 shard/다른 소비자를 손상시킬 수 있어 사용하지 않는다. 반대로 소유권을
판정하지 않고 전부 보존하는 것도 요청된 U05 완료를 대체하지 않는다. 먼저 실제로 안전한
범위를 계산하고 남는 참조·제외 원인을 증거로 남긴다.

검증은 중복·dangling encoding·서로 다른 Artifact revision·공유 encoding/shard·미귀속 row·
public partition 보호·결정적 출력·단일 source iteration과 대규모 합성 입력을 포함한다.
향후 실제 삭제/replay/중단/동시성은 disposable PostgreSQL에서만 검사한다.

## 실제 소비자 조사와 최소 연결 변경 — 2026-10-31 21:12 UTC

별도 immutable 설치본 `65112860`의 순수 분류기를 사용한 read-only inventory에서,
동결 기출의 구형 binding 80,474개와 수치 encoding 3,120개가 후보로 확인됐다. 이는
서로 다른 Graph/revision의 alias와 수치 row를 구분한 수이며 삭제 실행 수가 아니다.
같은 shard closure에 비귀속 encoding 6개가 있어 공유 shard 6개는 보호한다. 전체 파일을
지워 이 잔여 row를 잃는 처리는 하지 않는다. manifest membership/FK/JSON 소비자는 아직
별도 검증 대상이다. 정확한 사유·ID는 보호된 운영 inventory에 남긴다.

actual API process/config에서 reference preparation, reference Item start, exam similarity
observation이 켜져 있고, Chat process도 `NATIVE_TOPIC`/`READ_ONLY`다. 설치된 source와
대조하면 출제·기출변형은 기존 context1/delivery1/plan23·24, 채팅 주제 검색은 private
context1/CONTENT_ONLY namespace를 사용한다. DB 화면의 공통 검색만 통과했다고 이 구형
인덱스를 지우면 현재 켜진 다른 기능이 깨질 수 있다. 기능을 끄거나 원 request를 새
recipe라고 재해석해 정리 조건을 맞추지 않는다.

첫 최소 변경은 기존 전달 책임의 successor `system-rag-similarity-delivery/2.0`이다.
이미 있는 공통 context3/4의 exact Artifact member/raw SHA와 request/context semantic SHA만
전달한다. 기존 delivery1 bytes는 그대로 두며 두 family를 상호 relabel하지 않는다. 추가
DB/queue/cache/모델/벡터 저장소나 대형 payload는 필요 없다. 검증 비용은 bounded context
bytes에 선형이고, 이 값 자체에는 transaction·권한·독립 lifecycle이 없다. 실제 publication,
Item-start plan/worker read, 채팅의 공통-index successor는 각 기존 owner에서 후속 연결한다.
이 계약만 추가한 상태는 실제 소비자 전환이나 삭제 gate PASS가 아니다.

source 후보는 기존 Orchestrator `similarity_context_artifact`의 공개 풀이 발행 경로까지
연결한다. context1과 context3/4 각각의 closed validator를 거친 뒤 같은 canonical-byte
file-set publisher를 재사용한다. 서로 다른 receipt family는 별도 frozen typed result로
돌려주며, 동일 키의 다른 context/family는 conflict다. commit 이후 잘못된 receipt를 받으면
이미 생긴 Artifact/Job를 보존하고 같은 키로 재확인한다. 새 키/추가 native 실행은 없다.
이 단계는 Item-start API·plan·role와 Chat의 활성 consumer 전환을 대신하지 않는다.

공개 보고서 context의 READY/PARTIAL/EMPTY를 그대로 유지하며 FAILED는 전달하지 않는다.
선택한 request와 schema family/raw/semantic hash가 다르면 복구 추측 없이 거부한다. 과거
history는 기존 decoder로 남긴다. 더 작은 대안인 delivery1의 schema union 확대는 released
의미를 바꾸고 old consumer가 새 context를 잘못 해석할 수 있어 배제한다. native GPU 배치,
공통 입력 text/recipe/수치 공간과 실행 pin은 이 내부 전달 변경으로 바꾸지 않는다.

### 다음 owner 경계: 공식 Item publication2

API-only 기존 `PUBLISH_ITEM_SIMILARITY_CONTEXT` operation에 closed request/reply2를
추가한다. 입력은 실제 인증 operator ID와 원래 completed QUERY selection뿐이고, 출력은
앞 절의 delivery2와 owner Job/manifest hash다. context3/4 원문을 API에서 발행하거나
source 권한·native launch 지시를 전달하지 않는다. 기존 request/reply1은 그대로 해석한다.

Catalog의 기존 publication application 안에서 원래 QUERY3/4와 consumer purpose
`ITEM_AUTHORING`/`PAST_EXAM_VARIATION`을 확인한다. 실제 operator fence 및 WORKFLOW_START
permission을 적용하고, 기존 공식 completed-public-query read로 exact Graph/report/index/
query pins를 다시 해석한다. Orchestrator file-set commit 전후 같은 root에서 재허가·재조회하고
Artifact member/provenance를 대조한다. 동일 key의 timeout/replay는 같은 canonical 발행을
반환한다. 늦은 source 변경·권한 철회·receipt 오류는 실패이며 이미 commit된 산출물은 보존한다.

별도 queue, table, migration, model 실행과 worker 동작 변경은 없다. 조회는 원래 selection의
indexed lookup, ranking은 기존 bounded O(ND), 공통 payload materialization은 O(context bytes)다.
key는 실제 operator/QUERY/context SHA에 고정하며 fresh request의 latest를 해석하지 않는다.
dependency는 typed contracts → 기존 application → Catalog/Orchestrator storage adapters다.
같은 engine/root와 IAM/Artifact owner를 재사용하고 외부 component 테이블을 우회 변경하지 않는다.
실제 plan/role/Item-start 선택과 Chat의 public-index 연결은 이후 별도 소비자 단계이며,
이 publication2 지원만으로 운영 전환 완료를 주장하지 않는다. 단순히 publication1의 delivery
union을 넓히는 대안은 구 caller가 새 context를 잘못 읽을 수 있어 사용하지 않는다.

### 작업자에게 전달할 공통 원문·공개 풀이 자료

기존 materials1은 context1, materials2는 mixed context2에 고정돼 있다. 이를 변조하지 않고
local-workspace successor `system-rag-similarity-materials/3.0`을 추가한다. 실제 출처 정본은
기출/창작/AI의 원래 승인 Item과 accepted/registered 공개 풀이 entry1/2다. 새 자료는 이
정본의 일시적 bounded materialization이지 새 Item/profile/보고서 정본이나 권한 영수증이 아니다.

- 자료는 context3/4의 원래 request/context semantic SHA에 고정한다. anchor 1개와 원래
  순서의 후보 최대8개 각각에 exact public entry 및 question-only projection을 전달한다.
  source Item/revision/Artifact/member/raw SHA와 report/Graph/policy/recipe 핀을 비교한다.
  source가 달라도 같은 text hash라는 이유로 identity를 합치지 않는다.
- question-only 표현은 기존 renderer를 그대로 재사용한다. 정답·해설과 aggregate
  equation_sources를 원문 질문에 섞지 않는다. 렌더링 byte bound만 공통 recipe에서 받는다.
  schema/media/byte·text limit 때문에 읽지 못한 경우에만 명시적 unavailable를 전달하며,
  malformed JSON·dangling/hash/lifecycle/provenance 오류는 unavailable로 숨기지 않는다.
  public solution은 반드시 AVAILABLE이어야 하고 review 요약·private 사고 기록을 대입하지 않는다.
- Catalog의 기존 실제 operator-fenced `resolve_selected_sources`를 한 번 사용한다. 원래
  session의 `PinnedArtifactReadContext`를 선택적으로 재사용해 source capture와 질문 원문
  decoding이 불필요하게 같은 bytes를 다시 해석하지 않도록 한다. 기존 root/settings/권한
  검사와 재검증은 생략하지 않는다. indexing service를 사람으로 취급하지 않는다.
- 접근은 ≤9 revision의 set/map lookup, 한 번의 source batch와 Artifact prefetch, 원래
  candidate 순서의 tuple이다. 조회는 기존 index를 사용하며 projection 비용은 선택한 질문·
  공개 풀이 bytes에 선형이다. total workspace 자료는4MiB를 넘기지 않고 잘라 맞추지 않는다.
  새로운 table/index/cache/queue/의존성은 없다. IO는 Catalog adapter, 순수 표현은 기존
  projection module, 값/검증은 contracts, worker staging/commit은 기존 Orchestrator가 소유한다.
- 바깥 completed QUERY reader/Item plan은 원래 QUERY와 현재 권한을 별도로 검사해야 한다.
  이 자료만으로 vector 순위나 source 접근을 승인하지 않는다. 같은 pin을 재해석하고 실패를
  명시하며 latest나 다른 후보로 대체하지 않는다. context 발행의 같은 key/replay 규칙을 유지한다.
  실제 role/materialization 연결이 되기 전 이 값만 추가해 운영 전환 PASS로 표시하지 않는다.

더 작은 대안인 기존 inference profile1을 공통 공개 풀이로 위장하거나 포인터만 작업자에게
넘기는 것은 각각 양식/출처 의미 또는 staged-local-only 경계를 깨므로 사용하지 않는다.

### 실제 출제·검토 실행 계획의 공통 공개 풀이 successor

책임은 기존 `resolve_knowledge_backed_execution_plan`과 plan 저장 application이다. 새
plan30(기출변형)/31(일반출제)은 현재 generic1.16 topology·review 최대3회·Pack/instruction/
Evidence/Graph/policy/권한 핀을 그대로 보존하고 similarity delivery2/context3·4만 명시적으로
연결한다. 기존 plan19/23/24와 그 schema bytes는 재해석하거나 제자리 승격하지 않는다.
Content Pack/worker protocol은 이 보조 자료 전달만을 이유로 새로 만들지 않는다.

정본은 기존 immutable Evidence Bundle, 승인 기출 원문과 공개 풀이, 원래 완료 QUERY와
Orchestrator가 발행한 context Artifact다. 작은 plan은 이들의 typed revision/hash pointers와
필요한 실행 값만 보관한다. 모든 출처를 검색할 수 있다는 것이 변형 기준 원문을 임의로
창작/AI로 바꾸는 권한은 아니다. reference anchor는 기존처럼 PAST_EXAM이고, 후보는 공통
index에 승인된 기출/창작/AI가 가능하다. 원래 Graph/policy와 anchor content member의
identity/hash를 비교하며 다른 head/latest로 맞추지 않는다. 원래 request/context SHA와
READY/PARTIAL/EMPTY 의미도 보존한다. public context만으로 과학적 승인이나 Evidence
usage receipt를 대신하지 않는다.

자료구조는 bounded frozen plan/tuple, 저장·replay는 기존 workflow unique indexed lookup이다.
validation은 plan/selected context bytes에 선형이고 source full scan을 추가하지 않는다.
기존 root transaction/plan allocation/unique-workflow 경계와 동일 request replay를 사용한다.
이미 저장된 old/public plan은 다른 family/context를 새로 취득할 수 없고 conflict가 된다.
누락·hash/권한/producer 불일치는 실패하며 자동 legacy fallback이나 새 QUERY 재실행은 없다.
값·schema는 workflow/contracts, persistence/Artifact는 기존 Orchestrator, source와 completed
QUERY 재검증은 Catalog, staging은 기존 role materialization boundary가 소유한다.

새 table/index/queue/registry/의존성은 없다. 단순히 released plan23/24의 delivery field union을
넓히면 같은 schema version으로 공개 풀이와 구형 profile을 혼동하므로 그 대안은 사용하지
않는다. successor parsing/저장·staging·권한·재전송 회귀를 갖춘 뒤에만 실제 caller를 활성화하며,
schema/model 추가만으로 기존 운영 출제 경로가 전환됐다고 보고하지 않는다.

### 공통 출제·검토 role의 실제 Catalog 읽기와 workspace

기존 runner-only `READ_WORKFLOW_SIMILARITY_MATERIALS`에 closed request/reply2를 추가한다.
selection은 기존 workflow/step/plan/완료 QUERY 포인터를 그대로 재사용한다. operator나
filesystem path를 요청에 추가하지 않는다. Catalog는 저장된 human creator, RUNNING role,
원래 request/definition/Pack/plan hash 및 완료 QUERY의 동일성을 자기 root에서 검증한다.
plan30/31만 새 family를 받고 plan23/24는 기존 family로 계속 읽는다. cross-family replay는
오류이며 구형 profile로 fallback하지 않는다.

정본은 원래 완료 QUERY와 공개 풀이 context Artifact 및 승인 Item/report다. 실제 Catalog
reader가 기존 completed-public-query read와 selected owner를 재사용해 전후 현재 권한·
source/index/provenance를 검사하고, 같은 root의 pinned Artifact reader로 exact context
member와 materials3을 일시 materialize한다. runner는 고정 UDS peer로만 읽고 NAS를 직접
읽지 않는다. Orchestrator는 반환된 canonical bytes/raw hash/request/context/materials 핀을
다시 검사한 뒤 기존 두 workspace alias에 쓴다. 새 공개 풀이를 구형 inference profile로
설명하지 않으며 질문 unavailable과 pixel 미확인·Evidence receipt 비대체를 명시한다.

lookup은 기존 indexed workflow/step/plan/QUERY lookup이고 후보는 최대8개의 ordered tuple,
원문 선택은 기존 bounded set/map batch다. 비용은 선택 자료 bytes와 원래 ranking read에
비례하며 새 table/index/queue/cache/migration/worker protocol은 없다. transaction은 기존
Catalog current-read root, 파일 쓰기는 기존 Orchestrator staging boundary다. 실패/timeout은
같은 selection으로 재조회하며 모델 실행·다른 QUERY·latest source를 자동 생성하지 않는다.
이 작은 읽기 successor보다 단순한 union 확대/guard 삭제만으로는 released 의미와 권한
경계를 지키지 못한다. 실제 API caller·Chat 전환은 후속 작업이며 이 연결의 source PASS와
운영 activation을 구분한다.

구/공통 Catalog configuration은 `context_reads.owner`와 명시적인 `public_owner`로 분리한다.
같은 engine/settings root를 확인하고 publication2와 role read2에 public owner를 전달한다.
public 설정이 없을 때 legacy owner를 빌려 읽지 않는다. 이 연결을 운영 builder에서도
검사한다. 새 공개 풀이 전달은 원래 content-team 원문 두 파일을 바꾸는 이유가 아니다.
다만 현재 Pack1.20.17의 보조 지침 v1에는 실제 JSON 필드 `anchor_profile`이 명시되어 있다.
실제 API caller 활성화 전에 이 부분은 공개 풀이의 `anchor.entry.public_solution` 및 질문
표현에 맞는 immutable 지침/Pack successor로 명확히 해야 한다. 구 Pack/지침을 제자리
수정하거나 AGENTS 문구만으로 서로 모순되는 필드 요구를 덮어 운영 승인하지 않는다.

### 실제 Item-start의 공개 풀이 전환

Pack1.20.18은 1.20.17의 authoring/review 보조 지침만 v2로 바꾼 immutable successor다.
원래 컨텐츠팀장2개 원문, 이미지/HWPX/편집 규칙, 독립 검토와 최대3교·result schema는
보존한다. v2는 context3/4와 materials3의 실제 `anchor/entries[].entry.public_solution`,
question AVAILABLE/UNAVAILABLE, 보고서 종류/출처 차이와 텍스트 접근 한계를 설명한다.
profile ID는 identity carrier일 뿐 구형 profile fields를 새 문서에서 찾지 않는다.

API의 기존 reference-start use case에서 실제 resolved Pack18이면 기존 prepare-request4로
단일 원 기출 reference를 요청한다. source scope/Graph/policy는 기존 Evidence와 정확히
같아야 하며 실제 owner가 GPU/CPU 공간을 선택한다. 후보는 worker 자료 상한8개로 미리
제한하며 자르거나 다른 index로 재검색하지 않는다. Pack17의 기존 request/plan23·24는
그대로 replay한다. request4의 pending Artifact/parent와 원 key를 유지하고 새 child를
중복 생성하지 않는다. 선행 QUERY 없이 Item을 만들거나 old response를 public으로 relabel
하지 않는다. 실제 source/권한이 없으면 기존 명시적 오류 또는 허용된 ordinary NOT_OFFERED
의미를 사용하며 오류를 absence로 숨기지 않는다.

실제 publication2/read3·4로 얻은 결과는 frozen public preparation으로만 전달한다. 기존
단일 Item transaction에서 request/resolution/preset/Evidence/operator와 모든 작은 hash를
검증하고 plan30·31·acceptance2 metadata·START를 함께 저장한다. old acceptance1/fingerprint는
변경하지 않는다. rollback/재전송은 같은 identity로 하며 committed auxiliary Artifact와
기존 FAILED는 보존한다. HTTP/CLI는 business invariant를 새로 복제하지 않고 기존 runner
scope validator와 Orchestrator resolver를 재사용한다. 새 wire schema/DB/table/index/queue나
캐시는 필요 없다. 준비는 기존 bounded read, acceptance는 indexed key lookup과 원 root
transaction이므로 큰 payload의 DB 복제나 N+1을 추가하지 않는다.

### 일반 채팅의 private 질의를 공통 문항 인덱스로 연결

현재 NATIVE_TOPIC/READ_ONLY의 private QUERY1은 CONTENT_ONLY 구형 문항 인덱스 소비자다.
새 문항 벡터를 완성해도 이 active consumer가 같은 구 벡터를 사용하면 삭제할 수 없다.
다음 additive successor로 private 질문 provenance와 공통 문항 document scope를 분리한다.
이 절은 설계이며 구현·설치·활성화·실제 채팅 검증의 PASS를 뜻하지 않는다.

1. 책임/경계: 기존 Chat owned-turn → private QUERY application → Catalog current Graph/
   public index read → 기존 native encoder/Orchestrator commit 경로를 확장한다. 새로운
   검색 엔진·queue·worker 권한이나 arbitrary index/path 입력을 추가하지 않는다.
2. 정본: 질문은 원래 owned user-message Artifact와 basis1이다. 문항 document는 현재
   승인 source와 report의 공통 public-solution-text/1.0·recipe2 entry/index3·4다. 질문을
   accepted Item/풀이보고서로 위장하거나 corpus의 새 문항으로 등록하지 않는다.
3. identity/revision: 원 conversation/turn/message revision/raw UTF-8 text SHA와 basis SHA,
   Graph/policy/index revision·manifest SHA, 실제 model/query/document space를 핀한다.
   private context/execution/policy successor는 기존1의 의미/bytes와 분리한다. 수치 메시지는
   승인 문항 anchor가 없는 기존 PublicSolutionQueryInput/Result2를 그대로 재사용한다.
4. 해석: private 질문은 기존 exact-user-text 규칙으로 유지한다. trim/요약/추론/가짜 풀이
   단계로 재작성하지 않는다. 문항 쪽은 출처와 무관하게 같은 공통 입력·model/정규화·공간을
   사용한다. 질문의 공개 문항 근거 여부와 문항 간 풀이 유사도의 의미를 혼동하지 않는다.
5. 포인터: 실제 owner가 owned/live turn, source permission/lifecycle, pinned Artifact schema/
   media/hash, index membership·space/recipe, native original association을 전후 검증한다.
   질문/문서 철회와 old-family 응답은 명시적으로 거부하며 latest/old index로 우회하지 않는다.
6. 접근/구조: 하나의 질문 encoding key lookup, bounded source revision map/set, 기존
   exact ranking O(N·D + N log N), ordered top-k tuple, append-only checkpoint를 재사용한다.
   N은 기존 공통 corpus 상한16,384 안이며 중복 vector는 encoding hash map으로 재사용한다.
7. 공간/DB: DB에 새 binary/text 복제나 table/index를 추가하지 않는다. 기존 owner-config와
   typed references만 successor가 필요하다. 긴 질문/토큰 초과는 거부하며 자르지 않는다.
8. 동시성: 원 turn/claim·operator fence와 existing private Workflow transaction, 원래
   publication/checkpoint root 및 current-read fence가 소유한다. worker는 DB/NAS에 접근하지 않는다.
9. 의존성: 계약 → domain/use case → 기존 infrastructure adapter 방향이다. native numerical
   leaf는 model/space와 입력·결과 association만 검증하며 Chat 권한/Graph 선택을 맡지 않는다.
   private basis와 원문 hash는 owner-local projection/launch association에 묶고, numerical
   QUERY2에는 원 conversation/turn ID를 복제하지 않는다. 기존 shared encoder/packer와
   native schema bytes·backend/numerical pin은 변경하지 않는다. 이는 private purpose2의
   owner/정책/물리 실행 admission을 생략하거나 구 reference 정책을 빌려 쓰는 허가가 아니다.
10. 실패/retry: 같은 basis/request/command로 조회·replay한다. Chat 삭제/권한 철회/중단 후
    늦은 결과는 원 application에서 차단하고 실패 이력을 바꾸지 않는다. 새 public 인덱스가
    없거나 private2 미설치이면 명시적 unavailable이지 legacy vector 사용 허가는 아니다.
11. 단순 대안: private 질문을 임의의 승인 문항 anchor로 치환하거나 CONTENT_ONLY 이름만
    CONCRETE_FACETS로 바꾸면 provenance/수치 recipe가 거짓이 된다. 기존 private lifecycle와
    public document reader를 명시적으로 연결하는 successor가 필요한 최소 범위다. 배포는 현재
    GPU numerical pin을 보존하고 private consumer의 준비·원 요청/read/replay를 실제 확인한 뒤 한다.

구현 경계는 순서대로 닫는다. owner-local `PreparedPrivateChatPublicQuery`는 기존 basis1과
native QUERY2를 연결하는 작은 검증 값이며 권한/launch/runtime activation이 아니다. 이후
private context/execution/policy·Workflow successor에서 정확한 원 turn과 public index3·4,
native QUERY2 input/result hash를 함께 핀한다. 기존 원 turn unique key·immutability guard를
유지하는 additive DB CHECK가 필요하면 disposable PostgreSQL에서 검증한다. private2의
source owner는 새 public document read를 사용하되 질문을 승인 anchor로 만들지 않는다.
GPU 우선/CPU fallback은 기존 public routing의 실제 선택된 document/query space를 동일하게
적용한다. CPU의 작은 부분집합을 전체 GPU corpus의 대체라고 부르거나 공간을 섞지 않는다.
물리 native private-purpose successor가 exact QUERY2를 받아들이는 admission을 명시적으로
확인하기 전에는 기존 private1 unit에 새 입력을 보내지 않는다. old private1 parser는 계속
이 입력을 거부한다. Chat read/provenance/답변 전달까지 이어서 새 authorized turn1회와
삭제/철회/중단·원 요청 replay를 확인해야 active legacy private consumer 전환이 끝난다.

#### 공통 document proof의 단일 소유권과 private context2

2026-11-01 source 구현 경계다. 새로운 wire contract는
`system-rag-private-chat-similarity/2.0`이고 기존 context1/request1 bytes는 보존한다.
질문 basis1과 실행된 공통 QUERY2의 정확한 parent/input-set/result/member hash를 연결한다.
개인 질문은 문항 anchor가 아니므로 모든 문서 binding을 점수화하며 source-count에서
임의로1개를 빼지 않는다. 최대16,384개는 기존 공통 corpus 상한이다. unavailable는 결과가
없다는 뜻이 아니므로 `NO_RELATED_CANDIDATES`를 붙이거나 모집단0을 만들어내지 않는다.

DB 문항 검색과 개인 질문 검색의 document 검증은 기존 Catalog application의
`public_solution_document_scope`가 함께 소유한다. 같은 Graph/policy/recipe의 source·base
analysis·entry·profile·binding·row를 map/set으로 대조하고 정규화된 vector의 dimension/
finite/norm을 기존 codec으로 확인한다. 공개3은 기존 family/실제 anchor 검증을 그대로
더하고, 공개4와 private2는 등록 AI를 포함한 기존 공통 entry union을 사용한다. 원문과
긴 보고서를 복사한 별도 검색 store·registry·cache는 없다. 반환 map은 read-only view이며
현재 승인/권한 fence를 대신하지 않는다. shared encoding은 한 numerical row를 재사용한다.

질문 QUERY의 committed member/schema/media/raw SHA 및 binary/norm 검증도 기존
`read_verified_public_solution_query_vector`를 공유한다. numerical QUERY2 입력·결과 schema,
encoder, 수치 runtime/정규화/model space는 변경하지 않는다. source capture가 비었거나
등록 binding이0이면 임의 zero-vector/model 호출 없이 실제 빈 범위의 count/hash만 반환한다.
access pattern은 bounded revision/encoding hash lookup이며 비용은 O(total text bytes + N·D),
ranking은 기존 O(N·D + N log N)이다. 영속 DB/transaction/lease/queue 변경은 이 pure 단계에
없으며 native-purpose successor와 원 turn uniqueness/current-read fence는 후속 owner 작업이다.
이 source 계약·composer PASS를 private2 운영 활성화 또는 구 vector 삭제 허가로 해석하지 않는다.

#### 원 turn과 공통 QUERY2의 실제 실행 요청 연결

private `workflow-request/2.0`·`execution-policy/2.0`은 공통 context2/QUERY2와 실제
runtime bundle/resource/index-space를 정확히 묶는다. 원래 private request/policy1은 별도
family로 계속 해석한다. 단순한 reference-query 정책 재사용은 목적 권한을 바꾸므로 금지한다.
원 owned-message basis와 exact text가 먼저 일치해야 하며, 그 후 동일한 공통 QUERY2
projection/encoder를 사용한다. 동일 text라도 다른 turn의 basis로 이 실행을 빌릴 수 없다.

질문의 actor/turn·workflow request hash만 담는 기존 submission-context1의 의미는 변하지
않으므로 버전을 새로 늘리지 않는다. 지원된 request parser에서1/2를 분리하고 같은
`private-chat-query:<actor>:<turn>` 키를 쓴다. version2로 바뀌었다고 새 실행 key를 만들지
않는다. request/definition pin이 달라지면 fingerprint는 달라져 기존 key와의 충돌로 처리한다.
기존 unique partial B-tree와 origin immutable trigger를 유지하는 것이 transaction 경계다.
DB CHECK의 version/protocol 쌍 확장은 실제 compiler/receipt2와 함께 disposable DB에서
검증할 후속이며, 현재의 순수 metadata 지원만으로 DB가2를 허용하거나 운영 실행하지 않는다.

owner-configuration2는 기존 public routed cohost5의 전체 canonical raw SHA와 동일 corpus/
namespace/recipe/source-class/owner environment를 핀한다. private CPU/CUDA native policy2와
private-purpose routing policy1은 별도 Artifact로 읽어 raw/semantic SHA·device/bundle/resource/
document space·동일 Workflow definition·기존 finite timeout을 대조한다. GPU 우선/실행 전
capacity 부족 시 CPU fallback은 기존 router와 purpose를 그대로 사용하며, device를 바꾸면서
진행 중 실행·원 request를 바꾸거나 CPU 부분집합을 GPU 전체로 표시하지 않는다.
새 native parser/physical-purpose admission과 current source fence·원 요청/read/replay 검증
전에는 이 설정을 보호 운영 파일에 설치·활성화하지 않는다. 새 queue/테이블/임베딩 모델/
수치 payload/worker 권한은 추가하지 않는다. metadata lookup은 기존 indexed actor/turn,
policy 검증은 고정 크기의 두 device와 소수 pin에 대해 O(1)이다.

#### private2 완료 영수증과 저장 guard

새 고정 definition2는 기존 `encode_private_chat_query → complete` DAG를 유지하고,
result schema를 실제 numerical QUERY2인 `embedding-reference-query-result@2.0`으로 표시한다.
새 arbitrary worker 역할/SQL/실행 명령이나 자동 재생성 loop는 없다. compiler가2를 해석하는
것과 actual owner/admission이2를 실행하는 것은 별도다. native owner 준비 전에는 새 작업
admission을 추가하지 않는다.

해시·Job·원 command generation·원 basis만 담는 launch-association1은 의미가 같으므로
재사용한다. request2를 담는 execution-record2와 QUERY2 pointer를 담는 receipt/output2만
새로 정의한다. receipt owner/Artifact owner/native launch Job은 서로 다르고, data members는
하나의 Artifact revision에 속하며 receipt는 별도 revision이어야 한다. 원 actor/basis/Workflow/
step/native input/result/hash/bundle/resource를 닫고, current permission·producer/lifecycle 확인은
기존 owner가 소유한다. 원 질문·보고서·vector bytes를 DB에 복제하지 않는다.

additive migration `20261101_0067`은 context/step CHECK만 교체한다. private1의 허용 범위는
그대로 두고 private2는 definition/version/protocol/request/context2·실제 actor/definition hash를
상호 대조한다. 새 result2는 private application step/worker 없음/attempt1 조합만 허용한다.
원 turn unique partial B-tree와 snapshot/origin immutable triggers는 **교체하지 않는다**.
모든 버전의 같은 actor/turn은 같은 영속 키 공간에 있고 insert/lookup은 O(log N), metadata
검증은 기존64KiB 한도 안이다. 중단은 원 transaction rollback, 재조회는 원 key/hash를 쓴다.
다운그레이드는 successor instance/step history가 있으면 DDL 전에 거부하며 과거 row를
변환·삭제하지 않는다. schema가 원 요청을 자동 실행하거나 source 권한을 부여하지 않는다.

설계는 기존 queue/transaction/application 경계를 재사용하며 새 table/index/framework는 없다.
source head67의 disposable DB guard 검증은 운영 migration을 뜻하지 않는다. 운영 반영 전에는
기존 release operator의67 지원과 API/Catalog/QUERY/INDEX controller 호환·drain·rollback을
별도로 검증한다. 진행 중 numerical runtime/model/space pin은 이 DDL 때문에 바꾸지 않는다.
private2 history가 생긴 뒤의 기능 rollback은 DB를66으로 내리는 것이 아니다. head67과 원
private2 읽기/복구 호환성을 유지하는 release set에서 새 admission/consumer 활성화만 철회한다.
실제67 호환 검증 없이 과거66 wheel 재설치가 안전하다고 주장하지 않는다. 이미 시작한2는
원 pin으로 종료/조회하고1로 relabel하거나 구 vector fallback을 몰래 재활성화하지 않는다.

#### private2의 canonical 수치 파일과 완료 영수증 저장·조회

기존 Orchestrator `EmbeddingArtifactStore.publish_private_chat_query`가 private request/policy
1/2를 명시적으로 구분한다. private2는 공통 numerical QUERY2를 사용하지만 Artifact type은
여전히 private 전용이다. 공개 reference Artifact나 그 실행 권한으로 바꾸지 않는다.
입력·원 질문은 원 owned-message와 잠긴 임시 workspace에만 있고, commit하는 파일은 기존
`intent.json/result.json/shard.json/vectors.f32` 네 개다. 새 DB table/queue/vector store는 없다.

각 family의 record/result parser와 원 launch/input/result/observed-hash 검증을 통과한 뒤 같은
FD-pinned file-set publisher를 사용한다. 같은 원 idempotency key와 publication/native Job의
분리를 유지한다. file identity가 commit 중 바뀌거나 늦은 receipt 검사가 실패해도 이미 저장된
Artifact를 삭제하거나 성공으로 위장하지 않는다. 결과 관측이 불명확하면 재추론하지 않고
원 identity의 commit을 조회·replay한다.

Catalog의 기존 private Artifact reader에는 supported-family 경로만 추가한다. legacy entry는
계속1만 반환한다. 공통 수치2도 같은 current clean root, 정확한 네 member와 manifest SHA,
private type, approved producer/lifecycle, 각 raw SHA/schema/media, canonical JSON, shard·float32
shape/norm/hash, 원 origin/Workflow/step/Job/receipt를 검증한다. 마지막 bytes를 읽은 뒤에도
producer와 root를 재확인한다. 로컬 결과 모델은 family별 frozen value이며 질문·vector bytes는
repr에서 숨긴다. 같은 질문 text hash는 다른 actor/turn 접근 권한을 합치지 않는다.

별도 한 member `receipt.json`의 publisher/reader도 기존 owner와 key를 재사용하며
receipt/output1/2의 조합을 공통 Workflow validator 한 곳에서 구분한다. 네 member 수치
Artifact를 완료 receipt로 재사용하거나 private2를 legacy completion으로 반환하지 않는다.
동시 publisher/중단/replay는 marked disposable PostgreSQL에서만 검사한다. 주 접근은
Artifact revision key lookup과 고정5 member의 bounded bytes 해석이며 저장은 원 transaction,
시간·공간 비용은 O(input bytes + D)다. 새로운 추상 publisher/별도 저장소보다 기존 경계의
명시적 dispatch가 작고, 이미 승인된 private1의 의미와 이력을 보존한다.

이 저장·조회 구현만으로 private2의 실제 현재 권한/native-purpose admission·owner 실행·
채팅 답변 전달이 활성화되지는 않는다. 그 후속과 호환 release67 배포가 끝나기 전까지 실제
private1 소비자와 구 인덱스는 유지한다. source/임시 DB PASS는 구 벡터 삭제 gate가 아니다.
