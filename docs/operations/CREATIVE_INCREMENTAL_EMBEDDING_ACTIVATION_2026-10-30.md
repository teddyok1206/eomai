# 창작 풀이보고서 자동 증분 임베딩 활성화

2026-10-30 UTC. 목표는 **보고서·Graph 검증 → 실제 벡터 등록 → 공식 검색 반영**이다.
기존 [공통 풀이 설계](../architecture/SOLUTION_EMBEDDING_FORMAT_COMPATIBILITY.md)와
[구현 체크포인트](PUBLIC_SOLUTION_EMBEDDING_CONNECTION_2026-10-29.md)를 이어간다.

## 착수 기준선

- source `39fb4de67e15d83bb20300294c760c367a8f1a39`, clean main/origin.
- 기출 원래 목표 520개를 활성 CPU/CUDA 인덱스 12개에서 각각 대조했다. 원래 목표의
  누락·추가·등록 encoding 참조 누락 모두 0. 1,563 encoding 행은 문항 수가 아니다.
- 08:24 UTC 창작 77/1,053 Graph/report 검증 완료, 다음 원문 10394 분석 중.
- 기존 창작 순차 등록, INDEX, QUERY 서비스는 active. active는 새 창작 벡터 등록 증거가 아니다.
- public recipe2/source-plan3/index3/native3 및 numerical QUERY2는 구현 후보다.
  public source의 GPU 일괄 selection·installed owner·공식 similarity 소비 연결은 미완료다.

## 변경 경계와 짧은 설계 결정

1. 책임: Catalog가 실제 source/보고서/Graph 접근을 검증한다. 기존 Orchestrator INDEX/QUERY
   owner가 수치 실행과 등록을 맡는다. 원문 등록 transaction의 필수 후속 단계로 묶지 않는다.
2. 정본: accepted V10 또는 등록 창작 보고서와 원문/Graph 계보다. 공통 텍스트와 벡터는
   파생물이며 보고서·원문·과거 Graph를 수정하지 않는다.
3. identity: Item/revision, base analysis, report/lineage Artifact revision/hash, Graph/policy,
   recipe/space/partition을 각각 핀한다. 같은 text hash는 권한 또는 source identity가 아니다.
4. pointer: 기존 source capture·pinned artifact resolver·registry의 존재/권한/schema/media/
   hash/lifecycle 검사를 재사용한다. public source를 legacy accepted/review anchor로 위장하지 않는다.
5. 접근: bounded Graph source 순회, indexed report lookup, encoding key dedup, ordered batch,
   원래 queue의 atomic claim, index head CAS. 별도 스캐너·queue·검색 저장소를 만들지 않는다.
6. 구조: public source는 기존 typed entry/evidence를 쓰고, batch에는 text 없는 source/profile/
   evidence pointer만 둔다. 기존 native numeric input/result/shard와 물리 자원 lease를 재사용한다.
7. 비용: public metadata head 16,384, 페이지·수치 batch 1,024, 선택 메타데이터 4 MiB,
   report 캡처 64 MiB 한도 유지. 단일 batch pointer 검사는 O(n), map/set 공간 O(n)이다.
8. 동시성: 원문 등록과 분리된 기존 증분 owner가 누락을 발견한다. 완료 encoding은 재사용하고
   같은 binding은 CAS/unique 제약으로 등록한다. 실행 중 native/runtime pin을 교체하지 않는다.
9. 의존성: schemas/contracts → 순수 값 → Catalog admission → Orchestrator adapter.
   CLI/UI에 근거 검증이나 SQL/NAS 검색을 새로 구현하지 않는다.
10. 실패: canonical mismatch는 명시적 오류, missing report는 대기다. historical FAILED 보존.
    같은 요청의 replay·중단 복구는 기존 identity를 유지하고 완료된 수치를 재계산하지 않는다.
11. 단순 대안: 기존 anchor에 창작 데이터를 끼우면 계보·recipe를 오인하고, 별도 임베딩
    스크립트는 자원·등록·검색 경계를 우회한다. 필요한 successor만 기존 owner에 연결한다.

## 실행 순서와 완료 기준

1. public INDEX batch selection/입력 검증을 기존 GPU 자원·실행 경로에 연결한다.
   기존 1.0/1.1/1.2 계약 bytes와 의미는 보존한다. 수치 wire와 queue는 바꾸지 않는다.
2. 명시적인 public owner 설정과 동일 recipe QUERY/공식 similarity 소비 경로를 연결한다.
3. focused/static/schema와 disposable PostgreSQL의 concurrency/replay/중단 회귀를 확인한다.
4. 기존 수치 작업을 안전하게 마친 뒤 compatible wheel/policy/owner를 설치한다.
5. 고정 창작 5건의 실제 수치 계산·등록 binding·공식 검색 결과와 정확한 source identity를
   확인한다. 같은 요청 재전송은 새 수치 실행이 없어야 한다.
6. 기존 backlog와 이후 Graph publication을 기존 owner가 자동 발견하는지 확인하고 활성화한다.
   기존 기출 인덱스/정본/실패 이력과 창작 순차 등록의 보존도 재확인한다.

현재 상태: `IN_PROGRESS`, 운영 public 검색 활성화 `PENDING`.
소스 테스트·PID·캐시 membership 갱신만으로 목표 완료를 선언하지 않는다.

## 첫 구현 체크포인트 — public GPU 실행 준비

- `embedding-batch-plan/1.3`: 기존 INDEX batch owner가 public entry의 source/base analysis/
  profile/evidence **포인터**를 검증한다. 수치 본문·보고서를 selection에 복사하지 않는다.
  기존 allocation/route/bound 이벤트와 numerical input/result/shard는 그대로다.
- `local-indexing-owner-configuration/6.0`: 기존 GPU-first/CPU counterpart composition을
  재사용한다. public namespace 한 개와 명시적으로 핀한 legacy config5를 같은 서비스에서
  순회할 수 있어 기존 6개 view의 갱신을 끊지 않는다. 각각의 recipe/routing/source grant는
  따로 검증하고 물리 runtime·실제 DB owner·controller는 일치해야 한다. 구 config1–5의
  schema bytes와 decoder는 public successor 입력을 계속 거부한다.
- parent 생성은 public source에만 1.3을 선택한다. 기존 기출·review 경로는 1.1을 유지한다.
  같은 request의 parent/selection identity는 보존하고 새 allocation 후보를 새 dispatch로
  취급하지 않는다. CPU matching에도 같은 source·풀이 입력을 유지하되 space는 분리한다.
