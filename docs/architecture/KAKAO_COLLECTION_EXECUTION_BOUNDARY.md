# KakaoTalk 수집 실행 계약

기준: `KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md` §§4–6.
이 문서는 source 계약이며 실제 카카오 capability·로그인·운영 활성화 증거가 아니다.

## 책임과 정본

Catalog는 현재 사용자·binding 권한과 lifecycle, capability revision, 결과 발행의
소유자다. Orchestrator는 task/attempt/fence, 프로세스·profile 잠금과 local workspace를
관리한다. Collector는 승인된 화면을 관측해 local CSV/첨부/작은 결과 manifest만
제출한다. worker 간 통신, PostgreSQL·NAS 접근, 메시지 전송·차단·상태 변경은 없다.
브라우저 인증은 보호된 profile에 있고 command/result에 cookie·URL·비밀번호를 넣지 않는다.

정본은 발행된 raw CSV와 첨부 Artifact다. worker 결과와 정규화는 별도 파생물이다.
이 단계의 `CaptureCapability`는 owner가 검증한 관측과 release의 exact pin이며,
임의 worker/client가 제공한 JSON만으로 실행 권한·채널 검증을 얻을 수 없다.
새 capability를 발행하고 활성화하는 application은 별도 현재 권한 검사를 해야 한다.

## identity와 작은 계약

- binding/room/snapshot ID는 기존 Catalog 계약을 따른다.
- run/task/command/attempt ID와 증가하는 fence는 별개다.
- capability는 `kakaocapabilityrev_…`와 canonical SHA, adapter release SHA를 함께 pin한다.
- inventory는 `kakaoinventoryrev_…`; 수집 room은 해당 inventory의 확인된 내부 room이다.
- 출력은 ASCII relative path·size·SHA·detected media의 local member만 받는다.
  CSV는 32 MiB, 각 이미지 64 MiB, room 전체 256 MiB, CSV 100,000행,
  첨부 2,000건을 초기 상한으로 둔다. 이는 사용량 추정이 아니라 검증 예산이다.
- 원문 본문과 외부 서명 URL, 원본 파일명, DB/NAS 경로를 명령·결과에 넣지 않는다.
  CSV 원문은 raw member에, 방향/정합 관측은 별도 bounded JSON member에 둔다.

## 주요 접근과 구조

실행은 exact ID lookup, 정렬된 목록 순회, membership/중복 검사다. dict/set으로
scope/room/첨부 ID와 local member를 O(n)에 확인하고, 순서는 tuple로 유지한다.
같은 SHA의 반복 사진은 서로 다른 occurrence로 보존한다. 같은 path는 동일 bytes의
재사용일 때만 허용하며 서로 다른 hash/media를 가리킬 수 없다. unresolved 목록은
확인된 room/attachment 목록과 분리하되 coverage에서 사라지지 않는다.

작은 capability·command·result는 immutable value다. 긴 inventory/첨부 관측 JSON은
local member로 넘겨 owner materialization boundary에서 한 번 검증한다. 이 pure
module은 DB/파일 읽기/브라우저 실행을 하지 않으며 새 queue·scheduler를 만들지 않는다.

## 완전성·발신 방향

목록 complete는 확인된 전체 scope, filter 초기화 증거, 명시적 목록 끝,
loading 없음, 두 번째 pass의 신규 room 없음, unresolved 없음을 모두 요구한다.
종료를 못 증명한 반복 scroll은 complete가 아니다. inventory는 단일 시점의
원자적 snapshot이라고 주장하지 않고 시작/종료/reconciliation UTC를 남긴다.

CSV 순서·timezone·방향은 unknown을 허용한다. `USER` 이름으로 role을 추정하지 않는다.
정규화 parser는 별도 owner 경계에서 raw CSV를 재파싱한다. worker row count와 관측
JSON은 검증해야 할 주장이다. `사진` 행에 파일이 없다고 사진이 없었던 것으로 처리하지
않고 attachment inventory coverage와 unresolved 상태를 보존한다. 원본 확보와
PNG/JPEG/WebP 렌더 지원은 별개이며 지원하지 않는 파일은 unresolved로 남긴다.

## 상태·동시성·실패

도메인 run 상태와 허용 전이는 명시적 표로 둔다. 기존 global Job enum은 바꾸지 않는다.
활성 상태에서 중단/취소는 먼저 PAUSING이고, checkpoint+process/profile stop 관측 후
PAUSED/CANCELLED가 된다. lease 시간 만료 자체는 프로세스 종료 증거가 아니다.
DB의 atomic claim/최신 fence와 OS profile lock을 모두 owner가 확인해야 하며 이 pure
계약은 그 확인을 대신하지 않는다.

