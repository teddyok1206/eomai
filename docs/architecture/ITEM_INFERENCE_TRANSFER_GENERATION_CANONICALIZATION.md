# 비교 생성 출력의 참조 집합 정렬과 정본 경계

상태 시각: 2026-10-12 11:02 UTC. 구현·진단 기록이며 후속 실제 모델 결과의 PASS가 아니다.
최초 설계 원문과 released schema/model/prompt/rubric 의미는 변경하지 않는다.

## 관측한 실제 실패

두 번째 보존 pair의 원 실행은 `workflow_82a73b86ecfc42a3a018c988e6e3acd8`,
Step `steprun_d4e141a7067a4a61b9bf464c2e5141d9`, Job
`job_397fd1a72d584d108c2453c9030676a6`다. worker exit0 이후
`WORKER_RESULT_INVALID`로 종료했다. 첫 typed error는
`output.new_reasoning.0`의 `right difference claim IDs must be sorted and unique`다.

실제 local failed candidate를 runner identity로 bounded FD/identity 검사 후 읽었다.
정렬되지 않은 refs는 `new_reasoning[0].right_claim_ids` 2개와
`axes[0].left_claim_ids` 2개, `axes[0].right_claim_ids` 3개다.
모두 duplicate0이며 inner hash는 생략됐다. 이는 이 배열들의 형식 진단이지 다른
근거·설명 내용의 정확성 PASS가 아니다. 실패 파일·DB 상태·Artifact 게시 변경은 0이다.

- generation raw SHA: `6f071b4f7fb04b857168317e00a3e6a3d32802014ac8af507091a3bc11be905d`.
- input raw SHA: `58ddfef722544f1265d980f0f913f1de0a2a8fdfaa2e6fd03e02c3375c8dc08f`.

別도 memory-only 진단에서 refs 순서만 정렬한 사본은 기존 strict typed 결과와
exact selected-request ref/facet closure를 통과했다. 실제 파일 쓰기·게시·모델 실행은
모두0이고 원 FAILED는 그대로다. 이 관측을 실제 successor 결과나 의미 정확성 PASS로
확대하지 않는다.

## 작은 설계 결정

1. **책임/경계:** 기존 Orchestrator의 generation→canonical typed-result 경계인
   `eom_workflow.schemas._canonicalize_inference_transfer_pair_result_v11`에만 적용한다.
   별도 repair worker, queue, validator framework를 만들지 않는다.
2. **정본:** 승인 report/profile/Graph가 근거이며 worker 설명은 machine hypothesis다.
   실패 candidate는 새 정본으로 승격하지 않는다.
3. **identity/revision:** logical comparison·original FAILED Workflow/Step/Job·selected
   pair·control/source pins를 보존한다. 새 모델 실행은 explicit retry successor다.
4. **pointer/checks:** existing canonical schema, typed model, exact selected claim/source
   closure와 current authorization을 모두 유지한다. 잘못된 hash/ID/참조는 거부한다.
5. **access pattern:** 같은 객체·같은 측의 bounded claim-ref 집합을 canonical 순서로
   직렬화한다. 컬렉션 순서·객체 순서·좌우·membership·설명은 변경하지 않는다.
6. **구조:** typed `ClaimId` list, uniqueness set, sorted list와 copy-on-change의 작은
   dict/list 사본이다. dedup 결과를 출력하거나 refs를 추가·삭제하지 않는다.
7. **규모/복잡도:** 각 ref list 최대16, 기존 결과/worker 입력 상한 유지.
   정렬은 O(r log r), 보조 메모리는 변경된 refs/객체만 O(r); DB/cache/index 추가 없음.
8. **transaction:** generation memory 표현을 검증하고 typed envelope를 canonical
   bytes로 staging/commit하는 기존 transaction/publication owner를 사용한다.
   worker raw SHA와 정본 member SHA는 서로 다른 materialization identity다.
9. **dependency:** 기존 workflow/contracts/Pydantic을 재사용한다. 새 dependency 없음.
10. **failure/retry:** hash ABSENT의 support/result@1.1 generation만 정렬한다.
    supplied hash가 있으면 정렬도 하지 않는다. duplicate/malformed refs는 untouched로
    strict rejection하며 foreign refs도 exact worker closure에서 계속 거부한다.
    과거 실패를 수정하지 않고 고정 retry operation key로 successor/replay한다.
11. **대안:** 모든 형식 오류를 모델 재생성으로 해결하거나 duplicate를 지우는 방식은
    불필요한 사용량 또는 근거 변경을 만든다. hash를 가진 정본을 임의 정렬하는 것도
    금지한다. 생략된 hash의 generation-only 집합 직렬화가 가장 좁은 경계다.

정본 직접 parser의 unsorted 거부·released V1.0 동작·schema bytes는 그대로다.
derived generation-schema 설명만 이 직렬화 책임을 명확히 한다. released instruction
파일을 수정하거나 새 rubric/control을 재발행하지 않는다.

## 검증과 현재 남은 것

새45 tests는 unique-unsorted 정렬/hash, 입력·membership·내용·객체 순서 불변,
duplicate/malformed/foreign 거부, supplied hash bypass/거부와 직접 canonical parser의
unsorted 거부를 검사한다. 관련 focused 회귀275 PASS, Ruff/strict mypy 및 독립 source
검토 PASS다. 실제 후속 결과·MEMBER_VERIFIED·same-key replay는 아직 별도 gate다.
Root의 fresh 전체 관련 회귀는 83파일/2,899 PASS(75.48초), 변경한5 source/test
strict mypy/Ruff/format PASS다. 기존 Starlette deprecation과 의도적인 invalid fixture의
serializer warnings3개를 보존했으며 신규 dependency는 없다.
사람 평가는 사용자 지시에 따라 NOT_EVALUATED/NOT_REQUIRED이며, 이 형식 보완은
과학적 정확성이나 학습자의 체감 전이 검증이 아니다.