- 기존 device-index pair 검증에 public manifest3를 명시적으로 추가했다. 같은 원문 번호만
  보고 CPU/CUDA를 짝짓지 않으며 source/보고서/lineage/Graph/policy/input hash가 다르면 거부한다.
- 공개 풀이가 없는 plan3는 기존 coverage-only 경계로 처리한다. 0 벡터를 만들지 않는다.
  legacy similarity context1/2는 public profile을 자체 후보로 재해석하지 않는다.

확인 결과:

- focused unit **313 PASS**: 새 계약/owner/parent/device pair, 기존 batch/submit/similarity 회귀.
- dependency·similarity/native read boundary **119 PASS**.
- guarded disposable PostgreSQL의 parent·plan store·routed/fallback/recovery **83 PASS**.
  이 중 public/legacy parent concurrent creation·allocation 후 중단·release 변경 replay 6개는
  같은 저장 identity와 물리 실행 중복 방지를 확인했다.
- 별도 전체 model-free embedding persistence **151 PASS**. 기존 Artifact/registry/권한 경계와
  public native 등록·수치 완료 후 중단·등록 후 중단 복구를 다시 확인했다. 이 검사는
  임시 DB에서 477초가 걸렸으며 실제 모델 추론 시간이나 운영 처리량이 아니다.
- 변경 core 11개 mypy PASS, 변경 Python 20개 Ruff/format PASS, diff whitespace PASS.
- source `58a83bb394b318f9aeb212bff211d2cddfb43db2` commit/push 및 build-only PASS.
  wheel RECORD와 비편집 설치본 simulation을 통과했다. wheel은 빌드 후보이며 운영 설치 아님.

DB 검사는 실제 임시 PostgreSQL과 실제 control Artifact IO를 사용하나 IAM/source/runtime
일부는 명시적인 합성 seam이다. **모델·실제 GPU·운영 검색 성공 증거는 아니다.**
운영 API/INDEX/QUERY/창작 owner와 production migration은 이 체크포인트에서 바꾸지 않았다.
다음은 public query/result2의 공식 검색 소비 연결, installed wheel 검증과 호환 활성화,
창작 5건의 실제 벡터·검색 canary다. 목표는 아직 완료되지 않았다.

## 공식 공통 풀이 검색의 세부 연결 결정

기존 context1/2의 accepted-analysis 또는 AI-review 필드에 창작 보고서를 끼우지 않는다.
public context3는 같은 source/profile/evidence 참조를 anchor와 후보에 쓰고, 실제
query/result2와 index3를 핀한다. producer는 기존 QUERY owner/고정 native 실행 경계,
consumer는 기존 Catalog source·Artifact·registry read 경계다. 별도 모델·queue·벡터 DB는 없다.

- 책임/정본/identity/권한은 위 1–4번과 같다. pointer 값 검증은 실제 read 권한의 증명이 아니다.
- 순회·검색은 최대 16,384개 metadata head, 1,024개 source page, 실제 batch 한도를 분리한다.
  query와 candidate는 동일 recipe2, 서로 짝지어 검증한 QUERY/DOCUMENT space를 사용한다.
  텍스트를 같게 정규화해도 source·revision·보고서·Graph·policy는 각각 재검증한다.
- source 순회와 vector 검증은 O(n·d), top-k는 기존 bounded exact cosine/tie rule을 재사용한다.
  반환은 최대 64개 pointer/관측이고 전체 보고서나 binary를 DB/메시지에 복사하지 않는다.
- 준비 시 actual operator와 index revision을 고정하고, 같은 요청의 재전송은 원래 pin을
  재인가한다. 현재 head가 바뀌어도 latest로 바꾸지 않는다. 등록과 별도 transaction이다.
- source/보고서/입력·실행·index proof가 틀리면 명시적 오류다. 없거나 아직 미계산인 근거를
  0 벡터·다른 보고서·옛 recipe로 채우지 않는다. 부분 coverage와 과학적 정당성은 구별한다.
- 기존 source capture·native QUERY·수치 codec·Catalog Registry의 adapter 소유권을 유지한다.
  contract/domain은 DB/NAS/HTTP를 읽지 않는다. released context1/2 의미와 history는 보존한다.
- 더 단순한 DOCUMENT 벡터 재명명이나 임시 cosine 스크립트는 실제 QUERY 실행·권한·출처를
  증명하지 못한다. 기존 owner의 명시적 successor로 연결한다.

### QUERY2의 기존 finite native batch 연결

public QUERY2는 기존 numerical kernel과 QUERY/DOCUMENT space 쌍을 사용한다. 새 batch2는
public QUERY2만 담는 명시적 successor이고 기존 batch1의 허용 입력을 넓히지 않는다.
기존 scope/시간/행/출력 상한, 단일 모델 수명, child 전후 source fence와 연속 binary 배치를
공유한다. 새 queue·lease·프로세스·자동 권한은 만들지 않는다. 개별 결과는 각 request/job,
context/input hash와 recipe/space를 유지하고 배포 전 old/new dispatch·권한 거부를 검증한다.
메타데이터 입력 검사는 O(n), 수치 검사는 O(n·d)이며 n≤32, 전체 행≤1,024다.
실제 소스·물리 lease·Artifact commit 권한은 기존 owner가 별도로 증명해야 한다.

QUERY workflow는 동일 key의 definition2.0.0과 request3/context3, receipt2/step2를 사용한다.
기존 execution policy1/launch1은 definition·request·context·native input·recipe·runtime hash를
이미 핀하므로 wire를 재출시하지 않고 동일 closure 검사를 공유한다. numerical input/result의
family가 다르면 요청·영수증 모두 명시적으로 거부한다. definition1과 receipt1의 허용 입력은
변경하지 않는다. Workflow/Job/CAS/원래 command·launch identity와 기존 producer 권한 검사를
재사용하며 public frame 자체를 실행 권한으로 취급하지 않는다.

15:14 UTC 병행 등록 조회: 창작 95/1,053 완료 뒤 원문 10413에서
`KNOWLEDGE_GRAPH_NODE_CONFLICT`로 순차 owner가 중단됐다. INDEX/QUERY 서비스는 active였다.
아직 운영 public 임베딩 배포나 복구 retry를 수행하지 않았으며 accepted report와 실패 이력은
보존했다. 새 조회/검색 소스 검증과 별개로 정확한 accepted analysis의 충돌을 읽기 전용으로
분류한 뒤 기존 지원 복구 경계를 사용한다.

## 두 번째 소스 체크포인트 — 정본 검색 read와 QUERY2 저장 경계

