# 문항 착상 전이: bounded support worker binding

상태: 구현 후보. 기존 [F4 계획](ITEM_INFERENCE_TRANSFER_IMPLEMENTATION_PLAN.md)을 연결하는 additive protocol이며 운영 활성화·Codex 실행·교육 품질 PASS를 뜻하지 않는다.

## 설계 절차

1. **책임과 경계:** Catalog application이 실제 operator를 재인가하고 exact profile을 준비한다. Orchestrator만 support job, resolved execution plan, claim/lease, staging, schema 검증과 Artifact commit을 소유한다. worker는 local input/result만 사용하고 DB/NAS와 다른 worker에 접근하지 않는다.
2. **정본:** 승인 Item/accepted analysis/additive solution/Graph/policy가 정본이다. profile·pair result는 파생 관측이며 원본을 덮지 않는다. profile에 포함된 pointer/APPROVED 문자열 자체가 권한을 만들지 않는다.
3. **entity/revision:** PairComparisonRequest의 request ID/hash, exact profile ID/revision/hash, rubric revision/hash와 generic job/workflow/step/attempt/Artifact/revision identity를 분리한다. worker result hash와 committed Artifact hash도 다른 개념이다.
4. **resolution:** Catalog가 source/report의 실제 bytes/hash/approval/lifecycle와 actor를 검증한 뒤 bounded profile values를 넘긴다. Orchestrator는 exact profile hash, selected claim closure, pair pins, role/protocol과 result envelope identity를 독립 검증한다. source 재인가는 별도 typed `reauthorize_transfer_sources` port로 실행한다. 기존 `before_execute` callback은 workflow step/job CAS binding용이므로 source 권한 증거로 인정하지 않는다. latest substitution은 없다.
5. **access pattern:** exact immutable lookup, idempotency-key lookup, indexed plan/claim/lease, sorted bounded claim sets와 mapping closure, append-only job history를 재사용한다.
6. **data structure/index:** 기존 job/plan/lease/Artifact tables와 unique constraints만 사용한다. 신규 DB/table/queue/role/worker account는 없다. support request는 두 derived profile의 작은 frozen value와 pair request를 담으며 canonical input 64 KiB를 넘으면 명시적으로 거부한다. 원문 문항·전체 풀이보고서·PNG·벡터 행렬을 붙이지 않는다.
7. **scale/complexity:** 한 번에 한 방향 A→B 쌍만 처리한다. ID 검증은 map/set으로 O(claims+references), bounded hashing/serialization은 input bytes에 선형이다. 64 KiB를 넘는 profile은 잘라서 다른 원문처럼 취급하지 않는다. 장래 larger context는 별도 reviewed Artifact materialization successor가 필요하다.
8. **transaction/concurrency:** 기존 `submit_workflow_role`의 exact idempotent replay, generic transaction/state machine/capacity claim/lease/recovery를 사용한다. 신규 호출은 compatible exact resolved plan과 재인가 callback 없이는 시작하지 않는다. terminal history replay는 새 worker 실행으로 바뀌지 않는다.
9. **dependency direction:** Catalog는 기존 pure comparison preparer와 workflow public request를 조합하여 prompt를 준비한다. Orchestrator는 Catalog application 구현을 import하지 않고 workflow/contracts의 typed validation만 사용한다. domain은 subprocess/filesystem/SQLAlchemy를 import하지 않는다.
10. **failure/retry:** `workflow-role/1.29.0` support-only input과 `item-inference-transfer-pair-result@1.0` envelope를 추가한다. 이전 closed protocol/result bytes와 해석은 그대로다. missing compatible plan/reauthorization, invalid pins/hash/refs, oversized context와 malformed result는 explicit rejection이며 unknown timeout 뒤 새 identity로 우회 실행하지 않는다.
11. **단순한 대안:** CustomerSupport/PDF/KnowledgeAnalysis request 안에 pair JSON을 숨기는 방법은 목적·schema·release 의미를 위반하므로 사용하지 않는다. 별도 executor/queue도 필요 없다. isolated successor input/result를 기존 generic worker execution에 연결하는 것이 최소 변경이다.

## 실행 계약과 상태

