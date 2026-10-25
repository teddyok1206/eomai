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

### 사용자가 지정한 GPU 완료 이후의 작업 순서

2026-10-24에 사용자가 GPU 목표를 먼저 실제 운영까지 완료한 뒤 다음 정적 리뷰를 대조하도록
요청했다. 이 후속 요청 때문에 진행 중 GPU 작업을 되돌리거나 현재 목표의 완료 조건을 줄이지 않는다.
GPU 완료 commit과 실제 installed/active compatible release set을 먼저 checkpoint로 기록한다.
그 이후 `/home/eom/EOM_CODE_REVIEW_POST_CHECKPOINT_2026-10-24.md`의 수정 후보12건과 추가
확인4건을 해당 checkpoint의 코드·운영 상태와 대조한다. 건수와 성격은 사용자 인계 정보이며
아직 검증한 결함이나 실제 재현 결과로 분류하지 않는다. 이미 해결된 후보는 제외한다.

후속 우선순위는 단일 문항 HWPX의 중단 후 복구 → 토큰 갱신/계정 변경 잠금 순서 → 관리자
버전 검사/멱등 재전송 복구 → 문서 처리 lease/응답 대기 정렬이다. 기존 모듈·공식 application
경계를 유지하고 동시성·중단·재전송은 disposable DB에서 검증한다. 원 실패 기록을 성공으로
바꾸지 않는다. README 정리 `4e9c962e`는 이미 commit/push됐으므로 중복 반영하지 않는다.

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

## P2-H 원자적 계획·장치 결정·child binding

이 단계의 책임은 수치 실행이 아닌 **유한 묶음의 계획**이다. 기존 Orchestrator Job과 append-only
JobEvent를 재사용한다. 새 queue/table/worker protocol은 만들지 않는다. 원 선택은 장치와 무관한
Graph/accepted anchor/recipe/view/scope metadata의 canonical `selection.json` Artifact다. 큰 입력과
벡터는 기존 경계에 남기고 DB 계획에는 source-selection/policy의 immutable member pointer와
순서 있는 작은 child commitment만 저장한다. source selection을 단순 SHA로 대체하지 않는다.

logical batch ID + 실제 actor scope의 idempotency key로 원 Job을 식별하며 request hash는 별도로
비교한다. 원 allocation attempt/control frame을 먼저 독점 기록하고, 검증된 원 물리 결과에 따른
장치 결정을 한 번 고정한다. 다른 attempt/나중의 GPU 상태는 기존 결정을 바꾸지 않는다. Caller가
이미 성공한 계획을 읽었다고 새 root unit을 시작할 권한을 얻는 것은 아니다.

선택된 child들은 기존 실제 source owner의 Workflow/step/native Job/launch를 가진다. binding은
그 identity와 original native input hash만 참조한다. 계획의 BOUND는 그 순서·장치·scope·profile과
원 decision을 고정할 뿐 **GPU 실행 성공이나 child Artifact 등록 완료를 뜻하지 않는다.** planning
Job 종료와 numerical/child commit 상태는 구분한다. 실제 actor/source admission과 물리 증거
검증, encoding reservation·child completion은 기존 별도 owner 경계다.

주 연산은 idempotency indexed lookup, 원 Job row lock, O(n) tuple/set 검증과 monotonic event
append다. 규모는32 children·작은 metadata이며 binary는 DB에 없다. 동일 root에서 allocation/route
또는 binding과 해당 planning 상태 전이를 함께 commit한다. 독립 root의 동시 생성은 기존 unique
key와 한정된 insert-conflict read로 원 history를 반환한다. 불명 실행을 새 identity/장치로 복구하지
않고 partial transaction·schema/hash/order 오류는 rollback한다. replay는 read-only이며 원 실패를
성공으로 바꾸지 않는다. 단순 mutable device column이나 file-only lock은 crash/replay 및 실제 DB
소유권과 장치 선택의 원자성을 보장하지 못하므로 사용하지 않는다. Contracts → pure values,
Orchestrator → SQL adapter, runner → 실제 source/물리 admission의 의존 방향을 유지한다.

### P2-H 검증 체크포인트 — 2026-10-24 UTC

- schema-first `embedding-batch-plan/1.0` 후보를 정의했다. device-neutral selection은 원 Graph/
  anchor/recipe/view와 실제 actor scope를 고정하고, request는 정확한 selection/policy Artifact
  member·revision·raw/self hash와 순서 있는 작은 child commitment를 참조한다. 이 schema와
  실제 selection/policy 발행·운영 activation은 서로 다른 상태다.
- `EmbeddingBatchPlanStore`는 기존 Job unique key와 row lock/append-only history를 사용한다.
  동시 allocation 중 하나만 created=True이고, 다른 root는 원 attempt와 선택을 조회한다. CPU/GPU
  상태가 바뀌어도 원 route를 교체하지 않는다. BOUND와 planning 종료는 같은 transaction이며
  중단 시 전부 rollback한다. planning SUCCEEDED는 numerical SUCCEEDED가 아니다.
- child binding에는 필수 source authorizer가 있고 false 반환도 거부한다. 실제 source adapter는
  원 Workflow/step/native Job/launch/request/input identity를 대조하고 현재 actor/lease/source를
  확인한다. 소스·수치 profile 규칙은 workflow의 공통 순수 함수로 이동해 계획과 실제 index-route가
  같은 규칙을 사용하도록 했다. released predecessor schema/의미/실행 핀은 바꾸지 않았다.
- 관련 source/route/root-control/index-pair/binary/packaging/dependency283 PASS와 집중133 PASS,
  production5개 모듈 strict mypy, scoped Python9개 Ruff/format, diff whitespace PASS다. 겹치는
  수는 합산하지 않는다. 신규 schema의 canonical/mirror hash·JSON Schema2020-12도 확인했다.
- 공식 marker-guarded disposable PostgreSQL에서17 PASS다. 실제 동시 allocation, 원 요청
  conflict, route/BOUND replay·중단 rollback·실패 보존, child authority 거부, autoflush on/off와
  기존 B-tree lookup capability를 확인했다. 실제 원 QUERY Job/command를 사용하는 source binding
  callback도 확인했다. child 권한이 마지막 확인 중 철회되거나 false를 반환해도 BOUND를 쓰지
  않으며 exact replay도 늦은 fence를 건너뛰지 않는다. planning fixture의 child authority 및
  IAM/수치 seam은 합성이므로 이를
  실제 RAG/GPU 운영 실행으로 보고하지 않는다.
- 최종 로그는 `/tmp/eom-gpu-batch-plan-20261024-r5.log`이며 임시 DB
  `/tmp/eom-api-testdb-20261024182722_429882af`를 공식 guard로 검증한 뒤 제거했다. 추가
  source-binding negative test의 누락된 test import만 보정했고 그 실패 r3 로그는 보존했다.
  앞선 r1/r2/r4도 각각12/14/15 PASS 및 해당 임시 DB 정리 기록으로 남겨뒀다. 운영 DB/Artifact/계정,
  기존 실패 이력, 서비스 release/prefix는 변경하지 않았다. Linux 인증은 기존 창을 재사용했다.

다음은 실제 canonical selection/policy 발행·parent request admission과 root↔owner peer/release
연결, 선택된 child의 기존 예약/완료를 묶는 실행 adapter다. 이어 exact paired indexes, successor
runtime 설치와 실제 finite GPU/CPU fallback·그림/trainer 공존·처리량·배포/rollback을 검증한다.
사용자 지정 후속 정적 리뷰는 위 목표를 완료하고 실제 운영 release checkpoint를 고정한 뒤 한다.

P2_H_PLANNING=SOURCE_VERIFIED, PLANNING_DB_CONCURRENCY=PASS,
OWNER_RUNTIME_CONNECTION=PENDING, LIVE_GPU_BATCH_UNIT=NOT_RUN,
CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

## P2-I canonical controls와 GPU 이전 source admission

selection과 routing policy는 기존 `LocalEmbeddingControlArtifactPublisher`와
`ControlFileSetPublisher`로만 발행한다. parent Job에는 정확한 member/revision/raw hash와
self hash만 남기며 새 Artifact store, queue 또는 DB schema를 만들지 않는다. 정책을 발행하는
행위와 설치된 owner가 그 정책을 활성화하는 행위는 다르다.

owner의 installed configuration은 Catalog source scope와 허용된 routing policy pointer/hash를
고정한다. 실제 호출자는 ingress가 캡처한 기존 Registry actor다. request의 actor 문자열은 권한이
아니다. GPU 배정 전에 공식 `authorize_scope` → pinned control resolution →
`resolve_selected_sources`를 호출하며 원 source/profile/report와 Graph/recipe/정책을 정확히
대조한다. 종료 직전에는 같은 root의 provenance와 현재 source/actor를 다시 확인한다. 실행·발행
중 권한 변경이나 원자료 불일치는 CPU fallback이나 latest 재선택 사유가 아니다.

현재 미배포 planning 후보의 INDEX selection에는 기존 registered-review source/profile/evidence
pointer도 명시적으로 수용한다. 이는 V10 solution-report로 위장하지 않는 별도 anchor다. QUERY의
기존 reference anchor 의미는 유지한다. 기존 released schema와 운영 Job은 바꾸지 않는다.

주 접근은 최대32개 revision의 indexed lookup, bounded ordered iteration, hash-map membership다.
source와 entry는 revision map으로 한 번 대조해 O(n) 시간/공간을 사용하며 전체 corpus를 복사하지
않는다. 공식 Catalog source fence를 먼저 획득하고 parent planning row를 뒤에 다루는 순서를
유지한다. caller가 소유한 하나의 root transaction이며 nested transaction으로 승인 오류를
숨기지 않는다. retry는 같은 pinned controls의 재조회일 뿐 GPU dispatch 허가가 아니다.

request의 JSON을 직접 신뢰하는 대안은 current permissions, accepted report, canonical Artifact
lifecycle을 보장하지 못하므로 사용하지 않는다. 이 단계는 admission/publication 연결이며 실제
root IPC·수치 실행·child commit·운영 활성화의 완료 증거를 대신하지 않는다.

### P2-I 검증 체크포인트 — 2026-10-24 UTC

- 실제 기존 file-set owner로 `selection.json`/`policy.json`을 발행·재전송한다. first-observation
  UTC와 원 Artifact를 재사용하며 다른 종류/내용을 같은 key로 바꾸지 못한다. raw hash와 semantic
  hash를 분리하고 planning/control 계약의 JSON timestamp 직렬화 방식에 맞춘다. 후보 발행만으로
  runtime policy가 활성화되지 않는다.
- 새 `CatalogEmbeddingBatchPlanAdmission`은 설치된 routing selection과 exact source scope,
  실제 사람/서비스 actor를 대조한다. 첫 scope 거부는 control bytes를 읽기 전에 발생한다.
  canonical Artifact producer/lifecycle/schema/member/hash, 원 Graph/profile/report와 recipe를
  확인하고 마지막 provenance/source/actor fence 및 root transaction identity를 재확인한다.
  원 API/child source owner를 우회하는 DB/NAS reader나 대체 검색 엔진은 추가하지 않았다.
- 미배포 planning schema에 INDEX 전용 registered-review anchor를 추가했다. 원 검토 evidence와
  profile2 pointer를 유지하며 QUERY의 기존 reference anchor로 위장하지 못한다. canonical/mirror
  SHA는 `94fe09d2dc756e15b77c3f61883a4dd76f6028b463199a5ad62bd6bf700f1337`다.
  released predecessor schema/운영 history는 변경하지 않았다.
- 관련 계약·source·routing·result·dependency251 PASS, root controller/handoff/observation와
  numerical wheel/resource packaging285 PASS다. 범위가 겹치므로 합산하지 않는다. production3개
  모듈 strict mypy, scoped Python5개 Ruff/format, diff whitespace PASS다.
- 공식 marker-guarded disposable PostgreSQL에서22 PASS다. canonical control 발행 동시성,
  source window 안의 parent allocation 경쟁, exact replay, 중단/늦은 권한 거부 rollback과
  기존 child source/plan 동시성 suite를 함께 확인했다. IAM/source leaves는 합성이며 이를 실제
  RAG/GPU 운영 검증으로 보고하지 않는다. 최종 로그는
  `/tmp/eom-gpu-batch-admission-20261024-r2.log`다. 초기 r1의 synthetic allocation fixture에서
  actor 변경 후 child-set hash 재봉인이 누락된 실패를 바로잡았고 그 로그는 보존했다.
- 최종 DB `/tmp/eom-api-testdb-20261024184559_f7600f99`와 초기 fixture 실패 DB
  `/tmp/eom-api-testdb-20261024184440_39453aea`는 해당 official guard로 확인한 뒤 정리했다.
  운영 DB/계정/실패 history와 기존 runtime pin은 변경하지 않았다. API·일반 대화·INDEX owner는
  active이고 마지막 GPU 관측은0%/2MiB다. 새 인증 요청·모델 실행·GPU unit 실행은 없었다.

다음은 root↔actual-owner peer/release 연결과 선택된 child 예약·원 출력 commit/replay다.
그 뒤 successor runtime/paired indexes와 실제 finite GPU/CPU fallback·그림/trainer 공존·처리량을
검증하고 호환 운영 release로 활성화한다. 이 단계 commit은 GPU 목표의 완료 체크포인트가 아니다.

P2_I_CANONICAL_CONTROLS_AND_ADMISSION=SOURCE_VERIFIED,
PUBLICATION_AND_PLAN_DB_CONCURRENCY=PASS, OWNER_RUNTIME_CONNECTION=PENDING,
LIVE_GPU_BATCH_UNIT=NOT_RUN, CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

