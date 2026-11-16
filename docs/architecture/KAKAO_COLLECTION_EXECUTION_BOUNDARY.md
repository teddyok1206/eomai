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
| attempt | attempt, task, attempt number, command hash, profile/browser IDs, fence, lease owner/token/expiry, outcome/error, local-result receipt pointer, publication linkage | unique(task,attempt number), unique(command); (state,lease expiry,task); terminal history는 불변. profile/fence unique는 실제 browser epoch가 소유 |
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

### 0082의 제한된 구현 범위

첫 영속 slice는 room, immutable mapping revision, internal admission receipt의 3개 테이블이다.
공개 room create나 channel activate API는 없다. Catalog 내부 admission은 현재 실제 actor와
필수 owner-authority callback, 발행된 room-observation Artifact의 exact schema/hash/상태를
모두 검사한다. callback은 이미 검증한 source bytes와 현재 runtime/source authority를
대조하며 transaction 안에서 긴 파일 I/O를 하지 않는다. DRAFT binding에 자료를 연결해도
채널이 ACTIVE가 된 것으로 표시하지 않는다. RETIRED binding은 새 admission/mapping을 거부한다.

처음 확인한 room identity/display/evidence는 보존하고, 같은 verified source identity의
재접수는 기존 room과 해당 시점 mapping을 반환한다. worker의 변경된 이름/ID로 기존 방을
덮지 않는다. 주기적 재관측 이력은 후속 snapshot owner가 관리한다. mapping 수정만 current
pointer/version을 CAS 갱신한다. immutable mapping revision이 명령 key/hash를 보유하므로
mapping 전용 command 테이블을 또 만들지 않는다. 최초 UNMAPPED revision은 public key가 없다.

admission과 mapping은 owner/scope/key 잠금 뒤 binding → room → student 순서로 짧게 잠근다.
같은 source identity 동시 admission은 binding 내 identity 잠금과 unique constraint가 막고,
두 mapping 수정은 room lock+expected revision/version으로 하나만 수락한다. 이름으로 identity를
추정하지 않으며 public mapping은 같은 owner의 현재 ACTIVE student/display revision만 받는다.
이전 mapping 조회와 same-key replay는 나중의 rename/unmap으로 내용이 바뀌지 않는다.

## 실제 내보내기 경험에 따른 실행 방식 결정 — 2026-11-16

실제 방에서 CSV와 사진2건의 download event·로컬 보존·hash를 확인했다. 이것은 전체 방
수집이나 사진 occurrence 정합의 완료 증거가 아니다. 사용자 승인 아래 화면을 읽고 누른
개발용 좌표를 운영 selector로 승격하지 않는다.

**반복 수집에는 결정론적 Playwright adapter를 사용하고 전용 Codex 슬롯은 배정하지 않는다.**
CSV 내보내기와 사진 내려받기는 관측 가능한 고정 업무이며 모델의 판단이 필요한 작업이 아니다.
AI가 임의 클릭을 계획하면 인접한 차단/신고/상담 완료 기능의 위험과 재현성 비용이 커진다.
Codex는 개발·장애 원인 분석에만 사용한다. 실제 UI에서 검증한 label/DOM·채널/방 identity를
고정된 동작으로 구현하고, 일치 개수·현재 방·다운로드 결과가 예상과 다르면 `UI_CHANGED` 등으로
멈춘다. 추측 클릭·일반적인 브라우저 명령 실행 도구·메시지 입력/전송 경로는 추가하지 않는다.
이는 기존 ‘운영 수집·질문 구성·PDF에 AI를 쓰지 않는다’는 결정을 유지한다.

### 코드 수집과 전용 Codex 슬롯의 비교·적용 범위

사용자는 사진 확보 성공 여부와 별개로 두 방식을 비교하고 EOM 원칙에 맞게 정리하도록
요청했다. 현재 판단은 **고정 코드 수집을 계속 구현하고, 운영 전용 Codex 슬롯/프롬프트를
추가하지 않는 것**이다. 이는 실제 전체 방 자동 수집이 검증됐다는 결론은 아니다.

