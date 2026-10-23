# 로컬 임베딩 GPU 실험 — 실행 목표와 완료 기준

작성: 2026-10-20 UTC. 사용자가 GPU 실험을 별도 goal로 승인했다.
이 문서는 새 검색 시스템 설계가 아니라, 이미 구현된 CPU/CUDA 비교 경로의 실제 실행 계획이다.

## 현재 확인한 사실

- 기존 증분 RAG 연결 목표는 완료됐으며 그 acceptance와 정본 이력을 다시 열지 않는다.
- 기존 CPU/CUDA 여섯 비교는 `NOT_STARTED`; GPU 기본값은 아직 승인·활성화되지 않았다.
- 착수 시 GPU는 RTX 5080, VRAM 16,303 MiB, 사용량 2 MiB, utilization 0%였다.
  이는 실행 중 독점·호환성 증거가 아니며 입장 직전에 다시 확인한다.
- 저장소는 `742e7188b49166118dfd44eb357300fdd716be67` 기준 clean이었다.
- 이전 기출 비교 PDF를 위한 다섯 QUERY와 이번 benchmark는 서로 다른 작업이다.
  PDF의 완료 요청을 다시 실행하거나 그 시간을 CPU/GPU 측정으로 재해석하지 않는다.

## 재사용할 원 설계

- [GPU runtime §§6–8](../architecture/INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md)
- [고정 측정 계약](../architecture/INCREMENTAL_EMBEDDING_DEVICE_BENCHMARK_PROPOSAL.md)
- [기존 owner 구성](../architecture/EMBEDDING_BENCHMARK_OWNER_COMPOSITION.md)
- [유한 6회 root 제어](../architecture/EMBEDDING_BENCHMARK_SERIES_CONTROL.md)
- [실제 CUDA 파일 관찰](../architecture/EMBEDDING_BENCHMARK_CUDA_CAPTURE.md)
- [모델 로드 없는 token 준비](../architecture/EMBEDDING_BENCHMARK_TOKEN_PREPARATION.md)

새 DB, queue, vector engine, 모델 재학습, 상시 benchmark service는 만들지 않는다.
기존 supported application/Orchestrator/native worker/Artifact publication 경계를 사용한다.

## 실행 순서

1. **실제 설치·원래 실패 inventory.** CPU/CUDA configuration·bundle·admission·owner·unit과
   physical lease, 현재 INDEX/QUERY 작업을 읽기 전용 확인한다. 예전 script의 미완료 placeholder나
   과거 source pins를 현재 운영 사실로 사용하지 않는다. 진행 중 작업·실패 이력은 보존한다.
2. **고정 입력·실행 준비.** 공식 Catalog 경계로 승인된 기출 6 profile을 길이 층별로 선택하고,
   가능한 3 view의 DOCUMENT 최대18행과 genuine QUERY2개를 pin한다. 기존 tokenizer-only
   준비와 공개 fixture를 사용한다. 준비·root controller를 먼저 완성하고 실제 로그인은 필요한
   직전에 받아 반복 입력을 최소화한다. password 저장·freshness 연장·관리자 사칭은 하지 않는다.
3. **실제 유한 비교.** 같은 모델 payload·recipe·token 입력으로
   `CPU → CUDA → CUDA → CPU → CPU → CUDA`를 기존 original-Job/idempotency 경계에서 실행한다.
   device별 첫 process 안에서 warm-up1, warm5, QUERY2×5, 2048-token capacity batch1/4를 측정한다.
   나머지 process는 cold만 측정한다. 각 실행의 기존180초/RAM6GiB/GPU8GiB 경계를 유지한다.
4. **기존 판정기로 평가.** 원 수치·순위·성능 기준을 결과를 보고 바꾸지 않는다.
   norm 오차≤1e-5, 대응 cosine≥0.99999, component 오차≤1e-4, score 오차≤2e-5,
   gap>4e-5 순서 보존 및 사전 near-tie 규칙을 검증한다. GPU 우수 조건은 warm≤CPU×0.80,
   cold median≤CPU×0.90, 각 QUERY encode/end-to-end≤CPU×1.10, cold max≤CPU max×1.20이다.
   peak RSS/VRAM, 실제 physical lease·cgroup 종료와 image/trainer 공존 증거를 별도로 확인한다.
5. **조건부 운영 선택.** 실제 correctness/performance/resource/isolation/regression을 모두
   통과할 때만 CUDA DOCUMENT/QUERY compatible family와 별도 CUDA index를 연결하고
   default를 활성화·read back한다. CPU index/policy와 rollback 경로를 보존·검증한다.
   GPU가 불리하면 CPU 유지가 정당한 결론이며 임계값을 낮춰 GPU를 억지로 채택하지 않는다.
6. **종료 보고.** 실제 실행·실패·미실행 범위를 구분한 비교표와 Artifact pointers/hashes,
   기본값·복구 상태를 문서화하고 중요한 milestone을 Slack으로 보고한다.

## 완료 및 실패 경계

- 설치/소스 테스트 PASS만으로 측정 완료라고 보고하지 않는다.
- 원 6회 실행과 실제 비교 판정, 필요한 안전 회귀, 조건부 운영 결정·검증까지 종료 근거를 남긴다.
- 기존520개 전체를 device마다 재인코딩하는 것을 비교의 선행조건으로 추가하지 않는다.
- 사람의 유사성/교육 품질 평가는 이 기술 목표의 필수 gate가 아니다.
- 불명확한 실행·revocation·hash/space mismatch·미정리 GPU 작업이면 추가 side effect를 멈춘다.
  실패를 성공으로 덮지 않고 original key의 지원된 reconcile/replay만 사용한다.
- stage마다 원 설계와 대조한다. 공통 소비자·Chat·출제 UI의 무관한 확장이나 별도 연구로 새지 않는다.

## 착수 상태

`GOAL=ACTIVE`, `SIX_MODEL_RUNS=NOT_STARTED`, `DEFAULT_DEVICE=CPU`,
`GPU_SUPERIORITY=NOT_EVALUATED`. 후속 실제 증거로만 갱신한다.

### 06:38 UTC 준비 확인

- 원 benchmark allocation `7255032e`의 입력/정책/실행 Job 조회 결과0: 이전 여섯 모델 실행을
  재실행하거나 알 수 없는 실행에 새 identity를 발급하는 단계가 아니다.
- 원 CPU configuration `e0afda42`의 설치 관찰은 실제 `PASS`; 기존 protected EE owner
  `ee97239d`의 RECORD hash도 원 pin과 같다. 수치 prefix를 다시 설치하지 않았다.
- 현재 API provider는 `60af9e5d`; 운영 QUERY가 고정한 provider/code12개를 실제 설치 바이트와
  대조했다. 예전 `881584aa` provider pin을 그대로 사용해 로그인부터 실패시키지 않는다.
- 관련 집중 소스 테스트118 PASS. 실험 전용 operator의 별도 합성12 PASS, 새 HTTP leaf strict
  type·Ruff/format PASS. 이 수치는 실제 인증/모델/GPU/성능 PASS가 아니다.
- 임시 실험 전용 HTTP leaf는 login/me/system-info만 허용하고 기존 Identity FD capture와
  benchmark application에 세션을 연결한다. C1–C5·Chat·출제·Pack activation은 호출하지 않는다.
  기존 root lifecycle/tokenizer helper는 보호된 정확한 바이트를 재사용하며 루트의 기존
  6회 제어 순서가 동일하다는 AST 회귀를 포함했다. 새 production service는 추가하지 않는다.
- 준비 진단·검사 기록: `/tmp/eom-gpu-experiment-20261020.9jWy7rO3`.
  아직 실제6회와 GPU 기본값 전환은 수행하지 않았다.

### 14:33 UTC 재개 전 확인

- 추가 측정/수치/최종화/driver/relay 소스 회귀140개가 모두 통과했다
  (`measurement-source-gate.xml`, failures/errors/skips=0). 실제 장치 측정 증거는 아니다.
- 첫 controller는 Studio 비밀번호 입력을 기다리다 한 시간 제한으로 종료됐다
  (`Result=timeout`, 원 invocation `b0a53293f8044c42a2757ca04e85b054`).
  실패 이력을 유지하며 성공으로 바꾸거나 해당 unit을 초기화하지 않는다.
- 재개 시 read-only inventory에서 원 input/policy/measurement Job은 여전히0건,
  원 CPU 설치와 API provider12개 바이트 대조는 PASS였다. GPU 사용2MiB/0%,
  compute process 없음; tokenizer unit은 not-found, 원 controller MainPID=0이다.
- 보호된 원 selection/operator 바이트는 그대로 사용하고, terminal controller와
  구별되는 새 controller invocation만 준비한다. 원 benchmark/revision/publication key,
  모델·표본·여섯 실행 순서와 수치/시간 제한은 변경하지 않는다.
- 현재 `SIX_MODEL_RUNS=NOT_STARTED`, `DEFAULT_DEVICE=CPU`다.

### 14:41 UTC 실제 로그인 후 bootstrap 오류

- 실제 로그인·Identity FD capture·원 source 재인가는 성공했다. tokenizer 입장 전에
  root가 child의 `/proc/<pid>/stat` 소유자를 검사하다 `INSTALLED_RUNTIME_FILE_UNPROTECTED`로
  중단했다. 기존 validator를 완화하거나 원 Job을 성공 처리하지 않는다.
- 별도 무인증 커널 재현에서 원인을 확인했다: 이 호스트 `fs.suid_dumpable=2`이며 root에서
  UID990으로 내린 fork child의 proc 파일은 UID0으로 남는다. UID/GID/capability를 내린 뒤
  해당 child만 일반 비특권 exec와 같은 dumpability1로 설정하면 proc 소유자990과 기존
  identity validator가 일치하고, 잘못된 UID/GID는 계속 거부된다. 모델·DB·로그인 실행0.
- 수정 책임은 임시 finite operator의 privilege-drop bootstrap이다. 정본 데이터,
  설치된 production validator/SDK/native worker, 전역 sysctl이나 접근 정책은 변경하지 않는다.
  child의 실제 nonroot UID/GID·groups·NoNewPrivs·capabilities를 확인한 뒤에만 설정하며,
  실제 자기 identity 검사를 로그인 **이전**에 수행한다. core dump limit0은 유지한다.
- dumpability1은 같은 OS identity의 일반 서비스와 동일한 관찰 가능성을 갖는다.
  현재 Yama ptrace_scope1과 사용자 분리, NoNewPrivs, capability 제거 및 기존 sandbox는
  유지한다. 이 조정은 root/worker 권한 추가 또는 credential 저장/복사 허가가 아니다.
- 수정된 보호 operator 자체를 호출한 무인증 커널 재현도 PASS였다
  (`fork-identity-proof-v3.jsonl`): proc 소유자0→990, 기존 identity validator PASS,
  잘못된 UID/GID 거부. 합성 operator 회귀15 PASS에는 root/capability 보유 상태의
  조정 금지, 실제 read-back 요구와 로그인 전 identity 검사 순서를 포함한다.

### 15:00 UTC tokenizer 입장 진단과 복구 범위

- 두 번째 실제 로그인·원 자료 재인가와 수정된 proc identity 검사는 성공했다.
  tokenizer unit은 시작 직후 exit1, output0byte로 종료했다. 모델 실행 전 실패다.
- 동일 sandbox의 읽기 전용 진단에서 native UID/GID978/975,
  supplementary groups `[975]`, prefix·보호 경로·phase import PASS를 확인했다.
  기본 GID가 그룹 목록에도 들어오는 systemd 동작을 임시 entry의 `not groups`가
  잘못 거부했다. 같은 기본 GID만 허용하고, root/다른 추가 그룹·혼합 UID/GID는 거부한다.
- 원 unit/입력/intent/빈 output은 변경하지 않는다. terminal failure와 invocation을 확인한
  명시적 tokenizer 복구1회만 별도 attempt unit/output으로 수행한다. 모델 forward0,
  동일 원 input pointer를 읽고, 기존 schema·canonical bytes·bundle·row count를 검증한다.
  완료 결과는 root 소유 sealed 임시 파일과 hash receipt로 고정한다.
- 후속 controller는 재인가된 요청의 정확한 raw hash가 원 입력과 같은 경우에만 이 준비
  결과를 재사용한다. 재토큰화·재표본화·새 benchmark identity·여섯 모델 실행 재시도는 없다.
  worker에 DB/NAS/인증 접근을 추가하지 않고 기본 그룹 이외의 권한은 늘리지 않는다.
- 추가 그룹/혼합 UID·GID 거부 테스트7 PASS. 실제 tokenizer 복구 unit은 exit0,
  MainPID0/active-exited로 종료했다. 기록을 유지하는 oneshot에 `--wait`를 사용한
  CLI 관찰자는135초에 timeout했지만, 이것을 native 실행 실패로 재해석하지 않았다.
  같은 성공 invocation `64929c8d3b4d441dba973c331007bb4d`의 원 output을
  재실행 없이 검증·봉인했다. 기존 실패/intent/빈 output과 관찰자 timeout도 보존했다.
- tokenizer 결과29행의 schema/canonical/bundle 검증은 PASS이며 모델 forward0이다.
  sealed receipt raw SHA는 `be46ad0f4353ecaf22371308e806ebdab5b156b5a54cd7dd63581ee5d3870170`.
  이는 benchmark 입력·성능·GPU 입장 PASS가 아니다.

### 실제 토큰 수 사전 검증: 최대 길이 fixture 수정 필요

- 원29행은 DOCUMENT18/QUERY2/공개9행이다. 기출 문장의 실제 token count는 모두2048 이하다.
  공개 overflow는2050, capacity 후보는2049로 관찰됐다. 이 encoder의 prefix/special token을
  고려하면 기존 임시 fixture의 반복 횟수가 잘못됐으며, capacity 계약은 정확히2048을 요구한다.
- 잘못된 capacity를2048이라고 선언하거나, truncation하거나, 한도를2049로 높이지 않는다.
  원 입력/hash/benchmark allocation/실패는 그대로 보존한다. 실제6회는 여전히0이다.
- 사용자에게 정확한2048-token fixture를 사용하는 새 준비 버전 승인을 요청했다.
  기출6개·원 source/Graph/policy·모델 payload·FP32 recipe·실행 순서·수치/성능/메모리 gate는
  변경하지 않는 범위다. 승인 전 원 revision의 내용을 덮거나 새 모델 실행을 시작하지 않는다.
  다음 로그인은 이 입력 검증과 남은 실행 준비를 먼저 닫은 뒤 요청한다.

### 사용자 승인 반영: capacity fixture successor 준비

- 사용자가 “그래 진행해”로 준비 버전 변경을 승인했다. 동일 logical benchmark
  `embeddingbenchmark_7255032ecfa2447d817d436ac141026b`의 새 immutable revision
  `embeddingbenchmarkrev_8e2d9b251b184a4fbfc39836a2221bb4`를 준비한다.
  원 `c6f434d8` revision과 실패 기록은 보존한다. 새 publication key로 revision을 구분하며
  알려지지 않은 실행을 우회하거나 모델 실패를 재시도하기 위한 identity 변경이 아니다.
- canonical source는 원 pin된6개 source/Graph/policy와 같은 모델 bundle이며, 준비 결과는
  재인가가 필요한 파생 local cache다. public capacity 문장만 `a `2045회로 수정한다.
  나머지28행과 source 선택/수치·성능·메모리 기준/모델·설치는 동일해야 한다.
- typed 기존 selection/token request와 JSON Schema 검증 후 local tokenizer를1회 실행하고,
  정확2048과 나머지28행의 원 token hash 일치를 확인·봉인한다. 현재 source 재인가를 통과한
  동일 request raw hash에만 결과를 재사용하며, 준비 cache가 사용자 권한을 대신하지 않는다.
  root의 고정 dispatcher와 기존 isolated native tokenizer를 재사용하고 DB/schema/queue는
  바꾸지 않는다. failure/retry는 독립 기록하며 모델6회는 새 revision에서 최초1회씩만 수행한다.
- 새 준비는 기존 native CPU capacity lock을 실제 owner UID로 획득한 뒤 실행했다.
  실제 tokenizer exit0,29행·capacity2048·다른28행의 원 token hash 일치를 검증했다.
  새 selection raw SHA `bcc22a6c8e1a7b4f98abfa9268d88643f3915573bc189cafc05a34277fa70f5f`,
  준비 receipt raw SHA `98ee009b9f11d716ace7c586d669357992fab918332b970fb03668356c19beb4`.
  실제 모델 forward0; 권한 재인가는 여전히 별도 필수다.
- controller는 root 소유 receipt/result/token bytes를 pin하고, 새로 재인가된 request raw SHA가
  정확히 같을 때만 읽는다. tokenizer 성공 상태를 덮어쓰거나 다시 실행하지 않는다.
  소스 재인가·여섯 실행·실제 token witness/수치·성능 판정은 기존 owner/worker가 그대로 맡는다.
- 새 준비/replay/identity/root6회 제어 비교 회귀31 PASS. 실험 wrapper의 Ruff·format·mypy
  검증과 실제 모델 비교는 분리한다. source PASS만으로 GPU 우수나 기본값 전환을 승인하지 않는다.

