# 최초 설계 대조에서 발견한 비교 설명·평가 연결 보완

상태: 2026-10-10 UTC, source 감사에 따른 구현 설계. 실제 corpus/model 실행,
사람 평가 또는 운영 활성화의 성공 기록이 아니다. 설계 원문과 기존 실험 입력은 변경하지 않는다.

## 2026-10-11 현재 설계 대조의 종료 조건

후속 독립 source 감사에서 원문 SHA와 파생 profile, 세 embedding view/common pool,
condition/inference mappings, differences/new_reasoning, V11 독립 세 축,
V22/role 1.30의 전용 purpose 연결을 확인했다. 새 필수 source 누락은 발견되지 않았다.
이는 전체 목표의 완료 증거가 아니다. 당시 설치는 `c8b29f67`이며 V11 실행 정의는
기존 운영 CLI로 별도 등록했다. 정확한 identity/hash/시각과 권한 구분은
[운영 검증 기록](ITEM_INFERENCE_TRANSFER_LIVE_ACCEPTANCE.md)에 있다.

2026-10-11 09:44 UTC의 원래 실행에서 전체 READ와 CPU tokenizer coverage를
실제로 확인했다. 그러나 E5 512-token 한도를 CONCRETE_FACETS 517/520개가 넘었고,
모든 query가 공통 pool 밖이어서 실제 embedding forward는 0이었다. 정본 게시도
일회성 caller의 staging 설정 누락으로 COMMIT_UNCERTAIN 상태다. 이 실행은
MEASURED가 아니며 실패를 보존한다. 상세 metadata는 live acceptance 기록에 있다.
2026-10-11 13:20 UTC에 현재 인증·전체 재인가와 같은 Job/key로 retained 결과의
canonical 게시를 복구했다. CPU 재실행은 0이며 원래 부족 판정과 실패 이력은 그대로다.
당시 아래 1번 중 원래 결과의 정본 보존만 완료했다. 이어서 2026-10-11 13:55 UTC에
같은 520개·4 query·3 view의 BGE successor가 common profile 520/520, encoded text 1560의
실제 `MEASURED / COMMITTED` 결과를 남겼다. 아래 **1번 종료 조건은 이제 완료**이며,
2번 control 발행·3번 두 쌍 비교/replay·4번 최종 원문 대조는 아직 완료되지 않았다.

2026-10-11 17:15 UTC에 원문 SHA를 다시 확인하고 보존된 BGE request/result의
Top-8과 원래 Graph 후보 목록을 비교했다. 원문 변경, 새 조회·모델 실행·게시 없이
520개/3 view의 인코딩 성공과 4 query의 후보 차이를 관측했다. 원문 요구별 source
매핑과 이 제한적 관측은 확인됐지만 실제 두 쌍의 대응 설명을 대신하지 않는다.
사용자 지시에 따라 로그인 입력 요청을 중단했으며 인증·권한을 우회하지 않는다.
종료 조건 1은 완료, 2·3은 실제 실행 대기, 4의 최종 LIVE 판정은 2·3 이후에만 가능하다.
상세 수치와 미평가 한계는 위 운영 검증 기록에 남겼다.

다음 네 가지가 종료 조건이며, 완료된 1번을 다시 실행하지 않는다.

2026-10-11 19:08 UTC에 기존 typed account/model-options 진단 leaf만 추가한
`b59b3bac` compatible release를 설치·검증했다. 기존 520개 BGE 실행과 실패 기록은
보존하며, native model admission·V11 PREPARE/RELEASE·두 쌍 비교/replay는 여전히
현재 실제 인증·실행의 별도 gate다. 이 배포로 종료 조건 2–4를 통과했다고 표시하지 않는다.

2026-10-12 실제 native 관측과 owner PREPARE/RELEASE를 통과해 **종료 조건2는 완료**했다.
첫 selected pair는 202/Workflow 접수 후 self-hash 불일치로 FAILED다. 둘째는 selection만
보존됐고 POST하지 않았다. 현재 strict source 보완은 canonical 계약을 바꾸지 않는
generation absent-only hash 계산과 해당 POST의 순차 transport budget 정렬이며
2,705 unit tests PASS다. 첫 실패를 수정·재해석하거나 새 key로 우회하지 않는다.
추가 첫 pair model 실행 승인은 별도 gate이고 **종료 조건3·4는 여전히 미완료**다.
520개 embedding은 다시 실행하지 않으며 사람 평가는 완료 조건에 추가하지 않는다.

