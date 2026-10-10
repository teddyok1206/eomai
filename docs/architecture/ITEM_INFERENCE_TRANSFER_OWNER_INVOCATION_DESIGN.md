# 문항 핵심 착상 전이 — 후속 owner 호출부 설계

상태: **PROPOSED / NOT_IMPLEMENTED**. 2026-10-10 UTC.
네 번째 checkpoint의 소스 연결을 실제 bounded 실험에 잇기 위한 설계다. 이 문서는 새 API,
private operation, 권한, control release, 모델 실행 또는 배포를 활성화하지 않는다.

## 현재 경계

인증 snapshot API/private Catalog producer와 전용 Runner executor는 소스에서 연결됐다.
다음 네 호출부는 아직 없다. 기존 owner를 연결하는 최소 구현만 추가하고, 별도 registry,
queue, search engine, framework 또는 일반 사용자 UI를 이 단계에서 만들지 않는다.

1. 인증된 snapshot client → pure staging port와 명시적 오류 매핑.
2. staging → 보호된 local input → 기존 offline harness → 최종 source 재인가 → owner Artifact commit.
3. 선택된 두 profile → 실제 principal의 Workflow 제출 및 목적 전용 결과 조회.
4. 검토된 bootstrap 입력 → 실제 control-permission authorizer/publisher → 명시적 PREPARE/RELEASE.

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
   함께 기록한다. 기존 unique constraint/savepoint/replay/Runner fence를 재사용한다. HTTP read,
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

관련: [구현 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md),
[네 번째 checkpoint](ITEM_INFERENCE_TRANSFER_FOURTH_CHECKPOINT.md).
이 문서에는 운영 자료·자격 증명·worker 내용·실제 품질 판정이 없다.
