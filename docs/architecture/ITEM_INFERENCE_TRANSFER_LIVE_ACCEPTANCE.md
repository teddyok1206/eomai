# 문항 핵심 착상 전이: 실제 운영 검증 기록

상태 시각: 2026-10-11 17:15 UTC. 이 문서는 실제 설치·실행 증거와 남은 gate를
구분한다. 소스 테스트 통과를 운영 활성화나 사람의 전이 품질 승인으로 확대하지 않는다.

사용자 최신 지시에 따라 **사람 평가는 현 목표의 완료 조건에서 제외**한다.
`HUMAN_TRANSFER_REVIEW=NOT_EVALUATED / NOT_REQUIRED_FOR_CURRENT_COMPLETION`이다.
기존 optional 계약과 이력은 보존하며 자동 모델 판단을 사람 label로 기록하지 않는다.
아래 과거 실행의 human gate 표현은 당시 이력이지 현재 필수 조건이 아니다.

## 보존하는 설계와 범위

- [승인된 설계 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)의 SHA-256:
  `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a`.
- 정본은 기존 승인 문항·기출 분석·풀이보고서 및 pin된 Graph/policy다. 새 비교 표현,
  벡터와 쌍 비교는 보조 파생물이다. 기존 검색·출제·검토·승인 의미를 대체하지 않는다.
- 실제 `guiadmin` 사용 승인을 받았다. 승인은 인증 토큰이나 자격 증명 그 자체가 아니다.
  실제 session과 현재 권한을 검증하기 전에는 corpus를 읽거나 worker를 제출하지 않는다.
- 원래 occurrence-backed 기출 목표 520개를 사용한다. 별도 trusted-RAG canary는 의도적으로
  제외한다. 기존 풀이보고서 520개를 다시 생성하지 않는다.

## Component 상태

| Component | 실제 상태 | 한계 |
|---|---|---|
| 공유 API/platform | 설치 source `c8b29f67b523744049c56a12bcdef376b7aef5f5`, tree `0679c159eebe02a07e156d90aa57cc735e677191`; 2026-10-11 10:45 UTC 복구·검증 완료 | AUTHORIZE 전용 내부 300초/외부 330초, BGE-only 6 GiB/5400초 profile 포함. 전체 520개 BGE MEASURED/COMMITTED; 실제 V11 쌍 비교는 별도 gate; 사람 평가는 불필요 |
| 운영 PostgreSQL | `20261010_0051` migration 및 exact-head 검증 PASS | 새 비교 Workflow stage CHECK 적용이지 비교 control 발행이나 worker 실행이 아님 |
| 별도 CPU Conda | `/opt/eom/conda/envs/eom-embedding-experiment` 보호 snapshot 발행·승인된 격리 probe 및 전체 BGE 실험 PASS | 임베딩 성공은 풀이 전이·교육 품질의 증명이 아님 |
| CPU platform | `06134fcd91413a957ac3133db062dbcdd525ee15` wheel에서 비편집 설치 | d291 candidate와 1,361개 payload member가 일치함; source 표기는 원래 설치값 유지 |
| 최초 API build-only 후보 | `d2917ba448f21b86e7731d8477e802c658c2e106` | 역사적 후보로 보존; 현재 공유 배포와 동일시하지 않음 |

Component들이 같은 commit이어야 한다고 가정하지 않는다. 실제 파일·wheel·contract
호환성과 설치 provenance를 따로 기록한다. build-only 결과를 live release로 부르지 않는다.

### 원래 E5 결과의 same-key 게시 복구 — 2026-10-11 13:20 UTC

현재 `guiadmin` 인증으로 PREPARE/전체 AUTHORIZE/current-principal 검사를 거친 뒤,
기존 publisher가 원래 Job과 Artifact identity에 retained 결과를 게시했다.
`COMMITTED` receipt를 확인했으며 CPU/model 실행은 **0회**, 게시 호출은 **1회**다.

- execution: `embeddingexecution_125fe45683e34a2ea188e8ea65a990b0`.
- Job: `job_84bc2e74b708442580be243a5bb4f301`; 같은 idempotency key를 유지했다.
- Artifact: `artifact_7cdc94580e1a48b8ac22cefebab135e2`, revision
  `rev_fb45f587396e4c3a82cf656a5d8dcaf5`, member `result.json`.
- member raw SHA-256:
  `da68f546ab9cc9723463b4cbc785edafe9aec292a3d65bc8f5c309e5a3db649a`.
- result semantic SHA-256:
  `cc79373fb671bbe903ba9be602ae3ce6c42307c4355f5a178debf72c6206a664`.
- canonical manifest SHA-256:
  `66203d9895350fe36641bd1dde390720da583c37abb787123abac3e86f13b68b`.
- private recovery receipt: 기존 `owner-input-s9vek0xd/output.json`, raw SHA-256
  `daf23c1b3278f655749043a60da0a928a332662e2c3adeb9f7ce882b90c3894d`.
- 원래 publication source `68a648c2`와 현재 caller runtime `c8b29f67`을 분리했다.
  원래 input·result·실패 이력을 수정하지 않았다.

결과는 여전히 `INSUFFICIENT_ENCODING_COVERAGE`, benchmark `NOT_MEASURED`,
pair eligibility `BLOCKED_INSUFFICIENT_ENCODING_COVERAGE`다. 게시 복구를 원래 실행의
성공이나 실험 품질 PASS로 재해석하지 않는다. 긴 입력을 지원하는 BGE의 별도 successor
console을 준비했으며, 같은 520개·4 query·3 view의 실제 실행은 새 인증 대기다.
V11 control 발행·최대 두 쌍의 member 검증/replay와 최종 원문 대조는 아직 남아 있다.
Slack milestone: `devreport_f285775c8f7349919ea5e544dbbe5f81`.

### BGE 전체 520개 successor 실제 시작 — 2026-10-11 13:27 UTC

첫 BGE console 로그인은 `CONTROL_AUTHORIZATION_REQUIRED`로 종료됐다. 그 호출의
새 execution/CPU/게시 횟수는 모두 0이다. 새 실제 `guiadmin` 로그인은 통과했고,
명시적 `RUN_BGE_SUCCESSOR_EXPERIMENT` 후 현재 PREPARE/전체 AUTHORIZE를 거쳐
별도 실행 `embeddingexecution_d6b62c2fd7864efabf9f16c3aa947f9b`가 시작됐다.

- 실제 systemd 시작: `2026-10-11 13:26:58 UTC`; 확인 시 `activating/start`,
  MainPID `1312350`, InvocationID `bf89cd0d01624dc7aeb0aad150705f57`, NRestarts 0.
- 전용 `eom-embedding-experiment` identity, CPU quota 400%, MemoryMax 6 GiB,
  TimeoutStart 5400초. 현재 owner PID는 `1309462`(UID 990)다.
- 기존 520개 population·4 query·3 view·Graph/policy/recipe pin을 유지한다.
  모델은 승인된 BGE manifest, batch 1/threads 4로 명시적으로 분리했다.
- toy 기반 예상 3,845,894 ms(약 64.1분)는 추정값이며 전체 처리 실측이 아니다.
  실제 `MEASURED` 여부·정본 게시·V11 비교는 아직 PENDING이다.
- 원래 E5 부족 판정과 실패 이력은 보존한다. 문항/풀이보고서 재생성이나 자동 재시도는 없다.
  변경 없는 장기 실행 점검은 30분 간격이다.

### BGE 전체 실험 MEASURED / COMMITTED — 2026-10-11 13:55 UTC

같은 owner 대기 핸들의 종료 신호를 받고 실제 unit·parent·정식 게시 receipt를
확인했다. 임의 timeout을 실패로 보거나 새 실행을 재제출하지 않았다.

- execution: 위 `embeddingexecution_d6b62c2fd7864efabf9f16c3aa947f9b`.
- 실제 unit 종료: `2026-10-11 13:53:10 UTC`, `active/exited`, MainPID 0,
  Result success, ExecMainStatus 0, NRestarts 0. owner PID 1309462도 종료했다.
- `status=COMMITTED`, `result_status=MEASURED`, common profile **520/520**,
  encoded text **1560**. 기존 4 query·3 view와 원래 모집단/recipe/Graph/policy pin을 유지했다.
- 실측 encoding **1,559,484 ms**(25분 59.484초), process peak RSS **2,753,684 KiB**.
  별도 cgroup MemoryPeak는 759,586,816 bytes, CPUUsage는 5,841,114,674,000 ns다.
  process RSS와 cgroup accounting을 같은 메모리 지표로 해석하지 않는다.
- owner audit: PREPARE 1회/79,064 ms, 전체 AUTHORIZE 2회/237,032 ms,
  새 전체 READ 0회. 이 audit는 관측 metadata이며 영속 권한 증표가 아니다.
- CPU adapter/launch 각각 **1회**, publication **1회**. 무절단·무자동재시도이며
  원래 E5 부족 판정과 별도 toy 증거를 성공 결과로 덮어쓰지 않았다.
- request semantic SHA-256:
  `a246be6a722e82d0169ac3abb99a5fcff7dd559245a1fb1145fdef94b15a6b03`.
- result semantic SHA-256:
  `83f48dded66c6241b955f6ffc15ea504b5f9685b13fad63b50ce3a6833e4cb05`.
- Job: `job_6a03b3aac33b46b4ae82b66d05da2978`.
- Artifact: `artifact_0b04fa4b8c134853b65da0caf07c1785`, revision
  `rev_42e5834f068846e8acf891f767df6a3d`, member `result.json`, raw SHA-256
  `030a0e83923841341539ac9a9d93cc64ba98c834b1f09ab013a2cc942244b8a5`.
- canonical manifest SHA-256:
  `1da3494cb4d46010fd4b090ef61ec53cd1b40a470ab2b2fdae2ed67a9326a86f`.
- private successor input/output receipt raw SHA-256:
  `afd7563e4c60357fa300a89ca736862177523a21c5d831c5b6903afc8c4efec4` /
  `6946c7a06fd1e8f1a3b2d684b45904d11adca068e51cea0655bb8e4b0c80772c`.

V11 입력을 기존 보호된 도구·UID990 FD/O_EXCL 경계로 준비했다. local `manifest.json`
raw SHA는 `953c1bb2f0331096a52f2d795062081d0b60a0ac49f68e040344016e5c646c71`,
semantic SHA는 `933e2c729c6ad2fd1c777eb10421de6e99b119db0bec5e70d7b11be1ca92aaed`다.
이것은 **DRAFT_DATA_ONLY_NOT_AUTHORITY**이며 control 발행·모델 비교 완료 증거가 아니다.
fresh guiadmin 인증 후 공식 PREPARE/RELEASE와 최대 두 쌍의 실제 V11 비교,
MEMBER_VERIFIED 및 같은 key replay가 남아 있다. 근거 대응 가설과 교육 효과는 구분한다.
Slack milestone: `devreport_a95bc44d4e154b53b3158742fb84e09b`.

### V11 사전 점검 종료와 일회성 입력의 capacity schema 불일치 — 2026-10-11 17:05 UTC

기존 console의 로그인 거부와 이후 종료를 보존한다. 사용자 재입력 후 owner
PID1404179는 17:01 UTC에 `OWNER_COMPLETION_BOUNDARY_FAILED`로 종료했다.
공식 API는 `/auth/login` 1회와 `/auth/me` 5회 완료를 기록했다. PREPARE/RELEASE 메뉴의
사전 점검 완료 출력은 없었으며 control 게시·pair 요청·새 CPU 실행은 0이다.
generic 오류만으로 SQL·권한·실제 capacity 값을 단정하지 않는다.

독립 source 대조에서 **일회성 builder 입력의 명시적인 불일치**를 찾았다.
`capacity_2b2e003348f6759d4f780b4283dec6cd` /
`capacityrev_335b8a238f3755b9dc14d902598ee520`와 `sha256:6bac3c91…ba59cd3`는
`fixed-host:v1`이다. 기존 native producer와 bootstrap 회귀는 이 exact revision의
schema가 `worker-capacity-policy/1.0`임을 보여준다. 그러나 local draft에는 `1.3`을
기재했다. 이는 최신 정책을 선택해야 할 이유나 기존 guard를 완화할 근거가 아니다.

