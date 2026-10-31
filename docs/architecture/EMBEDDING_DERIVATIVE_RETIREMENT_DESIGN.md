# 구형 임베딩 파생 데이터의 안전한 지원 종료

2026-10-31 UTC. 공통 임베딩 목표 U05의 설계/진행 기록이며 삭제 승인이 아니다.
상위 범위: `UNIFIED_ITEM_EMBEDDING_GPU_MIGRATION_GOAL_2026-10-31.md`.

## 책임과 정본

Catalog는 encoding/binding/index의 소유 관계와 수명 검증을 담당한다. Orchestrator는
계산 Job/Artifact/worker 결과 및 NAS 저장 경계를 담당한다. 운영 owner의 명시적
유지보수만 삭제를 수행할 수 있다. worker·모델·일반 API 요청은 삭제 권한을 갖지 않는다.

기출 520개 Item revisions/manifest hashes, accepted 분석·풀이보고서, 교과서, 창작/AI 정본,
Graph와 무관한 이력은 보호한다. 원래 target-set hash를 그대로 사용하며 현재 Graph에
추가된 창작을 520 분모나 구형 기출 삭제 대상에 섞지 않는다.

## 식별과 포인터

- 정리 범위는 logical Item ID + exact Item revision + manifest SHA의 정렬된 동결 집합이다.
- encoding hash, binding hash, index ID/revision, Artifact ID/revision은 서로 다른 개념이다.
- shard의 소유 범위는 `(artifact_id, artifact_revision_id)`다. 경로 또는 logical Artifact
  ID만으로 묶지 않는다. 내부 소유권 계산은 이 작은 불변 key만 비교하며 bytes를 읽지 않는다.
- 실제 파일 해석/삭제 전에는 원래 owner resolver가 schema/media/hash/권한/수명과 실제
  디렉터리/파일 identity를 검증해야 한다. 소유권 계산 결과는 이 검증이나 삭제 권한이 아니다.

## 접근 패턴·구조·규모

주 접근은 동결 revision membership, encoding→bindings 및 shard→encodings의 key lookup,
중복 검출과 의존 관계의 보호 집합 계산이다. set/map을 사용하고 결과는 정렬된 tuple이다.
등록된 encoding/binding 각 행을 한 번 읽고, registry 소유권 분류는 O(E+B), 결정적인 출력
정렬까지 O(E log E+B log B), 메모리는 O(E+B)다. target 상한은 기존 public scope 16,384를
넘기지 않는다. 읽기 adapter는 기존 indexed revision/encoding/shard 조회를 재사용한다.

같은 encoding을 다른 문항이 참조할 수 있고, 같은 shard에는 서로 다른 encoding이 들어갈
수 있다. 따라서 target binding, target만 사용하는 encoding, target만 사용하는 shard를
각각 계산한다. binding 수나 source_class 한 개로 shard 전체 삭제를 추정하지 않는다.
binding이 없어진 미귀속 row도 공유 shard의 실제 잔여 encoding이므로 보호한다.

## 최소 구현 순서

1. 읽기 전용 registry 소유권 분류기를 구현·검증한다. 현재 core 구현 범위는 여기까지다.
   이는 새 wire message나 worker 동작이 아닌 내부 frozen value/순수 함수다. 새 schema,
   DB migration, queue, runtime feature flag는 만들지 않는다.
2. 실제 동결 집합에 대해 metadata inventory를 얻는다. legacy partition과 accepted
   binding만 후보로 잡고, public partition/new projection/비대상 source는 보호한다.
   mixed index도 이 원래 binding을 재사용하므로 index 이름과 binding 의미를 혼동하지 않는다.
3. 기존 index의 canonical manifest membership 및 previous-revision 관계를 owner resolver로
   검사한다. 최초 binding manifest는 모든 후속 index의 membership 목록을 대체하지 않는다.
4. 실제 FK와 구조화된 JSON carrier, 설치된 INDEX/QUERY/출제·변형/Chat 소비자를 조사한다.
   임의 문자열 등장만으로 canonical 참조나 삭제 대상이라고 판단하지 않는다. 알려지지 않은
   carrier는 명시적으로 미분류로 남기며 자동 삭제하지 않는다.
5. 새 GPU 520 coverage/대상별 해시·권한·실제 검색/read/replay를 확인한 뒤에만 writer와
   소비자의 지원 종료를 선택한다. 활성 기능을 없애거나 과거 request를 새 recipe로 위장해
   삭제 조건을 충족시키지 않는다. 필요한 실제 소비자 successor만 별도 schema-first로 정의한다.
6. 실제 lifecycle/삭제 command·receipt는 inventory 결과에 맞춰 최소 범위로 정의한다.
   기존 canonical Artifact와 owner transaction 경계를 재사용하는 방법을 먼저 검토한다.
   새 영속 구조가 필요하면 그 필요성을 먼저 증명하고 disposable DB에서 검증한다.
   이 문서로 아직 결정하지 않은 tombstone table/framework를 선행 구현하지 않는다.

## 트랜잭션·동시성·실패

inventory는 쓰기를 하지 않는다. 계획을 실제 삭제에 사용할 때는 대상 집합/hash와 현재
소유 관계를 transaction 안에서 다시 검사하고, 활성 lease/claim/Job와 원래 물리 handle을
대조한다. 오래된 inventory 파일이나 PID0 한 항목을 삭제 권한으로 사용하지 않는다.

Catalog는 자기 테이블만 변경하고, Orchestrator는 자기 Artifact 경계만 변경한다.
서로의 private 모듈/테이블을 우회 변경하지 않는다. 모호한 timeout 뒤에는 실제 적용 상태를
읽고 같은 identity로 재확인한다. failed 이력을 성공으로 바꾸지 않는다.

완료 기록에는 exact 삭제/보존 ID·hash·파일 byte 범위와 사유, 실제 적용 순서, 복구 가능
여부가 필요하다. 공유/비대상 shard는 파일 전체를 지우지 않는다. 보호 정본과 무관한 이력을
추가 삭제하는 방식으로 공유 참조를 없애지 않는다. 구형 벡터 삭제는 아직 실행하지 않는다.

## 단순 대안과 제외

`partition` 전체 삭제, 520×3 같은 추산 수량 삭제, broad prelaunch AI reset 재호출은
비대상 canary/공유 shard/다른 소비자를 손상시킬 수 있어 사용하지 않는다. 반대로 소유권을
판정하지 않고 전부 보존하는 것도 요청된 U05 완료를 대체하지 않는다. 먼저 실제로 안전한
범위를 계산하고 남는 참조·제외 원인을 증거로 남긴다.

검증은 중복·dangling encoding·서로 다른 Artifact revision·공유 encoding/shard·미귀속 row·
public partition 보호·결정적 출력·단일 source iteration과 대규모 합성 입력을 포함한다.
향후 실제 삭제/replay/중단/동시성은 disposable PostgreSQL에서만 검사한다.