- 공통 source/report 참조를 INDEX selection과 context3가 함께 사용한다. public namespace의
  누락 binding 발견이 legacy parser로 거부되던 경계를 기존 Registry에서 수정했다.
- 실제 Catalog Registry의 index3·원래 revision·member/hash·producer/lifecycle read를
  context3 준비/비교에 연결했다. 재전송은 current head가 아니라 원래 pin을 재인가한다.
  순수 비교는 기존 exact cosine/tie 규칙을 공유하며 최대 64개 pointer/관측만 반환한다.
- public QUERY2의 finite batch2와 definition2/request3/receipt2/step2를 추가했다.
  policy1/launch1의 원래 값은 보존한다. legacy owner의 request parser와 root GPU grant는
  아직 새 형식을 허용하지 않는다. 순수 provenance dispatch와 실제 실행 admission은 다르다.
- 수치 계산은 기존 encoder/backend/float32 codec, 파일 출력은 기존 보호 FD writer,
  저장·조회는 기존 Orchestrator `EmbeddingArtifactStore`와 Catalog pinned Artifact reader를
  재사용한다. 새 public 진입점은 QUERY2만 허용하고 legacy 진입점은 계속 거부한다.
- 복사·생성된 모델의 미선언 필드가 직렬화 중 사라지지 않도록 raw 값을 먼저 검증했다.
  source·nested report·query/result/member·profile/binding의 부정 검사를 추가했다.

동시 publication 테스트에서 기존 local manifest의 `O_EXCL create → write/fsync` 사이에
다른 재전송이 부분 파일을 읽는 경합을 재현했다. 같은 소유 workspace directory FD의
파일 작성 구간에만 advisory lock을 사용한다. DB/publication 전에 해제하고, crash 뒤 남은
부분 파일이나 충돌 파일은 덮지 않는다. 새 persistent lock/queue/테이블은 만들지 않았다.

검증 결과(서로 겹치는 suite이므로 합산하지 않는다):

- QUERY2/공통 검색/기존 native·제어 계약 unit **383 PASS**.
- 최종 raw-field·local manifest 경합·정본 저장/조회 관련 unit **172 PASS**.
- dependency/runner/similarity read 경계 **119 PASS**.
- disposable PostgreSQL의 기존 QUERY·Registry·재전송/복구 **90 PASS**.
- 추가 QUERY2 publication concurrent replay·commit 후 재조회·다른 completion 거부
  **3 PASS**. 실제 임시 DB/Artifact IO이며 모델/GPU/source IAM은 합성 seam이다.
- 관련 core와 기존 caller 26개 mypy PASS. source 테스트를 운영 inference로 해석하지 않는다.

남은 필수 작업:

1. 기존 Runner의 실제 QUERY claim/checkpoint/completion과 public source 준비를 연결한다.
2. 기존 GPU grant/routed owner 및 공식 similarity RPC/사용자 조회에 context3를 연결한다.
3. installed wheel 검증, migration0063/policy/호환 owner 활성화를 안전한 시점에 수행한다.
4. 이미 Graph 검증된 창작 5개로 실제 벡터·정본 등록·공식 검색·replay/복구를 확인한다.
5. 완료 backlog와 신규 publication 자동 발견을 활성화하고 기출/실패 이력 보존을 확인한다.

**운영 public 검색·5건 실제 임베딩 acceptance·backlog 자동 활성화는 여전히 PENDING이다.**
이 체크포인트에서 운영 migration·GPU 실행환경·기출 인덱스는 변경하지 않았다.
10413 충돌은 기존 `PROCESS` 키에 새 `CONCEPT`가 제안된 경우로 읽기 전용 분류를 마쳤다.
원래 accepted report와 실패 상태를 재해석하거나 임의로 유형을 바꾸지 않았다.

## 추가 사용자 요구 — DB에서 검색하고 다시 열람하기

[DB 작업 화면 설계](../architecture/ITEM_DATABASE_SIMILARITY_WORKSPACE.md)에 사용자 요구를
보존했다. `조회 / 배치 / 유사도` 탭, 조회의 선택 문항으로 검색, 결과에서 기존 상세·미리보기·
배치로 돌아가는 동선, 계산 표시/요청 경과시간을 같은 목표의 공식 소비 화면으로 연결한다.
탭 자체는 계산을 재제출하지 않으며 이미 접수된 PENDING만 같은 key로 관찰한다.

화면 controller와 실제 QUERY/API 연결은 구별한다. 합성 adapter 브라우저 테스트로 탭 왕복,
핀 보존, stale/오류/중복 클릭, 동시 검색 응답 순서, 계산 표시를 확인하더라도 운영 검색
성공이 아니다. 실제 application adapter가 없는 배포에서는 검색 버튼을 활성화하지 않는다.
현재 UI 소스는 실제 검색 adapter 연결 전이며 별도 운영 배포하지 않았다.
관련 Web 회귀 43개 PASS(실제 Chromium의 DB/안내 모드 검사 포함), Node 선택 포인터·문법,
Python Ruff/format 및 release integrity mypy PASS다. 브라우저는 합성 API/search adapter를
주입하고 운영 write·모델·GPU 실행은 하지 않았다. 계산 indicator는 접수된 PENDING 동안
계속 보이고, 다른 탭에서도 작은 표시가 남는다. terminal/오류/권한 변경 시 정리하며
관찰 timeout을 계산 실패로 단정하지 않고 같은 key를 유지한다.

## 실제 QUERY2 continuation 연결 결정

public QUERY는 기존 native QUERY Job·append-only event store·command lease·producer 배정을
그대로 사용한다. 새 checkpoint2는 같은 4단계(ALLOCATION/EXECUTED/PUBLISHED/COMPLETED)에
QUERY2 member/receipt2를 핀한다. EXECUTED는 실제 고정 CPU unit1.1 관측 또는 기존 CUDA
batch receipt 중 하나이며, request의 device와 반드시 일치한다. CPU를 GPU 관측으로
바꾸거나 old checkpoint1 이력을 새 형식으로 해석하지 않는다.

기존 Job은 `reference-query/1.0`, 새 public Job은 explicit `reference-query/2.0` protocol
row/hash를 사용한다. 저장소·task·인덱스·이벤트 순서·트랜잭션·멱등 key 규칙은 같다.
원래 request/launch hash와 revision을 핀하고, 동일 요청의 원래 Job과 allocation을
재사용한다. protocol row 생성은 기존 공식 `ensure_protocol_version` 경계에서 한다.
새 queue/schema/table은 필요 없다. 4단계 조회/검증은 O(1), 기존 indexed key lookup을
사용한다. 올바르지 않은 device/family/hash/producer 또는 terminal 실패는 명시적으로
거부한다. history를 삭제·재라벨링하거나 실패를 성공으로 바꾸지 않는다.