| 판단 기준 | 기존 고정 코드 경로 | 전용 Codex 슬롯을 수집자로 쓰는 경로 |
| --- | --- | --- |
| 반복 업무 | 확인한 방 열기·내보내기·다운로드·순회에 한정 | 동일 동작에 모델 판단·결과 검증·사용량 관리가 추가됨 |
| 위험 동작 | 코드에 없는 클릭/키 입력 경로를 만들지 않음. 검증된 selector 불일치는 중단 | 전용 프롬프트만으로 오클릭·전송 금지를 강제할 수 없어 결국 같은 실행 guard가 필요함 |
| 재시도 | 원래 command/fence/수신 receipt와 publication을 재조회 | 모델의 새 판단이 원래 요청과 같은 실행인지 별도로 입증해야 함 |
| UI 변경 | `UI_CHANGED`와 확인된 관측을 남기고 점검 | 화면 해석이 가능하더라도 새 selector의 운영 검증을 대체하지 못함 |
| 책임·유지보수 | 기존 Catalog/Orchestrator/collector/Artifact/PDF owner를 사용 | 별도 슬롯·프롬프트·모델/추론 설정·출력/권한 검증을 추가 관리해야 함 |

전용 모델이 필요한 의미 판단 업무는 현재 요구에 없다. 질문 후보는 기존 결정론적 규칙으로
구성하고 애매한 분할·학생 연결·사진 누락은 명시적으로 검토 대상으로 남긴다. 이 기능을
GraphRAG/문항 출제 슬롯이나 외부 LLM에 연결하지 않는다. 개발 중 Codex가 실제 화면을
관찰한 사실도 무인 운영용 selector/권한 검증을 통과한 것으로 취급하지 않는다.

운영용 adapter의 동작 집합은 방 열기/닫기, 내보내기 메뉴, 파일 내려받기와 스크롤뿐이다.
실제 확인한 대상의 종류·일치 수·채널/방 context·다운로드 결과를 매 단계 검사해야 하며,
불명확한 경우 다른 위치를 추측해서 누르지 않는다. 메시지 편집/전송·차단/신고·상담 완료·
담당자/설정 변경은 집합에 넣지 않는다. 로그인/2단계 인증은 기존 사용자 원격 화면 경계에
남긴다. 현재 MANUAL driver의 download 관측은 입력/클릭 메서드를 노출하지 않으며,
실제 자동 selector·전체 방 목록·사진 occurrence 실증 전 AUTO는 계속 비활성이다.

확보하지 못한 사진이나 불명확한 메시지 연결은 incomplete로 보존하고, 텍스트와 사진을
억지로 짝짓거나 모델이 추측하게 하지 않는다. 코드만으로 필요한 UI identity를 관측할 수
없는 경우에는 그 제약을 보고하고 수동 확인 경로를 쓴다. 전용 AI 슬롯으로 조용히 우회하지 않는다.

### 로컬 수신물의 owner 입력 경계

1. 책임: 기존 Orchestrator OS adapter가 browser의 로컬 수신 파일을 읽고, 기존 Catalog
   source/media publisher에 넘길 검증된 입력을 만든다. 새 수집 서비스/큐/registry는 없다.
2. 정본: 로컬 수신물은 untrusted staging이다. canonical source는 별도 실제 권한·방/메시지
   정합 검증 후 기존 Artifact owner가 발행한 revision이다. 읽기 성공은 admission 권한이 아니다.
3. identity: 기존 `manual-download-v1`의 capture/profile/browser-run/fence/page-instance와
   payload SHA를 재사용한다. page instance나 filename을 provider room/message ID로 쓰지 않는다.
4. resolution: exact fence와 run marker, STARTED/terminal receipt의 identity, 고정 member,
   UID/GID/mode·종류·단일 link·symlink 없음·크기·SHA를 검사한다. 경로 입력은 서버 설정과
   검증된 ID로만 구성한다. payload나 receipt가 없거나 바뀌면 명시적으로 거부한다.
5. access/구조: capture ID의 직접 directory lookup과 bounded streaming/read다. O(file bytes),
   최대32MiB 입력을 owner materialization 경계에서 한 번 읽는다. 반복 목록 탐색이나 재다운로드는 없다.
6. persistence/concurrency: DB와 worker output은 변경하지 않는다. 읽기 FD 전후 metadata를
   대조하고, consumer는 반환된 고정 receipt/bytes를 사용한다. source 수락은 기존 짧은 CAS와
   publication 멱등 계약이 담당하며 이 reader가 claim·권한·성공 상태를 만들지 않는다.