최소 수정은 **같은 ID/revision/hash에 맞는 schema 표기**를 별도의
`manifest.capacity-v1.json`에 기록하는 것이다. 이전 manifest·frozen console·실패
기록을 덮지 않는다. 모델·runtime·Graph·자료·recipe·두 쌍 예산은 그대로이며 새
DB/schema/queue나 core 배포가 필요하지 않다. O_EXCL/FD/SHA와 기존 owner의 exact
capacity/native model admission을 유지한다. 새 입력 생성·현재 실제 capacity 일치·
control 발행·pair 실행 여부는 각각 후속 실제 증거로 판정한다.

수정 builder는 raw SHA `ec542ab55b5d8e934627e06d43330c5fb1e2161301700b4348f6f35237770078`,
10,591 bytes다. schema와 별도 basename·설명 이외 AST는 보존됐다. root fresh 합성
테스트 6 PASS/3.77초, 기존 native pin·owner authorization·bootstrap 81 PASS/3.06초,
Ruff/format PASS이며 strict mypy 2파일 PASS도 확인했다. 기존 manifest 보존,
symlink/중복/race 거부·부분 실패 보존을 검증했다. 새 runtime/core 배포는 없다.

17:08 UTC에 기존 보호된 data-stage helper의 FD/SHA/O_EXCL 경계로 새 builder만
root 소유 0644 leaf에 복사하고 UID990가 새 private manifest를 생성했다. 이전 입력과
console은 변경하지 않았다. 새 raw SHA는
`81570550ce4ad16bc5cb08701243d6970f518be842f58c1adbb0d5d42621e8d6`, semantic SHA는
`9a8e990d21cd4a325b6f6b0ea85a98fc134de4f89c25f9ecfa96c9088f213f81`이다.
`DRAFT_DATA_ONLY_NOT_AUTHORITY`, publication/model 0이며 새 UID990 console PID1418086은
fresh Studio 로그인 입력 대기다. 실제 native equality/PREPARE/RELEASE/pair는 아직 미실행이다.

### 반복 로그인 요청 중단과 저장된 실험 결과의 관찰 — 2026-10-11 17:15 UTC

사용자가 반복 로그인 요청을 중단하도록 지시했다. 17:12 UTC에 입력 대기 중인
PID1418086을 중단했고 종료·TTY idle을 확인했다. 새 로그인 입력창, credential reset,
권한 대행이나 자동 로그인은 시작하지 않는다. 17:01 UTC의 실제 로그인 성공은
보존하지만 그 owner가 종료되면서 메모리의 인증 세션도 소멸했다. 지원된 bearer-FD/
in-memory session 재사용 경로는 있으나 현재 제공된 재사용 credential은 확인되지 않았다.
이는 사용자가 다시 잘못 입력했다는 판정이 아니다.

이미 인증·게시된 BGE 실험의 보존 request/result를 보호된 기존 parser와 UID990,
설치된 isolated interpreter로 검증하고 **작은 관측 metadata만** 집계했다.
새 corpus 조회·Graph 검색·모델 실행·control 게시·pair 제출은 각각 0회다.
관측은 `VALIDATED_RETAINED_METADATA_ONLY_NO_NEW_AUTHORIZATION`이며 결과의
`current_authorization=NOT_VERIFIED_BY_HARNESS`를 변경하지 않는다.

- 520개 모두 세 view에서 `ENCODABLE`; common pool 520, query 4, query/view 결과 12.
- 각 query에서 자기 자신을 제외한 후보 519개를 비교했고 저장된 순위는 view별 Top-8이다.
- encoding 1,559,484 ms, model load 3,493 ms, token measurement 536 ms.
  encoding requests started/completed 3/3, encoded texts 1,560이다.
- 새 임베딩을 돌리지 않고 저장된 Top-8과 **원래 request의** Graph 후보 순서를 대조했다.
  Graph 후보 목록은 query별 최대 64개이며 전체 519개 Graph 순위가 아니다.

| Query ordinal | 보존 Graph 후보 수 | Graph Top-8과 내용 view 중복 | 핵심 조건·추론 view 중복 | 메타데이터 view 중복 | 세 view Top-8 합집합 |
|---|---:|---:|---:|---:|---:|
| 1 | 64 | 2 | 1 | 2 | 14 |
| 2 | 46 | 4 | 2 | 2 | 15 |
| 3 | 55 | 2 | 0 | 1 | 19 |
| 4 | 63 | 1 | 2 | 1 | 18 |

내용/핵심 조건·추론, 내용/메타데이터, 핵심 조건·추론/메타데이터의 Top-8 중복 수는
각 query에서 순서대로 `5/4/4`, `4/4/5`, `1/3/2`, `2/2/3`이다.
관측 근거는 위 BGE request semantic SHA `a246be6a…a6b03`, result semantic SHA
`83f48dde…cb05`, canonical member raw SHA `030a0e83…44b8a5`의 exact closure다.

이는 **표현을 나누면 다른 후보가 나온다**는 제한적 관측이다. 4 query만의 결과이며,
서로 다른 후보가 실제로 유용하거나 임베딩이 Graph보다 우수하다는 증거는 아니다.
`SUPPLIED_NOT_REEXECUTED`, 교육 효과 `NOT_EVALUATED`를 유지한다. 실제 V11
PREPARE/RELEASE, 두 쌍의 CONCEPT/MATERIAL/CRUX 근거 설명·`MEMBER_VERIFIED`와
same-key replay는 미실행으로 남는다. 원문·520개 정본·Graph 경계와 실패 이력은 보존한다.

### 요청범위 불변 provenance 재사용의 실제 공유 배포 — 2026-10-11 08:23 UTC

- source `68a648c2`와 위 tree를 GitHub main에 반영했다. 새 source 경계는
  **559 PASS / 26.22초**, strict mypy 3파일, Ruff/format 5파일 및 diff 검사 PASS다.
  owner transaction-local reuse의 독립 검토도 PASS다. 같은 SQL transaction 안의
  성공한 불변 Artifact member와 PastExam decode만 재사용하며, 권한·Graph/policy·
  current source/lifecycle/lineage는 각 호출에서 다시 검증한다. 새 wire/DB migration/
  queue/dependency/timeout/retry 변경은 없다.
- 정상 build-only, fresh root-protected data stage, 별도 ADMIT을 각각 확인했다.
  stage는 `/var/lib/eom-release-operator-stage.68a648c2-W5QQur`다.
  context SHA는 `017752602263d5a095f44245cf2bcc26237a4f28c30c2d30a4d8ab1d247504ce`,
  protected source snapshot SHA는
  `8897a9e8afbe12ecc012de0cb36c48f078349e7513ae93e925c3126d64d01ca4`다.
  source archive SHA는
  `a372603d87f2dd53081f77d7801dcdc148c9c10598b6fb84a52842464dcce9dd`다.
- 배포 전 및 기존 8개 공유 서비스 정지 후 공식 worker/DB 및 HWPX owner
  quiescence를 확인했다. 기존 closed release operator의 PDF runtime, migration verify,
  API role, Catalog role, HWPX role, API isolation 여섯 callback이 모두 PASS다.
  migration `20261010_0051`, 보호 CPU runtime/model, worker 인증과 기존 queue는 유지한다.
- 정본 deployment record는
  `/var/lib/eom-api/deployments/68a648c293c2a0a0df441ba8607b1d58a02d08de.json`이며
  실제 배포 시각은 `2026-10-11T08:23:12.047329Z`다. installer가 재빌드한 실제 wheel
  raw SHA는 platform `b529b138ea5d99f0aa0306125f6e64878c2b47de66356b694d81f87a3f87b387`,
  API contracts `5c5cdce94f1996a9487c96ca91e5af2817a5127608013b01719b9aee6e04a255`,
  API `368d8ca3464f499011252bd4f018982d64055f5fda432e12c64d5b45605ed2c6`다.
  build-only의 ZIP raw SHA와 혼동하지 않는다.
- 기존 chat pin adapter로 exact predecessor `ab1d5b8c`에서만 새 pin으로 이동했다.
  API/Catalog/maintenance/workflow/HWPX/auth broker/chat worker/chat owner 8개 모두
  active/running/enabled/positive PID, API LIVE/READY, installed source/tree,
  Catalog inventory 295와 기존 chat slot READY를 확인했다. 새 모델 smoke는 없다.
- 같은 원래 private input/raw SHA와 execution ID를 받는 root-protected resume
  도구는 기존 SHA `82ab1c567eac053e9e1c26fe03207cd5cc2e02111829e03894d7a9d4e60f2fac`를
  유지한다. 08:24 UTC 현재 새 console은 fresh `guiadmin` 인증 대기다.
  실제 READ 성능·CPU embedding·최대 두 쌍 V11 비교/replay는 여전히 PENDING이다.
  이전 timeout을 성공으로 바꾸거나 새 execution으로 우회하지 않는다.

### V11 실행 정의의 별도 운영 등록 — 2026-10-11 08:32 UTC

배포의 config compile은 DB definition admission이 아니다. 기존 installed
`eomctl workflow definition admission`과 `list`를 read-only/10초 statement budget으로
조회한 결과 comparison 1.0/1.1 정의가 모두 없었다. 검토된 1.1 YAML만 기존
`eomctl workflow definition import`로 **한 번** 등록했다. 실행 주체는 기존 OS 운영자
`eom`(UID 1000)와 기존 credential/CLI 경계다. 새 grant나 root/worker identity 변경은
없고, `guiadmin` 인증·RBAC·사람 actor 감사가 수행됐다고 표현하지 않는다.

- definition: `wfdef_ff105c9d4997430b93b0788b54fcf5f9`.
- key/version: `item-inference-transfer-comparison@1.1.0`.
- canonical SHA: `a9c7e38151b7f0a0004069d23e60f8601c9717173bb672022ae075566844260e`.
- imported UTC: `2026-10-11T08:32:24.621383Z`.
- 별도 post-register admission 조회: protocol `workflow-role/1.30.0`,
  stored_active/admitted/accepts_new_work 모두 true, protocol error 없음,
  historical_instance_count 0.
- 이전 1.0은 미등록 그대로다. 전체 admission inventory가 consistent라고 주장하거나
  미사용 1.0을 새로 등록하지 않는다. released 1.0 schema/definition bytes는 보존한다.

처음 로컬 확인의 step 기대값은 agent 한 개만 세어 assertion이 실패했다. CLI의
`steps`는 agent와 terminal을 모두 센다. 기대값을 2로 바로잡아 fresh validation에서
정확한 key/version/hash와 compile PASS를 확인했다. 이는 무상태 검증기의 기대 오류이며
definition import 실패나 모델 실행이 아니다.

이 등록은 control PREPARE/RELEASE, native protocol 발행, 현재 capacity/model admission,
사용자 source 권한, CPU/Job/Artifact 결과를 대체하지 않는다. 해당 gate는 실제 사용자
인증과 기존 owner 경계에서 수행한다. PID `1045079`의 원래-input console은 08:33 UTC에
살아 있으며 `guiadmin` getpass 대기다. 원래 실험·입력·실패 기록은 변경하지 않았다.

### 동일 입력의 실제 재개와 비교 replay 도구 보완 — 2026-10-11 08:58 UTC

사용자의 실제 인증 뒤 installed `68a648c2`/`e9d3b88b`와 원래 input/execution을
확인하고 08:44:54 UTC에 `RUN_RETAINED_EXPERIMENT`를 **한 번** 실행했다.
08:55:54 UTC의 owner PID `1045079`는 살아 있었고 API의 공식 snapshot 경로에
해당 실행 이후 완료된 HTTP 요청 7건을 확인했다. 이때 고정 CPU unit은
inactive/dead, MainPID 0, InvocationID empty였다. 중간 HTTP 종료 기록을 전체
READ·AUTHORIZE·CPU 성공이나 phase별 최종 receipt로 확대하지 않는다.
실행이 진행 중이므로 동일 입력을 재제출하거나 서비스를 재배포하지 않았다.

실제 비교 전 검증 도구에서 별도 결함을 합성 재현했다. frozen V11 도구의
REPLAY 메뉴는 성공한 제출이 이미 저장한 `pair-N.command.json` 때문에 HTTP
호출 전에 거부됐다. 이는 운영의 idempotency 실패나 실제 모델 비교 실패가 아니다.
원본 도구 SHA `1844ac71bfe94695652fcc013dccf8ab22bb73285b75016d914938c9d37b6601`은
보존한다. 일회성 successor의 SHA는
`c3160ed80ef0e0c6e5e9cdb3891e8ada46ea1293c4958deba7325f7d16e9be46`이다.