- 입력 request name: `ITEM_INFERENCE_TRANSFER_PAIR_REQUEST`. 기존 support role만 사용하며 upstream Artifact는 비어 있다. pair context의 승인된 source pointers는 worker 권한을 부여하지 않는다.
- 입력 protocol: `workflow-role/1.29.0`. 이전 protocol로 이 purpose를 파싱하는 것은 거부한다.
- 출력: generic RoleResult envelope의 `output`에 exact `PairComparisonResult`. 기존 Catalog prompt의 core 의미를 재작성하지 않고 envelope 지시를 덧붙인다. prompt hash는 실제 전체 prompt bytes에 대해 따로 고정한다.
- generated strict schema는 request/profile/rubric pins와 양쪽 selected claim IDs를 제한한다. canonical JSON Schema 2020-12와 frozen 모델, context validation이 최종 경계다. 모델은 hidden chain-of-thought가 아닌 짧고 검증 가능한 대응 근거만 반환한다.
- `STRUCTURAL_ANALOGY`/`NEAR_IDENTICAL_CANDIDATE`는 모델 가설이다. human evaluation, scientific correctness, originality, human approval을 대체하지 않는다.
- worker binding 구현은 preset/Pack/Graph activation이 아니다. `item-inference-transfer-comparison` exact-purpose resolved plan, pinned instruction/runtime/model/policy release와 opt-in canary가 아직 준비되지 않았으면 `ACTIVATION=UNSUPPORTED_PENDING_COMPATIBLE_RELEASE`로 보고한다. 기존 plan의 purpose를 바꾸지 않는다.

## 검증

`resolved-execution-plan/21.0`의 전용 purpose를 추가해 pair request/profile/rubric,
Graph 전체 pointer/hash, access-policy revision/hash와 두 prompt hash를 고정한다.
generic V1의 Pack 의미를 비교 작업에 재사용하지 않는다. worker binding은 V21만 허용하며
실제로 전달할 전체 prompt의 UTF-8 bytes SHA와 prepared core prompt SHA가 정확한 plan과
일치해야 한다. core SHA는 Catalog의 preparer가 계산해 전달하며 전체 prompt SHA와 구분한다.
source/report와 실제 actor는 Catalog의 read-only 재인가 port가 독립 확인한다.
terminal replay는 worker materializer를 거치지 않으므로, plan의 self-hash뿐 아니라
동일 조회 행의 plan/workflow/preset/capacity/Graph identity, hash, resolver와 UTC 시각까지
canonical document와 대조한다. 행과 문서가 다르면 과거 성공 job도 반환하지 않는다.
동일한 exact Graph pointer를 갖는 두 profile만 허용한다. 실제 release를 활성화하기 전에는
목적별 request/resolver/materializer/instruction/runtime/capacity와 Catalog owner authorization
연결을 별도 검증해야 한다. 구 plan schema에 필드를 추가하거나 다른 preset을 재해석하지 않는다.
source callback은 job 생성 전, replay 반환 전, 실행 직전과 결과 commit 직전 호출되며, source가 그 사이 revoke되면
검증된 결과라도 canonical Artifact로 commit하지 않는다. callback의 실제 권한 검증 구현 및
protected release/model runtime resolution은 아직 이 pure-source gate의 증거가 아니다.

`before_execute` binder만 전달한 호출은 `CONTROL_TRANSFER_AUTHORIZATION_REQUIRED`로
거부한다. 두 callback은 책임과 입력을 분리한다. binder는 job ID를 받고, source port는
재검증된 exact `InferenceTransferPairWorkerRequest`를 받는다. 실제 actor/Graph/policy를
캡처한 Catalog owner가 source port를 조합해야 하며 worker가 callback이나 권한을 고를 수 없다.

schema/model/reference closure, old-version/purpose rejection, request/result/artifact identity, model-copy hash bypass, bounded input, deterministic schema projection, exact replay/conflict와 runtime Git 불필요성을 source tests로 검증한다. DB mutation은 disposable PostgreSQL에서만, 실제 worker 실행은 명시적인 bounded opt-in gate에서만 한다. 실제 실행과 운영 활성화를 수행하지 않고 PASS라고 보고하지 않는다.
