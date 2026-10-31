# 라우팅 후 BOUND 이전 GPU 준비 실패 복구

2026-10-31 UTC. 기존 owner-only 유지보수 경계의 누락된 경우를 닫는다.

- 책임: Workflow Runner application이 원 Workflow/명령/단계를, Orchestrator가 원
  planning/native Job 이력을 소유한다. root UID와 실제 PostgreSQL schema owner를 모두
  확인한다. worker, 사용자 입력, proof 모양 자체는 권한이 아니다.
- 정본/identity: 원 request/Graph/policy/plan/allocation/step/native intent와 실패한
  GPU invocation/보호된 retirement 기록이다. 성공한 START는 변경하지 않는다.
- 계약: 기존 JSON Schema 2020-12 `embedding-encoding-recovery/1.0`의 RECOVER 명령과
  `ArtifactMemberPointer`를 재사용한다. 이 명령은 원 실패 invocation의 복구 참조이며
  BOUND/encoding 존재를 선언하지 않는다. 기존 allocated recovery의 조건은 완화하지 않는다.
  원 RECOVER bytes를 Orchestrator가 immutable control Artifact로 먼저 저장한다.
- 포인터: 실제 실패 retirement SHA, allocation SHA, 원 plan/request/command generation,
  원 evidence member/schema/media/hash와 canonical bytes를 검증한다. 기존 control reader가
  원 selection/policy를 읽되 새로운 source/실행 권한을 부여하지 않는다.
- 접근/구조: Workflow PK → bounded 명령 두 개 → 단계 하나 → native launch unique key →
  parent Job PK → append-only 이력. indexed O(log N) lookup, 고정 크기 metadata만 사용한다.
  새 DB/index/queue/encoding/벡터는 만들지 않는다.
- 동시성: 짧은 단일 owner transaction에서 Workflow→명령→단계→parent/native locks를 잡는다.
  original START=SUCCEEDED, unclaimed ADVANCE=PENDING(gen0), native ALLOCATION 하나,
  association 없음, parent ROUTED CUDA/RUNNING/BOUND 없음, publication 없음만 허용한다.
  현재 처리 중인 명령/BOUND/encoding이 있으면 이 경로로 복구하지 않는다.
- 전이: parent는 기존 `record_failure`, native는 기존 `record_known_failure`, Workflow/step은
  기존 FAILED 전이, 미실행 ADVANCE는 CANCELLED 전이를 사용한다. 원 성공 START와 과거
  실패는 보존한다. claim/lease를 초기화하거나 원 실패를 성공으로 바꾸지 않는다.
- replay/실패: 원 명령/evidence를 한 개의 Workflow event에 고정한다. 정확한 replay만 같은
  결과를 반환하고 foreign pins/recovery, late physical change, lease/BOUND 경쟁은 전부 rollback한다.
  이후 작업 생성은 기존 증분 발견/명시적 retry 경로가 맡고 이 함수는 실행하지 않는다.
- 의존성: contracts → application → 기존 Catalog 파일 reader/Orchestrator store/DB adapter.
  NAS commit은 기존 Orchestrator만 수행한다. runtime 파일/권한/수치 bundle은 변경하지 않는다.
- 작은 대안: 원 pending 명령 재전송은 이미 종료된 물리 root를 재사용할 수 없고,
  allocated 복구는 BOUND/owned encodings를 요구하므로 그대로 쓸 수 없다. 이 경로를 분리하면
  기존 의미를 넓히거나 새 protocol family/일반 복구 framework를 만들 필요가 없다.

검증: disposable PostgreSQL에서 exact replay, 두 동시 호출, root/nonowner 거부,
성공 START 불변, BOUND/association/publication/claimed ADVANCE 거부, 마지막 물리 fence의
전역 rollback을 확인한다. 운영 배포/실제 복구는 source 테스트와 별도로 기록한다.