보완은 명시적인 known-success replay leaf에 한정된다. 기존 selection/key와
저장 command를 검증하고 공식 endpoint를 동일 key로 정확히 한 번 호출한다.
반환된 immutable command가 기존 값과 완전히 같아야 하며 원본 bytes를 다시
확인하고 별도 witness를 O_EXCL로 저장한다. command 파일이 실제 없는 uncertain
submission만 기존 경로를 사용한다. 인증·검증·transport 실패에서 자동 retry,
새 identity, 기존 receipt overwrite를 하지 않는다. 기존 일반 제출·control·
source read·승인 경계와 runtime/protocol은 변경하지 않았다.

root fresh 합성 회귀는 frozen 45개와 successor 35개를 함께 실행한 **80 PASS /
7.03초**다. strict mypy/Ruff/format 두 파일과 두 독립 diff 검토도 PASS다. 이 도구는 아직
보호 staging·actual 실행 전이다. 합성 replay PASS를 실제 worker 결과나 운영
replay PASS로 표시하지 않는다. 최초 설계의 실제 CPU/두 쌍 비교·최종 대조 gate는
계속 남으며, 사람 평가·추가 GUI는 새 완료 조건이 아니다.

### 원래 실행의 terminal 관측과 실제 모델 적합성 — 2026-10-11 09:44 UTC

08:44:54 UTC에 시작한 동일 실행의 owner는 09:33 UTC경 종료됐다. 정식 게시
경계에서 `INFERENCE_EXPERIMENT_COMMIT_UNCERTAIN`가 반환됐으며, CPU unit의
exit 0을 벡터 계산 성공이나 정본 Artifact commit으로 해석하지 않는다.

- 최종 snapshot audit: PREPARE 1회 / 83,887 ms, READ 33회 / 2,668,388 ms,
  AUTHORIZE 1회 / 119,212 ms. 누적 canonical response는 11,325,674 bytes다.
  audit chain SHA는 `35b19779d9f7691ec9caa44375e90e7505e3dc62e33c85b3239ed29a4f681978`이다.
- 고정 CPU unit의 InvocationID는 `737787b8259347d6862e26d058c24d20`이며,
  09:31:11 UTC에 active/exited 상태가 됐다. Result success, ExecMainStatus 0,
  MainPID 0, NRestarts 0을 별도로 확인했다. owner의 CPU adapter 호출은 1회다.
- 기존 Orchestrator 소유 DB의 read-only exact-key 조회에서는
  `job_84bc2e74b708442580be243a5bb4f301`이 CREATED였다. planned Artifact는
  `artifact_7cdc94580e1a48b8ac22cefebab135e2` /
  `rev_fb45f587396e4c3a82cf656a5d8dcaf5`이고, 정본 Artifact/Revision row는 없었다.
  DB row를 수정하거나 실패를 성공으로 바꾸지 않았다.
- 일회성 caller가 `env -i`에서 `EOM_STAGING_ROOT`를 전달하지 않아 publisher의
  기본 `/srv/eom/staging`을 선택했다. 이 경로는 eom:eom 0750이고 실제 caller
  UID 990/GID 1000에는 쓰기 권한이 없다. 기존 운영 runner의 지원된 설정인
  `/var/lib/eom-workflow-runner/orchestrator-staging`은 실제 caller가 쓸 수 있다.
  공유 staging 권한을 넓히거나 runtime/state-machine을 변경하지 않는다.

09:42–09:44 UTC에 보호된 installed Python `-I -B`, 실제 UID 990으로 **읽기만**
수행해 원래 input SHA와 exact request/result/schema/canonical SHA, 모델·Graph·policy·
520 population·4 queries·recipe·budget 및 local completion/publication bytes를 확인했다.
이 진단의 CPU/DB/NAS 호출은 모두 0이다. completion marker는 로컬 검증 증거이며
정본 commit 영수증이 아니다.

실제 결과는 **INSUFFICIENT_ENCODING_COVERAGE**다.

| View | ENCODABLE | TOKEN_OVERFLOW | token median | p95 | maximum |
|---|---:|---:|---:|---:|---:|
| CONTENT_ONLY | 519 | 1 | 186 | 342 | 571 |
| CONCRETE_FACETS | 3 | 517 | 844 | 1,081 | 1,330 |
| METADATA_ONLY | 519 | 1 | 207 | 353 | 536 |

- 세 view의 공통 profile은 3개뿐이고 선택한 4 query는 모두 공통 집합 밖이었다.
  query result는 0개다. 모델 loading 2,612 ms, token measurement 225 ms,
  peak RSS 874,008 KiB; encoding requests/texts와 encoding time은 모두 0이다.
  따라서 **tokenizer/model load는 실행됐지만 실제 embedding forward는 실행되지 않았다**.
- request SHA: `cadf64d4a91aad119f4492846db08bfd633fa7c5984fc7a2a46af9aeff20bbe2`.
  result semantic SHA: `cc79373fb671bbe903ba9be602ae3ce6c42307c4355f5a178debf72c6206a664`.
  canonical publication raw SHA:
  `da68f546ab9cc9723463b4cbc785edafe9aec292a3d65bc8f5c309e5a3db649a`, 757,224 bytes.
  원래 result.created_at은 `2026-10-11T09:31:07.848194Z`다.

원래 execution/model/spec/request/result/실패 이력은 보존한다. 새 최소 복구는
완료된 로컬 결과 검증 → fresh 실제 사용자 PREPARE와 exact header/index 대조 →
기존 `reauthorize_staged_experiment`의 전체 현재 population AUTHORIZE → 동일 key,
같은 source commit/생성 시각/member로 기존 publisher를 통한 게시다. CPU 재호출,
33 READ 반복, 새 identity로 기존 실패 우회, DB 직접 UPDATE는 하지 않는다.
게시가 성공해도 결과의 INSUFFICIENT를 MEASURED로 바꾸지 않는다.

이 발견 때문에 실제 벡터 후보와 두 쌍의 착상 비교는 여전히 미완료다. 현재 E5의
512-token pin을 늘려 표시하거나 조건·단위·부정을 잘라 통과시키지 않는다.
원래 설계의 내용을 보존하는 모델 적합성 보완이 필요하다. 이미 계약이 지원하는
긴 입력용 로컬 모델의 안전한 snapshot과 resource fit을 조사하되, 조사만으로
설치/활성화/후속 실험 PASS를 주장하지 않는다. 의미 있는 모델 변경은 별도 successor
실험이지 원래 실행의 retry가 아니며, 같은 520/4-query/3-view recipe를 유지한다.
새 framework·검색 엔진·ANN·GUI·사람 평가를 추가하지 않는다.

### 모델 successor 준비 — 2026-10-11 10:03 UTC

기존 입력을 자르지 않는 BGE-M3 후보의 고정 upstream 7개 파일을 비root 전용
acquisition으로 받아 member SHA/bytes와 manifest를 검증했다. process exit 0이다.
정확한 revision·member pins·manifest·runtime versions는
[모델 fit 기록](ITEM_INFERENCE_TRANSFER_MODEL_FIT.md)에 있다. 이는 보호 snapshot
입장이나 모델 load/forward, 실제 corpus MEASURED 판정이 아니다.

원래 INSUFFICIENT 결과의 동일-key 게시 복구는 34개 fresh fake tests와 독립 source
리뷰를 통과했으며 보호된 UID 990 콘솔을 준비했다. 첫 로그인은
CONTROL_AUTHORIZATION_REQUIRED로 거부됐다. publication/CPU 호출은 0이고 DB 상태나
실패 이력은 변경하지 않았다. 이후 실제 인증과 결과는 아래 별도 기록으로 구분한다.

### 동일-key 게시 복구의 인가 시간 제한 — 2026-10-11 10:08 UTC

두 번째 fresh guiadmin 로그인은 정상 통과했다. 원래 Job의 CREATED 상태와 로컬
request/result pins를 확인한 뒤 10:05:15 UTC에 RECOVER_RETAINED_PUBLICATION을
명시적으로 한 번 선택했다. PREPARE `req_7b57014b89f8738039db197454a533d5`는
10:06:41.390111 UTC에 80,167.603 ms로 완료됐고 원래 header/index와 일치했다.
전체 현재 population AUTHORIZE `req_56b00dbc0f3bc1bb834bd2ea45c91432`는
10:08:44.316434 UTC에 120,109.795 ms 뒤
INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE로 종료됐다. 게시와 CPU 호출은 0이며
기존 failed/INSUFFICIENT 기록은 보존했다. 인증 실패로 재분류하지 않는다.

기존 Catalog response budget와 owner HTTP timeout이 모두 120초이며 앞선 동일
AUTHORIZE는 119,212 ms였다는 사실을 확인했다. 현재 실패의 내부 예외를 직접
관측하지는 않았으므로 deadline cliff와 강하게 일치하는 측정으로만 기록한다.
기존 경계 안의 작은 보완은 검증된 typed phase로만 선택하는 고정 timing map이다.
AUTHORIZE는 Catalog 300초/외부 HTTP 330초로 분리하고 PREPARE/READ/일반 HTTP는
기존 120초를 유지한다. 권한·wire/schema·출처 검증·자동 retry는 바꾸지 않는다.
fake 125초 응답 재현과 관련 8 suite 310 PASS, strict 5파일/Ruff/format/diff 및
독립 source 리뷰 PASS다. 이 시점은 source 검증이며 실제 배포나 복구 PASS가 아니다.

### 보호 모델 입장 — 2026-10-11 10:12 UTC

독립 검토된 model-only helper를 root 소유 0400으로 staging하고 SHA
fb8db49658483c0efcc325b0c4c8f150234ec51b2c2893066bf42c104e1180bb를 확인했다.
보호된 CPU interpreter의 -I -S -B 실행으로 exact BGE member/manifest를
no-clobber admission했다. 실제 EMBEDDING_MODEL_ONLY_ADMISSION=PASS,
RUNTIME_AND_HISTORY=UNCHANGED를 확인했다. 기존 CPU wheel 06134fcd9, E5 snapshot,
실행 이력과 인증은 유지했다. BGE unit/polkit 설치, 실제 load/forward/성능 측정,
520개 successor와 V11 pair는 아직 실행하지 않았다.

### 긴 입력 모델 경계와 인가 timing의 실제 공유 배포 — 2026-10-11 10:27 UTC

- source `72f01147`/위 tree의 정상 build-only → root-private data stage → 별도 ADMIT →
  정상 installer/verify를 각각 확인했다. stage는
  `/var/lib/eom-release-operator-stage.72f01147-60bmG5`, context SHA는
  `38cb51a005101b67216511b85a6bce4c71acab70b7dd5a4242f8dadd2b7e4fce`,
  보호 source snapshot SHA는
  `0078a1591fd2a70ccc0e576af23be469031a17a29f07268b3362764597fe2a58`다.
- 배포 전 및 8개 공유 서비스 정지 후 공식 owner별 quiescence PASS다. 여섯 기존
  release callback PASS, migration `20261010_0051` 유지. 옛 API 프로세스 종료는
  실제 PID 0으로 확인했으며 이전 read-only AUTHORIZE가 완주했다고 추측하지 않는다.
- 정본 deployment record는
  `/var/lib/eom-api/deployments/72f01147c4a3bb8c79e73bed24dc893ac69672a1.json`이다.
  installer가 다시 만든 실제 wheel raw SHA: platform
  `440cf5e29de91a4f52b04fc7b7592b4142bc4cb4ce1daa264935bdcdbb5bc076`,
  API contracts `09b87c2f983b054af2e0a797f685cf06912b58628ae2790a85aead4708ff1e9e`,
  API `efc60085648107d5862c23914071bd47b624768548666ca251a03ab7d459b930`.
  build-only ZIP SHA와 구별한다. 기존 chat pin adapter로 exact 68a648c2 predecessor만
  갱신했다. 10:27:11 UTC에 8개 서비스와 API LIVE/READY·installed source/tree PASS다.
