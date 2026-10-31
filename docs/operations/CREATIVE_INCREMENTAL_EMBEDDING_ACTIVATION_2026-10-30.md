# 창작 풀이보고서 자동 증분 임베딩 활성화

2026-10-30 UTC. 목표는 **보고서·Graph 검증 → 실제 벡터 등록 → 공식 검색 반영**이다.
기존 [공통 풀이 설계](../architecture/SOLUTION_EMBEDDING_FORMAT_COMPATIBILITY.md)와
[구현 체크포인트](PUBLIC_SOLUTION_EMBEDDING_CONNECTION_2026-10-29.md)를 이어간다.

## 사용자 확정 최종 완료 조건

현재 활성 goal은 아래 세 조건과 본문의 실제 창작 5건 검증이 모두 닫힐 때만 완료한다.
source test·패키지 설치·service active만으로 완료하지 않는다.

1. 04/05/06 세 실제 슬롯이 서로 다른 풀이보고서를 작성하고 다음 작업으로 refill됨을 확인.
2. 슬롯 사용 중에도 상태·사용량 새로고침이 완료·갱신되는 버그 수정과 운영 acceptance 보존.
3. DB의 `조회 → 유사도 → 조회/배치`를 공식 Graph/Catalog/QUERY에 실제 연결·호환 배포하고,
   canonical vector/binding·검색·같은 key replay/복구 및 backlog/향후 자동 증분까지 검증.

30분 background 관측은 계속 유지하며 기존 520개 기출·교과서·정본·FAILED 이력을 보존한다.

## 23:50 UTC 작업 체크포인트 — 실제 완료 아님

- shared API/platform `c868a15c`, Web `f1a7ada4` 운영 배포와 설치 byte/source-free/isolation
  검증을 완료했다. source migration head `0064`는 그대로이며 새 migration을 적용하지 않았다.
- INDEX 이전 GPU 작업은 main-only graceful drain으로 실제 완료했다. 끝내 한 번도 claim되지
  않은 원래 CPU 대기 3건만 공식 cancellation으로 정리해 receipt를 남겼다. 시작한 작업·완료
  벡터·FAILED를 삭제하거나 성공으로 바꾸지 않았다.
- QUERY의 실제 설치 API provider member 2개가 새 wheel과 불일치해 시작을 거부했다.
  검증을 우회하지 않고 검증된 `c868a15c` wheel의 정확한 source/SHA/code members로 repin했다.
  비밀번호·인증 파일·외부 API는 바꾸지 않았다.
- public ownership/3.0은 기존 공식 schema-owner preparation으로 등록·확인했다. 이는 DB
  migration이나 runtime self-grant가 아니다. 예전 6개 namespace·물리 CPU/CUDA prefix와
  canonical index는 보존하며 public namespace 하나만 추가했다. 메모리 ceiling도 원래
  운영 2 GiB로 유지한다.
- `b5670ba9` CPU counterpart Graph pin 수정의 단위 54, 관련 실제 임시 PostgreSQL 9 PASS.
  `9836f132`의 불변 metadata 읽기 권한 검증 10 PASS. `bedbb72b` lineage/file-set·selection
  정상 transaction 수정 관련 99 PASS, 임시 PostgreSQL 11 PASS. `7e09a149` bounded reader /
  256-source keyset page 관련 100 PASS. 각 변경 core의 mypy/Ruff/format PASS.
- 실제 제한 Catalog 계정으로 고정 창작 5개의 canonical lineage/result/report를 읽고 원래
  provenance를 재검증했다: `eom-public-five-creative-read-preflight.service` PASS, DML=0,
  inference=0. 이는 **수치 계산·등록·사용자 검색 acceptance가 아니다**.
- 23:44 UTC 실제 세 슬롯에서 각각 RUNNING Job을 재확인했다. `job_aae353ccf6da4a5f82bd1c3bb857681b`
  (04), `job_7ad0142e2b4c4cf09437e434ebc17c2f` (05), `job_1220df32ab384801ab0c050607c6cb19`
  (06). 기존 refill 증거도 보존한다. 10700의 no-Job preexecution 실패는 공식
  `recover_unstarted`로 같은 입력/정책의 successor를 준비하고 재개했다. 원 실패의 정확한
  내부 cause는 generic summary만 남아 확정하지 않았으며, 이를 current source defect로
  단정해 코드를 바꾸지 않았다.
