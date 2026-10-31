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
