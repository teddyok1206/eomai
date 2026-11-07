# INDEX 실행 상태 조회 지연 복구

## 확인된 원인과 수정 경계

2026-11-07 15:54 UTC 마지막 CUDA batch가 완료된 뒤, INDEX runtime authority의
`systemctl show` 읽기 전용 조회가 2초 안에 끝나지 않았다. 단 한 번의
`TimeoutExpired`가 `EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE`로 전파되어
관리 프로세스가 종료됐다. GPU 계산 실패나 원본 미준비로 인한 대기가 아니다.

책임은 기존 Identity runtime adapter의 OS 상태 관측이다. 이 subprocess만
2/5/10초 상한으로 최대 3회 시도한다. 정상 조회는 추가 호출하지 않으며 결과를
캐시하지 않는다. 재시도 성공 후 기존 PID/invocation/UID/config/wheel/file epoch
검사는 모두 수행한다. 잘못된 응답·비정상 종료·권한 오류·설정 변화는 재시도하거나
무시하지 않는다. 세 차례 모두 시간 초과라면 기존 오류로 명시적으로 거부한다.

추가 구조·DB·schema·queue·설정은 필요 없다. 고정 tuple의 O(1) 읽기 재시도이고,
실패 subprocess는 기존 `subprocess.run`이 종료·회수한다. 공유 상태가 없어 CPU/GPU
관측 스레드 간 새 lock도 필요 없다. 임베딩 submit/commit/claim은 반복하지 않는다.
상태 확인을 생략하거나 서비스 전체를 무조건 재시작하는 대안은 실제 설정 변경을
숨기거나 작업을 중복시킬 수 있어 사용하지 않는다.

## 검증·운영 경계

일시 지연 1/2회 후 정상 응답, 총 시도 상한, 다음 조회의 새 관측, 부분 응답·stderr·
비정상 종료·OS 오류, 지연 중 invocation 변경을 검증한다. 기존 runtime admission 및
파일·hash·권한 거부 검사를 유지한다. production 테스트 row를 만들지 않는다.

운영 반영은 기존 INDEX owner successor 절차를 사용한다. 원래 요청의 실제 상태와
수치 worker 종료를 먼저 확인하고, 미완료 요청은 기존 지원된 recovery/cancel 경계로
분류한다. 기존 완료 벡터·원본·Graph·실패 이력은 보존한다. GPU 모델/space/정규화와
API/Web/QUERY 실행은 바꾸지 않는다. 설치 증거와 실제 재개 결과는 후속 기록한다.

## 수정본 및 실행 증거

- source `1083b89f11bbd2c1cff75773213e062c5ecf373e`.
- focused unit 119 PASS, Ruff format/check 및 focused mypy PASS.
- guarded disposable PostgreSQL 검사 236 + 22 PASS. 처음의 좁은 `-k` 실행은
  160 PASS 뒤 두 번째 suite가 전부 제외되어 exit 5였으며, 정상 suite 재실행 결과와
  구분해 보존한다. 운영 DB를 pytest 대상으로 사용하지 않았다.
- build-only 및 설치 platform/contracts wheel RECORD 검증 PASS. 별도 immutable
  INDEX release에 설치했으며 API/Web/QUERY와 수치 모델 환경은 교체하지 않았다.

운영 교체 전 두 CPU 작업을 발견했다. `platform_job_id IS NULL`은 native allocation
없음의 증거가 아니다. `workflow_2cf4270baadc4e30b1714b71d8b5ada2`는 native CPU 계산이
실제로 성공했으나 상위 저장이 남아 있었다. preallocation retirement는 기존 guard에서
거부됐고 transaction 변경은 없었다. 실패로 바꾸지 않고 원래 owner를 재개해 같은
명령 generation 2로 결과를 수집하고, SIGTERM의 정상 drain으로 교체 경계를 만든다.
시작하지 않은 다른 standby 한 건은 기존 cancellation application으로 취소했으며
같은 명령 replay도 확인했다. 새 identity로 중복 계산하지 않는다.