- `7e09a149` INDEX/QUERY/Catalog successor의 호환 activation을 진행 중이다. 기출 및 창작
  보고서 읽기에서 발견한 실제 권한·file-set·metadata budget 오류를 테스트로 고쳤다.
  아직 public vector/index/실제 HTTP 검색은 미검증이며 goal은 ACTIVE다.

운영 기록: `/var/lib/eom-public-solution-release-{b5670ba9,9836f132,bedbb72b,7e09a149}`의
exact plan·rollback 원본·control pointers·identity/cancellation receipt. 이전 후보와 실패한
preflight 기록은 보존했다. transient activation은 source Git을 runtime에서 읽지 않는다.

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

## 22:36 UTC 체크포인트 — DB의 실제 QUERY 연결 후보

사용자 확정 완료 조건은 **세 실제 슬롯의 연속 refill → 사용량 새로고침 버그 수정 →
DB 유사도의 실제 검색·호환 운영 배포**다. 목표는 ACTIVE이며 마지막 항목은 아직 미완료다.

- DB 선택 포인터를 Catalog의 API-only Unix operation으로 해석하고, 실제 operator 권한과
  원문 observation/등록 Item/Graph membership을 재확인한다. HTTP에서 actor·권한·경로·벡터는
  받지 않는다. 자세한 결정은
  [DB 연결 설계](../architecture/ITEM_DB_PUBLIC_SIMILARITY_CONNECTION.md)에 기록했다.
- API는 기존 public QUERY prepare4와 completed read3를 호출한다. 이번 경계 테스트에서
  새 route의 current authentication capture 누락을 발견해 기존 중앙 인증 분기에 추가했다.
  별도 로그인·세션·권한 추측을 만들지 않았다. 초기 요청과 PENDING 재관측은 같은 key와
  exact query/Graph/policy를 사용하며, 이미 처리 여부가 불명인 요청을 자동 재제출하지 않는다.
- 검색 ranking과 source/report 핀은 원래 indexed Graph를 보존한다. 결과 열람·배치는 같은
  immutable Item/revision/content pointer를 현재 Graph에서 한 번의 bounded metadata query로
  재검증한다. 검색 Graph와 탐색 Graph는 별개이며 없는 문항을 latest revision으로 바꾸지 않는다.
- Web BFF는 session/CSRF/key를 검사하고 기존 API만 호출한다. 실제 GUI adapter를 연결했으며
  `조회 → 유사도 → 조회/배치`, 작은 계산 중 표시, 원래 검색 pin의 자동/수동 재관측을 유지한다.
  새 DB·queue·벡터 복사본·검색 알고리즘·의존성은 없다.
- focused source/HTTP/Unix peer/replay/BFF 검증 **42 PASS**. 실제 브라우저 엔진으로 기존 DB
  조회·필터·responsive·유사도 이동·진행 표시·원래 pin 재관측과 OpenAPI/route 회귀 **25 PASS**.
  package resource/dependency/release inventory **52 PASS**. 변경 core 15개 mypy PASS,
  Python 20개 Ruff/format PASS. 이 테스트의 source/IAM/수치 leaf는 합성이며 운영 검색 성공이 아니다.
- 22:31 UTC 창작 owner는 원래 invocation `43c4dd6e88ee45ba8473b7785ad68e97`로 실행 중이며
  10679–10684가 Graph publication 단계다. 그 순간 ACTIVE worker lease 0은 publication 구간이지
  서비스 중단 증거가 아니다. 앞서 04/05/06의 실제 다음 Job refill 증거는 그대로 보존한다.
  derived counter 12를 전체 누적 완료 수로 표시하지 않는다. 기존 INDEX/QUERY도 교체하지 않았다.

다음은 이 후보의 clean wheel/source-free 설치 검증과 protected public INDEX/QUERY controls의
호환 활성화다. 기존 수치 runtime과 진행 중 native 실행을 보호하며 고정 창작 5건의 실제
encoding·canonical registration·공식 검색·replay를 확인하고 자동 증분 처리까지 운영 반영해야
완료다. 기존 사용량 acceptance와 historical FAILED 기록은 재해석하지 않는다.