2026-10-12 09:03 UTC에 위 최소 보완 `f093bf853e5bbf9094ff4e65c731d13569d60a91`을
실제 배포했고 8개 service/READY/installed source-tree/timeout390을 확인했다.
이미 발행된 b59 control과 첫 FAILED history는 보존한다. 읽기 전용 감사에서
`RETRY_STEP`이 enum/DB CHECK뿐이며 handler·공개 API가 없음을 확인했다. 기존
capacity-only reconcile로 실제 worker-result 실패를 복구하지 않는다. 같은 Workflow의
실패 Step/Job을 보존하고 새 attempt만 추가하는 최소 지원 경계와 첫 추가 모델 실행1회는
별도 승인 대기다. 운영 설치 PASS를 두 쌍 비교·replay PASS로 확대하지 않으며
**종료 조건3·4는 여전히 미완료**다. 실제 배포 identity/hash는 운영 검증 기록에 있다.

이후 사용자는 목표 달성까지 추가 승인 요청 없이 진행하도록 지시했다. released1회
제약을 변경하지 않기 위해 같은 Workflow의 attempt2가 아니라 같은 pair의 명시적
successor START를 선택했다. source2,952 PASS/추가API160 PASS, disposable PostgreSQL
25 PASS와 old295 resource/definition/role 불변 확인은 완료했으나 새 leaf의 실제
배포·successor 결과·두 pair/retry key replay는 아직 대기다. 별도 사람 평가나520개
재임베딩은 추가하지 않는다. 원 실패·원 요청/key·원 source/control pins는 보존한다.

### 2026-10-11 10:49 UTC 독립 source 대조

원문·구현 계획·현재 계약/코드/테스트를 read-only로 다시 대조했다. 원문 SHA는
위 보존값과 동일하며 추가 필수 구현 누락은 발견하지 못했다. 다음은 source 매핑이지
전체 corpus·실제 비교 결과나 교육적 효과의 PASS가 아니다.

| 원문 요구 | 구현/계약 | 관련 회귀 |
|---|---|---|
| 조건 역할·관계·판단·오개념 | `inference_transfer_projection.py`, `item_inference_transfer.py`; 승인 report의 step/node/anchor refs | `test_inference_transfer_projection.py`의 다른 조건·근거 없음·부정·오개념 |
| 승인 풀이보고서+원문+메타데이터 | `inference_transfer_catalog_adapter.py`, `inference_transfer_item_projection.py`; accepted V10와 원문 질문·구조/수식/승인 summary 분리 | `test_inference_transfer_item_projection.py`의 source closure/정답 배제/metadata |
| 후보 검색만 담당하는 벡터 | `local_embedding_adapter.py`, `inference_transfer_experiment.py`; offline exact pins·무절단·3-view 공통pool·view당 encoding 재사용 | `test_inference_transfer_experiment.py`의 공통pool/권한/순위/overflow |
| 조건·추론 대응과 차이·추가 추론 | `inference_transfer_comparison.py`, current Catalog source resolution; selected A/B refs와 방향/rubric closure | `test_inference_transfer_comparison.py`, `test_inference_transfer_pair_source_authorization.py` |
| 개념·소재·착상 세 축 | `inference_transfer_pair_result_v11.py`; 축별 설명·양쪽 refs·독립 INSUFFICIENT, 충분한 CRUX는 결정적 추론 refs | `test_inference_transfer_pair_result_v11.py`; released1.0 보존, role1.30/V22/explicit1.1 |
| 비동기·claim/lease·same-key replay | `inference_transfer_executor.py`, existing Runner repository/Orchestrator; actual creator/current auth·indexed claim·unique race | workflow_v11/runner_v11/worker_protocol 및 기존 disposable PostgreSQL 회귀 |
| 현재 권한·immutable pointer·정본 결과 | submission/router/workflow_read; cached replay 전 현재 source auth, Artifact/member/schema/hash/Job/Workflow/Step/pair closure | API v11/workflow read의 권한 거부·POINTER_ONLY/MEMBER_VERIFIED |
| 사람의 체감 전이 | 기존 optional HumanTransferEvaluation/owner/history 보존 | 사용자 지시에 따라 NOT_EVALUATED/NOT_REQUIRED; 새 사람평가·GUI·정확도 지표를 추가하지 않음 |