7. dependency: pure 계약 → Orchestrator filesystem adapter → Catalog application 방향을 유지한다.
   Catalog가 collector private module을 import하거나 worker가 Catalog/NAS를 호출하지 않는다.
8. failure/retry: 미완료/FAILED·다른 run/fence·변조·위험한 파일은 읽기 오류다. 같은 검증된
   capture를 다시 읽을 수 있지만 재클릭/새 capture 생성/과거 FAILED 재해석은 하지 않는다.
9. 단순 대안: 임의 경로와 `read_bytes()`만 넘기면 잘못된 실행·완료 전 파일·위험 경로를
   구별하지 못한다. 기존 OS file 검증과 작은 수신 계약을 확장하며 범용 storage layer는 만들지 않는다.

MANUAL 세션이 종료되어도 이미 RECEIVED인 수신물은 검증할 수 있다. 이것은 세션 만료 뒤
자동 수집을 허용하거나 현재 owner/source 권한 확인을 생략하라는 뜻이 아니다. 실제 사진은
메시지별 관측과 연결하고, 남은 사진을 확보하지 못하면 incomplete로 보존한다.

### 다운로드 순간의 제한된 DOM 관측

실제 CSV는 blob 다운로드이고 사진은 방별 읽기 URL에서 CDN으로 redirect한다. 파일명과
page instance만으로 메시지 occurrence를 알 수 없으므로, 기존 MANUAL download receiver가
같은 download event의 page를 읽어 별도 `page-observation.json`을 남긴다. schema를 먼저
정의하며 이것은 untrusted local evidence다. 단순히 저장됐다고 provider identity나 source
권한이 확인된 것은 아니다. 이 관측은 새 명령 queue, 외부 디버그 포트나 범용 JS 실행 API가 아니다.

- exact capture/profile/run/fence/page instance를 기존 STARTED receipt와 연결한다. page URL은
  실제 관측된 `https://business.kakao.com` origin과 query/fragment를 뺀 path만 허용한다.
  download target은 같은 origin path 또는 blob 여부만 남긴다. CDN 서명 URL은 남기지 않는다.
- DOM은 고정된 read-only expression 하나로 한 번 읽는다. 값·cookie/storage·script·HTML·
  event handler·임의 attribute는 읽지 않는다. form/input/textarea/contenteditable/iframe
  subtree는 제외한다. tag/class/role/명시적 label, bounded leaf text, 소수 data identity,
  같은 origin의 link path와 image 존재 여부만 기록한다. image src·CDN URL은 저장하지 않으며
  이 관측은 사진 bytes의 대체물이 아니다.
- 시간은1.5초, 최대2,048개 element·65,536 text code point·최대1MiB JSON이다. 초과/clip은
  `truncated`로 표시하며 완전한 관측으로 사용하지 않는다. 페이지 종료·다른 origin·timeout은
  명시적인 UNAVAILABLE이다. DOM 관측 실패 자체로 정상 다운로드 bytes를 버리지 않는다.
  이 제한된 DOM text로 질문 본문을 만들지 않고, 원본 CSV 전체를 기존 parser로 읽는다.
  node index/parent index는 해당 snapshot의 임시 배치 값이며 메시지의 logical identity가 아니다.
- 실제 SDK page가 전달한 결과라도 schema/한계/identity를 확인한다. raw DOM 예외·URL·
  대화 원문은 log로 출력하지 않는다. 파일은 기존 수신 directory의 write-once0640이다.
  기존 file 수신 상태와 FAILED 기록은 바꾸지 않고, disk/receipt 쓰기 실패는 기존 수신 경계에서
  오류로 처리한다. worker는 NAS/DB에 쓰지 않는다.
- 주 access는 download event별 한 번의 bounded DOM 순회와 capture ID lookup이다.
  관측은 O(scanned DOM nodes + emitted text), 최대8,192 node를 검사한다. parent 관계는
  map으로 만들고 전체 DOM 복제·재파싱·주기적인 전체 화면 dump는 하지 않는다.
- 별도 control service나 전용 Codex 슬롯을 여는 대안은 과하다. 기존 receiver의 page callback과
  보호된 로컬 receipt helper를 재사용한다. 실제 DOM/selector 실증 전 자동 클릭·수집은 켜지 않는다.