### 16:24 UTC 원 publication 완료 후 연결 경로 결함

- 실제 새 인증·source 재인가, 준비 cache 재사용과 input/policy publication이 성공했다.
  owner는 root listener의 read-only 사전 검사에서60초 뒤 종료했고, 그 후 root가 이미 종료 중인
  owner의 proc 메타데이터를 검사하며 출력한 오류는 2차 증상이다. native 모델 unit은 시작 전이다.
- `/run/eom-incremental-embeddings`는 의도된 root0711이다. owner는 통과할 수 있지만 목록을
  읽을 수 없다. 공통 protected-directory adapter가 모든 ancestor를 `O_RDONLY`로 열어,
  정상적인 통과 전용 ancestor에서 실패하는 결함을 조사한다. 접근 권한이나 validator를
  완화하지 않고 ancestor만 `O_PATH|O_DIRECTORY|O_NOFOLLOW`로 열고 실제 leaf는 기존
  `O_RDONLY`를 유지하는 수정과 커널 회귀가 필요하다.
- 책임은 Orchestrator filesystem adapter이며 source는 실제 열린 directory FD와 inode다.
  기존 owner/root/mode 및 종료 시 named inode 재검사, O(depth) FD/time, leaf의 fsync/read,
  symlink·writable ancestor·rename 거부는 유지한다. 새 schema/DB/queue/Artifact identity는 없다.
  read 권한 확대보다 통과용 FD를 사용하는 것이 작고 정확한 수정이다.
- Main 수정 commit `a63f8786`. 관련 source52 PASS, strict type/formatter/linter PASS.
  현재 보호된 owner SDK의 원 base `ee97239d`에 이 adapter와 회귀만 backport한 source는
  `933017f7ecc5bbc37094bdf97c7c71fd19ef36f8`이며 다른 기능 변경을 섞지 않았다.
  설치는 기존 owner installer/RECORD 검증을 사용했고 compatible API contracts wheel은
  그대로 재사용했다. 수치 CPU/CUDA prefix·모델·API/INDEX/QUERY 서비스는 바꾸지 않았다.
- 실제 root/owner UID 분리·NoNewPrivs 환경의 listener 경로/상호 SO_PEERCRED/start-ticks 검증:
  원 EE SDK는 FAIL, 설치된933 SDK는 PASS. 두 probe 모두 모델 import/run·로그인0,
  자기 socket 제거를 확인했다. 실행 전 소유자 검사와 namespace 검사이지 측정 PASS는 아니다.
  초기 새-SDK 설치 전 probe는 source provenance를 보장하지 못해 증거에서 제외했고,
  실제 import origin을 검사하는 `listener-*-validated.jsonl`만 위 판정의 근거로 사용한다.
- read-only Job inventory는 새 input `job_3c9f76226bb54b7286fd890bc5084c67`,
  policy `job_fcc3873936284ccaa1fb82b59f1c2886`의 SUCCEEDED와 measurement Job 없음을 확인했다.
  원 producer source EE/publication keys·time·bytes·Artifact pointers는 보존하며 idempotent
  publication replay만 한다. 새 controller release933은 실행 provenance로 별도 기록한다.
  root owner-request/configuration 파일도 정확한 hash replay만 허용하고 덮어쓰지 않는다.
- SDK RECORD에는 변경된 adapter를 포함해 실제9개 owner 경계 member를 검사한다.
  wrapper 회귀38 PASS에 기존 root recovery bytes의 충돌 거부/재작성 금지와9번째 member
  누락 거부를 추가했다. 모델6회는 여전히 시작 전이며 기본 CPU를 유지한다.

### 17:00 UTC 재인가 성공 후 SERIES 사전 진입 오류

- 실제 Studio 인증과 source 재인가, 원 input/policy의 정확한 publication replay가 성공했다.
  수정한 owner SDK933의 listener 확인도 통과했으므로 앞선 경로 결함은 재발하지 않았다.
  `SERIES` 진입 약1초 뒤 owner가 종료했다. root의 종료 중 proc 검사 오류는 이후의 2차 증상이다.
  첫 원인은 아직 미확정이며 source pin 결함이나 모델 실행 실패라고 단정하지 않는다.
- 17:04 UTC read-only indexed Job inventory에서 input/policy만 SUCCEEDED이고 measurement Job은
  없었다. 실제 native unit/launch는 시작 전이다. 새 Job/원 identity 우회, 실패 성공 재해석,
  root 보호 완화나 수치/성능 기준 변경은 하지 않았다. v4 실패 unit·frozen inputs는 보존했다.
- 재로그인을 요청하기 전, 같은 전체 unit sandbox와 실제 root/owner UID 분리 아래
  `STAGED_INPUT_PURE_CLOSURE`, `ACTUAL_OWNER_INSTALLATION_PREFLIGHT`,
  `ROOT_OWNER_LISTENER_NAMESPACE`를 모두 PASS했다. 실제 public policy도 지원된
  PinnedArtifactReadContext로 read-only 검증 PASS했다. 이 진단은 원문 근거 접근권한이나
  모델 실행 승인이 아니다. 모델 import/run·새 source 인가·DB 쓰기는 모두0이다.
- 설치된 owner 코드의 파일/줄 번호만 남기는 임시 진단을 추가했다. exception message,
  source line, frame locals, 문항 내용, credential은 기록하지 않고 SQL 오류는 frame도 생략한다.
  실제 최신 권한을 필요로 하는 남은 read admission은 가짜 사용자/DB state로 재현하지 않는다.
  source 수정 없이 exact 원 request를 재인가할 v5 finite controller를 별도 고정한다.
  wrapper40 PASS, Ruff/format 및 실제 의존성을 해석하는 strict mypy PASS다.
  최초 follow-imports=skip invocation의6건 타입 오류는 import 환경 문제로 별도 구분한다.
- v5 phase raw SHA `d23bd36552b8e76b268e8db77aa3130531f431c73f25534a186a28e1a5071f97`,
  pins `44c916022b0b738027b72fdfe738028838c28fe9c6a08e48624bef8580628207`,
  supervisor `70393f7e22efce8a3fc2381e575ac98823275f3293756319120c0cc7f0c43ee0`.
  원 benchmark/revision/input/policy/publication time와 모델·실행 기준은 그대로다.
  실제6회·수치/속도/메모리·공존·기본값 판정은 아직 PENDING이며 기본 CPU는 유지한다.

### 17:33 UTC 최초 오류 위치 및 source identity 호환 수정 설계

- 실제 v5 로그의 최초 frame은 Catalog `embedding_benchmark_sources.py:170`이다.
  로그인·source capture·publication replay·listener 모두 성공했고, 실행 Job을 배정하기 전
  report basis와 재인가된 Graph source를 비교하다 거부했다. 이후 root proc 오류와 구분한다.
- 실제 Graph는 원문 페이지/검수 acceptance를 포함한 V3 subtype을 재인가하지만, 기존 accepted
  solution profile은 같은 Item/member의 V2 core source를 pin한다. 전체 Pydantic 객체 동등성은
  같은 immutable Item/member라도 subtype/추가 lineage 때문에 false다. 두 형태를 주는 새
  회귀2건이 실제와 같은170행에서 실패했고, 나머지 기존/거부 회귀28건은 PASS했다.
- 책임은 Catalog benchmark source admission이다. canonical source는 기존 GraphRAG resolver의
  현재 실제 actor에 대한 완전한 source 인가이며 profile은 accepted report의 파생 pointer다.
  Item ID/revision/member의 schema/media/hash와 lifecycle core는 기존 공통
  `same_approved_item_source_identity`로 비교한다. request가 V3를 pin했다면 admitted V3의
  모든 page/acceptance/layout/bundle도 반드시 객체 전체가 같아야 한다. V3를 V2로 낮춰서
  바뀐 lineage를 허용하지 않는다. V2-only predecessor는 본래 계약에 담은 core를 비교하고
  실제 V3의 권한/lineage 검증은 기존 공식 resolver에서 그대로 수행한다.
- 새 schema·DB·queue·request/input/policy bytes·역사적 Artifact 변경은 없다. 기존 map lookup과
  O(6) source closure, 짧은 root transaction/종료 재인가/동일 요청 replay를 유지한다.
  단순 equality를 제거하거나 전체 source를 무조건 V2로 변환하는 대안은 V3 pin을 잃으므로
  사용하지 않는다. 실제 운영 재실행 전 source/negative lineage 회귀를 먼저 닫는다.
- Main source 회귀86 PASS. 동일 변경만 이전933 owner SDK에 backport한
  `c535b50bae8fe4dd209da1884724f84b49485e6e`도 호환 SDK import로86 PASS했다.
  최초 backport pytest의 ambient 최신 workflow/과거 contracts 혼합 collection 실패는
  source-only 변경이 아니라 test import 환경 불일치였고, 전체 compatible SDK를 지정해 해소했다.
  Ruff/format 및 두 source의 strict mypy PASS; 임시 wrapper40 PASS다.
- 기존 installer로 backport를 별도 root-owned release에 설치했다. 원 numerical CPU/CUDA,
  API/INDEX/QUERY, frozen source/input/policy/실패 이력은 그대로다.
  platform wheel SHA `344aa230a12c5f6f996cc5714757bad862ed28d34d872689c3948a285c21f8ae`,
  installed RECORD `1ed34a60936d251c878a800ad507638a89ba4f492433df37862bd10769bef87b`.
  새 helper/benchmark admission을 포함한11개 경계 member의 실제 bytes를 시작 시 검증한다.
  v6 준비는 source admission 수정의 운영 적용이며, 실제 비교 PASS나 GPU 기본값 변경은 아니다.

### 17:42 UTC 실제 최초 CPU 예약 후 root staging 권한 결함

- source admission 수정 후 원 measurement Job `job_324b59d7fde242bca60437cdacdf5def`가
  RUNNING이 되고 CPU1 `9b37158957804beeb4be83a8fd04f118`이 한 번 예약됐다.
  root는 `prepare_benchmark_environment`의 OSError 경계에서 실패했다. owner의
  `BENCHMARK_OWNER_EXECUTION_UNCERTAIN`은 이 오류 이후의 안전한 정지다.
- 실제 handoff output16개는 native UID978/GID1000의0640 빈 파일이다. `launch.env`와
  root-prepared/completion은 생성 전이고 `root-uncertain.json`은 원 handoff 아래 보존됐다.
  read-only indexed event 조회에서 RESERVED1개/RECORDED0개다. 현재 native unit은 없지만
  이 사실만으로 never-started 증명이나 재시작 승인을 만들지 않는다.
- root는 제한된 cap 집합에 DAC_READ_SEARCH만 있고 DAC_OVERRIDE는 없다. root preparation이
  worker writer adapter를 재사용해 검증 중 native 소유 output을 O_WRONLY로 여는 것이
  첫 실패 후보이다. 같은 권한의 실제 kernel probe로 읽기 허용/쓰기 거부를 확인한다.
  기존 합성 테스트는 native UID를 test UID로 바꿔 이 경계를 놓쳤다.
- 수정 책임은 기존 benchmark local-file adapter와 root handoff preparation이다. canonical
  source는 이미 봉인된 invocation/input과 실제 inode/ACL/UID/mode/empty-output snapshot이다.
  root에는 필요한 read-only staged-layout capture만 제공하고 native writer는 기존 역할을
  유지한다. 같은 검증 규칙·retained epochs·closed member set·inode uniqueness를 재사용한다.
  root의 쓰기 capability, worker 권한, ACL/mode, DB/schema/queue를 바꾸지 않는다.
  작은 read-only view의 O(member_count+depth) FD/검증 비용은 기존 capture와 같다.
- 단순 DAC_OVERRIDE 추가나 validator 우회보다 좁은 read-only adapter를 사용한다. 실패한
  원 execution 디렉터리·예약·불확실 기록은 고치거나 삭제하지 않는다. 현재 구현에는 이
  pre-launch reservation의 같은-ID resume가 없으므로 수정 후 `run_launches` 재호출이나
  새 execution ID로의 자동 우회는 금지한다. 재개는 별도 지원된 복구 설계/판정 전 PENDING이다.
  추가 로그인은 이 경계를 닫기 전 요청하지 않는다.
- 실제 제한된 root capability fixture에서 읽기 open은 성공하고 native output의 쓰기 open은
  EACCES로 거부되는 것을 확인했다. `restricted-root-capture.jsonl`의 PASS는 정확한 DAC
  재현이며 source/DB/native/model 작업은0이다. 권한을 늘리거나 운영 파일을 만지지 않았다.
- `BenchmarkRootStagedFiles`를 기존 capture 모듈 안에 추가해 validation/retained epochs는
  공유하고 output FD만 O_RDONLY로 연다. public write API는 native writer에만 남겨 root view는
  노출하지 않는다. 생성·context 진입 때 root를 확인하며 정본/member/hash/ACL/mode/empty 및
  inode uniqueness/변경 감지 검증은 유지한다. parent 코드 검토와 독립 검토를 거쳤다.
- 회귀: capture/environment/handoff128 PASS + opt-in12 SKIP, 별도 worker/entrypoint/CPU/CUDA/
  root/series210 PASS(앞 cohort와20개 겹치므로 단순 합산하지 않는다). Ruff/format, core2개
  strict mypy, diff checks PASS. 새 environment 회귀는 수정 전 원469행에서 FAIL했다.
- 더 중요한 실제 OS gate는 root/root·supplementary group 없음·NoNewPrivs1·DAC_READ_SEARCH
  있음/DAC_OVERRIDE 없음·실제 native/workflow UID 분리에서 full environment preparation
  1 PASS/2.31초다. 자체 private /run fixture만 사용했고 실제 owner proc 출생 확인,
  native output write 거부·readonly root capture·launch.env0600 생성·output16개가 끝까지
  비어 있음을 확인했다. unit `eom-gpu-root-read-capture-source-gate-20261020`, invocation
  `f4807d20198d49da98ecfdc5396e9550`. 실제 모델/운영 원 execution을 재실행한 것은 아니다.
- 원 execution의 CPU service/socket은 inactive/dead, InvocationID 없음, start/exit monotonic0,
  MainPID0·cgroup/pending Job 없음이었다. root failure가 driver 전에 발생한 코드/기록과
  함께 해석한다. 이것만으로 지원되지 않는 resume 권한이나 성공 receipt를 만들지 않는다.
  원 Job은 여전히 RUNNING+unresolved reservation으로 보존돼 있고 새 키로 우회하지 않았다.
- 감사 결과 generic eomctl/public Job cancel/fail 경로도 없다. private `_fail`/직접 state
  transition은 benchmark 인가·근거 검증 use case가 아니므로 사용하지 않는다. 향후 복구는
  frozen series의 재시작 금지를 묵시적으로 바꾸지 말고, 사전 실패 증거와 fresh actor를
  검증하는 명시적 supported application/append-only 판정부터 설계해야 한다.
  이번 source 수정은 그 복구 기능이나 실제 CPU/GPU 측정 완료를 뜻하지 않으며 아직 미배포다.

### 2026-10-21: 원 pre-launch 실패의 명시적 정리 경로

- 설계 문서 `docs/architecture/EMBEDDING_BENCHMARK_PRELAUNCH_FAILURE_RECOVERY.md`와
  additive JSON Schema2020-12/Pydantic 계약을 먼저 추가했다. released benchmark1.0,
  launch-control1.0, 원 Job/예약/uncertainty와 출력16개는 바꾸지 않았다.
- 새 use case는 실제 root가 확인한 never-started 근거와 현재 실제 관리자/GraphRAG source
  인가를 대조해 원 RUNNING Job을 FAILED로 기록한다. 재실행·성공 receipt·모델 실행이
  아니며, 정확 replay는 원 결정/시간/sequence를 반환한다. 종료 전 OS/source/Identity
  검증 실패는 같은 SQL transaction을 rollback한다. 원 행 직접 수정이나 private `_fail`
  호출은 하지 않았다.
- root proof는 원 handoff 밖의 고정 recovery 경로에 create-once0440으로 둔다. 원 invocation과
  빈 output은 read-only FD로 검증하고, owner는 root-origin/hash/ACL/inode·ctime와 실제
  controller/CPU service/socket/boot/process/deadline 상태를 독립적으로 재확인한다.
  parsed JSON은 권한이 아니며, source와 ADMIN 인가는 기존 genuine capture/fence로 수행한다.
- 후속 revision은 원 FAILED 판정의 Job/event/hash를 명시적으로 pin해야 한다. logical
  benchmark/source/모델/recipe/행/input-set은 그대로이고 원 revision과 input Artifact도
  보존한다. source 입력을 다시 만들거나 토큰화하지 않는다. 후속 등록 시 원 input Artifact의
  현재 lifecycle/권한 검증은 기존 Catalog admission으로 별도 수행해야 하며, projected hash
  일치만으로 대신하지 않는다.