- BGE fixed unit의 6 GiB/1800초 template SHA
  `55c70d9b3f115c7c6c3b869e1730922edf69d1d45d905a5e5053a268fea315a3` 및
  고정 polkit SHA `589f0c9258bacf17e4d3cefe3aba49c313c6733299dde196aaccf1662c7f985c`
  설치·effective sandbox 검증 PASS다. E5/probe/prepare bytes와 원래 실행 InvocationID,
  보호 CPU source 06134fcd9·model snapshot·실패/Job 이력은 보존했다.
- root fresh 관련 9 suite 443 PASS, strict/Ruff/format PASS다. 첫 pytest invocation의
  PYTHONPATH 누락 9 collection error를 바로잡은 후 위 결과를 얻었다. 일회성 도구의
  fake tests와 source PASS를 실제 게시·전체 corpus·V11 성공으로 확대하지 않는다.

### 실제 짧은 CPU 벡터 실측과 전체 처리시간 보완 — 2026-10-11 10:29 UTC

공식 UID 990 owner → 고정 격리 CPU adapter를 통해 합성 6 profile/3 view/3 query를
한 번 실행했다. 자료 권한이나 corpus 적합성 증거를 만들기 위한 입력이 아니다.

- Execution: `embeddingexecution_321ec70a88c947ddb2e859d8c0935763`.
  InvocationID `650a32436e9140838857fdc41a34b40c`, terminal active/exited,
  MainPID 0, Result success/ExecMainStatus 0, retry 0.
- 실제 result `MEASURED`, common profiles 6, requested/encoded texts 18,
  encoding requests started/completed 3/3, query result 3.
  모든 입력이 ENCODABLE이며 token 범위 51–1,599다.
- 모델 load 3,527 ms, token measurement 10 ms, encoding 44,325 ms,
  Linux peak RSS 2,486,848 KiB, owner launcher 52,912 ms다.
  cgroup MemoryPeak 1,222,045,696 bytes는 Linux process RSS와 다른 측정이다.
- request semantic SHA `00038b74b8dad142715e55bfdb78a4915f23cec1ea058b0fd59e6f9aeb46cc08`,
  result semantic SHA `d7004a00f91714836f57115cc22ce5df5e0625a4318d8fdcbf4d41fcb61377a4`,
  canonical member raw SHA `166e7c60467485ca2f96f7b06c1df7d7c4d1e59e89a4280de56555f79a97209f`.
  로컬 결과는 기존 owner workspace의 해당 execution `publication-result.json`이다.
  정본 NAS 게시·corpus fit·교육 품질·production activation은 NOT_PERFORMED/NOT_EVALUATED다.
- 18개 실측을 520×3=1,560 text로 단순 환산한 proxy는
  `3527 + ceil((44325+10)×1560/18) = 3,845,894 ms`(약 64분)다.
  전체 실제 소요시간이나 deadline 통과를 보장하는 예측은 아니다.
  기존 30분 한도에는 맞지 않으므로 새 입력을 자르거나 목표를 줄이지 않는다.

이에 BGE에만 fixed 5,400초(90분)를 적용하는 최소 source 보완을 검증했다.
E5 1,800초, BGE 6 GiB/400%/4 threads/재시작 금지는 유지한다. 새 template SHA는
`d54b75b04619490b095f529086b3c2169c87901016871152df52cab5f4183454`이며,
effective TimeoutStartUSec도 검증한다. 기존 측정 계약의 24시간 상한을 변경하지 않는다.
root fresh CPU 3 suite와 새 console 회귀는 319 PASS/4.21초, strict 3파일/Ruff/format/diff
PASS다. 첫 source PYTHONPATH 누락의 3 collection error는 설정을 바로잡고 재검증했다.
이 시각은 새 90분 profile의
소스 검증이며 아직 운영 적용 전이다. 과거 toy의 30분/55c7 pin·bytes·result는
그대로 두고, 미래 successor execution의 새 resource pin과 분리한다.
원래 동일-key 게시 복구, 실제 520개 BGE 실험, 최대 두 쌍 V11/replay·최종 설계 대조는 PENDING이다.

### BGE-only 90분 profile의 실제 호환 배포 — 2026-10-11 10:45 UTC

- source `c8b29f67`/위 tree를 GitHub에 반영한 clean 후보에서 정상 build-only PASS,
  fresh root-private data-only stage 및 별도 ADMIT PASS를 확인했다.
  stage `/var/lib/eom-release-operator-stage.c8b29f67-S3sryf`, context SHA
  `fd5039c56c053ac013e1eda1868c1040ac0bc65ceabcc6326cd657f04f5efaec`,
  source snapshot SHA `013fc01b7ffc47891d749f2ddaac6307dd85deda5b2e0a2648df7a6d20dbdee0`,
  archive SHA `cc88f9f654a4f61cd3b038aaaef4153c12ce1bc2b2a600d09aa6fff58cf05478`.
- 배포 전 및 8개 서비스 정지 후 이전 source72 owner별 quiescence PASS다.
  정상 installer/verify의 기존 여섯 release callback과 installed source/tree PASS,
  migration `20261010_0051`은 유지했다. 정본 설치 기록은
  `/var/lib/eom-api/deployments/c8b29f67b523744049c56a12bcdef376b7aef5f5.json`이다.
- 기존 chat source pin adapter의 exact predecessor72→c8만 갱신했다.
  8개 서비스 복구 PASS, 10:45:27 UTC API LIVE/READY PASS다.
  worker 인증·모델·RAG policy·queue·CPU06134 runtime·GPU 권한은 바꾸지 않았다.
- 과거 BGE template55c7를 root-private rollback member로 보존한 뒤 새 d54b75 template만
  설치하고 daemon-reload했다. updated protected verifier의 effective BGE 90분/
  E5·probe 30분/prepare 30초/sandbox PASS다. 원 E5 InvocationID7377와 과거 toy650a는
  그대로이며 MainPID0이다. 과거 실행을 재시작/reset하거나 새 timeout으로 재해석하지 않았다.
- 실제 toy request/result만 읽은 presentation prerequisite는
  `.../embeddingexecution_321ec70a88c947ddb2e859d8c0935763/bge-probe.json`, raw SHA
  `9783bfaa0b4da8470af822efb68ad9449f10cbd4231c76d09f227dfe99f6f783`으로 O_EXCL 저장했다.
  모델/인가/DB/NAS 호출 0이며 권한 토큰이나 전체 corpus PASS가 아니다.
  원 30분 proof와 미래 90분 execution resource metadata는 별개다.
- 추가 일회성 materializer·현재 caller용 same-key recovery·predecessor quiescence의
  root fresh fake regressions 39 PASS/11.84초다. 기존 도구·receipt bytes는 보존했다.
  10:46 UTC 새 protected recovery caller는 실제 `guiadmin` getpass 대기다.
  원래 결과 게시·520 BGE successor·두 쌍 V11/replay는 아직 PENDING이다.
- BGE successor의 batch1/원래 입력 pointer를 기존 V11 presentation에 연결하는 별도
  일회성 도구를 source 검증했다. 원래 V11/replay 도구와 BGE receipt는 변경하지 않고,
  same520 scope/entries/query4/Graph baseline/recipe·원/새 결과 hash·actual actor·
  정본 member closure를 확인한다. 공식 control/source authorization/submission/replay
  함수는 불변이다. root fresh 27 fake PASS/24.03초, strict2/Ruff/format PASS다.
  실제 보호 staging·control 발행·비교 제출은 아직 하지 않았다.

### 세 축 비교와 owner refresh의 실제 공유 배포 — 19:12 UTC

- GitHub에 `64f5f31e` 및 후속 `ab1d5b8c`를 반영했다. 앞 후보의 수기 Catalog inventory
  누락으로 거절된 정상 build는 보존하며, successor의 정상 build-only는 PASS다.
- 당시 실제 source/tree는 `ab1d5b8c`/`f134dea4`다. source archive SHA는
  `831f3570eac07a13cd7dac02d2e67925678fd3590eddbb6263c1f4bae127a5e8`,
  보호 source snapshot SHA는
  `a68ab45e1b2fef8bdac2be4bb19ca786be37bbb1b1ae16ea32ea49d67288848d`다.
- data-only stage와 별도 ADMIT을 검증한 뒤 기존 closed release operator를 사용했다.
  context SHA는 `69656ed72e08be42f917594528a73554710e8ff4173e011b194a8a0b38ab224d`다.
  보호 runtime byte-tree와 launcher/helper는 이전 승인값 그대로다.
- 배포 전 및 8개 shared consumer stop 뒤 지원된 worker/DB quiescence PASS,
  workflow command/API processing/HWPX item/exam active count 모두 0이었다.
  callback은 PDF_RUNTIME_VERIFY, MIGRATION_VERIFY, API_ROLE_BOOTSTRAP,
  CATALOG_ROLE_RECONCILE, HWPX_ROLE_RECONCILE, API_ISOLATION_VERIFY의 여섯 개 모두 PASS다.
  migration `20261010_0051`은 변경하지 않았다.
- 정본 배포 record는
  `/var/lib/eom-api/deployments/ab1d5b8c3205b1fcad63e6b1e72246b490936f0a.json`이며
  시각은 `2026-10-10T19:12:08.407502Z`다. 정상 installer가 다시 만든 설치 wheel raw SHA는
  platform `971d549e5c07a6b68544e1e2a8ca38c33015189582150d65647a94e33e569b3d`,
  API contracts `d31d6dec8e632cb73ab0de8d3205c0e1560c7e6683d2a69b9c1bdc4b4f08f89f`,
  API `4ed3d470932e433b0969489868f9d2d72da8413c6f4ec1d7126e9a7a1fd7aa08`다.
  build-only ZIP raw SHA와 실제 설치 wheel SHA를 동일시하지 않는다.
- 기존 public chat release-pin adapter로 정확한 predecessor `f12fb971`에서만
  nonsecret pin을 변경했다. worker 인증·모델·RAG 정책·unit·대화 이력은 그대로다.
  API/Catalog/maintenance/workflow/HWPX/auth broker/chat worker/chat owner 8개 모두
  active/running/enabled로 복구했고 API LIVE/READY, installed source/tree, Catalog 295개
  public inventory, 전용 기존 chat slot READY를 확인했다. smoke 중 모델 호출은 0이다.
- 후속 source 경계는 291 PASS, strict 6파일/Ruff/format/Bash/diff PASS다. 같은 원본 입력을
  재개하는 일회성 도구는 합성 51 PASS와 전체 독립 읽기 검토 PASS이며 root-protected
  사본 SHA `82ab1c567eac053e9e1c26fe03207cd5cc2e02111829e03894d7a9d4e60f2fac`를 확인했다.
  V11 pair-completion 도구는 actual resume provenance shape를 맞춘 뒤 합성 45 PASS,
  strict/Ruff/format과 두 독립 검토 PASS다. 이런 합성 결과를 actual model PASS로 부르지 않는다.

원래 private input raw SHA `7dd0fba98ac3cf61d32a5bdf47f48a72e6c9132dd19ab33adefd387ff0d2a775`,
execution `embeddingexecution_125fe45683e34a2ea188e8ea65a990b0`는 그대로 보존한다.
위 19:12 배포 관측 당시 보호된 console은 fresh `guiadmin` 인증 대기였다.
그 이후의 실제 조회는 아래 별도 실행 관측에 기록한다. 자동 재시도·새 execution·
DB 상태 초기화·사람 점수표는 없다.

### 동일 입력의 실제 재개와 첫 READ timeout — 2026-10-11

사용자 인증 뒤 실제 `/me`와 installed `ab1d5b8c`/`f134dea4`를 확인하고,
07:56:14 UTC에 `RUN_RETAINED_EXPERIMENT`를 정확히 한 번 실행했다.
원래 input SHA·execution·experiment·Graph/policy·520 모집단·4 query·예산은 불변이다.

- 공식 PREPARE 1회: owner 관측 85,908 ms. API request
  `req_7c3f3e1139407128e92d21f25f5b0242`는 07:57:39.640282 UTC에
  85,614.423 ms로 종료됐다.
- 공식 READ 1회: owner 관측 120,090 ms. API request
  `req_5cd57042262745f4e19809bde4b08995`는 07:59:40.203297 UTC에
  120,074.701 ms로 종료됐다. console은 `SUPPORTED_EXECUTION` / `READ`의
  `INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE`로 terminal 실패했다.
