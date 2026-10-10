# 문항 핵심 착상 전이 — 후속 owner 호출부 설계

상태: **SOURCE_IMPLEMENTED / LIVE_ACCEPTANCE_PENDING**. 2026-10-10 UTC.
네 번째 checkpoint의 소스 연결을 실제 bounded 실험에 잇기 위한 설계다. 이 문서는 새 API,
private operation, 권한, control release, 모델 실행 또는 배포를 활성화하지 않는다.

## 현재 경계

인증 snapshot API/private Catalog producer와 전용 Runner executor는 소스에서 연결됐다.
다음 네 호출부가 후속 범위다. 기존 owner를 연결하는 최소 구현만 추가하고, 별도 registry,
queue, search engine, framework 또는 일반 사용자 UI를 이 단계에서 만들지 않는다.

1. 인증된 snapshot client → pure staging port와 명시적 오류 매핑: **source 구현·검증 완료**.
2. staging → 보호된 local input → CPU port → 최종 source 재인가 → owner Artifact commit:
   **source 연결·검증 완료**, 고정 staging/main CPU unit과 launcher도 소스에 추가했다.
   실제 설치·privileged 격리 검증은 미실행이다.
3. 선택된 두 profile → 실제 principal의 Workflow 제출 및 목적 전용 결과 조회:
   **source 구현·검증 완료**, authenticated installed 실행은 미실행.
4. 검토된 bootstrap 입력 → 실제 control-permission authorizer/publisher → 명시적 PREPARE/RELEASE:
   인증된 보호 owner CLI composition을 소스에 추가했다. 실제 인증·발행·RELEASE는 **대기**다.

검증 결과와 잔여 한계는 [다섯 번째 checkpoint](ITEM_INFERENCE_TRANSFER_FIFTH_CHECKPOINT.md)에
기록한다. 소스 연결을 모델 실행·NAS publication·운영 활성화로 해석하지 않는다.
실제 guiadmin 승인 이후 인증 HTTP/owner CLI·CPU 설치 경계와 운영 관측은
[여섯 번째 checkpoint](ITEM_INFERENCE_TRANSFER_SIXTH_CHECKPOINT.md)에 구분해서 기록한다.

## 필수 설계 결정

1. **책임·경계:** snapshot/결과 bytes의 권한 있는 resolution은 Catalog, 실제 operator/session은
   API, protected staging·실행·검증된 Artifact commit은 Orchestrator, command/lease/Workflow
   state는 기존 Runner가 소유한다. Router·CLI는 입력 검증·표현·composition만 수행한다.
   Workers에는 NAS/DB/다른 worker 권한을 주지 않는다.
2. **정본:** 기존 approved source, accepted solution-report chain, exact Graph/policy와
   Orchestrator가 commit한 `result.json`/ArtifactManifest가 정본이다. 실험과 profile은 파생물이다.
   DB의 `revision.result` metadata JSON을 canonical Artifact member 대신 반환하지 않는다.
3. **identity·revision:** public comparison request ID, Workflow ID, profile logical/revision ID,
   Artifact ID/revision, manifest/member SHA, initial permission digest와 현재 권한을 분리한다.
   Snapshot header/hash는 identity closure이며 credential이 아니다.
4. **입력·resolution:** public selected-pair DTO는 schema-first로 기존 `PairComparisonRequest`,
   actor 없는 `SnapshotPrepareRequest`, expected exact header hash 정도를 담는다. Public 입력에
   actor/role/permission/preset/완전한 profile bytes를 받지 않는다. 현재 PREPARE index에서 exact
   두 pointer를 찾아 READ로 재생성하고 server가 wrapper/context를 만든다. Source·report·rubric·
   Graph·policy·schema·media·member·hash·lifecycle·현재 권한을 확인한다. Hash/권한 실패는 latest로
   바꾸지 않는다. 구현 전에 공개 DTO와 새 private result-read를 JSON Schema 2020-12로 정의한다.
5. **access pattern:** frozen index 생성, exact 두 profile lookup, current source authorization,
   indexed idempotency/Workflow/Job/Step lookup, ordered local materialization, append-only
   result/history가 주 경로다. Snapshot/result 조회는 현재 actor 권한으로 매번 실행한다.