- 관련 최종 source gate는327 PASS/5 opt-in SKIP였다. 개별 suite의 이전 결과를 여기에 더해
  총계로 부르지 않는다. core7개 strict mypy와 변경 Python15개 Ruff/format도 PASS다.
  중간 회귀에서 partial proof write의 OSError를 기존 directory adapter가 CpuHandoffError로
  변환하는 것을 확인해 새 inspection 경계에서 안정된 코드로 정규화했다. 부분 파일은
  삭제/수리/덮어쓰지 않는다. capture context 종료는 FD/lifecycle 정리만 하고, 의미 검사는
  application이 commit 전에 명시적으로 수행해 commit 이후 검사가 허위 실패를 만들지 않게 했다.
  disposable PostgreSQL 동시성4건과 실제
  root/owner/native DAC gate는 아직 NOT_RUN이다. 새 코드도 아직 운영 SDK에 설치하지 않았다.
  실제 원 Job closure0, 새 measurement launch0, 모델 forward0, 기본값CPU 유지다.

### 별도 운영 상태: INDEX owner 중단

- read-only 확인에서 INDEX owner가2026-10-21 06:18:20.957361 UTC에
  `EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE`/`LOCAL_INDEXING_RUNTIME_UNAVAILABLE`로
  종료했다. 당시 installed source는 `e013d35013851a8a5a7b50b8bee9c40edd90568c`다.
  마지막 관찰된 INDEX command는06:16:08.881656 UTC에 SUCCEEDED였다.
- 같은 초에 apt-daily-upgrade가 PID1 reexec를 요청했으므로 일시적인 systemd/D-Bus 영향이
  후보이지만, 거부된 subprocess의 stderr/return code가 없어 원인 확정은 아니다. GPU 실험이
  원인이라고 단정하지 않는다. API/기존 QUERY 서비스는 active이며, API ready가 INDEX의
  가동/신선도까지 보장하는 것은 아니다. 이 확인 과정에서 restart/reset/DB 변경은 하지 않았다.

### 실제 복구 gate와 좁은 owner SDK 설치

- Main `b8f3e411`은 pre-launch 실패 정리 계약/application/inspection과 source327 PASS다.
  `6570049d`는 실제 제한된 root 테스트의 임시 owner0700 디렉터리 정리만 고친 test 변경이다.
  최초 DAC 실행은 핵심 assertion 이후 fixture cleanup 권한 오류로1 FAIL/1 PASS였으며,
  실패 unit/출력을 보존했다. CAP_DAC_OVERRIDE를 추가하거나 제품 검사를 완화하지 않았다.
  새 별도 unit의 같은 두 실제 root/owner/native filesystem gate는2 PASS/2.96초다.
  proof DAC fixture의 machine 관측은 합성이며 실제 원 실행 관측과 구분한다.
- 새 guarded disposable DB `/tmp/eom-api-testdb-20261021152609_40fe6f19`에서 공식 prepare,
  migration cycle/reconcile 후 embedding-encoding cohort29 PASS/45.80초였다. 그 안에 새
  prelaunch 동시 closure/replay/rollback/successor4건이 포함된다. 공식 `--confirm` cleanup으로
  DB/임시 role을 제거했다. 운영 DB를 pytest 대상으로 사용하지 않았다.
- 동일 필요한 수정만 c535 SDK에 backport한 source는
  `c7dd3288bd6793d67885de99b7511043da6f3386`이며 compatible SDK source327 PASS,
  core9개 strict mypy와 Ruff/format PASS다. 기존 installer로 별도 immutable prefix에 설치했고,
  numerical CPU/CUDA prefix·기존 API/INDEX/QUERY release는 교체하지 않았다.
  platform wheel SHA `206f036bc9d99943322e8a25a81b86a9281c9e4d0afb6c78fa4a913f4d85c7e7`,
  installed RECORD `32003c456baec90e340dc38efd134feaf8a05b265bdcd83c9d440c9f5dc7436c`.
  기존 API contracts wheel `91ffbea4f187ae3c5323c244c4e6a65780152959b5fff3586517f8ebf9fcaa50`
  는 그대로다. wheel600 사전조건과 installer의 Bash invocation 오류는 실제 설치 전 발생했고,
  bytes/검증을 완화하지 않고 정정했다. OWNER_ACTIVATION=NOT_PERFORMED다.
- 실제 원 v6 controller/CPU service/socket/boot/process/빈 output을 새 설치 SDK로 확인하고
  root proof1개를 원 handoff 밖에 create-once로 생성했다. root helper는 NAS/DB 접근이 막힌
  제한된 capability unit에서 성공했다. proof RAW SHA는
  `4f155e819e848eba1e4bd6c1487e384aa6b30d68c192b8bb9bb26fd11dcfb681`, observation SHA는
  `ed30220cdeb5482291fcf2930dd782a30ea5d28d08b05339cc18d3faf1d9352b`다.
  이것은 OS 관측이지 current actor 인가나 Job closure가 아니다. 원 Job/예약/uncertainty는
  그대로이며 actual closure0/모델0/defaultCPU다. 실제 owner read-only proof probe는 준비만 했고
  아직 NOT_RUN이다. Studio 로그인을 추가 요청하지 않았다. 기존 pane의 sudo cache를 재사용했다.
- 후속 finite wrapper는 `/tmp/eom-gpu-recovery-20261021.RFshJFka`에 DRAFT로만 있다.
  pure/mocked10 PASS이며 root proof→genuine capture→원 실패 closure commit→실제 parent
  admission→revision-only input→같은 SQL root의 guarded successor→기존6회 순서다.
  새 revision `embeddingbenchmarkrev_4e40dad6e4c946abaa01815537d28952`는 계획 값일 뿐,
  Artifact/Job/launch로 등록되지 않았다. 토큰 재생성도0이다.

### 새로운 STOP: OS 보안 업데이트와 고정 host closure의 불일치

- 기존 INDEX service를 정확한 기존 release 그대로1회 supported start했다. Invocation
  `1002a26157454e4189fbd291a2942bf7`는 잠시 running 후15:36:08 UTC에 실패했다.
  이번 실패는 이전06:18의 systemctl 경계와 다르게 fixed no-forward CPU verifier의 nonzero
  결과(`local_indexing_runtime_verification.py:40`)다. verifier stdout/stderr가 폐기돼 직접
  exception은 확인되지 않았으며, 추가 실패가 전혀 없다고 주장하지 않는다.
- 별도 read-only 확인으로 현재 host의 필수 불일치가 확정됐다. 설치된
  `embedding_runtime_host_closure.py:209`는 `/usr/lib/x86_64-linux-gnu/liblzma.so.5.4.5`의
  SHA `696e868dd0700a19a6d65fc01608ec2d70d3cb91f65710e89180cd2e688f30cb`를 요구하지만,
  현재202904-byte 파일 SHA는
  `26b37d25f7ca2a2d348de8ecabacda12e921cd933b21fa069a179760db77219d`다.
  dpkg.log는06:18:18 UTC의 `5.6.1+really5.4.5-1ubuntu0.3`→`…0.4` 업그레이드를 기록하고,
  파일 ctime도06:18:18.961272845 UTC다. host snapshot 예외는 ld.so.cache만 대체하며
  liblzma에는 적용되지 않는다. 따라서 현재 host는 기존 승인 검사를 통과할 수 없다.
- 현재 eom 사용자의 같은 nine-property systemctl read는 rc0/stderr0/272bytes였지만,
  이것은 실제 service UID 인가 증거도, 이전06:18 실패 원인의 확정도 아니다. API/QUERY
  service는 active지만 새 native 작업/색인의 정상 동작까지 PASS로 확대하지 않는다.
  INDEX는 failed/Restart=no/NRestarts0다. 추가 start/reset/검증 우회는 하지 않는다.
- 기존 host hash/receipt/configuration을 현재 bytes로 덮거나 OS 보안 패키지를 downgrade하지 않는다.
  기존 numerical runtime을 고정한 benchmark successor에 새 host를 묵시적으로 섞어서도 안 된다.
  실제6회 진입은 보류한다. 다음에는 기존 승인 기록을 보존하는 명시적 host compatibility
  재검증과 필요한 successor runtime/configuration 범위를 먼저 검토·승인해야 한다. 이는 현재
  'runtime pin 불변' 실행 범위의 변경점이며, 추가 로그인만으로 해결되지 않는다.

### 승인된 host successor — source와 실제 host bytes PASS, native 전환 전

- 사용자는 이전 승인 기록을 보존하는 별도 OS 환경 재검증을 승인했다. 설계는
  `docs/architecture/EMBEDDING_HOST_REQUALIFICATION_2026_10_21.md`에 기록했다.
  Main source `2e6bae5e`는 기존 host tuple/hash/default를 보존하고 liblzma 한 파일만 다른
  명시적 baseline을 추가했다. 기존 snapshot1.0/runtime config1.1/1.3 포맷은 바꾸지 않았다.
  관련 source cohort306 PASS, Ruff/format/strict mypy PASS다. 넓은 검사에서 발견한
  schema-count4건은 clean predecessor75755294에서도 같은 실패이며 별도 미해결로 남긴다.
- CPU/owner compatible source `6c4cd95f709ba66756bfcbe2c4528b94cf3622ea`와 CUDA source
  `87cc21d68b0b2584c2b683844aea67d759e5bb02`는 각 기존 릴리스에 같은 host 변경만 적용했다.
  각각 같은 관련 source306 PASS이며, 이를 합산해612개의 독립 검증이라고 표현하지 않는다.
  두 공개 수치 runtime/세 numerical implementation 원본 bytes는 각각의 predecessor와 같다.
  두 wheel의 RECORD 검증도 PASS다. CPU/owner wheel raw SHA는
  `11467ef059c8b4ea2bbeb9ac1c1cc72c04cde514649cca9d304547d2f02f0ee5`, source tar는
  `51b4b800859dd8fb0ffd1489d31c1c8a2b8f50d8b6340e60ae352292df982a45`다.
  CUDA wheel raw는 `ec5cb5ef02d2f72776b39013dd0e64313c07931a158017a63ba06efdec7ea19b`,
  source tar는 `245716057beafe7f59a686a438d05aa3c62a8277432bdba850bdae05998f7399`다.
- 기존 설치기로6c4 owner SDK만 새 immutable 경로에 설치했다. RECORD raw는
  `0a92d35b5a8c5757adc30c37a0b19a4b4704b3663fca7bf390842026a15438a2`다.
  API contracts91ffbea4는 유지했다. 설치된 host readers의 actual OLD `-I -S -B` import는
  stdlib-only PASS이며 모델/DB dependency를 불러오지 않았다. 이는 native admission이 아니다.
- 16:41:04 UTC 새 snapshot revision `embeddinghostconfigrev_c1266b6dbab44ffea078ea6dd455f935`
  (logical bd45 유지)을 root create-once로 발행했다. raw721-byte SHA는
  `466b8169012fc4d2931e64d1bf04463414237d15328dd463eaa0d68757f97d94`, semantic은
  `b1b42f01f656dfbff7a5ce35266371eec86786ff44d00aae49e6ab18e5151023`다.
  기존 snapshot raw c0f405d7는 그대로이고 selected-cache도 바꾸지 않았다.
  실제 root 보호 코드/캐시 mount namespace에서 shared stdlib host closure가 PASS했다.
  두 root unit은 capability를 비우고 NAS/인증/DB secrets/모델 접근을 막았다.
  host-byte unit Invocation은 `b629e3dbe3e746e49f5bcac638260be4`다.
- CPU audit1.1 준비 입력은 `/tmp/eom-host-requalification-20261021.pZw7NbCi/prefix-audit-input.json`,
  raw `6dd3608901491d425b85e9e4edd7135bfd845587e31a33720f6e85dfe2b5def6`이며
  host pointer/seed, private archive, 필요한 bootstrap2개만 predecessor19a559b3에서 달라졌다.
  이 사용자 소유 입력은 UNTRUSTED이며 root byte audit/admission을 대신하지 않는다.
  native CPU config candidate revision38786bb0은 아직 게시·승인되지 않은 계획 값이다.
- 이 시점 native CPU/CUDA prefix 교체0, 서비스 설정 전환0, 실제 모델/GPU forward0,
  원 benchmark Job closure0, GPU default 미활성이다. INDEX는 여전히 같은 failed invocation이며
  QUERY는 active다. 다음 단계는 scoped INDEX/QUERY 유효 claim/실제 native holder 부재 확인,
  기존 private-successor 설치·OLD byte audit·actual no-forward probe/seal·linked control 전환이다.
  전역 Codex 작업 부재를 이 prefix의 필수 계약으로 오용하지 않는다. 별도 원 benchmark의
  never-started OS proof와 unresolved Job은 보존하고, 실제 인가된 closure는 뒤에서 수행한다.

### Scoped CPU 전환 — 실제 byte audit와 host-only 설정 게시

- 16:53:50 UTC 현재 INDEX/QUERY의 유효 claim이0임을 실제 read-only 조회로 확인한 후
  QUERY만 정상 중지했다. INDEX의 failed invocation `1002a26157454e4189fbd291a2942bf7`는
  reset하거나 성공으로 바꾸지 않았다. 원 benchmark Job과 pending command도 보존했다.
  root stopped-unit snapshot raw는
  `11c66291df7ee00b8f2944d7c779ba9709f2126b77c8b8cd48f3d18d187ae4da`다.
  quiescence는 세 local-embedding queue의 유효 claim, 실제 native/prefix holder와 원
  never-started proof를 검사하며, 전역 Codex 작업이 없을 것을 요구하지 않는다.
- 첫 CPU publication invocation `7208e8829a05403187f82339a6d0fcf9`는 사용자 입력 경로의
  첫 임시 디렉터리 mode가775라서 기존 source 경로 guard가 거부했다. prefix 이동/overlay
  전 실패였으며 검사를 완화하지 않았다. 당시 생긴 빈 root archive 예약은 실제 비어 있고
  accepted bytes가 없음을 확인한 뒤 `.failed-empty-<invocation>-11467ef0` 이름으로 보존했다.
  보존 record raw는 `28dca439a9451f15e629968c5216658481ea1018b581bf174c556238e853e76c`다.
  같은 wheel/source bytes를 명시적0700 input 경계에 materialize하고 기존 guard PASS 후
  별도의 유한한 두 번째 operation을 실행했다. 이는 모델/benchmark retry가 아니다.
- 두 번째 publication invocation `7c577e85c1594701aafe1933abea12c5`는 기존 installer의
  OLD Python 기반 전체 prefix byte/source/ELF audit를 통과했다. inventory raw는
  `7323f2005af2e82e6eea3f747b16df7d1e4ae080b380c12f4ff95a1d6d649a25`, semantic은
  `1ee572cbec0c5e73f648746547190b8cceda6d05dc03fbb6271abf172b0f8cca`다.
  regular27509/link1380/ELF356, 전체30984 entries를 검사했다. old CPU prefix는
  `/opt/eom/conda/envs/.embedding-index-prepublication-CPU_INDEX_FP32-.embedding-index-install-ayICWfww`
  에 보존했다. 별도 root reader도 실제 inventory/boot와 수치 구현3개 bytes를 확인했다.
  이 시점의 상태는 `BYTE_AUDITED_NOT_ADMITTED`이며 runtime 성공 receipt가 아니다.
- host-only native configuration revision `embeddingnativeconfigrev_38786bb0953d4835ae05b1c0fd5e06d6`
  를 root create-once로 게시했다. raw는
  `b3a92c7c9f272fc82bc4c92739423d992dd1b03bc710307691c1bf35ffe4e1d2`, semantic은
  `84c7eb05deeb4e295133afce373ae01b7103561f47b6f3ca82df26f16536a3e9`다.
  기존 bundle/proof/수치 runtime/모델/ACL은 그대로 재검증했다. 실제 생성된 native probe
  execution은 `0e44028083874e07b7521e9db167a78d`, input raw는
  `5528a43e878feb6139f8e6e9cb11b4a35121b5b73f7ac20a31cdc0c2150ef9a0`다.
  이 metadata publication은 모델을 생성하거나 forward하지 않았다.
- owners가 계속 중지된 상태에서 `selected-cache`를 기존 snapshot의 절대 경로에서 정확한
  새 c126 snapshot의 절대 경로로 CAS했다. old/new cache bytes는 같지만 inode는 다르므로
  hash만으로 mount identity 검사를 대체하지 않았다. 두 immutable snapshot은 모두 보존했다.
  actual scoped root observation과 cache CAS가 PASS했다. 이후 실제 native probe/seal,
  연결된 여섯 control 전환과 서비스 복구가 필요하며, 이 기록만으로 완료를 선언하지 않는다.
- CUDA host publication의 별도 source 검토에서 cache builder가 옛 `_FILES`를 직접 사용하는
  경계를 발견했다. 새 baseline을 허용하는 capture/closure와 별개인 실제 누락이므로
  reviewed baseline 선택 helper를 cache builder에도 명시적으로 전달하는 좁은 수정과
  old/new/unknown/drift 회귀를 준비한다. old host 파일을 bind하거나 검증을 우회하지 않는다.