DECISIVE의 deterministic 후보나 합법 ref/hash만으로 과학적 정답·교육적 crux를
증명하지 않는다. 실제 metadata 활용은 기존 구조·수식·승인 summary 범위이며 임의
개념/난이도 분류나 PDF 픽셀 관찰을 발명하지 않는다. 아래 actual 종료 조건은 그대로다.

1. 원래 input/execution의 INSUFFICIENT 결과를 같은 key와 현재 재인가로 보존한다.
   그다음 실제 길이에 맞는 안전한 local model을 admission한 명시적 successor에서
   같은 520/4 queries/3 views의 CPU `MEASURED` 정본 Artifact를 검증한다. 원래 모델의
   길이 pin이나 원문·조건·부정을 바꾸지 않고 실패를 새 성공으로 재해석하지 않는다.
2. 등록된 V11 정의와 실제 native protocol/capacity/model의 검증 → 명시 owner
   PREPARE/RELEASE. config compile/DB 정의 등록을 control 발행으로 확대하지 않는다.
3. 승인된 두 쌍의 실제 V11 비교 → `MEMBER_VERIFIED`, 독립 CONCEPT/MATERIAL/CRUX
   설명과 양측 claim/decisive refs, 같은 key replay. 모델 가설을 실제 풀이 전이의
   증명으로 표현하지 않는다.
4. 최초 원문 요구별 정본 pointer·자동 관측·미평가 한계를 최종 보고한다.

사람 평가/precision·recall·새 scorecard/GUI/ANN/embedding recipe는 추가 완료 조건이
아니다. 실제로 부적합하다고 측정된 모델의 fit 보완은 원래 벡터 후보 기능을 끝내기
위한 작업이며 기존 optional 계약/기록은 보존한다.

## 이후 사용자 지시 — 사람 평가 없음

2026-10-10 사용자는 “사람 평가는 없다고 생각해”라고 지시했다. 아래 초기 감사에서
발견한 사람 점수표 연결은 **추가 구현·완료 조건에서 제외**한다. 기존 human owner,
label 계약과 canonical 기록은 보존하지만 새 scorecard/context/GUI를 만들지 않는다.
모델의 판단을 사람 label로 기록하지 않는다. 실제 학습자의 체감 전이 검증은
`NOT_EVALUATED / NOT_REQUIRED_FOR_CURRENT_COMPLETION`로 명시한다.

현재 보완 범위는 독립적인 세 축 비교 계약과 자동 검증이다. 기존 검색 대비
bounded 실험에서는 정확한 후보/순위·token coverage·공통 모집단·지연·resource 사용량과
Codex의 claim-grounded 대응을 기록한다. 사람 label이 없는 precision/recall/교육 효과를
수치로 만들거나, 모델의 구조 대응 가설을 실제 학습자 전이의 증명으로 표현하지 않는다.
아래 human 집계 제안은 변경 전 설계의 기록일 뿐 구현할 작업 목록이 아니다.

## 확인된 누락과 변경하지 않을 것

- 원문은 개념·소재·핵심 착상의 유사성을 **각각** 설명하도록 요구한다.
  현재 pair-result/1.0은 조건/추론 mapping과 shared_idea, differences,
  new_reasoning을 검증하지만 세 설명 축을 독립적으로 강제하지 않는다.
  세 embedding view의 ablation은 이 요구의 대체물이 아니다.
- 사람의 검토 묶음과 label을 게시/조회하는 owner는 있다. 그러나
  `evaluate_transfer_ranking`은 순수 함수이며 실제 canonical label을 받아
  실험의 3-view/Graph 순위를 집계하는 호출 경로는 아직 없다.
- 실험 result/1.0은 3-view 순위와 coverage를 보존하지만 Graph baseline의
  후보 순서와 원래 Graph/policy/population 입력은 request/1.0에만 있다.
  최신 Graph 조회로 옛 순서를 보충하거나 baseline_status로 복원하지 않는다.
- 현재 metadata producer는 자료형식·평가형식·일부 수식만 채운다.
  CONCEPT/OBSERVABLE/교육과정/난이도가 enum에 존재한다고 실제 사용을 주장하지 않는다.
  이 보완에서 원래 profile/embedding recipe와 입력 pins를 변경하지 않는다.

## 설계 절차