후속 설치 후보 확인: `896c596684f721a36d663ff4dd05134521cc29b0` API/platform wheel
build와 RECORD/source-free simulation PASS. protected owner installer로 같은 source를
`/opt/eom/embedding-owner-releases/896c596684f721a36d663ff4dd05134521cc29b0`에 stage했다.
설치본은 아직 **미활성**이며 CPU numerical runtime·기존 INDEX/QUERY/창작 process는 그대로다.
처음 installer를 직접 실행한 호출은 파일이 non-executable이어서 실행 전에 거부됐다.
기존 Bash 실행 방식으로 stage를 마쳤으며 runtime/DB 변경은 없었다.

Web의 독립 wheel gate는 새 `item_db_similarity_contracts.py`가 명시적 runtime inventory에
빠진 것을 탐지해 차단했다. inventory에 이 실제 모듈 하나를 추가하고 해당 release 회귀와
독립 Web build를 재실행한다. 이 실패를 운영 장애나 미확인 성공으로 표시하지 않는다.

## 운영 활성화 전 발견한 root GPU policy 선택 경계

public INDEX6와 QUERY5는 기존 수치 runtime을 공유하지만 공통 풀이 recipe2에 대한 별도
routing policy를 핀한다. 기존 고정 root batch entry는 purpose마다 policy 파일 하나만
허용하므로, 기존 recipe1과 public recipe2를 cohost하면 새 public 실행이 거부된다.
기존 정책 파일을 새 정책으로 덮으면 반대로 기존 작업이 깨진다. 실제 운영 controls를
읽어 이 차이를 확인했으며, public activation 전에 기존 adapter의 이 경계만 보완한다.

- 정본은 기존 root-protected routing Artifact와 고정 설치 파일·raw hash다. allocation
  JSON Schema/wire·source 권한·native lease·수치 protocol·DB schema는 바꾸지 않는다.
- purpose마다 기존 정책 하나 + 명시적 public 정책 하나만 허용한다. public 경로는 고정된
  `public-index.json`/`public-query.json`이며 각각의 별도 root 환경 hash가 있어야 한다.
  요청의 임의 경로·hash만으로 정책을 읽거나 등록할 수 없다.
- 정상 기존 policy가 request의 exact semantic hash와 맞으면 기존 경로만 읽는다. 다를 때만
  opt-in public policy를 읽고, CPU/CUDA backend·profile은 기존 정책과 정확히 같아야 한다.
  recipe가 다른 것만 허용하므로 물리 권한·resource ceiling을 넓히는 fallback이 아니다.
- malformed/missing/hash-mismatched 원 정책, public policy 부재·변조, 다른 request hash는
  명시적 거부다. GPU BUSY로 바꾸거나 CPU로 강제 우회하지 않는다.
- 기존 root adapter 소유권과 두 개의 O(1) fixed lookup을 유지한다. 새 registry·queue·
  자유 형식 policy 목록이나 영속 cache는 만들지 않는다. 활성 native 실행 종료 후에만
  설치 파일/hash/entrypoint를 호환 묶음으로 선택한다.

`896c5966` owner stage와 미활성 read-only index plan은 보존한다. 위 수정까지 포함한
successor 설치본을 준비하기 전에는 그 plan을 운영 활성화하지 않는다.

후속 source gate: 기존 root entry/handoff/activation/controller/unit descriptor **100 PASS**,
public/legacy indexing owner·finite batch **56 PASS**. 최종 immutable fixed-map root entry
suite **28 PASS**(100 suite와 겹침), mypy 1개와 Ruff/format PASS다. 기존 정책의 정상 경로,
INDEX/QUERY의 public opt-in, hash/미설정/다른 요청/더 넓은 자원/같은 recipe/원 정책 변조의
거부를 포함한다. 물리 GPU·설치 grant·운영 동작은 아직 이 source gate로 입증하지 않았다.
DB schema·lease·state-machine 변경은 없으므로 기존 guarded PostgreSQL evidence를 보존하고,
이번 fixed-file selection diff만을 이유로 DB mutating suite를 다시 실행하지 않는다.

별도 임시 디렉터리의 synthetic publisher로 실제 non-secret 준비 controls의 변환을 확인했다.
새 public namespace 1개 + 기존 namespace 6개, 각 장치의 독립 grant, 실제 수치 runtime 입력
보존, 같은 plan 재실행 결과 동일을 확인했다. 이 검사는 **1 PASS**, DB/NAS/model 호출 0이며
source 권한·실제 벡터 등록 성공 증거는 아니다. metadata 정책 선택 순서를 grant의 정해진
namespace 순서로 유지하도록 운영 adapter를 정리했고, 후보 검증 전에 NAS controls를
발행하지 않았다.