6. **자료구조·index:** profile/source map과 membership set, frozen tuple, existing indexed
   request/command/lease/Artifact relations를 사용한다. 새 queue/index는 만들지 않는다.
   현재 1,024-source/선택 두 개 상한에서 index 구성 O(N), lookup 평균 O(1), embedding O(Nd).
   기존 query plan을 재사용하고 중복 전체 profile payload나 raw byte 캐시를 만들지 않는다.
7. **규모·예산:** 기존 64 KiB wrapper, snapshot frame/chunk/누적 64 MiB, member/batch 한도를
   보존한다. 실제 corpus 처리량·token overflow를 측정하기 전 chunk/facet 의미를 바꾸지 않는다.
   CPU/model/worker/read/replay 횟수를 분리한다. Worker 호출 수와 compatible runtime/권한 범위는
   live 실행 직전 명시한다. 새 문항 생성·기출 재학습·HWPX 생성은 이 실험 범위가 아니다.
8. **transaction·concurrency:** 기존 transaction에서 Workflow 생성과 START_WORKFLOW command를
   함께 기록한다. 실제 구현은 같은 transaction에서 V21도 고정한다. 현재 permission digest가
   바뀐 concurrent replay를 안전하게 처리하는 기존 PostgreSQL transaction advisory lock을
   요청 key 하나에만 적용하며, unique constraint/savepoint/replay/Runner fence를 재사용한다. HTTP read,
   local model 실행과 NAS commit을 하나의 distributed transaction이라고 부르지 않는다.
   최종 source 재인가 직후 기존 commit owner가 출력을 검증·등록하며 partial publication과
   failed history는 보존한다.
9. **의존성·adapter:** router → 작은 application use case → typed read/start/result/commit ports.
   기존 Catalog socket, SQL repository, identity, protected filesystem, local subprocess와
   ControlArtifactPublisher는 각 경계의 infrastructure adapters다. API가 Catalog private
   helper나 NAS를 읽지 않는다. Optional CPU adapter가 없어도 기존 출제/RAG/검토는 동작한다.
10. **failure·retry·idempotency:** 현재 source 재인가는 HTTP cached replay보다 먼저 수행한다.
    `routers/common.run_command`의 replay는 callback을 실행하지 않으므로 callback 안에만
    authorization을 두면 안 된다. Replay에서 현재 permission SHA로 옛 wrapper를 새로 만들어
    conflict를 일으키지 않는다. 원래 서버 capture SHA는 provenance로 유지하고 현재 권한은
    별도로 확인한다. Timeout 뒤에는 동일 identity를 조회/replay하며 새 key로 우회하지 않는다.
    Control PREPARE는 DRAFT만, RELEASE는 별도 실제 NON_LIVE 검증으로 수행한다.
11. **더 단순한 대안:** 기존 `CommandResult`와 Workflow 상태 DTO는 재사용하지만
    `WorkflowStartRequest`/출제 `CommandAdapter.start_workflow`는 Item/Pack/이미지 의미를 강제하므로
    비교 요청을 숨겨 넣지 않는다. 같은 이유로 snapshot READ에 worker 결과를 숨기지 않는다.
    API 전역 WORKFLOW_READ나 cached 성공을 comparison content 권한으로 삼는 방식은 부적절하다.
    작은 목적 전용 leaf·closed DTO·기존 owner adapters가 최소 연결이다.

## 제출과 결과의 실제 권한

제출은 현재 실제 operator의 WORKFLOW_START, ITEM_READ, KNOWLEDGE_GRAPH_RETRIEVE,
KNOWLEDGE_ANALYSIS_READ, PAST_EXAM이면 CONTENT_INTAKE_READ와 pinned released policy의
answer-bearing role을 요구한다. 현재 기본 역할 중 ADMIN이 이 조합을 갖지만, 구현은 ADMIN
역할을 위장하거나 hardcode하는 것이 아니라 **현재 실제 permissions와 policy**를 검사한다.
기능을 성공시키기 위해 다른 역할 권한을 자동 확대하지 않는다.