timeout이면 원래 command/attempt 조회가 먼저다. 유효 결과는 재발행이 아니라
같은 publication intent를 이어간다. 결과 처리가 불명확한 동안 새 attempt는 없다.
네트워크 오류의 재시도는 최대 3회, 이전 process/profile stop 확인 이후에만 허용한다.
AUTH_REQUIRED는 로그인 자동 반복 금지, UI_CHANGED/HASH_MISMATCH는 점검 대기,
ACCESS_DENIED는 권한 변화 전 반복 금지다. NAS 발행 실패는 local 결과를 보존하고
publication recovery를 사용하며 재수집하지 않는다. FAILED 기록은 변경하지 않는다.

## 수락과 단순 대안

command/result exact identity·capability hash·현재 fence → local 파일 type/link/크기/hash
→ core staging → 현재 ACL/lifecycle → 기존 Artifact commit → domain pointer 연결 순이다.
외부 다운로드 동안 DB transaction을 유지하지 않는다. NAS와 domain DB를 단일 atomic
transaction이라고 부르지 않으며 기존 publication idempotency로 중간 실패를 복구한다.

더 간단한 `성공 여부 + CSV 경로`만으로는 어느 채널/시점/attempt의 결과인지, 사진·목록이
누락됐는지, timeout 뒤 중복 실행인지 구분할 수 없다. 반대로 selector registry·새 workflow
framework는 현재 필요 없으므로 만들지 않는다. 실제 capability 실증 전 운영 자동 수집은
활성화하지 않는다.

## 다음 구현: 최소 영속 owner 경계

이 절은 2026-11-16 소스 재검토의 설계 제안이다. 아직 아래 DB·scheduler·collector가
구현되거나 설치됐다는 뜻이 아니다. 기존 binding은 DRAFT/RETIRED뿐이고 capability는
NOT_VERIFIED다. 다음 담당자는 실제 최신 migration head와 공유 diff를 먼저 확인한다.

### 이미 있는 것을 재사용할 위치

| 기존 코드 | 재사용하는 책임 | 재사용하지 않는 것 |
| --- | --- | --- |
| `kakao_archive_authorization.authorize_kakao_actor` | 실제 API actor/session·현재 permission·owner 확인 | worker가 전달한 operator나 role을 authority로 사용 |
| `kakao_archive_commands.lock_kakao_intent`, `kakao_command_sha256` | 짧은 owner/scope/key 잠금과 같은 요청 replay | 다운로드 동안 transaction 유지 |
| `kakao_student_models`, `kakao_student_service` | owner별 학생·불변 display revision·CAS 패턴 | 이름 중복 제거, 다른 owner 학생 연결 |
| `material_learning_store.claim_next_material_run`, `lock_material_run` | indexed `FOR UPDATE SKIP LOCKED`, lease 검증 **패턴** | 카카오를 material learning task로 등록하거나 그대로 재사용 |
| `material_learning_coordinator.authorize` | 저장된 run owner로 현재 권한을 다시 확인하는 **패턴** | 오래된 API session이 계속 유효하다고 간주 |
| `CatalogArtifactService.commit_file_set` | publication lock, exact idempotency, COMMITTING 복구 | collection run과 publication Job을 같은 ID로 간주 |
| `kakao_archive_intake.publish_kakao_capture` | raw hash·재파싱 일치 확인, raw/normalization 별도 발행 | arbitrary worker normalization만 믿고 정본 등록 |
| `kakao_pdf_execution.KakaoPdfExecutor` | core local staging, exact command/result, stopped-attempt recovery **패턴** | renderer 프로세스에 카카오 profile·network 권한 부여 |
| `capture`, `kakao_remote` pure 계약 | 상태 전이, exact capability, fence, stop receipt 검증 | bool receipt만으로 실제 종료·권한·채널 검증을 대체 |

`JobRecord`는 닫힌 실행 상태와 Artifact publication을 이미 소유한다. 신규 run의
AUTH_REQUIRED/PAUSING/PARTIAL을 여기에 추가하지 않는다. PDF/수집 실행은 새 source별
도메인 run/task의 pointer·상태로 관리하고, canonical 발행 Job ID는 별도 FK로 연결한다.
일반 Codex worker slot을 카카오 브라우저 슬롯인 것처럼 등록하지 않는다.

### 실제 수집을 시작하기 전에 필요한 authority

1. 현재 owner가 만든 binding과 보호된 profile의 연결은 owner runtime inventory다.
   public request·collector 결과의 profile 경로나 owner 주장은 받지 않는다.
2. 실제 원격 로그인 후 **예상 채널 ↔ 현재 열린 채널**을 비교할 관측 근거가 필요하다.
   사용자 확인과 adapter가 관측한 source identity/evidence를 작은 immutable verification
   receipt로 남긴다. 확인된 안정 ID가 없으면 수동 context 연결이며 이름 유사도로 대체하지
   않는다. 이 경우 자동 재접속에서 동일 채널을 재검증할 수 있는지 실증 전에는 보류한다.