### 후속 운영 준비 결과 — c868a15c, 아직 미활성

- 수정 source `c868a15c155cf08669a35a0ee2b6ef645b366ed6` commit/push 및 clean API/platform
  build/RECORD/source-free simulation PASS. 같은 source의 protected owner wheel stage PASS.
  원래 CPU/CUDA numerical prefix는 설치·교체하지 않았다.
- 실제 read-only preflight에서 현재 INDEX service revision에 CPU PENDING Workflow 1개를
  확인했다. pending을 FAILED/성공으로 바꾸지 않았으며 실행 owner를 임의로 중단하지 않았다.
  underlying source policy가 APPROVED_ITEM/PAST_EXAM을 허용함도 정확한 revision/hash로 확인했다.
- `/var/lib/eom-public-solution-release-c868a15c/index-plan.json`에 successor identity·rollback
  원본 hash·runtime·기존 6개 namespace·새 1개 namespace를 준비했다. 현재 service identity는
  아직 바꾸지 않았다. `896c5966` 준비 기록은 미활성 predecessor로 보존한다.
- 공식 Orchestrator `LocalEmbeddingControlArtifactPublisher`로 새 routing/native control
  Artifact 발행을 마쳤다. `candidate-owner.json`/`candidate-grants.json`이 생성됐지만 **source
  access grant의 DB publication, service 활성화, systemd 선택은 하지 않았다**. 실제 모델 호출 0.
  root의 `public-index-policy.json`과 opt-in 환경 hash도 아직 운영 선택 파일이 아니다.
- 기존 INDEX PID 2113256, QUERY PID 3364368, 창작 owner PID 3418846은 유지했다. 따라서 이
  checkpoint를 창작 벡터 등록·공식 검색 성공으로 확대 해석하면 안 된다.

실제 로그: `/tmp/eom-public-root-policy-final-20261030-2.log`,
`/tmp/eom-public-root-cohost-compatibility-20261030-2.log`,
`/tmp/eom-public-index-composition-successor-20261030.log`,
`/tmp/eom-public-root-policy-build-c868a15c-20261030.log`,
`/tmp/eom-public-owner-install-c868a15c-20261030.log`,
`/tmp/eom-public-index-prepare-c868a15c-20261030.log`,
`/tmp/eom-public-index-publish-c868a15c-20261030.log`。

남은 실제 실행은 public QUERY의 native definition2/policy·공통 recipe 선택 준비, 현재 pending
작업을 보존한 quiescent INDEX/QUERY 활성화, API/Web compatible rollout, 고정 창작 5건의
encoding/Registry/search/replay·backlog/future 자동 처리다. 목표는 계속 ACTIVE다.

### 활성화 전 CPU counterpart 범위·snapshot 보정

public namespace는 이미 16,384 source를 계약으로 허용하지만 기존 CPU counterpart 준비
함수의 내부 상한은 1,024로 남아 있다. 또한 GPU 완료 후 일반 CPU discovery를 호출하면,
그 사이 Graph publication이 진행된 경우 CPU/GPU head가 서로 다른 snapshot을 고를 수 있다.
공식 검색은 같은 Graph/policy의 두 장치 index만 허용하므로 이 경계를 먼저 보정한다.

기존 service preparation의 public namespace 상한만 선언된 16,384로 맞추고 legacy는
1,024 그대로 둔다. GPU public 완료/metadata refresh의 CPU standby는 기존 `prepare_matching`
과 `submit_prepared`로 원래 GPU request의 Graph/policy/ordered source를 재인가·핀한다.
새 queue·selector·DB/index·wire family·모델 호출 경로는 만들지 않는다. CPU/GPU space는
계속 별개이며 벡터를 이름만 바꿔 복사하지 않는다. API/UI가 target이나 권한을 주는 것도
아니다. 준비/START 사이의 실제 service/source fence, stable key, CAS/unique 제약은 기존
경계를 사용한다. 비용은 원래 선택 K개에 대한 O(K) metadata 준비이며 K≤1,024, 전체 허용
population≤16,384다. 더 단순한 latest CPU discovery는 원래 Graph pin을 깨므로 적절하지
않다. source 거부·범위 초과·내용 불일치는 실패하며 옛 보고서로 대체하지 않는다.

### 운영 발견: 창작 보고서 batch read의 최소 권한과 불변성

