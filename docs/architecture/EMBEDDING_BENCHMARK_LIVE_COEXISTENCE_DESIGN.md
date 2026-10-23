# 임베딩 비교 실험의 운영 서비스 공존 설계

상태: 구현·소스 검증 완료, 운영 설치 대기
기준: 2026-10-23  
범위: 기존 고정 입력·모델·검색축을 사용하는 CPU/GPU 비교 실행의 서비스 격리

## 결정

비교 실험을 위해 운영 INDEX/QUERY owner 서비스를 중지하거나 기존 unit template을 교체하지 않는다. 현재 budget600 supervisor의 finite window는 두 owner에 SIGTERM을 보내고, 종료를 기다린 뒤 같은 이름의 benchmark template으로 교체한다. 실제 운영 로그에는 유사도 읽기가 계속 관측된다. 이 방식은 실험 중 사용자 조회를 끊을 수 있고 전체 시리즈 시간만큼 중단을 유지하므로 다음 비교 실행에는 사용하지 않는다.

새 benchmark launch는 기존 `BenchmarkWorkerInvocation`, Orchestrator Job/ordinal 기록, Artifact publication, CPU capacity lock 및 CUDA lease를 그대로 사용한다. benchmark 전용의 고정된 systemd unit family를 별도로 설치·검증하여 launch별 고유 execution ID로 실행한다. 운영 owner unit, service revision, 기존 설정 파일은 수정하지 않는다. unit template의 추가가 기존 systemd 권한 경계와 충돌하면 실행을 중단하고 이름/권한 구성을 다시 설계한다.

## 경계와 정본

- 책임 경계: Orchestrator benchmark owner가 현재 관리자 권한·고정 source/model/runtime pins·Job ordinal을 검증하고 기존 native executor에 단일 launch를 위임한다. worker는 로컬 staged input을 읽고 결과를 제출한다. Artifact commit은 기존 Orchestrator publisher만 한다.
- 정본: 기존 benchmark request/revision, staged-input Artifact revision/hash, source/Graph/policy/model/runtime pins, Job/launch event와 결과 receipt다. 새 DB, queue, registry, 모델 정본은 추가하지 않는다.
- identity: logical benchmark ID, immutable benchmark revision, Job ID, per-launch execution ID, Artifact revision ID와 content SHA-256은 기존대로 분리한다. 새 launch는 기존 ordinal을 재사용하지 않는다.
- pointer resolution: 기존 application 경계가 permission, lifecycle, schema, media type, hash와 exact revision을 계속 검증한다. 직접 DB/NAS 조회·수정으로 이를 대체하지 않는다.

## 데이터 구조와 비용

주요 연산은 Job ID/ordinal의 indexed lookup, 고정 순서 6개 launch의 반복, append-only receipt, 중복 방지다. 기존 indexed Job/state relation과 unique/idempotency 규칙을 재사용한다. 별도 in-memory queue나 polling scan을 추가하지 않는다. launch 처리 메모리는 기존 worker contract bound에 따르고 controller 상태는 O(1), receipt 순회는 O(launch 수)이며 launch 수는 6으로 고정된다. 운영 검색이나 기존 인덱스에는 추가 비용이 없다.

## 동시성·실패·복구

- CPU launch는 기존 `native_cpu_capacity` nonblocking lock과 native unit/cgroup 검사로 동시 CPU encode를 거부한다.
- CUDA launch는 기존 GPU lease, VRAM/resource limit, invocation-bound cgroup 및 cleanup proof를 유지한다. GPU 작업이 이미 점유 중일 때 우선순위를 강제로 뺏지 않는다. admission에서 거부하거나 정해진 capacity가 확보될 때까지 요청을 제출하지 않는다.
- benchmark 전용 unit은 invocation ID와 고정 service family로 결합한다. 운영 INDEX/QUERY owner의 PID·InvocationID·설정 hash는 전후 동일해야 한다.
- timeout, process 종료, lease 불명 또는 cleanup 실패는 실패/불확정으로 보존한다. 같은 ordinal을 재발행하지 않는다. supported post-start closure 후에만 successor revision을 만들 수 있다.
- 600초 실행이 실패한 뒤 1200초 정책으로 이동할 때는 기존 `/1.1` 실패 결정의 `BenchmarkBudget600PredecessorReference`를 새 `/1.2` 요청의 append-only predecessor event로 기록한다. 기존 `/1.0→/1.1` 및 `/1.2→/1.2` 전환 규칙은 바꾸지 않는다. source, corpus, model, runtime, 검색축은 동일해야 하며 revision/policy budget 이외의 변경은 거부한다. 새 Job은 원 600초 실패의 지원된 closure가 확인된 뒤에만 등록한다.
- launch 종료 뒤에도 Artifact/receipt/hash를 재검증하고 같은 request의 idempotent replay가 기존 receipt를 돌려주는지 확인한다.

