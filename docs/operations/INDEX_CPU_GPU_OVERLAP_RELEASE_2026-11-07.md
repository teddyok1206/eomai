# CPU 예비 인덱스가 GPU 진행을 막던 순서 수정

2026-11-07 UTC. 설계: [INDEX CPU/GPU overlap](../architecture/LOCAL_INDEXING_CPU_GPU_OVERLAP.md).

## 원인과 범위

운영 INDEX `fedb9750`는 같은 프로세스에서 CPU command를 끝낸 뒤에만 다음 CUDA
reconciliation을 호출했다. 07:47:49 CUDA batch 완료 뒤 CPU command가 08:15:34까지
이어졌다. 약 27분 45초는 수치 연산뿐 아니라 source 검증·publication을 포함한다.
이때 GPU 0%는 새 서비스 장애나 전체 완료 증거가 아니었다.

수정은 기존 owner의 bounded scheduling에 한정한다. CPU outstanding 호출 최대 1개와
GPU main call을 겹쳐 실행하며 기존 queue·lease·예약·권한·Graph/policy pin·CPU/CUDA
별도 space·정확한 공통 검색 scope는 유지한다. 원래 CPU 요청은 CPU로 완료하고 GPU
결과를 CPU 결과로 재분류하지 않는다. 모델·수치 controller·API·Web·QUERY·창작 슬롯,
DB migration은 변경하지 않는다.

## 검증

- focused scheduling/namespace/resource/context 회귀 141 PASS.
- routed composition/document backend/target selection/context 회귀 70 PASS.
- 마지막 service entry 변경 후 entry/overlap 회귀 33 PASS. 위 집합과 중복이며 합산하지 않는다.
- ruff format/check, 변경 production 모듈 3개의 mypy PASS.
- disposable PostgreSQL `/tmp/eom-api-testdb-20261107081051_c958aeb7`에서 0074 migration
  round-trip과 기존 native claim/replay/prepare/permission tests를 실행했다.
  첫 suite는 272 PASS + 새 fixture 2 FAIL이었다. 새 fixture가 동일 request를 두 번 만들어
  기존 active-equivalent dedup에 의해 같은 command를 가리킨 것이 원인이다. 이를
  실제 CPU/CUDA 두 namespace의 서로 다른 유효 요청으로 고쳤으며, 해당 runner suite
  24개(새 두 케이스 포함)를 모두 다시 통과했다. 운영 실패나 보호 규칙 완화가 아니다.
- 첫 로컬 pytest 호출의 source path 누락, 추가 suite의 잘못된 파일명은 invocation 오류다.
  명시 source closure/실제 파일명으로 재실행했고 설치본 테스트를 source PASS로 세지 않는다.

## 인계 기준선

- 기존 PID `1626367`, invocation `67ec9e4eca6e4dd8b4c5ce22b998bbf8`.
- 08:14:10 UTC 현재 원래 CPU Workflow 하나만 RUNNING인 것을 확인한 뒤 main에만 SIGINT.
  수치 worker·GPU root·창작 슬롯에는 신호를 보내지 않았다.
- `workflow_3760cd8fec8342e7b32df0046db1f407` / `wfcmd_6a90cf3e17ac476f9d4c048dd68f5604`
  는 08:15:34 SUCCEEDED, owner exit status 0으로 자연 종료했다.
- 같은 시점 기출 CUDA 등록 337/520, 창작 Graph 1,034. 전체 완료 수는 아니며 device/view별
  index binding 수와 혼동하지 않는다. 기존 벡터·실패 이력은 삭제하지 않는다.
- 정확한 drain 기록은 `/var/lib/eom-index-overlap-drain-20261107/drain.json`이다.
  최초 read-only 진단의 device JSON 경로 오류는 수정 후 재확인했다. 최초 호출은 신호나
  설정 변경 전에 거부되었으며 별도 로그를 보존했다.

이 문서의 위 항목은 소스 검증/안전한 기존 작업 종료 증거다. 새 release의 설치·활성화,
실제 CUDA commit과 CPU/GPU 진행 중첩 증거는 후속 체크포인트에 따로 기록한다.

## 운영 반영 — 08:30 UTC

- source/설치 release: `11a75c955183523348bb3063a3e0929661101110`, `origin/main` push 완료.
- immutable owner wheel의 RECORD와 API contracts 설치 검증 PASS. 비편집 설치본으로
  scheduler/namespace/runtime 51개 PASS. CUDA 수치 worker와 CPU 수치 환경은 교체하지 않았다.