- 첫 native metadata probe invocation `b08e3e1ca10d499c820be2b594afdd13`는 UID978/GID975,
  모델 constructor/tokenizer/forward0으로 실제 report/live process maps/ACK/terminal 검사에
  성공했다. 그러나 같은 root operation의 seal helper가 이미 읽은 config를 같은 file ledger로
  다시 읽어서 `INSTALLED_RUNTIME_REPEATED_BYTE_READ`로 거부됐다. 뒤이어 inventory schema도
  같은 문제가 있음을 source 검토로 확인했다. 제품의 중복 읽기 guard는 올바르게 동작했으며
  이를 완화하지 않는다. root operation `2b63f47cb04c4786aa0e5bff589eefd0`의 실패/observation,
  실제 native 성공 unit과 모든 원 파일을 보존했다. 설치 receipt는 아직 성공으로 게시되지 않았다.
- 수정은 같은 live observation의 sealer에 이미 검증한 typed config/raw와 schema raw를 전달하는
  것이다. saved observation JSON을 새로운 admission 근거로 재사용하지 않는다. old probe가
  실제 성공 종료/PID0/cgroup empty이고 owners가 계속 quiescent임을 root에서 재확인한 후,
  설정·prefix·모델을 다시 만들지 않고 metadata 검사 한 건만 새로 준비했다. execution은
  `0091eefed7394700a1f5f2d9accde0c3`, input raw는
  `338f5e4dcbba48761fdda0c96160c582cdc0f5111240212b0d7c92f126d0c256`다.
  이전 attempt 디렉터리를 덮거나 같은 unit을 재시작하지 않으며 native probe forward는0이다.
- 두 번째 실제 native invocation `49a1aafe00b24734bfb89564ff06a088`는 같은 UID/GID/수치
  runtime으로 live process/ACK/terminal 검사를 통과했고, 같은 live 관측에서 seal과 독립
  installation reader도 PASS했다. receipt raw는
  `04185f7a8563fd46a9124b3d64f30959cda8cc52b774fee890a2dfb690f7f14c`, semantic은
  `d94915c67b1bb666004d06dc1efd8e90b6307ca978dc5409aaf22d465b23e78e`다.
  root final-seal record raw는
  `8f57ecc8f5ecd519459c7b18a6cdad5e72a818f8227289fd1c10134034dd33c3`다.
  이는 새 CPU 설치 승인이지 서비스 전환/원 benchmark closure/GPU 측정 완료가 아니다.
- 첫 linked PREPARE operation `bf85ae1dc1b24943a0c291dd0902ba5f`는 staging이나 control 수정
  전 mixed owner DTO import에서 거부됐다. 숫자용 prefix6c4는 c535 SDK에 기반해 운영 e013의
  mixed owner4.0/V2 DTO가 없었다. 운영 schema를 낮추거나 임의 JSON으로 수정하지 않는다.
  해결 범위는 현재 e013에 검토된 host3개 모듈만 적용한 별도 maintenance SDK다. root selector는
  첫 EOM import 전에 그 한 SDK를 명시적으로 선택하고, numerical prefix/interpreter와 새
  receipt는 유지한다. 서로 다른 SDK의 module 객체를 섞거나 새 projection protocol을 만들지
  않는다. 실제 설치 SDK를 사용하는 pure projection 검사를 activation 전에 추가한다.
- maintenance SDK `2e5b22f35cb9e1bdaf7109aab461bfc0332fb33d`를 기존 installer로 별도
  root 보호 경로에 설치했다. 설치 platform wheel raw는
  `805a657001bb583cfc042f874ad4acc2cc3d5970e0b127ef62a44f67e6b86c91`, 현재 e013과 짝인
  API contracts wheel raw는 `54beca4d3e9a9074f2676fd53e2174c4f787e5af852ac7daa8f123531f06c182`,
  installed RECORD raw는 `2417cb35405200df03d86d6be88afe4eba23097ebb064e4ed3dc9e03b07c207e`다.
  e013과 다른 source 파일은 host3개뿐이며, 기존205+host5 source tests와 Ruff/strict types가
  PASS했다. **metadata SDK는 numerical backend가 아니다.** e013의 기존 ranking helper 파일
  bytes가 native6c4와 다르므로 numerical3개가 모두 같다고 주장하거나 이 SDK로 backend를
  교체하지 않는다. 실제 native inventory/receipt와 별도6c4 verifier는 그대로 사용한다.
- v2 selector는 import 전에 두 보호 wheel의 EOM package payload와 설치 파일을 대조하고,
  예상하지 않은 최상위 EOM namespace를 거부한다. 이후 EOM module이 모두 같은 SDK에서
  왔는지와 파일 epochs를 유지·확인한다. ML 및 numerical 구현 module import도 금지해
  metadata-only 경계를 검사한다. source main의 임시 PYTHONPATH 성공으로 대신하지 않고,
  실제 NEW CPU interpreter + 실제 설치 SDK의 pure projection이 PASS했다. 여섯 output과
  verifier `04294a14748dbacd2dd0043320103211b43e28aaac80e320bc1c17f44fdf9ef8`가 고정 기대값과
  같았으며, 이 smoke의 service/DB/file write/model run은 모두0이다.
- v2 실제 PREPARE는 같은 새 host namespace의 native admission, scoped quiescence, 여섯
  old control/unchanged control pins를 확인하고 새 verifier/전환 manifest만 준비해 PASS했다.
  manifest raw는 `cdd61fc44d56cd043968b6b559def78e2e9eb8800cc4a1e3f24eb178cc26b9ca`다.
  실제 SELECT와 서비스 시작 성공은 별도로 관찰해야 하며 이 기록으로 선취하지 않는다.
- 실제 v2 SELECT도 같은 manifest로 PASS했다. 여섯 control CAS/readback 후 한 번만
  daemon-reload했고, 이전 failed INDEX 기록과 QUERY의 quiescent 상태를 재검사했다.
  이후 supported start로 INDEX 새 invocation `6f2efbb34a8b4744ab30bf876a7fd612`/PID1983190,
  QUERY 새 invocation `90dbe3e364fa4589930e4a33f5b0e60f`/PID1983188이 시작됐다.
  INDEX `LOCAL_INDEXING_SERVICE_STARTED`는17:45:50.303152 UTC,
  QUERY `REFERENCE_QUERY_OWNER_READY`는17:46:06.149327 UTC에 실제 기록됐다.
  Catalog 자료 조회의 lock/provenance/candidate/solution-profile/materialization 단계도
  COMPLETED로 진행됐고, 두 서비스는 후속 관찰에서도 같은 invocation으로 active였다.
  기존 INDEX source e013과 QUERY source `2eef9b20bbd9f1394efc8d1566fada8d37769f66`의
  실제 ExecStart는 그대로다. Identity/policy/grants와 실패 이력도 보존했다.
  따라서 `CPU_INDEX_QUERY_RECOVERY=PASS`다. 이는 GPU/default 또는 교육 품질 PASS가 아니다.
- Slack `devreport_fd44c1dc3c80408a82b9680c9767dbb4`에는 실제 native admission과 전환 전
  상태를, `devreport_63624820801c405888336c32a00552b0`에는 복구 완료를 한국어 요약 먼저
  보고했다. 다음 실제 CUDA 단계용 SDK072도 별도로 설치했지만 native prefix/GPU device/
  backend/default는 활성화하지 않았다. GPU 비교를 위해 Studio 재로그인을 아직 요구하지 않았다.

### CUDA host34ed — same-ID completion PASS, native admission pending

- 기존 source와 같은 일곱 library/driver580.126.09/tool을 실제 해시로 확인하고,072 SDK의
  stdlib publication owner를 설치했다. original RDMA 파일의 private0700 부모/UID1000/
  0444/단일 링크는 유지했다. root view는 원자적인 mkdir로 새로 예약하고 PID1 단일 파일
  read-only bind로 제공했다. 실제 bound source device64512/inode9576921도 고정 검사했다.
  root publication은 model/device/NAS/DB/secrets에 접근하지 않는다.
- 실제 unit invocation `98588123156e4dc2b0f1df4e790bae19`는 일곱 payload, 새 cache,
  snapshot을 완성했지만 마지막 `os.rename(stage, final)`에서 EXDEV로 실패했다.
  원인은 outer unit의 두 별도 ReadWritePaths bind mount였다. underlying device가 같아도
  mount 경계가 갈리면 atomic rename이 거부된다. CPU 두 서비스는 같은 PID/invocation으로
  계속 active/READY이며 실제 Catalog 조회도 진행됐다. GPU/model forward는0이다.
- 실패 당시 complete stage와 failed unit을 보존했다. 새 ID로 우회하거나 publish를 반복하지
  않고, 기존 publication owner에 exact typed pointer를 받는 explicit completion 경로를
  설계·구현·회귀 검증했다. 후속 namespace는 common CUDA root 한 mount와 lock만
  writable로 지정하고, 같은 revision의 검증된 stage를 atomic commit하도록 한정했다.
- root read-only 관찰에서 staged manifest는2325 bytes,
  raw `34b9427d01f5d9cdeb956147cbe4809fd2c39578510982fa9dc82972559eb482`, semantic
  `486dd1ca5de50596ea7f9252ec9aae5fac85c93e74af0ab78bcf8a50ab6b529f`다.
  새 loader cache는2319 bytes,
  `65171e487533d81862e3e56df880e600a683517b72aae2364179cd8a1810097c`, CUDA host seed는
  `8d9e9e5befeb5ec2a322ae2444ea3ec70800762b15595b122ce63f6c2bbc1330`다.
  base는 정확한 c126이고, 일곱 library/driver는 기존 값과 같다. 이 관찰 시점의 상태는
  **STAGED_ONLY**였으며, 아래 실제 completion 결과와 구별한다. host publication 자체는
  native admission이 아니고, 후속 audit generator는 DRAFT를 유지한다.
- 기존 publication adapter에 public `complete_cuda_host_extension_publication(request,
  expected_pointer)`를 추가했다. typed pin/manifest/base/compiled recipe, 전체 retained tree,
  modes/ACL/link/hash/cache outcome/late epochs와 같은 lock을 확인한 뒤 기존 ID의 rename만
  수행한다. 원 publish의 partial-workspace 거부는 유지했다. shared commit은 최종 디렉터리와
  양쪽 변경 부모를 fsync한다. builder/모델/worker는 다시 실행하지 않는다.
  focused80 PASS, 관련 cohort379 PASS/known registry-count assertion1건만 명시적 제외,
  Ruff/format/strict mypy/diff check PASS다. 이 source 검증과 실제 completion은 별도 gate다.
- 검토한 completion만 기존072 owner에 backport한 SDK
  `532a2f43c99055d2abed1bd6ab99fcca91991c4c`를 별도 immutable 경로에 설치·검증했다.
  platform wheel raw는 `94ef9f26597b31e41d74bf5de24c38595a8882c8a28de2d6316c834ba50debfd`다.
  API contracts91ff pair의 RECORD 검증과 실제 설치 검증은 PASS였고, numerical3개
  `3487…/440d…/f667…`와 CPU numerical prefix·owner selection은 바꾸지 않았다.
  유한 completion helper raw는
  `87404626cd5106ed6bd40c3df142a83eceac0039b3b078f480fd255f2b5845b6`다.
  원 helper의 root 보호 ancestor/regular444/단일 링크와 FD epochs를 확인하고, 정확히
  hash한 동일 bytes만 실행한다. OLD Python3.12.13/고정 self path도 확인한다.
- 실제 `eom-cuda-host-complete-34edecbf.service` invocation
  `7a7cc84733274521be45f3ac70df950e`가 같은 logical99ec/revision34ed를 `CREATED`로
  완료했고, 독립 public resolver readback도 PASS했다. 위2325-byte manifest raw/semantic,
  2319-byte cache SHA와 CUDA host seed가 정확히 같았다. root-private payload를 common
  CUDA root 안에서 한 번 rename하고0555로 봉인했으며, 별도 cache builder·ldconfig·모델
  실행은 모두0이다. RDMA source/view를 다시 읽거나 bind하지 않았다. 원 실패 invocation
  `98588123156e4dc2b0f1df4e790bae19`와 retained builder evidence는 그대로 보존했다.
- 따라서 `CUDA_HOST_PUBLICATION=PASS_NOT_NATIVE_ADMITTED`다. CPU INDEX/QUERY는
  PID1983190/1983188과 invocation6f2e/90db가 그대로 active였다. CUDA prefix successor,
  실제 no-forward native probe/seal, benchmark 원 Job closure와 여섯 비교는 아직 pending이며,
  GPU default는 활성화하지 않았다. host 발행 성공을 GPU admission·성능 PASS로 확대하지 않는다.

### CUDA prefix·no-forward probe·receipt·retirement — 실제 PASS

2026-10-21 18:36:03 UTC 기준 후속 결과다. 위 host publication 직후의 pending 기록을
덮어쓰지 않고, 실제 설치 검증과 실제 native no-forward 검증이 끝난 시점을 구분한다.
**여섯 CPU/GPU 모델 비교와 조건부 GPU 기본값 전환은 아직 완료되지 않았다.**

- 기존 `publish-private-successor CUDA_INDEX_FP32`를 실제 physical GPU lease가 유지되는
  유한 parent 안에서 실행했다. publisher invocation은
  `392cfc21c25740e89650f97f43265319`이며 성공 종료했다. installer만 기존 CUDA profile
  lock을 획득했고, OLD Python이 candidate 코드 실행 없이 byte/source/ELF audit를 수행했다.
  수치 prefix의 private source는 `87cc21d68b0b2584c2b683844aea67d759e5bb02`다.
  공통 `/opt/eom` 쓰기 mount를 사용해 이전 EXDEV 조건을 반복하지 않았다. CPU·OLD
  interpreter·model 경로는 읽기 전용이고 CPU owners는 중지하지 않았다.
- 보호 audit stage는 `/opt/eom/.embedding-index-install-boFUiSkR`다. 독립 root inventory
  reader도 PASS했으며 총31656 entries/7085437688 bytes, regular28083/link1380/ELF287을
  확인했다. inventory는8946502 bytes, raw
  `2b533b7aebfc0f4ea5218c2337a5eb671ccdb804c5c715d65eb41dba3888f0be`, semantic
  `b0d30323cce5de382b6c467e6899febffdf5466dc7c3dc8900674d9177bb2008`다.
  final phase는 `PREFIX_BYTES_AUDITED_NOT_ADMITTED`이고 phase raw는
  `38479ffb601585f33b1021d9376bdeee3651e8ea8205e6022afdf0acc5356324`, prefix-byte receipt
  raw는 `8c0cd73e699420ffc49eceee9ba56c2e97dd880d304718c545da9f40af0d3d62`다.
  frozen numerical implementation3개와 fixed benchmark 파일2개의 원 bytes도 확인했다.
  기존 prefix는
  `/opt/eom/conda/envs/.embedding-index-prepublication-CUDA_INDEX_FP32-.embedding-index-install-boFUiSkR`
  에 보존했다. 이 byte audit와 독립 metadata read를 native 모델 실행 승인으로 해석하지 않는다.
- 같은 logical `embeddingnativeconfig_3e98a13d3d164e2db5f861c2e5f73e08` 아래 host-only
  successor `embeddingnativeconfigrev_6d5b478396494300bb24ea217685b9a4`를 create-once로
  게시했다. config는2618 bytes, raw
  `11d56625a72acedbf46ac8e5188d8a9fffa1b3061f47ce1c7862778378c0547c`, semantic
  `d9fb71267be9bf38160bde77e7c3cf66ab99a2f1883998b5c9d280f03ced4674`다.
  원 config/proof/bundle/schema를 같은 file ledger에서 읽고 정확한 host34ed/basec126을
  typed public resolver로 확인했다. 변경은 revision/config hash/명시적 CUDA host pointer뿐이며
  bundle/proof/resources와 수치 runtime
  `d0887315a3b7afd0d86dceb10228c157c72f7161dbdbb01a582d97be1d8c7560`은 유지했다.
- 이후 actual successful byte evidence와 현재 physical/profile quiescence를 확인한 CAS
  invocation `00a7e538a3b84f569df000d3c74fdc3a`가 PASS했다. CUDA `selected-cache`만 기존
  b103 절대 경로에서 새34ed 절대 경로로 전환했다. root symlink epoch/target과 old cache
  `7276f7a0f80cbcb2cf877a51021f96b0f2f9ea4ca553e061b4f38146c6fb6d20`, new cache
  `65171e487533d81862e3e56df880e600a683517b72aae2364179cd8a1810097c`를 확인한 뒤 exclusive
  temporary symlink/rename/fsync와 같은 pinned host의 fresh resolver readback을 수행했다.
  이미 unload된 transient unit의 상태를 현재 권한 근거로 요구하지 않았다. CPU selected-cache,
  서비스 설정과 기본 backend 정책은 바꾸지 않았고, 두 host revision은 모두 보존했다.
- 실제 native no-forward execution은 `9ceda2b7bb7a4187a2947dde6bbf0704`, worker invocation은
  `5ee073da72c845d689bf71d90b35733d`다. 같은 live PID2196219의 READY를
  18:34:41.517314 UTC, FINAL을18:35:39.474188 UTC에 관찰·검증한 후 각각 ACK했다.
  동일 root operation이 실제 typed observations와 이미 읽은 config/proof/bundle/schema를
  직접 sealer에 전달했다. saved observation JSON이나 새 file ledger로 대체하지 않았다.
  READY raw는 `5c4d71069fb497fce10d04432dd636152cd124bb45e5c640332268f24db73f90`,
  final result raw는 `41ef728cefa9b8590f81b52b6b154281f6c5b513968b1845539b3ebed985ff24`다.