P2-I source commit `d08eaf710d002d2bbeb905817c13a369d09f206c`는 main에 push했다.
해당 commit의 공식 API/platform build-only 및 wheel RECORD 검증은 PASS다.
산출물은 `/tmp/eom-api-build/d08eaf710d002d2bbeb905817c13a369d09f206c.7lyt0B/dist`이며
설치·activation·실제 GPU/CPU 수치 실행은 하지 않았다. 이 문서 정리는 candidate code나 운영
runtime pin을 바꾸지 않으며 README의 별도 완료 작업도 다시 반영하지 않는다.

## P2-J root↔actual owner의 유한 연결

기존 GPU controller는 root 자원 관찰/원 worker 수명만 소유한다. DB/NAS/인증을 root 수치
adapter에 넣지 않는다. actual owner는 기존 runner UID의 Catalog/Orchestrator application이며
actor/source/lease와 child의 등록을 소유한다. native worker는 계속 root와만 통신한다.

새 `embedding-batch-owner-control/1.0`은 이 둘의 동일 host Unix 연결이다. 기존 bounded framing,
SO_PEERCRED와 매 frame SCM_CREDENTIALS/원 PID birth fence를 재사용하고 exact controller release,
원 allocation request hash, 순서와 self hash를 검증한다. root READY는 신뢰된 root adapter의
하드웨어 관찰 요약일 뿐 actor permission이나 양도 가능한 lease가 아니다. owner BOUND도 물리
GPU 관찰을 대신하지 않는다. 서로의 책임을 DTO의 boolean으로 합치지 않는다.

큰 batch input은 owner 전용 고정 작업 root의 attempt/`batch-input.json`에 한 번 materialize하고
root가 bounded canonical/schema/hash/inode/owner/mode 검증 후 자신의 원 empty input inode에
한 번 bind한다. wire에는 이 위치에서 유도 가능한 attempt identity와 byte/hash metadata 및
작은 원 planning binding만 보낸다. 임의 path, credential, prompt, vector payload는 보내지 않는다.
결과도 기존 root handoff의 read-only member를 가리키는 작은 완료 요약이며 binary를 IPC로 복사하지
않는다. 최종 Artifact 정본·child commit은 기존 Orchestrator 소유권이다.

상태는 READY→BOUND→(CHECK→CHECKED)*→COMPLETED→ACK의 유한 전이표다. 입구 BUSY는 별도의
terminal이며 actual root의 원 unit/비실행/retirement 증거가 있어야만 owner가 CPU route를
고정할 수 있다. 완료 ACK는 수신 확인이지 canonical publication 성공이 아니다. 임의 reconnect,
재계산, timeout 후 새 identity 생성은 없다. 실패 시 원 작업·파일·history를 남긴다.

한 묶음≤32 child에 대한 hash-keyed map과 monotonic check sequence를 사용한다. 시간/공간 O(n),
frame≤64KiB, child check≤352(native≤256+root pre/post≤96), 하나의 원180초 deadline이다. 원
peer/release를 확인한 owner handler가 짧은 기존 DB roots를 열며 root는 SQL transaction을
유지하지 않는다. 프로토콜은 새 DB/queue/schema migration을 만들지 않는다.

단순히 root에 Catalog 객체를 넣는 대안은 실제 runner UID/인증·DB 역할 경계를 깨뜨리므로 쓰지
않는다. 새 네트워크 RPC framework나 FD로 GPU lease를 넘기는 우회도 필요하지 않다. source 선택,
예약, child 결과 commit의 실제 application 연결과 설치 검증은 별도 완료 조건으로 남는다.

### P2-J 검증 체크포인트 — 2026-10-24 UTC

- 새 제어 schema canonical/mirror SHA는
  `c253a518f30cf1f12fbe5644b7758ce50b726143ebe4334078cfba6cabdc437b`다.
  closed JSON Schema2020-12와 frozen/raw-preserving Pydantic은 임의 path/role/token/vector,
  다른 원 allocation/release/순서·check ACK와 중복 완료를 거부한다. ACK는 publication이 아니다.
- `RootEmbeddingBatchOwnerProxy`가 실제 기존 GPU controller의 mandatory source port를 이
  연결로 구현한다. source 입력은 고정 owner workspace에서 검증해 한 번 읽고, 실행 중에는 작은
  원 child hash와 metadata epoch만 검사한다. 매 child마다 numerical prefix 전체를 순회하지
  않는 회귀를 추가했다. root에는 DB/NAS/auth/source 판단을 추가하지 않았다.
- 기존 controller 결과는 이미 검증한 원 worker output claim을 함께 보존한다. 결과 bytes를
  재직렬화·재해시해서 두 번째 identity를 만들지 않고 원 result/vector hash·count를 전달한다.
  원 unit의 SUCCEEDED/retirement/FD-store0이 아닌 완료는 전달하지 않는다.
- 실제 OS 검사에서 마지막 ACK 직후 `/proc`가 아직 R 상태인데 root 소유로 변하는 종료 경합을
  재현했다(r3/r4 로그 보존). active peer parser를 느슨하게 바꾸지 않고 원 PID에 대한 pidfd를
  배정 전 birth 양쪽 확인 사이에 보유한다. 종료 교환에만 원 deadline 안에서 최대100ms pidfd
  exit 관찰을 허용한다. 살아 있는 권한 오류·PID 재사용·active 상태의 종료는 계속 거부한다.
  설치 Conda에 os.pidfd_open이 없어 표준 ctypes/libc wrapper를 쓴다. 새 외부 dependency,
  signal 권한 또는 약한 PID-only fallback은 없다. 소유 FD 교체 시 다른 FD를 닫지도 않는다.
- 최종 관련214 PASS, 별도 기존 handoff/observation/lifetime/stdio/binary/wheel377 PASS,
  신설 연결 집중100 PASS다. 범위는 겹치므로 합산하지 않는다. production6개 모듈 strict mypy,
  scoped Python12개 Ruff/format 및 diff whitespace PASS다.
- 실제 root와 runner UID의 Unix peer/sender·birth/pidfd, 즉시 종료 ACK, owner-local input 읽기,
  다른 UID의 source workspace 거부, 상속한 socket sender 거부 및 기존 original handoff를
  `/run`의 자동 정리되는 임시 root에서 확인했다. 최종10 PASS 로그는
  `/tmp/eom-gpu-batch-owner-os-20261024-r6.log`다. 실제 source/IAM/unit/GPU 연산은 합성 seam인
  검사이므로 live RAG/GPU/sandbox PASS로 확대하지 않는다. 운영 DB/계정/원 실패 이력은 그대로다.
- API·일반 대화·INDEX owner는 active, 마지막 GPU 관측0%/2MiB다. 새 모델·GPU unit 실행, 운영
  설치·activation·credential 변경은 없었다. parent planning/source admission의 이전 disposable
  DB22 PASS는 보존하며 이번에는 DB·migration·queue 변경이 없었다.

다음은 실제 owner의 선택된 device child 준비/예약·BOUND와 이 channel handler를 연결하고,
원 batch 완료 요약으로 canonical child 결과를 commit/reconcile하는 application 경계다.
이어서 numerical successor 설치, exact paired indexes, 실제 GPU/CPU fallback·그림/trainer 공존·
처리량·호환 운영 활성화와 rollback을 확인한다. source/OS 검사만으로 목표를 완료하지 않는다.

P2_J_ROOT_OWNER_BRIDGE=SOURCE_AND_OS_VERIFIED,
ACTUAL_OWNER_ALLOCATION_AND_CHILD_COMMIT=PENDING, LIVE_GPU_BATCH_UNIT=NOT_RUN,
CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.

P2-J source commit `f156e6a28280668f65cc049416866c01874cc40c`는 main에 push했다.
공식 API/platform build-only와 wheel RECORD 검증은 PASS이며 산출물은
`/tmp/eom-api-build/f156e6a28280668f65cc049416866c01874cc40c.GgjJdw/dist`다.
그3개 wheel만 `/tmp/eom-batch-owner-wheel-ttCtRTte`에 추출하고 explicit API Python의
`-I -B`, cwd `/`에서 신규 연결6개 모듈과 packaged schema를 읽었다. EOM dependency225개도
모두 추출 wheel에서 해결됐고 torch/transformers import·모델 초기화는 없었다. source Git,
editable import, native identity/sandbox/GPU 실행 또는 운영 설치 검증으로 대체한 것이 아니다.

## P2-K actual owner 결과 검증과 canonical 실행 근거

root의 완료 ACK는 publication이 아니다. actual owner가 원 채널의 완료 요약과 root 소유의
고정 result/vector member, 자기 원 input을 대조하고 실제 Catalog child source/lease를 전후
재검증한 뒤 기존 Orchestrator file-set owner로 작은 실행 영수증을 발행한다. root나 native
worker에 DB/NAS 쓰기를 주지 않는다. 입력 text·vector payload를 영수증/DB/IPC에 복제하지 않는다.

새 receipt1은 현재 구현된 CUDA root 완료 의미만 다룬다. CPU 결과를 CUDA proof로 위장하지
않으며 CPU batch의 실제 unit/proof 연결에서 별도 명시적 variant를 추가한다. 기존 receipt와
CPU 실행 이력은 그대로 보존한다. 영수증은 parent planning Job ID와 원 request/route/binding,
root READY/완료의 작은 불변 값, child별 Job/input/result/shard/binary hash·range만 보유한다.
Root observations는 독립 lifecycle이 없는 small values여서 별도 Artifact들로 분해하지 않는다.

원 parent BOUND history와 actual child bindings를 official application 경계에서 확인해야만
발행할 수 있다. Artifact 승인만으로 실제 실행이나 사람 권한을 추정하지 않는다. 이후 QUERY의
기존 continuation에 batch 실행 proof successor를 연결하고 DOCUMENT의 기존 encoding 예약과
결과 등록을 재사용한다. CPU legacy executor가 batch child를 새로 실행하지 못하는 모드 경계도
같은 allocation transaction에 고정해야 한다.

주 접근은 원 attempt 고정 경로 두 개의 bounded read, child ordinal/hash map lookup과 ordered
iteration이다. metadata O(n), binary는 한 버퍼와 read-only memoryviews다(최대32 child/16MiB).
immutable bytes는 명시적 root→owner 검증 경계에서만 materialize하며 각 child의 canonical 결과
등록 때 필요한 범위만 별도 commit한다. 큰 binary나 aggregate input은 DB에 넣지 않는다.

모델 실행과 큰 입력·binary 읽기 동안 SQL lock을 유지하지 않는다. 작은 실행 영수증의 공식
publication 때는 기존 query completion과 같이 실제 source/lease read fence를 유지하되,
parent/child의 미커밋 write를 독립 Artifact commit에 걸쳐 보유하지 않는다. 기존 publisher의
key/transaction/first-observation replay를 쓰며 같은 원 실행의 영수증만 재조회한다.
부분·불명 결과는 보존하고 재계산/CPU fallback으로 바꾸지 않는다. 단순히 wire ACK나 shape-valid
JSON을 성공으로 등록하는 대안은 실제 source·hash·원 실행 closure가 없어 사용하지 않는다.

P2-K 검증 결과:

- receipt/result-read/channel/기존 control publisher 집중74 PASS다. native 연산은 합성 backend,
  unit의 root/IAM leaf도 명시적 합성 seam이며 실제 GPU/운영 source PASS가 아니다.
- marker-guarded disposable PostgreSQL에서 실행 영수증10건과 기존 planning/admission/source22건,
  총32 PASS(37.62s)다. 동시 publication의 한 Artifact 수렴, 중단 전 미발행, 원 key의 변경 거부,
  parent 계획/실패를 계산 성공으로 사용하지 않음, 재전송 때 현재 권한 재확인, 발행 직후 권한
  취소 때 이미 commit한 기술 Artifact를 보존하고 child 완료는 차단함을 확인했다. large binary는
  DB request에 없고 parent history도 바뀌지 않는다. 실제 IAM/source/numerical leaf는 합성이다.
- 첫 DB r3은 fixture batch ID 중복으로3 failed/23 passed/6 errors였다. 실제 정책을 완화하지 않고
  case별 identity를 고친 r4에서 위32 PASS를 확인했다. 실패 로그는 보존하고 같은 marker DB를
  공식 cleanup으로 제거했다. 운영 DB·계정·원 FAILED 기록은 변경하지 않았다.
  로그: `/tmp/eom-gpu-batch-admission-20261024-r3.log`, 같은 prefix의 `r4.log`.
- 실제 root/runner UID·sender·birth/pidfd/local DAC suite는 root-owned640 결과와 read-only 공유
  vector buffer의 owner 검증을 추가해12 PASS(6.84s)다. 로그는
  `/tmp/eom-gpu-batch-owner-os-20261024-r7.log`다. source/IAM·unit·GPU 연산은 여전히 합성이다.
- 별도 기존 plan/admission/source/proxy/결과 및 dependency·wheel inventory103 PASS(57.79s)다.
  위74/DB32/OS12와 겹치는 경계가 있으므로 전체 고유 테스트 수처럼 합산하지 않는다.
- production7모듈 strict mypy, scoped Python14개 Ruff/format, diff whitespace PASS다.
  API/Web·채팅·INDEX owner는 active이고 GPU0%/2MiB다. 모델 import·추론·운영 배포·activation은
  하지 않았다.

P2_K_RECEIPT=SOURCE_AND_DB_AND_OS_VERIFIED, CHILD_CANONICAL_COMPLETION=PENDING,
LIVE_GPU_BATCH=NOT_RUN, GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU, GOAL=ACTIVE.

P2-K source commit `ecb653fce3e8968bb50d2e083f64b402b2e6e215`를 main에 push했다.
공식 API/platform build-only와 wheel RECORD 검사 PASS이며 산출물은
`/tmp/eom-api-build/ecb653fce3e8968bb50d2e083f64b402b2e6e215.XUMSQL/dist`다.
그3개 wheel을 `/tmp/eom-batch-receipt-wheel-P0OSvTh3`에 추출해 API Python `-I -B`, cwd `/`에서
신규 receipt/publication/read를 포함한9개 모듈과 packaged schema를 읽었다. EOM dependency413개가
모두 추출 wheel에서 해결됐으며 torch/transformers import는 없었다. 이는 설치된 실제 service
identity/sandbox/GPU 실행·activation을 대신하지 않는 data-only wheel 검증이다.