결과 조회는 exact Workflow/Step/Job/V21/comparison lineage, 현재 원본 접근과 실제 caller를
확인하는 목적 전용 boundary를 사용한다. 기존 global `GET /workflows/{id}` 상태 조회는 비교
내용을 공개할 근거가 아니다. Pointer-only 조회와 canonical member-read 완료를 구분한다.
Owner가 `CatalogArtifactService.load_json_revision(artifact_id, revision_id, content_hash, max_bytes)`
등 기존 정식 structured Artifact resolution으로 `result.json`을 검증한 뒤에만 typed
`PairComparisonResult`를 반환한다. 이 manifest를 file-set용 member resolver에 억지로 맞추지 않는다.

## 구현·검증 순서

1. 실제 인증 경로를 가진 snapshot staging adapter와 safe protected local materialization을 연결한다.
2. 기존 offline harness 입력/결과 pins를 검증하고, 현재 actor의 final AUTHORIZE와 기존 owner commit을 연결한다.
3. selected-pair public submission/result-read의 closed schema를 먼저 추가한다. 기존 submit response,
   indexed repository, Runner queue를 재사용하며 source 재인가가 HTTP replay보다 앞에 오게 한다.
4. Bootstrap leaf에 실제 current control authorizer와 publisher를 owner composition으로 공급한다.
   초기 exact version만 취급하고 기존 support/PDF preset을 바꾸거나 자동 successor를 만들지 않는다.
5. Source/fake-port/format/lint/type/dependency 검증, 필요할 때만 guarded PostgreSQL concurrency,
   installed wheel/RECORD/compatible release를 확인한다. 이후 실제 authenticated bounded canary와
   corpus 비용/Graph/세 표현 실험을 수행한다. Human label 없이는 recall/전이 품질 PASS를 선언하지 않는다.

필수 회귀: current 권한 회수 뒤 HTTP replay 거부, 다른 사용자 결과 접근 거부, missing/stale/member/hash
불일치, source drift, immutable exact replay, concurrent 단일 제출, lease fence, partial commit,
bounded input/output, secret-safe failure, 기존 출제/support/PDF/Graph 의미 보존.

## 확인된 기존 인터페이스

- API `routers/workflows.py`, `routers/common.py`, `services/idempotency_service.py`
- `packages/api_contracts/eom_api_contracts/common.py`의 `CommandResult`
- Runner `repository.create_workflow_instance`, `enqueue_command`
- Workflow `InferenceTransferWorkflowRequest`/서버 `InferenceTransferSubmissionContext`
- API `InferenceTransferSnapshotApplicationService.execute(authentication, request)`
- Orchestrator `stage_snapshot_experiment`, `reauthorize_staged_experiment`
- Runner `PlatformInferenceTransferExecutor`
- Catalog `CatalogArtifactService.load_json_revision`
- Orchestrator `prepare_inference_transfer_controls`, `release_inference_transfer_controls`

## 실제 운영 호출부의 추가 점검

2026-10-10 UTC 최초 읽기 전용 inventory와 그에 따른 설계 입력이다. 아래의 당시 누락은
후속 소스 결정으로 보강했지만 실제 설치·인증·실행을 완료했다는 뜻은 아니다.

- Bootstrap은 `ControlArtifactPublisher.publish_bytes`를 사용하고 CPU 실험 결과는
  `ControlFileSetPublisher`를 사용한다. 서로의 manifest/permission 의미로 대체하지 않는다.
- 현재 control 권한은 기존 `SqlAlchemyOperatorActorSource.load`와
  `OperatorIdentityWorkflowActorAuthorizer.authorize(..., EXECUTION_PRESET_MANAGE)`로 재확인할 수
  있다. 하지만 ID 조회는 인증이 아니므로 실제 로그인 경계에서 얻은 principal만 연결한다.
  기존 CLI의 임의 `--actor-id`나 전권 ActorContext 생성은 권한 증명으로 재사용하지 않는다.
- API의 `/mnt/nas` 격리는 유지한다. Bootstrap 호출을 연결하려고 API에서 publisher를 실행하거나
  account OBSERVE/ENABLE/DRAIN/DISABLE queue에 bootstrap을 숨겨 넣지 않는다. 전용 호출부 및
  검토된 최초 bootstrap config는 아직 없다.
- CPU launcher는 기존 `worker_systemd.py`, `source_pdf_crop_processing.py`,
  `sdxl_probe_workspace.py`의 고정 unit·interpreter·clean environment·uncertain 판별 패턴을
  참고할 수 있다. GPU/PDF launcher를 다른 목적·UID·환경의 embedding 실행으로 위장하지 않는다.