- receipt2.1을 immutable 게시하고 같은 live PID1 lease가 유지되는 동안 기존
  `ProtectedCudaInstallationFiles` root metadata reader로 독립 readback PASS했다.
  receipt raw는 `d4df79e16d6b8332164cef99debaa5de711c577c055d5c05c8593b92b5487e98`, semantic은
  `9f59a7fd5944e82ba714e6e145388ce16e19a35d1b999232789311d2b224afd4`다.
  이 reader는 root metadata 검증이며 NEW CUDA interpreter에서의
  `ProtectedNativeCudaEmbeddingInstallationAdmission`을 대신 수행한 것이 아니다.
  다음 실제 benchmark worker가 해당 native admission 경계를 그대로 통과해야 한다.
- 실제 terminal PID0/empty cgroup 확인 후 supported successful-probe retirement와
  same-inode FD-store lease 해제 readback도 PASS했다. 원 successful probe/report/receipt는
  보존했으며 generic stop/reset-failed나 과거 실패의 성공 재해석은 하지 않았다.
  root operation은18:36:03.271076 UTC에 `ACTUAL_CUDA_PROBE_SEAL_ROOT_READER_RETIREMENT_PASS`
  로 완료됐다. unit 전체 runtime은1분43.621초다. CUDA initialization/synchronize는 각각1회,
  model constructor/tokenizer constructor/forward는 모두0회다.
- 이 milestone 동안 CPU INDEX/QUERY는 같은 PID1983190/1983188과 기존 invocation으로
  계속 active였다. 상태는 `CUDA_PREFIX_BYTE_AUDIT=PASS`,
  `CUDA_NO_FORWARD_PROBE_SEAL_READBACK_RETIREMENT=PASS`, `GPU_MODEL_COMPARISON=PENDING`,
  `GPU_DEFAULT=NOT_ACTIVATED`다. 남은 순서는 양쪽 runtime preflight 확인 후 새 genuine
  operator 인증, 원 benchmark의 supported prelaunch closure 및 guarded successor, 보존된29개
  token witness를 사용하는 기존 여섯 CPU/GPU 비교다. 수치 동등성·성능·cleanup/coexistence
  gate가 실제로 충족된 경우에만 GPU 기본값을 검토한다. 이 milestone만으로 전체 goal 또는
  GPU 성능을 PASS로 선언하지 않는다.

### 실제 인증·원 실행 정리 성공 / 최초 CPU 실행의 제한시간 종료 — 2026-10-22 UTC

이번 기록은 위 준비 성공 이후의 실제 모델 실행 결과다. 전체 비교나 GPU 성능의 PASS가
아니며, 이전 인증 대기와 이번 계산 실패를 구분한다.

- operator unit `eom-gpu-benchmark-recovery-20261021-4e40dad6-auth5.service`, invocation
  `edb79156ff69400a8907578983dde388`에서16:52:44.723746 UTC에 실제 guiadmin 로그인이
  성공했다. 비밀번호·bearer는 파일에 저장하지 않았다. auth3/auth4의 입력 대기 timeout과
  auth2의 로그인 거부 이력은 그대로 남겼다.
- 16:53:25.642188 UTC에 기존 지원된 application으로 원 Job
  `job_324b59d7fde242bca60437cdacdf5def`의 실제 시작 전 실패를 정리했다. event sequence7,
  decision semantic hash는
  `03db9fe0cbe38230b793871de259622ea189652ce638d8fed2d650872066f6a2`다.
  원 RUNNING row를 직접 UPDATE하거나 실패를 성공으로 바꾸지 않았다.
- 16:53:28.591675 UTC에 사전 고정된 successor revision
  `embeddingbenchmarkrev_4e40dad6e4c946abaa01815537d28952`가 Job
  `job_25b047f39709405190942c42c619a441`로 등록됐다. request semantic hash는
  `8f0ceae4905441fded0ccd198a70a338685d6f7c1df78b006e12e537cf05f32c`다.
  원18 DOCUMENT·2 QUERY·synthetic/capacity 입력29행의 token witness, 모델·Graph·정책·
  수치 기준과 CPU→CUDA→CUDA→CPU→CPU→CUDA 순서는 유지했다.
- 최초 CPU execution `b7f5a692b8b24dc5b886821b8635f567`의 root preparation은
  16:53:39.672942 UTC였고, cold18행 벡터73728 bytes의 mtime은16:56:12.066754 UTC다.
  이152.4초는 **준비부터 파일 관측까지의 경과**이며, 검증된 encode 시간이나 GPU 비교
  수치가 아니다. supplementary/query/worker-result/timing/resource 파일은 모두0 bytes다.
- PID1이 native unit의 고정 `TimeoutStartSec=180`에 도달해 TERM으로 종료했다.
  journal의 CPU time은287.662초, RSS peak는 약4.5GiB이고 swap peak는0이다.
  worker 결과나 capacity 측정이 없으므로 이를 완전한 자원 검증으로 보지 않는다.
  16:56:36.455207 UTC에 owner phase `SERIES`가 중단됐고 MemorySession도 닫혔다.
  **CPU model invocation1 / GPU invocation0 / 완성된 비교 결과0**이다.
- 정확한 local root completion에는 `original_outcome=FAILED`, `cleanup=CONFIRMED`가
  기록됐다. raw hash는
  `5c599d55c803e030a4f1f2992585f30bb3c1b56fd9017ffc16327e2832abd41e`이고,
  별도 root uncertainty raw hash는
  `31b53c923f11c14de0f4ea89dbec0889d62f4da8f206df0b3e6d4b538ff81e44`다.
  cold partial raw hash는
  `771bdd4e96f5926ebb0483de1e382bacd52eebc25f19ea4a456d0e9dd604173d`다.
  위치는 `/run/eom-incremental-embeddings/benchmark/<execution_id>/`이고 이 local
  중간 증거를 정식 measurement Artifact로 게시한 것으로 주장하지 않는다.
- 실패 native unit은 기존 root driver가 terminal/empty cgroup/동일 실행 retirement를
  수행해 inactive로 정리했다. operator도 PID0/empty cgroup이다. 원 reservation은
  성공 receipt 없이 남아 있으며 새 identity·key로 우회하거나 자동 재실행하지 않았다.
  새로운 비교를 위한 재로그인 입력창도 만들지 않았다.

남은 원인 구분: worker는 cold 파일을 쓴 뒤 `COLD_READY`와 owner ACK를 거쳐 첫 synthetic
계산으로 이동한다. supplementary 파일은 각 sample 때 즉시 append되므로, 이 partial 결과는
진행 위치가 cold checkpoint/ACK 또는 첫 synthetic 부근임을 나타낸다. 그러나 saved 결과만으로
긴 모델 기동·cold 계산, owner 재승인/ACK 지연, 첫 synthetic 지연을 분리할 수 없다.
고정180초가 종료의 직접 원인이라는 사실과 ACK 결함이 증명됐다는 주장은 구분한다.

현재 계약은 timeout `Literal[180]`을 schema·worker·channel·owner·root driver와 systemd에서
같이 강제한다. `TimeoutStartSec` 하나만 늘리거나 released1.0 의미를 바꾸지 않는다.
또 기존 prelaunch closure는 시작 전·빈 출력에만 적용된다. 이번처럼 실제 시작하고 부분
출력이 생긴 실패에는 사용할 수 없다. 후속 작업은 다음 순서이며 아직 구현·활성화하지 않았다.

1. 동일 execution의 실제 terminal/cleanup/partial hash를 고정하고 현재 권한으로 확인하는
   좁은 **시작 후 실패 정리 계약**을 먼저 정의한다. append-only/idempotent하게 FAILED를
   기록하며, native 재실행·worker 결과 합성·기존 성공 Artifact 변경 권한을 주지 않는다.
2. 내용 없는 cold/checkpoint/ACK 경과시간으로 지연 구간을 구분한다. 입력 텍스트·token·
   비밀번호·prompt·전체 exception은 진단에 싣지 않는다.
3. 시간이 부족한 경우에만 explicit recipe/resource-policy successor로 수정한다. 원 입력·
   모델·순서·수치 gate는 보존하고, native/owner/root series의 수명을 일치시킨다. 실제
   인증의 유효기간·권한을 늘리거나 이미 종료된 세션을 인증된 것으로 간주하지 않는다.
4. 원 failure reference와 새 실행 예산을 명시한 검토된 실행만 허용한다. 현재 successor를
   단순 재호출하거나 새 key를 발급해 unresolved guard를 피하지 않는다.

이 후속 계약의 canonical source는 원 benchmark Job/launch append-only journal과 protected
root completion·retirement다. logical benchmark/revision/Job/execution/hash를 구분하고
schema·hash·원 invocation·권한·lifecycle·terminal process/FD/cgroup을 함께 확인한다.
주 access pattern은 Job/execution indexed lookup과 monotonic history, small typed evidence의
map/set 검증이다. 시간/공간은 원 launch 수에 선형이며 새 queue/cache/registry는 만들지 않는다.
current-source/Identity fence와 원 Job row lock 안에서 동일 failure 결정 및 replay를 검증한다.
application이 transaction/idempotency를, root adapter가 OS 관찰을 소유한다. 더 단순한 대안인
systemd timeout만 변경하거나 새 Job부터 만드는 방식은 immutable180초 계약과 원 실행
미해결 guard를 우회하므로 불충분하다. 이 설계 기록은 새 실행이나 migration의 PASS가 아니다.

### 별도 CPU INDEX 서비스 복구 — 2026-10-22 17:00 UTC

실험 점검 중 INDEX가 당일06:56:27.843897 UTC의 protected no-forward verifier 실패로
중단돼 있던 사실을 확인했다. 당시 wrapper가 세부 원인을 숨기므로 일시적 timeout과 다른
검증 실패를 구분하지 못한다. apt 종료 직후라는 이유만으로 지속적인 host drift라고 단정하지
않는다. 현재 cache 내용 및 verifier/loader/liblzma/readelf 해시는 고정 값과 일치했다.

benchmark operator와 native CPU가 모두 종료된 뒤, 기존 설정·release를 바꾸지 않고 INDEX를
한 번 정상 기동했다. 설치된 시작 경로가 동일 namespace·실제 service identity의 protected
no-forward 검증을 먼저 수행한 후에만 claim을 허용한다.17:00:29.418244 UTC의
`LOCAL_INDEXING_SERVICE_STARTED`와 이후 정상 read-stage 완료를 확인했다.
새 PID2935655, invocation `3d028f973ec841359ca0bed8a0232e7e`다.
QUERY는 PID1983188/invocation90db로 계속 active였다. 별도 모델·GPU 측정, 설정·권한·DB
schema 변경과 과거 실패 재해석은 하지 않았다. 이 서비스 복구는 benchmark 시간초과의
원인이나 여섯 비교 PASS 증거를 대신하지 않는다.

### 시간 제한·실제 시작 후 실패 복구 — 2026-10-22 소스 검증

[명시적 예산 successor 설계](../architecture/EMBEDDING_BENCHMARK_BUDGET_SUCCESSOR_2026_10_22.md)에
따라180초의 원 계약·leaf·네 unit bytes를 유지하고 정책/요청/invocation1.1의600초와
별도 CPU/CUDA 실행 unit을 추가했다. listener3600초는 operator 인증 freshness900초를
늘리지 않는다. 같은 Job의 완전히 기록된 ordinal까지만 반환하는 한 실행 단위도 추가했다.

원 실제 CPU ordinal1의 실패는 새 post-start schema/공식 application이 원 root 완료·실제
retirement·16개 부분 파일의 크기/hash·현재 terminal unit/PID/cgroup/FD를 대조해 닫는다.
실패 controller의 생존 시간도 원 실행 시간 전체를 포함해야 한다. root-only 증명과
owner가 다시 확인하는 증거를 구분하며, DB 직접 수정·실패 성공 처리·새 key 우회는 없다.
이 시점에는 실제 원 Job closure를 아직 수행하지 않았다.

재검토에서 실제600초 경로의 세 미연결 소비 지점(GPU effective policy, CPU capacity와
cgroup, native OOM 관측)을 수정했다. CUDA leaf의 READY용 file capture를 공유 worker가
다시 context-enter하던 결함도 같은 FD를 한 번만 전달하는 명시적 API로 수정했다.
일반 재진입은 계속 거부하고, sealed READY·미사용 출력·원 FD/hash/current 검증을 유지한다.
legacy readiness의0f93 pin은 보존하며, 새1.1은 정확한4bc5d315 staging 구현을 선택한다.

실제 임시 PostgreSQL 검증은34 PASS이며, 첫33 PASS/1 FAIL은 비동기 advisory lock의
정상 BUSY를 테스트가 잘못 해석한 것이었다. production lock은 바꾸지 않고 동일 요청
rollback 후 replay가 한 winner만 반환하는지 확인했다. 공식 cleanup은 정확한 임시 DB와
그 전용 credential/state만 제거했고 운영 DB·Artifact·실패 이력은 건드리지 않았다.
controller-time 보완 후 제한된 root/owner/native DAC 재검증은1 PASS/2.67초다
(`eom-benchmark-poststart-dac-20261022-review.service`). Machine/retirement의 의미는
이 DAC test에서 합성이므로 실제 원 실행 증명을 이미 게시한 것으로 확대하지 않는다.

현재 소스의 집중 검증은484/139/205/84/73/191 PASS의 서로 겹치는 cohort이고 합산하지
않는다. 의존·설계 경계44 PASS, 변경된 core41개 mypy와 Python63개 Ruff/format도 PASS다.
넓은 benchmark 회귀는 수정 도중 collection되어2021 PASS/2 FAIL로 끝났고, 이전 CUDA
pin 상태였던 두 실패는 최종 소스로 정확히 다시 실행해2 PASS였다. 이후 변경까지 포함한
완전히 새 전체 회귀 PASS라고 주장하지 않는다.

current main의 HOST_L2 bytes가 운영 native와 다르므로 main wheel 전체를 수치 prefix에
설치하지 않는다. 원6c4 native 기반의 최소 호환 backport를 별도 준비했으며 해당 후보의
집중716 PASS/타입42개/format·lint64개가 통과했다. 원 numerical3/모델/라이브러리/표본은
보존하지만 새 전체 prefix inventory·config/admission은 여전히 필요하다. CPU shared
prefix를 바꾸려면 건강한 INDEX/QUERY의 scoped drain과 연결된 verifier/control 전환 및
재자격검증 가능한 rollback 입력을 먼저 준비한다. 원 receipt를 새 bytes에 재사용하지 않는다.

Slack milestone은 `devreport_9e613db548cb4735a9355258972f93f7`로 전송했다.
이 소스 checkpoint의 실제 새 모델/GPU 추론0, 여섯 비교 Artifact0, GPU 기본값 미활성이다.
정상 INDEX/QUERY는 PID2935655/1983188과 원 invocation으로 계속 active였다.

### 별도 호환 SDK 설치와 원 실제 실패 증명 — 2026-10-22 17:56 UTC

- main 수정은 `a4be4f528631c455060c9af10abb47585c5e9163`으로 커밋·push했다.
  원6c4 기반의 독립 native/owner 후보는
  `fea7fe57bd7d8b6aa6601fe324cf5866ef7d1f09`이며 별도 maintenance branch도 push했다.
  해당 후보의716개 집중,73개 READY,3개 schema 검사와 정적 검증은 별도 기록한다.
- 동일한 원 numerical3을 유지한 source tar는65925120 bytes,
  raw `4d6c6b9fc19694c02ea0b8ea57f85dcd5947f798007546651840c9b4ed687e41`다.
  platform wheel은4307929 bytes, raw
  `6c22233cafbfaa20ea1d8ce116500611b1e0891f1d926337341d9e6b46ca2e20`다.
  원 API contracts91ff pair의 wheel RECORD 검증이 PASS했다.
- 공식 owner installer로 별도 `/opt/eom/embedding-owner-releases/fea7fe57…`에만 설치했다.
  installed platform RECORD raw는
  `420d1e2afb69e48bb9010fb06a8b260d44104459fa88a39882bd9f5142e6b9b1`이다.
  실제 CPU/CUDA 수치 prefix와 서비스 설정·기본값은 바꾸지 않았다.
- root proof minter는 이 보호된 SDK/RECORD와 원 request raw d164bff8/invocation raw28a01e02,
  정확한 auth5 controller6c4/eececd1a를 pin했다. source·형식·권한 guard7개가 통과했다.
  첫 로컬 staging은 계정과 primary group 이름이 같다고 잘못 가정해 unit 생성 전에 멈췄다.
  이미 설치된 helper bytes/권한과 미생성 unit/부재 proof를 확인한 뒤 실제 primary GID1000을
  조회해 사용했다. 계정·그룹·권한 정책을 바꾸거나 원 실패를 재실행하지 않았다.