## P2-L 기존 QUERY continuation에 batch 실행 근거 연결

기존 CPU checkpoint1.0/1.1의 고정 prepare/query unit proof를 GPU 실행처럼 해석하지 않는다.
후속1.2의 EXECUTED는 P2-K canonical batch receipt의 immutable member/hash와 child ordinal,
원 child result hash·완료 시각만 보유한다. ALLOCATION/PUBLISHED/COMPLETED와 공개 검색
결과 receipt1은 재사용한다. 기존 성공/실패 Job·checkpoint bytes는 수정하지 않는다.

정본은 원 native QUERY Job의 append-only checkpoint와 기존 Orchestrator가 commit한 batch
receipt Artifact다. 결과 조회/등록 때 actual child source 권한과 원 parent planning history,
receipt producer·member raw/self hash·schema·lifecycle, route/binding/Job/input/result/shard/binary를
대조한다. GPU unavailable과 무관한 누락·오류는 명시적으로 실패하며 모델을 다시 실행하지 않는다.
현재 receipt1이 CUDA 전용이므로 CPU fallback batch를1.2 CUDA proof로 통과시키지 않는다.

원 parent/child는 indexed ID/key lookup, child는 ordinal 접근, history는 최대4개의 ordered tuple이다.
추가 DB/table/index/queue나 큰 binary 저장은 없다. lookup O(1) indexed, metadata O(children) bounded다.
기존 native Job row lock과 원 caller transaction이 append/replay를 소유한다. module 방향은
workflow 순수 계약 → Orchestrator 기존 checkpoint adapter → runner 현재 owner/Artifact read다.
일반 조회에 historical unit 재기동/모델 재실행을 요구하지 않는다. 원 RPC ACK만 조회 성공으로
사용하는 더 단순한 대안은 canonical producer와 child 원 실행 closure가 없어 충분하지 않다.

QUERY ID/input 준비도 기존 CPU executor에서 작은 순수 함수로 공통화한다. replay는 원 Job/query
ID·최초 command·시각을 유지한다. CPU handoff guard는 durable Job 생성 전에 그대로 적용한다.
후속 batch owner도 같은 준비 함수를 사용하지만 이 값만으로 compute/source 권한은 생기지 않는다.

P2-L 구현·검증:

- checkpoint1.2 schema를 먼저 정의하고 package mirror/raw SHA를 고정했다.
  `8e00ce9ceb8f0717bf6eb0c9a42481df4585b055d449a986e0471839df65bf65`이며1.0/1.1의
  기존 schema SHA는 그대로다. 원 allocation의 checkpoint family를 유지하고 CPU unit proof와
  batch receipt를 섞거나 재해석하지 않는다.1.2를 CPU profile에 적용하는 것도 거부한다.
- launch/input 순수 준비는 `reference_query_launch_preparation`이 소유하고 기존 CPU executor가
  재사용한다. 원 ID/time/command replay와 durable Job 이전 exact CPU guard가 유지된다.
- `reference_query_batch_execution_read`는 current source 경계 안에서 원 receipt와 parent Job/
  controls/route/binding을 대조한다. 실제 actor·Graph·권한 정책·anchor·query options·recipe·
  CUDA profile/bundle과 원 child Workflow/Job/input/result/range가 일치해야 한다. native result의
  실제 binary 검증은 기존 canonical reader에 두며 작은 receipt 검증 때문에 vector를 다시 읽지 않는다.
- 기존 completion은 작은 readonly publication-material interface로 CPU와 batch의 결과 등록을
  공유한다. batch proof는 첫 child Artifact publication 전, canonical result/receipt 등록과 완료
  조회 경계에서 확인한다. 별도 publication framework나 DB/queue/migration은 추가하지 않았다.
- final disposable PostgreSQL50 PASS(85.12s), 공식 cleanup PASS다. 이 중18개가 신규 QUERY batch
  read/completion 경계이며 기존32개도 회귀 확인했다. canonical member/parent/route/child 검증,
  stale revision/raw/self hash 실패, 동시 checkpoint replay, QUERY Artifact 직후/receipt 전/receipt
  직후 중단에서 원 producer 재사용과 completed canonical-only 재조회가 포함된다.
  로그는 `/tmp/eom-gpu-batch-admission-20261024-r8.log`다. 앞선 r5(42 PASS), r6(46 PASS),
  r7(47 PASS)는 이후 추가 case 이전 기록으로 보존하고 final50을 대체하지 않는다. 실제 SQL/
  Artifact/typed source derivation은 사용했지만 current IAM/Workflow·command 및 숫자/GPU leaf는
  명시적인 합성 seam이다. 실제 GPU/sandbox/서비스 admission 성공으로 확대하지 않는다.
- 관련 unit75 PASS, 별도 CPU completion/consumer/Artifact·dependency/wheel inventory103 PASS,
  최종1.2/launch/private continuation77 PASS다. 범위가 겹쳐 합산하지 않는다. 단위 검사 첫20건 중
  1건은 예상 schema 예외 타입을 좁게 지정한 fixture 문제였고 실패 의미를 약화시키지 않고 수정했다.
  production9모듈 strict mypy 및 scoped Python16개 Ruff/format, diff whitespace PASS다.
- API/Web·채팅·INDEX owner active, GPU0%/2MiB다. 운영 설치·activation·모델 추론·credential 변경은
  없었다. 기존 root/runner OS12 PASS는 변경 없는 어댑터의 이전 근거로 유지하며 이번 재실행으로
  보고하지 않는다. README의 별도 승인 commit도 건드리지 않았다.

P2_L_QUERY_BATCH_COMPLETION=SOURCE_AND_DB_VERIFIED, ACTUAL_SELECTED_CHILD_DISPATCH=PENDING,
LIVE_GPU_BATCH=NOT_RUN, GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU, GOAL=ACTIVE.

다음은 root↔actual owner channel의 설치된 시작 진입점, 선택된 device의 기존 QUERY/START·
command claim/native1.2 allocation과 DOCUMENT reservation/commit을 연결하는 실제 실행 경계다.
이후 sealed numerical successor·CPU finite fallback·exact paired indexes, 실제 GPU/자원 부족 CPU·
sandbox·image/trainer 공존·처리량과 호환 release/default/rollback 검증을 닫는다. 이 source/DB
체크포인트를 GPU 목표 완료 commit 또는 실제 운영 release로 부르지 않는다.

P2-L source commit `a3814da3e454618de72029555d54c68d7a19be03`를 main에 push했다.
공식 API/platform build-only 및 wheel RECORD PASS, 산출물은
`/tmp/eom-api-build/a3814da3e454618de72029555d54c68d7a19be03.QlSj6V/dist`다.
그3개 wheel을 `/tmp/eom-batch-query-wheel-timSEz5u`에 추출해 API Python `-I -B`, cwd `/`에서
신규 QUERY continuation/read/publication을 포함한13개 모듈을 import했다. dependency421개도
추출 wheel에서 해결됐고 새 packaged1.2 schema SHA도 일치했다. torch/transformers import나
모델 초기화, 실제 service UID/sandbox/운영 설치·activation은 하지 않았다.

다음 root 시작 연결에서는 기존 CUDA INDEX의 fixed owner systemd/Polkit/보호된 owner-release
방식을 먼저 재사용한다. 별도 일반-purpose socket broker·queue·daemon을 추가하지 않는다.
새 진입은 fixed attempt identity만 받고 기존 typed ALLOCATION_REQUEST와 실제 root↔runner
kernel peer/birth를 연결한다. bootstrap은 작은 metadata/socket만, 큰 batch input은 기존
owner workspace 한 곳만 사용한다. root는 설치된 policy/config만 읽고 DB/NAS/source 권한은
actual owner의 기존 application callback에 남긴다. 구체 wire/설치 변경 전에 기존 installer와
Polkit whitelist의 실제 지원 범위를 대조하며, 지원된 경계가 있다는 추정만으로 활성화하지 않는다.

## P2-M 실제 fixed root 시작과 owner rendezvous

기존 CUDA INDEX owner의 one-shot systemd/Polkit·`prepare_native_index.py` 보호 release bootstrap을
재사용한다. 추가 mode는 `GPU_BATCH <original-attempt-hex>` 하나이며 임의 path/명령/사용자/단위를
받지 않는다. 기존 JSON Schema의 ALLOCATION_REQUEST를 canonical600 파일로 한 번 staging한다.
별도 worker 메시지/schema나 새 큐는 없다. 정본 parent Job은 DB에 남고 작은 로컬 metadata와
Unix socket은 `/var/lib/eom-workflow-runner/embedding-batch-control/<attempt>`에 둔다. 큰 batch
input은 기존 embedding-work-batches workspace에만 보유한다.

실제 owner는 기존 protected workspace와 no-clobber dispatch marker를 쓴다. root는 고정
Root0 policy 파일의 raw/self hash·purpose/config/profile을 확인하고 원 caller socket으로 연결한다.
SO_PEERCRED/SCM_CREDENTIALS·원 PID/birth/pidfd를 검증한 기존 channel/proxy가 source callback을
운반한다. owner도 실제 root unit MainPID/원 invocation·고정 template를 확인한 뒤 원 channel에
바인딩한다. PID나 JSON이 source permission이 되는 것은 아니며 actual owner의 기존 Catalog
source/lease 검증이 계속 필요하다.

주 접근은 attempt map/key lookup, bounded metadata read, 고정4개 member와 socket inode 비교다.
공간은 O(1) metadata, 시간은 bounded bytes/고정 member 수다. No-follow retained directory FD와
원 socket inode만 정리하며 기존 allocation/dispatch/부분 파일은 보존한다. dispatch marker는
systemctl side effect 전에 한 번 기록한다. timeout/실패/관측 불명 때 재시작·새 ID·CPU fallback을
추정하지 않는다. Root native retirement와 canonical 결과 저장은 기존 owner/controller를 사용한다.
코드/IPC adapter에는 SQL·NAS가 없고 source application과 physical adapter의 의존 방향을 유지한다.

Root가 arbitrary owner path를 읽거나 상시 broker를 만드는 대안은 불필요한 실행 표면과 상태를
늘리므로 채택하지 않는다. 기존 protected owner-release와 purpose별 fixed unit/Polkit만 확장한다.
정상 source/DB 테스트나 OS rendezvous 검증을 실제 GPU/numerical admission으로 확대하지 않는다.

P2-M 구현·검증:

- 실제 source owner가 원 allocation의 local listener를 먼저 준비하고 no-clobber marker를 기록한
  뒤 fixed root unit만 시작한다. root/owner 양쪽은 실제 kernel UID/GID·sender·원 PID/birth/pidfd를
  확인한다. template/MainPID/invocation/drop-in 관측도 대조한다. timeout·부분 dispatch는 같은
  attempt의 재기동이나 CPU fallback 허가가 아니다.
- 기존 stdlib bootstrap을 platform wheel/RECORD에 포함하고 owner-release installer가 그 검증된
  작은 파일만 runtime 경계에 materialize한다. runtime Git/source 의존이나 새 dependency가 없다.
  실제 offline `pip --target`의 data-file 배치와 이전 wheel 호환도 검사했다.
- 실제 권한 하강 후 non-dumpable 프로세스의 `/proc/<pid>` directory UID와 일부 leaf의 root
  storage UID가 다를 수 있었다. 임의 dumpability 활성화로 우회하지 않고, 기존 protected reader에
  명시적 kernel leaf 소유 구분만 추가했다. batch owner는 모든 real/effective/saved/fs UID·GID와
  같은 active birth를 전후 확인하고 원 pidfd로 생존을 확인한다. 기존 numerical/benchmark의
  strict parser와 보호된 runtime 파일의 기본 소유 규칙은 변경하지 않았다.
- 계산의 검증/ACK 뒤에는 immutable terminal metadata를 보존한다. canonical publication이 종료된
  socket/PID나 계산 deadline의 생존을 요구하지 않도록 했지만, 현재 source/권한/lease와 parent
  history 검증은 계속 별도 application 경계에서 수행한다. wire ACK는 publication 성공이 아니다.
- 집중 unit/packaging133 PASS(49.65s), 별도 installed-runtime/snapshot/receipt/dependency53 PASS
  (25.66s)다. scoped Python19개 Ruff/format와 production9모듈 strict mypy, shell syntax/diff PASS다.
  두 test 목록의 최초 invocation에는 존재하지 않는 파일명으로 collection error가 있었고 실제
  파일을 확인해 위 범위로 실행했다. 실행하지 않은 검사를 PASS로 포함하지 않는다.
- guarded disposable PostgreSQL50 PASS(82.83s), 공식 cleanup PASS다. 로그:
  `/tmp/eom-gpu-batch-admission-20261024-r9.log`. terminal ACK snapshot 변경 뒤에도 원 child
  publication/replay·중단/동시성·current source 거부 경계를 확인했다. actual IAM/numerical leaf는
  해당 fixture의 명시적 합성 seam이며 운영 실행 증거가 아니다.
- root/runner 실제 OS16 PASS(8.05s), 로그 `/tmp/eom-gpu-batch-owner-os-20261024-r11.log`다.
  실제 nondumpable source owner의 rendezvous와 unavailable/ready 교환, sender/pidfd/local DAC,
  ACK 뒤 metadata 보존을 포함한다. r8의 socket timeout2건 및 r10의 proc ancestor2건 실패 로그는
  보존한다. r9는 nondumpable case 추가 전14 PASS였다. unit/systemd/source/GPU leaf는 합성으로,
  실제 fixed-unit sandbox·GPU 격리·그림/trainer 공존 PASS로 확대하지 않는다.