#### 다운로드 이벤트와 DOM 관측 사이의 화면 이동

`receive`는 SDK download callback 안에서 query/fragment/credentials 없는 page path를
동기적으로 고정한다. 비동기 관측을 시작할 때의 page path, 관측된 document path와 관측 후
page path가 모두 같을 때만 DOM을 수신물에 붙인다. path가 바뀌었거나 일치하지 않으면 기존
`UNAVAILABLE/OBSERVATION_INVALID`로 남기며, 정상 수신 bytes와 원래 receipt는 보존한다.
다른 방 화면을 읽었을 때 재관측·추측 연결·재다운로드로 덮지 않는다.

이는 기존 collector의 관측 adapter가 소유하는 O(1) path 비교다. schema/DB/API·새 registry나
service를 추가하지 않는다. **같은 path 안에서 바뀌는 UI나 방/메시지 identity의 증명은 아니다.**
미래 source 수락은 여전히 실제 provider identity와 occurrence 관측을 별도로 확인해야 하며,
이 검사만으로 capability를 상향하거나 기존 실제 수신물에 DOM을 소급해서 붙이지 않는다.

## 관측한 MANUAL 방을 기존 방 디렉터리에 수락하기

첫 실제 방 등록은 `KakaoRoomService.admit_room`과 기존 admission receipt를 재사용한다.
새 수집 tracker/큐나 범용 승인 service는 만들지 않는다. 방 등록은 CSV/사진 source 수락,
학생 연결, capability 검증, AUTO 활성화와 서로 다른 단계다. DRAFT 연결을 fake ACTIVE로
바꾸지 않고, 사용자 확인이 필요한 작은 경로를 명시적으로 `MANUAL_CONFIRMED`로 기록한다.

1. 책임/정본: Catalog의 `KakaoRoomIntakeService`가 실제 현재 owner·COLLECT/ADMIN을 확인하고
   보호된 MANUAL 수신물을 읽어 기존 Artifact owner와 Room application을 연결한다. 원문 DOM/
   수신 receipt는 private Artifact에, canonical room/최초 mapping은 기존 room 테이블에 둔다.
2. 입력/identity: schema-first 명령은 binding/lease/capture ID, 사용자가 확인할 channel/room
   provider key, 표시 이름과 binding version만 받는다. 파일 path·권한·profile/fence·Artifact
   pointer를 클라이언트가 정하지 않는다. provider key는 canonical room ID가 아니며 기존
   room owner가 별도 ID를 발급한다. 이름으로 방/학생을 합치지 않는다.
3. 근거: actual SDK download target에서 관측된 `/api/profiles/<channel>/chats/<room>/…/image`
   구조와 document의 channel path가 맞아야 한다. query/서명 URL·filename은 join key가 아니다.
   현재 확실히 관측하지 않은 문서의 room URL suffix나 selector는 추측하지 않는다. 그 근거가
   없는 CSV/blob/text-only 방은 이 단계에서 IDENTITY_UNAVAILABLE이며 최종 제품의 남은 의존이다.
4. 수신 접근: 현재 operator의 새로운 유효 세션으로 자기 소유 과거 capture를 확인할 수 있다.
   이것은 원격 화면을 다시 여는 권한이 아니다. remote `_owned`/TTL/session 일치 규칙은 그대로다.
   원래 lease의 owner/binding/fence·실제 browser 관측 및 capture 시각을 확인하며 ENDED/실패
   이력은 수정하지 않는다. 과거 VNC의 30초 grant를 현재 원격 접근 권한으로 재사용하지 않는다.
5. materialization: 기존 Orchestrator reader로 원래 payload·receipt·DOM의 hash/종류/UID/GID/
   mode를 검사한다. room proof는 원래 receipt/관측 bytes를 pointer와 SHA로 연결한 작은 값이다.
   새 JPEG 복사·재다운로드·NAS writer는 없다. 질문 본문은 나중에 원본 CSV에서 만든다.
6. 저장/동시성: existing Artifact publication의 같은 owner/binding/key를 재사용하고, 마지막
   `admit_room` transaction에서 actual source callback과 현재 ACL/lifecycle을 재검사한다.
   canonical channel 고정에는 immutable `kakao_manual_channel_pins` 한 테이블만 추가한다.
   owner+binding unique/FK와 evidence Artifact FK로 첫 channel identity를 고정한다. 같은
   binding의 다른 channel은 명시적으로 거부하며 전환은 다른 binding의 별도 작업이다.