- 실제 `eom-benchmark-original-poststart-proof-20261022.service` invocation
  `970d640894de4f6899650374b80bad44`는17:56:31.407226 UTC에 create-once proof를 생성하고
  성공 종료했다. 원 execution은 b7f5a692이며 proof raw는
  `929e82552ff83e41bf1c1720a770e0eb3c8007c6196f386ff3274eb9970cfdf2`, semantic은
  `d7399026241fbebf3b77baad55ec7b5e7320c72f59b11059e73672b35db7cbed`다.
  `/run/eom-incremental-embeddings/benchmark-poststart-recovery/b7f5a692b8b24dc5b886821b8635f567.json`
  의 root-owned proof다. 원 root completion·retirement·부분 파일을 수정하지 않았다.
  root unit은 원 파일을 읽기 전용으로 두고 proof 디렉터리만 쓰기 가능했으며 NAS/인증/모델,
  네트워크·GPU 장치를 차단했다. Job state 변경·DB·native/model 실행은0이다.
- 두 후속 prefix audit 입력은 OLD stdlib reader로 검증된 **UNTRUSTED DRAFT**다.
  CPU raw599b9e98/CUDA rawa3e33780은 platform private archive만 새 후보로 바꾸고,
  기존 host·bootstrap·Conda/public archive·실제 created_at 파일 pin·GPU lease를 보존한다.
  실제 prefix 교체, 새 native config/receipt/probe/seal은 아직 수행하지 않았다.
  실제 owner capture와 genuine operator/source admission 뒤의 원 Job failure closure도 남아 있다.

### CUDA private-prefix 교체·byte audit — 2026-10-22 18:05 UTC

`eom-cuda-budget600-prefix-fea7fe57.service`의 실제 invocation은
`3b9fc4327e1742388fe919aff97e6bac`이며 기존 보호된 installer와 물리 GPU lease를
사용해 한 번 실행하고 성공 종료했다. 새 prefix는 fea7 private source이며 원 numerical3,
모델·public/Conda archive·CUDA host34ed와 GPU lease 의미를 유지했다. CPU 두 owner의
PID/invocation과 CPU 기본값은 바꾸지 않았다. 새 budget600 unit은 아직 설치하지 않았다.

- 실제 audit: `/opt/eom/.embedding-index-install-ADAWDfi1`.
- retained predecessor:
  `/opt/eom/conda/envs/.embedding-index-prepublication-CUDA_INDEX_FP32-.embedding-index-install-ADAWDfi1`.
- root600 inventory는8970837 bytes, raw
  `16e0a154bf9776d682061d509cb85123e205f49674170b7071f1b34de76ff221`, semantic
  `10bdc00156387c84e0d53c33e2a3bfa84df360ce166b8680f2a94dd738014e61`이다.
  entries31733, regular28160, link1380, ELF287, declared bytes7086259962다.
- 판정은 **BYTE_AUDITED_NOT_ADMITTED**다. 이전6d5 config/receipt는 새 prefix의 승인이
  아니며, 새 config revision과 실제 no-forward probe·same-live seal/readback이 남았다.
- 별도 owner-only 원 실패 증명 preflight는18:04:30에 실패했다. 원 root proof와 Job을
  수정하지 않았으며, 재로그인이나 모델 재실행 전에 content-free 진단으로 실제 실패
  경계를 확인한다. 감독 코드의 경로가 root700이라는 초기 추정은 실제 root755/444
  관찰과 달라 원인으로 확정하지 않았다. 실패 기록도 보존한다.

이 checkpoint의 새 모델 추론0, DB 상태 변경0, GPU 기본값 전환0이다.
Slack `devreport_535b2583f6914bbc83db7ebed4db8e5f`는 설치 PASS와 남은 owner 경계를
구분해 보고했다. 설치 성공을 여섯 실행의 수치·성능 PASS로 확대하지 않는다.

### 실제 CUDA 자격 검증과 owner proof 조회 복구 — 2026-10-22 18:18 UTC

새 CUDA config는 동일 logical ID의 revision
`embeddingnativeconfigrev_a04c2b17b3124f93bd04d5735f623235`다. 기존 config와 다른 것은
revision과 그 hash뿐이며 원 bundle/proof/host/resource/numerical 의미는 같다. raw는
`477de895adfd1399b84ec429d6021c5e0c5499ee30f1815a6bb49c341a3f02df`, semantic은
`0854fdad278a7b28e4d6ff3fef33d7578dd17ba9a277ecf4a2f919e5986e1fb0`이다.
config 발행 unit의 실제 invocation은 `070015f04f2b436f82fba2182d4bfd79`다.

`eom-cuda-budget600-probe-seal-fea7fe57.service` invocation
`dcce266b170042cd85ff929d881e6c2b`는18:17:41.060244 UTC에 성공했다. 고정 native probe
execution은 `649d59622f1740d6826497708faae14c`, 실제 native invocation은
`6c6d851f05cc45d3ad0824c42d1940d6`이다. READY/final ACK, 실제 CUDA 초기화1회·동기화1회,
same-live seal, 새 root metadata reader와 정확한 supported retirement/lease 해제까지
확인했다. 모델·tokenizer 생성과 forward는0이다. 새 receipt2.1 raw는
`579d5e6aa9b5fe6c06a6b9c1a8adf37e353b06c3e4bd4db47c7caa1d86f2bec7`, semantic은
`aabac42025851aea49454954650d527c6e31a854d4bba31bd670933dc5c5294f`다.
보호된 실제 summary는
`/var/lib/eom-cuda-budget600-qualification-fea7fe57/native-probe/summary.json`에 남겼다.
root metadata reader의 PASS를 향후 실제 numerical interpreter의 입장 검증으로 대체하지 않는다.

owner proof preflight의 실패는 본체 proof adapter가 아니라 진단 launcher의 root→owner
전환 이전이었다. EOM-free 실제 두 kernel probe에서 ambient가 비어 있으면 root의 실제
permitted/effective에 SETUID가 없었고, 기존 운영 방식인 parent ambient SETUID를 사용하면
정확히 UID990으로 전환됐다. owner는 전환 직후 V3 capset의 두 all-zero word와 ambient-clear로
Inh/Prm/Eff/Amb를 모두0으로 내렸다. NoNewPrivileges와 기존 filesystem/네트워크 격리는
유지했다. worker 권한이나 계정 그룹을 늘리지 않았고, 이 원인 때문에 본체 source/SDK를
덧붙여 수정하지 않았다.

`eom-benchmark-owner-poststart-capclear-20261022.service`의 실제 root→UID990/GID1000
조회는 원 proof929e/observationd739를 그대로 재검증하고 성공 종료했다. supervisor/proof/
association 모두 실제로 읽을 수 있었다. 이전 실패 preflight·진단 기록은 보존했다.
Job closure·새 benchmark 등록·CPU prefix 교체·여섯 모델 비교는 아직 수행하지 않았다.

### 원 실제 시간초과의 공식 closure — 2026-10-22 18:24 UTC

`eom-benchmark-original-poststart-close-20261022.service` invocation
`0397d7e8152c4d3299f7978b4a7e9c33`는 실제 guiadmin 인증 뒤 원 request4e40의 Job
`job_25b047f39709405190942c42c619a441`을 지원된 post-start application으로 정리했다.
18:24:33.913306 UTC에 append-only event8과 함께 RUNNING→FAILED가 확정됐으며 decision은
`3b07acf382bbbbdf81b4e2a9f1721ef514d601933ce9fd00ddd250446ca5e23f`다.
같은 세션의 같은 요청을18:24:35.545943 UTC에 다시 실행해 동일 decision/event와
`created=false`를 확인했다. 원 실패·부분 출력·root proof는 그대로다.

제한 계정은 실제 현재 operator/source/Graph/policy fence와 root 증명을 재검증했다.
직접 row UPDATE, 실패의 성공 재해석, 새 Job/Artifact/native/model 실행은 없었다.
정리 전 실제 SDK/원 파일·provider·capability/FD·proof 검사를 마친 뒤에만 getpass를
표시했다. 비밀번호는 저장하지 않았고 bearer는 child process 밖으로 보내지 않았다.
공식 close/replay 뒤 실제 memory session은 닫았으며 향후 계산의 인증으로 가장하지 않는다.
CPU INDEX/QUERY는 원 PID/invocation으로 유지했고, 새600초 비교 request 등록·CPU
prefix 교체·여섯 수치/성능 비교·GPU 기본값 활성화는 여전히 미완료다.

### 다음 CPU 전환의 준비 범위와 인증 경계

CPU 전환/복구 초안은 `/tmp/eom-benchmark-cpu-cutover-prep-1RNjsY0A`에 보존했다.
정확한 retained tree를 검증하는 복구 알고리즘30개와 revision-only config/연결 설정의
합성·정적 검사10개, 총40개가 통과했다. 기존 metadata2e5 SDK의 실제 공개 모델로 여섯
현재 control의 순수 projection도 검사했다. 이는 CPU cutover·runtime admission·rollback의
실제 PASS가 아니며 **CUTOVER_READY=NO**다. 현재 서비스는 멈추지 않았다.

앞으로 필요한 것은 별도 queue나 인증 우회가 아니라, 기존 finite installer와 새 config/
실제 no-forward probe/seal, 멈춘 INDEX/QUERY의 여섯 연결 control을 동일한 호환 조합으로
전환하는 준비다. 실제 설치 후 생기는 inventory/epoch/receipt를 미리 만들어 채우지 않는다.
전환 전에 forward·실패시 보존/복원 알고리즘과 원본 재감사 입력을 검토하고, 각 effect 뒤의
실제 관찰 값을 다음 고정 단계의 입력으로 검증한다. 복원도 새 자격 검증이 필요하다.

이번 closure용 인증은 정확한 close/replay 후 종료됐다. 비밀번호·bearer를 저장하거나
운영자 인증을24시간 받은 것으로 간주하지 않는다. 실제600초 비교는 모든 설치와 root/
owner 준비가 끝난 뒤 현재 인증으로만 시작한다. 여섯 실행 중에도 이미 완료·게시된
clean prefix 사이에서만 진짜 재인증할 수 있다. 준비되지 않은 도구 때문에 반복 로그인하는
경로를 만들지 않으며, 인증900초의 계약을 조용히 완화하지 않는다.

### CPU 전환·복구 recipe와 실제 read-only preflight — 2026-10-23 UTC

이번 checkpoint도 실제 CPU 교체나 모델 성능 비교 완료를 뜻하지 않는다. 두 정상
owner는 기존 PID/invocation을 유지하며 CPU 기본값, Graph/문항/벡터 정본과 원 실패
event8은 그대로다. 다음 실제 경계는 CPU 설치·새 자격 검증·연결 control 선택이다.

정상 CPU interpreter에서 기존 전체 tree30eaaede와 원 설치 승인을 먼저 확인한 뒤,
전환용·복구용 config만 각각 create-once로 준비했다. configuration은 수치 recipe를,
별도의 future receipt는 실제 prefix inventory/probe를 고정하므로 metadata를 미리 준비할
수 있다. 선택 중인38786 config/receipt/verifier를 바꾸거나 모델을 생성하지 않았다.

| 구분 | 실제 unit / invocation | 실제 결과 |
| --- | --- | --- |
| 전환 recipe | `eom-cpu-budget600-config-3d499bbc-20261023.service` / `bf1d3d8595f546b082465dff250e2583` | 03:44 UTC 성공, config3d499 준비·미선택 |
| read-only preflight v2 | `eom-cpu-budget600-live-preflight-v2-20261023.service` / `622962bfe6714634882f140847d575c2` | 성공, 원 event8/decision/proof 일치·유효 claim0 |
| 복구 recipe | `eom-cpu-budget600-rollback-config-48d83553-20261023.service` / `cc47e1ddc06b41159e143cc15aae5208` | 04:05:09.116739 UTC 성공, config48d8 준비·미선택 |

전환 config raw는 `ff4a2b979b8ee4d2e90b753e31b32560297a9f2156a3b80ac39c7de438748353`,
semantic은 `6d1dedfe614b6f6d5b5176168ebeb8ded6f978116ce0ad8668d55186ae757887`이다.
probe execution은 `c400c2cf073b4dfa81b88fb7dfcdf826`, staged input raw는
`0391815c35af9e1f621d18ebcc77788c5f9bacc89165ae55c1d5ca8efed5ed7d`다.

복구 config revision은 `embeddingnativeconfigrev_48d8355309644541a1e326124e43c83b`, raw는
`9c9c08a87636057a6fa455613b342fbd6900121bddc80bc2896bdcef2c16747d`, semantic은
`e6e6f7b76a0e8979003ed81e38dbcd83cc2ded58d6eac8028d3a20b29306f0da`다. staged probe
execution은 `0af0fc9f94534dcab02b056fe5d99153`, input raw는
`773f1fabd87e3183ec7980df22cc65bb580b4cd50606af449e24de54dbd020a7`이다.
두 상태 모두 **PREPARED_NOT_ADMITTED**이며 native probe는 시작하지 않았다. 복원할 때
실제 OLD 재감사와 새 probe/receipt가 필요하고, 원04185 receipt를 재사용하지 않는다.

실제 preflight v1은 QUERY supervisor까지 INDEX와 같은 비특권 계정이라고 잘못 가정해
`CPU_MAINTENANCE_OWNER_IDENTITY`로 거부됐다. 실패 unit/소스는 보존했다. v2는 각 실제
service identity를 각각 pin했으며 QUERY의 root supervisor→UID990 child 구조는 변경하지
않았다. root maintenance의 read-only SQL은 기존 scoped claim query와 정확한 원 Job/event
검증에만 사용하고, Studio 사용자 권한이나 새 모델 실행 권한으로 가장하지 않았다.
운영 DB 변경, 테스트 DB 대용, worker 권한 확대는 없었다.

보호된 operational metadata는 `/var/lib/eom-benchmark-budget600-20261023` 아래 각 config
디렉터리에, 실행 정의는 `/usr/local/libexec/eom-benchmark-budget600-20261023`에 남겼다.
복구 알고리즘·STOPPED observer adapter·전환/복구 same-live seal·정확한 owner main-only
종료·기존 CPU installer 호출 정의를 검토했으며, **정의를 설치했을 뿐 실행하지 않았다.**
복구 알고리즘 v2는 고정 경로 변경과 formatting 외에 기존 검증된 함수 body를 보존한다.
원 root444 정의도 덮어쓰지 않는다. 전환에 필요한 실제 미래 inventory/receipt/epoch는
여전히 미생성 상태이며 임의로 채우지 않았다.

이번 준비의 집중 검증은 **113 PASS**다: config/원 실패 관측44, 복구·quiescence43,
same-live seal body 보존5, main-only 종료7, installer 인수·출력·create-once14.
명시적 eom-api Python과 보호된 fea7 SDK를 사용했으며, 초기 ambient package 경로의
8개 import 실패는 동일 테스트를 올바른 SDK로 다시 실행해 구분했다. core source나
운영 package를 이 import 실패 때문에 수정하지 않았다. 새 typed operational 모듈4개
strict mypy와 새 source Ruff 검사, shell syntax 검사도 통과했다. 합성 검사이며 실제
prefix 교체·복원·한 번의 모델 추론이나 성능 우위를 증명하지 않는다.

installer 준비 중 발견한 두 로컬 결합 문제는 실행 전에 수정했다. 기존 installer stdout은
bare preparation marker 다음에 여덟 key/value가 오므로 이를 정확히 검증한다. CPU 입력은
group-writable build 상위 경로를 직접 사용하지 않고, 이미 CUDA 설치에 사용한 동일
fea7 wheel/source의 private0700 materialization을 hash로 재사용한다. 큰 archive를 또
복사하거나 installer/public protocol을 바꾸지 않았다. intent와 결과는 create-once로 남기며
실패·불명확 상태를 새 호출로 우회하지 않는다.

현재 남은 작업은 검토된 실제 CPU 전환·자격 검증·여섯 연결 control의 선택/복구,
600초 실험 실행 도구의 최종 조립, 현재 operator 인증 뒤 동일 입력6회 측정, 수치/순위/
시간/메모리·공존/복구 판정, 조건부 기본값 결정과 정본 결과 게시다. 준비가 끝나기 전
새 Studio 로그인을 요청하지 않는다. GPU 기본값은 **미활성**, 여섯 측정은 **미완료**다.

### 실제 CPU 전환·설치 승인·서비스 기동 복구 — 2026-10-23 04:41 UTC

앞 checkpoint에서 남아 있던 **CPU 전환·새 설치 승인·연결 control 선택·서비스 기동
복구는 완료**했다. 아래는 실제 관찰이며 모델 성능 비교나 원 목표 전체의 완료는 아니다.

- 첫 전환 wrapper unit `eom-cpu-budget600-prefix-fea7fe57-20261023.service`, invocation
  `75145666b4424c32bc4bbe2ae89d7ad8`는 이 systemd에서 template 자체를 `show`하는
  조회 형식이 지원되지 않아 첫 guard에서 실패했다. 두 owner와 prefix를 변경하기
  전이었다. 실패 기록과 source는 보존했고, 실제 지원되는 미생성 instance 조회만
  사용한 v2로 수정했다. reset-failed·실패 성공 처리·작업 우회 생성은 없었다.