### 세 번째 소스 체크포인트 — 원래 Job 복구와 검색 입력

- checkpoint2는 기존 `NativeQueryCheckpointStore`와 원래 Job/event/protocol owner를
  사용한다. CPU/CUDA의 관측 형식과 request device를 각각 대조한다. 기존 1/1.1/1.2의
  parser, immutable schema bytes, Job identity와 실패 보존 규칙은 변경하지 않는다.
- receipt2는 기존 completion publisher와 Catalog pinned Artifact reader로 저장·해결한다.
  원래 launch/query Artifact/receipt producer를 분리하고 실제 member bytes와 lifecycle을
  확인한다. 기존 receipt1 진입점은 새 family를 받지 않는다.
- Catalog의 pinned query 준비는 최초 선택한 Graph/policy/report/index를 재인가한다.
  원래 index를 latest로 교체하지 않는다. 계산 전 입력과 계산 후 비교가 같은 공통 풀이
  renderer를 사용하고, QUERY space와 DOCUMENT space의 encoding identity는 분리한다.
- Runner의 public source 입력 materialization은 actual Identity/Catalog/control owner를
  사용한다. 이는 실제 Workflow claim 또는 CPU/GPU 실행 허가의 대체물이 아니다.
  기존 실제 execution/admission/GPU/RPC 연결은 아직 남아 있어 운영 활성화하지 않았다.

검증(겹치는 suite 합산 금지):

- QUERY2/기존 continuation·private Query·completion·Catalog source 비교 **199 PASS**.
- 기존 source/launch/admission/completed read와 새 public 입력 **142 PASS**.
- dependency/runner/공식 similarity read 경계 **122 PASS**.
- guarded disposable PostgreSQL의 public original Job 동시 생성, CPU/CUDA 각 prefix 재개,
  동시 event replay, known failure 보존, receipt commit 전후 응답 유실 및 canonical read와
  앞선 publication 검사 **11 PASS**. source/모델/unit/GPU 증거는 명시적인 합성 seam이다.
- 기존 실제 QUERY persistence **22 PASS**. 운영 DB/모델/GPU 실행은 하지 않았다.
- 관련 core/기존 caller mypy와 변경 Python Ruff/format, diff whitespace PASS.

개발 중 public source를 legacy builder에 넘기는 부정 테스트에서 안정적인 family 오류
대신 `AttributeError`가 발생했다. 두 materialization 진입점의 exact source family 검사를
추가한 뒤 해당 검사와 전체 source/admission/read suite를 재실행해 위 PASS를 확인했다.

### 완성된 DB 화면만 선행 운영 반영 — 2026-10-30 16:47 UTC

사용자가 완성된 부분의 선행 배포를 요청했다. 이미 검증·커밋·빌드한 Web
`82388ed1343bac631f5a731384881733e4ff7bc5`만 설치했다. 미완성 backend를 섞지 않았다.

- 이전 Web `204ee18c7a4cf61c179a1b2953c2deca44d04b1e`의 rollback wheel/hash를 확보했다.
  두 버전의 실제 BFF Python 21개는 동일했고, 변경은 화면·static inventory뿐이었다.
- 새 wheel SHA-256: `08beb3173b44aeebb6f48ac94928e252390a896d8e9b3940fb3d8f64630d38eb`.
  service identity로 비편집 설치본 RECORD/static 51개 검증 PASS.
- 직전 관련 Web/API alignment·release·실제 Chromium 검사 **22 PASS**.
  브라우저 기능 검사는 합성 API adapter이며 운영 인증 사용자의 검색 성공이 아니다.
- Web만 stop/install/start했다. 실제 HTTPS live/ready PASS, 제공된 새 module hash가
  source/installed wheel과 일치한다. 세션 없는 실제 DB 요청은 인증 경계에서 거부된다.
- API/INDEX/QUERY의 PID와 InvocationID는 배포 전후 동일하다. DB migration·GPU 실행환경·
  worker/창작 순차 owner·기출 index는 변경하지 않았다. Web in-memory session은 재시작으로
  사라질 수 있음을 사용자에게 사전 고지했다.
- 운영 `조회 / 배치 / 유사도` 탭은 반영됐다. 검색 adapter가 아직 없어 버튼은 비활성이다.
  계산 indicator와 결과→기존 조회 연결은 실제 검색 adapter 활성화 때 동작한다.
  이 선행 UI 배포를 운영 public 검색 또는 목표 완료로 해석하지 않는다.

설치 기록: `/tmp/eom-db-ui-release-20261030T1650.log` (파일 이름의 1650은 실행 시각 증거가
아니며 실제 HTTPS 응답/서비스 관측은 16:47 UTC). 기존 복구 wheel은 보존했다.

## 실제 Runner 연결 — supported family 승격

순수 provenance만 다루던 request3를 실제 기존 Runner에 연결할 때 `supported` dispatch가
request3를 명시적으로 포함하도록 승격한다. 개별 request1/1.1/2 parser와 schema bytes는
그대로 닫혀 있고, definition1에는 result1/receipt1, definition2에는 result2/receipt2만
허용한다. 지원되는 Python union은 실행 권한이 아니다. 실제 configured namespace·controls·
definition/hash·operator·원래 command/claim 및 보호된 native bundle 검사는 계속 필수다.
모든 source 준비/실행/completion/read에 같은 family를 끝까지 전달하며, 구 설정이 public
입력을 받을 경우 namespace/control 또는 definition 경계에서 거부한다. 기존 owner를 두고
public 전용 Runner/queue/service를 복제하는 대안은 사용하지 않는다.

## 사용자 후속 버그 — 현재 목표 완료 뒤 처리

2026-10-30 사용자 보고: 슬롯 하나가 사용 중이면 그 슬롯과 다른 슬롯 모두에서 사용량
새로고침 요청은 나가는 것으로 보이나 화면이 갱신되지 않는다. 아직 원인·재현은
확인하지 않았다. 현재 증분 임베딩·공식 검색 연결을 먼저 마친 뒤 별도로 진단·수정한다.
실제 응답/진행 중 slot 상태와 UI polling·stale-response·권한 처리의 관계를 확인하고,
원인 없이 lock/lease/실행 정책을 해제하거나 진행 중 작업을 재시작하지 않는다.

## 현재 목표의 최종 완료 조건 — 사용자 확정, 2026-10-30