7. access/복잡도: owner/binding/lease/capture의 indexed lookup, 기존 admission key lookup과
   bounded 파일 읽기다. 첫 수락 O(bytes), 완료 재조회는 작은 canonical proof만 해석하고
   원본 payload를 다시 hash/read하지 않는다. node/대화 전체 검색이나 N+1은 없다.
8. transaction: 긴 file I/O·Artifact 발행 중 DB lock을 잡지 않는다. 방의 기존 intent/binding
   잠금 뒤 channel-pin intent를 직렬화하고 pin과 room/admission을 한 transaction에 채택한다.
   source 발행 후 중단은 같은 key/publication으로 이어가고 실패를 성공으로 바꾸지 않는다.
9. replay: 기존 room admission의 exact evidence를 찾아 실제 owner/원래 명령/hash·source 접근을
   다시 검증한다. 완료본은 worker staging이 정리된 뒤에도 canonical Artifact로 재조회한다.
   확인 전에 바뀐 binding version은 거부하되 이미 완료된 receipt는 이후 policy edit로 바꾸지 않는다.
10. 계층: HTTP/CLI가 invariant를 구현하지 않는다. Catalog application → 기존 room/manual
    metadata/read·Artifact/Orchestrator adapter → pure 계약 방향을 유지한다. worker는 이
    테이블·NAS·Identity에 접근하지 않고 이 기능에 Codex 슬롯/AI를 추가하지 않는다.
11. 단순 대안: boolean callback 허용이나 이름/filename 매칭은 근거가 없다. 별도 intake queue와
    다중 command 테이블은 기존 admission/publication receipt와 중복이다. 작은 channel pin만
    새로 두고 나머지는 현재 owner를 재사용한다. 이 절은 source 구현 설계이며 운영 승인 증거가 아니다.

## MANUAL 방 근거에서 수집 capability를 고정하는 최소 owner

1. 책임은 Catalog의 `KakaoCapabilityService`다. 이미 수락된 MANUAL room observation과
   그 source proof를 검증해 기존 worker `CaptureCapability`를 발행한다. 임의 capability JSON,
   worker bool, 사용자 path·adapter hash를 받지 않는다. 현재 actor/ADMIN/COLLECT 검사는 필수다.
2. 정본은 기존 Artifact의 방 관측·원래 수신 proof와 새 capability JSON/verification이다.
   DB에는 불변 수락 한 row만 두고 본문·사진·전체 관측 JSON은 넣지 않는다.
3. capability revision은 owner/binding/idempotency key에 대한 독립 UUID다. 파일 SHA와 다르며,
   Artifact/revision도 별개다. 동일 명령의 발행 중단을 이어가기 위해 UUID5로 예약 identity를
   결정하되 request hash 충돌은 기존 publication과 DB unique로 거부한다.
4. 원래 방 관측·proof의 schema/media/hash와 방·채널 pin·MANUAL lease/fence·시각·현재 권한을
   재검사한다. completed replay는 채택한 Artifact만 읽고 temporary download 파일을 요구하지 않는다.
   바뀐 정책/version은 새 수락 전에 확인하고 과거 완료 receipt를 최신 값으로 바꾸지 않는다.
5. access는 owner/binding/key와 exact capability revision의 indexed lookup, bounded JSON 읽기다.
   `kakao_capability_acceptances` 한 테이블만 추가한다. mutable current/activation head나 새 큐는
   아직 필요 없으며 이후 collection run이 사용할 exact revision을 명시적으로 pin한다.
6. 첫 관측의 검증 비용은 작은 JSON bytes에 선형, metadata lookup은 indexed O(log n)이다.
   동일 수신 JPEG를 다시 복사·decode·hash하지 않고 원래 proof pointer를 worker input 경계에서 해석한다.
   초기 수백 binding·수만 capability revision을 가정하며, 이는 설계 규모이고 현재 운영 수치가 아니다.
7. 파일 발행 동안 DB lock을 잡지 않는다. 현재 scope 확인 → 기존 idempotent publication →
   짧은 owner/key 잠금과 늦은 재인가 → 불변 수락 row 순이다. 같은 key의 동시 요청은 같은 revision이다.