- `eom-cpu-budget600-prefix-fea7fe57-v2-20261023.service` invocation
  `17d458b2b11c414bb006997bd98a3f16`는 fresh read-only preflight 뒤 정확한 owner main
  두 개에만 SIGTERM을 보냈고 정상 종료를 기다렸다. 자연 종료한 INDEX/QUERY를
  기록한 root400 `stopped-units.json` raw는
  `5bd53aebfe40cdee9ca6470d1db7fddbee1328e867ac3ca0bba4b67175d3a8d6`이다.
  stopped/claim/원 failure proof를 다시 검증한 뒤 기존 installer를 한 번 호출했다.
- 실제 OLD byte audit operation은 `/opt/eom/.embedding-index-install-neDH039m`이며
  04:30:39.656471 UTC에 성공 종료했다. retained predecessor는
  `/opt/eom/conda/envs/.embedding-index-prepublication-CPU_INDEX_FP32-.embedding-index-install-neDH039m`이다.
  이전 root device64512/inode19578306과 원 tree30eaaede를 확인해 보존했다.
  새 inventory raw는 `d366530a68bf786a9899eada16dceac371417364b512f135c9e2099868b2f797`,
  semantic은 `f809c6afab1bbfb30adf3fb97f4a7352284042cb3f934ee7221ef6b44c05282e`다.
- `eom-cpu-budget600-probe-seal-fea7fe57-20261023.service` invocation
  `19a41c2acc654b62b3908cde9ab337ef`는 실제 native probe `c400c2cf...`, PID3840911,
  native invocation `bcec0222693d4b4ca0ae9ff0b00f3854`의 live maps/ACK/정상 종료를
  확인하고 같은 live 관찰에서 봉인했다. UID978/GID975, model member8개·denial 검증,
  실제 runtime `f02cfc2b...` 보존, root의 ML import0·model/tokenizer/forward0을 확인했다.
  report raw는 `5632611ccdb295ece401a03aa8f9efa04f4aeeb46c9fdc89e9a0d5edc1a12070`이다.
- 04:33:45.085946 UTC의 config3d499 receipt raw는
  `80415754bb21ef2ff7d5d5bc66edd10cd2382cc42c0f967b6c2fbc7aa38a4f8e`, semantic은
  `f292d624ed0cff8a5b0f02c76a24e9c6de74f4aec527a75653f2434fcdb546a9`다. 실제
  `ProtectedNativeEmbeddingInstallationAdmission` reader도 PASS했다. final seal raw는
  `50f9f5e34fbceb507a2e05ae71d9218a9bfb58cae1f726b369b5d13eb6c2a778`이며 root 운영
  기록 `cpu-fea7fe57-seal/final-installation-seal.json`에 보관했다.
- `eom-cpu-budget600-select-fea7fe57-20261023.service` invocation
  `59e710f758ed43c28c4d5eb94d92024f`는 보호된 metadata2e5 SDK로 PREPARE와 SELECT를
  순서대로 통과하고04:38:57.795410 UTC에 성공 종료했다. before/after/epoch/receipt/
  host/claim/물리 상태를 확인해 여섯 파일을 sequential CAS하고 마지막에 한 번만
  daemon-reload했다. manifest SHA는
  `e50e1bb8a10e9d86fae75b9b9d50dd5846840955fc9372d2eb23a623b1c82acc`다.
  새 fea7 verifier raw는 `8fc388054a921c76092296f6cf21a80f6e1f3b90c1b00141901ef588cc22fad3`다.

| 새 선택 파일 | 실제 raw SHA-256 |
| --- | --- |
| CPU env | `3d15b83d01133a3ad46692bd636f13135860a31130d974804f884cfa8886c308` |
| INDEX owner | `e3f9e6bb569988bff95ed3a1151c58b29d06b9eda699d4fd2db6f19ae42f9823` |
| REFERENCE owner | `91ac9c0ec0e334659a128432dc24ec30d0a84dcd4e344eb6ddafcb97e49021f5` |
| MIXED owner | `10b0cd8556f3506f0d799ce7392f5213265eceb53239c37710316e1061551f24` |
| PRIVATE owner | `b31fd2c4c0d791d3b2bedc2908ff0e8abd72a3cb9a2d97376c00a79c3042cd81` |
| QUERY unit | `e532cd7069e0c8e0cd3f63a5b6319f198f019b84e65ec7c786b48d18caaee664` |

기존 before bytes와 새 verifier/여섯 after bytes는 root700 `linked-fea7fe57`에 유지한다.
기존 runtime/source grant·Identity·Graph·모델·벡터 공간·CPU 기본값은 바꾸지 않았다.
새로운 schema/migration/queue를 추가하거나 DB row를 수정하지 않았다.

budget600 네 template과 instance가 미설치/미실행임을 확인한 뒤 두 기존 owner를 재개했다.
INDEX PID3844518/invocation `84cf9411d71e438a9cff64cfbc695b0f`는04:40:32.179061 UTC에
STARTED, QUERY PID3844513/invocation `e11b59a3c3364c3c95f0c5a07a07c070`는
04:40:48.122954 UTC에 READY였다. 새 invocation의 journal만으로 확인했고 이전 READY를
재사용하지 않았다. 04:41:28의 실제 `/api/v1/health/live`와 `/api/v1/health/ready`는
각각 LIVE/READY였다. 처음 잘못 조회한 `/health/live`의404는 서비스 장애로 해석하거나
API를 바꾸지 않고, 기존 배포 smoke에 정의된 실제 route로 조회했다.
이는 기동 복구 증거이며 이번 변경 후 인증된 사용자 검색 smoke는 별도로 남아 있다.

집중 검증은 후속 actual-pin/기존 installer arity/disabled-plan 검사까지 **121 PASS**다.
명시적 CPU private publication 인수에는 기존 installer가 요구하는 common wheelhouse를
추가했으며 공용 dependency를 새로 설치하지 않았다. 앞서 보호 설치한 미실행 정의는
덮지 않고 v2 이름으로 보존했다. 원 failure·부분 출력·Job event8은 그대로다.

다음 비교 준비용 작은 pointer 파일은
`/tmp/eom-cpu-budget600-config-20261023.7549egJj/budget600-pins.CPU_ADMITTED.json`이다.
원 disabled plan의 CPU backend만 실제 config3d499/receipt80415754로 채웠고 다른 필드는
같다. **execution_enabled=false**이며 이 파일은 사용자 인증·root series tool·공식
benchmark 접수/실행의 대체물이 아니다. 원 DRAFT는 보존했다.

남은 목표: 실제 root/owner 비교 실행 도구 마무리 → 현재 operator/source 권한 확인 →
동일 고정 입력 CPU/CUDA6회 실측과 수치/검색 순위·시간·메모리 검증 → 다른 GPU 작업과의
공존·복구 검증 → 실측에 따른 기본값 결정·필요한 운영 반영 → 정본 결과·한국어/Slack 보고.
현재 여섯 측정은 **미완료**, GPU 기본값은 **미활성**이며 원 목표는 계속 ACTIVE다.

### 실제 유한 실행 도구 사전 점검·로그인 대기 — 2026-10-23 05:48 UTC

CPU/CUDA 설치 준비와 별도로 남아 있던 유한 root/owner 실행 도구를 조립하고 실제
서버의 보호된 파일·정확한 계정·API provider로 사전 점검했다. **새 benchmark Job과
모델 forward는 0**이다. 아래 사전 점검 성공은 성능 비교나 실제 사용자 인가 성공이 아니다.

- 현재 고정 운영 도구 위치는
  `/var/lib/eom-gpu-benchmark-budget600-20261022-a7a80a1c`다. 파일은 root444,
  복구 기록 디렉터리는 root700이며, 기존 helper/SDK를 원 hash로 참조한다. 새 schema,
  migration, queue, 검색 엔진이나 인증 방식을 제품에 추가하지 않았다.
- 현재 진입점 `benchmark_budget600_supervisor_v4.py` raw SHA는
  `dde6200d180c2cec9ffa252a177b783b4b4f79077135ececff58debc3bcbffab`,
  작은 선택 파일 `pins-v4.json` raw SHA는
  `4fb2c4c44a6de47dd18f1cd66e61a3391cda1447b0fb945d09b119f8868a9041`이다.
  비교 phase raw64013c36, marker raw8e7d7356은 원 측정/출판/인가 동작을 보존한다.
  유지보수 창 helper raw는
  `ebb08e3a793c40838b6042627c2c38a5924a6fb17e9a45b0c97a2f421d6cf06c`다.
- `eom-gpu-benchmark-budget600-a7a80a1c-v4-preflight.service` invocation
  `09e330ca71954004a7018645ca3fee7f`는05:48:28.599738 UTC에 PASS를 기록했다.
  실제 owner UID990/GID1000/groups[], 변경 가능한 capability0, NoNewPrivs1,
  설치된 API60af9e5d provider와 원 proof의 typed pin 연결을 확인했다. 사용자
  로그인·새 Job·model forward는 없었다. PID1의 최종 상태도 MainPID0,
  active/exited, success/0으로 확인했다. `RemainAfterExit`로 이 사전 점검 결과를
  보존하며, 사라진 transient unit의 기본 `Result=success`를 PASS로 오인하지 않는다.
- 초기 v1 사전 점검 invocation7089e79d와1e3945ba의 실패, v2 실제 실행
  invocation `2c0fc831ce344db8aa1166f04a175c6c`의 초기 CPU-prefix 점유 거부,
  v3 사전 점검 invocation `63ae24e65c6e4556834d644b7d7c3bee`의
  `CPU_SCOPE_UNEXPIRED_INDEX_QUERY_CLAIM` 거부는 보존했다. v1의 일반화된 오류를
  확인하지 않은 상세 원인으로 소급 해석하지 않는다. v2의 별도 read-only 사전 점검은
  두 번 통과했으나 그것으로 이후 순간의 quiescence를 보증하지 않았다.
- 사전 점검은 아직 정상 동작 중인 INDEX/QUERY의 작업·metadata reader가 존재할 수
  있는 **읽기 단계**다. 그 단계부터 이미 정지된 유지보수 창을 요구한 초기 조건을
  분리했다. 진짜 로그인 성공 후 두 owner main만 정상 종료·drain하고, **그 다음에
  전체 native/socket/cgroup/prefix 점유와 유효 claim 부재·실제 DB role·원 closure를
  확인한 뒤** 네 개 template을 활성화한다. 실제 실행 전 검사를 생략하거나 busy
  작업을 강제 종료·성공 처리·DB row 변경한 것이 아니다.
- 네 작은 template의 복구는 별도 bind mount 간 rename에 의존하지 않는다. 정확한
  byte를 복구 디렉터리에 create-once/fsync하고 일치·source epoch를 확인한 뒤
  지정 임시 load path만 제거·directory fsync한다. 부분 보존 이후 복구와 틀린
  보존 byte의 거부, native/claim이 불명확할 때 복구/활성화 금지를 검사했다.
- 최종 집중 검증27개, 원 phase의 별도 합성 검증14개, Ruff/format과4개 모듈의
  구조적 mypy 검사를 통과했다. 같은 실험의 통과 수를 중복 합산하지 않는다.
  집중 검증에는 실제 보호 설치 byte/시험 대상 byte/hash 대조1개도 포함한다. 이것은
  운영 DB 테스트나 모델 시간 측정이 아니다. 새 의존성은 없다.

실제 비교 제어 unit `eom-gpu-benchmark-budget600-a7a80a1c-v4.service` invocation
`9f1f123729f342339bd61a4613581f24`는05:48:55.463745 UTC에
`READY_FOR_GENUINE_LOGIN`을 표시했다. tmux `EOM`의3번 `gpu-embedding`에서
실제 Studio guiadmin 비밀번호를 기다리며, 비밀번호/bearer를 저장하지 않는다.
이 관측 시점에 기존 INDEX PID3844518/QUERY PID3844513과 두 invocation은 유지됐다.
로그인 대기 때문에 서비스를 미리 정지하지 않는다. 원900초 human freshness와
clean-prefix genuine 재인증은 그대로이며 root의2시간/series3600초는 인증 연장이 아니다.

이 checkpoint의 Slack 보고는 `devreport_dfdda64a42494d4290ae6857aa3469da`,
05:48:49 UTC, HTTP200/SENT다. 한국어 한 문장 요약을 맨 앞에 두었고 문항·prompt·secret은
전송하지 않았다. 인증 뒤 원 closure의 지원된 replay/새 successor 접수와 같은 입력6회,
수치·순위·시간·메모리·실제 GPU 공존/복구, 조건부 기본값 결정은 **계속 미완료**다.

### 실제 인증·정상 drain·공식 successor 접수 — 2026-10-23 06:00 UTC

앞의 인증 대기는05:55:47.256344 UTC에 실제 Studio 로그인 성공으로 해소됐다.
새 로그인 실행/Job을 복제하지 않고 같은 root invocation9f1f1237과 owner child를 유지했다.
원래 INDEX는 기존 command `wfcmd_29f317756bfa46de9d3ef90e3a11e055`를
06:00:47.308054 UTC에 SUCCEEDED로 마친 뒤 정상 종료했다. main-only SIGTERM에서
약5분이 걸렸지만 강제 종료나 DB 상태 수정은 없었다. QUERY도 success/0으로 종료했다.
과거 원 command 완료가 최근 약5~7분 간격이었다는 journal을 확인했으며, 단순 대기를
새 state-machine defect 또는 실패로 해석하지 않았다.

두 owner의 정상 종료 후 전체 physical/claim/실제 role/원 closure 검사를 통과해
06:00:50.222850 UTC에 네 실험 template의 window가 열렸다. owner는 실제 현재 세션으로
원 closure를 replay해 created=false/동일 predecessor를 확인하고, 원 입력을 유지하는
새 policy1.1/600과 staged-inputs를 공식 Orchestrator publisher로 게시했다.

- 새 Job: `job_26e206dc11434d52870f51737d15fdbd`, created=true,
  06:00:55.071729 UTC의 공식 successor 등록1건.
- 새 request semantic SHA:
  `4208355fa95249743bd71ff8022650d4b51f2d91ddc44140d68a8b5647c7070f`.
- 원 benchmark logical ID7255032e와 배정된 새 revision88769635를 사용했다.
  원 실패 Job25b047f3·event8·failure decision3b07acf3은 보존했다.
- 아직 launch ordinal1도 dispatch하지 않았다.06:00:55.708719 UTC에
  `CLEAN_PREFIX_GENUINE_REAUTH_REQUIRED`에 도달했다. 직전 인증은 성공했으나
  정상 drain에 사용한 약5분 때문에 남은900초 freshness가 다음600초 계산+60초
  준비/정리 reserve보다 짧아졌기 때문이다. 인증 자체가 만료됐거나 잘못된 암호라는
  의미가 아니다. 새 key/Job으로 우회하거나 인증 시간을 늘리지 않았다.

이 관측 시점의 INDEX/QUERY는 실험 window 때문에 **의도적으로 inactive/dead**이며,
기동 상태를 정상 운영 중이라고 표시하지 않는다. API 자체와 구분한다. 같은 tmux3
입력창에서 실제 인증 갱신을 기다린다. 서비스 재개는 같은 보호된 window-close/stop-post
규칙이 담당한다. 후속 재개 시 새 Job을 제출하지 않고 위 Job/원 실행의 현재 상태부터
조회한다. 아직 CPU/GPU 측정·수치 판정·GPU 기본값 완료는 아니다.

인증 대기 해소/정상 drain 진행 Slack은
`devreport_db8ff7d6ede44a46b5ee35f6baf0908c`(05:59:38 UTC, SENT/HTTP200)다.

### 첫 budget600 CPU 실행의 실제 상한 도달 — 2026-10-23 06:16 UTC

같은 제어 unit/invocation과 새 Job `job_26e206dc11434d52870f51737d15fdbd`에서
05:55:47의 첫 인증에 이어 06:05:43.657032 UTC에 clean-prefix 재인증이 성공했다.
첫 launch는 CPU ordinal1이며, native unit
`eom-embedding-benchmark-cpu-budget600@a038b51d231a47e9866766c8a6b6e476.service`
invocation `4dcc0272a3c14e32955c08ac45355154`가 06:05:55 UTC에 실제 시작했다.
프로세스는 실행 중 CPU를 사용하고 있었고 GPU 사용량은 0%/2 MiB였다. GPU launch는
한 번도 시작되지 않았다.

06:15:51.978899 UTC에 owner가 `BUDGET600_OPERATION_FAILED`와
`BENCHMARK_OWNER_EXECUTION_UNCERTAIN`을 기록했고 자동 재시도를 거부했다.
systemd는 06:15:55 UTC에 위 native unit의 **600초 start timeout**과 SIGTERM,
`Result=timeout`을 기록했다. 이는 성공 측정이나 GPU 성능 판정이 아니다. 정확히
어느 계산 단계에서 상한에 도달했는지, 그리고 별도로 기록된 root의
`InstalledRuntimeProofError`가 같은 실패의 후속 관측인지 독립 실패인지는
현재 증거만으로 확정하지 않는다. 확인된 것은 첫 CPU launch에 유효한 완료 receipt가
없고, CUDA launch와 여섯 번의 비교가 없다는 점이다. 새 Job의 RUNNING/실패 여부도
공식 Journal/closure 조회 전에는 추정하지 않는다.