- API/Web·일반채팅·INDEX owner active, GPU0%/2MiB를 확인했다. 이번 source 검증 중 운영 release,
  device default, 계정/credential, 기존 실패 기록은 바꾸지 않았다.

P2_M_ROOT_OWNER_RENDEZVOUS=SOURCE_AND_OS_VERIFIED, CANONICAL_QUERY_REPLAY=DB_VERIFIED,
ACTUAL_SELECTED_CHILD_DISPATCH=PENDING, LIVE_GPU_BATCH=NOT_RUN,
GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU, GOAL=ACTIVE.

P2-M source commit `933466502dce27de3ef176a81d94eea04329ea3a`를 main에 push했다.
공식 API/platform build-only 및 RECORD PASS이며 산출물은
`/tmp/eom-api-build/933466502dce27de3ef176a81d94eea04329ea3a.KAQYI5/dist`다.
그3개 wheel을 `/tmp/eom-gpu-batch-root-wheel-2QBtiu9X`에 추출해 API Python `-I -B`, cwd `/`에서
새 root/control 진입점 등을 포함한17모듈을 import했다. dependency421개가 모두 추출 wheel에서
해결됐고 bootstrap member와 packaged schema pin도 일치했다. torch/transformers import는 없었다.
이 build-only 결과는 실제 service identity/sandbox/GPU 실행·운영 설치·activation 증거가 아니다.

## P2-N 기존 parent 계획과 실제 owner 실행 연결

별도 실행 tracker/queue/schema를 만들지 않고 P2-I parent admission/store, P2-M fixed root
rendezvous, P2-G 실제 child source/lease와 P2-K 결과 publication을 한 application use case로
연결한다. 정본은 기존 parent Job history와 canonical execution receipt이며 로컬 channel은
원 physical lifecycle 동안만 유지한다. child 준비/예약/완료는 QUERY/DOCUMENT의 기존 owner에
남기고 GPU READY 이후 확정된 route를 받아 실행 입력을 만들게 한다.

첫 allocation transaction만 원 dispatch를 소유한다. 이미 존재하는 parent는 같은 history를
반환하되 root를 시작하거나 현재 GPU 상태로 재선택하지 않는다. actual ROOT_READY/ROOT_BUSY에서
관측 hash와 route를 만들고 짧은 admitted SQL root에서 고정한다. source·input/binary IO·연산 동안
SQL root를 유지하지 않는다. CUDA run은 BOUND → staging → source CHECK → 검증 → ACK → 기존
receipt publisher 순서이며 ACK 뒤 current source/lease를 다시 확인한다. BUSY 경로는 원 CPU
route만 반환하고 아직 실행되지 않은 CPU 결과를 만들어내지 않는다.

주 접근은 indexed parent key와 bounded child 순서/원 control 메시지다. 시간/공간 O(children),
벡터는 기존 단일 버퍼를 공유한다. root grant와 실제 source 권한은 별개이며 어느 하나만으로
실행/성공을 허용하지 않는다. context 중단·관측 불명은 원 기록/dispatch marker를 보존한다.
자동 재시작·새 identity·failed→success·unknown→CPU fallback은 없다. 직접 SQL/소켓 처리를
각 runtime에 복사하는 대안 대신 기존 adapter와 공식 application owner를 조합한다.

P2-N 구현·검증:

- `CatalogEmbeddingBatchExecution.open`은 새 parent allocation의 commit을 확인한 뒤 실제 fixed
  root adapter를 호출한다. replay는 원 planning history만 돌려주며 새 dispatch를 하지 않는다.
  actual root READY/BUSY의 **전체 frame hash**와 시각으로 route를 기록하고 current source를
  재확인한다. BUSY는 CPU route만 허용하고 CPU 계산/완료를 대신하지 않는다.
- CUDA active handle은 한 번만 실행할 수 있다. exact child binding과 실제 authorization owner를
  확인한 뒤 원 input staging, root CHECK/완료, local result 검증, fresh source 검증/ACK, 기존
  canonical receipt publication을 순서대로 연결했다. context/결과 오류 뒤 handle 재사용도 거부한다.
  소켓은 ACK 뒤 닫을 수 있고 publisher는 현재 권한/lease와 terminal snapshot으로 재확인한다.
- guarded disposable PostgreSQL62 PASS(93.57s), 공식 cleanup PASS다. 신규 application12건과
  기존50건이며 로그 `/tmp/eom-gpu-batch-admission-20261024-r11.log`다. parent/Artifact SQL은
  실제로 실행했고 동시 두 caller의 한 dispatch 수렴, 미상 dispatch/Root 응답의 재실행 금지,
  late parent 거부, child 준비 중 중단, child 권한/결과 실패, CPU route replay 고정, 정확한
  receipt 발행을 확인했다. root IPC·unit·숫자·current IAM leaf는 명시적 합성 seam으로 실제
  GPU/sandbox/운영 admission 근거가 아니다.
- 첫 DB r10은 schema 재검증으로 값은 같지만 Python object가 달라진다는 fixture의 잘못된
  `is` 검사 때문에9 failed/50 passed였다. 객체 identity 대신 immutable value 일치로 수정하고
  원 marker DB에서 r11을 재실행한 뒤 공식 cleanup했다. 원 실패 로그는 보존한다.
- pure route7건과 dependency6건, 총13 PASS(13.84s)다. 최초 unit의2건은 wire에 datetime 객체를
  넣은 새 adapter 오류를 발견했다. UTC JSON 문자열로 직렬화한 뒤 재검증했으며 schema나
  hash 검증을 완화하지 않았다. production1모듈 strict mypy, Python3개 Ruff/format/diff PASS다.
- 실제 selected QUERY/DOCUMENT child 준비/예약과 설치 runtime composition은 다음 단계다.
  이번 application 연결만으로 새로운 GPU 정책을 활성화하거나 기존 CPU 검색을 바꾸지 않았다.

P2_N_FINITE_OWNER_APPLICATION=SOURCE_AND_DB_VERIFIED,
ACTUAL_SELECTED_CHILD_DISPATCH=PENDING, LIVE_GPU_BATCH=NOT_RUN,
GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU, GOAL=ACTIVE.

P2-N source commit `99186fdc080adf58a8cbb7013aa953eca5b0f640`를 main에 push했다.
공식 API/platform build-only 및 wheel RECORD PASS이며 산출물은
`/tmp/eom-api-build/99186fdc080adf58a8cbb7013aa953eca5b0f640.v8tZFH/dist`다.
3개 wheel을 `/tmp/eom-gpu-batch-application-wheel-dSIwNM3r`에 추출한 API Python `-I -B`, cwd `/`
검사에서 application을 포함한18모듈과 dependency422개가 모두 wheel에서 import됐고 packaged
schema/bootstrap도 확인했다. 모델 import·실제 실행·운영 설치·activation은 없다.
21:35 UTC milestone Slack `devreport_903c66f694f24b54aa466e7082f6e4c0` 전송도 성공했다.
그 보고는 source/DB/OS와 실제 GPU/운영 gate를 구분하며 GPU goal을 완료로 보고하지 않았다.

## P2-O 선택된 QUERY의 기존 Workflow 실행 결합

CUDA child는 별도 queue/state machine이 아니라 기존 atomic QUERY/START, `WorkflowRunner`,
command claim/heartbeat, native checkpoint1.2와 canonical completion을 사용한다. 원 parent
request hash와 child ordinal에서 한 authoritative idempotency key를 만들고 실제 Workflow의
immutable key와 대조한다. 다른 parent가 이미 할당된 QUERY를 자기 묶음으로 다시 계산할 수
없게 native Job 생성 전에 관계를 고정한다. key는 authority가 아니며 actual owner/source/lease
검증은 그대로다. 기존 CPU executor/handoff의 CUDA 거부도 유지한다.

같은 Orchestrator 프로세스 안의 유한 child 실행들은 bounded map/Condition으로 입력 준비만
모은다. 이것은 worker 간 통신, 새 persistent queue, 상시 모델 cache가 아니다. 자식들은 기존
Runner의 독립 command/SQL root/heartbeat를 유지하며, 마지막 준비자가 P2-N의 원 root channel을
한 번만 구동한다. 다른 자식은 SQL root 없이 같은 immutable 결과를 기다린다. source callback은
각 child의 명시적 request/workflow/lease를 담은 기존 native transaction을 사용한다. 다른 스레드의
ContextVar를 현재 child 권한으로 오인하지 않는다.

정본은 기존 parent/child Job과 canonical batch receipt·child Artifact다. 큰 input은 원 batch
workspace에 한 번 staging한다. 결과의 각 QUERY 범위는 기존 Artifact publisher가 요구하는
보호된 child publication workspace에서만 materialize한다. 이는 canonical 복사본이 아니라
명시적인 local→commit 경계다. memoryview는 그 경계까지 한 vector buffer를 공유한다.

주 접근은 source revision→ordinal map, Workflow/Job indexed lookup, 최대32 child의 ordered
tuple이다. 시간·공간 O(n) bounded이며 DB schema/index/migration과 새 dependency는 없다.
중복 ordinal, 다른 parent/Graph/policy/index profile, 기한 경과나 중단은 fail-closed한다. 부분·미상
실행을 CPU로 재분류하지 않고 실패 이력을 보존한다. legacy CPU executor에 CUDA flag를 추가하거나
Runner claim/완료 로직을 복사하는 대안 대신, 기존 executor port에 유한 CUDA 구현을 결합한다.

P2-O 구현·검증:

- `start_batch_reference_queries`는 기존 원자적 QUERY/START를 호출하며, 실제 actor와 원 parent의
  child key로 새 logical query intent를 만든다. supplied context의 source/index/Graph 핀은 그대로다.
  generic Workflow equivalence를 완화하거나 다른 parent의 기존 QUERY를 덮어쓰지 않는다.
  `drive_batch_reference_queries`는 기존 Runner의 claim/heartbeat/완료와 canonical completed-read를
  재사용한다. child 준비와 root callback은 각 child의 명시적 transaction/lease를 유지한다.
- 실제 disposable PostgreSQL의 두 QUERY Workflow/step/command/lease/native checkpoint/Artifact를
  끝까지 연결했다. 저장 직전·직후 네 interruption은 원 command의 만료/재claim 경계를 통해
  같은 native Job/producer/checkpoint로 복구했다. 한 원 batch 계산과 canonical replay를 확인했고
  기존 FAILED 이력은 변경하지 않았다. current IAM/source leaf와 root/numerical leaf는 이 fixture의
  명시적 합성 seam이다. 실제 GPU·운영 권한·sandbox 검증이라고 보고하지 않는다.
- 첫 DB r12는5 failed/1 passed(47.76s)였다. 서로 다른 시험 parent들이 같은 fixture context ID를
  재사용하여, 기존 Workflow equivalence가 올바르게 이전 QUERY를 반환한 것이 원인이었다.
  parent/ordinal에 귀속된 새 query intent를 기존 logical-ID 함수로 만들도록 정리했다. 같은 guarded
  DB의 r13은6 PASS(168.69s), 새 disposable DB의 기존 회귀 포함 r14는68 PASS(260.41s)이며 두 번
  모두 공식 cleanup PASS다. `/tmp/eom-gpu-batch-admission-20261024-r12.log`부터 r14까지 보존한다.
- 계산 deadline180초는 유지한다. 계산이 끝난 원 결과의 ACK/canonical metadata 정리는 기존
  root unit의240초 범위 안에서 기다릴 수 있지만 새 입력/권한/GPU grant를 연장하지 않는다.
  완료된 같은 operation-local material만 원 결과를 재사용한다. cold-process 재시작과 아직 없는
  DOCUMENT 실행 연결까지 이 in-process 복구 시험으로 검증했다고 확대하지 않는다.
- 설치 검토에서 이전 build-only wheel의 bootstrap `.data` member가 실제 numerical successor의
  strict namespace/source-payload 검증과 맞지 않음을 발견했다. 그 후보는 운영 설치하지 않았다.
  installer/audit 예외를 추가하지 않고 stdlib bootstrap의 정본을 Python package 안의
  `eom_catalog_service.embedding_owner_bootstrap`로 옮겼다. owner installer가 검증한 wheel member를
  기존 release의 `prepare_native_index.py` 위치로만 materialize한다. unit/config ABI와 옛 release는
  유지하며 새 dependency/schema/migration은 없다. 원 scripts 파일은 Git history로 복구 가능하다.
- source→wheel byte parity, namespace-only wheel, offline installed imports와 기존 root/QUERY/CUDA/
  private successor/dependency 검사를 포함해278 PASS, opt-in protected old-pip 검사2 SKIPPED다
  (45.66s). 로그 `/tmp/eom-gpu-batch-packaging-20261024-r16.log`. 앞선 검사의 종료 출력이 인계에서
  보존되지 않아 실행 중 프로세스가 없음을 확인한 뒤 이 비수치 검사를 재실행했다.
- QUERY context/child material/finite group와 기존 CPU executor/completion/launch preparation/
  preparation 회귀102 PASS(114.38s)다. 로그 `/tmp/eom-gpu-batch-query-20261024-r17.log`.
  packaging278건 및 DB68건과 실행 환경/범위를 구분하며 중복 합산한 총 PASS 수로 보고하지 않는다.
- scoped Python17개 Ruff/format, production7모듈 strict mypy, installer shell syntax/diff PASS다.
  운영 API/Web/일반 채팅/INDEX owner는 active이며 이번 source/DB 검증에서 실제 모델 호출,
  numerical prefix 교체, 서비스 activation, credential 변경은 없었다.

P2_O_QUERY_RUNNER_FLOW=SOURCE_AND_DB_VERIFIED,
DOCUMENT_BATCH_COMPOSITION=PENDING, INSTALLED_BATCH_COMPOSITION=PENDING,
LIVE_GPU_BATCH=NOT_RUN, GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU, GOAL=ACTIVE.

