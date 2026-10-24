# GPU 우선 임베딩과 유한 묶음 실행

2026-10-24 UTC. 사용자가 계획과 구현 goal을 승인했다. 이 문서는 새 운영 정책의
설계이며, GPU 우선이 이미 설치·활성화되었다는 증거가 아니다.

## 목적과 현재 경계

- 기본 실행 장치는 GPU, GPU 자원 할당이 불가능할 때만 CPU를 사용한다.
- 다문항 검색과 대량 증분 임베딩에서 한정된 묶음 동안 모델을 재사용한다.
- 기존 Catalog source resolution, 실제 사용자 권한, Graph/정책/분석 revision,
  Orchestrator queue·claim·encoding reservation·Artifact commit 경계를 재사용한다.
- API·Codex worker에 GPU 할당, DB/NAS 직접 접근 또는 임의 실행 권한을 추가하지 않는다.
- 새 vector engine, 작업 큐, 상시 모델 daemon, 외부 LLM API는 도입하지 않는다.

[완료한 비교](../operations/EMBEDDING_GPU_MEASURED_2026-10-24.md)의 원 판정은 KEEP_CPU다.
warm 문서 배치는 GPU가 약3.97배 빨랐지만 단일 질의 전체 시간은 비슷했다. 새 정책은
유한 묶음 처리량과 GPU 가용성을 위한 별도 결정이며, 과거 기준·결과를 바꾸지 않는다.
독립 SANDBOX·IMAGE_TRAINER_REGRESSION의 기존 NOT_RUN도 PASS로 바꾸지 않는다.

현재 실행 정책1.0/1.1은 gpu_busy=WAIT, 선택1.0은 단일 장치다. 설치된 INDEX와 QUERY
서비스는 CPU 전용이다. CUDA INDEX의 보호된 root controller/leaf/READY/ACK/retirement는
재사용 가능한 소스 경계이지 생산 서비스의 자동 GPU 선택이 아니다.

## 책임·정본·identity

1. 정본은 승인된 원자료·분석·Item revision과 기존 등록된 Artifact/인덱스 revision이다.
2. CPU/CUDA는 runtime/device를 포함하는 서로 다른 EmbeddingSpace다. 수치 비교 PASS는
   identity 동등성이 아니다. CPU 결과를 CUDA space로 표시하거나 한 인덱스에 섞지 않는다.
3. 처음에는 장치별 독립 인덱스와 정확한 QUERY/DOCUMENT 쌍을 사용한다. 각 장치가 같은
   논리적 대상 집합·원자료 revision·view recipe를 커버하는지는 별도로 확인한다.
4. view마다 인덱스 쌍은 두 immutable pointer와 target-set hash를 고정한다. CPU fallback도 대상
   집합이 같은 정확한 CPU 인덱스로 검색한다. 누락·stale·권한/해시 불일치는 오류다.
   증분 처리가 한쪽만 진전시키면 기존 reconciliation으로 보조 namespace도 따라잡는다.
   그동안 다른 장치의 더 작은 corpus를 정상 fallback처럼 검색하지 않는다.
5. 새 cross-device 수치 호환 계층으로 기존 CPU 인덱스에 GPU 질의를 바로 연결하는 대안은
   이번 범위에서 채택하지 않는다. 더 작은 검증 경계를 위해 기존 exact-space 규칙을 유지한다.
6. root/Orchestrator가 장치 선택을 확정한 뒤 그 장치의 실제 profile/space로 입력과 encoding
   예약을 생성한다. 선택·실행·결과의 identity 및 raw/self hash를 각각 기록한다.

## GPU 할당과 CPU 대체 실행

후속 schema-first 정책은 CUDA 우선, CPU 보조, 고정 묶음 상한을 명시한다. 기존 정책
1.0/1.1과 backend selection1.0의 bytes·의미·실행 핀은 수정하지 않는다.

- 할당은 기존 공유 physical GPU lease를 사용한다. GPU lock을 별도로 만들지 않는다.
- 기존 leaf가 직접 lease를 획득하므로 root가 먼저 잡은 뒤 그대로 leaf를 시작하면 자기
  lock을 기다리게 된다. 후속 allocation은 leaf의 일회 획득·READY/FDSTORE/ACK 수명을
  재사용하고, BUSY는 CUDA 초기화 전 typed 결과와 root의 미시작/정리 관찰로 증명한다.
- BUSY 또는 검증된 가용 용량 부족은 CUDA 실행 **이전**에만 CPU 선택 근거가 된다.
- lock을 잠깐 잡았다 놓은 뒤 실행하는 사전검사는 금지한다. 실제 할당의 수명을 dispatch와
  연결하거나, root가 CUDA 미시작을 증명한 공식 결과를 받은 뒤 CPU를 선택한다.
- 모델/설치/구성/해시/권한 오류, INVALID lease, 시작·ACK·종료 불명은 fallback하지 않는다.
- CUDA가 실행되었거나 시작 여부가 불명확하면 원 실행을 reconcile한다. CPU로 조용히
  중복 계산하지 않는다. OOM은 단순 BUSY가 아니며 원 실패와 정리를 보존한다.
- 확정한 선택은 원 요청의 replay에서 고정한다. 나중에 GPU가 비어도 성공한 CPU 작업을
  GPU로 다시 실행하지 않는다. FAILED 이력을 성공으로 바꾸지 않는다.
- 이미지 작업·학습이 이미 GPU를 점유한 경우 기다리며 새 GPU 점유를 만들지 않고 CPU를
  선택한다. 실행 중 묶음은 안전한 경계까지 완료/정리하며 강제 GPU 선점은 도입하지 않는다.

## 다문항과 대량 자료

QUERY 묶음은 새 바깥 envelope로 독립된 자식 입력1.1/결과1.0을 연결한다. 기존의
문항당 최대3 view 규칙을 여러 문항 규칙으로 재해석하지 않는다. 각 자식은 요청·context·
원자료·권한·hash를 독립 검증하고, 완료 결과는 원 순서와 identity로 반환한다.

DOCUMENT는 기존 IncrementalEmbeddingInput1.0(최대1024행,64MiB)과 microbatch1–16,
증분 plan·encoding reservation·unique constraint를 재사용한다. 이전에 완료된 encoding은
정확한 runtime/space 키로 재사용하고 텍스트가 같다는 이유로 다른 권한 범위와 합치지 않는다.

같은 유한 실행에는 동일 actor/권한 partition, 모델/runtime bundle, device, purpose,
profile·recipe·정책 핀만 포함한다. 임의 사용자나 private chat과 일반 문항을 함께 묶지 않는다.
묶음 입력의 전체 byte/행/시간/출력 상한도 적용한다. 모델 scope는 묶음 안에서 한 번 열고
finally에서 정리한다. 무기한 입력을 추가하거나 전역 모델 cache로 권한을 대신하지 않는다.
문항 간 microbatch 결합은 padding/수치 recipe에 영향을 주므로 첫 단계에서는 모델만 재사용하고
자식별 기존 encode 함수를 유지한다. 추후 실제 수치·순위 검증 후에만 cross-child 결합을 검토한다.

## 자료구조·복잡도·동시성

- 작업은 기존 indexed queue에서 claim한다. 새 persistent queue/registry는 없다.
- 유한 자식 순서는 tuple, identity 중복은 set, encoding/result lookup은 dict를 사용한다.
- 계획·중복 검사는 O(n), metadata는 O(n). 모델 메모리는 한 scope, 벡터는 기존 local
  output 경계에 한 번 materialize하고 hash/manifest로 commit한다. DB에는 binary를 넣지 않는다.