3. 그 verification에 연결된 capability Artifact와 installed adapter release hash를
   Catalog가 확인한 뒤에만 binding ACTIVE 전이를 허용한다. `channel_verified=true`인
   임의 JSON 업로드나 worker self-report만으로 ACTIVE가 될 수 없다.
4. API command는 기존 실제 session 검증을 사용한다. 오래 걸리는 run과 schedule은
   **이미 저장된 owner의 실행 의도**를 현재 Identity ACTIVE/permission/binding grant에
   다시 대조한다. `authorize_kakao_actor`를 허위 actor/session으로 우회하지 않는다.
   별도 Catalog background authorizer는 run ID로 owner를 읽으며 operator ID를 worker에서
   받지 않는다. scope는 현재 ACTIVE binding과 해당 run의 exact capability/policy다.
5. Orchestrator의 실제 peer/launcher만 attempt admission을 요청한다. Catalog의 current
   lease/fence와 runtime owner의 process/profile-lock 관측이 함께 맞아야 한다. 현재
   `ProfileStopReceipt`는 값 모델이므로 receipt를 만들 수 있다는 것이 종료 증거는 아니다.

실제 채널·CSV 범위·사진 다운로드 실증 없이 2–3을 통과했다고 표시하지 않는다.
이 authority가 아직 없는 동안 학생·질문·packet 같은 독립 기능의 source/DB 검증은
합성 fixture로 진행할 수 있지만, 운영 방 수집·자동 스케줄은 비활성 상태다.

### 권장 최소 테이블과 조회 패턴

기존 binding/student 테이블은 유지한다. 다음 표는 한 번에 전부 추가하라는 지시가 아니라
후속 migration을 나눌 최소 aggregate 경계다. 본문·사진·전체 room 목록 JSON은 넣지 않는다.

| 작은 record | 핵심 필드·제약 | 주요 인덱스/용도 |
| --- | --- | --- |
| capability revision | binding, revision, adapter SHA, verification/manifest Artifact pointer, observed/accepted UTC, accepted owner | unique(binding,revision), exact Artifact composite FK; current pointer만 binding에 추가 |
| room | owner+binding, server-issued room ID, verified identity method/key, identity evidence pointer, current mapping rev nullable, resource_version, lifecycle, last_observed UTC | unique(binding,verified provider identity key) **verified일 때만**; (binding,last_observed,room) keyset |
| room-student mapping revision | binding/room, mapping rev, previous rev, student ID 또는 명시적 UNMAPPED, exact display rev, actor/time, reason, request hash/key, result version | unique(room,revision number), unique(owner,room,idempotency key); room/binding/owner, student/owner, student/display composite FK |
| collection run | run, owner, binding, policy/capability pins, state, current inventory pointer, active task, created/update UTC, next event sequence | owner+idempotency key/request hash; partial unique(binding) for nonterminal run; (state,created,run) |
| room task | task, run, room, operation, state, current attempt, ordinal, result pointer | unique(run,room,operation); (run,state,ordinal); inventory task는 room NULL인 별도 부분 unique |
| attempt | attempt, task, attempt number, command hash, profile/browser IDs, fence, lease owner/token/expiry, outcome/error, local-result receipt pointer, publication linkage | unique(task,attempt number), unique(profile,fence); (state,lease expiry,task); terminal history는 불변 |
| snapshot acceptance | snapshot/normalization revision, binding/room, accepted attempt, raw/normalization exact pointers, row count, observed time, source scope/timezone/order | unique(snapshot), unique(normalization), (room,observed,snapshot); publication Job FK 별도 |
| media blob | binding, SHA, size/MIME/dimensions, original exact pointer | unique(binding,SHA); 다른 binding 전역 dedup 없음 |

binding별 browser 모드·증가 fence는 실제 원격 lease persistence와 **한 owner record**에서
조정한다. collection 전용 profile gate를 하나 더 만들어 MANUAL과 AUTO가 서로 다른
배타성 테이블을 보게 하지 않는다. pending task를 모두 claim하는 별도 queue도 만들지
않고, run row를 claim한 owner가 현재 task 하나를 고른다. 초기 전체 동시 run 1 제한은
기존 owner tick의 고정 설정으로 충분하며 범용 capacity framework는 추가하지 않는다.

mapping revision 자체가 immutable 명령 결과를 담을 수 있으므로 이를 위해 별도 범용
command bus를 만들 필요는 없다. 다만 실제 public API의 create/read/rename/replay 모양에
맞추기 위해 기존 student command receipt 구조를 그대로 택하는 것도 가능하다. 둘을
동시에 도입하지 않는다. 이벤트가 필요하면 run의 monotonic sequence 아래 작은 ID·state·
error만 append하고 다른 도메인의 이벤트 테이블에 카카오 본문을 넣지 않는다.