- AUTHORIZE 0회, CPU adapter 호출 0회, CPU launch 0회, pair submission 0회다.
  새 execution 생성·원래 입력 재작성·자동 retry는 없으며 실패 이력은 보존한다.
- 성공적으로 반환된 PREPARE canonical response는 374,467 bytes다. READ의 실제
  응답 크기·내부 성공 여부는 UNKNOWN이다. 기존 f12 READ의 `FROZEN_MODEL` 오류와
  이번 timeout을 동일 원인이라고 단정하지 않는다.
- 08:00경과 08:06경 Catalog의 동일 MainPID `644380`과 두 기존 thread를 확인했다.
  두 thread 시작은 각각 2026-10-10 19:12:01/19:12:03 UTC다. 동기 요청별 handler가
  남아 있지 않은 `SERVER_READ_NOT_ACTIVE` 증거이지, 해당 READ 성공이나 전체
  Workflow/lease quiescence를 증명하는 것은 아니다.
- 고정 `eom-embedding-experiment@embeddingexecution_125fe45683e34a2ea188e8ea65a990b0`
  unit은 loaded / inactive / dead, MainPID 0, InvocationID empty였다.

기존 adaptive split은 `INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED`에서만 동작한다.
이번 UNAVAILABLE를 split 신호나 서버 미처리로 재해석하지 않는다. timeout 확대나
재제출보다 기존 공식 source-resolution의 요청범위 중복 비용을 먼저 점검한다.
실제 CPU embedding·세 축 pair·replay 증거는 여전히 PENDING이며, 사람 평가는
현재 완료 조건이 아니다.

### 후속 V11 입력의 소스 핀 확인 — 인증 전 읽기 전용

설치된 `ab1d5b8c`와 아래 config bytes가 동일함을 Git revision diff로 확인했다.
공개 compiler의 definition canonical SHA는
`a9c7e38151b7f0a0004069d23e60f8601c9717173bb672022ae075566844260e`다.
`platform.md` raw SHA는
`0c0c01042bc357514b547dea323d53f9111bf0d062da3cfbbdf029ebe0f6fcc9` / 2,103 bytes,
`transfer-rubric.md`는
`e6fff04f7803c7858d62ea9d1013e4cced62f6551fbac4ab6d5ec87614dcacea` / 4,692 bytes다.
YAML 원시 SHA를 definition canonical SHA 대신 쓰지 않는다.

기존 검토된 SUPPORT config의 모델 후보는 `gpt-5.6-terra / medium`이다.
이는 역사적 candidate value이며 현재 사용 가능·구독 자격·새 comparison 목적의
모델 admission 증거는 아니다. 공식 V11 PREPARE의 실제 capacity/model freshness
검증이 필요한 상태로 둔다. 이 확인에서 새 manifest·rubric/control identity 발급,
control 발행·모델 호출·CPU 재실행은 하지 않았다.

## 보호 CPU 설치의 실제 증거

2026-10-10 15:08 UTC경 보호 snapshot·model·고정 unit·polkit 설치가 완료됐다.

- 고정 runtime의 독립 byte-tree SHA-256:
  `d0dcd26e841ef583ead382b19269f559a3263a35ce809d34c6308bfe0399ed73`.