- device/profile/namespace key로 묶고, DB encoding unique key와 원 owner claim/lease를 유지한다.
- 실행 결정은 원 request/launch와 함께 원자적으로 고정되어야 한다. 실행 완료를 모르는 상태의
  timeout에는 새 identity를 만들지 않는다. 자식 결과는 기존 commit/idempotency 경계를 따른다.
- 자료 권한은 model load 전과 실행/commit/read 경계에서 재인가한다. batch 권한은 자식 권한을
  대신하지 않는다. staging은 정본의 복제 저장소가 아니라 명시적 임시 입력 경계다.

## 의존 방향과 소유권

- workflow/contracts: 후속 JSON Schema2020-12, frozen Pydantic 값, 순수 선택 규칙.
- Catalog application: 입력/결과 검증, 유한 모델 scope와 기존 encode adapter 재사용.
- WorkflowRunner: 기존 queue·claim·namespace·자식 완료/replay 연결.
- Orchestrator/root adapter: 실제 GPU 할당, 보호된 실행·READY/ACK·자원 종료 및 Artifact commit.
- API/Web: 준비·진행·결과 표시. fallback provenance는 실제 선택 결과에서 읽는다.

## 구현 순서와 gate

1. **P1 계약·순수 규칙:** 새 GPU 우선/자원 부족 fallback 정책, 결정·묶음 계약과 회귀 테스트.
   유한 Catalog 실행은 기존 encode를 모델 scope 하나에서 사용한다. 이 단계는 운영 활성화가 아니다.
2. **P2 실행 연결:** 원 lease를 보존하는 실제 pre-dispatch 할당, CUDA INDEX/QUERY launcher 및
   자식별 권한/완료/재개를 기존 owner에 연결한다. 기존 CPU 전용 구성은 그대로 동작해야 한다.
3. **P3 인덱스·운영:** 공식 source-resolution으로 장치별 인덱스 쌍과 같은 target 집합을 준비한다.
   실제 bulk QUERY/DOCUMENT canary, CPU fallback, 이미지 점유/종료/비정상 종료 및 namespace
   검증 후 호환 릴리스를 설치한다. source PASS와 live PASS는 분리한다.
4. **P4 기본값:** GPU 우선 read-back, forced-resource-contention CPU 경로, replay·권한·다운로드
   또는 결과 조회를 확인한다. rollback은 이전 CPU policy/namespace/release set 선택이며 기존
   GPU Artifact/실패/CPU 인덱스를 삭제하지 않는다.

테스트는 정책/잘못된 fallback/space 혼합/중복/범위/단일 모델 구성/예외 정리/순서/자식
결과 closure를 포함한다. DB 동시성은 disposable PostgreSQL에서만 실행한다. 실제 실험은
bounded opt-in으로 실행하며 숫자적 동등성과 순위, 처리량·지연·RSS/VRAM·GPU 반환·그림
생성과 학습의 공존을 별도로 기록한다. 사람의 교육 품질 평가는 이 실행 장치 변경의 gate가 아니다.

첫 canary는 적은 고정 자식으로 시작한다. CPU/GPU1회 적재 비용을 각 검색마다 반복하는
기존 경로와 유한 모델 재사용을 구분해 측정한다. 고정값으로 4배 성능을 약속하지 않는다.

## 시작 상태

GOAL=ACTIVE, REPOSITORY_BASE=ed927b99, GPU_PREFERRED_SOURCE=NOT_IMPLEMENTED,
GPU_PREFERRED_INSTALLED=NO, GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU.

이후 상태는 실제 구현·검증·설치 증거로 갱신한다. 기존 로그인 모델 자동 검증 canary와
이번 GPU goal은 서로 다른 acceptance이며 어느 쪽도 다른 쪽의 PASS를 대신하지 않는다.

## P1 진행 체크포인트 — 2026-10-24 14:29 UTC

- 정책·할당 관찰·결정의 후속 schema와 순수 route/replay, 유한 묶음 schema/Catalog 실행,
  장치별 인덱스 쌍과 선택 closure의 후보 소스를 작성했다. 아직 미커밋·미설치다.
- 순수 routing 신규54+기존207=261 PASS, batch 집중56 PASS와 기존 encode/contracts를
  포함한 앞선193 PASS, 루트의 별도 관련 묶음414 PASS를 확인했다. 서로 겹치는 묶음이며
  후속 raw-value/Artifact identity 수정까지 반영한 최종 통합 결과로 합산하지 않는다.
- 루트 index-pair의 mixed fixture import에는 API 등 전체 source 경로가 필요했다. 마지막
  후속 수정의 집중 재실행, 배치 route closure 자체 테스트, format/type 및 전체 통합이 남았다.
- independent review에서 발견한 raw extra 필드 은폐, scalar coercion, 같은 Artifact ID/
  revision/member에 다른 hash를 붙이는 충돌을 후보 소스에서 차단했다. 보조 인덱스가 실제
  현재 target 집합을 커버하는지는 P2의 공식 owner에서 별도 확인해야 한다.
- 사용자가 별도 요청한 채팅 부가 알림 수정은 `1a4e3c67`만 독립 배포했고 새 메시지 실제
  응답/COMPLETED PASS다. [검증 기록](../operations/GENERAL_CHAT_MODERATION_METADATA_FIX_2026-10-24.md).
  GPU 소스는 명시적15경로의 Git stash `735012d92ff33138deb7c9ca686b2a70b2fc89cb`로
  보존해 release archive/wheel에서 제외했다가, 배포 완료 후 원 경로에 복원했다. stash도
  복구 근거로 보존했다. 이 동안 실제 GPU 모델 호출은 없었다.
- 현재 main/origin은 docs-only `d3a63d24`; 실제 public platform/API는 `1a4e3c67`,
  Web은 기존 f15e66b8, QUERY 수치 SDK는2eef9b20, INDEX invocation은053c5ab4 그대로다.

다음 작업은 P1 후보의 최종 회귀·검토와 별도 커밋이다. 이후 P2에서 실제 할당/READY/ACK,
유한 세션 worker handoff·자식별 완료/replay를 기존 실행기에 연결한다. CPU 기본값을
후속 정책으로 바꾸거나 실제 GPU canary를 했다고 보고하지 않는다. GOAL=ACTIVE다.

## P1 소스 통합 검증 완료 — 2026-10-24 UTC

- 새 routing/batch/index-pair/route closure와 기존 backend selection·QUERY/DOCUMENT encode·
  runtime bundle·stdio·schema packaging·dependency boundary의 실제 통합503 PASS다.
  이는 실제 CUDA 모델·DB 동시성·서비스 설치 또는 GPU 기본값 활성화 PASS가 아니다.
- root scalar fixture가 모델의 실제 token 상한과 다른8192를 사용하던 것을 실제 상한의
  string/float로 수정했다. canonical serializer의 float 거부도 일관된 ValueError로 전달한다.
  권한·hash·수치 recipe나 released predecessor의 규칙을 느슨하게 바꾸지 않았다.
- 공통6개 소스 모듈 strict mypy, 변경10개 Python의 scoped Ruff/format을 확인했다.
- 추가 route 검토에서 단일 view pin으로 여러 QUERY view를 처리할 수 있는 빈틈을 발견했다.
  CONTENT/CONCRETE/METADATA별 정확한 인덱스 쌍을 요구하고, view 누락/중복/추가·잘못된
  namespace·선택/자원/recipe mismatch를 거부한다. 순서는 기존 VIEWS 상수로 고정한다.
- 묶음은 원 route decision hash를 필수로 고정한다. 실제 source 재인가와 물리 lease,
  private 목적 분리, hard deadline·완료 journal·publication은 P2 owner의 책임이며,
  현재 순수 후보 값만으로 실행을 허용하지 않는다.

