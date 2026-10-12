# 증분 임베딩의 non-Codex 실행 경계

작성: 2026-10-12 UTC. 상태: **설계 제안 / 미구현·미활성**.
상위 설계: [GraphRAG·문항 유사도 통합과 증분 임베딩](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).
이 문서는 기존 queue를 재사용하는 최소 실행 경계를 정한다. 운영 변경·DB migration·모델
실행의 승인이나 완료 증거가 아니다. 아래 신규 이름은 제안이며 등록된 계약이 아니다.

## 1. 책임과 경계

Catalog는 source/report/Graph/policy의 현재 eligibility, 표현과 등록을 소유한다.
WorkflowRunner는 기존 Workflow·command queue·claim/lease·step 상태를 소유한다.
Orchestrator는 보호된 입력 물리화, 격리 CPU 실행, 결과 검증과 Artifact commit을 소유한다.
encoder는 staged 입력을 읽고 local 결과만 제출하며 DB/NAS/network에 접근하지 않는다.

첫 실행은 **local embedding application step 한 종류**이며 CPU를 검증 baseline으로 쓴다.
승인된 bounded CPU/GPU 비교 후 gate를 통과하면 같은 목적의 명시적 GPU resource profile을
기본으로 전환한다. `support`/`image` agent, Codex model,
ContentPack이나 rubric을 가짜로 붙이지 않는다. 새 queue·scheduler·executor registry는 없다.
원 자료 학습은 먼저 정상 종료하며 embedding 후속 Workflow의 실패가 이를 바꾸지 않는다.

## 2. 정본과 발견 기준

정본 발견은 commit된 `KnowledgeGraphPublicationRecord`와 그 snapshot의
`KnowledgeSnapshotAnalysisRecord`다. source 및 accepted-analysis revision/hash를 읽는
Catalog query만 사용한다. 업로드·변환·`ANALYSIS_ACCEPTED`·Item 승인만으로 공용 검색
membership을 추정하지 않는다. 승인대기 Item의 Preview/HWPX 자격도 확대하지 않는다.

현재 Item source adapter는 `PAST_EXAM/APPROVED_ITEM`과 accepted V10 solution report를
지원한다. `AdmittedInferenceTransferCorpus.sources`는 보고서 없는 source도 보존하고,
`profiles`와 `missing_solution_reports`는 이를 구분한다. 첫 범위의 missing report는
`WAITING_FOR_SOLUTION_REPORT` coverage이지 원 학습 실패나 가짜 CRUX 생성 사유가 아니다.
보고서 없이 CONTENT view만 만드는 기능은 별도 projection successor가 생기기 전 미지원이다.
교과서/document chunk는 이 Item 계약에 넣지 않고 후속 source recipe로 분리한다.

## 3. identity와 revision

- **encoding key:** storage 격리 범위 + encoder-space pin + 실제 인코딩 입력 text hash.
  모델의 prefix는 encoder-space에 pin한다. view/renderer recipe는 source binding에서
  검증하되, 같은 space의 실제 text가 같으면 recipe가 달라져도 수치 Artifact를 재사용한다.
- **binding:** source logical/revision ID와 raw member SHA, accepted analysis/report pointer,
  profile pointer, Graph snapshot과 encoding pointer를 연결한 불변 관계다.
- **index:** logical index → immutable revision → ordered binding/shard member pointers.
  current revision만 version/CAS로 전진시킨다.

Graph-only 변경으로 profile hash가 바뀌면 새 association은 재검증한다. 인코딩 입력과
space가 같으면 기존 vector를 재사용한다. source ID를 text hash로 병합하지 않는다.
model/tokenizer/pooling/prefix/dimension/normalization/overflow 변경은 다른 encoder space다.

## 4. 필요한 계약과 resolution

JSON Schema 2020-12를 먼저 추가하고 frozen Pydantic 및 canonical hash를 검증한다.

- 별도 `WorkflowDefinition` 1.1 schema: 기존 1.0 bytes를 보존하고 새 indexing 목적에만 사용.
- `LocalEmbeddingStep`: `type=application`, `operation=BUILD_LOCAL_EMBEDDINGS` 한 literal,
  exact result schema와 `on_success`. executable/module/path/worker role 설정은 받지 않는다.
