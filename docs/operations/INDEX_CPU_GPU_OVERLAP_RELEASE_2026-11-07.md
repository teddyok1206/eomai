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