실제 제한된 Catalog DB 역할에서 public capture가 `item_components`의 `FOR SHARE` 때문에
42501로 거부됐다. PostgreSQL의 row-lock SELECT는 UPDATE 권한도 필요하지만, 승인 문항의
component·resolved plan·승인 Artifact Revision은 기존 DB trigger로 UPDATE/DELETE가 금지된
불변 정본이다. 이 조회 때문에 해당 정본에 새로운 UPDATE 권한을 부여하지 않는다.

책임은 기존 Catalog batch reader에 둔다. 승인 Item Revision 및 mutable Workflow/step/Job의
기존 source/lifecycle lock은 유지하고, exact revision/hash로 고정된 불변 component/plan/
Artifact metadata의 불필요한 row lock만 제거한다. 원래 hash·manifest·완료 상태·출처·권한
검증과 caller-owned transaction은 유지한다. 변경은 wire/queue/schema/index가 아닌 SQL read
선택이다. ID-keyed map과 batch 5개 metadata query, O(K) 공간·시간, K≤16도 그대로다.
missing/hash/lifecycle 실패와 원래 idempotency는 변하지 않는다. 더 단순한 해결처럼 보이는
UPDATE grant 확대는 least privilege와 정본 불변성에 불필요하므로 배제한다. 제한된 실제
PostgreSQL 역할로 SELECT 성공·FOR SHARE/UPDATE 거부를 함께 검증한다.

또한 실제 lineage는 `lineage.json`을 primary로 가진 기존 file-set Artifact인데 batch
경로에서 `result.json` 전용 JSON loader에 넘기던 불일치를 발견했다. 공통 Artifact loader의
허용 범위를 넓히지 않는다. 기존 caller-owned `PinnedArtifactReadContext`로 lineage의 정확한
member/schema/media/hash와 producer를 prefetch·검증하고, 역할 결과만 원래 result loader로
batch 읽는다. Item component·lineage·result의 정본과 경고는 그대로다. 새 Artifact나 복사본,
wire format은 없다. reader 전체 재검증은 원래 capture owner가 마지막에 수행하며, 각 작은
batch에서 커진 공용 cache를 반복 재검증하지 않는다.

DB 유사도 selection의 read use case 역시 원래 source capture의 shared lifecycle lock을
사용하므로 PostgreSQL `READ ONLY` transaction을 강제하면 그 SELECT조차 25006으로 거부된다.
기존 application-owned 정상 transaction에서 공식 source reader만 호출하도록 정렬하며,
selection 자체에 DML·권한 확대·모델 실행을 추가하지 않는다. shared lock·정확한 current
operator 양끝 fence·원래 replay scope는 유지하고 해당 PostgreSQL 동작을 임시 DB로 검증한다.

실제 full-corpus capture에서는 Graph/source metadata가 채운 공용 reader에 lineage를 계속
추가해 기존 4,096 revision budget을 넘는 것도 확인했다. budget을 늘리는 대신 기존 root-bound
reader를 lineage 16개 단위로 나누어 그 작은 집합만 재검증하고 해제한다. public population의
keyset page도 최대 256 source로 제한해 provenance reader가 corpus 증가에 따라 무한히 커지지
않게 한다. 이는 전체 모집단의 truncation이나 허용 정책 변경이 아니다. 모든 page를 순서대로
읽고 동일한 최종 membership·authority 재확인을 유지하며, 1,100/1,573 source synthetic
회귀로 누락 없는 전체 순회와 페이지 간 변경 거부를 검증한다.

23:51 UTC paginated capture는 진행됐지만, native START/등록의 정상 SQL SAVEPOINT 안에서
기존 creative batch reader가 nested transaction 자체를 거부하는 경계를 확인했다. 이 reader는
읽기만 하므로 정상 savepoint를 막지 않는다. read set은 root뿐 아니라 생성 시의 exact
savepoint와 thread를 함께 핀하고 commit/rollback/다른 savepoint로 넘어가면 재사용을 거부한다.
원래 source·lifecycle·hash 검증은 유지한다. 이 수정은 아직 운영 배포 전이며 실제 임시 DB의
savepoint commit/rollback 경계와 제한 권한 회귀를 확인한 뒤 successor release로 반영한다.