기존 sudo 인증이 남아 있는 운영 pane에서 파일 **내용이 아닌 이름·길이·보호 메타데이터**를
읽기 전용으로 더 확인했다. 같은 execution의 `cold-documents.f32`는73,728 bytes
(18×1024×4), `supplementary-documents.f32`는122,880 bytes(30×1024×4)다.
`worker-result.json`·`timings.json`과 QUERY 결과는0 bytes다. 이는 cold 행렬과
30개 보조 벡터의 부분 materialization을 보여줄 뿐, 유효한 benchmark 완료나
개별 phase의 채택 판정이 아니다. 고정 첫 launch 프로그램은 cold1,
synthetic12, warm5, query10, capacity2 sample로 구성되고 첫 warm 직전
unmeasured warm-up도 실행한다. 따라서 현재의600초가 전체 첫 launch에 충분하다고
가정해 재제출할 근거는 없다.
각 파일의 실제 mtime은 cold `06:08:24.351659 UTC`, supplementary
`06:15:29.412350 UTC`다. native 시작06:05:55부터 cold materialization까지 약2분29초,
그 뒤 supplementary materialization까지 약7분5초가 경과했다. 파일 생성 시각은
phase 전체 wall-time이나 안정적인 미래 처리량을 증명하지 않지만, warm/query/capacity가
남은 채600초 상한에 도달했다는 판단에는 직접적인 근거다. 같은 실패 입력을 시간을
조금만 늘려 자동 재시도하는 접근은 적절하지 않다.

별도로 root가 남긴 `root-completion.json`에는 같은 execution/ordinal1의
`original_outcome=FAILED`, `cleanup=CONFIRMED`가 있고,
`root-uncertain.json`도 존재한다. 실제 native retirement의 intent/result 파일이
같은 invocation 아래 보존되어 있다. 이 두 control record를 마음대로 하나의
성공 receipt로 합치지 않는다. 원인 분류와 공식 failure closure는 둘의 관계와
실제 systemd timeout·부분 출력·파일 보호 상태를 함께 검증해야 한다.

보호된 window는 06:15:57.096600 UTC에 닫혔고, 실험 template instance는 더는
활성화되어 있지 않다. 정상 INDEX와 QUERY owner는 각각 새 PID3916708/3916710으로
`active/running`, API `/api/v1/health/ready`는 `READY`를 확인했다. GPU 기본값과
정본·기존 벡터는 바꾸지 않았다. 실험 제어 unit은 `failed/exit-code`이고 그 실패
기록을 보존한다. 구식 systemd 실패 unit들을 현재 서비스 장애로 합산하지 않는다.

다음 단계는 새 요청을 제출하거나 timeout만 높여 재실행하는 것이 아니다. 정확한
첫 launch 예약·부분 출력·native/cgroup/retirement와 root proof를 읽기 전용으로
분류하고, **600초 family의 timeout 관측을 표현하는 지원된 post-start closure**가
필요한지 확인한다. 현재 기존 closure는 원 180초 CPU service/socket, 원 supervisor
identity와 native `Result=success`를 pin하므로 이 600초 timeout을 그대로 성공/실패로
재해석할 수 없다. 실제 CPU 처리량과 checkpoint를 근거로 적정 실행 경계 및 900초
사람 인증 freshness의 관계를 별도 설계·검증한다. 숫자·입력·dtype·허용오차를
조용히 변경하지 않는다. 실패한 이 Job은 유지하고, 새 successor는 정식 closure와
versioned policy/recovery가 준비된 뒤에만 고려한다.

이 중단/운영 복구의 Slack 보고는
`devreport_7daf94ac0a1949c1a5c2872dd0df2c1f`(06:18:54 UTC, SENT/HTTP200)다.

### budget600 실패 계약의 저장소 후보 — 2026-10-23 UTC

원 1.0 post-start 실패 schema와 기존 실패 Job/Artifact bytes는 수정하지 않고,
`embedding-benchmark-poststart-failure/1.1` JSON Schema 2020-12와 Pydantic
계약을 추가했다. 새 관측은 budget600 CPU unit, 원 `FAILED`/`CONFIRMED` root
completion, 별도 `UNCERTAIN` record, 보존된 retirement, 임시 template과
before/stopped/restored window의 정확한 hash를 pin하도록 설계했다. 계약 파싱은
실행 권한이나 재시도 허가가 아니다.

기존 Orchestrator failure closure/Journaling 경계를 재사용해 1.1 결정을 같은
RUNNING→FAILED append-only 전이로 다룰 수 있는 source candidate를 추가했다.
합성 SQLite에서 새 successor의 첫 예약 1건을 실패로 닫고, 원 실패 Job과 새 실패
Job의 이력을 모두 보존하며 동일 결정 재조회가 새 전이를 만들지 않는 것을 검사했다.
1.0 경로의 기존 검증과 함께 집중179 PASS, release schema inventory33 PASS,
core source strict mypy와 Ruff를 확인했다. 합성 검사이므로 실제 root proof,
운영 DB closure, 모델 실행, GPU 실행 또는 GPU 기본값 승인을 뜻하지 않는다.

특히 **운영의 새 Job은 아직 정식 closure 전**이다. 보호된 window/retired-template
bytes와 현재 PID1/cgroup을 재검증하고 1.1 관측을 mint/read하는 설치 어댑터,
그 어댑터의 격리 검증·배포·실제 사용자/자료 재인가가 다음 단계다. 그 전에는
기존 Job row를 직접 바꾸거나 새 benchmark successor를 제출하지 않는다.

### budget600 운영 window의 읽기 전용 검증 — 2026-10-23 UTC

저장소 후보에 유한 window 전용 보호 파일 리더를 추가했다. 원 root-owned
`before`/`stopped`/`restored` 기록의 정본 JSON·고정 service 집합·실제 controller
invocation·상태 전이·서로 다른 복구 invocation, CPU service/socket의 보존된
template SHA, 원 systemd load path 부재를 함께 확인한다. 파일/상위 디렉터리
identity와 ACL을 capture 후에도 다시 확인한다. 가짜/변조 기록을 거부하는
합성 검사 8 PASS, 새 실패 계약·application 포함 집중 18 PASS, 새 리더 strict
mypy PASS다. 첫 직접 실행에서는 운영 root stage가 `0755`이고 retired-template
디렉터리가 `0700`이라는 차이가 드러나 리더를 실제 보호 모드에 맞게 바로잡았다.
수정 후 정확히 **원 before `9bd7daea...`, stopped `f7f5788c...`, restored
`c6705352...` 해시**로 운영 파일을 읽기 전용 검증해 PASS했다. 이 검사는
root proof 출판, 원 Job failure closure, 새 모델 실행 또는 GPU 기본값 전환이 아니다.
현재 normal INDEX/QUERY 경로는 유지한다.

### 06:28 UTC OS zlib 갱신에 따른 CPU INDEX 중단 — 2026-10-23 UTC

이전 문단의 서비스 상태는 그 시각의 스냅샷이다. 이후 `dpkg.log`에
`zlib1g`/`zlib1g-dev`의 `...2.2 → ...2.3` 갱신이 06:28:00 UTC 기록됐다.
실제 `/usr/lib/x86_64-linux-gnu/libz.so.1.3`는 같은 시각 ctime이 바뀌었고
현재 SHA-256은 `f61677c7bdb7c2aa2a243ea781bfd16afcb361cede7b4ef76127a9d8eb9a5242`,
기존 승인 해시 `86200da370f20476a2507e9097a789b5ef97269b4ca8d5e164ad82dab9d99892`와
다르다. 이 OS 변화 후 INDEX owner는 06:29:57 UTC에 실행 준비 검증 거부로
종료됐다. 한 번의 기존 unit 재시작은 시작 직후 06:53:21 UTC 실패했고,
별도 격리 read-only verifier가 정확히 이 `libz.so.1.3`의
`INSTALLED_RUNTIME_FILE_HASH_MISMATCH`를 반환했다. QUERY owner는 별도
실행 중이다. INDEX는 현재 `failed`이며 정상으로 보고하지 않는다.

처음에는 `WorkflowRuntimeNotReady`를 일시적 큐 준비 거부로 해석했으나,
보호된 설치 검증을 추적하면서 같은 OS 파일 교체가 근본 원인임을 확인했다.
이를 서비스 안에서 무조건 catch해 정상 실행처럼 남기는 source 변경은
철회했고 작업 트리는 원상 복구했다. 기존 실패/승인 기록이나 DB row를
수정하지 않았고 GPU launch/default 전환도 하지 않았다.

다음 순서는 OS 갱신 완료 여부와 전체 고정 host closure를 확인하고,
기존 snapshot/config/receipt를 보존한 새 host configuration 및 native
installation 증거를 지원된 경계로 발급·검증한 뒤 INDEX를 복구하는 것이다.
기존 verifier의 hash 검사 완화, 이전 `libz` 파일 되돌리기, 무조건 재시작,
미해결 benchmark Job의 직접 DB 수정은 금지한다. 이 CPU 복구가 끝나기 전
GPU 비교의 새 실행을 시작하지 않는다. 개발 Slack 보고
`devreport_ed5d0793ca8e411ba0b0a9aa7ffe026d`가 07:02:49 UTC 발송됐다.

### 06:28 OS zlib 갱신 후 CPU 서비스 복구 — 2026-10-23 07:44 UTC

`libz.so.1.3`의 실제 새 SHA-256을 반영한 host snapshot
`embeddinghostconfigrev_76048812b8d740ad9ebedfe76bbf5ed4`와 같은 numerical
runtime을 가리키는 CPU native config
`embeddingnativeconfigrev_fa612fc539d34effbfb4bfcaf875928a`를 발급했다.
보호된 CPU prefix는 원본을 보존한 상태로 설치했고, 실제 host bytes probe 및
installation seal `31675d57ff9cb7f3d17acb230a34823c969f1635859ee394d674919b80573092`
검증을 통과했다. 모델 forward는 실행하지 않았다.

INDEX와 세 QUERY 소비자의 설정 및 연동된 systemd unit 환경값을 동일한 새
설치 revision으로 전환했다. 전환 전/후의 6개 파일 해시와 서비스 quiescence를
검증했고, 기존 정본 DB/Artifact/benchmark 실패 기록은 수정하지 않았다.
INDEX는 07:43:40 UTC `LOCAL_INDEXING_SERVICE_STARTED`, QUERY는 07:44:01 UTC
`REFERENCE_QUERY_OWNER_READY`를 기록했다. 두 owner는 07:44 UTC 현재
`active/running`이며 CPU 기본값을 유지한다. 이 복구는 이전 budget600 CPU 실패를
성공으로 바꾸거나 GPU 비교를 완료한 것이 아니다. 최초 설정 준비 시 새 cache bind가
빠진 시도는 설치 admission에서 거부됐고, 정확한 cache를 bind한 후속 준비와
설정 선택이 PASS했다. 개발 Slack 복구 milestone은
`devreport_ab754716b5734297ad9013553739c325`(SENT/HTTP200)다.

### budget600 원 실패의 정식 종료 준비 — 2026-10-23 UTC

원 실행 `a038b51d231a47e9866766c8a6b6e476`의 `COMPLETED`/`UNCERTAIN`
root control 두 기록은 같은 Job·execution·invocation·association을 가리킨다.
`COMPLETED`는 원 native 결과 `FAILED`와 cleanup `CONFIRMED`를 보존한다.
이는 성공 결과가 아니며 중복 재실행 허가도 아니다. 현재 PID1의 원 controller는
동일 invocation의 `failed/exit-code`, retired budget600 native service/socket은
`not-found/inactive`이고 해당 cgroup은 비어 있다.

저장소 후보는 기존 bounded handoff/partial-output capture를 재사용하고,
retired budget600 unit과 보호된 finite window를 별도 관측하는 adapter를 추가했다.
정본은 원 request/invocation, 원 root control, 원 retirement/window 기록이다.
키 조회는 execution ID, append-only 실패 이력은 원 Job sequence이며,
새 증명은 원 revision/hash들을 고정해 root-local 한 번만 생성한다. 동시 생성은
`O_EXCL`, 기존 증명의 재조회는 동일 해시·현재 출처 재검증으로 처리한다.
별도 DB/schema/queue나 worker-to-worker 경로는 추가하지 않는다.

원 파일·PID1의 읽기 전용 capture가 격리 unit에서 PASS했다. 정식 증명 경로와
분리된 보호된 canary 위치에서 root proof 생성 `created=True`, 동일 입력 재조회
`created=False`(같은 raw SHA), 실제 owner UID의 proof 재검증도 PASS했다.
이 과정에서 모델 forward, 새 Job, 운영 DB 전이, NAS 게시, canonical proof 발행은
수행하지 않았다. 다음은 이 source candidate의 회귀 검증·설치 후 canonical proof를
발급하고, 재인가된 Orchestrator application으로 원 Job만 정식 FAILED 종료하는 것이다.

### budget600 원 CPU Job 정식 종료 — 2026-10-23 08:24 UTC

source `0e332c5dcec306bb7febfa696672accf3571f1e4`의 설치 wheel/RECORD와
원 실행의 보호된 증명을 owner UID로 검증했다. 실제 `guiadmin` 로그인 뒤 지원된
Orchestrator application이 원 Job `job_26e206dc11434d52870f51737d15fdbd`를
`RUNNING→FAILED`로 기록했다. event sequence는 8, 결정 SHA-256은
`1181768f0d92103982ed1dffd8c391a1a6659f6abe77c1a7dbdb7f92bd89db4b`다.
동일 요청의 즉시 재확인은 `created=false`였고 새 Job·native launch·model forward는
모두 0이다. 과거 실패, 부분 출력 및 원 Artifact는 보존했다. Slack milestone
`devreport_24da82656736481db06c854c2f151ee5`는 SENT/HTTP200이다.

첫 CPU 실행은 cold 18행 파일까지 약 2분 29초, 보조 30벡터 파일까지 약 9분
34초가 걸렸고 warm/query/capacity 완료 전에 600초에 종료됐다. 따라서 동일
600초 작업의 무조건 재시도는 하지 않는다. 다음 실험은 같은 모델·고정 입력·검색
축에서 먼저 실제 CPU/GPU 처리량을 작은 범위로 측정하여 적정 실행 상한을
결정하고, 그 결과에 맞는 새 versioned recipe로 원래의 수치·순위·자원·공존
acceptance를 진행한다. 이 진단만으로 GPU 기본값은 전환하지 않는다.

#### 다음 실행의 경계: 짧은 비교 진단

책임은 기존 Orchestrator owner가 지며 정본은 고정된 source/Graph/모델·설치
revision과 staged-input Artifact다. 새 실험은 새 logical revision으로 만들고,
원 1.0/1.1 요청·실패 기록을 재해석하지 않는다. source·policy·모델·입력 hash와
operator 권한을 실행 전에 재확인하며 worker는 로컬 입력·출력만 다룬다.
키 조회는 revision/Job/ordinal, 고정 출력은 순서 있는 manifest, 중복 제출은
기존 idempotency key/unique constraint로 처리한다. 최대 수십 행이므로 메모리는
`O(rows × 1024)`, 각 encode는 모델 비용이 지배한다. DB transaction은 예약과
Artifact 게시에만 사용하고 모델 실행 중에는 열어두지 않는다. 실패·timeout은
같은 Job을 재시작하지 않고 원 기록을 정식 종료한 뒤 successor로만 재시도한다.
단순히 600초를 늘리는 대안은 첫 실행의 CPU 처리량과 900초 인증 신선도에
맞지 않아 제외한다. 이 진단의 수치가 좋아도 별도의 원래 acceptance에 필요한
반복·긴 입력·GPU 공존/복구를 생략하지 않는다.

첫 지연 원인 조사에서 설치된 CPU prefix의 일반 파일은 약 27,509개다.
`NumericalRuntimeFileSnapshots.assert_unchanged()`가 검증 대상 파일마다 공통
상위 경로를 반복 `lstat`하는 경로를 확인했다. 단일 snapshot 검증 안에서
상위 경로의 예상 identity를 deduplicate하고 파일 identity는 모두 그대로
검사하도록 바꿨다. 공통 상위 경로를 검사 전후 한 번씩 확인한다. 합성
64파일 검사에서는 공통 경로 확인이 64회에서 2회가 됐고, 설치된 CPU
prefix의 실제 torch 파일 1,000개를 대상으로 한 읽기 전용 메타데이터
중앙값은 기존 27.6ms, 새 방식 5.4ms(5.10배)였다. 관련 source 테스트
429 PASS, Ruff·strict mypy PASS다. 같은 방식의 실제 5,000파일 표본은
150.0ms→28.5ms(5.27배)였다. 이는 모델 추론 시간 개선의 증거가
아니므로 새 설치 runtime의 실제 CPU/GPU 실행 시간은 별도로 측정한다.