### Worker room ID를 정본으로 바로 수락하지 않기

worker inventory의 room ID는 proposed reference다. 타 binding의 기존 ID를 제시했다고
그 방을 가져오거나 update하지 않는다. 수락 owner가 verified source identity를 binding
범위 안에서 lookup하고, 새 방이면 canonical room ID를 발급한다. 안정 ID를 확보하지 못한
항목은 unresolved로 보존하고 사람이 확인한 context mapping 없이는 기존 방과 합치지 않는다.
닉네임·정렬 순서·마지막 메시지·CSV hash는 영구 room identity가 아니다.

raw inventory와 **accepted inventory/identity mapping manifest**는 별도 revision이다.
후자는 raw exact pointer와 proposed observation→canonical room 대응을 pin하고, 이후
CaptureCommand가 사용하는 room ID와 inventory revision을 고정한다. worker의 기존 결과
파일을 제자리 수정하지 않는다. 현재 pure `CaptureInventory`는 관측 proposal 계약이며,
owner가 그 객체를 파싱했다는 사실만으로 source identity acceptance를 얻지 않는다.

### 가장 짧은 구현·transaction 순서

1. room+mapping 저장/조회부터 구현한다. owner 일치와 composite FK, same-key replay,
   두 동시 mapping CAS를 disposable DB에서 검사한다. 이 단계는 collector를 실행하지 않는다.
2. capability/verification 발행·수락을 연결한다. DRAFT에서 ACTIVE로 가는 guarded command와
   실제 current source authorizer가 있어야 다음 단계를 켠다. 단순 표시용 READY는 부족하다.
3. run intent를 실제 API actor로 접수한다. 짧은 key lock 안에서 owner/binding/policy와
   request hash를 확인하고 run/task identity를 고정한다. 같은 key는 같은 run을 돌려준다.
4. owner tick은 row lock으로 run/task를 claim하고 command/attempt/fence를 기록한 뒤
   transaction을 닫는다. 이전 process/profile 종료가 불명확하면 recovery로 보내고 launch하지
   않는다. 브라우저 실행 중 DB lock을 유지하지 않는다.
5. Orchestrator가 capability/input hash·실제 profile lock을 검증하고 local collector를 실행한다.
   result는 exact command/fence/capability와 파일 bytes 검사를 통과한 뒤 core staging에 둔다.
   unknown capability가 full/verified/original로 승격된 worker 결과는 거부한다.
6. Catalog는 현 권한·binding ACTIVE·pinned capability lifecycle을 재검사하고 기존 Artifact
   publication 경계로 raw inventory/CSV/사진을 발행한다. publication은 수집과 다른 Job이다.
7. 짧은 domain transaction에서 같은 current attempt/fence를 다시 확인하고 exact pointer,
   room mapping, snapshot acceptance, task state/checkpoint를 함께 연결한다. publication 후
   이 transaction이 실패하면 미채택 Artifact를 보존하고 **같은 attempt의 accept**만 재개한다.
8. normalize/candidate/question은 accepted pointer에서 만든다. owner-issued occurrence IDs와
   alignment receipt를 고정하고, 매번 이름/본문 hash로 새 identity를 추측하지 않는다.

### 필수 부정·복구 검사

- 다른 owner/binding/room/student/Artifact revision, retired source, expired public session 거부.
- 저장된 background intent가 있어도 owner 비활성/권한 철회 뒤 claim·accept·download 거부.
- 두 claim 경합, manual/auto 경합, lease 만료지만 process 생존, 늦은 이전 fence 결과 거부.
- worker가 타 room ID를 끼워 넣기, unknown source identity를 stable로 승격, 일부 scope를
  빠뜨리고 inventory complete 주장, unsupported 첨부를 누락시키는 결과 거부.
- publication 성공 후 domain commit 전 중단 → 원래 publication pointer 연결, 재수집 0회.
- 정규화 raw 재파싱 불일치, source hash 불일치, 동일 문구/동일 사진의 서로 다른 occurrence 보존.
- 원본 rows/Artifact/FAILED 기록 변경 없음; Item·Graph·임베딩 호출 0회.
- owner/room keyset page, bound 10,000-room inventory의 선형 검증; 불필요한 N+1·전체 history LCS 없음.

source 프로토콜 검사는 63개, 기존 remote 회귀와 합쳐 146개가 통과했다. 이는 위 신규 영속
owner·Kakao runtime·운영 배포를 검증한 수치가 아니다. 그 단계의 검사와 실증은 각각 별도다.