- 기존 INDEX가 정상 종료한 후 기존 공식 service identity/grant publication 경계로
  successor를 선택했다. 출처 scope·routing·CPU/CUDA runtime profile의 동등성을 확인했다.
  기록: `/var/lib/eom-index-overlap-release-11a75c95-20261107`.
- 새 INDEX PID `2717326`, invocation `a1c97c53ec5847d989e76e88a8b26469`.
  08:27:04 시작, 08:27:26 `LOCAL_INDEXING_CPU_OVERLAP_ENABLED(maximum_cpu_calls=1)`과
  첫 `CONCRETE_FACETS` reconciliation 진입을 확인했다.
- 08:30 관측에서 NRestarts=0, 새 실패 없음. GPU/CPU/QUERY environment bytes와 수치 profile
  불변, API/Web/QUERY/창작/자료 학습의 PID 및 invocation 불변을 확인했다.
- disposable DB는 공식 cleanup으로 삭제 완료. 운영 DB에 pytest를 실행하지 않았다.
- 최초 protected installer 호출은 파일이 executable이 아니어서 거부됐다. 뒤따른 설치본
  테스트/PREPARE도 실제 설치 전 import 단계에서 거부됐고 활성화는 없었다. 보호된
  스크립트를 `/bin/bash`로 실행한 뒤 설치·검증·PREPARE/PUBLISH/ACTIVATE를 정상 완료했다.
  보호 권한을 변경하거나 실패 기록을 삭제하지 않았다.

이 시각에는 첫 source 검증이 진행 중이다. **새 CUDA commit/실제 CPU와 GPU의 중첩 완료는
아직 관측하지 않았다.** source/설치 테스트 PASS와 service 기동을 그 증거로 확대하지 않는다.
기출 등록은 337/520, 잔여 183으로 기존 누적값을 유지하며 기존 10분 관측·Slack timer도 유지한다.

## 실제 처리 재개 — 08:33 UTC

새 release가 준비 단계만 반복하는지 별도로 대조했다. 08:31:50에 생성한 CUDA
`workflow_a6d5489790c9476cb6517a7228164a40` /
`wfcmd_f373266464134cb4903a20ae99d6db13`이 실제 RUNNING/PROCESSING이며,
attempts=1, lease_generation=1, heartbeat에 따른 lease 갱신과 failure/error_code=null을
08:33:53에 확인했다. 이것은 실제 원래 application 경로의 처리 재개 증거이며,
GPU 수치 완료·index commit·CPU와 다음 GPU 작업의 실제 중첩 완료 증거는 아니다.
재계산/재시작 없이 이 요청을 계속 처리한다.

## 후속 실제 관측 — 부분 성공과 새 중단, 13:59 UTC 확인

- 첫 CUDA Workflow는 09:01:22 BATCH_COMPLETED이며 command SUCCEEDED. 기출 등록은
  337→339/520으로 증가했다. 한 batch의 4 targets와 기출만의 증가량 2는 다른 분모다.
- 09:02:22 다음 GPU 준비와 CPU standby가 실제 중첩됐으며 CPU
  `workflow_090b1c121e6b49c99c4e2e24ce36e485`는 09:32:08 COMPLETED/SUCCEEDED였다.
- 다음 CUDA `workflow_bfb8b5f72e4544b8b9f644f3407bab4a`는 channel의
  `EMBEDDING_BENCHMARK_CHANNEL_EXPIRED`로 owner가 09:32:09 종료했다. CPU drain은 완료됐다.
  13:59 관측에서 실제 worker/controller lifetime는 전부 drained지만 해당 Workflow는
  RUNNING, command PROCESSING/만료된 lease로 남아 있다. 운영 정상 진행으로 세지 않는다.
- 두 device의 중첩 자체와 첫 commit은 확인됐지만 **전체 연속 처리 안정성은 미완료**다.
  유한 allocation 시간 안에 들어가는 실제 source/owner 검증 비용과 completion 증거를
  추가로 확인해야 한다. 만료된 권한을 연장·재사용하거나 row를 직접 성공 처리하지 않는다.
  이번 슬롯 재개 작업에서는 GPU 재시작·다른 key의 재계산을 제출하지 않았다.
