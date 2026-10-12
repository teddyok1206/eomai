# GraphRAG·증분 임베딩 첫 구현 checkpoint

기록: 2026-10-12 UTC. 소스 기준: `165b0214a8c8812fe5e4d24e5a8b266ea345dbb6`.
기준 설계: [전체 goal](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).
**전체 goal은 진행 중이다.** 아래 source/임시 DB PASS를 운영 인덱스 완료로 확대하지 않는다.

## 구현·실행 완료 범위

- native Workflow definition/request와 encoding input/result를 JSON Schema2020-12 및 frozen
  Pydantic으로 정의했다. 과거 agent Workflow/역할 계약 bytes·의미는 유지한다.
- encoding key는 storage partition + numerical space + 실제 text hash다. source/profile/Graph
  association은 별도로 검증하며, Graph-only 변화와 동일 text는 벡터를 재사용하는 pure delta
  계획을 만든다. 이 계획만으로 background 권한이나 Job admission이 생기지 않는다.
- float32-LE row-major bytes와 integer-only JSON manifest를 분리한다. raw SHA/shape/finite/L2
  norm을 검증하며 저장된 bytes를 재정규화해서 손상을 숨기지 않는다.
- injected backend의 모델/runtime 일치·ordered result closure와 local output을 검증하고,
  기존 `ControlFileSetPublisher`를 통해 `result.json`, `shard.json`, `vectors.f32`를 한 번 게시한다.
  logical encoder Job과 publisher Job/Artifact/Artifact revision/hash는 구분한다.
- formatter/linter PASS, strict mypy 관련 source15개 PASS, focused source 회귀 **598 PASS**.
  숫자는 한 번의 통합 suite 결과이며 개별·과거 suite와 합산하지 않는다.

## 실제 disposable PostgreSQL 증거

official lifecycle의 marker/owner/schema 검증을 통과한 임시 DB만 사용했다.
source migration `20261010_0051`의 upgrade → downgrade1 → upgrade와 head 확인 PASS.
공식 runner의 신규 `embedding-tests` action에서 합성 입력으로 **2 PASS (6.22s)**:

- 실제 owner publication, 세 member/outer manifest·pointer·SHA·binary read 검증;
- 동일 key replay가 기존 inode/mtime/bytes를 유지하고 다른 bytes는 conflict로 거부;
- 서로 다른 spawn 프로세스/engine의 동시 publication이 한 Job/Artifact/revision으로 수렴;
- PostgreSQL approved-row UPDATE/DELETE trigger가 실제로 거부;
- Job/Artifact/revision/event DB row에 원문 text·raw vector bytes/float arrays가 없음.

앞선 동일 두 케이스의 thread 기반 실행도2 PASS였으며 위 실행은 독립 process 검증으로
보강한 결과다. 수치를 합산하지 않는다. pytest 임시 local artifact paths만 사용했고 운영
DB·NAS·원 기출·모델에는 쓰지 않았다. 모델/GPU 실행0회. 검증 후 guarded cleanup으로
정확한 임시 DB/owner role/상태 파일을 제거했다. 삭제된 것은 재생성 가능한 테스트 자료이며
운영·historical evidence를 삭제한 것이 아니다.

## 아직 완료·활성화하지 않은 범위

| 경계 | 상태 |
| --- | --- |
| vector/binding/index 계약·pure encoding/delta·owner Artifact path | SOURCE_PASS |
| 위 owner publication/replay/concurrency | DISPOSABLE_DB_PASS |
| Catalog 영속 encoding/binding/index registry·CAS·missing-binding query | 구현 중, 아직 미배포 |
| exact-key reservation·native Runner admission/executor·자동 reconcile | 미연결 |
| scoped indexing service identity/권한·현재 source 재인가 | 설계 필요 경계 명시, 미활성 |
| CPU/CUDA bundle·보호 runtime·공유 physical GPU lease | 설계, 아직 실제 설치/실험 전 |
| GPU 성능·수치/검색 일관성·기본값 활성화·rollback | NOT_EVALUATED / NOT_ACTIVE |
| 최초 영속 seed·실제 source delta·소비자 연결 | 미실행 |

