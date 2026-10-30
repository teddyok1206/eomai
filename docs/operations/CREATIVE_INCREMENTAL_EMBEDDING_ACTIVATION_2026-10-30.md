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