이 절은 위 작업 순서와 후속 버그의 처리 시점을 대체한다. 기존 활성 목표를 유지하되,
다음 세 단계를 모두 충족해야 완료 처리한다. 목표 카드 도구는 활성 목표의 문구 변경을
지원하지 않으므로, 기존 목표를 거짓 완료하거나 별도 목표를 중복 생성하지 않는다.

1. 창작 Graph 등록 중단 원인을 수정하고, 기존 accepted 풀이보고서를 재사용해 등록을
   이어간다. 공식 Orchestrator의 기존 queue/claim/lease/용량 정책 안에서 **3개 슬롯이
   실제로 풀이보고서를 계속 작성**하는 것을 관찰한다. 서비스 active나 슬롯 사용 가능
   표시만으로 통과하지 않는다. 서로 다른 문항의 실제 claim/실행과 후속 문항으로의 진행,
   중복 accepted successor 없음, Graph 등록 진척을 확인한다. Graph publication은 기존
   직렬화/CAS 경계를 유지하고 worker끼리 직접 통신하지 않는다.
2. 사용 중인 슬롯이 있을 때 사용량 새로고침 결과가 화면에 반영되지 않는 사용자 보고를
   재현·진단하고 수정한다. 진행 중 worker를 끊거나 사용량 소진·lease를 우회하지 않는다.
   수정된 원인과 재발 방지 테스트 및 실제 운영 상태를 확인한다.
3. 기존 목표의 공통 풀이 표현·정확한 revision/hash·공식 증분 임베딩/검색 경계를 지키며,
   창작 5건의 실제 임베딩→정본 등록→공식 유사도 검색과 중단/재전송을 검증한다.
   DB `조회 → 유사도 → 조회/배치` 실제 adapter를 연결하고, 호환 release set으로 운영
   배포·활성화한다. 완료 backlog와 향후 등록의 자동 증분 처리, 기출 인덱스 및 실패
   이력 보존도 확인한다. 비활성 검색 버튼·합성 브라우저 테스트만으로 완료하지 않는다.

사용자에게는 위 순서의 실제 증거와 남은 조건을 간단히 보고한다. 아직 이 절의 어느
단계도 완료했다고 주장하지 않는다. 기존 기출 520개·교과서·창작 정본은 보존한다.

3개 실제 슬롯 실행은 현재 slot05 전용 cohort 설정과 구분한다.
[제한적 3슬롯 continuation 설계](../architecture/CREATIVE_COHORT_THREE_SLOT_CONTINUATION.md)는
기존 물리 역할·용량 상한을 몰래 완화하지 않고 필요한 successor 경계와 실제 검증을 정한다.
이는 아직 구현·운영 활성화 증거가 아니다.

### 창작 등록 중단 복구 배포 — 2026-10-30 17:38 UTC

- Graph 충돌 successor `2b374f5b`와 완료 기록 재확인 polling 수정 `54b39f7f`를
  각각 검토·커밋·push했다. 관련 Graph/교육과정/Item publication 154 PASS,
  control-loop/cohort 21 PASS, guarded disposable Graph/analysis 저장 검사 6 PASS다.
  이 수치는 서로 겹치는 검사이며 합산한 전체 테스트 수가 아니다.
- 실제 창작 owner는 격리 prefix
  `/opt/eom/maintenance-releases/54b39f7f98b92e5cc75f4670363cb0766ebe4c26`를 사용한다.
  원래 cohort revision `rev_36fc4e4e415f4e609e2033f7a4ab48dc`, target 1053,
  original operator·source·preset·보고서는 그대로다. 별도 새 cohort를 제출하지 않았다.
- wheel RECORD 검증 및 비편집 설치본 member 2,435개 바이트 대조·실제 import PASS.
  API/Web/INDEX/QUERY PID·Invocation은 전후 동일, DB migration·GPU bundle 변경 없음.
- 최초 설치 시 eom 소유 wheel을 root identity로 검증하려다 정상 거부됐다. 서비스/DB
  변경 전에 중단됐으며 기록을 보존했다. root 전용 stage에 동일 hash의 wheel을
  materialize한 뒤 그 소유자로 원래 verifier를 실행해 통과했다. 검증 규칙을 완화하지 않았다.
- 재개 뒤 처음 95건은 기존 Graph/report 포인터 재확인이다. 표시가 0부터 증가하는 것은
  기존 데이터를 삭제하거나 모델을 다시 실행하는 것이 아니다. 17:43 UTC의 95건까지
  재확인을 관찰했다. **10413 새 Graph 등록·후속 worker·3슬롯 지속 실행은 이 시점에
  아직 확인하지 않았으며 다음 검증 항목이다.**
- Slack milestone 전송·보관 PASS: `devreport_25e5b878c4bb4774b34dff487f1b3e71`.
  완료 조건 변경과 현재 source/운영 상태를 구분했고 목표 완료로 보고하지 않았다.

### 실제 Graph 복구 확인과 3슬롯 source 준비

- 중단 문항 10413은 원래 accepted analysis와 Item Revision을 그대로 재사용해
  `graphrev_093e67fbaa8f03b9ce1fb17df1eee7bc`에 등록됐다. 공식 보고서 조회까지 통과해
  96/1053이 됐다. 18:17 UTC 관측은 98/1053, 다음 10416 추출 중이다. 새 문항들이
  순차적으로 진행되는 증거이며 **3개 슬롯 병렬 실행의 증거는 아니다**.
- 고정 전후 Graph의 accepted source 1110→1111, 기존 source/revision/hash 변경 0,
  원래 accepted candidate 재사용을 read-only 확인했다. 교과서·기출 node 17,000개와
  edge 40,652개 모두 누락/재발급 0이다. metadata evidence:
  `/tmp/eom-creative-preservation-20261030T1800.json` (이름으로 시각을 추정하지 않는다).
- 별도 capacity key의 schema 1.4는 4/5/6번을 이용한다. slot04의 물리 default-role은
  그대로 두고, 명시된 `creative-reports/support` 목적에만 위임한다. 기존 fixed-host
  current pointer·계정·auth·전역 Codex 상한 3·슬롯별 상한 1을 바꾸지 않는다.
- 새 0064는 1.4 목적에만 analysis 상한 3을 허용한다. 전용 새 disposable DB
  `/tmp/eom-api-testdb-20261030175640_02dc147e`에서 upgrade/downgrade/re-upgrade PASS.
  실제 3개의 동시 claim, 같은 Job 재전송, 원래 역할 tamper 거부, legacy 정책과 공유하는
  전역 상한, 3슬롯 이력 보존 downgrade guard를 검증했다. 운영 DB에 적용하지 않았다.