계약상 index1.0은 view별1024 bindings 상한이다. 미래 corpus를520으로 고정하거나
truncated 결과를 전체 coverage로 표시하지 않는다. 큰 corpus/paging과 empty snapshot은
명시적 successor가 필요하다. 과거 operator ID나 permission hash를 상시 background 권한으로
사용하지 않는다. source/model/policy latest를 조용히 대체하지 않는다.

GPU가 정확성·성능·격리·image/trainer resource gate에서 우수하면 기본 CUDA 활성화까지가
이번 goal이다. CPU와 GPU numerical space는 분리하고 기존 CPU 환경·payload·이력·rollback은
보존한다. 실제 benchmark/activation 증거 없이 GPU가 더 빠르거나 기본값이 됐다고 보고하지 않는다.

다음: schema-first registry/registration → supported native work/source admission → 실제
seed/delta/replay → 공통 후보 소비자 연결·GPU 비교/선택 → compatible release/live 검증.
교과서 chunk/PDF matching/ANN/대화 삭제 부록은 별도 후속 범위다.

## 후속 source checkpoint — 2026-10-12 17:20 UTC

등록 command/result와 exact receipt closure, pointer-only Catalog 관계4개, source migration
`20261012_0052`, payload를 복제하지 않는 runtime-bundle/numerical descriptor 계약을 추가했다.
이는 registration application/native Runner/현재 source authority/CUDA backend를 활성화하지 않는다.
이 후속 source 전체 gate는 **720 PASS (18.15s)**, 새 파일8개 strict mypy PASS,
Ruff format/lint 및 diff check PASS다. 기존598 PASS와 합산하지 않는다.

새 별도 marker-guarded DB에서0052 up/down/up 및 combined Artifact/registry **7 PASS (7.10s)**.
registry5개는 encoding/source binding/index head/revision의 happy relation, unique·composite FK,
append-only guards·fenced head CAS와 nonempty downgrade 거부를 실제 PostgreSQL에서 검증했다.
DRAFT Item/REQUESTED analysis를 사용하는 합성 FK fixture는 DB 관계 존재가 승인/eligibility를
보장하지 않는 것을 명시한다. source/member authorization과 registry use case의 동시 생성·
query-plan/limited-role gate를 완료했다고 보고하지 않는다. 해당 임시 DB와 상태도 guarded
cleanup으로 제거했다. 운영 DB migration은 실행하지 않았다.

첫 실행은3 PASS/4 FAIL: protocol fixture가 Job보다 먼저 flush되지 않은 FK 오류였다.
test fixture의 저장 순서만 수정한 뒤 위7 PASS를 얻었다. 기존 immutable history를 고치거나
production state machine을 수정하지 않았다. 통합 source 첫 실행의719 PASS/1 FAIL도
새 additive schema2개가 frozen predecessor inventory에 포함된 test 분류 문제였다.
기존295/296 resource count/hash/bytes 기대값은 그대로 보존하고 새 successor만 분리했다.

GPU 준비: [공식 metadata·고정 download lock](../architecture/INCREMENTAL_EMBEDDING_CUDA_PACKAGE_LOCK.md)의
25개 exact wheel을 별도 private local wheelhouse에 `pip download --no-index --no-deps
--only-binary=:all: --require-hashes`로 준비했다. advertised byte budget은3,848,835,734이고
다운로드 exit0로 요구한 raw wheel hashes가 확인됐다. CPU 환경·모델 payload는 변경하지 않았다.
이것은 full model/protocol runtime 설치·RECORD 검증·CUDA import/추론/benchmark/lease/default
activation의 증거가 아니다. 독립 archive/FD 검사와 별도 보호 staging·offline 설치가 다음 gate다.

기존 operator deployment callback은0051에 명시 고정되어 있다.0052 운영 배포 전에는
historical0051 의미를 보존하는 compatible successor/release gate가 필요하며, 현재 후보가
기존 배포 callback으로 자동 설치된다고 주장하지 않는다. consumer·service authority·paging
미구현 상태와 전체 goal 진행 상태는 위 표와 동일하다.