- 현재 owner workspace와 offline CLI는 자기 EUID 소유를 요구한다. 별도 unprivileged CPU UID를
  연결하기 전에 worker input/output handoff를 명시적으로 설계하고 검증해야 한다. Owner-private
  workspace의 소유권 검사를 완화하거나 worker output을 곧바로 정본 owner 파일로 간주하지 않는다.
  별도 handoff는 임시 materialization이며 canonical publication은 계속 기존 owner가 수행한다.
- 실제 전용 CPU 환경·libexec·sandbox unit·제한된 시작 권한 경로는 아직 확정하지 않았다.
  모델/runtime 설치 및 OS 격리 negative 검증은 source 테스트나 임시 toy 실행으로 승인하지 않는다.

관련: [구현 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md),
[네 번째 checkpoint](ITEM_INFERENCE_TRANSFER_FOURTH_CHECKPOINT.md).
이 문서에는 운영 자료·자격 증명·worker 내용·실제 품질 판정이 없다.

## 남은 소스 경계의 최소 구현 결정

2026-10-10 UTC. 아래는 설치·실행 승인이 아니라 소스 구현 결정이다.

1. **책임·경계:** CPU 입력 전달은 고정된 privileged staging unit, 모델 forward는 별도
   unprivileged CPU unit, 결과 수용·재인가·publication은 기존 Orchestrator가 담당한다.
   Control bootstrap은 기존 보호된 Orchestrator owner CLI에서 수행한다. Catalog에 control
   쓰기 권한을 추가하거나 API의 NAS 격리를 풀지 않는다.
2. **정본:** root runtime handoff는 임시 복사다. 기존 owner-private request와 검증된 owner
   result/publication만 기존 Artifact commit에 전달한다. Control 입력은 이미 정의된 reviewed
   bootstrap manifest/원문 bytes, 출력은 기존 published control pointers와 exact preset이다.
3. **identity·revision:** 두 고정 unit은 같은 `embeddingexecution_…`를 사용한다. Local markers는
   여전히 임시 실행 관측일 뿐 durable queue가 아니다. Bootstrap PREPARE receipt는 새 closed
   schema로 manifest와 기존 exact prepared pointers/preset 및 receipt hash를 묶는다.
4. **resolution:** root staging은 고정 owner root만 dir-FD/O_NOFOLLOW로 열고 owner UID,
   0700/0600, regular/single-link, byte bound와 named inode를 확인한다. Root-owned runtime
   parent에만 O_EXCL로 input/output를 만들며 PID1은 그 경로만 연다. CPU는 inherited stdin/stdout만
   사용한다. Owner는 confirmed terminal observation 뒤 root-owned output를 bounded FD read하고
   자기 private `result.json`을 O_EXCL600으로 materialize한다. 이전 workspace 검사 완화는 없다.
5. **access pattern:** exact execution lookup, ordered bounded byte transfer, 현재 auth 조회,
   exact receipt replay다. FIFO/새 registry/새 queue는 없다. 기존 publisher의 indexed publication
   idempotency와 control transaction lock을 유지한다.
6. **자료구조·index:** 고정 unit name과 frozen typed observations, 기존 typed experiment request/result,
   prepared receipt를 사용한다. Filesystem handoff는 execution별 directory와 고정 member 두 개다.
   DB index/migration/신규 grant는 필요 없다.
7. **규모·복잡도:** 기존 input/result 64 MiB bound를 유지한다. Byte transfer와 hash는 O(B),
   metadata lookup은 O(1), bounded materialization 공간 O(B)다. 파일 한 번씩 전달은 명시적
   trust/materialization boundary이며 추가 canonical copy나 cache가 아니다.
8. **transaction·concurrency:** owner의 exclusive launch marker와 기존 publication boundary를
   사용한다. Staging/main units는 exact identity에 대해 RemainAfterExit를 유지해 종료 후
   재시작으로 같은 forward를 반복하지 않는다. 이는 distributed exactly-once 증명이 아니다.
   Source 권한 확인, local execution, Artifact publication은 별도 관측/commit 경계다.