- indexing Workflow request: exact source/Graph/policy/actor context, model/recipe/device/resource pins, bounded
  input manifest와 semantic input-set hash. Item brief/Pack/LLM prompt는 없다.
- local CPU 입력/결과: bounded batch의 text/row identity, model pins, local vector member와
  bytes/raw SHA/차원/dtype/행 순서. float vector는 JSON 숫자나 DB JSON에 복사하지 않는다.
- vector/index Artifact 및 등록 command: exact members·binding closure·expected index version.

현재 CPU experiment request/result는 query/ranking 실험이며 vector payload를 반환하지 않는다.
한 source만 인코딩하는 작업을 가짜 query·후보 집합으로 포장하지 않는다. 보호된 handoff/
stdio에는 **새 indexing 계약의 명시적 분기**가 필요하고 기존 experiment 1.0은 그대로 둔다.
pointer 해석 시 존재·revision·schema/media·size/hash·lifecycle·현재 권한을 확인한다.

## 5. 주요 접근 패턴

publication/source membership ordered read → missing-binding indexed lookup → 동일 encoding
key membership/dedup → 기존 command FIFO/lease → bounded CPU batch → ordered manifest commit →
Catalog exact binding 등록과 index CAS다. 발견 cursor는 힌트이며 missing-binding 조회가
완결 기준이다. 중복 사건·동일 timestamp·지연 commit은 timestamp watermark만으로 제거하지 않는다.

## 6. DB·구조·migration 최소 범위

| 기존 경계 | 변경 제안 | 보존 사항 |
|---|---|---|
| `workflow_definitions` | 새 1.1 definition의 immutable hash/snapshot 등록 | 기존 1.0 definition과 admission 불변 |
| `workflow_instances` | `ck_workflow_instances_stage`에 `LOCAL_EMBEDDING` 추가 | 기존 state·FK·idempotency·active-request unique 유지 |
| `workflow_step_runs` | `step_type=application`, `worker_role=NULL`, exact result schema 저장 | 기존 attempt unique·state CHECK·Job FK 유지 |
| `workflow_commands` | 기존 START/ADVANCE/RECONCILE command 사용 | 새 command enum·queue·table 없음 |
| Catalog encoding/binding/index | 아래 pointer-only 관계 추가 | 원 Item/analysis/Graph 테이블 직접 수정 없음 |

현재 `workflow_step_runs.step_type`은 `String(32)`이며 **type enum CHECK가 없다**.
따라서 존재하지 않는 CHECK를 확대하는 migration을 만들지 않는다. 새 application row에만
`worker_role IS NULL`과 고정 result schema를 요구하는 conditional CHECK는 additive 보호다.
`workflow_instances.role_schema_version`은 역사적인 column명이다. 새 목적에는 native indexing
execution protocol pin을 저장하고 Codex role의 증거로 쓰지 않는다. 기존 값은 재해석하지 않는다.

Catalog의 최소 persistent 관계는 다음 책임으로 나눈다. 실제 table/ID 이름·migration 번호는
schema/model owner가 확정하며, 신규 queue state나 vector bytes column은 만들지 않는다.

1. encoding record: encoding key unique와 검증된 canonical vector Artifact member/row pointer.
2. source binding: exact source/report/profile/Graph/view/space와 encoding pointer; composite unique.
3. logical index head: index ID·current revision FK·lock version.
4. immutable index revision: predecessor와 index-manifest Artifact pointer·source-set hash.

encoding/binding은 **commit된 관계만** 기록한다. pending/running/failed 실행 상태는 기존
Workflow/Job에서 읽으며 관계 테이블을 두 번째 queue로 만들지 않는다. Artifact revision,
Item/source revision, accepted analysis와 Graph FK를 검토하고 raw binary/전체 report는 저장하지 않는다.
초기 migration은 (a) 전용 stage/application guard, (b) Catalog 관계/FK/unique/index로 분리한다.
downgrade는 신규 목적 row가 남으면 거부하며 historical row나 Artifact를 삭제하지 않는다.

## 7. 규모·비용