1. **책임/경계:** 기존 Catalog 비교 검증과 Orchestrator의 비교 실행·Artifact
   owner를 확장한다. 평가 집계는 기존 human owner가 읽은 canonical label과
   experiment request/result를 조합하는 작은 application use case다.
   새로운 검색 엔진, queue, DB, worker 통신, 평가 GUI를 만들지 않는다.
2. **정본:** Item Revision, accepted solution report, pin된 Graph/policy가 근거다.
   모델의 축별 설명은 가설이고 사람 label만 사람 판정이다. 기존 실험의
   exact request bytes와 canonical result member가 순위 재현의 근거다.
3. **identity/revision:** released pair-result/1.0과 기존 protocol/plan/schema를
   보존한다. 세 축을 요구하는 출력은 명시적인 successor로 추가한다.
   평가 context/scorecard도 별도 immutable Artifact이며 기존 결과를 덮지 않는다.
4. **pointer/resolution:** 실험 request/result, human record/bundle은 exact
   Artifact ID/revision/member/schema/media/raw SHA로 읽는다. request/result
   canonical hash와 model/recipe/profile-set closure를 재검증한다. 세 축의
   설명은 실제 selected claims에 연결하며 없는 concept/material 근거는
   INSUFFICIENT로 명시한다. 실제 operator, 원래 policy/Graph와 source lifecycle을
   공식 snapshot/comparison 경계에서 재인가한다.
5. **access pattern:** bounded Artifact exact lookup, query/view 키 lookup,
   candidate/profile membership, reviewer/rubric별 label dedup, ordered ranking이다.
   최신 순위나 다른 방향·평가자의 label을 자동 병합하지 않는다.
6. **구조/index:** frozen DTO, tuple 순위, profile/query keyed dict와 set을 쓴다.
   기존 Artifact/index/unique publication boundary를 재사용한다. 새 DB/index 없음.
7. **규모/복잡도:** 기존 최대 1,024 profiles, 16 queries, 세 view와 Graph baseline,
   bounded explicit label pointers를 처리한다. lookup과 집계는 입력 수에 선형이며
   space도 선형이다. full corpus 재임베딩·모델/worker 재실행은 집계의 일부가 아니다.
8. **transaction/concurrency:** 기존 Orchestrator publisher가 유일하게 commit한다.
   같은 context/scorecard command의 replay는 동일 idempotency key를 쓴다.
   게시 전후 current authorization과 source closure를 확인하고, post-commit
   revoke는 receipt를 보류하되 canonical 실패/성공 기록을 삭제하지 않는다.
9. **dependency/ownership:** contracts는 I/O 없이 순수 검증, Catalog는 순수 지표,
   Orchestrator application은 read/authorization/publication port를 조합한다.
   CLI는 파일 입력·typed command·공식 owner 호출과 출력만 담당한다.
10. **failure/retry:** 잘못된 hash/revision/schema, 다른 actor/query/rubric,
    conflicting label, source revoke와 입력 누락은 명시적 오류다. 평가되지 않은
    후보는 NOT_EVALUATED/부분 평가로 남기고 near-identical은 유용한 전이에
    합산하지 않는다. recall은 **명시적으로 평가한 pool**의 recall이며 전 corpus
    recall이 아니다. Graph와 embedding common pool 차이도 보고한다. unknown
    timeout은 새 identity로 재제출하지 않는다.
11. **더 단순한 대안:** 기존 pair prose에 제목만 넣는 방법은 세 축·참조를
    구조적으로 검증하지 못한다. 순수 지표 함수만 제공하면 실제 label과 당시
    baseline의 연결이 누락된다. 반대로 전체 새 평가 플랫폼이나 원래 실험
    재생성은 불필요하다. 기존 boundary에 작은 successor와 집계 leaf만 추가한다.

## 구현 및 검증 순서

1. Schema 2020-12를 먼저 추가하고 frozen model, closure/negative tests를 작성한다.
2. 사람 점수표/context 추가 구현은 이후 사용자 지시에 따라 수행하지 않는다.
   기존 experiment의 정확한 request/result와 Graph baseline 입력은 계속 보존한다.
3. 세 축 비교는 successor result와 그 출력을 정확히 pin하는 최소 compatible
   workflow/protocol/prompt support를 추가한다. 기존 1.0의 의미나 bytes를 바꾸지 않는다.