다음 P2는 먼저 묶음 결과/벡터 offset manifest와 보호 FD 인계 계약을 정의한다. 이어
기존 physical lease·root READY/ACK/retirement로 실제 할당을 연결한다. native 수명은
고정180초를 임의로 늘리지 않고 유한 묶음을 나눈다. PRIVATE_CHAT_QUERY도 목적·사용자
경계를 따로 유지하며 기존 private 입력/출력을 공개 문항 batch로 변환하지 않는다.

## P2-A 로컬 결과와 보호 FD 인계

책임은 기존 native stdio/encoding adapter의 확장이다. 새 `embedding-work-batch-result/1.0`
metadata는 원 batch request/route decision hash와 순서 있는 자식 결과(기존 QUERY1.0 또는
DOCUMENT1.0)를 담는다. 각 자식의 `vector_offset`은 하나의 `vectors.f32` 안에서 연속된
영역을 가리키며 길이·해시는 기존 자식 shard.binary가 정본이다. aggregate binary는 별도의
전체 hash/byte_count를 가진다. offset은 storage identity나 권한이 아닌 작은 불변 값이다.

이 parent result/aggregate binary는 **로컬 precommit materialization**이다. NAS에 aggregate와
같은 bytes의 자식 binary를 모두 정본으로 등록하지 않는다. 기존 owner가 자식의 canonical
shard/result를 한 번 commit하고, 원 group의 완료 이력은 자식 Artifact pointers와 원 local
hash들을 고정한 receipt로 연결해야 한다. 부모 임시 파일을 영속 pointer로 남기지 않는다.

부모 hash만 맞추고 자식 job/context/input/result를 바꾸거나, 영역의 overlap/gap/reorder,
다른 space/recipe/purpose를 섞는 것을 거부한다. 전체/자식 hash와 FLOAT32 shape·unit norm,
실제 input closure를 확인하고 나서만 기존 owner가 각 자식을 commit한다. DB binary 저장이나
새 registry/queue는 없다. 합성 테스트는 모델 실행이나 실제 GPU 소유권 증거가 아니다.

입력·결과·binary는 기존 root-created regular FD 세 개를 사용하고 alias·offset·소유자·mode·
epoch 검사를 재사용한다. 결과의 실제 metadata+binary 크기가 owner의 total output 한도를
초과하면 결과를 성공으로 쓰지 않는다. binary는 각 자식 조각을 한 번씩 연속 write/hash하여
추가 concatenate 복사를 피한다. 처리/해시 O(total bytes), metadata O(children), 메모리는
기존 유한 encoded 결과 외 전체 binary의 중복 사본을 만들지 않는다.

마지막 metadata write는 모든 자식 검증과 binary write/FSYNC 후다. 부분 write, input 변경,
권한 철회, deadline/cleanup 불명은 성공 결과가 아니다. 이미 시작한 계산에 CPU fallback을
적용하지 않는다. 기존 completion owner가 원 launch identity로 reconcile하며 새 key로
중복 계산하지 않는다. 하위 scalar·hash 규칙은 각 released parser를 그대로 사용한다.

owner-local binary reader는 원 batch/result closure와 전체/자식 hash·shape·unit norm을
검증하고 단일 immutable bytes buffer를 공유하는 read-only memoryview 범위를 반환한다.
이는 Python의 안전한 로컬 buffer view이며 protocol pointer나 DB 저장값이 아니다.

부모 요청의 일괄 출력만으로 자식별 영속 checkpoint가 생기지 않는다. P2-B에서 기존 owner의
commit/replay를 연결하고, Artifact commit까지 끝난 자식은 재실행하지 않아야 한다. 이 단계의
로컬 codec/stdio만으로 생산 연결이나 기본 장치 변경을 선언하지 않는다.

### P2-A 검증 체크포인트

새 결과/owner-local binary/보호 FD 인계와 P1·기존 직렬 경로·패키징·의존 경계를 포함해
527 PASS다. 변경3개 소스 strict mypy, 변경4개 Python의 scoped Ruff/format도 PASS다.
합성 CPU/CUDA 양쪽의 동일 원 자식 결과·연속 offset·전체/자식 hash·unit norm과 단일
모델 scope를 확인했다. overlap/gap/reorder, 위조 extra, immutable Artifact member 충돌,
descriptor alias, model 종료 후 input 변경, partial binary write와 총 metadata+binary
상한 초과를 거부하며 실패 출력은 보존한다. 실제 모델/GPU/DB/서비스 변경은0이다.

현재 INDEX PID130161/invocation053c5ab467ff4e29b4901cfabf037b4b 유지, GPU 관측2MiB/0%다.
이는 GPU 경로를 검증했다는 뜻이 아니라 이번 회차가 source/합성 단계임을 확인한 것이다.
P2-B 실제 할당·새 native 목적의 unit/READY/ACK/retirement·원 child commit/replay 연결,
P3 인덱스 준비/실제 안전·처리량 canary, P4 운영 기본값/CPU fallback/rollback은 남았다.

## P2-B 할당 수명 결정 — 실제 kernel 관찰