- 보호된 release context/admission 1.13과 exact 0064 callback을 추가한다. 기존 1.12와
  0063 callback 의미는 보존한다. 현재 운영 0062에서 0063+0064를 동일 승인 source로
  올릴 때만 쓰는 별도 `MIGRATION_UPGRADE_0064_FROM_0062`도 정확한 predecessor를 검사한다.
  generic/latest migration, 직접 production SQL, 예전 callback 재해석을 사용하지 않는다.
- slot04의 별도 고정 analysis unit은 원래 identity·sandbox·명령을 유지하고 승인된
  7200초 timeout만 구분한다. lease 복구는 두 profile을 모두 관측해 실행 중/이력 모호성을
  없던 작업으로 오인하지 않는다. 소스·테스트 단계이며 아직 운영 설치하지 않았다.

다음은 새 scope/preset admission과 bounded cohort driver, 호환 배포·실제 3슬롯 반복 실행이다.
운영 창작 owner는 계속 54b39f7f이며 API/Web/INDEX/QUERY와 GPU runtime pin은 유지한다.
전체 목표와 공식 유사도 검색 활성화는 여전히 미완료다.

#### 넓은 metadata 감사에서 발견한 기존 차이 — 현재 변경과 분리

완전한 ORM composition 감사는 관련 model import 순서에 의존하던 문제를 노출했다.
필요한 owner를 명시적으로 불러온 뒤에도 14개의 차이가 남았다. 같은 disposable DB에서
변경 전 실제 설치본 54b39f7f와 현재 source를 각각 별도 interpreter로 대조했고, **14개
차이의 table/column/constraint/index 목록이 동일**했으며 worker_capacity 차이는 없었다.
새 변경이 추가한 schema drift가 아니다. 전체 감사는 PASS로 바꾸지 않았다.

차이는 curated assembly current-revision FK의 ondelete, 품질 검토/legacy/PDF 완료
operator 열 길이, whole-exam HWPX job 열 길이·index 정의, private-chat turn expression
index다. 원래 full-audit assertion을 완화하거나 목적과 무관한 모델·index를 변경해
검사를 통과시키지 않는다. 별도 유지보수 대조 대상으로 보존하고, 이번 capacity는
실제 새 DB 제약·동시성 및 변경한 capacity table 범위를 검증한다. read-only 대조 결과:
`/tmp/eom-capacity-current-schema-diff-20261030.json` /
`/tmp/eom-capacity-baseline-schema-diff-20261030.json`.

## 19:13 UTC — three-slot source pipeline checkpoint, operating activation still pending

- 원래 serial owner는 중단하지 않았다. 18:55 UTC 마지막 로그 확인은 **100/1053**
  VERIFIED, 10446 분석 중이다. 이것을 3개 슬롯 동시 동작 증거로 해석하지 않는다.
- 1.1 continuation은 원래 cohort와 serial predecessor를 exact pointer로 참조한다.
  원래 문항/등록/보고서/분석/실행 설정은 재사용하고 새 대상만 새 용량 설정으로 준비한다.
  여섯 source 상태 안에서 세 actual worker와 최대 세 문항 Graph batch를 겹친다.
- 기존 `support` pool 이름과 source plan 28 / 지식 분석 plan을 재사용하도록 미활성
  capacity 1.4 후보를 단순화했다. 별도 logical capacity/preset으로 목적을 한정하며,
  fixed-host current pointer, slot04의 기본 역할, 인증과 원래 1.0–1.3 의미는 바꾸지 않는다.
  불필요한 plan 29 / 별도 분석 plan을 새로 만들지 않는다.
- 관련 source **688 PASS**, core mypy 15개 PASS, Ruff/format / shell syntax PASS.
  fresh guarded DB `/tmp/eom-api-testdb-20261030190926_69c250b2`에서 **24 PASS**:
  실제 control Artifact·lifecycle·동시 release/replay, Workflow preparation/start/recovery,
  세 physical claim, shared host / per-slot ceiling. 모델 실행이나 운영 PASS는 아니다.
- 동시 control release 검사에서 발견한 advisory/FK 잠금 역전은 lifecycle fence를
  evaluation insert보다 먼저 잡도록 수정했다. 예외 무시나 재시도 땜질을 넣지 않았다.
  이전 실패 로그는 보존한다. 함께 실행된 구 fixture의 definition ID 충돌은 unique
  family/version 조회로 수정하고 기존 canonical bytes 비교를 유지했다.
- 새 운영 scope, migration, worker profile은 아직 활성화하지 않았다. 실제 3개 슬롯의
  동시 작성→다음 문항 refill 확인, 사용량 UI 버그, 실제 similarity adapter 배포는
  여전히 남아 있으며 goal은 ACTIVE다. 기존 GPU INDEX/QUERY 실행은 바꾸지 않았다.

Evidence: `/tmp/eom-creative-parallel-final-support-unit-20261030.log`,
`/tmp/eom-creative-parallel-final-pg-20261030.log`.

### Exact release staging checkpoint

- Source commit `8a88667700bdb2456871931ec94dc75b20908815`, pushed main.
  Source tree `2391d5b917df29318e4c3648a1a60bcba33007e1`.
- Build and wheel RECORD validation PASS:
  `/tmp/eom-api-build/8a88667700bdb2456871931ec94dc75b20908815.BrNrD8/dist`.
  The unfinished public QUERY2 work was preserved separately, excluded from the clean
  release build, then restored unchanged. Do not claim that search adapter is deployed.
- Immutable protected source/wheel staging succeeded, without a migration or service change:
  `/var/lib/eom-release-operator-stage.8a886677-gzfrs2r_`.
  Context 1.13 SHA `sha256:7716596a51a15c38223b6e9b1f976e3044235dd0d3e381829640f2e6eeded73e`.
  Operator helper/launcher: `/usr/local/libexec/eom-release-operator-creative-8a886677/`.
  Runtime ADMIT validation was started separately; inspect its terminal result before any
  callback, never assume completion from the existence of this directory.
- Retained root staging input: `/usr/local/libexec/eom-stage-creative-8a886677.py`.
  SHA `ab0ecaabc408b124f3645f87f7a62640935f45dcdbd0120d6d12ed93ce837744`.
  Staging evidence `/tmp/eom-creative-release-stage-8a886677-20261030.json`;
  admission output `/tmp/eom-creative-release-admission-8a886677-20261030.log`.