4. fake-port source tests, formatter/linter/type checker, historical schema hashes,
   installed-wheel inclusion을 확인한다. 현재 READ 진단 중 runtime 배포는 하지 않는다.
5. 실제 corpus 실험·bounded comparison을 각각 검증한다. 사람 검토는 완료의
   선행 조건이 아니며, 미실시 상태를 자동 성공으로 바꾸지 않는다.

## 종료 판정

현 구현의 종료에는 축별 설명 계약과 실제 corpus의 자동 실험·운영 연결 증거가
필요하다. owner scorecard 추가 구현과 사람 평가는 이후 사용자 지시에 따라 필요 없다.
자동 PASS를 실제 학습자 체감 전이의 증명으로 표현하지 않는다. 최종 보고는 최초
원문 요구별로 SOURCE_VERIFIED/LIVE_VERIFIED/HUMAN_NOT_EVALUATED/GAP을 구분한다.

## 최초 설계 대조 — 세 축 successor source 후보

2026-10-10 UTC의 source 후보는 기존 경로를 대체하지 않고 다음 explicit family를
추가한다. 아직 설치·control 발행·실제 worker 실행 증거가 아니다.

| 경계 | 보존된 기존 family | 추가된 세 축 family |
|---|---|---|
| Pair result | `item-inference-transfer-pair-result/1.0` | `.../1.1` |
| Workflow request/definition | request `1.0`, definition `1.0.0` | request `1.1`, definition `1.1.0` |
| Worker envelope | `workflow-role/1.29.0` | `workflow-role/1.30.0` |
| Resolved plan | V21 | V22 |
| Preset key | `item-inference-transfer-comparison` | `item-inference-transfer-comparison-axes` |
| Reviewed instructions | `comparison-v1/instructions` | `comparison-v1_1/instructions` |
| API | `/comparisons`, `/workflows/{id}` | explicit `/comparisons/v1.1`, `/workflows/{id}/v1.1` |

Schema 2020-12와 frozen model은 CONCEPT/MATERIAL/CRUX의 정확히 세 축, 독립 설명,
selected claim 참조와 canonical hash를 검증한다. 부족하지 않은 축은 양쪽 참조가
필요하며 CRUX는 양쪽 DECISIVE_INFERENCE facet에 묶인다. 긍정적 전이 가설에는
CRUX SAME/PARTIAL뿐 아니라 기존 조건/결정적 추론 mapping과 차이 검증도 필요하다.
generation용 JSON Schema에서 Codex가 지원하지 않는 conditional/tuple 표현만 완화하고,
정본 admission은 축 순서·조건·참조 검증을 그대로 적용한다.

Orchestrator staging/commit, current actual-actor 재인가, Catalog의 exact canonical
결과 조회와 같은 idempotency/claim/lease 경계를 재사용한다. DB schema/migration,
queue, embedding 모델·recipe와 기존 실험 입력을 변경하지 않는다. old/new 요청·결과·
실행계획의 상호 해석은 거부하고 pinned historical replay의 의미는 유지한다.

| 최초 원문 요구 | 자동 검증 범위 | 현재 한계 |
|---|---|---|
| 직접 주어진 조건·중간 관계·결정적 추론·오개념 | accepted report의 exact refs와 deterministic profile projection | 새로운 과학적 사실을 발견·입증한 것은 아님 |
| 개념·소재·핵심 착상의 별도 설명 | 새 1.1 계약·프롬프트·workflow·canonical read 연결 | 실제 corpus worker 결과는 아직 없음 |
| 벡터는 후보 수집, Graph/근거는 설명 기반 | opt-in 로컬 embedding와 기존 supported retrieval/policy 유지 | 실제 corpus/Graph baseline 실험은 READ 정상화 뒤 수행 |
| 어떤 조건·추론이 대응하며 무엇이 다른가 | selected condition/decisive mappings, differences, new_reasoning | ref closure는 semantic correctness 보증이 아님 |
| 숫자·이름 변경과 구조적 전이 구별 | NEAR_IDENTICAL_CANDIDATE/STRUCTURAL_ANALOGY의 독립 가설 | 자동 표절 판정이나 출판 승인으로 사용하지 않음 |
| 실제 풀이 전이의 사람 평가 | 기존 optional owner/계약/기록 보존 | 이후 지시에 따라 NOT_EVALUATED / NOT_REQUIRED |
| 원문 보존 | 원문 raw SHA `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a` 유지 | 설명용 예를 실제 corpus 관측으로 사용하지 않음 |