ROOT가 먼저 flock을 잡아 같은 open-file description을 SCM_RIGHTS로 전달하는 대안도
읽기 전용 kernel metadata로 실험했다. 수신 프로세스에서 LOCK_EX를 다시 적용해도 fdinfo의
lock-holder PID는 원 송신 프로세스였다(관찰 parent2645469/child2645470). 기존의 독립
resource observer는 실제 numeric worker PID가 같은 lock을 보유함을 확인한다. 전달 방식을
채택하려고 이 검증을 느슨하게 만들지 않는다. 별도 peer/allocator identity 계약을 추가하는
것보다 **기존 numeric leaf가 직접 한 번 획득하고 원 lease를 유지**하는 방식을 선택한다.
[Linux fdinfo의 descriptor별 lock 정보](https://docs.kernel.org/filesystems/proc.html#proc-pid-fdinfo-fd-information-about-opened-file).

새 할당 scope는 기존 standalone lease의 nonblocking claim을 한 번만 호출한다. acquire의
검증된 BUSY만 자원 부족 결과이며 INVALID·설치 부재·body/cleanup 오류는 대체 실행 근거가
아니다. 이 scope는 logical 요청·source/정책 권한·실행 grant·cgroup 종료를 증명하지 않는다.
원 open description을 FDSTORE에 유지하는 기존 READY/root ACK/retirement를 그대로 따른다.
close는 worker의 참조만 닫으며 PID1의 보유 잠금을 제거하거나 LOCK_UN 하지 않는다.

실제 native 연결은 두 단계다. 먼저 할당용 fixed metadata만 받은 worker가 lease를 획득하고
READY 또는 BUSY를 보고한다. root가 실제 unit/PID/FDSTORE와 원 요청을 검증한 뒤 장치를
확정하고, 같은 root-created input inode에 정확한 batch/decision을 고정한 grant를 제공한다.
worker는 root ACK 뒤에만 그 입력을 읽고 CUDA를 초기화한다. BUSY는 원 unit의 미실행/
빈 수치 출력/no-ACK/정상 종료를 root가 확인한 경우에만 CPU route가 된다. 다른 이미지
프로세스의 GPU 점유는 BUSY의 정상 원인이고, 그 프로세스를 중단하지 않는다.

이 후속 purpose의 input/grant/READY와 child 권한 확인은 새 폐쇄형 wire 계약으로 연결한다.
기존 INDEX의 WAIT 의미·이미 pin된 수치 실행·기존 CPU entrypoint는 바꾸지 않는다.

### 할당용 제어 계약

`embedding-gpu-allocation-control/1.0`은 root와 단일 native worker 사이의 bounded metadata
계약이다. REQUEST는 원 parent/child-set/route-policy/configuration/receipt·만료 시각을
고정한다. READY는 원 worker PID/birth/group/resource FD와 retention 요청을, BUSY는
acquire-time 자원 부재를 주장한다. 둘 모두 root의 실제 unit/커널 관찰을 대신하지 않는다.

root의 GRANT는 검증된 READY hash, 확정한 route decision과 같은 원 input inode에 고정한
batch raw/self hash·byte_count를 연결한다. worker는 GRANT 전 입력을 읽거나 모델을 열지
않는다. CHECK_CHILD/FENCE_ACK는 원 grant/batch/child와 monotonic sequence를 연결한다.
root는 기존 actual actor/source resolution 경계로 매번 재인가하고, worker에 DB/NAS나
사용자 credential을 제공하지 않는다. source 거부/timeout에는 ACK하지 않고 실행을 중단한다.
마지막 RESULT_READY는 파일 hash/크기만 주장하며 원 unit 성공이나 publish PASS가 아니다.
root가 실제 로컬 파일·원 종료·GPU 정리와 현재 source 권한을 검증한 뒤 기존 owner가 commit한다.
worker는 root의 실제 로컬 출력 확인 RESULT_ACK를 받을 때까지 제어 peer를 유지한다.
ACK 뒤 worker 종료와 독립 retirement를 확인하며, ACK 자체를 완료·GPU 반환으로 해석하지 않는다.

제어 프레임에는 문항 텍스트·벡터·비밀번호·도구 권한을 넣지 않는다. 프레임 크기32KiB와
최대256 child fence sequence, 원180초 native 수명을 제한한다. 외부 API/queue가 아닌 고정
local peer 채널이고, 계약 parse만으로 root 신원·작업 권한·실제 lease가 확인되지는 않는다.
worker-owned lease를 유지하는 실제 channel/unit/owner 연결과 root retirement는 후속 구현이다.

### P2-B 제어·물리 관찰 소스 검증

제어 채널 후보는 실제 AF_UNIX socketpair와 kernel SCM_CREDENTIALS를 사용해 검증했다.
기존 bounded framing을 재사용하며, SO_PASSCRED가 켜져 있지 않거나 원 peer/실제 sender,
원 unit fence, deadline이 달라지면 닫고 원 요청에 재연결하지 않는다. 32KiB 초과 header는
body를 기다리지 않고 거부한다. 상태 전이는 immutable lookup table, child lookup은 dict,
확인한 child 집합은 set, sequence는 단조 증가 값이다. 통신 복잡도는 fence 수에 선형이다.

유효한 채널에서도 ROOT/WORKER label은 권한이 아니다. root의 실제 source authorizer가
성공해야 child ACK를 보내며, 실제 파일/hash/source verifier가 성공해야 결과 ACK를 보낸다.
실패·비정상 callback 반환·중복 sequence·다른 child/attempt/result·구성 변경은 ACK하지 않는다.
동일 모델 scope의 자식2건을 왕복 실행하는 합성 검증에서 적재1회, cleanup1회와 적재 전/
자식 전후/cleanup 후의 총8회 독립 source fence를 확인했다. 실제 CUDA 추론은 아니다.

새 unit family는 `eom-embedding-native-gpu-batch@<allocation attempt hex>.service`다.
이는 **아직 설치하지 않은 후보 identity**다. 원 attempt와 같은 READY만 받아 기존 physical
observer로 worker의 flock·device FD·PID1 retained lock을 독립 확인하도록 확장했다.
old INDEX/probe/benchmark의 메시지나 unit으로 위장하지 않는다. retained/released 단계도
기존 same-inode 확인을 사용한다. release 확인은 이미 종료·정리한 unit에 대한 별도 root
증거가 전제이며, 실제 GPU holder를 강제로 중단하거나 LOCK_UN하는 기능이 아니다.

최종 관련 통합726 PASS, 뒤에 추가한 출력 verifier 거부/peer 철회3건을 포함한 채널·기존
shared lease 집중61 PASS다. 겹치는 테스트 수는 합산하지 않는다. 변경4개 production 모듈
strict mypy와 변경 Python scoped Ruff/format PASS다. schema mirror/packaging/dependency
검사도 통합에 포함했다. 이 증거는 root unit 설치·현재 사용자 권한의 source-resolution 연결,
DB 동시성·실제 GPU/이미지/학습 공존·운영 기본값 변경의 PASS를 뜻하지 않는다.

남은 실행 연결은 보호 input을 GRANT 뒤에 한 번 읽어 같은 FD epoch/hash로 bind하고,
원 숫자 adapter를 이 채널 fence에 연결하는 것이다. root controller는 unit/invocation/PID birth,
실제 retained lease와 source authority를 별도로 확인해야 한다. terminal ACK 뒤 process 종료가
정상적으로 일어나는 시점에는 살아 있는 PID를 재요구하는 대신 원 unit의 terminal identity를
검증해야 한다. control ACK만으로 Artifact commit이나 GPU 반환을 완료 처리하지 않는다.

CURRENT_DEFAULT=CPU, GPU_PREFERRED_INSTALLED=NO, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

### 보호 FD와 계산 연결의 구현 경계

기존 stdio adapter에서 입력을 한 번 파싱한 내부 capture(작은 typed request, 실제 raw
hash/count, 세 FD의 원 stat epoch)를 같은 호출 안에서 사용한다. raw bytes는 파싱 경계에서만
소유하고 내부 capture에 복사 보관하지 않는다. 기존 batch 호출과 GPU grant 호출은 같은
계산/검증/쓰기 함수를 사용한다. GPU 호출은 제어 채널의 GRANTED 상태 확인 **전에는**
입력 FD를 읽지 않으며, 읽은 실제 raw hash/count를 grant와 bind한 후에만 모델을 연다.

계산 결과는 이전처럼 binary fsync 뒤 metadata를 마지막으로 기록하고 FD/input/source를
재확인한다. typed result를 같은 호출의 채널로 알리고 원 root의 실제 파일 검증 ACK를
기다린다. ACK를 잃으면 로컬 출력이 있어도 성공을 반환하지 않는다. 재계산·CPU 대체·NAS
commit은 이 adapter가 수행하지 않는다. root owner가 원 identity로 reconcile해야 한다.
내부 capture는 영속 contract·별도 Artifact·worker 권한이 아니며 외부에서 전달받지 않는다.

native worker 조합은 별도 queue/launcher가 아니다. fixed CUDA identity와 독립 backend
pin/설치 receipt를 확인하고, 원 제어 요청 수신 → 일회 lease claim → FDSTORE retention
요청/READY → 원 root GRANT → 기존 CUDA backend와 보호 FD adapter → 결과 ACK →
model/device/lease 참조 정리 순서를 하나의 호출로 연결한다. BUSY일 때는 numerical input과
CUDA R/W·model scope를 열지 않는다. 기존 owner가 원 unit의 종료/무계산/빈 출력을 별도로
증명해야 CPU로 선택할 수 있다. private query는 공개 batch로 바꾸지 않고 명시 거부한다.
quiet stdio bootstrap, 실제 root peer/unit 관찰, 설치된 entrypoint와 owner source authority는
상위 composition의 별도 필수 경계다. 이 library 조합만으로 운영 실행 권한은 생기지 않는다.

### P2-C worker/보호 FD 연결 검증 체크포인트

- 기존 stdio·장치 선택·batch·제어·물리 관찰·schema packaging·dependency boundary를 함께
  실행한739 PASS다. 이후 identity 실패 시 채널 종료까지 추가한 worker/FD 집중11 PASS다.
  겹치는 결과는 합산하지 않는다. 변경3개 production 모듈 strict mypy와 Python scoped
  Ruff/format도 PASS다. 새로운 외부 의존성·DB migration은 없다.
- 실제 AF_UNIX와 임시 regular FD에서 원 READY/GRANT, 실제 input raw hash/count,
  자식별 source ACK, 모델 scope1회, binary→metadata 순서와 실제 출력 hash를 연결했다.
  원 root 결과 ACK 전에는 성공을 반환하지 않는다. 이 결과의 kernel socket/FD는 실제지만,
  UID·설치·GPU lease/device·수치 backend는 합성 port이며 CUDA canary 증거가 아니다.
- lease BUSY는 numerical input을 읽지 않고 모델/device R/W를 열지 않는다. pin mismatch,
  retention 불명, GRANT 손실, source 철회, 결과 ACK 손실은 CPU 대체 실행으로 바뀌지 않는다.
  결과 ACK가 유실되면 이미 완성한 로컬 파일을 보존하고 원 실행을 실패/불명으로 반환한다.
- 실제 실행 worker는 하나의 original lease를 retention/READY부터 결과 ACK와 device 정리까지
  유지한다. worker close는 PID1의 retained flock을 해제했다는 증거가 아니다. 독립 root unit
  종료·GPU client 확인·retirement/same-inode 반환 확인은 여전히 필수다.
- 운영 API·일반 대화·INDEX owner는 active/running이며 GPU 관측은2MiB/0%다. 이번 단계에서
  모델 추론, GPU 실행, 운영 DB 변경, prefix 설치, 서비스 재시작, 사용자 인증은 모두0이다.

다음 구현은 실제 fixed native bootstrap/unit과 root controller를 연결하는 것이다. root는
원 invocation/PID birth·sealed executable/configuration·FDSTORE를 관찰하고, 기존 actual-actor
source owner를 통해 각 child를 재인가해야 한다. 후보 library를 실행 권한으로 취급하거나,
기존 INDEX WAIT/ownership1.0과 현재 mixed ownership2.0을 조용히 같은 계약으로 읽지 않는다.
자식별 기존 commit/replay 연결, 같은 target 집합의 CPU/CUDA view 인덱스 준비, disposable
DB 동시성·실제 CUDA/이미지/학습 공존·성능 canary, 배포·GPU default/CPU fallback·rollback이
남아 있다. 실험·로그인 요청을 새로 만들지 않고 이 구현 경계부터 이어간다.

P1=SOURCE_VERIFIED, P2_CONTROL_AND_WORKER=SOURCE_VERIFIED,
P2_OWNER_UNIT_AND_COMMIT=PENDING, P3_LIVE_CANARY=PENDING, P4_ACTIVATION=PENDING.
CURRENT_DEFAULT=CPU, GPU_PREFERRED_INSTALLED=NO, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

## P2-D fixed bootstrap와 root 전용 활성화

원 numeric input은 GRANT 전에 비어 있는 root-created stdin inode다. 별도의 작은
`allocation.json`은 기존 제어 요청 schema/정본 hash를 가진 root-created metadata이며,
PID1 `OpenFile=...:gpu-batch-allocation:read-only`로 전달한다. 이는 원 input의 복사본이 아니다.
numeric worker는 두 activation FD를 LISTEN_FDNAMES로 구분한다. 순서를 추정하거나
socket을 직접 bind/reconnect하지 않는다. 원 argv/env는 fixed attempt, allocation raw SHA,
root PID, backend5개 pin, resource profile/상한만 담고 path·model·authority를 고르지 않는다.

같은 unit의 root-only socket0600과 PID1 nonblocking listener를 사용하며, `PassCredentials=yes`
는 첫 메시지가 queue에 쌓이기 전에 적용한다. worker는 원 root PID/UID/GID의 kernel peer와
메시지별 SCM_CREDENTIALS를 확인한다. root의 /proc가 worker에게 보인다고 가정하지 않으며,
root PID의 claimed birth를 읽었다고 보고하지 않는다. root controller가 원 service invocation,
worker PID/birth/cgroup·sealed code와 실제 FDSTORE를 독립 관찰하는 경계는 유지한다.

bootstrap은 stdout/stderr의 원 결과 FD를 보존하고 /dev/null로 진단을 분리한 다음에만
contract/backend를 import한다. metadata는 bounded canonical parser로 한 번 읽고 raw SHA,
stat epoch·root ownership·mode·독립 inode를 확인한다. numerical stdin은 실제 GRANT 뒤의
기존 adapter에서만 읽는다. native hard lifetime180초, 재시작 없음, 원 PID1 GPU retention과
DB/NAS·네트워크·credential 차단을 유지한다. 기존 INDEX WAIT unit/entry bytes는 바꾸지 않는다.

선택은 metadata FD와 제어 listener의 두 고정 descriptor를 쓰는 것이다. JSON 전체를 argv로
인코딩하거나 request를 numerical stdin과 섞는 대안은 late-bound input identity와 분리하기
어렵고 검증/복사 비용을 늘리므로 채택하지 않는다. metadata read는 O(32KiB), accept는 원
deadline까지 bounded하며 두 FD의 membership은 고정 map/set으로 확인한다. 새 queue/DB는 없다.
임시 root unit과 Artifact commit/재실행 결정은 이 bootstrap이 소유하지 않는다.

설치 host는 systemd255이며 실제 설치 전 동일 버전의 정적 verifier로 unit을 확인한다.
[systemd socket activation](https://www.freedesktop.org/software/systemd/man/systemd.socket.html),
[OpenFile 실행 descriptor](https://www.freedesktop.org/software/systemd/man/systemd.service.html#OpenFile=).

root staging은 기존 protected directory/no-clobber file primitive를 확장한다. 기존 nonempty
CPU/INDEX input의 규칙을 풀지 않고, 별도 late-bound 함수만 empty input을 생성한다. 동일
attempt의 root 디렉터리와 metadata/env/결과 파일은 exclusive create하며 기존 폴더를
지우거나 재생성하지 않는다. GRANT와 실제 batch/device/raw hash를 검증한 뒤 작은 원 grant
intent를 O_EXCL로 기록·fsync하고, **처음 만든 input inode**에 단 한 번 기록한다. intent가
이미 있으면 원 grant/현재 bytes를 조회해 정확히 같은 완성 입력만 read-only replay로 인정한다.
부분/다른 입력·진행 여부 불명은 새 write나 CPU fallback이 아니다. 기존 source owner의
원자적 route/encoding reservation을 이 local intent가 대신하지 않는다.

### P2-D 검증 체크포인트 — 2026-10-24 UTC

- fixed launch/env, 순서 독립 activation FD, canonical allocation metadata, root-only socket,
  numeric stdout 진단 분리, 기존 physical policy readback의 후보 소스를 연결했다.
  실제 host systemd255 `systemd-analyze verify --man=no`로 새 service/socket의 정적 검사 PASS다.
  verifier PASS는 새 unit이 설치·실행됐다는 뜻이 아니다.
- 기존 API/QUERY/INDEX 경로와 새 후보의 관련 통합1023 PASS, 최종 handoff fixture/profile
  보정 후 집중12 PASS, production6개 모듈 strict mypy와 scoped Ruff/format PASS다. 겹치는
  숫자는 합산하지 않는다. 기존 nonempty CPU/INDEX input 계약과 old INDEX entry/unit SHA는
  그대로다. 최종 전체 검증은 향후 실제 source-owner/runtime 연결까지 포함해 다시 수행한다.
- 실제 root 권한·전용 임시 `/run` 파일·실제 UID 전환·concurrent writers를 사용한 opt-in
  filesystem 검사6 PASS다. PID1 역할이나 실제 CUDA 연산을 합성해서 PASS한 것이 아니다.
  원 empty input을 미리 연 FD가 같은 inode의 완성 내용을 읽는 것, exact replay의 무쓰기,
  exclusive attempt, 부분 쓰기와 intent 보존, 동시 쓰기1회, 잘못된 grant 사전 거부,
  native UID의 경로 읽기 차단과 inherited FD 읽기를 확인했다.
- 기존 tmux EOM2의 Linux 인증을 재사용했다. source-controlled test 준비 후 noninteractive
  sudo로 root fixture만 실행했으며 사용자 재로그인·비밀번호 변경·실제 DB·NAS·모델·GPU·
  운영 unit 설치/재시작은0이다. 임시 fixture는 종료 시 정리했다. 실패한 테스트 기록은 지우지
  않았다. 최초 partial-IO 검사는 기존 adapter가 OSError를 CpuHandoffError로 감싸는 기대값을
  보정했고, 추가 resource closure 후에는 fixture의 profile을 실제 batch와 같게 보정했다.
  생산 검증 규칙을 느슨하게 바꿔 PASS시키지 않았다.
- 임시 실행 기록은 `/tmp/eom-gpu-batch-os-20261024*.log`, 최종 root6 PASS는
  `/tmp/eom-gpu-batch-os-20261024-r4.log`다. 준비 script는 Git에서 제외한
  `staging/gpu-batch-os-20261024/run.sh`이며 DB 통합 플래그를 명시적으로0으로 고정했다.

다음은 실제 root controller의 pre-compute 관찰/GRANT/원 unit terminal·retirement와 기존
actual-actor source owner의 child 재인가·commit/replay 연결이다. 새 worker가 source authority나
unit 성공을 스스로 증명하게 하지 않는다. 전체 목표의 장치별 현재 target 인덱스 준비,
disposable PostgreSQL concurrency, 실제 CUDA/이미지·trainer 공존·bulk 처리량, 설치·GPU default/
CPU fallback·rollback gate는 여전히 남아 있다. 기존 비교 결과 KEEP_CPU와 CPU 운영 경로는
보존하며 goal을 source-only 검증으로 축소하거나 완료 처리하지 않는다.

P2_D_BOOTSTRAP=SOURCE_VERIFIED, ROOT_FILE_DAC_AND_CONCURRENCY=PASS,
LIVE_GPU_BATCH_UNIT=NOT_RUN, CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

## P2-E 실제 root 관찰과 종료

root의 pre-compute 판정은 worker의 READY만으로 성립하지 않는다. 고정 service/socket과
entry의 installed bytes, backend/receipt/prefix/host closure, 원 allocation/env와 빈 numeric
inode, unit invocation/start stamp, 실제 PID/birth/UID/GID/cgroup/argv/cwd/단일 thread,
실제 worker/PID1 flock/device FD, GPU client 미시작을 별도로 관찰한다. 원 unit의 전후
read-back이 같아야 GRANT 가능한 machine 사실이 된다. source/actor 허가는 기존 owner의
별도 책임이며 이 관찰값이 권한을 대신하지 않는다.

bounded 검사는 GRANT와 terminal 경계에 모으고 frame마다 systemctl이나 prefix 전체 scan을
반복하지 않는다. transport peer fence는 원 PID/birth/cgroup과 kernel sender를 가볍게 확인한다.
전체 prefix와 host capture는 같은 실행에서 보유하고 GRANT/terminal에서 다시 확인한다.
관찰값은 작은 frozen metadata이며 model/문항 text/output binary의 복사나 새 registry가 아니다.

획득한 GPU의 terminal/retirement는 원 invocation과 start stamp, 원 PID/birth 종료,
cgroup 비어 있음, 원 PID1 retention, 실제 GPU client 없음과 같은 unit policy를 다시 확인한다.
STOP/실패 unit 정리/FDSTORE clean은 기존 protected intent/result primitive로 먼저 원 phase를
exclusive reserve하고 같은 원 unit에만 적용한다. phase가 이미 있거나 결과가 불명이면
다시 실행하지 않는다. 원 FAILED 판정은 별도 불변 terminal 기록에 보존하며 성공으로 바꾸지 않는다.

최종 반환은 PID1 store0, 원 process/cgroup 종료, 같은 lease inode의 독립 재획득과 GPU client
없음을 함께 확인한다. read-only reconcile은 이 상태만 재관찰하며 STOP/clean이나 모델 계산을
재시도하지 않는다. 이 acquired-READY 경로는 BUSY의 미실행/CPU 선택 경로가 아니며 서로
위장하지 않는다. 정리 성공도 source 권한·수치 결과 검증·Artifact commit을 대신하지 않는다.

재시작을 검토하면서 cleanup까지 원 controller PID를 요구하면, 그 프로세스가 죽은 뒤
재관찰이 막힐 수 있음을 확인했다. 따라서 원 실행 controller만 가능한 staging/bind/precompute와
다른 root process도 가능한 **읽기 전용** 원 pin/파일 재확인을 별도 public 함수로 나눴다.
READY 관찰에는 원 input/allocation epoch와 output inode identities를 함께 고정한다. 복구는
그 기록과 같은 파일·설치·unit/process/GPU 종료를 확인하며 새 계산을 허용하지 않는다.
원 PID를 현재 PID로 치환하거나 기존 실패를 성공으로 재해석하지 않는다.

### P2-E 검증 체크포인트 — 2026-10-24 UTC

- 실제 root adapter의 precompute/원 terminal/retirement·read-only reconcile 후보를 작성했다.
  주 검증은 controlled OS ports를 사용한 합성 검증이며 실제 GPU unit 실행의 PASS가 아니다.
  root의 원 unit/hash/UID/cgroup/FD/retention 확인과 source owner 권한은 계속 분리한다.
- 현재 source와 기존 INDEX·자원 관찰·계약 packaging·dependency boundary의 관련508 PASS,
  마지막 복구/기존 terminal metadata/phase guard 집중159 PASS다. 겹치는 숫자는 합산하지 않는다.
  production4개 모듈 strict mypy와 변경 Python scoped Ruff/format PASS다.
- 원 controller 종료 후에도 같은 immutable pin/OS identity를 재확인할 수 있으나 precompute는
  거부함을 검증했다. 바뀐 input/allocation/output inode는 복구의 최신값으로 대체하지 않는다.
  dangling grant intent도 없는 것으로 처리하지 않는다. side effect 결과 불명에는 원 phase를
  다시 reserve하거나 STOP/clean을 재실행하지 않으며 read-only 상태 관찰만 허용한다.
- acquired READY의 원 SUCCEEDED/FAILED를 보존하고, 원 PID/cgroup/GPU client 종료 확인 후에만
  원 unit의 FDSTORE를 정리한다. 최종 store0와 같은 lease inode의 독립 재획득까지 확인한다.
  단위 테스트에서 unrelated GPU client·살아 있는 PID·새 invocation·파일/자원 drift·권한 변화는
  정리 승인이 되지 않음을 확인했다. 실제 GPU 반환/공존 시험은 별도 live gate로 남아 있다.
- 빠른 pre-compute BUSY가 정상 종료한 경우에도 실제 systemd의 원 ExecMainPID/store를 읽을
  수 있도록 batch 전용 terminal metadata 경계를 추가했다. old FAILED-only 경계는 유지한다.
  이 tuple만으로 BUSY/CPU fallback을 승인하지 않으며 원 request·미GRANT·빈 수치 출력·정상
  종료·안전한 unit 정리까지 root controller가 확인해야 한다. 아직 그 full driver는 미연결이다.
- public handoff 검증 분리 후 실제 root 임시 파일/DAC/concurrency6 PASS를 재확인했다.
  `/tmp/eom-gpu-batch-os-20261024-r6.log`. 새 로그인·운영 DB 변경·prefix 설치·서비스 재시작·
  모델/GPU 실행은0이며 이전 failed 테스트 기록과 과거 비교 KEEP_CPU는 보존한다.

다음 필수 작업은 실제 root controller의 socket 시작/원 sender 연결/GRANT와 terminal-aware
peer fence, pre-compute BUSY 및 pre-READY 실패의 독립 정리, 실제 source-owner child 권한/
commit/replay 연결이다. 그 뒤 현재 target을 일치시키는 CPU/CUDA view 인덱스와 live canary,
배포·GPU default/CPU fallback·rollback을 검증한다. 현재 checkpoint는 전체 goal 완료가 아니다.

P2_E_OBSERVATION_AND_ACQUIRED_RETIREMENT=SOURCE_VERIFIED,
ROOT_FILE_DAC_AND_CONCURRENCY=PASS, LIVE_GPU_BATCH_UNIT=NOT_RUN,
CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

### P2-E 패키징 확인

source `2a819d7dd2c51a1ab104f5275571b337709ca466`를 commit/push한 뒤 기존
`scripts/api/deploy_release.sh --build-only`로3개 wheel의 archive/RECORD·build metadata
검사를 통과했다. build-only이며 운영 API나 CUDA prefix에 설치한 것은 아니다.
후보 경로는 `/tmp/eom-api-build/2a819d7dd2c51a1ab104f5275571b337709ca466.A56BzZ/dist`다.
platform wheel SHA-256은 `061bb65213050a05689bd06cc03e3bf0551717b4e611ec3263042fc9b561b3dc`다.

그 wheel만 임시 `/tmp/eom-gpu-batch-wheel-import.Mm5piv`에 추출하고, explicit API Python의
`-I -B`, cwd `/`에서 신규8개 module과 제어 schema를 읽었다. 모든 module이 그 추출본에서
해결되고 torch/transformers를 import하거나 모델을 초기화하지 않음을 확인했다. repository
PYTHONPATH나 editable install은 쓰지 않았다. **격리 wheel import probe**이며 실제 native
identity·worker sandbox·GPU 연산·source owner의 운영 연결 PASS는 여전히 아니다.

## P2-F root 실행 제어 연결

새 root adapter는 이미 준비한 원 attempt의 socket activation, 제어 교환, local 결과 검증,
원 invocation의 종료와 retirement만 담당한다. 실제 actor/source admission과 child 재인가는
필수 owner port이며 INDEX와 REFERENCE_QUERY가 같은 수명 제어를 사용한다. 이 port는 DB나
NAS 권한을 worker에게 주지 않는다. 기존 source-owner transaction/encoding reservation과
canonical child Artifact commit은 이 root adapter 바깥의 기존 경계다.

canonical 입력은 원 allocation/grant와 released batch이며, 출력은 같은 원 inode의 임시
result/vector다. 결과 schema/hash·child 범위·unit norm을 검사하고 한 immutable local buffer의
읽기 전용 범위로 반환한다. 최종 ACK 전에 실제 source를 다시 인가하고, ACK 이후 원 worker가
종료·GPU를 반환한 뒤에만 결과를 성공 반환한다. 임시 buffer/path는 DB 정본이 아니다.

원 root PID의 no-clobber dispatch marker를 socket 시작보다 먼저 남긴다. 원 unit invocation과
start stamp를 고정하고 grant intent/입력 bind를 먼저 기록한다. 중간 실패·timeout·다른 invocation은
재전송·새 계산·CPU fallback을 허가하지 않는다. BUSY만으로도 fallback하지 않고 빈 input/output,
미GRANT, 원 SUCCEEDED/ExecMainPID/store0, own cgroup 종료와 원 socket 정리를 별도로 확인한다.
다른 image/trainer가 GPU를 사용 중인 것은 정상 BUSY일 수 있으므로 그 프로세스를 멈추거나
전역 GPU idle/lease 재획득을 BUSY의 조건으로 요구하지 않는다.

transport fence는 ALLOCATION / ACTIVE / TERMINATING으로 나눈다. ACTIVE의 frame마다
원 PID/birth/cgroup만 확인하고 prefix scan·systemctl을 반복하지 않는다. 최종 결과 검증 후 ACK를
보낼 때만 TERMINATING으로 바꿔 정상적인 ACK 직후 worker 종료를 허용한다. 원 unit terminal와
GPU 반환 검증은 별도로 유지한다. 원 terminal 이전 실패는 오류를 보존하고, 확인하지 못한
retention 정리를 성공이나 CPU 선택으로 바꾸지 않는다.

주 access pattern은 고정 attempt key lookup, child hash map, 순서 고정 iteration, 독점 dispatch와
append-only effect 기록이다. child lookup O(1), 최종 검사 O(children + vector bytes), buffer는
기존16MiB 한도이며 새 DB/schema/queue/dependency는 없다. 전체 batch를 다시 복사하거나
generic retry framework를 추가하는 대안은 identity·중복 실행 위험만 늘리므로 쓰지 않는다.

### P2-F 검증 체크포인트 — 2026-10-24 UTC

- 원 root controller의 exclusive dispatch → 고정 socket activation → 원 kernel sender →
  독립 READY 관찰 → 필수 source-owner admission → 원 grant journal/input bind → child 재인가 →
  실제 local output schema/hash/range/unit-norm 검사 → 최종 ACK → 원 terminal/retirement 흐름을
  연결했다. Source owner는 필수 typed port이며 아직 운영 DB/application owner와의 연결을
  완료한 것은 아니다. 이 root adapter는 NAS commit이나 실제 actor 권한을 스스로 만들지 않는다.
- 실제 BUSY claim은 원 PID/birth·SUCCEEDED/ExecMainPID/store0, 원 empty input/output·미GRANT,
  own cgroup 종료와 원 unit/socket 정리를 통과한 경우에만 별도 unavailable observation을
  반환한다. unrelated image/trainer client는 허용하되 이 worker PID의 GPU 사용은 거부한다.
  FAILED·알 수 없는 송수신·수치/hash/권한 오류는 CPU 대체 허가로 변환하지 않는다.
- GRANT 전 FAILED의 독립 정리도 연결했다. 실제 원 ExecMainPID/PID1 retention으로만
  physical fence를 읽고, READY나 사라진 process birth를 만들어내지 않는다. store0이면 unrelated
  GPU holder를 관찰/중단하지 않고, store1이면 원 retention·GPU idle·store 해제·같은 lease inode의
  독립 재획득을 확인한다. 원 FAILED를 기록하고 OS unit 상태만 정리한다. side effect 결과가
  불명이면 같은 phase를 다시 실행하지 않으며 원 오류에 reconcile 필요 상태를 남긴다.
- transport ACTIVE는 원 PID/birth/cgroup/UID만 확인하며 frame마다 systemctl/prefix 전체 scan을
  반복하지 않는다. 빠른 BUSY의 zombie/terminal 전이와 최종 ACK 직후 PID1 status settling을
  별도로 검사했다. TERMINATING 허용은 최종 결과·source 검증 후에만 열리고, 별도의 원 terminal/
  GPU 반환 관찰을 대신하지 않는다.
- controlled OS/unit ports와 실제 contract/binary 검증을 결합한 관련846 PASS, 마지막 집중186 PASS,
  production3개 모듈 strict mypy, scoped Python6개 Ruff/format 및 diff whitespace PASS다.
  겹치는 테스트 수는 합산하지 않는다. 같은 목적의 legacy INDEX/probe·공유 physical resource·
  image lifetime·dependency boundary 회귀도 포함했다. **합성 kernel/unit ports를 사용한 source
  검증이며 실제 PID1/GPU 공존·처리량·sandbox acceptance로 보고하지 않는다.**
- 현재 API/채팅/INDEX owner는 모두 active다. 새 로그인 요청·운영 DB/NAS 쓰기·prefix 설치·unit
  재시작·새 모델/GPU 실행은0이며 과거 비교6회와 KEEP_CPU 판정을 유지했다. 이번 root 제어
  adapter와 새 batch unit은 아직 운영에 설치/활성화하지 않았다.

다음은 actual-actor source owner의 route/reservation·child commit/replay 및 root 서비스 연결,
current target CPU/CUDA companion index, successor numerical runtime 설치다. 그 뒤 disposable DB
concurrency, 실제 CUDA/CPU fallback·그림/trainer 공존·격리·처리량과 호환 배포/rollback을 검증한다.
원 controller를 관찰하기 전 실패한 startup처럼 충분한 원 invocation 증거가 없는 경우는 여전히
unknown으로 보존한다. 새 identity의 재실행이나 성공/CPU 선택으로 추측 복구하지 않는다.

P2_F_ROOT_CONTROLLER=SOURCE_VERIFIED, SOURCE_OWNER_RUNTIME_LINK=PENDING,
LIVE_GPU_BATCH_UNIT=NOT_RUN, CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

## P2-G 기존 source-owner 재인가 연결

계산용 batch가 source authority를 만들지 않도록 실제 runner의 기존 source owners를 재사용한다.
DOCUMENT child는 `CatalogEncodingOwnerAdmission.resolve_launch`가 원 actor/command/step/Job,
encoding ownership·원 input Artifact·source plan을 다시 확인한다. QUERY child는 기존
`CatalogReferenceQueryOwnerAdmission.resolve_execution_sources`와 원 launch/native input closure를
사용한다. selected device의 원 Workflow/launch만 받으며 기존 CPU 요청을 CUDA로 재해석하지 않는다.

이 연결은 짧은 기존 fenced transaction마다 현재 source를 다시 읽는다. 대형 batch 전체를
매 frame마다 복사·parse·hash하지 않는다. 원 batch/child SHA 두 개로 immutable child map을
조회하고, 해당 child의 원 입력과 scope/profile을 검증한 뒤 늦은 actor/lease fence를 적용한다.
순서와 중복은 최초 tuple/set 검증으로 고정한다. lookup O(1), 해당 child의 source 검증은 기존
owner의 indexed lookup/Artifact materialization 비용이며 DB binary·새 queue/table/cache는 없다.

이는 source 재인가 adapter이지 root allocation 증거나 route/reservation·실행 완료 승인이 아니다.
root↔owner 연결의 kernel peer/release fence와 원자적 장치 결정/예약 및 기존 child commit의
후속 실행 영수증은 별도로 연결해야 한다. 입력 hash나 actor label만으로 그 권한을 추측하지 않는다.

묶음의 schema 상한1024행이 원180초 안의 실행을 보장하지 않는다. 원 cold/warm 실측과
실제 길이·child 수를 기준으로 후속 owner packing을 canary에서 검증하고 유한 묶음을 나눈다.
상한을 채우기 위해 원 native timeout을 늘리거나 partial 계산을 CPU로 재실행하지 않는다.

### P2-G 검증 체크포인트 — 2026-10-24 UTC

- `CatalogEmbeddingBatchSourceAuthorization`을 실제 기존 DOCUMENT encoding owner와 QUERY
  source owner에 연결했다. child마다 원 Workflow/command/step/Job·input Artifact 또는 원
  launch·현재 source/control closure를 다시 확인하고, 마지막 actor/lease 확인을 반복한다.
  OPERATOR와 LOCAL_INDEXING_SERVICE를 구분하며 서비스 작업을 사람 계정으로 위장하지 않는다.
- root port도 batch/child SHA 두 개만 전달하도록 좁혔다. 원 batch는 최초 한 번만 검증하고,
  child map의 고정 참조로 조회한다. 잘못된 scope/profile/actor/원 input·missing launch·현재
  권한 철회·만료 lease는 실패하며 최신 입력이나 성공한 과거 fence로 대신하지 않는다.
- source/root controller·기존 owner/executor·routing·dependency 회귀292 PASS, source 집중18 PASS,
  production2개 모듈 strict mypy, Python5개 scoped Ruff/format 및 diff whitespace PASS다.
  겹치는 수는 합산하지 않는다. 테스트의 IAM/수치 실행 seam은 합성이며 운영 권한 승인이나
  실제 GPU canary의 PASS가 아니다.
- 공식 marker-guarded disposable PostgreSQL에서 source 재인가 신규2개, 원 QUERY checkpoint/
  producer/receipt/replay와 일반·mixed encoding reservation 회귀를 함께 실행해 **37 PASS**다.
  동시 두 root가 원 command lock과 원 Job 이력을 유지함을 확인했고, 실제 synthetic command
  lease를 만료시키면 새 source fence가 거부되고 기존 이력은 바뀌지 않는다. 새 source 검사만을
  근거로 아직 미연결인 원자적 route/batch claim까지 검증됐다고 확대하지 않는다.
- 처음에는 fixture seed request 대신 실제 저장된 원 request를 사용하도록 바로잡았고,
  기존 generic fixture의300초 profile을 느슨하게 허용하지 않고 정확한180초 정책을 별도 test
  Artifact로 발행했다. 기존 nonowner 회귀가 요구하는 runtime role도 공식 `--reconcile`로
  같은 임시 DB에 준비했다. 실패한 r1/r2/r4 로그는 보존했으며 생산 코드의 검증을 완화하지 않았다.
- 실제 migration cycle `20261019_0058`과 test role 준비·정리까지 완료했다. 테스트 DB
  `/tmp/eom-api-testdb-20261024174055_151c4d7f`는 공식 guard/marker 검사 후 삭제했으며 운영
  DB/계정/Artifact는 변경하지 않았다. 최종 기록은 `/tmp/eom-gpu-batch-source-20261024-r5.log`다.
  원37개 테스트의 실패 로그와 임시 준비 script는 Git 밖에 보존한다.
- 기존 tmux EOM2의 Linux 인증을 그대로 재사용했다. 새 로그인·서비스 배포/재시작·GPU/모델
  실행은0이며 API/채팅/INDEX owner는 active다. 기존 CPU 운영 기본값과 과거 비교 결과를 유지했다.

다음은 route를 원자적으로 고정하는 owner의 batch allocation/reservation, root 서비스의 실제
peer/release 연결, 자식별 canonical commit/replay의 successor 관찰 영수증이다. 이어 paired
current-target indexes와 numerical runtime 설치, 실제 bounded CUDA/CPU fallback·공존·처리량·
배포/activation/rollback을 검증한다. 이번 source/DB 검증은 전체 goal 완료가 아니다.

P2_G_SOURCE_AUTHORIZATION=SOURCE_VERIFIED, SOURCE_COMMAND_DB_CONCURRENCY=PASS,
BATCH_ROUTE_RESERVATION_AND_RUNTIME_LINK=PENDING, LIVE_GPU_BATCH_UNIT=NOT_RUN,
CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.