- 19:16 UTC operating observation: serial **102/1053** VERIFIED, next 10448 EXTRACTING.
  Creative owner PID 3040218 / invocation e17abed891af4fd5a79e8799579809a7;
  INDEX 2113256 / 8b9b5ed1ec1a4c67bc9ec7c44f9debff;
  QUERY 1708497 / 9c60629b423547fc832a91b7e9f180e3 unchanged.
  Three-slot activation, usage UI fix and live similarity search are still pending.

Graph 복구 Slack 보고는 `devreport_e133ee93d7054d8a8b42b35988cb3dcb`로 전송·보관됐다.

## Operating activation and three-consumer correction

- Protected migration from operating 0062 through 0063 to **0064 PASS**. Shared
  Platform/API/Catalog/Workflow/HWPX now use `8a886677`; API isolation verification PASS.
  Wheel/RECORD and actual service-identity imports were checked. Web remains `82388ed1`.
- Root staging initially inherited restrictive umask, first hiding operator code and later
  making installed Python files unreadable to service identities. No authorization guard was
  disabled. The latter was corrected by reinstalling the **same frozen wheels** with normal
  release umask 022 under the owning eom account, then checking actual service UID imports.
  Initial failure logs remain; failed Jobs/Workflow history were not changed.
- INDEX PID 2113256 / invocation `8b9b5ed1ec1a4c67bc9ec7c44f9debff` stayed running.
  QUERY coordinator was cleanly stopped by its existing `Requires=eom-api` dependency when
  API was replaced; it was restored with the **same** `07ec7b32` code/config pins (PID
  3210533 / invocation `a9b0bede71cb4372aff380ecf892562a`). Numeric bundles were untouched.
- New parallel scope `creativecohort_a7772cd7546c0adce026108e667f635a` /
  `rev_575315a22338491a9b09473d475f0139` was officially admitted for the original 1053
  targets, original operator, Workflow 2.0, original model/reasoning and target-set hash.
  Capacity `capacityrev_c754409b78514d0fa31e89cbcaa121d0` and private source/analysis
  presets are separate from fixed-host defaults. No native slot role/auth was changed.
- Operating owner reconstructed **102/1053** historical verifications and started new
  extraction/analysis. This is **not yet three-worker acceptance**. One synchronous command
  consumer serialized model submission despite capacity three; extend the already supported
  runner scale-out manager to exactly two accelerators over the original indexed queue.
  The existing reviewed similarity-read flag must be inherited byte-for-byte by both.
- First newly completed parallel extraction exposed a real resolver defect:
  `CREATIVE_LEARNING_INPUT_MISMATCH`. Completed-proposal registration only accepted the
  serial preset key, unlike submission's existing closed purpose mapping. The fix reuses
  that same mapping; the successful original result remains canonical and is not regenerated.
  Failure evidence: `/tmp/eom-creative-three-slot-error-20261030t2007.log`.
- New focused source tests **65 PASS**, actual disposable capacity/concurrent replay suite
  **7 PASS**; core mypy/Ruff/shell syntax PASS. Pending-first scheduling is a bounded,
  ephemeral priority hint only, never authority to skip historical validation or completion.

Release evidence: `/tmp/eom-creative-reviewed-migration-20261030.log`,
`/tmp/eom-creative-same-release-read-mode-20261030.log`,
`/tmp/eom-creative-isolation-8a886677-20261030.log`,
`/tmp/eom-creative-parallel-scope-8a886677-20261030.json`,
`/tmp/eom-creative-three-consumer-pg-20261030.log`.
Three actual workers/refill, usage-refresh bug and real similarity operating integration
remain required; goal stays ACTIVE.

### 20:18 UTC — actual two-worker progress and restart/observation follow-up

- Isolated creative owner `19109fc1` was installed from exact clean wheels; shared API/
  Platform remains `8a886677`, Web `82388ed1`, GPU INDEX unchanged. Fixed scale-out manager
  activated two exact accelerator consumers (PIDs 3233490/3233505) alongside canonical
  runner 3210513. Both inherit only the exact reviewed similarity-read drop-in.
- Actual workers **05 and 06** were observed simultaneously with distinct active leases
  and fixed native units. Slot06 finished one extraction and claimed the next original Job.
  **Three workers are not yet proven**: current slot04 admits Terra/high only; this cohort
  pins Terra/xhigh. No availability entry was fabricated or reasoning setting lowered.
  A bounded official compatibility window is required before slot04 can join this scope.
- A second actual restart failure was isolated without printing item content: exact START
  replay rejected legitimate derived ADVANCE command history. The fix queries the original
  START identity only, continues validating owner/plan/source, and rejects foreign history
  when no original START exists. No new Workflow or successful-history reinterpretation.
  Redacted frame evidence `/tmp/eom-creative-resume-diagnosis-20261030t2017.json`.
- The pending-first query used source-class spelling where the persisted source-kind is
  `APPROVED_ITEM_REVISION`; fixed with a regression tied to the actual contract discriminator.
  This affected scheduling priority only, not stored reports/completion counts or permissions.
- Source usage-refresh fix: maintenance claims only OBSERVE, independent of long synchronous
  model commands; busy OBSERVE collects bounded native usage without auth refresh/state writes.
  Same binding version/assignment and no enrollment are rechecked before committing its receipt.
  UI sends official OBSERVE for both busy and idle accounts. No extra service/queue/schema.
- Parallel PROCESSING is added to the read-only observer's closed healthy-state set. It was
  missing from the previous sequential-only reader and caused the 30-minute check to fail.
- Source regression runs: 45 + 73 tests PASS; restart/observation subset 56 PASS, core mypy6
  PASS. Disposable observation-claim scope PASS; first two new test failures were fixture
  mistakes (ENABLE reason / nonexistent command enum), not operating failures or waived gates.

New restart/usage/observer changes are source candidates, not yet an operating PASS. The
current creative owner stopped safely on the replay rejection; already-running worker Jobs
continue independently. Restore that same admitted scope with the tested correction; do not
submit replacement identities. Actual similarity search and full five-vector acceptance remain
pending and the full goal remains ACTIVE.

### 20:31 UTC — actual three physical workers, compatible release prepared

The bounded official compatibility window waited for zero held leases/worker units, then
held the existing host fence while stopping the same three command consumers and maintenance.
No running worker was interrupted; no binding was manually drained, reset or promoted.
Seven fresh synthetic cases retained the six existing scoped grants and tested only one new
pair (slot04 Terra/xhigh). **7/7 actual calls PASS**, original consumers restored automatically.

