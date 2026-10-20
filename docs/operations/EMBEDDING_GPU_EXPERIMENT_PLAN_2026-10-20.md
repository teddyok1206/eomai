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