key lookup/anti-join은 B-tree·composite unique, source/Graph membership은 기존 association
index를 재사용한다. source/encoding은 map/set, output은 ordered frozen rows다.
관계 규모는 source 수 × available view 수다. exact search는 O(Nd), vector 저장도 O(Nd)다.
Graph-only successor의 관계 재검증은 O(N)이지만 인코딩은 delta만 수행한다. 신경망 비용은
별도 실측한다. bounded batch/cursor를 사용하며 source별 full-corpus 재구성·N+1·전역 cache는 없다.

## 8. transaction과 concurrency

Catalog의 Graph 출판 transaction은 그대로 종료한다. Runner-owned admission use case는
Catalog의 typed eligible/missing 조회를 받고 현재 실행 권한을 확인한 다음, 같은 Runner tx에서
전용 Workflow creation과 `enqueue_command(START_WORKFLOW)`를 수행한다. Catalog가 Runner
테이블을 직접 쓰거나 서로의 private repository를 호출하지 않는다.

command 처리에는 기존 lease heartbeat/fence를 사용한다. CPU 실행 동안 SQL transaction을
열어 두지 않는다. claim 전 입력·모델·purpose admission, 결과 commit 전 source 재인가를 수행한다.
Artifact commit과 Catalog binding/index 등록은 cross-service 단일 transaction인 것처럼 표현하지
않고 exact receipt·같은 operation key·reconcile로 복구한다. CAS 충돌은 다른 revision을 덮지 않는다.
background authority는 공식 등록된 목적별 identity/policy가 필요하며 과거 operator ID나
`guiadmin` 세션의 존재만으로 이를 생성하지 않는다. 각 사용자 검색은 현재 실제 권한으로 재인가한다.

### 8.1 CPU baseline과 GPU 후보의 별도 admission