P2-O source commit `56e545c4978db96d94a134f4c3d27fd29109f8f8`를 main에 push했다.
공식 API/platform build-only/RECORD PASS이며 산출물은
`/tmp/eom-api-build/56e545c4978db96d94a134f4c3d27fd29109f8f8.EhuwNA/dist`다.
API Python `-I -B`, cwd `/`에서20모듈/dependency470개를 해당3개 wheel에서 import했고
namespace bootstrap/schema pin 일치와 모델 import 없음도 확인했다.
추출 위치는 `/tmp/eom-gpu-query-wheel-S3rs43qc`다.

이어 이 owner release만 공식 보호된 installer로 root-owned immutable 경로
`/opt/eom/embedding-owner-releases/56e545c4978db96d94a134f4c3d27fd29109f8f8`에 준비했다.
platform rawSHA `9581f722436c083c8a715c1a25370d72effb7100e296d4bae165e72640394b25`,
API contracts rawSHA `49626770061db0c5e9dc4eb74f6800318c41d0fd60996f4db93b9387bd3127ed`다.
wheel RECORD와 새 namespace bootstrap의 기존 sibling 위치 materialization PASS,
그 설치본의20모듈/dependency470 import도 PASS다. 로그
`/tmp/eom-gpu-batch-owner-stage-20261024.log`, exit0.

보호된 installer 자체는 기존 rawSHA `559ada516fe9d46f57926aad70699e81deba5f1a18b4e25e3f6e6bcdf1384b71`
에서 검토한 rawSHA `a603fea5ac3e1846e3975a15333f688935e75596e35fe1a94949f4f2c741be12`로
원자적으로 갱신했고 원본은 같은 root-owned 디렉터리의 `install_owner_release.sh.pre-56e545c4`에
보존했다. 변경은 검증된 package bootstrap의 materialization뿐이며 구형 wheel 지원도 유지한다.

**이것은 owner 코드 준비이지 실제 운영 활성화가 아니다.** API/platform의 active1a4e3c67,
Web f15e66b8, private QUERY2eef9b20와 CPU 기본값, 수치 interpreter/prefix/모델/Graph/계정·인증은
그대로다. 실제 fixed-unit sandbox·CUDA batch numerical canary·DOCUMENT 결합·CPU busy fallback·
양쪽 인덱스 coverage·이미지/trainer 공존 및 최종 activation/rollback은 아직 남았다.
따라서 이 source/staging commit은 사용자가 요청한 **GPU 목표 완료 후 리뷰 checkpoint가 아니다**.
22:28 UTC milestone Slack `devreport_a0c5c951587a47dc8edd0e5ce8b4fe32`도 SENT/HTTP200이다.

## P2-P 설치된 CUDA 수치 코드의 후속 준비

P2-O owner 설치만으로 고정 numerical leaf가 새 batch entry를 import할 수는 없다. 다음 경계는
기존 `install_index_runtime.sh publish-private-successor CUDA_INDEX_FP32`다. 그 공식 installer와
accepted OLD interpreter의 byte/host audit를 재사용하며 runtime admission/activation을 대신하지
않는다. 정본은 검증한56e545c4 source archive/wheel과 기존 GPU lease archive다. 기존 Conda/
공개 numerical package·모델을 재설치하거나 CPU/private QUERY prefix를 바꾸지 않는다.

주 접근은 immutable archive hash→고정 경로 lookup, source/wheel payload의 단회 선형 검증과
보호된 prefix 복사다. 새 DB/table/queue/schema/dependency는 없다. 기존 설치 입력1.3에 새 SDK
source/wheel 및 audit bootstrap byte pin만 반영한다. host/CUDA extension/Conda/public package
pins와 원 created_at/history는 보존하며, 현재 host가 그 핀과 다르면 preflight에서 중단한다.
새 SDK를 실행하기 전 accepted OLD의 비실행 source→wheel/prefix 검사를 통과해야 한다.

현재 CUDA interpreter 사용자와 실제 GPU 계산이 없는 시점에만 수행한다. installer의 기존
root-private lock/quarantine/copy/audit와 predecessor backup을 사용한다. 실패 후에는 phase와
실제 prefix 상태부터 확인하고 맹목적으로 재실행하지 않는다. 성공해도 새 configuration/
installed proof/probe/service selection이 없으면 GPU 실행은 여전히 불가하다. rollback 대상은
보존한 numerical predecessor와 명시적 config 선택이며 기존 결과/FAILED 기록은 지우지 않는다.
검증을 생략한 pip inplace 교체나 CPU/CUDA space 재사용은 대안으로 채택하지 않는다.

새 prefix의 자격 증거는 새 configuration revision에 귀속시킨다. 기존 운영 one-off의 순수
revision 투영 규칙을 `derive_native_configuration_revision`으로 재사용한다. 기존 schema1.0–1.3을
그대로 파싱하고 독립 raw/semantic pin·logical ID·원 revision을 확인한 뒤 revision과 self-hash만
바꾼다. 시간/공간 O(작은 config bytes), 새 DB/프로토콜/permission 또는 publication side effect는
없다. 파일 보호·현재 prefix/host·실제 no-forward probe/same-live seal은 기존 root owner가 따로
검증한다. 이 함수가 성공했다고 admission을 발급하지 않는다. 모델/장치/host/resource 핀까지
같이 바꾸는 범용 patch API는 만들지 않고, 원 고정 one-off를 매번 복사하는 대안을 줄인다.

P2-P source 체크포인트:

- 순수 configuration revision 투영과 기존 native config/host/CUDA 계약222 PASS(9.99s),
  wheel payload/import·dependency7 PASS(17.91s)다. 로그는 각각
  `/tmp/eom-gpu-native-configuration-revision-20261024.log`,
  `/tmp/eom-gpu-native-revision-packaging-20261024.log`다. production1모듈 strict mypy,
  scoped Python2개 Ruff/format와 diff PASS다. 첫 Ruff import 정렬 지적은 formatter로 수정했고
  최종 lint는 PASS다. 이 pure helper는 config를 발급/활성화하지 않는다.
- 실제 CPU root-controller interpreter로 준비한56e545c4 owner의20모듈/dependency470개를
  `-I -B`, cwd `/`에서 import했다. 모델 import와 실행은 없었으며 API Python만의 결과와
  구분한다. 실제 service identity/sandbox의 실행 성공이라고 확대하지 않는다.
- 최초 numerical 입력 생성에서 전체 API source archive70,144,000 bytes가 기존64MiB
  제한에 걸렸다. 제한을 늘리지 않고, 같은56e545c4의 선언된 package roots·원 helper/lock을
  포함하는 별도 Git source archive22,056,960 bytes를 준비했다. 이 archive의 rawSHA는
  `ecf437c78dc888b48f25a6ddc2ac31a2a7bc59070d45e6937239125e76766882`다.
  원 API source archive/설치 release는 바꾸지 않았다.
- 기존 input1.3을 재사용한 새 audit input rawSHA는
  `b1e8636b79979acfbfdd7fef901d0a2f7a4e699c63dcf110a2147278bd1553ec`다.
  CUDA predecessor tree는 `b1abe7a028298666d590803db28c8960ef18bfa3d750c62eb291fa8e9b047c34`로
  공식 fingerprint했다. 이 값들은 source bytes/설치 계획의 핀이지 GPU 실행 권한이 아니다.
- 첫 설치 호출은 wheelhouse 인수 누락으로 NOT_STAGED에서 거부됐다. r2는 필수 CUDA cache
  mount가 없는 일반 host namespace라 BEFORE_HOST_BYTES_PREFLIGHT에서 거부됐다. 원 prefix를
  교체하지 않았으며 각 실패 로그를 보존한다. protected/cache-bound r3도 계산/설치 전 짧게
  종료됐다. 그 단계의 GPU process 검사는 device를 숨긴 비실행 sandbox 밖으로 옮겼다.
- cache-bound r4는 실제 HOST_BYTES_PREFLIGHT_PASS_NOT_ADMITTED 뒤 최초 archive retention에서
  거부됐다. 공식 API build의 상위 `/tmp/eom-api-build`가775인 반면 설치 입력은 바로 아래의
  전용700 root를 요구한다는 것을 원 `_index_source`의 read-only 재현으로 확인했다.
  package ZIP32/필수 source member는 양쪽 archive 모두 PASS였다. 공유 build의 권한을 바꾸거나
  검증을 완화하지 않고 전용700 input workspace에 같은 wheel bytes를 materialize했다.
- 실패한 r4 creator의 empty/uncommitted archive reservation은 실제 원 unit FAILED/MainPID0,
  root700·빈 디렉터리를 확인한 뒤 `.failed-empty-9581f722-gpu-batch-20261024-r4`로 이동해
  보존했다. bytes/committed archive/Artifact 삭제는 없다. 네 입력의 공식 source DAC preflight는
  모두 PASS다. r5는 보호된 새 root operation으로 시작했으며 원 실패를 성공으로 바꾸지 않았다.
  설치 안의 `fuser`는 네트워크 socket 경고를 출력했다. 그것만으로 전체 process 부재를
  증명했다고 간주하지 않으며 별도 fixed CUDA process/unit 및 GPU 관찰과 구분한다.

P2_P_NATIVE_CONFIGURATION_REVISION=SOURCE_VERIFIED,
CUDA_SUCCESSOR_INSTALLATION=IN_PROGRESS, ACTUAL_GPU_BATCH=NOT_RUN,
GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU, GOAL=ACTIVE.

### P2-P 실제 CUDA prefix byte audit 완료 — 2026-10-24 22:52 UTC

r5 `eom-gpu-batch-numeric-stage-56e545c4-r5.service`가 원 작업에서 exit0/result success로
종료했다. 실제 elapsed252.013초, CPU212.248초, cgroup memory peak2GiB다. 이는 설치/audit
리소스 관찰이지 모델 throughput/VRAM 측정이 아니다. 공식 root-private operation은
`/opt/eom/.embedding-index-install-CIJ3z7uq`이며 로그는
`/tmp/eom-gpu-batch-numeric-install-20261024-r5.log`다.

- 새 CUDA numerical SDK는 **56e545c4**다. accepted OLD가 source/wheel/installed-prefix의
  전체 bytes/host closure를 검증했으며 상태는 **BYTE_AUDITED_NOT_ADMITTED / NOT_PROBED**다.
  원 interpreter로 새 numerical instruction·model/tokenizer/forward는 실행하지 않았다.
  새 `embedding_gpu_batch_entry.py`의 실제 설치 hash
  `da1c1ef262ff2a52adfdd0b9dc726f1cc6df31c1aef2d51478a54e5f6edd3909`가 원 source와 일치한다.
- 이전 실제 CUDA prefix는
  `/opt/eom/conda/envs/.embedding-index-prepublication-CUDA_INDEX_FP32-.embedding-index-install-CIJ3z7uq`
  에 root700으로 보존했다. 이전 config/receipt/benchmark 결과·failed unit은 수정하지 않았다.
  지금 old config/receipt를 새 whole-prefix의 승인처럼 사용하지 않는다.
- canonical candidate inventory rawSHA는
  `361cca0700c5f0cb9ff1319260b51618b9c7c61f6b5cb335bae800b1078df356`, semantic SHA는
  `de96753229b541b81b4d6527e1c33e2aa44dde1ad72b50dba4781e1d5dcc2c59`다.
  9,014,639 bytes/31,871 entries이며 실제 guarded root metadata reader가 schema와 원 audit input
  hash를 대조했다. root inspection 첫 시도는 stat 전체 비교가 read의 atime 변화까지 포함해
  거부됐다. 읽기 자체로 변하는 atime을 immutable epoch에서 제외하고 기존 file reader와 같은
  dev/inode/UID/GID/mode/nlink/size/mtime/ctime을 확인한 r2가 PASS다. 그 실패도 보존한다.
  별도 non-sandbox host `fuser`의 무경고 exit1, fixed CUDA process/unit 없음과 GPU0%/2MiB를
  확인했다. read-only 결과는 `/tmp/eom-gpu-batch-audit-summary-20261024-r2.json`,
  `/tmp/eom-gpu-batch-post-stage-readiness-20261024.log`다. 이는 현재 quiescence이며 이전
  socket 경고가 난 observation을 소급 PASS로 바꾸지 않는다.
- 다음 no-forward 자격 검증은 원 bundle/수치 proof/runtime
  `d0887315a3b7afd0d86dceb10228c157c72f7161dbdbb01a582d97be1d8c7560`을 유지한
  새 native configuration revision과 same-live probe/seal에 귀속해야 한다. 기존 logical
  config3e98/948f의 rawSHA `7d8aef012c9e957f41ad888eadc6e214568e01aae490aa134851dcdb22cbe087`,
  semantic SHA `e070fe5e3b207175f4e4aec85de3b2e085f774cf843b06d0d510ee645f63d32b`를 실제로 읽었다.
  새 revision/probe는 아직 발행·시작하지 않았다. 별도 실제 batch 계산/현재 source/lease/권한은
  no-forward probe 성공으로 대신하지 않는다.

순수 revision helper의 source commit **c34ef31982e8d80fc835fac7ed0c4f9ae73aefcf**를 main에
push했다. 공식 API/platform build-only/RECORD PASS이며 경로는
`/tmp/eom-api-build/c34ef31982e8d80fc835fac7ed0c4f9ae73aefcf.oEjfTp/dist`다.
추출 wheel은 `/tmp/eom-gpu-native-revision-wheel-h01LmrC8`에서 API Python `-I -B`, cwd `/`의
21모듈/dependency471 import PASS다. 같은 owner를 공식 installer로 root-owned immutable
`/opt/eom/embedding-owner-releases/c34ef31982e8d80fc835fac7ed0c4f9ae73aefcf`에 **준비만** 했으며
실제 CPU root-controller Python에서도21/471 import PASS/모델 import 없음이다. platform rawSHA
`c03e2e2366a1f1524f499edbf207b4ce15f64537ffcbff77d09cdc16513dbf27`, contracts rawSHA
`ee0fe24ed2ef17f4210375e24092ff798ffa092346a5aa97ac4ed27b6675ed53`다. 로그는
`/tmp/eom-gpu-native-revision-owner-stage-20261024-r2.log`, exit0다.