동시에 creative owner가 다시 no-Job preexecution failure로 멈췄다. 알려진 새 실패는
`workflow_f44f5c995540491d83da44fe2634b6b5`다. 기존 실패는 보존하며 generic error summary만으로
원인을 추측하지 않는다. 현재 INDEX와 creative owner의 실패를 active/완료로 보고하지 않는다.
API/Web/Catalog/QUERY의 정상 운영과 원래 30분 관측 timer는 유지된다. 다음은 savepoint 수정
검증·배포, 새 creative 실패의 원인 분류/공식 복구, 실제 vectors/검색 acceptance다.

2026-10-31 00:04 UTC `31ddcf62` INDEX/QUERY/Catalog successor를 실제 활성화했다. shared
API/Web와 physical numerical prefixes는 바꾸지 않았다. 00:07 UTC finite native GPU owner /
batch `71e77449bd684eb29b5a21f040f1c8fb`의 실제 PID 3646559/3647095가 확인됐다. 이는 살아 있는
실행 handle이며 아직 수치 완료·등록 증거가 아니다. 앞선 no-Job 실패는 같은 원문/정책으로
공식 successor `workflow_dec29de748d34038b392a955f8fe6f84`를 준비하고 creative owner를 재개했다.

preexecution generic exception의 내부 원인이 기존 로그에 보존되지 않아, command-failure
로그에 bounded cause type/code/EOM module:line/SQLSTATE만 추가한다. 메시지·locals·SQL·파일
경로·입력/결과는 기록하지 않고, 예외 chain/cycle도 bounded로 처리한다. 실행·상태 전이·retry
정책이나 과거 실패는 바꾸지 않는다. 실제 source defect 판정은 이 진단 증거를 본 뒤 한다.
새 logging candidate는 운영 배포 전이며, 기존 protected INDEX/QUERY pin을 건드리지 않는
shared release 창에서만 반영한다.

## 22:01 UTC 체크포인트 — 세 슬롯 복구와 public QUERY 공식 조회 연결

목표 상태는 **ACTIVE / 미완료**다. 사용자 확정 세 단계와 기존 창작 5건의 실제 수치·등록·
검색·운영 검증 범위를 줄이지 않는다. 이번 체크포인트의 새 public 연결은 저장소 후보이며
운영 source `4cc9546c`, 기존 QUERY `07ec7b32`, INDEX `b3c8a4c0`와 구분한다.

### 실제 창작 처리 중단 및 공식 복구

- 21:21 UTC 10668의 `workflow_2c8e7f50ef6942069f83cbd3b0c33842` /
  `job_b75d959b00304af5a105c27370543494`가 `WORKER_RESULT_INVALID`로 끝났다.
  원인은 결과의 content-region map이 허용되지 않은 원문 영역 역할을 가리킨 것이다.
  모델 실행은 exit 0이었지만 출처 검증에 실패했다. 사용량 소진·슬롯 점유 표시 문제가 아니다.
- 추측한 대표 문항 10514가 아니라 실제 실패한 10668을 읽기 전용 조회와 local result의
  입력을 제외한 validation location/message로 특정했다. 잘못된 출처 연결을 자동 수정하거나
  검증을 완화하지 않았다.
- 배포된 `CreativeCohortPreparationService.recover_invalid_result`를 명시적으로 호출했다.
  기존 Workflow/Job/step은 FAILED로 보존되고, no-commit/no-active-work 증명과 현재 원문
  권한 재확인 후 successor `workflow_b70706d174c14d978a75096af9a05b95`만 준비됐다.
  같은 복구 요청 재전송은 같은 successor이며 원래 request와 정책 핀은 변경하지 않았다.
- 원래 cohort revision으로 기존 서비스를 재개했다. 21:47 UTC 실제 04·05·06 세 슬롯에서
  각기 다른 RUNNING Job과 ACTIVE KNOWLEDGE_ANALYSIS lease를 확인했다. 22:00:54 UTC에는
  모두 **다음** Job으로 refill된 것을 다시 확인했다:
  04 `job_470fa6a6f78d410fa2e56ad783d51d63`,
  05 `job_00e12058af03473ea31c461fc23e181d`,
  06 `job_7ef1863ff9a244e992f6a3a454741c13`.
- INDEX PID `2113256` / invocation `8b9b5ed1ec1a4c67bc9ec7c44f9debff`는 그대로다.
  창작 서비스 재시작 시의 derived verified counter는 새 pending-first 순회 분모로 계산된다.
  이를 누적 정본 수의 감소로 해석하거나 기존 완료 수에 무조건 합산하지 않는다.
  30분 observe timer는 계속 활성화돼 있다.