9. **의존성·adapter:** installed `-I -m` CPU harness와 고정 systemd adapter만 추가한다. 기존
   experiment JSON schema를 재사용하며 새 CPU worker protocol은 없다. Control owner는 existing
   API `/api/v1/auth/me` typed contract를 fixed loopback/no-proxy/no-redirect/bounded read로 호출하고
   실제 operator/session을 얻는다. 토큰은 별도 FD로 받고 argv/env/receipt/log에 넣지 않는다.
   연결 뒤 token을 보내기 **전에** Linux exact reverse four-tuple peer socket UID를 확인해
   설치된 `eom-api` UID에 묶는다. Listener나 HTTP 200만으로 서버 identity를 추정하지 않는다.
   이 검사가 불가능하면 닫으며 API secret을 읽는 fallback은 없다.
   외부 dependency는 추가하지 않는다. 실제 owner auth adapter는 기존 별도
   `eom-api-contracts==0.1.0` wheel을 optional `inference-transfer` extra로 명시한다.
   이유는 공식 CurrentOperator/SingleResponse 계약을 복제하지 않고 재사용하기 위해서다.
   같은 package version만으로 호환성을 증명하지 않으며 release set의 source/wheel SHA를 pin한다.
   Core와 CPU adapter에는 이 의존성을 강제하지 않고 새 CLI command에서만 지연 로딩한다.
10. **failure·retry·auth:** CPU timeout/불명확한 terminal 상태는 UNCERTAIN이며 자동 재실행하지 않는다.
    Partial handoff는 덮어쓰지 않는다. Control 호출은 실제 auth가 유효한지 각 publication/최종
    transaction 전에 재확인하고 현재 ACTIVE/ADMIN/EXECUTION_PRESET_MANAGE를 재조회한다.
    Principal/session 교체·만료·password-change-required는 거부한다. PREPARE와 RELEASE는 별도
    명령이며 caller-supplied actor/time/authority와 auto release는 없다. 실패 publication history는 보존한다.
11. **더 단순한 대안과 배제 이유:** owner-writable path를 `StandardInput=file:`로 PID1에 직접
    넘기면 privileged open의 symlink 우회가 가능하다. systemd v255는 O_NOFOLLOW를 적용하지
    않으므로 두 fixed unit이 필요하다. Worker에 owner group/DB/NAS 권한을 주거나 소유 검사를
    완화하는 대안은 배제한다. Bootstrap을 Catalog에서 실행하면 불필요한 control DB grant가
    필요하므로 기존 owner와 실제 auth read를 결합한다. 임의 `--actor-id` 조회는 인증이 아니다.

두 unit/CPU environment/protected entrypoint 설치, polkit 제한 start grant, 실제 auth와 control
publication 및 OS negative smoke는 별도 운영 gate다. Source/fake tests를 LIVE PASS로 쓰지 않는다.

### 기존 CLI 의존성의 별도 한계

API contracts가 없는 fresh interpreter에서 기존 control-plane/codex-runtime help와 새 command의
안전한 거부를 검증한다. 그러나 기존 최상위 `eomctl.cli → legacy_assessment → eom_api.build_info`
경로는 원래 API contracts에 의존한다. 이번 optional adapter 변경으로 그 기존 문제까지
해결했다고 주장하지 않으며 관련 코드는 변경하지 않는다. 운영 owner에는 검증된 호환 API
contracts wheel이 필요하다.

## guiadmin 승인 이후 실제 호출 연결

2026-10-10 UTC. 사용자는 `guiadmin`으로 운영 설치와 제한된 비교 실험 진행을 승인했다.
이는 계정 사칭·비밀번호 추측·브라우저 session token 추출을 허용하지 않는다. 최초 운영
점검에서 interactive login과 authenticated HTTP snapshot→protected owner 호출부가 아직
없음을 확인했다. 아래 최소 연결을 구현한 후 검증된 새 release identity로 설치한다.

1. **책임:** console은 실제 비표시 비밀번호 입력과 typed command 전달만 한다. 공식 API가
   로그인·현재 사용자·snapshot source 권한을 확인한다. 보호된 Orchestrator application이
   기존 execution composition/CPU launcher/Artifact publisher를 호출한다.