이 owner candidate와 CUDA numerical SDK56e545c4는 서로 다른 역할의 명시적 핀이다.
현재 API/Web/private QUERY·CPU INDEX의 active selection은 그대로이고 다섯 서비스가 active다.
새 config/admission, 실제 GPU batch·CPU fallback, DOCUMENT 연동과 장치별 index coverage,
image/trainer 공존·처리량·GPU 기본값 activation/rollback은 여전히 남았다.

P2_P_CUDA_PREFIX=BYTE_AUDITED_NOT_ADMITTED, P2_P_OWNER_CANDIDATE=STAGED_NOT_ACTIVE,
ACTUAL_GPU_BATCH=NOT_RUN, GPU_PREFERRED_ACTIVE=NO, CURRENT_DEFAULT=CPU, GOAL=ACTIVE.

## P2-Q 실제 native CUDA 자격 검증

byte-audited numerical56e545c4와 immutable owner c34ef319를 명시적으로 구분해 사용한다.
기존 config1.3/probe1.0/receipt2.1 schema·고정 native probe unit·두 ACK/live OS 관측·same-live
seal/read-back/retirement를 그대로 재사용한다. 새 configuration은 원3e98/948f의 독립 raw/semantic
pin으로부터 순수 revision 함수로 만들며 수치/모델/host/resource/schema 핀은 바꾸지 않는다.
정본은 protected root-local config/설치 증거와 원 prefix inventory다. 준비된 config만으로 GPU
source 권한이나 실행 grant를 얻지 않는다. 별도 queue/table/DB write나 새 worker protocol은 없다.

주 접근은 고정 revision/hash lookup과 한 유한 unit 관측이다. 작은 config 값 외 prefix/모델을
재복사하지 않는다. root owner는 보호된 wheel의 실제 installed bytes를 확인한 뒤 SDK를 import하고
원 prefix publication lock을 유지한다. probe는 새 고정 execution identity로 한 번만 실행한다.
실패/미상 시 원 unit/lease/proof를 보존하고 실제 상태를 확인하며 자동으로 새 unit을 실행하지 않는다.
기존 성공 probe JSON을 새 설치의 증명으로 재사용하거나 old FAILED를 고치지 않는다. 성공해도
모델/tokenizer/forward0의 설치 자격만 확인하며, batch source/권한·계산·CPU fallback·운영 activation은
별도 gate다. 필요 bootstrap은 이미 검증된 기존 root operation을 pin 갱신해 사용하고 원본은 보존한다.

## P2-R 고정 GPU batch unit 준비와 실제 물리 경계

기존 schema-first Root/owner/worker adapter를 운영 고정 unit으로 설치하되 enable/default/claim은
하지 않는다. 실제 CPU selection977df5…와 새 CUDA config2c3b/receiptcee52e…/bundle의 exact profile로
INDEX/QUERY policy 후보를 만든다. 합성 CPU profile이나 가짜 admission을 정책에 넣지 않는다.
기존 closed native backend-env codec을 사용하며 CPU/CUDA space는8a2f…/39bc…로 별개다.

정본은 보호된 config/설치 증거 및 원 verified wheel이다. root policy 파일은 명시적 실행 입력
materialization이며 아직 Catalog에 released/activated된 source policy나 정본 parent Job이 아니다.
실제 Source/Catalog/Artifact 경계는 계속 필요하다. 고정 unit의 세 파일/Polkit49와 새 폴더/환경만
준비한다. 기존 파일은 덮어쓰지 않고 identity/소유/권한을 확인한다. O(고정 파일 수)이며 새 DB,
service actor, queue나 Worker sudo/group grant는 없다. 실제 hardware-only READY/BUSY/중단 검사는
원 controlled unit과 원 actor UID로 수행하고 source/교육 품질/최종 GPU 배포 PASS로 확대하지 않는다.
오류는 원 unit/lease/record를 보존해 조사한다. 이 stage의 rollback은 아직 사용하지 않는 새 unit/
selection의 비활성 유지이며 기존 CPU 서비스·인덱스·실패 이력은 그대로다.

### P2-Q 실제 결과와 P2-R 배포 전 발견

2026-10-24 UTC에 native CUDA no-forward 자격 검증을 실제로 완료했다. config logical3e98의
새 revision2c3bb102308440b18f7887939aeeaa3c는 rawSHA
`ebf0f0be479fde046d440759fe7231095998d0ff6d320b61afb6888e188f443c`, semanticSHA
`9144e66d7eaaa5339b97ffe6a31e00d87cf95019c2f32f1b67f4b5c715788fd0`다. 원 수치 runtime
`d0887315a3b7afd0d86dceb10228c157c72f7161dbdbb01a582d97be1d8c7560` 및 model/resource 핀은
불변이며 새 receipt rawSHA는
`cee52e34ba376fb1f4fb7c16ca2d52a3b873c03dd290c63d996e16e5d8ea9917`다.

원 probe execution8250f571af28416eb239c323495b8c5b는 READY ACK23:07:38.804099 UTC,
FINAL ACK23:08:34.516842 UTC, terminal23:08:58.574080 UTC로 종료했다. same-live seal,
독립 root metadata read-back, 원 성공 unit retirement 및 PID1 FDSTORE release PASS다.
root controller exit0/101.214초, native MainPID0/ExecMainStatus0/NFileDescriptorStore0이며
GPU는0%/2MiB로 반환됐다. model/tokenizer/forward0, CUDA init1/synchronize1이다.
로그는 `/tmp/eom-gpu-batch-native-qualification-20261024.log`, 보호된 요약은
`/var/lib/eom-gpu-batch-qualification-20261024/native-probe/summary.json`다.
이는 실제 numerical batch 실행이나 현재 Source/IAM·운영 default의 PASS가 아니다.

고정 root batch unit 설치 전에 잘못된 `SupplementaryGroups=eom-workflow-runner`를 발견했다.
실제 trusted application 계정은 UID990/primary GID1000(`eom`)이며 같은 이름의 Unix group은
없다. 아직 설치/시작하지 않은 후보의 설정 오류이지 실패한 운영 unit 재현이라고 주장하지 않는다.
root peer UID/GID0과 기존 capability 제한은 유지하고 root supplementary group만 실제 socket
GID1000의 `eom`으로 지정한다. workers나 기존 계정·그룹은 변경하지 않는다. 원 dispatch adapter에서
고정 group의 존재 및 actual owner primary GID 일치를 **dispatch marker 소비 전** 확인한다.
누락/불일치 회귀는 systemctl 실행과 marker 생성을 모두 막는다. 고정 unit hash는 새 bytes와 함께
갱신하며 별도 schema/DB/queue/worker protocol은 바꾸지 않는다. 이 변경은 root owner SDK만
후속 release로 준비한다. 이미 검증한 numericalSDK56e545c4/config2c3b/receipt를 재설치하지 않는다.

실제 CPU selection977df5…로 만든 INDEX/QUERY physical policy 후보의 rawSHA는 각각
`bc340fc04659d1c57cb7ea3c5f4a62815ddd2c240deb978e28867d071d57c4d0`,
`df44e6bf2c841338a0e302ce243ebe60e7a4195d647ec9c0ac05c1018b8d3727`이다.
CPU space8a2fcad6…/CUDA space39bc2c31…는 별개이며 policy는 아직 canonical source authority나
운영 released selection이 아니다. CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO,
ACTUAL_GPU_BATCH=NOT_RUN, GOAL=ACTIVE를 유지한다.

그룹 수정 집중 unit46 PASS/12.06초, strict mypy1 PASS, Ruff/lint/format 및 diff-check PASS다.
실제 root/runner UID·소켓/DAC·고정 그룹 조회의 opt-in 격리 suite17 PASS/8.18초
(`/tmp/eom-gpu-batch-owner-os-20261024-r12.log`, exit0), dependency/resource packaging16
PASS/32.87초다. actual unit/numerical/IAM/DB 검증을 이 테스트로 대체하지 않는다.

### P2-S 실제 systemd255 OpenFile 경계와 좁은 후속 수정