- Compatibility run `codexcompat_9725b7f8becb473c941726044e184e72`;
  canonical report `artifact_b206a7b39b134bb4b5c7d03e25583211` /
  `rev_f2a08ce1924a433991ffa616646826a4`, member `report.json`,
  SHA `sha256:5cd3eab5c220c8b74289b35c412d84f6c5ddae1f7ce5ea0c7e1aa49dfb37b95d`.
- Official protected policy owner installed
  `sha256:d472d448f1e38a760ec17b2e00d4f9c3c3a91f9440c4ee108126eb7b95f05c73`.
  Fresh capability snapshots were recorded against current assignments. Native slot04
  role, credentials and original Workflow/model/reasoning pins were not changed.
- Corrected isolated owner **4cc9546cf06c272ecf438716f24285244bd16cae** is active,
  PID 3275042 / invocation `1899b08f827c4085a79a4b736a1b5579`, same admitted scope.
  The read-only 30-minute observation service now completes successfully (PROCESSING supported).
- **20:27:45 UTC actual DB leases and systemd executions**:
  slot04 `job_86fe84b99f3d47fb94383795219f48d4` (PID 3275449),
  slot05 `job_bd8ccc95e8fe4d0ca45e6542a2fa9da4` (PID 3275864),
  slot06 `job_8a2ca9d884fa408c8a46d9120ea438c4` (PID 3276216).
  All three held distinct ACTIVE KNOWLEDGE_ANALYSIS leases under the admitted capacity.
  This is actual parallel execution, not three queued commands or available GUI cards.
- At **20:30:46 UTC**, slot04/05 Jobs were SUCCEEDED with exit0/no error; slot06 was
  still RUNNING. Graph publication is asynchronous and exact official report reads still
  precede VERIFIED. Refill to further source Jobs remains a separate acceptance observation.
  A restarted owner's derived counter does not reset the previously registered canonical corpus.
- Clean-source **180 PASS**, core mypy6/Ruff PASS, guarded PostgreSQL restart/control-scope
  **18 PASS**. One clean-source test initially consulted a live runtime drop-in: fixture paths
  were isolated, production identity checks retained, then the full180 passed. Failed logs kept.
- Matching API/Platform wheel and Web installed simulation/RECORD PASS. Web51 files verified.
  Build `/tmp/eom-api-build/4cc9546cf06c272ecf438716f24285244bd16cae.6Xuv5v/dist`;
  Web `/tmp/eom-web-gui-build/4cc9546cf06c272ecf438716f24285244bd16cae.W8JErN/dist`,
  wheel SHA `9dd624ced91c9e34d5f8e635eed567e1c5b3a8931e73ebabd63a2b5efbcaafbb`.
- Protected shared-release staging `/var/lib/eom-release-operator-stage.4cc9546c-xjyhsbhs`,
  context `sha256:ff5b8f38f84a8dffb19273748208ebf51244f67451c80ebf544633936a3a279b`,
  operator **ADMIT_PASS**. Shared activation has **not** happened. API/Platform stays8a886677,
  Web82388ed1; INDEX2113256 and QUERY3210533 remain active with unchanged pins.

Actual metadata-only evidence: `/tmp/eom-creative-three-live-observe-20261030t2028.json`,
`/tmp/eom-creative-refill-observe-20261030t2032.json`,
`/tmp/eom-creative-three-worker-capabilities-tail-20261030.log`,
`/tmp/eom-creative-usage-source-final-2-20261030.log`,
`/tmp/eom-creative-resume-usage-pg-final-20261030.log`.
Slack milestone `devreport_dc97eeab62ae4925b03aacfe74c880ef` SENT.

Completion still requires sustained/refilled three-slot work, usage refresh live activation /
busy-and-idle verification, actual five creative embeddings and authenticated DB similarity
search/return-to-detail/assembly integration, and compatible operating deployment. Do not
mark the full goal achieved from this three-worker checkpoint or the prepared release alone.

### 20:57 UTC — three-slot refill and busy/idle usage operating acceptance

- The initial three physical Jobs all finished. Three **different following Jobs** were
  subsequently observed together: slot04 `job_5356835536804d28b59966d746ba2355`,
  slot05 `job_df35ad1fe73a47a497775435c366d2f8`,
  slot06 `job_088000ced609431bbbf0e24d46ccc7a4`. This closes initial three-slot/refill
  acceptance, not the full embedding/similarity goal. The six-source bounded pipeline
  may temporarily wait for its serial Graph publication; it does not promise that all
  three slots stay occupied during every observation or a graceful release window.
- Shared Platform/API and Web are now the compatible **4cc9546c** release. Installed
  wheel verification checked 2,439 members, actual API isolation passed, Web service
  identity checked 51 files, and public HTTPS `/studio/` followed to the login page
  returned 200. The original three queue consumers and admitted creative scope resumed.
- The first rollout passed installation/isolation but its immediate post-restart HTTPS
  probe failed. It automatically restored shared8a886677/Web82388ed1. That failed release
  remains failed; the second recorded attempt used the same wheels and a bounded,
  read-only HTTP readiness wait, then completed successfully. No model request was
  regenerated, history rewritten, or DB downgrade performed.
- **Actual official OBSERVE commands while slot04 was writing a report**:
  busy04 `codexcmd_1469362685b74041a33483cdcd0c45e0` and idle01
  `codexcmd_7a1339f00e1543c0a78a7e5c2a19c410` both SUCCEEDED with new native usage
  observation times. Slot04's Job `job_40431a2e9baa4c65a02300cc78012562`, READY state
  and resource version3364 were unchanged. Idle01 retained the normal full observation
  behavior (version3360→3361). No auth refresh, inference or administrative state promotion
  occurred for the busy slot. This is operating command/receipt evidence; no new manual
  browser assertion is inferred from it.
- INDEX PID2113256 / invocation `8b9b5ed1ec1a4c67bc9ec7c44f9debff` stayed unchanged.
  QUERY coordinator was stopped/restarted by its existing API dependency and retains the
  original07ec7b32 runtime/configuration pins; do not claim its PID was unchanged.

Evidence: `/tmp/eom-creative-usage-attempt2-terminal-20261030.log`,
`/tmp/eom-busy-usage-operating-4cc9546c-20261030.json`,
`/tmp/eom-busy-usage-operating-tail-20261030.log`; protected completion record
`/var/lib/eom-release-operator-stage.4cc9546c-xjyhsbhs/usage-release-completed.json`.
Full goal remains ACTIVE: public-report INDEX activation, five actual creative vectors,
official DB similarity QUERY/read/replay and automatic backlog/future increments remain.
