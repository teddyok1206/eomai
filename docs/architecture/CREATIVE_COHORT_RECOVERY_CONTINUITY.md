# 창작 원본 처리의 명시적 복구 결과 연결

## 범위와 정본

기존 cohort 처리기가 최초 분석의 멱등 key를 다시 읽으면서, 별도로 승인·완료된
predecessor-linked retry를 무시하는 결함을 수정한다. 과거 FAILED를 바꾸거나
재시도·Graph·queue 프레임워크를 새로 만들지 않는다. 정본은 기존 분석 run의
`predecessor_analysis_run_id`, 고정 source/preset/policy와 accepted Artifact다.

논리 문항/Item revision/분석 run/Artifact revision/hash는 기존처럼 분리한다.
내부 read use case는 원 분석과 명시적으로 연결된 retry만 찾고 typed 기존 projection을
반환한다. 새 worker protocol, 공개 wire schema, DB migration은 필요하지 않다.

## 조회·경계

- 분석 owner가 원 run의 존재와 요청자·현재 권한을 확인한다. caller는 원본 재인가와
  동일 고정 preset/source/policy 검사를 유지한다.
- FAILED/REJECTED/CANCELLED에서만 predecessor FK의 indexed lookup을 수행한다.
  연결마다 operator, source revision/Artifact/hash, preset revision과 risk policy,
  요청 schema·general-knowledge mode가 같아야 한다. 다른 문항·버전·풀이 추가 분석을
  '복구'로 채택하지 않는다.
- successor가 하나면 그 exact identity로 진행한다. 없으면 원 실패를 그대로 반환한다.
  복수 가지·cycle·최대 길이 초과는 명시적 오류이며 latest/성공 우선 추측을 하지 않는다.
- 체인은 최대 32단계, visited set과 기존 predecessor B-tree index를 사용한다.
  시간 O(depth × indexed lookup), 공간 O(depth). 전체 corpus scan/N+1은 없다.

이 조회는 쓰기·claim을 하지 않는다. 기존 create의 unique idempotency와 기존
reconcile/accept/Graph publication이 transaction과 side effect를 계속 소유한다.
동시 retry 생성이 조회 직후 발생하면 다음 관측에서 연결하며 중복 요청을 만들지 않는다.
cohort의 빠른 경로도 실패한 최초 run만 보고 중단하지 않고 같은 owner를 통해 확인한다.

## 나머지 원본 보류

실제 `WORKER_EXEC_FAILED` 및 이미 실패한 Workflow의 고아 실행에 새
`creative-execution-recovery/1.0` 감사 링크를
기존 successor 준비 use case에 추가한다. 기존 invalid-result/launch 계약은 바꾸지 않는다.
원래 Workflow/step/Job이 같은 사유로 FAILED이거나, Workflow/step이
`WORKFLOW_STEP_FAILED`이고 Job은 error/exit 없는 역사적 RUNNING인 경우로 한정한다.
commit 이력·Artifact·살아 있는 command/lease가 없으며 모든 실제 고정 worker unit도
없음을 확인한 뒤에만 명시적으로
한 번 준비한다. parent row lock과 기존 unique Workflow key가 동시 제출을 직렬화한다.
같은 source/plan/preset/operator를 유지하며 JSON Schema→Pydantic→기존 Workflow event와
successor runtime context에 작은 hash-bound link만 남긴다. 과거 실패와 원본은 보존한다.

운영 보류는 변환 실패, worker 완료 후 proposal 없음, 실제 실행 실패를 분리한다.
원본/결과를 공식 resolver로 확인하고, 지원되는 명시적 recover/reconcile 경계만 사용한다.
내용을 꾸미거나 실패 결과를 수정해 등록하지 않는다. 새 입력/worker 재처리가 필요하면
원본 hash와 이전 실행을 보존한 명시적 successor로 처리한다. 이미 완료된 다른 문항과
실행 중 INDEX의 runtime/namespace/벡터는 건드리지 않는다.

단순 서비스 재시작은 복구 연결 누락을 해결하지 못한다. 반대로 전체 1,053건을 다시
풀이시키는 방법은 이미 accepted인 결과를 중복 생성하므로 사용하지 않는다.

## 검증·배포

failed→accepted/running retry, 두 단계 체인, source/policy/operator/hash 불일치,
복수 가지·cycle·한도, retry 없음, repeated read, 권한 철회를 focused test로 확인한다.
disposable PostgreSQL에서 실제 predecessor index 조회·동시 read/retry와 실패 이력
불변성을 확인한다. metadata producer만 graceful handoff하며 GPU owner는 보존한다.
실제 복구된 문항의 공식 report read/Graph membership와 후속 실제 slot claim을 따로 보고한다.