[상위 설계 §8.1](SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md#81-cpugpu-비교와-기본-device-결정--사용자-추가-요청)을 따른다.
현재 CPU experiment 계약·보호 runtime·고정 CPU unit은 변경하지 않는다. GPU가 보이거나
현재 idle인 사실은 이 embedding 목적의 GPU 사용·활성화·capacity 자격이 아니다.

- 같은 pinned 모델 weights·정본 입력·view recipe·float32/L2/무절단의 bounded workload를
  사용한다. GPU runtime/device/precision profile은 encoder-space에 별도 pin하며 기존 CPU
  vector와 혼합하지 않는다. 새로운 모델 다운로드·학습·외부 LLM API는 필요하지 않다.
- CUDA runtime·보호 설치·고정 격리 launcher·GPU lease/admission은 GPU candidate의 새 경계다.
  단일 embedding executor가 명시된 typed resource profile을 선택하며 `cuda.is_available()`
  fallback이나 임의 실행 파일·새 handler registry를 만들지 않는다.
- 기존 `CodexCapacityController`와 GPU 자원 owner의 claim/lease 경계를 조사·재사용하되,
  Codex Worker slot lease를 native encoder의 권한으로 가장하지 않는다. 현 WorkerCapacityPolicy가
  이미 embedding GPU를 허용한다고 가정하지 않는다. 새 목적의 memory/thread/time/concurrency
  제한·장치 identity·lease token을 검증하고 이미지 작업의 capacity와 충돌을 회귀한다.
- CPU/GPU의 cold load·warm encode·end-to-end·texts/s·RAM/VRAM을 구분해 측정한다.
  전체 seed를 두 번 무작정 돌리지 않고 synthetic 후 승인된 bounded 실제 입력을 사용한다.
  실행 전에 수치 오차·순위/동점 허용 조건·반복 횟수를 고정하고 교육 품질 PASS로 해석하지 않는다.
- GPU가 비교 workload에서 실측 우수하며 격리·권한·lease·기존 이미지 작업 회귀를 통과하면
  compatible release와 명시적 policy로 **기본 GPU 활성화까지** 진행한다. GPU space를 검증한
  후 index current를 전환하고 CPU space·이전 policy·rollback을 보존한다.
- GPU 경합/미지원 시 CPU는 사전에 정한 admission에 따른 명시적 선택이다. source/hash/result
  오류나 uncertain GPU 실행을 CPU 재실행으로 숨기지 않는다. gate 미통과 시 CPU를 유지한다.

## 9. public entry와 변경 소유자

| public 재사용 지점 | 연결/소유 |
|---|---|
| `KnowledgeRetrievalApplicationService.admit_read_only_candidate_pool()` | Catalog 내부 동일 권한·source admission 재사용 |
| `CatalogInferenceTransferSourceAdapter.load()/reauthorize()` | 현재 Item/report 입장과 재인가; fake query를 넣지 않고 indexing query leaf를 추가 |
| `project_accepted_solution_report()` / `render_no_solution_item_text()` | Catalog의 검증된 bytes 이후 pure 표현 |
| `create_workflow_instance()/enqueue_command()/claim_next_command()` | Runner-owned typed request/storage/admission successor에서 재사용 |
| `create_step_run()/transition_step()/transition_workflow()` | 기존 상태·event·attempt 기록 유지 |
| `ProtectedExperimentWorkspace`, `FixedCpuExperimentLauncher` | 보호 FD/O_EXCL·uncertain guard 재사용; 새 계약 branch 별도 검증 |
| `ControlFileSetPublisher.publish()` | Orchestrator vector file-set commit와 exact-key replay |

compiler/repository의 현재 agent-only protocol 계산은 하나의 public definition-protocol helper로
모은다. 기존 agent 정의는 지금과 같은 규칙이고, 전용 application 정의만 native indexing protocol을
반환한다. 임의 handler registry나 혼합 agent/application workflow 지원을 일반화하지 않는다.
Runner에는 전용 `LocalEmbeddingStep` 분기와 주입된 indexing executor 한 개만 연결한다.
adapter가 없으면 Job/claim 전에 명시적 unavailable이며 Codex executor로 fallback하지 않는다.

새 Catalog query/register port, Runner indexing admission/executor, CPU stdio 계약 분기와
composition은 **아직 없다**. 초기 내부 owner invocation부터 검증한다. GUI/API endpoint 추가는
별도 successor이며 일반 문항 start API의 authority/body를 넓히지 않는다. 보호 CPU runtime은
새 계약 code를 실제 설치·검증하기 전 운영 지원이라고 보고하지 않는다. 신규 dependency 기본값은 없다.

## 10. 실패·retry·idempotency

같은 encoding/binding identity의 발견은 동일 Workflow/operation key를 재사용한다.
CPU launch identity는 immutable Workflow/step/attempt와 연결하고 owner workspace에는 O_EXCL로
고정한다. timeout·lease 만료·owner 재시작은 추론이 미실행됐다는 증거가 아니다.
known output은 검증 후 재게시/재등록하고, uncertain은 확인 없이 새 실행 ID로 우회하지 않는다.
vector Artifact commit 후 metadata 등록 실패는 같은 pointer를 재인가·등록하며 재인코딩하지 않는다.
missing report/overflow/revoked source는 각각 별도 coverage 제한이며 원 학습 성공은 유지한다.
released schema/model mismatch·hash drift는 explicit error다. 기존 실패를 성공으로 바꾸지 않는다.

## 11. 대안과 첫 exit gate

동기 Graph publication hook은 긴 encoder와 실패를 학습 transaction에 전파한다.
support/image agent 사용은 역할·capacity·prompt provenance를 거짓으로 만든다.
현재 실험을 상시 index라고 부르면 저장되지 않은 벡터를 존재하는 것으로 재해석한다.
새 queue나 범용 application framework는 기존 durable queue보다 큰 변경이다.
따라서 새 CPU leaf 하나와 기존 queue/state-machine/commit owner 연결을 선택한다.

첫 gate는 synthetic 1-source/bounded batch의 schema·binary·pointer·replay와 disposable DB의
FK/unique/claim/limited-role/up-down-up다. report-missing과 Graph-only 입력 동일 사례에서
coverage와 실제 encode/reuse count를 분리해 검증한다. source revocation 전·후, model/view 변경,
uncertain launch, commit 후 등록 실패, 경쟁 CAS를 negative로 포함한다. 기존 정의 1.0·Codex 목적·
CPU experiment bytes/의미·원 학습 성공을 회귀한다. 운영 gate는 보호 runtime 설치·새 purpose
admission·현재 authority·compatible release와 실제 delta 확인이며 unit PASS로 대체하지 않는다.
GPU가 개선되면 비교 기록만으로 끝내지 않고 위 기본 전환 gate의 실제 활성 상태까지 보고한다.