현재 source 정적 검사: 변경 Python 53파일 Ruff/format PASS, 변경 source 38파일
strict mypy PASS, diff check PASS. source-only package/OpenAPI/instruction 19tests PASS:
wheel RECORD/schema inclusion과 source checkout 없는 installed simulation에서 구/신
workflow를 각각 compile하고, 무인증 외부 호출 없이 OpenAPI alignment를 검증했다.
초기 전체 관련 회귀는 2,420 PASS/1개의 이전 테스트 기대 불일치였다. 새 1.1이 없는
버전이라는 옛 fixture 기대를 실제 successor admission과 미지원 1.2 거부 검사로
갱신한 후 fresh 전체 실행에서 **2,421 PASS / 83.51초**를 확인했다. 뒤의 조회 보완과
새 진단 테스트는 이 실행 이후의 변경이므로 최종 회귀를 별도로 기록한다.
여기서 CPU/모델/운영/교육 품질 PASS를 주장하지 않는다.

## READ producer 상한 불일치와 안전한 원인 진단 보완

실제 `f12fb971` READ 실패는 OWNER_SERVICE/FROZEN_MODEL까지 관측됐고 세부 원인은
미확정이다. 별도로 정상 producer 범위의 합성 source 67개로 PREPARE 성공 → 첫
READ 실패를 재현했다. supported `retrieve_read_only`는 최종 출판 Evidence가 아니라
Graph 후보 pool을 최대 256개 반환한다. snapshot producer는 여기에 자신의 query
제외·frozen eligible filtering만 적용한 뒤, 최대 64개인 `SuppliedGraphBaseline`을
생성하므로 65개 이상이면 `ordered_candidates / too_long`으로 실패한다.

최소 보완은 **기존 bounded baseline 계약**을 producer가 준수하게 하는 것이다.
Graph retrieval과 authoring의 document/item/node/claim/context 예산 알고리즘은
변경·복제하지 않는다. 필터링된 후보 순서는 그대로 두고 첫 64개를 baseline으로
기록하며, eligible 전체 수·보존 상한·나머지 미기록을 limitations에 명시한다.
이 baseline은 최종 authoring Evidence selection이나 완전한 후보 pool이 아니다.
64개 이하의 기존 valid ordered/hash는 그대로이며 기존 wire schema의 64 상한도
바꾸지 않는다. 원본 문항·보고서·전체 source/index/profile 모집단은 자르지 않는다.

책임은 Catalog snapshot producer, 정본은 재인가된 frozen source/Graph/policy다.
identity·기존 실험 입력은 그대로 유지한다. loop에서 모든 후보의 exact source/run과
eligibility를 확인한 후 bounded tuple을 만들며, dict/set lookup과 안정적 ordered
iteration으로 O(candidate 수) 시간/공간을 유지한다. 기존 read-only transaction과
staging/reauthorization/idempotency를 사용하고 새로운 DB/cache/queue/권한은 없다.
더 단순한 무제한 배열은 released bound를 위반하며, 전역 retrieval를 바꾸거나 private
출판 selection을 호출하는 것은 다른 두 consumer와 기존 evidence 의미까지 바꾼다.

추가 진단은 기존 logger 안에서 Pydantic 오류를 고정 model/field/type category로만
분류한다. allowlist 밖의 model title·field·type은 OTHER, 위치의 숫자·동적 key·ID는
기록하지 않는다. input/context/오류 원문/traceback/문항은 출력하지 않는다. 후보 수
초과 재현은 BASELINE_RESULT/CANDIDATES/SIZE_OR_COUNT로 구분되며 로깅 장애는
safe wire reply를 바꾸지 않는다. 새 wire/schema나 예외 메시지 노출은 없다.

이 source 재현과 보완은 이번 운영 오류가 확정적으로 동일 원인이었다는 뜻은 아니다.
설치·actual-principal READ 재확인 전에는 LIVE_FIX_VERIFIED=PENDING이다. 기존 실패와
동일 execution/input은 보존하고 새 identity로 우회하거나 실패를 성공으로 재해석하지 않는다.

### Source 동결 검증