2. **정본:** 기존 accepted source/Graph/policy와 owner commit이 그대로 정본이다. 실제 user
   login은 API session이며 로컬 username/actor 문자열이나 OS UID로 대체하지 않는다.
3. **identity:** 실제 operator/session, reviewed command/execution, exact model/Graph/policy와
   Artifact hashes를 분리한다. 동일 실행의 완료 output은 새로운 로그인 후에도 같은 operator의
   현재 권한으로 재인가해야 하며 CPU를 다시 호출하지 않는다.
4. **resolution:** 기존 fixed loopback의 TCP peer UID 검사를 secret 전송 전에 재사용한다.
   `/auth/login`, `/auth/me`, snapshot의 기존 JSON Schema/Pydantic 계약과 bounded body/context를
   검증한다. Password/token은 memory·inherited FD만 사용하며 argv/env/file/log에 저장하지 않는다.
5. **access pattern:** exact principal·request·source lookup, bounded ordered snapshot 읽기,
   encode-once, exact replay/append-only receipt다. 새로운 queue/search/session store는 없다.
6. **구조:** 기존 frozen StageCommand/model/budget/request/result와 작은 session adapter를
   재사용한다. 전역 mutable token registry나 duplicate source cache는 만들지 않는다.
7. **규모:** 최초 actual original past-exam 모집단은 최대 1,024 sources, 질의 최대 4개,
   top-K 8, batch/thread 4, 입력 64 MiB, snapshot frame 3 MiB로 제한한다. 최초 Codex 비교는
   최대 2쌍이다. 실제 source/encoding coverage가 부족하면 축소·요약으로 PASS를 만들지 않는다.
8. **transaction:** 공식 login, typed read, CPU 실행과 Artifact commit은 별도 경계다. 기존
   prepare/claim/lease/unique/commit을 사용한다. HTTP timeout 뒤 state-changing 요청을 자동
   재전송하지 않는다. UI/worker 기존 활성 설정이나 역사적 실행은 바꾸지 않는다.
9. **dependency:** optional API contracts와 표준 HTTP adapter만 추가 연결한다. CLI→application
   →기존 ports/composition 방향을 유지한다. Worker는 staged local bytes만 사용한다.
10. **failure/retry:** 만료/회수/다른 principal/uncertain refresh는 명시적으로 멈춘다. 자동
    refresh/relogin/새 execution 우회는 없다. 완료 workspace를 보존하고 실제 재로그인 후 같은
    identity의 supported replay를 사용한다. Fresh control 승인 15분과 API token/CPU time은
    서로 다른 경계다. Secret-bearing traceback은 출력하지 않는다.
11. **대안:** server-only AccessAuthentication adapter를 owner에 가져오려면 API secrets나
    server 내부 권한을 복제해야 하므로 배제한다. Root DB로 source pointer를 만들거나 브라우저
    token을 읽는 우회 대신 기존 공식 HTTP 계약과 owner composition의 작은 연결을 사용한다.

Full Graph pointer/정책 핀은 이미 승인된 official resolver/read 경계에서만 얻는다. 아직 없는
discovery API를 있다고 가정하거나 revision/hash로 Artifact pointer를 합성하지 않는다. Protected
CPU 설치는 exact reviewed model/runtime, 별도 worker UID, no NAS/DB/network/GPU 및 privilege
negative smoke를 확인해야 한다. 실제 품질·human label은 계속 별도 gate다.

### 최초 설치 점검에서 확인한 환경 경계

기존 `/srv/eom/conda/envs`는 개발 계정 소유이므로 privileged launcher의 root-owned
ancestor 검사를 만족하지 않는다. 이를 맞추려고 기존 서비스 환경의 소유권이나 검사 규칙을
바꾸지 않는다. 전용 prefix는 `/opt/eom/conda/envs/eom-embedding-experiment`, 모델 저장소는
`/opt/eom/embedding-models`로 분리한다. Prepare와 CPU는 검증된 같은 전용 Conda Python을
쓰되 서로 다른 OS identity와 sandbox를 유지한다. 설치용 bootstrap과 실제 실행 환경의
검증은 구분하며, mutable 개발 환경의 interpreter를 root로 실행하지 않는다.

### Exact metadata resolution의 최소 추가 계약