- 복구 회귀 32 PASS. 이 작업에 새 runtime 설치·DB 직접 UPDATE·인증 변경은 없었다.

### 새 public QUERY 연결의 저장소 검증

- 공개 풀이 namespace 전용 CPU4/routed5 설정과 prepare4를 기존 owner에 opt-in cohost했다.
  같은 installed source/provider/DB identity를 확인하며 실제 HTTP capture를 재사용한다.
  preparation2는 기존 parent1.4와 ordered source/policy/Graph/index 핀을 보존한다.
- 1–32 source 준비는 실제 Catalog public-source read를 일괄 수행한다. 장치별 canonical
  index를 한 번만 읽고 요청 순서를 유지한다. replay는 original preparation을 읽으며
  head/index selection을 다시 실행하지 않는다. legacy single/16-item 계약의 한도는 유지한다.
- 완료 결과의 read3는 기존 completed public QUERY reader를 호출한다. Catalog의 read-only
  composition은 public QUERY5의 비밀 없는 고정 controls를 재사용하지만 DB role/fence와
  policy/bundle/routing Artifact를 독립 검증한다. 새 queue·검색 엔진·reader 설정 계열은 없다.
- HTTP는 기존 preparation과 similarity-context operation에 명시적 새 family를 추가했다.
  완료 결과는 schema discriminator로 선택해 구형 응답을 새 family validator에 넣지 않는다.
  단일 준비와 일괄 준비의 원래 raw-byte 한도를 각각 적용한다. 새 public read는 threadpool로
  실행해 Catalog 응답 대기가 API event loop를 막지 않는다. OpenAPI도 함께 갱신했다.
- focused selection/configuration/legacy prepare 회귀 219 PASS; 기존 runtime/native executor
  회귀 25 PASS; completed-read/legacy 회귀 93 PASS; public read composition 6 PASS;
  실제 HTTP/Unix/current-capture/API/OpenAPI 회귀 88 PASS;
  schema resource/dependency/runner composition 회귀 74 PASS.
- guarded disposable PostgreSQL에서 public native result·중단 복구·routed preparation/
  publication·동시성 22 PASS. 임시 DB는 `/tmp/eom-api-testdb-20261030190926_69c250b2`이고
  운영 DB에 mutating pytest를 실행하지 않았다. 새 DB migration은 없다.
- 변경 core 25개와 QUERY/batch/read 관련 core 79개 mypy PASS; 변경 Python 38개 Ruff/
  formatter PASS. 모델/GPU inference·추가 문항 생성은 이 source test에 포함되지 않는다.
- 후속으로 public prepare4 자체의 동일 요청 동시 생성·publication 중단 후 원래 selection
  재사용·현재 권한 거부·다른 intent 재전송 거부를 같은 guarded PostgreSQL에서 추가 확인했다.
  새 integration 3 PASS, 공유 unit fixture 회귀 3 PASS. source/index/IAM 관측은 명시적 합성
  leaf이고, 실제 PostgreSQL Job/event/Artifact의 uniqueness와 복구를 검사한 결과다.
- source `3cc5792de80b70740c3c711d6891ad8e88764b45` clean build PASS:
  `/tmp/eom-api-build/3cc5792de80b70740c3c711d6891ad8e88764b45.2ajqlw/dist`.
  wheel RECORD와 source-free installed simulation을 검증했으며 운영에는 설치하지 않았다.

### 남은 필수 작업

DB 선택 포인터→현재 권한으로 정확한 Graph/등록 원문 해석→공식 prepare/read adapter를
`조회 → 유사도 → 조회/배치`에 실제 연결해야 한다. public INDEX/QUERY의 compatible installed
release와 정책은 아직 활성화하지 않았다. 기존 수치 runtime pin을 보호하며 candidate wheel을
검증한 뒤, 원래 창작 5건의 실제 encoding/Registry/search/replay와 자동 backlog/향후 증분을
검증·배포해야 목표가 완료된다. 기존 사용량 버그의 운영 acceptance는 재개방하지 않는다.

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

### Following source checkpoint — public QUERY through existing finite execution owners

The operating release remains4cc9546c; the following changes are a **source candidate**,
not a claim that DB similarity is live. No new model/GPU canary was run for this checkpoint.