세 축 successor와 위 READ/diagnostic 보완을 모두 반영한 fresh 전체 관련 source,
API, instruction, OpenAPI, wheel/installed-simulation 묶음은 **2,497 PASS / 102.64초**다.
변경 Python **59파일 Ruff/format PASS**, 변경 source **41파일 strict mypy PASS**, diff
검사 PASS다. 이전 2,421개 및 하위 focused suite와 합산하지 않는다. Starlette의
기존 httpx TestClient deprecation warning 1개는 남아 있으며 runtime 장애로 분류하지 않는다.
이 변경에 새 dependency·DB migration·권한 부여는 없다.
별도 기존 역할 protocol/definition/dependency/Catalog resource 회귀는 **86 PASS / 16.13초**다.
추가 검사 첫 invocation은 없는 test 파일명을 지정해 collection 없이 종료됐으며,
실제 존재하는 위 네 파일로 바로잡아 fresh 실행했다. 운영 작업·모델 실행이 아니다.

OpenAPI raw SHA는 `ec9e311298c0dcf00b992c8e601efa170bdab85ccee77e3d6d2057fd8d760908`다.
기존 path의 정의 변경은 0이며 세 축 비교용 version-explicit submit/read 2개만 추가했다.
기존 released schema·원래 1.0 definition/instruction bytes와 설계 원문은 바꾸지 않았다.

legacy snapshot Catalog fixture 파일의 전체 strict 검사에는 변경 전부터 있던 union
접근/재노출 typing 오류 6개가 남는다. 신규 회귀 영역은 이 오류에 해당하지 않지만,
해당 test 파일 전체를 type PASS라고 표시하지 않는다. 핵심 41 source는 위와 같이
strict PASS다. 사람 점수표/context/GUI 추가 구현은 0이다.

SOURCE_CANDIDATE=VERIFIED, LIVE_SUCCESSOR=NOT_INSTALLED,
ACTUAL_READ_AFTER_FIX=PENDING, CORPUS_CPU_FORWARD=NOT_EXECUTED,
BOUNDED_CODEX_PAIR=NOT_EXECUTED, HUMAN_TRANSFER_REVIEW=NOT_EVALUATED/NOT_REQUIRED다.

### 정상 release build의 추가 검증

source `64f5f31e7382f1875d1744c89bb4268d3d96672b`를 GitHub에 반영한 뒤 정상
`deploy_release.sh --build-only`를 실행했다. wheel RECORD 검증은 PASS였으나 독립
installer의 Catalog schema 수기 inventory가 새 invocation/pair-result/workflow-binding
1.1 리소스 세 개를 누락해 build 검사가 거부됐다. 실패한 build
`/tmp/eom-api-build/64f5f31e7382f1875d1744c89bb4268d3d96672b.afpg7Z`는 보존한다.
이 실행은 build-only이며 admission·package install·service 변경·DB 변경·모델 실행은 0이다.
앞의 source suite PASS를 정상 installer PASS로 확대하지 않는다. 기존 authoritative
inventory와 독립 설치 simulation을 일치시킨 successor에서 정상 build를 다시 검증한다.

### Installer inventory와 장시간 owner session 보완

수기 Catalog 목록을 기존 frozen registry의 데이터만 AST로 읽는 exact inventory로
대체했다. source 코드를 import/실행하지 않으며 wheel member 집합·canonical bytes·RECORD,
격리 설치의 public inventory equality와 old/new workflow family 검증을 유지한다.
독립 읽기 검토에서 구체적 차단 결함은 발견되지 않았다.

실측 첫 READ 약 96초와 16개 단위 520개 조회는 access token 기본 TTL 1,800초를
넘길 수 있다. [owner session refresh 설계](ITEM_INFERENCE_TRANSFER_SESSION_REFRESH.md)에
따라 기존 공식 refresh와 `/me`를 재사용했다. 같은 operator/session/authenticated_at을
검증하고 실제 현재 권한을 다시 읽으며, unknown refresh 결과나 snapshot POST를 자동
재전송하지 않는다. TTL·fresh-auth·DB·권한·worker protocol은 바꾸지 않는다.

두 변경을 포함한 fresh 통합 focused 검증은 **291 PASS / 5.09초**다. 처음 잘못된
test 파일명을 지정한 invocation은 collection 0으로 종료했고, 존재하는 일곱 파일로
바로잡아 실행했다. 하위 suite 숫자와 합산하지 않는다. 운영 설치·실제 READ·CPU와
pair 완료는 이 source 결과와 별개다. 사용자 지시에 따라 사람 평가는 요구하지 않는다.