- 전용 CPU identity: UID 979 / GID 976, private group만 사용, nologin.
- 모델: `intfloat/multilingual-e5-small`, upstream commit
  `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
- local model/revision:
  `embeddingmodel_f30c692a99476867e96f3567ae266036` /
  `embeddingmodelrev_82eace0bd4ceeacb31ced2e8e40bc293`.
- semantic manifest SHA-256:
  `f106f8df1ca01062a3900fa65f4c235d278294c34a113efe1cc1934432d0d9eb`.
- root-private phase receipt:
  `/opt/eom/.embedding-install-n6SfouPM/phase-receipt`.
- 원래 developer tree는
  `/opt/eom/conda/envs/.embedding-prepublication-.embedding-install-n6SfouPM`에 보존했다.
  이 원래 tree는 보호 실행 환경이 아니며 root로 실행하지 않는다.

새 inode에 복사한 뒤 hash/type/mode/link와 wheel payload를 검증하고 고정 prefix로
발행했다. mutable interpreter·pip를 root로 실행하는 방식이나 광범위한 기존 runtime
소유권 변경은 사용하지 않았다. 설치 자체는 모델 load/forward를 실행하지 않는다.

## No-forward preflight에서 발견한 실제 차이

1. 처음의 unprivileged `pkcheck --detail` 호출은 trusted caller 조건 때문에 거절됐다.
   정책을 확대하지 않고 root caller가 실제 별도 kernel-validated subject의
   `PID,starttime,UID`를 확인하는 adapter로 수정했다. 실제 여섯 allow/deny case는 PASS다.
2. installed unit/polkit bytes와 runtime 경로 검증은 PASS다. 그러나 `systemctl show`가
   빈 structured `ExecStartPre`/`ExecStartPost`를 출력하지 않는 실제 serialization 차이로
   strict parser가 실행 전에 거절했다. `--all`도 이 host에서는 빈 배열을 출력하지 않았다.
   나머지 필수 property·exact FragmentPath·drop-in·reload 검증은 유지하면서 이 차이를
   재현 테스트로 보완했다. unit·권한·sandbox 정책을 바꾸는 해결이 아니다.
   수정 driver SHA-256은
   `6333f2aa7b3456c4d5433ca91afa83688018257f8a44f1de4e8fb90a378be477`이며
   root-private `/var/lib/eom-embedding-verifier.XeVJgr8B/verify.py`에서 실행했다.

위 두 preflight 거절 시점의 probe는 `MainPID=0`, `InvocationID` 없음,
inactive/dead였고 실행하지 않았다.

### 최초 실제 no-forward probe와 권한 수정

수정 preflight 뒤 최초 실제 probe가 15:20:29–15:20:31 UTC에 실행됐지만 exit 1로
종료했다. InvocationID는 `5c4878814d5f42a3b28fc91049a7fe36`이다. 모델 load/forward를
호출하지 않는 고정 검증 프로그램이므로 이것을 임베딩 실험이나 worker 비교로 세지 않는다.

root와 실제 전용 CPU UID로 지원된 runtime/model 검증을 따로 조회해 원인을 분류했다.
runtime/RECORD는 양쪽 PASS였지만 model snapshot은 root PASS / CPU `PermissionError`였다.
metadata에서 고정 모델 논리 ID 부모만 root:976:0700임을 확인했다. installer의
`mkdir(mode=0750)`에 umask 077이 적용되고 explicit chmod가 없어 private group traversal이
누락된 것이다. revision은 0750, manifest는 0440으로 의도한 값이었다.

독립 model manifest/member hash 검증 뒤 해당 부모의 retained FD와 정확 UID/GID/inode를
검사하고 **그 부모만 0700 → 0750**으로 복원했다. 소유자·group·모델 bytes·기존 runtime·다른
서비스 권한은 바꾸지 않았다. source installer에 실제 umask 회귀 테스트를 보강했다.
수정 뒤 실제 CPU UID로 동일 model snapshot/hash read를 다시 확인해 PASS였다.
이는 outside-sandbox read 검증이며 전체 격리 probe PASS의 대체 증거는 아니다.

사용자가 기록 보존 후 no-forward 검증 **1회** 재실행을 명시적으로 승인했다. 원래 실패
observation·확인된 원인·수정·승인 한도를 root-owned 0400 receipt로 먼저 보존했다.

- receipt: `/var/lib/eom-embedding-probe-recovery.vNOQNB0B/first-failed-observation.json`.
- receipt SHA-256: `2397e9df2e0bb279bc7a249313e4621b806ac02ef141447dc3becfdcb469c5ab`.

정확한 기존 failed InvocationID·terminal 상태·PID 0·고정 unit/polkit/runtime/model pins와
실제 권한 범위를 재확인한 뒤, 승인된 fixed no-forward probe만 reset-failed했다. 정상
garbage collection 뒤 fresh 상태를 확인하고 동일 reviewed driver의 기존 첫 실행 guard를
그대로 사용해 **한 번** 실행했다. generic retry, 새 identity, main experiment 재실행이나
과거 실패의 성공 재해석은 사용하지 않았다.

실제 재검증은 **PASS**다. 새 InvocationID는 `1f3c503f4ed2400b9b62fa58a422259e`,
상태는 active/exited, MainPID 0, Result success, ExecMainStatus 0다. 동일 policy의 전후
일치와 설치/RECORD/model hash, 실제 identity/network/file/socket negative 검증이 통과했다.
model load/forward 0이다. 첫 실패 journal과 위 receipt를 보존하며 자동 재실행은 없다.

실제 journal에서도 `IDENTITY=PASS`, `RUNTIME_RECORD=PASS`, `NETWORK=PASS`,
`MODEL_SNAPSHOT=PASS`, `nas=DENIED`, `repository=DENIED`,
`postgres=ABSENT_IN_SANDBOX`, `docker=DENIED`, `MODEL_FORWARD_COUNT=0`을 확인했다.

### 보호 CPU와 후속 후보의 byte 호환성

`16798a34d9ab2b38844724a645645377f2e9f1f4`의 build-only wheel을 실제 설치 CPU와
읽기 전용으로 비교했다. 수치 계산·정적 EOM import closure와 Catalog schema resources
345/345, handoff/launch closure 118/118, owner execution/invocation/staging/artifacts
4/4 member가 일치했다. 수치 group의 sorted member/hash/equality canonical JSON hash는
`0d240e8bfaf7dc6933348212c51bcf417f456450f2a16f2913bc6700cca2c65b`, handoff group은
`72f70fe6cc4e29ddce09ebf22c9474fbf3b6ee969a0ca1b0cb103b323784bd61`이다.

후속 owner HTTP 비교 제출/조회, verifier의 추가 진단, installation preflight 세 모듈은
다르다. 전체 CPU platform이 최신이라고 주장하지 않는다. 실제 HTTP/control/비교 owner는
새 호환 공유 runtime을 사용하고 CPU는 동일한 수치/handoff 경계만 사용한다. 이 검사는
모델·service·probe를 실행하지 않았다.

최종 `ad3ed8ca` 후보도 원래 보호 CPU `06134fcd` 설치와 data-only로 다시 대조했다.
정적 AST EOM import와 Catalog JSON resource를 포함한 수치 경계는 345/345,
launch/handoff 경계는 118/118 member 일치이며 missing/diff는 모두 0이다.
새 explicit recipe는 member 순으로 정렬한
`{member,candidate_sha256,installed_sha256,equal}` rows를 JSON `sort_keys=True`,
separators `(',', ':')`, UTF-8로 hash한다. 수치 경계 manifest SHA는
`0c4fd662de7c651ae1413c5411d3d6850969b146e1bdc1e463fe7899adf280a1`,
launch 경계는 `7c086848862e8ca638f95eb8cb0916e12e12ad3605e9ba3ca98b18b7889f71e8`이다.
이 recipe의 hash를 위 이전 관측 recipe의 hash와 동일시하지 않는다.
CPU 전체 package의 최신화·실제 추론·실제 권한 인가를 증명하는 검사는 아니다.

## 현재 source 회귀 검증

최종 동결 source에 대해 94개 test 파일 **2,609 PASS / 90.30초**, Ruff check/format
기존 46개 및 후속 변경 파일 PASS, strict mypy production 26개 파일 PASS,
Bash syntax/diff 검사 PASS다.
최초 통합 실행은 동시 source/test guard 정렬 중 이전 assertions 두 개가 실패했다
(2,578 PASS / 2 FAIL). 전체 동결 뒤 다시 실행한 결과를 위 최종 gate로 기록한다.
이후 닫힌 API 격리 callback을 추가하는 과정의 이전 six-callback 기대값 하나는
2,586 PASS / 1 FAIL로 확인해 갱신하고, 같은 94개 파일을 전부 다시 실행해 2,587 PASS였다.
native 0755와 protocol 초기 등록 후속 회귀에서는 이전 all-0644 source assertion 하나가
2,608 PASS / 1 FAIL이었다. metadata predicate/실제 mode·alias behavior 회귀를 정렬한 뒤
같은 94개 파일을 다시 실행한 최종 결과가 위 2,609 PASS다.
앞선 2,582 PASS 및 overlapping focused suite 수를 합산해 고유 테스트 수로 과장하지 않는다.

## 운영 변경 경계

공유 API 설치 전에는 지원된 owner projection으로 실제 command/job/lease/GPU claim의
quiescence를 다시 확인한다. historical failed/terminal row와 실제 실행 가능한 일을
구별하며, DB row 직접 수정이나 과거 성공 재해석을 하지 않는다.

기존 migration wrapper가 mutable API interpreter와 checkout을 root로 실행하는 경계를
발견해 [고정 release-operator adapter](../operations/RELEASE_OPERATOR_RUNTIME.md)로 좁혔다.
이 adapter는 기존 Alembic/role bootstrap을 재사용한다. 새 service/queue/worker protocol은
만들지 않는다. root-private reviewed source/wheels/context와 보호 interpreter를 먼저 입장시키고,
exact `20261010_0051` 및 기존 role reconciliation만 허용한다. 이 경계로 후속 `ad3ed8ca`
공유 release의 실제 migration·설치·검증을 완료했다. 배포 전 baseline과 실패한 admission은
아래에 역사적 증거로 보존한다.

마지막 배포 검사도 기존 API verifier의 public `verify_runtime_isolation()`을 보호된
interpreter와 admitted wheel에서 호출하도록 같은 adapter의 닫힌 callback에 연결했다.
이 검사는 DB secret을 읽지 않는다. 기존 fixed child는 service namespace 입장 후
`setpriv`로 실제 API UID에 내려간 **뒤** API interpreter를 실행한다. 격리 기준이나
service 권한은 바꾸지 않는다. 변경 가능한 API console entrypoint를 root로 실행하는
기존 배포 경로는 사용하지 않는다.

## 남은 실제 실험과 사람 검토

### 배포 전 실제 operator admission과 발견한 차이

`4fa29774f527a960e7b15f2d84f8044b388fab2b`의 source archive/3 wheels를
fresh root-private `/var/lib/eom-release-operator-stage.4fa29774-nTZ4k7`에 준비했다.
setuptools 중간 파일이 생긴 build `source/`는 복사하지 않고 exact `source.tar`를
검증·추출했다. context SHA는 `8955cbd48c444f1e202f3ee97d86c9d5a2d1fdc73be8669583de2ae99b746514`,
source snapshot SHA는 `a20184ca74f79c9de3411b858077398c57ddf3f112fcc3afc4d9e9f5d232bbb0`이다.
보호 interpreter/source/wheel의 실제 `ADMIT_PASS`를 확인했다. admission은 운영 배포가 아니다.

그 뒤 `PDF_RUNTIME_VERIFY`가 `RELEASE_OPERATOR_PDF_RUNTIME_INVALID`로 실패했다.
API와 보호 CPU의 `pymupdf/__init__.py`는 root:root:0644, `_extra.so`는 root:root:0755이며
양쪽 bytes/hash가 각각 일치했다. native SHA는
`218b6076f130f2a5d159e64909f5ffe8b966719e177c908af3db1305f8cb1dc1`이다.
정상 배포 native의 비쓰기 0755를 data-only reader가 0644로만 제한한 현재 source 결함이다.
exact `_extra.so`에만 0644/0755를 허용하고 다른 executable/writable/alias는 거부하는
source 회귀 86 PASS로 수정했다. 설치 파일 권한을 바꾸지 않았다. 기존 실패 stage/admission을
보존하고 수정 후보 `ad3ed8ca`를 새로운 build/context로 준비해 배포했다. 기존 no-forward
probe를 다시 실행하는 작업이 아니다.

owner의 읽기 전용 조회에서 비교 protocol `workflow-role/1.29.0`의 초기 등록이 없음을
확인했다. PREPARE의 초기 등록은 기존 Orchestrator protocol registration 경계에서
실제 현재 관리자 인가·정확 released schema hash·definition/capacity/candidate 입장을 검증한
뒤 처리하도록 후속 source를 보강했다. 직접 SQL 삽입이나 RELEASE 중 누락 복구는 사용하지
않는다. 실제 명시적 owner PREPARE는 아직 실행하지 않았으므로 초기 protocol/control 발행
gate는 계속 PENDING이다.

배포 전 공유 runtime baseline은 `83884224651d8b9516a7a54370077757138c518c`, DB head는
0050이었다. 그 release record의 3 wheel SHA와 보존된 rollback 입력의 SHA/RECORD가 일치했다.
0051 이후 옛 0050 platform으로 blind downgrade할 수 있다는 뜻은 아니다.
당시 chat nonsecret source pin도 같은 838842였다. 후속 배포에서 기존 supported atomic
pin-update로 `ad3ed8ca`에 정렬했다. API/일반 chat/worker/broker와 HWPX builder,
kordoc, content-team을 포함한 quiescence와 service 복원은 모델 실험과 별도의 운영 배포
gate다. 이 배포 전 baseline·실패 시점에는 service stop/migration/package replacement/model
forward를 하지 않았으며, 이후 완료된 공유 배포는 다음 기록과 구별한다.

### `ad3ed8ca` 실제 호환 공유 배포

2026-10-10 **16:07:55 UTC**에 source
`ad3ed8caf43f3a4ece5abce25b9b59801451803e`, tree
`a974e0754aaa8125cf8d481eda7d3c5cdc29b794`의 공유 release를 완료했다.

- fresh operator stage: `/var/lib/eom-release-operator-stage.ad3ed8ca-CJ7YAJ`.
- context SHA-256: `3cb2b8e14aa0d6b0e5074ffa77de68a5c8469193bc9e37870f812f9df3ee833d`.
- source snapshot SHA-256: `d805c8330f4ff368c6f47b44452d14d5359a49901abc782197c418bec100b4b7`.
- 보호 runtime/context `ADMIT`, migration 0051, 일곱 closed callback, API ready 검증: PASS.
- **16:10–16:11 UTC경** 최종 조회: 관련 8개 service 모두 active·enabled·positive PID.
- 일반 chat의 nonsecret runtime pin: `ad3ed8ca`; 전용 slot: READY.
- 실제 authenticated metadata/corpus read, CPU forward, selected pair 제출: 아직 수행하지 않음.
- 보호된 owner console과 UID 990 private 입력 경계 준비 완료; 실제 `guiadmin` TTY 로그인
  프롬프트 준비는 인증 성공 증거가 아님. 후속 종료 관측은 아래와 구분한다.

처음 admission한 build는
`/tmp/eom-api-build/ad3ed8caf43f3a4ece5abce25b9b59801451803e.CJ7YAJ`다.
기존 deploy는 같은 commit을 다시 build하므로 실제 설치된 wheel은
`/tmp/eom-api-build/ad3ed8caf43f3a4ece5abce25b9b59801451803e.BrDlZ9/dist`에서 왔다.
source commit/tree가 같아도 두 build의 raw ZIP SHA를 동일하다고 취급하지 않는다.

두 build의 data-only 비교에서도 source archive SHA가
`98155a371c03604d8eea9c04e797e004146ab6feb8ba66203329c054fb89b2c4`로 일치했다.
Platform 1,361개 및 API-contracts 99개 member의 payload/RECORD/order는 동일하다.
API 104개 member에서는 `build-info.json`의 `build_timestamp_utc` 한 필드와 이를 반영한
RECORD만 다르다. 세 wheel의 exhaustive RECORD 검증은 양쪽 모두 PASS다. raw ZIP의 시각
차이를 source/policy/protocol drift나 동일 Artifact identity로 해석하지 않는다.

실제 API identity로 읽어 검증한 정본 deployment record는
`/var/lib/eom-api/deployments/ad3ed8caf43f3a4ece5abce25b9b59801451803e.json`이다.
설치 wheel SHA-256은 이 record의 값이며, 최초 operator stage의 wheel SHA와 별개다.

| 설치 component | 정본 deployment record의 wheel SHA-256 |
|---|---|
| API contracts | `dfed170bf5b55a3db92192cc2fcb465ee8b35ea61b99e735c859fb6cd6ed80c5` |
| Application API | `ddd2dc4f340102e7519200d11195d2667343bb6f23211f32ec5e453802e9f7fd` |
| Platform | `ffb8ac66b31d134e2143a8efb534be274c313840cf90a478168cd32bc68351ed` |

이 결과는 설치·migration·격리·service 복원의 실제 증거다. 새 비교 목적의 protocol 초기
등록·control PREPARE/RELEASE, `guiadmin` 실제 session, corpus snapshot과 embedding/Codex
실험은 아직 PASS로 승격하지 않는다. 기존 no-forward 실패와 4fa stage/admission도 보존한다.

### 최초 실제 owner 로그인 시도의 종료

16:14:44.529 UTC API journal에는 `/auth/login` POST 한 건
(`req_a3cc8526dd2207154f92ff37812f31d2`)이 기록됐다. 콘솔은
`OWNER_CONSOLE_BOUNDARY_FAILED`로 종료했고, 실제 pane foreground가 bash로 복귀한 것을
확인했다. 이 관측 구간에 `/me`나 corpus read 요청은 보이지 않았다. 기존 request-completed
log에는 HTTP status가 없고 콘솔은 상세 예외를 의도적으로 출력하지 않으므로, 이 증거만으로
잘못된 비밀번호·현재 권한·응답 계약 중 어느 원인이라고 단정하지 않는다.

실제 owner UID의 metadata-only 검사에서 `owner-input-s9vek0xd` 아래 입력·prepare·query·
result receipt 네 개가 모두 ABSENT였다. 고정 콘솔은 이 receipt와 explicit RUN_EXPERIMENT
이후에만 CPU launcher를 호출하므로, 이 시도는 모델 실행이나 Artifact 발행 단계에 도달하지
않았다. 실패한 원래 코드·보호 복사본·private 입력 경계는 보존한다. 자동 relaunch나 새 CPU
identity 우회는 없으며, 사용자 입력 확인과 secret-safe phase/code 진단은 별도 후속 단계다.

사용자는 입력한 비밀번호가 실제 Studio 로그인 비밀번호였다고 확인했다. 따라서 잘못된
비밀번호라고 추정해서 계정·권한·비밀번호를 바꾸지 않는다. 원래 코드를 보존하고 단계명과
allowlisted stable error code만 추가한 one-off 진단 presentation을 준비했다.

- 진단 코드 SHA-256:
  `8c3a2d53043e9d2285a72d9e86f38730229c2bc1091eace9debfcb8da7fb37a7`.
- 보호 복사본: 원래 libexec의 `owner-diagnostic.py`; root:root:0644, 새 single-link inode.
- private 증거: `/var/lib/eom-inference-console-diag-kd1ob7jb/owner-diagnostic.py`.
- 독립 focused 합성 검사 38 PASS, Ruff check/format PASS, strict mypy 2 files PASS.
- 진단 statements를 제거한 AST는 원래 identity/auth/input/hash/model/budget/explicit
  RUN_EXPERIMENT 동작과 동일하다. 예외 message·token·password·응답 본문은 출력하지 않는다.
- 실제 identity/private-input 검증 뒤 PASSWORD_PROMPT에 도달했고, 사용자 재입력 후
  16:24:36.529 UTC `/auth/login` POST
  (`req_0965aa9a67f11a5c25df3fb16f73e07e`)가 기록됐다. 진단 콘솔은 LOGIN 단계에서
  `CONTROL_AUTHORIZATION_REQUIRED`로 종료했다. `login_guiadmin=ENTERED`, 별도의
  current-principal read는 NOT_ENTERED이고 이 관측 구간에 `/auth/me` 요청도 없었다.
  따라서 corpus·권한별 자료 조회·CPU 실행 전의 로그인 거절로 분류한다. native transport는
  login HTTP 401/403/429를 같은 stable code로 표현하고 journal은 HTTP status를 기록하지
  않으므로, 비밀번호 불일치·계정 잠금/비활성·rate limit 중 어느 하나로 단정하지 않는다.
  자동 재로그인, credential reset, auth 경계 완화는 하지 않았다.
  이전과 같은 private 입력 경계를 사용하며 새 CPU execution identity를 만들지 않았다.

source-only 독립 진단에서 지원된 다음 조회는 기존 실제 브라우저 session의
`/api/v1/auth/account`와 fresh ADMIN `OPERATOR_READ`의 `/api/v1/operators`다.
표시 이름 `GUI admin`은 로그인 username `guiadmin`의 alias가 아니며 현재 username은
사용자가 변경했을 수 있다. Operator 조회에는 상태·역할·실제 username이 있지만 credential
hash나 잠금 상태는 없다. public ApiAuditEvent read 계약도 확인되지 않았으므로, root 권한으로
private auth 테이블을 읽어서 실제 사용자 인증을 우회하지 않는다. 현재 사용자에게
`guiadmin`의 실제 브라우저 로그인 가능 여부를 확인 중이며 해당 답변 없이는 추가 로그인이나
코퍼스/모델 실행을 시작하지 않는다.

이후 사용자는 이전 입력이 잘못된 비밀번호였다고 직접 확인했다. 이것은 사용자 피드백이며
과거 API 응답의 상세 상태나 실제 로그인 성공을 새로 증명하지 않는다. 해당 확인 뒤 같은
보호된 진단 코드와 private 입력 경계로 새 입력 창을 한 번 열었고, 실제 foreground 실행이
PASSWORD_PROMPT에 도달한 것을 확인했다. 비밀번호 자동 입력, 계정 변경, model forward,
새 CPU execution identity 생성은 하지 않았다. 실제 인증 성공은 새 입력 이후의 native
current-principal/corpus read 증거로 별도 확인한다.

### 실제 재입력 인증과 original corpus 조회

16:31:19 UTC 재입력 이후 native `login_guiadmin`과 명시적 current-principal read가
RETURNED에 도달했고, 공식 `/assessment-learning-corpus`와 `/execution-presets` 조회가
완료됐다. 이는 이전 거절 기록과 별개의 실제 인증 성공 증거다.

- original occurrence-backed approved Item count: **520**.
- original target solution report: **520/520**.
- Graph revision: `graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9`.
- Graph semantic SHA-256:
  `sha256:da76258a650dcb66c3303f579ec1502215bda6cb75f05808414809d7076bf645`.
- 조회된 ACTIVE `knowledge-grounded-item` preset:
  `execpreset_ae1ba40431514551ba86e8148c985f9c`.
- 해당 RELEASED current revision:
  `execpresetrev_8dcefbb3518c4d7d8b3289d7f154414c`.
- preset content SHA-256:
  `sha256:bdb3772ce54c86dbc7d5a5a190395b35970fdc15d8dfcb5472607002c91a1c26`.

같은 실제 session으로 exact Graph/policy metadata를 확인하고 query-free inventory 조회를
시작했다. 이 경로는 기존 출제 preset의 retrieval scope만 pin하며 그 preset을 비교 worker
실행 목적으로 바꾸지 않는다. inventory·고정 query·입력 receipt·CPU 실행 결과는 각각 실제
반환과 검증 이후 기록한다. 이 시점의 corpus 완료 수는 profile encodability나 비교 품질,
model forward 실행의 증거가 아니다.

16:34:11.711 UTC snapshot POST `req_9044d63519bde9fb1eef0c6c4762baa8`가
120,107.849 ms에 종료됐고 콘솔은 INVENTORY_READ의 `OWNER_CONSOLE_BOUNDARY_FAILED`로
terminal 종료했다. 기존 API→Catalog snapshot socket과 owner HTTP 경계는 각각 120초다.
이는 해당 timeout 경계와 일치하는 증거이며 모델 실패나 로그인 실패로 재분류하지 않는다.
동기 Catalog handler가 실제로 완료됐는지는 클라이언트 종료만으로 증명하지 않는다.
입력 stage/CPU launcher에 도달하지 않았고 자동 재제출은 하지 않았다. source inspection의
공유 extraction provenance 반복 검증 비용과 요청범위 재사용 설계는 구현 계획에 기록했다.
성능 개선 효과와 실제 520개 snapshot 재조회는 수정·검증 이후 별도 증거가 필요하다.

16:39:08 UTC Catalog의 MainPID 298424와 OS thread 목록을 조회했다. 남은 두 thread는
각각 16:07:43, 16:07:45 시작으로 해당 16:32 snapshot 요청보다 먼저 존재했다. 당시
ThreadingMixIn의 요청별 handler thread는 관측되지 않았다. 이는 그 timeout 요청이 계속
실행 중이라는 증거가 없다는 확인이며 전체 Workflow queue/lease의 quiescence는 아니다.

후속 source 수정은 `past_exam_source_provenance.py`의 요청범위 typed provenance와 immutable
index를 기존 source resolver/cache에 연결한다. exact member key는 Artifact/revision/member/
raw SHA/schema/media/byte bound와 decoder kind를 포함한다. 보존 상한은 source JSON 64 MiB,
member 1,024개, index row 100,000개다. 상한 초과 시 전체 검증한 값을 반환하되 캐시에
보존하지 않는다. 실패는 캐시하지 않고 현재 Item 승인·decision·revision·lineage 검사를
생략하지 않는다. 전역 cache, 새 schema/migration/dependency, 원문 수정은 없다.

- 변경 경계의 focused source/source-resolution/retrieval/snapshot 검사: **154 PASS**.
- root 재검사에서 동일 suite와 dependency-boundary 검사를 함께 실행해 **160 PASS**;
  unused decoder 제거와 새 leaf의 필수 wheel inventory 반영 후 source/deployment 경계
  검사 **93 PASS**. 이들은 겹치는 suite이므로 합산한 고유 test 수로 보고하지 않는다.
- 소스 3개 strict mypy PASS, 새 unit test strict mypy PASS, 수정 Python 5개 Ruff/format PASS.
- 합성 520회 공유-member 조회에서 manifest/acceptance/result/layout의 전체 검증은 각각
  1회였다. 8/64 work-unit fixture에서도 full-batch validation 각각 1회를 확인했다.
  이것은 반복 비용의 복잡도 개선 증거이지 실제 520개 latency 측정은 아니다.
- 기존 inventory 실패의 native `SnapshotReadFailure`만 stable code로 표시하도록 one-off
  presentation successor를 준비했다. 원래 identity/auth/pins/budget/RUN 동작은 AST 대조로
  보존했다. 53개 secret-safe 합성 검사와 Ruff/strict 타입검사 PASS. 원래 코드·진단 코드와
  실패 관측은 덮지 않는다. successor SHA-256:
  `0595863d1b26be7c1c204fad52fc0a64beab2576233c9356b20a815c9988150b`.

이 source 수정의 실제 runtime 검증은 다음 후속 관측에 기록한다. 동일 공식 snapshot
재조회는 fresh 인증 전까지 PENDING이다.
격리 CPU 수치/launcher closure와 새 Catalog leaf는 겹치지 않으므로 이 수정만으로 CPU
환경을 재설치하거나 이미 승인된 no-forward probe를 반복하지 않는다.

### 요청범위 source 비용 수정의 실제 compatible 설치

16:50:32.991392 UTC 정상 배포 record와 실제 API UID의 installed build 조회로 다음을
확인했다. 최초 ad3 설치·실패·인증·timeout 기록과 별개의 successor다.

- installed source: `7383d1c60efcd1fdd80d0cf49e644bcc55b0c62b`.
- installed tree: `e4858223947ac7f1fdb4871384c70a9d079080c1`.
- migration head: `20261010_0051` 그대로; 새 migration/upgrade 없음.
- normal install wheel directory:
  `/tmp/eom-api-build/7383d1c60efcd1fdd80d0cf49e644bcc55b0c62b.sD8kJI/dist`.
- installed wheel SHA-256:
  - API contracts: `e317ba3f2bbc066158ffe4c44ff899cd46223701f5e6c1596a65055233f82b15`.
  - Application API: `0d9a37b34097e21041217a535efbaa79c98b0adf98eaf20d16f7901a2248aec6`.
  - Platform: `04f3113d88f01dfc522dce5a77085086e4361677165351428f86af1e76a8d5de`.
- source archive: `sha256:25600ef02c0aa25c4c20564793282be7f4628ecef39e2a19d6e97d9b7f8c98ad`.
- protected operator data stage: `/var/lib/eom-release-operator-stage.7383d1c6-Pt46NV`;
  context SHA `059665712883923013e03c235f0ca2c6a97d2fbefb314763ecbe3df3c24157c2`;
  source snapshot SHA `6d9bc6d783589b957e7f77cded0204e975cd581e943300bead6e553f6e90edde`.
  기존 ad3 보호 libexec와 CPU runtime을 그대로 재사용하고 새 context ADMIT를 통과했다.
- normal deployment의 6개 callback(PDF runtime, migration verify, API role, Catalog role,
  HWPX role, API isolation) 모두 실제 PASS; deployment admission READY.
- 별도 Chat release pin은 기존 보호 adapter의 atomic predecessor update로 갱신했다.
  auth/model/secret/unit bytes는 변경하지 않았다. 16:51:42 UTC 8개 서비스 모두
  active/running/enabled/positive MainPID, API live/ready smoke PASS.
- 최초 Pt46NV stage wheel과 normal sD8kJI wheel은 raw SHA가 별개다. 두 빌드 RECORD PASS;
  Platform 1,362개·API contracts 99개 payload 전부 동일, API 104개 중 build timestamp와
  해당 RECORD만 달랐다. 최초 stage identity를 설치 identity로 덮지 않는다.
- source resolver를 사용하는 Chat/pair-authority 추가 회귀 **76 PASS**. 앞선 suite와
  합산한 고유 test 수나 실제 사용자 기능/비교 품질 PASS로 해석하지 않는다.
- snapshot 진단 successor를 새 candidate libexec에 보호 복사했다. 원래 콘솔·old diagnostic
  보존; private copy `/var/lib/eom-inference-console-snapshot-diag-ay17euhl`.
- actual owner UID metadata 검사에서 같은 `owner-input-s9vek0xd`의 4개 output receipt는
  모두 ABSENT였다. 이전 timeout을 우회하는 새 CPU execution identity는 만들지 않았다.

원래 인증 session은 timeout으로 콘솔이 terminal 종료되면서 소멸했다. fresh guiadmin TTY
로그인 이후 같은 private 입력 경계에서 공식 snapshot 재조회를 진행한다. 아직 snapshot
latency 개선, 고정 corpus embedding, pair worker, human transfer quality는 확인하지 않았다.

이것은 임시 operator presentation이며 새 worker protocol, auth grant, HTTP status 관측이나
production search 활성화가 아니다. 원인 분류 이후 임시 진단 호출부를 회수하고 검증 기록은
보존한다. 실제 로그인·corpus/모델 실행 PASS를 대신하지 않는다.

- 격리 no-forward probe PASS: **PASS_AFTER_ONE_APPROVED_RETRY / FIRST_FAILURE_PRESERVED**.
- compatible shared release: **7383d1c6 PASS**; migration 0051 unchanged, service 복원 PASS.
- 실제 `guiadmin` 인증·metadata·original corpus read: **PASS**; profile inventory 별도.
- 명시적 비교 owner PREPARE/RELEASE 및 초기 protocol/control 발행: **PENDING**.
- 고정 4-query, top-k 8, batch 4, threads 4 CPU 실험: **NOT_RUN**.
- 최대 2개 selected pair의 지원된 Orchestrator/Codex 비교: **NOT_RUN**.
- 사람의 풀이 전이 품질: **NOT_EVALUATED**.

E5의 512-token 범위를 넘는 자료를 자르거나 성공한 subset을 전체 520개처럼 보고하지
않는다. common encodable pool과 고정 query 조건을 만족하지 못하면
`INSUFFICIENT_ENCODING_COVERAGE`라는 측정 결과를 보존한다. Artifact commit 완료와
유효 benchmark 완료, 사람 평가 완료는 다른 상태다.

사람에게 최종적으로 모아줄 검토는 exact pair·자료 pins·후보 근거·대응하는 조건과
착상·대응하지 않는 부분·새 추론·rubric이다. model 출력으로 사람 평가나 교육 품질 PASS를
만들지 않는다. 사용자의 추가 선택이 필요한 successor 정책은 별도 gate로 남긴다.

### Fresh 인증과 실제 520개 inventory — 2026-10-10 17:38–17:42 UTC

새 실제 owner 콘솔에서 native 로그인/current-principal 조회가 RETURNED에 도달했다.
공식 original corpus는 520개, 풀이보고서는 520/520이며 앞서 기록한 Graph와
`execpresetrev_8dcefbb3518c4d7d8b3289d7f154414c`의 revision/hash가 그대로였다.
query-free snapshot PREPARE `req_4aa7b2e4ba22125e059a52be3bb1be00`는
17:41:27.352284 UTC, **79,325.809 ms**에 반환됐다. source/profile 각각 520개,
missing report 0, header SHA는
`sha256:04bf1b4b9d10d4f7273abbcb98049c838cc0cb3eb794714d50fb780883bf9fb8`다.
이것은 이전 120초 timeout 이력과 별개의 실제 성공이며, 같은 환경에서 완료된 이전
baseline 시간이 없으므로 개선율이나 충분한 운영 응답성 PASS를 계산하지 않는다.

canonical index의 첫 네 profile-present revision을 고정했다. 질의 선정은 토큰 길이·
검색 성적을 보고 바꾸지 않았으며 품질 대표표본이 아니다.

- `itemrev_3fc12f67ee35469b8f45fdd9ded1506c`
- `itemrev_367073d3afc741ad842bb46078db50a7`
- `itemrev_7dce2140909f4194aaa9a12a551a1752`
- `itemrev_ca382cd4bd86455d914c38daea3d1b38`

기존 private owner 경계에서 입력을 O_EXCL로 보존한 뒤 명시 RUN_EXPERIMENT에 진입했다.
실행은 `embeddingexecution_125fe45683e34a2ea188e8ea65a990b0`, 실험은
`embeddingexperiment_c79e37d2c816471f9ea9554521cef987`, revision은
`embeddingexperimentrev_dd0f2293c1a54ab6b1b7a0078e471c74`다. 입력 receipt raw SHA는
`sha256:7dd0fba98ac3cf61d32a5bdf47f48a72e6c9132dd19ab33adefd387ff0d2a775`다.
예산은 queries 4/top-k 8/batch 4/threads 4/encoded texts 최대 3,072 그대로다.
17:43:35.940292 UTC 같은 실행의 query-bearing PREPARE
`req_a64d9314e71433850894a53e8cc41338`도 **78,910.796 ms**에 완료됐다.

이 시점은 staging이며 CPU launch·정본 결과·측정 coverage·사람 판정 완료가 아니다.
설치는 `7383d1c6` 그대로이며 `60ed7667` human-owner 후보는 build-only다.
전체 승인 자료를 부분 READ마다 다시 입장·해석하는 비용은 실제 READ 완료/실패와
함께 후속으로 분류한다. timeout 확대, 질의 교체, 승인/출처 검증 생략이나 자동 CPU
재실행으로 성공을 만들지 않는다.

### 실제 첫 READ 실패와 목적 한정 보완

첫 READ `req_9a829a533935374769c4868a2c5ed9cd`는 17:45:12.022501 UTC,
**95,670.972 ms** 뒤 `INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID`로 종료됐다.
owner 콘솔은 terminal FAILED이며 Catalog 요청 thread도 종료된 것을 확인했다.
staging이 완료되기 전이므로 코드 경로상 CPU launch/workspace preparation/publication에
도달하지 않았다. 결과 Artifact나 model quality PASS는 없고 원래 입력 receipt/identity를
덮거나 다른 execution identity로 우회하지 않는다.

source 검토와 유효한 합성 3-record/4,635,472-byte 재현에서 응답 byte-budget 초과가
일반 ValueError에 흡수되어 REQUEST_INVALID로 잘못 반환되는 결함을 확인했다.
기존 staging의 같은 chunk 분할은 BUDGET_EXCEEDED에만 동작한다. 실제 실패 요청의
동일 원인 여부는 현재 진단이 없어 UNKNOWN이며 합성 재현을 actual 원인으로 단정하지 않는다.

보완 경계는 기존 Catalog READ application/transport다. 정본 typed records의 canonical
응답 bytes를 frozen 모델 생성 전에 계산하고, 기존 global frame/요청 chunk 중 작은
한도를 넘으면 이미 released enum인 BUDGET_EXCEEDED로 반환한다. 동일 header/index/
질의/자료를 유지하는 기존 split만 복구하며 원문 절단·더 큰 bound·새 schema enum·
새 queue/DB/cache·비인가 재사용을 추가하지 않는다. 그 외 hash/ref/schema 오류는
일반 invalid로 보존한다. transport에는 고정 phase/검증 단계/오류 종류만 기존 logger로
기록하며 오류 메시지·input·context·traceback·문항 내용은 기록하지 않는다.

후속 source 회귀는 frozen 변경 기준으로 snapshot budget/diagnostic/service/staging/
transport/execution/design-boundary/reporter 8파일 **237 PASS / 18.63초**다.
추가 계약/binding/Catalog adapter/profile/comparison/human contract·owner/experiment
8파일 **323 PASS / 12.40초**이며 앞선 역사적 suite와 합산하지 않는다.
Ruff check/format 7파일, strict mypy 5파일 및 diff 검사는 PASS다.
합성 overflow의 기존 split과 exact canonical bytes/hash 보존, singleton에서
workspace/CPU/commit 0, 비크기 오류·권한 철회 시 중단, logger 장애가 기존 safe reply를
바꾸지 않는 것을 검사했다. 이 source 검증 시점에는 아직 설치하지 않았으며 실제 READ
원인과 자료 전체 staging·CPU 결과를 확인한 증거가 아니다. 이후 설치는 다음과 구별한다.

### `f12fb971` 실제 수정본 배포와 서비스 복구

2026-10-10 **18:11:32.257955 UTC**, source
`f12fb9710823bccc30c78a61bf1b2d784b7b4929`, tree
`a67bc6a69c10c31521eebabce01d210d06a3c3e4`의 정상 공유 배포를 완료했다.
사용자가 이미 인증한 `EOM:2 inference-transfer` TTY의 sudo를 그대로 사용했다.
다른 비TTY 실행의 인증 실패를 사용자의 인증 실패로 해석하지 않았다.

- 기존 보호 interpreter, 기존 closed operator adapter를 재사용했다. CPU 설치·model
  bytes·worker 인증·queue·DB schema를 새로 변경하지 않았다.
- fresh data-only stage: `/var/lib/eom-release-operator-stage.f12fb971-J3RSLX`.
- context SHA-256: `e3ccc3efdb4e34421a042a9ccd2df94b01cb915e01918a3039cfbc985dfc5219`.
- source snapshot SHA-256: `f353b4cdb55939122b17ae718dea62b967c63169abda2a71fd72d29c5aeb4120`.
- 실제 `ADMIT_PASS`와 **여섯 EXECUTE callback** PASS: PDF runtime, migration verify,
  API role, Catalog role, HWPX role, API isolation. 기존 migration `20261010_0051`
  그대로이며 `MIGRATION_UPGRADE_0051`은 이번 배포에서 실행하지 않았다.
- 실제 지원된 작업·lease·채팅 quiescence 검사 PASS, workflow command/API processing
  각각 0. HWPX runtime role로 별도 조회한 item/exam active build도 각각 0이다.
  Orchestrator role의 HWPX 조회 권한 거부는 우회하거나 grant로 해결하지 않았다.
- 원래 active/enabled인 관련 8개 service를 정지하고 실제 inactive/dead/PID 0과
  정지 뒤 작업 검사 PASS를 확인했다. 정상 install은 개발 사용자로 실행했다.
- 정상 배포는 같은 source의 별도 `G9uItf` wheel build를 설치했다. 처음 admitted
  `J3RSLX` ZIP hashes와 설치 ZIP hashes를 같다고 보고하지 않는다.
- 정본 설치 record:
  `/var/lib/eom-api/deployments/f12fb9710823bccc30c78a61bf1b2d784b7b4929.json`.

| 실제 설치 wheel | Raw SHA-256 |
|---|---|
| API contracts | `716a73d24368bcb8d03f9b1092171cacb2a376098ad5ee228d75ceaf1eb18a0a` |
| Application API | `9bd20d36f7087c1b87b83a16da02eaec24091bfbdba94735adf5282ea0c8b377` |
| Platform | `7c19596877dbf1bb515f75915f0c70133027574d8c2ca763b2249c5025106dc6` |

같은 admitted source의 기존 `update_release_pin()`만 보호 interpreter에서 호출해
채팅의 정확한 nonsecret predecessor `7383d1c6` → `f12fb971`을 atomic advance했다.
auth/model/RAG 설정과 대화 기록은 바꾸지 않았다. 별도 broker/chat worker/chat owner를
복구한 뒤 **관련 8개 service 모두 active/running/enabled/positive PID**, API health
smoke PASS, API UID의 공식 chat slot read **READY**, 실제 installed build commit/tree
일치를 확인했다. human-review owner leaf도 공유 wheel에 포함되지만 실제 사람 label
게시·교육 품질 판단을 수행했다는 뜻은 아니다.

이 배포에서 실제 model/CPU forward, 새 비교 job, 문항/풀이보고서 재생성은 **0**이다.
원래 failed READ, private 입력 receipt/실험 identity를 그대로 보존한다. 수정본에서
actual-principal PREPARE/첫 READ를 최소 범위로 진단하는 다음 gate가 남아 있다.
일반 source tests나 service health로 그 READ 원인·성능을 확정하지 않는다.

18:13 UTC Slack `devreport_29bf2d655f2e4a7985e1a65dc5bab872`의 처음 callback 수
표기는 7이었으나 실제 log는 위 6개와 별도 ADMIT다. 원 보고를 지우지 않고
`devreport_810773308b08422fa90153c57a593085`에서 한국어 첫 문장으로 정정했다.
중간 정정 보고의 비한국어 summary도 한국어 reporting 규칙 준수로 간주하지 않는다.

### `f12fb971` 실제 첫 READ 진단 — 실패 보존

2026-10-10 **18:33:41 UTC**, fresh `guiadmin` 인증과 원래 보호된 입력 receipt를
사용한 one-off READ-only probe가 종료됐다. PREPARE는 source 520과 expected
header/index 일치를 확인했으며 **80,305 ms**였다. 첫 16-entry READ는 **95,710 ms**
뒤 `INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID`로 실패했다. 실제 API request는
`req_ae39720cd6dd694ad04bb144457b9236`이며 Catalog의 안전한 진단은 다음과 같다.

```text
phase=READ
validation_stage=OWNER_SERVICE
error_kind=FROZEN_MODEL
attempted_first_read_calls=1
cpu_launch_count=0
no_auto_retry=true
original_input_rewritten=false
```

실제 header는 `sha256:54825b8c7b34e943e0cd0309053d04f73ddddb4fd8eb80abbfb012f32eecdb70`,
index는 `sha256:a01015a9992b3cb2d1601fdf86dd4f262de22dd27b2eaa8b16237c37f8ae7220`,
PREPARE는 `sha256:9e6d065811b61c5d40c7b6cc9bfdca380dd964b34982a7c539447aedbf09b5db`,
READ는 `sha256:046c41300539385d5498d06a81d6377518a0bb370733494af33f33d417fed843`이다.
같은 `embeddingexecution_125fe45683e34a2ea188e8ea65a990b0`와 기존 raw input
`sha256:7dd0fba98ac3cf61d32a5bdf47f48a72e6c9132dd19ab33adefd387ff0d2a775`를 유지한다.

이 결과는 합성 overflow 수정이 해당 실제 오류를 해결했다는 증거가 아니다. 입력 frame
파싱이 아닌 owner 내부 frozen-model 검증 실패로 범위를 좁혔지만, 구체적 모델/field
또는 실제 크기 초과 여부는 아직 확정하지 않는다. CPU/model forward, control 발행,
비교 job과 결과 Artifact commit은 수행하지 않았다. 실패 기록을 성공으로 고치거나
새 execution으로 우회하지 않는다. 구체적인 source 결함을 먼저 재현한다.

이후 사용자의 “사람 평가는 없다고 생각해” 지시에 따라 사람 평가는 현 완료의
조건이 아니다. 기존 human owner/계약/기록은 보존하며
`HUMAN_TRANSFER_REVIEW=NOT_EVALUATED / NOT_REQUIRED_FOR_CURRENT_COMPLETION`로 둔다.
Slack `devreport_68fb3bdba72a40f8b7eaac696955b5aa`는 이 범위 변경과 READ 진단을
한국어 첫 문장으로 보고했다. 새 사람 scorecard/context/GUI는 구현하지 않는다.