그룹 수정20d0b910 owner를 별도 immutable release로 준비하고 고정 batch unit을 설치했다.
기존 CPU selection/API/Web은 바꾸지 않았다. 실제 hardware-only pre-grant 요청
`embeddingallocation_ba055c2b768140c2ba832d20af625100`은 PID1이 OpenFile의 `%i`를 문자 그대로
취급해 status202/FDS로 종료했다. 모델/GRANT/Source binding은0이며 GPU0%/2MiB다.
실패 root/socket 기록은 보존한다. 이는 source unit 검사만으로 놓친 실제 OS 호환 결함이다.
systemd255의 [공식 parser](https://github.com/systemd/systemd/blob/v255/src/core/load-fragment.c)는
OpenFile을 parse만 하고 instance specifier를 확장하지 않는다. OS 업그레이드나 worker 권한 확대,
검증된 CUDA prefix 재설치로 우회하지 않는다.

책임은 기존 root unit/handoff adapter에 둔다. PID1의 `RuntimeDirectory`가 생성한 **해당 원
instance 전용** root0700 drop-in 디렉터리에 absolute allocation path만 담은0444 파일을 한 번
생성한다. root controller는 원 고정 template에 대한 이 exact drop-in 하나만 허용하고 reload 후
actual DropInPaths와 bytes/hash/inode를 검사한다. 임의 property/path/명령/추가 drop-in은 거부한다.
정본 allocation.json과 inherited original inode/FD 검증, CUDA56 entry/ABI 및 원 shared GPU lease는
그대로다. payload 복사나 새 worker protocol/schema/queue/DB는 없다.

접근은 instance→고정 path lookup/상수 크기 파일1개(O(1))다. canonical identity는 기존 allocation
ID/hash와 immutable protected template이며 파일은 명시적 실행 materialization이다. 원 root 단일
dispatch 이전에 exclusive create/fsync/reload를 수행한다. 이미 있는/부분 파일은 덮거나 재전송하지
않고 reconciliation 대상으로 보존한다. `RuntimeDirectoryPreserve=yes`로 종료 후 증거를 유지한다.
root sandbox의 쓰기는 해당 instance 디렉터리에만 열고 workers에게 systemd/NAS/DB 권한은 주지
않는다. 단순 `%i` OpenFile은 실제로 실패했고, 전체 unit 생성·전역 경로/심볼릭 링크·임의 drop-in
허용은 더 넓은 권한/경합을 만들므로 선택하지 않는다. 기존 failed 이력은 고치지 않는다.

후속 source 회귀366 PASS/66.70초(이미지 GPU lifetime 및 shared terminal/policy/dependency/
package resource 포함), exact descriptor 생성·중복·동시성12 PASS/0.98초, actual root/runner
filesystem/peer18 PASS/8.30초다. descriptor 테스트의 PID1 reload는 synthetic이고 actual Unix
file identity/DAC는 별도 privileged gate다. strict mypy6 source PASS, Ruff 및 diff-check PASS다.
로그는 `/tmp/eom-gpu-batch-systemd-compat-tests-20261024-r2.log`,
`/tmp/eom-gpu-batch-owner-os-20261024-r13.log`다. source PASS를 다음 실제 고정 unit 실행으로
확인하기 전에는 hardware READY·CPU fallback·batch computation PASS로 표시하지 않는다.

후속9d34335a owner의 실제 r2는 PID1 RuntimeDirectory/absolute descriptor materialization과
reload까지 통과했다. 실제 `OpenFile` read-back은 원0a72f542…/allocation.json의 absolute path다.
다만 native dispatch marker가 생성되기 전에 재사용한 CPU 관측 adapter가 모든 drop-in을 거부해
중단됐다. 원 root failed 기록과 root0444 descriptor/빈 input은 보존했으며 numerical unit/model/
GRANT는 시작하지 않았다. fixture가 관측 adapter 전체를 대체해 이 아래 parser 규칙을 가렸으므로,
후속 회귀에서는 실제 공통 parser까지 이어 검증한다.

공통 bounded read-only projection을 `inspect_fixed_unit`으로 노출하고 기존 `inspect_cpu_unit`은
계속 empty allow-list로만 호출한다. GPU batch 전용 adapter만 원 instance의 exact descriptor
하나를 선언한다. CPU/기존 GPU 경계를 전역적으로 느슨하게 바꾸지 않는다. 실제 현재 PID1의
0a72… unit에 read-only 적용해 batch projection PASS와 기존 CPU 거부 guard PASS를 동시에
확인했다. 새 unit/모델/DB 작업·권한 부여는 이 read-only 확인에 없었다. CUDA56/config2c3b/receipt는
다시 만들지 않는다.

공통 parser/CPU 거부·batch 전용 projection/원 dispatch·중단·retirement/dependency 회귀195
PASS/34.28초, strict mypy5 source PASS, Ruff PASS다. 결과는
`/tmp/eom-gpu-batch-unit-parser-tests-20261024-r3.log`다. 실제 GPU READY는 아직 다음 gate다.

933a644b owner의 실제 r3(c6b4791b…)는 공통 관측/dispatch/OpenFile을 통과하고 native unit을
시작했다. PID1 namespace 구성에서 현재 사용하지 않는 다른 CUDA-index 임시 디렉터리가 없어서
status226/NAMESPACE로 거부됐다. Python/model/GRANT는 시작하지 않았고 원 실패 기록은 유지했다.
다른 서비스의 ephemeral staging 경로는 `InaccessiblePaths=-…`로 선언해 **존재하면 차단**하되
존재 자체를 이 unit의 의존성으로 만들지 않는다. 원 batch runtime 경로는 여전히 필수 차단이다.
다른 runtime을 설치하거나 디렉터리를 임의로 생성하지 않는다. parent들의 기존 root/owner DAC와
worker UID/group 분리도 그대로 유지한다. 고정 unit raw SHA와 root 관측 pin을 함께 갱신한다.
수치 SDK/config/receipt나 Source/IAM/DB는 변경하지 않는다.

optional namespace/fixed unit bytes·descriptor·OS observation/entry 회귀95 PASS/12.32초,
Ruff PASS다(`/tmp/eom-gpu-batch-optional-namespace-tests-20261024.log`). 다음 actual unit gate는
기존 r3를 재시작하지 않고 새 진단 identity를 사용하며 원 실패는 보존한다.

56d868cc actual r4(9acb8703…)는 파일/namespace/실제 Python bootstrap까지 진입했지만 READY 전
종료했다. 원 단일 진단7b216813…에서는 추적/주입/추론 없이 kernel FD/선택된 activation 변수3개만
관측했다. 초기 MainPID의 activation 환경이 아직 비어 있다가 정상 LISTEN_FDS2/두 descriptor
이름으로 정착하고, 원 allocation FD가1096 bytes를 실제로 읽은 것을 확인했다. 원 결과/vector/
input은 비어 있고 모델/Source grant는0이다. 원 로그와 failed unit은 보존했다.

PID1이 MainPID를 공개하는 시점은 native Python exec/권한 전환보다 빠르다. root controller는
그 PID를 곧바로 native UID/birth proof로 사용하지 않고, 원 qualified interpreter의 실제
device/inode가 관측될 때까지 **알려진 systemd executor 전환만** 최대3초, 원 allocation deadline
이내에서 기다린다. 다른 executable/권한 오류는 즉시 거부하고 timeout/불명은 fallback하지 않는다.
이는 실행/claim 재시도나 새 timeout 예산이 아니라 최초 exec readiness의 추가 검사다. 그 이후 기존
실제 UID/GID/cgroup/capability 및 READY/grant 검사는 모두 그대로 필요하다. 실제 r4 실패의 모든
원인이 이 race라고 확정하지 않으며, 다음 installed fixed-unit gate로 확인한다. numerical prefix나
worker protocol은 수정하지 않는다.

startup executable settling/거부 및 기존 controller/descriptor/lifetime 회귀76 PASS/24.76초,
strict mypy1 PASS, Ruff PASS다(`/tmp/eom-gpu-batch-startup-exec-tests-20261025-r2.log`).

### P2-T 실제 READY/중단 회수 PASS와 BUSY 전달의 원 invocation

1a708be0 owner로 actual91395b22… 실행에서 ROOT_READY를 수신했다. 관측은 실제 PID가
systemd executor UID0/NoNewPrivs0 상태에서 원 native Python UID/GID973/973,
supplementary974/모든 capability0/NoNewPrivs1로 전환하는 것을 확인했다. executor는 worker로
인정하거나 요청/grant를 보내지 않았다. 새 exec guard 이후 기존 실제 native 신원·파일·device/
FDSTORE·unit/원 Root peer 검사가 통과해 READY가 전달됐다. source/compute binding을 주지 않고
연결을 끊었으며 원 supported retirement가 완료됐다. Root의 의도된 실패와 native 원 failure
journal은 보존했다. 실제 native MainPID0/NFileDescriptorStore0/inactive, GPU0%/2MiB,
input/result/vectors size0과 보호된 원 retirement intent/result 두 파일을 별도로 확인했다.
모델/토크나이저/forward0이며 실제 Source/IAM·수치 batch 검증을 대신하지 않는다.

원 기록은 `/tmp/eom-gpu-batch-pregrant-os-status-20261025.log`,
`/tmp/eom-gpu-batch-pregrant-retirement-readonly-20261025.log`다. original native invocation은
`795fbcaf56c54a3d8b5b50c754a88969`로 protected retirement 경로에 남아 있다. current PID1 unit의
InvocationID가 stop/unload 후 비는 것은 원 identity를 덮어쓰거나 새 invocation으로 바꾼 일이 아니다.

실제 shared GPU mutex를 다른 root 진단 프로세스가 계속 유지한60030e0d… BUSY 검증에서는 native
unit이 정상 BUSY 종료했고 original invocation `c6d8fdebb0144103a830b2bff41c5ba3`에 대한 protected
`EMBEDDING_GPU_BATCH_UNAVAILABLE_NOT_EXECUTED` result와 원 unit retirement까지 완료됐다.
그러나 Root→owner 알림 adapter가 stop 후 빈 current InvocationID를 original ID와 같아야 한다고
요구해 전달을 거부했다. 실제 current LoadState=loaded/InvocationID empty/PID0/store0과 원
protected result를 대조해 확인한 input/output 계약 충돌이다. 원 BUSY 실행은 다시 시작하지 않는다.

기존 stopped observation은 이미 `observed invocation ∈ {empty, original}`만 허용한다. 알림 adapter도
그 검증된 cleared-current 상태를 받아들이되 **전달하는 immutable invocation은 원 terminal
snapshot의 정확한 ID**로 유지한다. 다른 non-empty invocation은 계속 거부한다. 관측 값을 원 ID로
조작하거나 latest를 조회하지 않는다. COMPLETED와 BUSY 양쪽에 같은 불일치가 있어 둘 다 수정한다.
Root/worker JSON schema, qualified numerical prefix, DB/history와 API/Web selection은 바꾸지 않는다.

원/cleared/current-other invocation의 COMPLETED·BUSY 전달과 기존 controller/terminal 관측 회귀94
PASS/32.55초, strict mypy1 PASS, Ruff PASS다
(`/tmp/eom-gpu-batch-cleared-invocation-tests-20261025.log`). 원 BUSY physical result는 보존하며,
알림 수정 후 새 hardware-only identity로만 최종 전달을 확인한다. CPU 대체 실행은 아직 별도 gate다.

7f041c715ad92dc8e5ec375ef6e8225d6f1b85cf를 main에 push하고 공식 build-only/RECORD를 통과했다.
private root owner만 해당 immutable release로 준비했다. build 경로는
`/tmp/eom-api-build/7f041c715ad92dc8e5ec375ef6e8225d6f1b85cf.iDjAmh/dist`, platform rawSHA
`6ac7d31b800ab624c8bc5c10883dfe57c243b702d4d55152e647f9ed81165112`, contracts rawSHA
`5043e452f5c6c5d9d913bc432414a09bf83aa6f191de8e8f72ac5b9733c4e843`다.
실제 CPU root-controller Python에서 installed owner21/dependency472 import PASS/model import NONE다.
현재 production application에 아직 연결하지 않은 batch-controller environment가 이 owner를 pin하며 로그는
`/tmp/eom-gpu-batch-retirement-owner-stage-20261025.log`, exit0다. API/Web/private QUERY·CPU INDEX의
active selection은 이 설치로 바꾸지 않았고 다섯 기존 서비스가 계속 active다.

7f041c71의 첫 BUSY 실행d37de4f3…는 Root/native 모두 정상 종료했다. 진단 출력의 datetime JSON
직렬화만 실패해 output harness를 수정했다. 운영 source를 그 문제 때문에 또 바꾸지 않았으며
해당 정상 unit/history도 그대로 남겼다. 그 다음 실제0ed3289f…에서는 actual RootBusy 전달과
수신 caller 검증, 원 native invocation `abee33a0c19a4e05aa8b96c8ab627d45`, 원 종료·retirement를
모두 확인했다. 실제 공통 GPU mutex를 별도 프로세스가 끝까지 유지했고 그 holder를 중단하거나
락을 빼앗지 않았다. elapsed24.9373초, source authority NONE/model0/CPU execution NOT_RUN,
parent lease validation/close 및 harness exit0다. 로그는
`/tmp/eom-gpu-batch-busy-hardware-20261025-r4.log`다. 원 native MainPID0/store0/inactive와
Root MainPID0/success, 최종 GPU0%/2MiB를 다시 확인했다. 이는 acquire-time 비실행/물리 상호배제
증거이며 실제 image/trainer 모델 실행이나 Canonical Source/CPU 대체 계산의 PASS는 아니다.

CPU metadata owner에 GPU 패키지를 설치하지 않았다. hardware-only mutex holder는 이미 자격
검증된 CUDA prefix의 stdlib-only public `eom_gpu_lease` 두 파일만 root0444/정확한 SHA로 확인해
별도 diagnostic namespace로 사용했다. CUDA interpreter/ML factory나 전체 site-packages를
metadata owner에 혼합하지 않았고 production dependency/environment도 바꾸지 않았다.

LIVE_GPU_READY_INTERRUPTION=PASS, LIVE_ACQUIRE_TIME_BUSY=PASS,
CANONICAL_SOURCE_BATCH_COMPUTE=NOT_RUN, CPU_FALLBACK_EXECUTION=NOT_RUN,
CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, GOAL=ACTIVE.
이 시점은 hardware 경계 milestone이지 사용자가 요청한 **전체 GPU 목표 완료 checkpoint**가 아니다.
DOCUMENT/QUERY 실제 application 연결·device index coverage·CPU 대체·처리량·default/rollback을
완료하고 source와 실제 compatible release set을 고정한 다음에만 지정된12+4 정적 리뷰를 시작한다.

### P2-U — DOCUMENT 수치 실행 경계 연결 설계 (2026-10-25)

기존 `CatalogNativeEmbeddingExecutor`의 source/claim/encoding reservation/Artifact commit/
index 등록은 공통 application 한 곳에 유지하고, CPU 고정 unit 실행과 CUDA 묶음 실행만
작은 `DocumentEmbeddingExecution` port의 별도 adapter로 분리한다. DB/schema/worker wire는
변경하지 않는다. 입력은 기존 불변 launch association + input, 출력은 검증된 result + 보호된
publication workspace이며 binary/완전한 문항을 DB나 다른 registry에 복제하지 않는다.

canonical source는 Catalog의 pin된 source plan, 실제 actor/command lease와 기존 encoding
Job/association이다. CUDA adapter는 실제 parent admission/route를 소유한 active batch에만
결합한다. 자료형식(view)별 순서 고정 tuple, job/ordinal 조회 map, 유한 Condition gathering을
사용한다. 최대3개 view와 기존1,024 encoding rows의 O(n) 처리이며 새로운 queue/daemon은 없다.
각 Runner는 기존 claim/heartbeat를 유지하고 SQL root 밖에서만 다른 child/계산을 기다린다.

GPU 결과는 aggregate의 read-only memoryview에서 기존 child commit workspace로 한 번만
materialize하고 기존 publication/reservation completion/index 등록을 재사용한다. CPU의
`PreparedNativeIndex` CPU-only guard는 그대로 둔다. device-neutral liveness enum은 관측일
뿐 권한/완료 영수증이 아니다. unknown/error/중단은 기존 소유권을 보존하며 다른 장치로
재실행하지 않는다. source/hash/권한 오류는 전파한다. 완료 후 replay는 원래 child만 받는다.

단순 대안인 CUDA 전용500행 executor 복제는 source fence/등록/중복 방지 규칙을 갈라놓으므로
배제한다. 이번 경계 분리에서 CPU adapter와 CUDA child publication materializer를 구현한다.
finite-batch CUDA dispatch를 이 port에 결합하는 단계는 아직 완료하지 않았다.
이미 재사용 가능하거나 다른 intent가 소유한 child의 no-numerical 처리,
원 parent의 cold recovery, INDEX selection의32→bulk 범위 확대는 별도 남은 호환 계약이며
이 경계 분리만으로 GPU default/전체 goal 완료를 선언하지 않는다. released1.0 schema bytes는
수정하지 않고 필요한 후속 계약에서 명시한다. 테스트는 실제 파일/중단 보존과 disposable
PostgreSQL reservation/replay를 구분하며 hardware/운영 실행 PASS로 확대 해석하지 않는다.

P2-U 소스 검증: 집중 회귀/파일 경계/의존성/설치 wheel 검사 **186 PASS,87.15초**
(`/tmp/eom-document-execution-tests-20261025-r1.log`). 새 CPU adapter/CUDA materializer/
indexing runtime의 cold import 순서를 추가한 wheel 검사를 별도로 다시 실행해
**1 PASS,15.89초** (`/tmp/eom-document-execution-wheel-tests-20261025-r1.log`)다.
7개 변경 source strict mypy, scoped Ruff lint/format, diff whitespace PASS다.
새 dependency/DB migration/external worker message는 없다.

기존 CPU numerical handoff를 실제 보호된 임시 파일에서 사용한 disposable PostgreSQL
Workflow/encoding reservation/index 등록/중단 재전송 회귀 **36 PASS,208.18초**,
임시 DB cleanup/실행 exit0 (`/tmp/eom-document-execution-pg-20261025-r1.log`)다.
동시 동일 encoding claim, 기존 완료 행 재사용, publication 단계 중단 후 원 producer
재사용과 completion replay를 포함한다. IAM/model/OS 실행 leaves는 해당 suite에 명시된
synthetic seam이므로 실제 GPU 수치 실행/운영 인증 PASS로 보고하지 않는다.

CUDA child materializer는 실제 임시 파일에 대해 exact replay/inode 유지, partial member/
symlink/legacy launch marker 보존·거부, raw hash/read-only vector/실행 소유자 검사를 통과했다.
CPU adapter는 현재 source/lease 확인과 staging을 짧은 root에서 끝내고 수치 실행은 SQL 밖에서
한다. 기존 BUSY/UNCERTAIN만 pending이며 다른 오류는 전파한다. liveness는 enum 관측값일 뿐
성공 영수증이나 장치 변경 권한이 아니고, 누락된 unit/문자열 가짜 성공은 uncertain이다.

운영 배포/active selection 변경은 이 단계에서 하지 않았다. 다섯 기존 서비스 active,
GPU0%/2MiB를 재확인했다. CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO,
CUDA_DOCUMENT_DISPATCH_COMPOSITION=PENDING, CANONICAL_SOURCE_BATCH_COMPUTE=NOT_RUN,
CPU_FALLBACK_EXECUTION=NOT_RUN, GOAL=ACTIVE. 기존 API/Web/QUERY/INDEX/private root
release와 qualification/실패 기록은 그대로다. 이 commit은 경계 분리 중간 체크포인트이며
요청된 전체 GPU 완료 체크포인트가 아니다. 후속12+4 리뷰는 아직 시작하지 않았다.

### P2-V — 기존 namespace 단위 DOCUMENT GPU adapter 설계 (2026-10-25)

기존 INDEX Workflow는 하나의 namespace/view를 소유한다. 이 원래 단위를 변경하지 않고
하나의 canonical parent selection/view와 연결한 CUDA adapter를 공통 executor에 주입한다.
한 native input의 다수 document rows/microbatches는 기존 finite GPU backend scope에서
모델 한 번을 재사용한다. QUERY의 여러 독립 문항을 모으는 계약과 자료1건의 여러 view는
같은 개념이 아니다. 전체 목표의 bulk coverage/연속 자료/다문항 QUERY는 별도로 유지한다.

canonical source/identity는 기존 Catalog owner, source plan, 실제 command lease,
parent admission/route, child Workflow의 unique key 및 원 encoding launch association이다.
parent request+child selection에서 도출한 Workflow key를 확인한다. 기존 Workflow equivalence가
다른 parent의 실행을 반환해도 그 실행을 새 GPU parent에 묶거나 다시 계산하지 않는다.
관측 port에는 작은 immutable intent를 전달해 원 Workflow 관계를 검사하며 권한을 주지 않는다.

원 parent 한 개/Workflow 한 개/owned input 한 개의 O(1) identity lookup과 source set의 O(n)
map 비교를 사용한다. 기존 최대1,024 rows/16MiB vectors, original physical deadline을 유지한다.
readiness는 metadata/runtime 관측이고, 실행 직전과 publication 직전은 실제 owner/source/lease
fence를 재진입한다. SQL transaction은 GPU 실행 전에 닫는다. canonical batch receipt와 실제
검증된 child result/read-only vectors를 기존 child publication 경계에 넘기고 공통 예약 완료·
index 등록을 사용한다. 새 DB/schema/worker wire/dependency/queue는 추가하지 않는다.

단순 대안인 string job ID만으로 READY를 보고하는 것은 다른 parent의 publication 중단 결과를
재실행할 수 있으므로 배제한다. CPU adapter의 unit 관측은 그대로 두되 intent에서 원 job ID를
취한다. 실패/permission/hash/계산 불명은 CPU fallback하지 않는다. 같은 살아 있는 application의
publication 중단 replay는 원 결과만 재사용하며 root를 다시 실행하지 않는다. 새 process에서
canonical receipt와 남은 원 binary를 복구하는 경계는 추가 검증 전까지 명시적으로 pending이다.

구현: `document_embedding_cuda_execution`은 기존 공통 numerical port의 두 번째 실제 adapter다.
`document_embedding_batch_driver`는 공식 atomic INDEX/START를 호출하고 원 parent key를 확인한
뒤, 실제 owner/executor/actor에 묶인 purpose-only 기존 Runner에 claim을 맡긴다. 새 queue나
별도 worker/scheduler는 없다. broad-role Runner는 실행 전에 거부한다. run_once의 None을
성공 receipt로 포장하지 않는다. 완료 조회/새 process 복구의 권한 경계는 별도로 유지한다.

소스 회귀/파일·의존성·설치 wheel **193 PASS,99.04초**
(`/tmp/eom-document-cuda-source-tests-20261025-r1.log`), 최종 driver까지 포함한 cold-import/
실행 경계 재검사 **48 PASS,33.16초** (`/tmp/eom-document-cuda-driver-tests-20261025-r1.log`).
변경 source8개 strict mypy와 scoped Ruff lint/format, diff whitespace PASS다.

disposable PostgreSQL 증거는 범위를 나눠 기록한다(중복 suite를 합산하지 않는다).

- CPU/encoding 중복 예약/등록/중단 재전송 + CUDA 자료 + 기존 두 QUERY finite-batch 회귀:
  **48 PASS,446.68초**, cleanup/exit0 (`/tmp/eom-document-execution-pg-20261025-r4.log`).
  이는 driver 추가 전 회귀다. QUERY/DOCUMENT가 동일한 synthetic root fixture를 재사용한다.
- 최종 자료 adapter/공식 START·실제 Runner + 저장4지점 중단·재전송 + 다른 parent 차단 +
  broad-role Runner 거부: **8 PASS,98.67초**, cleanup/exit0
  (`/tmp/eom-document-execution-pg-20261025-r6.log`). 이전 command/launch/producer checkpoint
  prefix가 그대로 유지되고 CPU numerical launcher 호출은0이다.
- heartbeat1초의 isolated config에서 실제 background-thread renewal transaction의
  after_commit을 기다린 뒤 계산을 시작했다. 완료와 동일 START replay를 확인한 최종 재검증:
  **1 PASS,19.36초**, cleanup/exit0 (`/tmp/eom-document-execution-pg-20261025-r7.log`).
  기본 운영 heartbeat/lease 값은 변경하지 않았다.

개발 실패도 보존했다. r2는 fixture가 read-only identity property를 덮어쓰려 해 setup에서
실패했다. r3 수정 fixture의6개는 PASS다. r5에서는 기존 CPU 수동-step fixture의 fake owner가
terminal command에도 live-only lease 검사를 적용해 실제 Runner의 terminal commit에서
실패했다. fixture에 실제 `NativeCommandMutationFence`와 실제 owner의 mutation fence를
사용한 r6/r7로 교정했다. production lease/state-machine 규칙은 완화하거나 바꾸지 않았다.
각 disposable DB는 해당 실행 종료 시 정리했고 기존 운영 실패 기록은 건드리지 않았다.

이 suite의 parent/Workflow/claim/command fence/Artifact/index 등록과 파일 materialization은
실제 경계다. IAM/source capture와 root/OS/GPU/model leaves는 명시적 synthetic seam이다.
따라서 **CANONICAL_SOURCE_BATCH_COMPUTE=NOT_RUN**은 여전히 유지한다.

남은 연결 순서: INDEX의 bulk source selection(현재1.0은32 anchors)을 source-side 후속 계약으로
확장한다. QUERY의32개 제한이나 기존1.0 schema bytes를 바꾸지 않는다. allocation/route/bound의
기존 opaque parent hashes와 native control wire를 유지할 수 있는지 검증해, 불필요한 CUDA
수치 SDK/qualification 재발행을 피한다. 이어 service/runtime의 per-request routed composition,
CPU route의 공식 child 실행·binding, no-numerical child의 명시적 disposition, cold receipt/binary
복구, paired index 실제 coverage, 수치/처리량/공존 canary와 default/rollback을 닫는다.
하나의 namespace/view의 대량 rows와 여러 문항 QUERY를 모두 유지하며 목표 범위를 축소하지 않는다.

CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, CUDA_DOCUMENT_ADAPTER_SOURCE=PASS,
CUDA_DOCUMENT_DRIVER_DISPOSABLE_PG=PASS, LIVE_CANONICAL_GPU_COMPUTE=NOT_RUN,
CPU_FALLBACK_EXECUTION=NOT_RUN, GOAL=ACTIVE. 이 단계 역시 전체 완료 checkpoint가 아니다.

### P2-W — INDEX bulk selection/request1.1 설계 (2026-10-25)

INDEX의1.0 selection은32개 source anchor 한도라520개를 작은 parent로 나누면 같은 모델의
cold load를 반복한다. source-side 후속1.1을 추가해 INDEX만 최대1,024 anchors/4MiB metadata로
받는다. QUERY는 released1.0/32개를 유지하며1.1 QUERY는 명시적으로 거부한다. 기존1.0
schema bytes/ID/hash와 native allocation/route/bound/failure1.0, CUDA numerical SDK/qualification은
그대로다.1.1 schema는 재사용하는1.0 event frames를 명시적으로 참조한다. opaque parent hash를
전달하는 native wire를 넓히거나 구버전을 새 버전으로 retag하지 않는다.

canonical source는 pin된 selection Artifact와 실제 Catalog actor/Graph/policy/source closure다.
logical batch+actor key와 immutable request hash, 각 source/profile/analysis pointer는 분리한다.
메타데이터만 기존 Artifact/Job/Event에 두며 DB table/index/queue를 새로 만들지 않는다.
source revision map/set으로 O(n) coverage/uniqueness를 검사하고 순서는 immutable tuple로 고정한다.
기존 unique Job key/row lock/append-only sequence와 짧은 실제 authority transaction을 재사용한다.
동일 batch의 다른 version/hash는 충돌이며 latest로 치환하지 않는다.

version-specific schema-first model과 closed parser로 지원 family를 한 곳에서 dispatch한다.
공통 selection/request value fields와 순수 closure 규칙만 공유해 domain invariant 복사를 막는다.
1.1 선택과1.0 request의 혼합/반대 혼합, unknown version, hash/schema/media/lifecycle 오류는 거부한다.
실패/재전송은 원 Job/route/producer를 유지하고 이 변경이 재추론 권한을 만들지 않는다.
권한·해시·실행 불명 오류의 CPU fallback 금지도 유지한다.

대안인 released1.0 한도 직접 확대와17개32-source batch 반복은 각각 불변 계약/모델 재사용 목적에
맞지 않아 배제한다. domain/contracts는 infrastructure를 import하지 않으며 Source owner가
publication/resolution을, Orchestrator가 기존 history commit을 소유한다. schema/resource mirror,
32/33·520/1,024/1,025 경계, QUERY 거부, legacy bytes/정확한 replay, missing/stale/hash/current
authority와 disposable PostgreSQL 동시성/Job history를 검증한다. Source 검증과 실제 GPU 실행은
별도 gate이며 이 후속 계약 추가만으로 GPU default 활성화를 선언하지 않는다.

P2-W 구현/검증:1.1 raw schema SHA는
`deb40e0b3ebbcaed1d956bf5d9cbc09937a5f4a568bd397c819396387e0dd6c3`다.
source/resource mirror가 동일하며1.0 두 파일의 rawSHA
`94fe09d2dc756e15b77c3f61883a4dd76f6028b463199a5ad62bd6bf700f1337`은 그대로다.
공통 value fields/closure만 추출하고 version별 schema-first guard와 closed family parser를
분리했다. Source publisher/resolver/store/실행 adapter가 이 family를 사용한다. 실제 owner의
maximum_sources 제한은 기존 SelectedEmbeddingSources가 계속 소유하며1.1 한도로 우회하지 않는다.
기존 parent key는 version별로 나누지 않아 동일 logical batch를 새 version으로 fork하지 못한다.

- 계약/현재 source admission 집중 **68 PASS,20.67초**
  (`/tmp/eom-bulk-plan-contract-tests-20261025-r2.log`).33/520/1,024 metadata,
  legacy32 한도·QUERY1.1 거부·unknown/mixed version·raw hash·scope cap·revoked/missing source를 확인했다.
- legacy/native owner-control/DOCUMENT/QUERY/의존성·설치 wheel 포함 **174 PASS,79.47초**
  (`/tmp/eom-bulk-plan-source-regression-20261025-r2.log`).1,024 anchors의 실제 canonical metadata
  파일은 기존512KiB를 넘으며 새 resolver가 읽었다. 설치 wheel에서1.1 resource를 직접 열어
  SHA/schema ID를 확인했고 runtime checkout 의존은 없다.
- disposable PostgreSQL1.0/1.1 plan/admission 동시성·원 allocation 유지·중단 rollback·정확한
  replay·FAILED 보존·B-tree lookup capability **38 PASS,24.02초**
  (`/tmp/eom-document-execution-pg-20261025-r8.log`), cleanup/exit0.
- 기존 실제 source/Workflow/Artifact 경계와 synthetic OS/model leaves의 실행 회귀
  **48 PASS,317.81초** (`/tmp/eom-document-execution-pg-20261025-r9.log`), cleanup/exit0.
-1.1 parent가1.0 native control/bound를 사용해 공식 INDEX/START와 실제 Runner로 등록되는 경로,
  기존1.0 logical batch를1.1로 fork/교체하지 못하는 경로의 최종 추가 검사 **2 PASS,19.32초**
  (`/tmp/eom-document-execution-pg-20261025-r10.log`), cleanup/exit0.

테스트1차의 legacy negative case import3건과 잘못 지정한 unit publication 파일 invocation은
개발 fixture/실행 목록 오류였다. import/대상을 바로잡은 r2로 해당 gate를 재실행했다.
운영 코드의 validation/권한/lease를 완화하지 않았고 이 실패 로그도 보존했다.
13개 source strict mypy와 scoped Ruff lint/format/diff 검사 PASS다. 새 dependency/migration은 없다.

위520/1,024는 synthetic metadata cardinality 검사이며 운영 corpus 재임베딩 수가 아니다.
실제 GPU math/CPU 대체 실행/paired coverage/default/rollback은 여전히 별도 미완료 gate다.
운영 API/Web/INDEX/QUERY/private root/CUDA prefix 선택은 바꾸지 않았다. 다음 단계는 실제
per-request routed runtime/service composition과 no-numerical disposition/cold recovery다.
CURRENT_DEFAULT=CPU, GPU_PREFERRED_ACTIVE=NO, BULK_METADATA_CONTRACT_SOURCE=PASS,
LIVE_CANONICAL_GPU_COMPUTE=NOT_RUN, CPU_FALLBACK_EXECUTION=NOT_RUN, GOAL=ACTIVE.
