# 계산 완료 후 릴리스가 교체된 INDEX 저장 복구

## 범위와 설계

2026-11-08 확인: 과거 CPU workflow 한 건은 4개 encoding의 검증·Artifact commit까지
성공했으나 INDEX_PREPARED 이후 중단됐다. 이전 서비스 revision에 고정된 요청이므로
새 INDEX 서비스에 그대로 claim시키거나 성공 상태만 기록해서는 안 된다.

복구는 **root + 실제 PostgreSQL schema owner의 명시적 유지보수 작업**이다. 일반
service IAM이나 사용자 권한을 넓히지 않는다. 현행 서비스와 현재 RELEASED CPU
source policy가 이전 요청과 같은 자료 범위·모델·recipe·resource를 여전히 허용하는지
확인하고, 정확히 지정된 과거 요청의 이미 준비된 publication만 이어간다.
이 유지보수 권한을 새 source discovery, submit, allocation, model execution에 쓸 수
없어야 한다. 기존 source/registry 검증 및 Orchestrator Artifact publisher를 재사용한다.

- 정본: 기존 Workflow request/Graph/plan/policy, 성공한 encoding receipts와 Artifact.
- identity: 기존 Workflow/step/native launch/index producer/receipt producer는 유지한다.
  실행한 유지보수 코드와 현재 허용한 서비스 revision은 별도 audit로 남긴다.
- pointers: 원래 request hash, native intent hash, INDEX_PREPARED registration command,
  current service reference와 current CPU policy hash를 고정한다. latest 치환은 없다.
- 접근: 정확한 ID 조회와 최대 4개 encoding membership; 기존 PK/index와 작은 tuple/set.
  전체 자료 검증은 기존 Catalog resolver 책임이며 새 scan/index/cache를 만들지 않는다.
- 동시성: 원래 Workflow/command lease 및 shared service-head lock을 유지한다.
  동일 요청 replay는 기존 prepared/registered/completed checkpoint를 이어간다.
  GPU namespace·현재 GPU 요청·QUERY·service PID는 변경하지 않는다.
- 실패: 다른 source/identity, 미완료 encoding, failed history, stale registration head,
  hash 오류, 유효한 다른 command claim이면 명시적으로 중단한다. 계산 재실행은 없다.
- 단순 대안: 구 서비스를 재활성화하면 현 GPU를 방해하고 알려진 timeout을 다시
  실행한다. DB 상태만 바꾸면 실제 index/receipt가 없으므로 채택하지 않는다.

## 검증과 운영 판정

구현은 기존 source gate의 명시적 유지보수 분기와 publication-only executor다.
일반 INDEX/QUERY API에는 이 권한을 노출하지 않는다. 151개 focused unit 및 실제
disposable PostgreSQL의 중단 후 publication·원래 command 재claim·terminal replay·
동시 접근 거부·실패 이력 거부 검사 4개가 통과했다. Ruff/mypy도 통과했다.
검사 중 fixture의 terminal replay 호출과 late command fence를 보정했으며, 이때의
실패는 운영 실행이 아니다. 운영 DB에서 pytest를 실행하지 않았다.

별도 immutable installed wheel에서 실행한다. 운영 성공은 실제 원래 index 등록,
Workflow COMPLETED, 같은 요청 replay, 숫자 worker 시작 횟수 증가 0 및 GPU 계속
진행을 확인한 뒤에만 기록한다.