8. worker에는 기존 `capability.json`과 `inputs/manual-room-proof.json` local member만 전달할 수
   있게 한다. 이 절의 owner는 아직 worker를 실행하거나 NAS 경로/권한을 worker에게 주지 않는다.
9. MANUAL proof가 확인하는 것은 채널과 그 방뿐이다. 내부 scope `MANUAL_SELECTED_ROOM`은
   사용자가 확인한 단일 방을 뜻하며 카카오 UI 필터명이나 전체 방 목록이 아니다. CSV 범위·순서·
   시간대·발신 방향·메시지 identity·album·원본 화질·읽음 여부는 UNKNOWN으로 고정한다.
   더 강한 관측은 실제 adapter 실증에 따른 successor이며 임의 request로 상향하지 않는다.
10. 실패/중단은 원래 Artifact와 기록을 보존한다. 첫 수락 중 binding version/권한 변경은
    채택하지 않으며 재발행/새 작업으로 우회하지 않는다. 조회는 실행·activation·로그인을 하지 않는다.
11. 수락된 capability는 **자동 수집 활성화가 아니다**. 기존 DRAFT/NOT_VERIFIED DTO를 고쳐
    ACTIVE로 위장하지 않는다. 완전한 collection owner/원격 실행/실제 UI capability 검증과 guarded
    activation이 남아 있다. 별도 registry framework나 boolean 승인 callback보다 이 작은 owner와
    기존 Artifact/Room/Identity 경계를 재사용하는 방식이 단순하다.