- Shared source preparation/native executor/completion/consumer read now dispatch public
  Workflow2 / request3 / QUERY2 / receipt2 explicitly. Legacy concrete parsers stay closed.
  Common public reports use context3 and canonical completed result/shard reads; no direct
  API encoder call or substitute search engine is added.
- Schema-first `embedding-batch-plan/1.4` is QUERY-only. It pins up to32 ordered public
  report/source references, Graph/policy and one exact CPU/CUDA index pair. Original physical
  allocation/route/bound/root receipt frames retain their bytes and meanings. Catalog
  resolves and reauthorizes both actual device populations; it does not pair by item number.
- The already-defined numeric public batch2 passes through the original protected local
  workspace, root grant/channel, source/lease checks, native FD execution and publication
  owners. Public parent1.4 binds batch2 only; older parents and DOCUMENT INDEX1.3 retain
  batch1. A literal legacy/public mismatch is rejected, not relabeled. New tests exercise
  real temporary protected files, real Unix peer framing and canonical result/ACK with
  explicitly synthetic model and authority leaves.
- Source verification: controller/contract/workspace matrix **273 PASS**; native/public
  focused regression **65 PASS**; final public parent/routing/materialization **14 PASS**;
  legacy routed/preparation consumers **69 PASS**. The separate public/legacy Unix round
  trip **2 PASS** is included in later focused coverage; do not sum overlapping suites.
- Marker-guarded disposable PostgreSQL native public/legacy tests **37 PASS**, including
  seven additional actual-executor tests for concurrent checkpoint replay, four interruption
  boundaries, exact replay and immutable failed history. These use synthetic IAM/model
  observations and temporary Artifact storage, never the production DB or NAS. Existing
  public coordinator/publisher coverage is preserved, not replaced by the executor tests.
- Core mypy passed58 changed files, and the full39 QUERY/batch consumers passed separately.
  These sets overlap. Ruff/format and final clean-source verification are recorded alongside
  the candidate commit/build; no production acceptance is inferred from source tests.

Evidence: `/tmp/eom-public-query-controller-closure-tests-20261030.log`,
`/tmp/eom-public-query-final-focused-20261030.log`,
`/tmp/eom-public-query-parent-final-2-20261030.log`,
`/tmp/eom-public-query-legacy-consumers-20261030.log`,
`/tmp/eom-public-query-all-postgres-20261030.log`,
`/tmp/eom-public-query-final-core-mypy-20261030.log`,
`/tmp/eom-public-query-consumers-mypy-20261030.log`.

Next required scope: supported installed public QUERY configuration/composition (existing
owner versions1/2 and routed3 already exist; do not reuse their version numbers/meanings),
public selection/HTTP prepare/read/DB adapter, compatible isolated/public INDEX activation,
five actual creative vectors and authenticated result/replay/return-to-detail. Three actual
report slots and busy/idle operating usage acceptance are closed; the full goal stays ACTIVE.

Source commit `43b57013` was pushed. Its first build-only run passed wheel RECORD but
correctly rejected an incomplete installed-definition inventory: native QUERY2 had been
admitted in source but omitted from the release simulation's materialized/compiled definitions.
The follow-up explicitly stages, passes and checks that definition; the actual equality gate
is retained. Release-inventory tests also execute the pre-existing two derived creative
definition paths, and the per-frame parse-spy test follows the closed supported-family parser
name. No obsolete parser alias or production validation relaxation was added for tests.
These focused release/source checks **56 PASS**; the failed build/log remains preserved at
`/tmp/eom-public-query-build-43b57013-20261030.log`. Operating services were not touched.

Follow-up commit **376fd55d970ea2e79ff4655cce8a67344e0c6ce9** was pushed and its
clean build-only release passed wheel RECORD and the non-editable installed simulation:
`/tmp/eom-public-query-candidate-build-final-20261030.log`; wheels
`/tmp/eom-api-build/376fd55d970ea2e79ff4655cce8a67344e0c6ce9.8FHUxI/dist`.
This candidate is not installed into the operating shared or numerical runtimes.
The operating shared/Web4cc9546c, creative owner PID3364628 and original INDEX PID2113256
remain active. The 30-minute creative observation timer remains enabled; no frequent
separate polling loop was installed. Slack usage milestone
`devreport_911126f32b8a41ad869b9ba04d290205` was delivered with the required first Korean
summary sentence. Public activation and the full five-vector/search acceptance stay pending.