기존 공개 API는 Graph revision/semantic snapshot hash를 표시하지만 안전한 resolution에
필요한 full Artifact pointer는 반환하지 않는다. 알려진 exact pin을 해석하는 작은 read-only
leaf를 추가한다. 임의 latest discovery, source content 공개 또는 권한 발급 기능이 아니다.

1. **책임:** 인증 API principal → 기존 fixed Catalog socket → Catalog Graph/policy owner다.
2. **정본:** published Graph record와 approved manifest Artifact, released access policy다.
3. **identity:** Graph logical/revision/semantic hash와 Artifact revision/raw manifest hash를
   구분하고 정확히 같은 값을 응답에서 검증한다.
4. **resolution:** actor 없는 입력은 known Graph revision + expected semantic snapshot SHA,
   access-policy revision/SHA와 source classes뿐이다. Actual ACTIVE operator의 ITEM_READ,
   GRAPH_RETRIEVE, ANALYSIS_READ, 필요 시 INTAKE_READ와 Catalog policy의 role/query-kind/
   source-class, active corpus와 exact published corpus revision의 연결을 owner가 재확인한다.
   Pointer 결과는 source 권한 증명이 아니며 후속 PREPARE/READ/AUTHORIZE도
   기존 검사를 다시 수행한다.
5. **access pattern:** exact indexed Graph/policy lookup과 bounded metadata read다.
6. **자료구조:** 작은 frozen typed DTO와 existing indexes/socket을 사용한다. 새 table/queue는 없다.
7. **규모:** request/reply 각 64 KiB 이하, 기존 indexed lookup 비용을 유지한다.
8. **transaction:** 읽기 전용 owner transaction이다. control/Artifact publication과 합치지 않는다.
9. **의존성:** JSON Schema 먼저, contracts → application ports → existing socket adapters다.
   API와 worker가 Catalog DB/NAS를 직접 읽지 않는다. Capacity는 Orchestrator 책임으로 남긴다.
10. **실패:** missing/stale/hash/policy/permission 오류는 명시적으로 반환한다. latest 대체,
    policy 확장 또는 source authority 합성은 없다.
11. **대안:** revision/hash만으로 Artifact pointer를 만들면 실제 member/schema/media/hash를
    검증할 수 없다. Root DB lookup이나 parallel discovery 대신 공식 owner resolver를 연결하는
    한 read leaf가 필요한 최소 구현이다.

Catalog access policy에는 preset의 `retrieval_policy.allowed_corpus_keys` 필드가 없다.
이 leaf가 그 별도 실행 설정의 권한을 발급하거나 검증했다고 주장하지 않는다. 존재하지
않는 policy 필드를 추정하지 않고, 비교 Workflow 제출·실행의 기존 exact preset 검사는
해당 Orchestrator/Runner 경계에 남긴다. Capacity 조회도 현재 실제 control permission으로
existing native revision을 읽는 별도 owner leaf이며 slot 예약·관측 갱신·발행은 하지 않는다.

### 동일 owner session의 selected-pair 호출 adapter

최초 두 쌍 비교를 위해 같은 인증 session의 `submit_pair(selection, idempotency_key=...)`와
`read_comparison(query, selection=...)`를 기존 공식 comparison API 계약에 연결한다. 신규
wire schema·권한·queue·실행 framework는 없다. Peer UID 확인 전에 bearer/key를 보내지 않으며,
공개 입력에는 actor/role/permission/preset을 추가하지 않는다. GET URL은 검증된 Workflow ID와
두 기존 mode만으로 구성하고 반환된 comparison·Graph·policy는 원래 selection과 같아야 한다.
현재 principal/session과 필요한 실제 permission을 호출 앞뒤 재확인하고 pending/pointer-only/
member-verified 상태를 보존한다. POST는 한 번만 보내며 timeout 또는 무효 accepted reply는
`INFERENCE_TRANSFER_SUBMISSION_UNCERTAIN`이다. 서버 미처리로 추정하거나 새 key를 만들지 않고,
보존한 exact input/key로 명시적 현재 권한 재검증 replay만 허용한다. API/Catalog가 canonical
member와 현재 source 권한을 검증하며 adapter는 NAS/DB를 직접 읽거나 결과를 snapshot READ에
숨기지 않는다. Source 연결은 설치·실제 로그인·모델 실행 증거가 아니다.