## 의존 방향과 배포

`Orchestrator use case → typed benchmark contract → fixed executor port` 방향을 유지한다. systemd와 GPU 장치 접근은 Catalog의 기존 native launch adapter가 소유하고, 도메인/contract는 systemd나 파일 경로를 import하지 않는다. 외부 API·worker 직통 호출·root Codex auth·운영 owner unit 변경은 금지한다.

새 systemd template는 기존 benchmark unit policy에서 지원하는 고정 실행 값만 담고, 첫 설치 전에 unit bytes/hash, `DeviceAllow`, `ReadWritePaths`, `InaccessiblePaths`, UID/GID, cgroup, timeout, cleanup, 설치/복구 순서를 검증한다. 운영 owner가 실행 중인 상태에서 isolated systemd admission test를 먼저 통과해야 한다. 배포 전후 실제 HTTPS similarity read, owner PID/InvocationID, API health를 확인한다. 회귀 시 새 benchmark unit만 비활성화하며 기존 owner와 native data는 변경하지 않는다.

2026-10-23: v1.2 CPU/CUDA unit family와 post-start failure closure가 구현되었고 571개 회귀 테스트, lint/type/systemd 검증을 통과했다. Commit `9e6efc165d97e57f1bc089134f229bff1a0c2df6`의 API/platform/contracts release는 protected release-operator `ADMIT_PASS`, migration/role/isolation verification PASS, build/RECORD PASS와 installed API health verification PASS 후 배포됐다. API와 Catalog runner가 새 invocation으로 active다. INDEX owner는 원 invocation으로 계속 active지만 QUERY owner는 표준 배포 과정에서 재시작되어 새 invocation으로 active다. 이 짧은 query-owner 교체는 무중단 공존 gate의 성공으로 간주하지 않고 보고서에 남긴다. 운영 GPU는 RTX 5080 0%/2 MiB였고 GPU 비교 실행은 아직 시작하지 않았다. 1200초 entrypoint는 `/opt`의 고정 CPU/CUDA runtime에 아직 게시되지 않았으며, 다음은 기존 격리 runtime successor/admission 경계로 이를 연결하는 것이다. 보호 경계를 우회하는 직접 root 복사나 owner 중지는 대체 경로로 사용하지 않는다.

## 검증 게이트

1. JSON Schema 2020-12/Pydantic 및 기존 protocol compatibility; request/policy bytes와 과거 revision 불변.
2. CPU/GPU unit 이름 격리, owner unit 불변, 동시 CPU claim 거부, GPU lease/VRAM/cleanup 경계, timeout·재시도·idempotency 테스트.
3. live preflight에서 INDEX/QUERY owner가 계속 active/running이고 invocation/config hashes가 전후 동일.
4. 각 ordinal 이후 실제 similarity read가 성공하고, 운영 owner가 중지·재시작되지 않았음을 확인.
5. 기존 fixed input/model/search axis로 CPU/GPU 실제 실행, 수치 허용오차·ranking parity·warm/cold/query timing·VRAM peak 기록.
6. 별도 GPU lease 점유 상황에서 안전한 거부 및 release 후 재시도, unit 종료·orchestrator 재시작 후 복구 검증.
7. GPU 기본값 전환은 모든 수치/품질/공존/복구 gate의 실측 PASS 뒤 별도 successor runtime으로만 한다. 실패/불충분 시 CPU 기본값 유지.

## 단순 대안과 제외 이유

현재처럼 두 owner를 통째로 중지하고 그 이름의 unit을 바꾸는 방식은 구현은 쉽지만 실제 조회 경로를 시리즈 전체 동안 끊는다. 반대로 활성 owner가 실행 중인 이름의 unit template을 교체하는 것도 systemd 상태와 설치 provenance를 혼동시킬 수 있어 제외한다. 새로운 benchmark 전용 family를 추가하는 것이 기존 contract·executor·lease 경계를 재사용하면서 운영 서비스와 실험의 identity를 가장 작게 분리한다.

기존 `embedding-device-benchmark` 입력·수치 축은 바꾸지 않는다. 600초 CPU launch가 600초 안에 끝나지 않고 부분 출력만 남긴 실측 때문에 policy/request/invocation successor `/1.2`의 고정 1200초 계약을 추가했다. V1.0/V1.1 의미는 보존한다. 2026-10-23 현재 JSON Schema/Pydantic, 전용 CPU/CUDA 진입점·systemd unit family, CPU-capacity 관측 allowlist, 그리고 v1.2 CPU1 post-start failure closure가 source에 연결됐고 관련 571개 회귀 테스트, strict mypy, Ruff 및 systemd 문법 검증을 통과했다. root 설치와 실제 실행 검증은 아직 하지 않았으므로 v1.2 요청을 운영에 게시하거나 비교 실행을 재개하지 않았다.