릴리스 준비·control publication은 완료했지만, 첫 ACTIVATE는 outstanding 작업을
탐지해 identity/config 변경 전에 중단됐다. 이 실패 기록을 보존하고 기존 release
plan을 이어서 사용한다. 실제 activation/새 batch 완료는 다음 절에서 별도 기록한다.

## 실제 drain 결과와 한정된 운영 인계

기존 owner 재개로 CUDA 새 4개가 실제 계산·저장됐고,
`workflow_e97c028bfa9e489496e7646f721102e6`가 17:33:27 UTC COMPLETED가 됐다.
공통 CUDA index binding은 772 → 776, 기출은 343 → 345/520이다.
그러나 CPU 결과 수집 thread는 이전 코드의 동일한 2초 timeout을 다시 겪었으며,
GPU 작업 후 drain에서 그 예외가 전파됐다. CPU 저장 완료로 보고하지 않는다.

기존 코드를 반복 실행하지 않고 다음 조건으로 INDEX hotfix 인계를 제한한다.
원래 CPU 요청 한 건은 RUNNING/PROCESSING의 역사적 저장 미완료로 보존하며, 그 CPU
unit의 원래 invocation·exit 0·PID 0·FD store 0·빈 cgroup 및 만료된 command lease를
확인한다. 모든 CUDA 작업은 완료됐고 physical native lifetime도 drained이다.
시작되지 않은 다른 CPU standby만 공식 cancellation application으로 종료한다.
Identity의 기존 register/activate/policy-publication 경계를 그대로 사용하되,
배포 helper의 nonterminal=0 선행 검사에서 이 정확한 과거 CPU 요청 하나만 제외한다.
동일 transaction에서 원래 요청 hash/state/command/generation/lease를 잠금 조회한다.
그 요청의 DB 상태·native 결과·예약을 변경하지 않으며, 새 owner는 새 service revision
선택을 사용하므로 과거 요청을 claim하거나 새 계산으로 위장하지 않는다.

이는 runtime 권한/hash 검증 완화나 일반적인 unfinished-work 무시가 아니다.
기존 CPU runtime/workspace는 공식 저장 복구에 필요하므로 삭제하지 않는다.
그 한 건의 CPU 저장 복구는 별도 미완료 사항이다. GPU 운영 재개 및 새 작업의 timeout
수정과 구분한다. 구 CPU 요청이 성공/실패로 확정됐다고 표시하지 않는다.

## 운영 활성화

17:41:42 UTC INDEX source `1083b89f`가 active/PID 3424739로 시작됐다.
17:42:00 UTC 실제 runtime admission·구성 확인을 통과하여
`LOCAL_INDEXING_RECONCILIATION_STARTED`로 다음 GPU 대상 준비를 시작했다.
새 release의 다음 수치 batch 완료는 아직 별도 확인 대상이며, 위 CUDA 4건의
완료는 교체 전 원래 owner의 실제 복구 결과다.

API/Web/QUERY/creative/material 서비스 PID·invocation과 CPU/CUDA 환경 hash가
시작 전후 동일함을 확인했다. 기존 10분 관측·Slack 현재 GPU 사용률 보고는 유지한다.
운영 증거는 `/var/lib/eom-index-unit-observation-recovery-20261107`의
`selected.json`, `started.json`, `retained-cpu.json`에 보관한다.
성공한 CUDA 인덱스의 전체 binding 776개와 기출 subset 345/520은 서로 다른 분모다.
구 CPU index binding 736개 및 저장 미완료 요청은 그대로 보존되어 있다.

위 시점의 운영 기록·빌드·격리 DB 검사·실패/인계 로그 16개 member를 기존
Catalog→Orchestrator commit 경계로 NAS에 보관하고 모두 읽기/hash 대조했다.
감사 Artifact: `artifact_3fb442fffc264d8eb614b07c311e8ea5`,
revision: `rev_4f85697905944df3849fd3d8dd15df81`.