2026-11-16에 열람한 [카카오 공식 채팅 가이드](https://kakaobusiness.gitbook.io/main/channel/run/chat)의
목록 필터 설명은 기간 조건을 최근 대화 시점 기준으로 안내한다. 이를 질문 기간으로 그대로
적용하면 필요한 방을 누락할 수 있다는 것은 설계상 추론이다. 따라서 전체 방 수집과 질문 단위
구성 뒤의 출력 기간 선택을 분리한다. 열람한 가이드에서는 CSV `USER` 열의 발신 방향 의미나
실제 export 범위의 검증 근거를 확인하지 못했으므로, 문서만으로 capability를 상향하지 않는다.

## Collection intent와 공용 profile gate 연결

1. Catalog collection owner가 현재 실제 ADMIN/READ/COLLECT로 단일 방 수집 의도를 접수한다.
   첫 public command는 `KakaoRoomCollectionCreate`다. 이는 전체 방 수집의 대체물이 아니라
   실제 한 방 실증을 위한 첫 단계이며, 전체 목록 수집·주기 실행은 여전히 완료 조건이다.
2. 원본은 기존 Artifact이며 run/task/attempt/browser epoch에는 작은 ID·pin·state만 저장한다.
   새로운 범용 큐나 Job 상태 enum을 만들지 않는다. 처음 선택한 room/capability/policy는 불변이다.
3. 하나의 run이 순서 있는 task를 소유하고 한 번에 하나만 실행한다. browser epoch는 실제
   persistent context의 identity/lifecycle이다. 여러 방의 command가 같은 browser/fence를 사용할
   수 있으므로 `unique(profile,fence)`는 browser epoch에 두고 attempt에 두지 않는다.
4. profile은 기존 `kakao_profile_runtime` 한 gate를 재사용한다. AUTO current-browser pointer만
   추가하고 MANUAL lease와 동시에 소유할 수 없게 한다. DB 예약 뒤 실제 OS 시작/종료는 기존
   Orchestrator adapter가 관측한다. 시간 만료나 DB 예약 자체를 프로세스 실행·종료로 보지 않는다.
5. primary access는 owner/binding/key replay, active run lookup, run별 ordered task claim, exact
   epoch/attempt lookup이다. unique/partial B-tree와 FK를 사용한다. 초기 수천 방/run, 수만
   attempt 이력을 가정하며 본문 list scan이나 N+1은 없다. 상태 집계는 run별 bounded aggregate다.
6. source/파일 I/O 중 DB lock은 잡지 않는다. profile 예약 순서는 binding → 기존 installed-profile
   advisory gate → profile → run이다. 실제 runtime을 관측한 뒤 같은 epoch/pointer를 CAS로 수락한다.
   source 발행은 기존 publication intent를 재사용하며 worker 재실행과 구분한다.
7. background 권한은 원래 HTTP session의 만료와 분리한다. owner는 **저장된 run/task 참조**에서
   읽고 현재 Identity ACTIVE/ADMIN/READ/COLLECT·binding·capability·policy를 재검사한다. worker가
   owner/role/session을 주장하거나 새 OPERATOR ActorContext를 가장하지 않는다. 내부 참조는
   public RPC/worker 입력에서 생성할 수 없다. 공개 요청의 기존 session 검증은 그대로 유지한다.
8. 첫 actual binding/profile owner는 보존한다. 같은 Studio owner가 STOPPED profile로 다른
   자기 binding을 선택할 수 있도록 MANUAL history의 profile FK와 binding FK를 분리한다.
   과거 lease를 현재 binding에 종속시키지 않으며 다른 owner로 profile을 넘기지 않는다.
   actual channel identity는 기존 수락 proof와 매 실행 관측으로 검증하고 이름으로 선택하지 않는다.
9. unknown dispatch/살아 있는 worker는 같은 epoch를 조회한다. 새 browser/attempt를 자동
   생성하지 않는다. 명시적 중단·권한 상실은 profile을 붙잡은 채 종료 관측을 거치며 FAILED는
   보존한다. 이미 검증된 local output의 발행 복구와 실제 재수집 retry는 다른 경계다.
10. 계층은 기존 API → Catalog application/state → typed contract, Orchestrator OS adapter다.
    worker는 local command/result만 사용한다. 새 browser service나 Codex 슬롯을 추가하지 않는다.
11. 더 단순한 run row 하나에 모든 방/프로세스/attempt를 덮어쓰면 재개 위치와 실제 프로세스
    identity를 잃는다. 반대로 room마다 브라우저를 재시작하는 구조도 불필요하다. 작은 run/task/
    attempt/epoch 관계만 두고 실제 UI selector·source 수락·전체 방 실행은 각 단계에서 검증한다.

### 0091의 첫 구현 범위: 수집 의도와 방별 checkpoint

`collection-intent-v1` schema를 먼저 정의하고 `KakaoCollectionService`가 현재 실제 API
actor의 ADMIN/READ/COLLECT·binding/room 권한으로 한 방의 의도를 접수한다. 실제 수락된
capability owner의 canonical proof를 DB lock 밖에서 해석한 뒤, 같은 방·scope·설치 adapter를
확인한다. 짧은 owner/key → binding → room transaction에서 늦은 권한/version을 다시 확인하고
run과 첫 QUEUED task를 함께 저장한다. 첫 단계의 scope는 MANUAL_SELECTED_ROOM이며 전체
방 inventory의 대체물이 아니다. 실제 수집 활성화·브라우저 실행·정본 수락 권한을 만들지 않는다.

DB에는 `kakao_collection_runs`와 `kakao_collection_tasks` 두 작은 metadata 테이블만 추가한다.
run은 원래 request/version·policy hash·capability revision·adapter pin·owner를 보존하고
current state/version만 이후 갱신할 수 있다. task는 방/순서 identity를 보존한다. 기존 room/
capability/policy FK, same-key unique, nonterminal binding partial unique와 (run,state,ordinal)
인덱스를 사용한다. deferred 초기 task guard가 run만 저장되는 것을 막으며 terminal row·원래
pin·순서의 UPDATE/DELETE를 거부한다. 본문/사진/큰 JSON·NAS path·인증정보를 넣지 않는다.

접근 패턴은 indexed exact run/key lookup·방별 중복 차단과 정렬된 checkpoint다. 수락/재조회는
고정 개수의 indexed metadata 조회이며 첫 capability 해석만 bounded JSON bytes에 선형이다.
초기 scale은 연결당 수천 방·수만 attempt를 가정한다. 같은 요청 replay와 상태 GET은 이미
수락된 capability를 새 파일로 발행하거나 브라우저를 실행하지 않는다. 요청 body가 다르면
conflict이고 다른 key의 unfinished run은 명시적 pending 오류다. 더 단순한 process-local dict는
재시작/동시 접수에 부족하며, 별도 command table/queue는 원래 run receipt와 중복이라 만들지 않는다.

`read_background_intent`는 오직 trusted owner composition의 **준비용 metadata read**다.
owner는 저장된 run에서 읽고 Identity의 현재 ACTIVE/ADMIN/READ/COLLECT를 재확인한다.
원래 HTTP 세션의 만료를 무시한 새 ActorContext/session을 만들지 않으며, public 조회는 계속
유효한 현재 session을 요구한다. 계정/권한 철회·retired binding/room·정책 변경·adapter 불일치·
terminal run은 신규 준비를 거부한다. 과거 receipt는 최신 정책/adapter로 바꾸지 않는다.

이 metadata에는 actual attempt/profile fence·원본 source authority가 없다. 전체 capability
evidence closure의 byte materialization/재인가는 실제 실행·수락 직전에 기존 owner가 수행해야
한다. **이 read만으로 browser launch/source admission을 허용하면 안 된다.** 기존 공용 profile
gate의 AUTO 소유, 실제 epoch/attempt, guarded activation과 full inventory·주기 실행은 다음
구현이다. 이 첫 단계가 검증돼도 DRAFT/NOT_VERIFIED·AUTO 비활성은 그대로다.

### 다음 연결: 공용 프로필과 실제 collection browser epoch

- 기존 `kakao_profile_runtime`을 단일 gate로 유지한다. collection browser epoch 한 테이블과
  profile/run의 current pointer만 추가한다. worker task/attempt, source authority나 별도 queue를
  이 record로 대체하지 않는다. epoch는 process lifetime, task는 수집 작업 identity다.
- worker가 받는 고정 입력은 기존 `ProfileFence` schema를 재사용한다. owner 간 intent/
  running/closure 관측은 새 `collection-browser-v1`의 작은 typed metadata이며 public/worker가
  보낸 bool을 authority로 받지 않는다. 실제 OS 관측 callback은 필수이고 lock 밖에서 실행한다.
- same-owner의 다른 binding 전환을 위해 MANUAL history의 (owner,binding,profile) FK를
  (owner,profile)와 (owner,binding)로 분리한다. 과거 lease/수신물은 수정하지 않는다. 실제 정지·
  profile lock 해제 확인 전이나 다른 owner로는 바꾸지 않는다. 채널 identity는 별도 관측이다.
- binding → 기존 installed-profile advisory gate → profile → run → epoch 순서로 잠근다.
  시작 예약은 AUTO 소유와 증가 fence를 원자적으로 고정한다. 재조회는 같은 epoch를 반환하고
  불명확한 이전 dispatch/이미 CLOSED인 원래 run을 새 browser로 자동 재생성하지 않는다.
- (profile,fence), (run,epoch_number), non-CLOSED profile의 partial unique와 exact current
  FK를 사용한다. 접근은 indexed lookup이며 큰 payload·원문·사진·인증정보는 저장하지 않는다.
  수천 방을 같은 browser lifetime에서 순회할 수 있고 room마다 browser를 재시작하지 않는다.
- PREPARING/RUNNING/STOPPING/CLOSED와 version으로 관리한다. running 관측의 실제 boot/
  invocation/PID/monotonic start가 고정되고, stop timeout은 CLOSED가 아니다. 종료 callback의
  정확한 실행·gateway 정지·profile lock 해제·freshness를 확인해야만 profile을 반환한다.
- closure와 cleanup은 이미 접수된 epoch로 수행하므로 계정/정책 철회 뒤에도 실제 프로세스를
  정지할 수 있다. 새 실행 준비/수락은 현재 accepted run의 권한·policy/adapter pin을 재검사한다.
  HTTP session이나 worker actor를 가장하지 않는다. terminal epoch와 과거 실패는 보존한다.
- epoch 예약/시작만으로 상위 run이나 문항 수집이 완료되지 않는다. parent run의 수집 상태는
  실제 command/task owner가 관리한다. browser 종료는 current pointer만 반환하며 자동 retry·
  source 수락·guarded activation은 후속 경계다. DRAFT의 예약도 AUTO 실증/활성화가 아니다.
- 이 claim은 실제 방→CSV/사진→질문/PDF 경로를 위한 선행 저장 경계다. 현재 core/remote와
  같은 OS adapter를 재사용하고, 실제 selector나 원격 브라우저를 fixture 근거로 활성화하지 않는다.
- process-local bool lock이나 두 번째 AUTO 전용 mutex는 재시작/MANUAL 경합에 부족하다.
  반대로 browser record에 방별 result를 복제하거나 새 runtime service를 만드는 것도 불필요하다.
