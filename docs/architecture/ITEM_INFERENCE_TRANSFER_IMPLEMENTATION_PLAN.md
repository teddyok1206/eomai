# 문항 핵심 착상 전이: 구현·검증 계획

상태 기준: 2026-10-11 10:49 UTC, `c8b29f67` 설치·BGE-only 90분 profile 및 합성 18 text의 실제 MEASURED 관측. 원래 520개 E5 실험의 INSUFFICIENT 기록은 보존한다. 이 문서는 구현 계획과 단계별 상태 요약이다.
실제 설치 증거는 [live acceptance 기록](ITEM_INFERENCE_TRANSFER_LIVE_ACCEPTANCE.md)과
정본 deployment record로 확인하며, 설치·service health를 비교 실행·교육 품질 PASS로 확대하지 않는다.

## 보존한 설계와 목표

### 이후 사용자 범위 변경 — 사람 평가 없음

2026-10-10 사용자가 “사람 평가는 없다고 생각해”라고 지시했다. 원문은 그대로 보존하되
현 구현 목표의 완료 조건에서는 실제 사람 평가를 제외한다. 기존 human 계약/owner와
평가 기록은 유지하고 새 사람 점수표나 필수 수동 평가 절차를 추가하지 않는다.
`HUMAN_TRANSFER_REVIEW=NOT_EVALUATED`는 한계 표시이지 현 완료의 blocker가 아니다.
자동 모델 판정을 사람 label로 저장하거나, label 없이 precision/recall/실제 학습 효과를
만들지 않는다. 자동 검증은 source/pointer/grounding closure, 독립 개념·소재·착상 설명,
기존 검색 대비 bounded 후보 실험과 coverage/latency/resource 재현 증거에 집중한다.

사용자가 승인한 직전 답변은 [설계 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)에 그대로 보존했다. 원문 파일 SHA-256은 `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a`다. 설명용 용수철·저항 예시는 실제 corpus 관측으로 취급하지 않는다.

구현 목표는 **A의 풀이에서 배운 결정적 착상이 B에 어디서 통하는지**를 찾고, 그 대응·차이·추가 추론을 정확한 근거와 연결하는 것이다. 같은 소재·개념·공식·정답·일반적인 풀이 단계만으로 전이를 확정하지 않는다. 후보 검색, 모델의 구조 대응 제안, 사람의 체감 전이 평가는 다른 단계다.

## 책임·정본·경계

1. **책임:** Catalog가 권한 있는 자료의 비교용 read projection과 후보 입장을 소유한다. 임베딩은 application port의 제거 가능한 로컬 adapter다. Codex의 쌍 비교는 기존 Orchestrator의 실행·staging·검증·commit 경계를 사용한다. worker끼리 통신하거나 DB/NAS에 접근하지 않는다.
2. **정본:** 승인된 Item Revision, 기존 accepted base analysis와 additive V10 solution report, pin된 Graph/policy/원문 Artifact가 정본이다. 비교 표현·벡터·쌍 평가는 파생물이며 원문을 덮지 않는다. 보고서는 검증 가능한 풀이 근거이지 비공개 사고 과정이 아니다.
3. **identity/revision:** profile 논리 ID, immutable profile revision, Artifact identity/revision, canonical hash를 분리한다. 모델 upstream commit과 local model manifest도 분리한다. 정규화·추출·토크나이저·pooling 정책 변경은 새 revision이다.
4. **resolution:** Item/source/accepted analysis/solution receipt/report/Graph/policy의 exact revision, schema, media, member, hash, lifecycle와 실제 actor 권한을 검증한다. 누락·중복 accepted successor·미해결 풀이·폐기·해시 오류는 명시적 제한/오류다. latest나 문항 내용만으로 풀이 근거를 대체하지 않는다.
5. **주요 access pattern:** indexed exact revision lookup, accepted successor batch lookup, source membership/dedup, immutable ordered profiles, bounded exact vector scan, pair mapping의 reference closure, append-only 평가다. 기존 lexical/Graph 경로는 그대로 둔다.
6. **구조:** profile/source는 frozen typed values, refs는 set/map 검증, vector snapshot은 immutable ordered matrix + exact profile references다. 최초 실험에는 새 DB 테이블·ANN/vector DB·queue가 없다. 향후 저장은 기존 Artifact/manifest 경계로 하며 binary/vector를 PostgreSQL에 넣지 않는다.
7. **규모/복잡도:** 원래 기출 520개부터 bounded 실험한다. projection/reference 검증은 steps+refs에 선형, exact search는 O(Nd), 공간 O(Nd), candidate merge는 ID keyed map이다. 모델 embedding은 batch 단위다. 대량화는 실측 결과로 판단한다.
8. **transaction/concurrency:** 기존 Catalog authorization/read snapshot과 Orchestrator job/idempotency/claim/lease/commit을 재사용한다. 서로 다른 operator의 eligible set은 섞지 않는다. immutable index가 permission cache가 되지 않으며 dereference 직전 재확인한다.
9. **dependency:** contracts → application pure projection/ports → infrastructure adapter로 분리한다. contracts/pure projection은 SQLAlchemy, filesystem, transformers/torch, HTTP를 import하지 않는다. core 설치에 GPU/모델 의존성을 추가하지 않는다.
10. **failure/retry:** 모델 미설치·비지원 runtime·빈 결과·report 없음은 UNAVAILABLE/INSUFFICIENT로 보고한다. NaN/zero norm/차원·pin 불일치는 명시적 오류다. timeout 이후 새 identity로 중복 실행하지 않는다. 모델 결과는 grounded claim/ref validation 후에만 다음 단계로 전달한다.
11. **단순한 대안:** 기존 lexical/Graph 검색만으로 기본 기능을 계속 제공할 수 있지만 다른 소재의 같은 착상 후보를 놓칠 수 있다. 일반 operation 라벨이나 full item text 하나의 cosine만 쓰는 방식은 사용자가 지적한 generic/surface similarity를 해결하지 못한다. 따라서 별도 facet 표현과 작고 명시적인 opt-in adapter를 추가한다. 기존 evidence 의미를 바꾸거나 병렬 검색 플랫폼을 만들지 않는다.

## 단계와 exit gate

| 단계 | 구현·검증 | 완료 조건 | 현재 상태 |
|---|---|---|---|
| F0 | 답변 원문 보존·goal·기존 경계 점검 | 원문 read-back/hash, 기존 경계와 제한 기록 | 완료 |
| F1 | additive JSON Schema 2020-12 → frozen 모델 → grounded deterministic profile | exact refs/hash/closure/uncertainty tests, predecessor bytes 불변 | source 구현·검증 완료 |
| F2 | pinned offline local embedding adapter와 exact ranking | dependency isolation, malformed vectors·ties·permission-prefilter tests; 실제 CPU benchmark 별도 | source·CPU toy·보호 CPU/model 발행 완료. 원래 실제 corpus는 E5 512-token에서 INSUFFICIENT: 착상 view 517/520 overflow, forward 0. 내용을 보존하는 긴 입력 모델의 fit 보완 필요 |
| F3 | Catalog opt-in authorized candidate read use case | actual actor/policy/Graph admission 재사용, 별도 후보 예산·provenance, 기본 retrieval 무변경 | 공유 `68a648c2`와 실제 guiadmin 520 population의 PREPARE 1/READ 33/전체 AUTHORIZE 1 완료. 기본 retrieval 불변. 이전 실패 이력 보존; publisher staging caller 설정 누락의 동일-key 복구 대기 |
| F4 | Orchestrator 경유 bounded Codex pair comparison | exact A/B, condition+decisive mapping, 차이/새 추론, unsupported/insufficient 처리, schema validation | V11 세 축 source·호환 공유 경계·운영 definition 등록 완료. 실제 native protocol/control PREPARE·RELEASE 및 최대 두 쌍 MEMBER_VERIFIED/replay는 대기 |
| F5 | 기존 검색 대비 bounded 자동 실험 | lexical/content-only/crux/metadata의 후보·순위·공통 모집단·coverage·latency·memory; label 없는 정확도나 교육 효과 주장 금지 | 실제 520/4-query/3-view token coverage·CPU load/RSS 관측 완료. common pool 3/queries 제외로 순위는 0이며 MEASURED 아님. 원래 결과 게시와 적합한 모델의 명시적 successor 실험 대기. 사람 평가는 불필요 |
| F6 | 문서·회귀·supported 운영 연결 | 설치 package 검증·compatible release·opt-in activation; 사람 평가 불필요, 자동 검증과 실제 교육 효과 구별 | `68a648c2` 설치·migration 0051 unchanged·6 callback·8 service/chat READY 확인. 변경 경계 559 PASS와 원문/계약/adapter fresh 124 PASS. 실패 모델 결과를 성공으로 바꾸지 않으며 실제 successor CPU·control·두 쌍·최종 대조 gate는 남음 |

위 F2–F6의 원래 corpus 관측은 역사적 68a648c2 실행이다. 후속 실제 설치는 c8b29f67이며
6개 release callback/8개 서비스·API LIVE/READY PASS, migration0051/CPU06134는 그대로다.
BGE 합성 18 text는 무절단 MEASURED(encoding44,325ms/RSS2,486,848KiB)이고,
520×3 text 단순 환산 proxy 약64분에 근거해 BGE만 90분으로 조정했다.
이는 전체520개 fit이나 후보 품질 PASS가 아니다. 원래 동일-key 게시 복구와 새520개
BGE/두V11쌍·replay는 실제 사용자 재인증 후 수행할 PENDING이다.
원문 요구별 독립 source 대조에서 추가 필수 구현 누락은 찾지 못했으며,
[최종 대조 기록](ITEM_INFERENCE_TRANSFER_FINAL_CONFORMANCE_GAPS.md)의 실제 종료 조건은 유지한다.

## 비교 표현과 판정

실제 모델의 입력 적합성 누락과 최소 보완은
[모델 fit 설계](ITEM_INFERENCE_TRANSFER_MODEL_FIT.md)에 기록했다. 이는 기존 착상
표현·원문·인가를 유지하면서 실제 벡터 후보를 만들기 위한 변경이다. 새 검색 플랫폼,
embedding recipe나 평가 GUI를 추가하지 않는다.

비교 facet은 given condition, intermediate relation, decisive inference, asked judgement, misconception으로 나눈다. deterministic profile은 기존 report 문구와 explicit concept-assessment role을 배열한 **비교용 자료**이며, 새 숨은 조건이나 결정적 착상을 발견했다고 주장하지 않는다. 의미를 새로 추출한 Codex profile은 원문과 구분하고 model/prompt/request/result pins 및 참조를 남긴다.

쌍 비교는 A→B 방향, 각각의 조건·추론 refs, 공유되는 착상, 대응하지 않는 조건, 필요한 새 추론을 필수로 한다. 모델의 `STRUCTURAL_ANALOGY`나 `NEAR_IDENTICAL_CANDIDATE`는 과학적 타당성·사람의 체감·표절 판정·승인 상태가 아니다. 부족한 자료는 `INSUFFICIENT`다.

기존 설계의 optional 사람 label은 `표현만 유사 / 같은 개념 다른 착상 / 착상 전이 / 사실상 동일 / 판정 불가`다. 기존 exact pair·rubric·reviewer·UTC 기록 계약은 보존한다. 사용자 범위 변경에 따라 사람 평가를 요청하거나 새 scorecard를 구현하지 않는다. synthetic expected label이나 model 출력으로 human PASS를 만들지 않는다.

## 실행 예산·검증과 활성화

- 먼저 source/fake adapter/synthetic tests를 수행한다. 기존 520 보고서를 재생성하거나 새 문항을 출제하지 않는다.
- 모델 후보는 공식 primary documentation에서 license·upstream revision·files·pooling·tokenizer를 확인한다. 초기 BGE-M3는 **조사 후보**이며 설치·EOM 품질이 확인됐다는 뜻이 아니다.
- 실제 모델 실험은 offline local runtime, exact manifest, bounded corpus/pair budget과 공유 GPU capacity를 고정한 후 수행한다. CPU-first로 측정한다. 새 core dependency나 무제한 worker 호출은 하지 않는다.
- 실제 corpus는 supported Catalog retrieval/read/source resolution을 통해 실제 operator 권한으로 읽는다. worker에게 DB/NAS나 impersonated ADMIN을 주지 않는다. report 기반 임베딩은 answer-bearing 접근이다.
- 기존 V2 `HYBRID_LOCAL_MULTIHOP` request나 Evidence V2–V5의 bytes/해석을 바꾸지 않는다. 새 index/model/projection pins는 별도 opt-in request에 명시한다. 벡터 후보가 Graph placement를 위조하지 않는다.
- pure/schema/unit/type/dependency tests → opt-in 실제 local benchmark → bounded Orchestrator comparison → 필요한 disposable DB/live release gate 순서다. 실행하지 않은 것은 PENDING으로 보고한다.
- formatter/linter/mypy/focused regressions와 released schema hash inventory를 확인한다. runtime/model files, vectors, 긴 결과·로그·평가 Artifact는 Git에 넣지 않는다.
- Slack은 F1/F3 구현·검증, 실제 실행 gate, 실험 발견/범위 변경, BLOCKED/완료 등 중요한 milestone만 보고한다. 원문 프롬프트·문항·worker 결과·full log·secret은 보내지 않는다.

## 사람 평가로만 확인 가능한 미측정 사항 — 현 완료 조건 아님

1. 실제 서로 다른 소재지만 조건·착상이 대응하는 pair가 유용하게 검색되는가.
2. 같은 소재·공식인데 착상이 다른 pair를 구별하는가.
3. “착상이 연결됨” 설명에 실제 대응 조건과 새 추론이 나오는가.
4. A를 푼 사람이 B를 풀 때 느끼는 도움이 모델 제안과 일치하는가.

위 사항은 자동 기술 검증의 한계로만 기록한다. 현 목표에서 사람 검토 묶음이나 점수표를 추가 생성하지 않는다. `HUMAN_TRANSFER_REVIEW=NOT_EVALUATED / NOT_REQUIRED_FOR_CURRENT_COMPLETION`이다.

## 최종 설계 대조 검토 — 사용자 요청 반영

2026-10-10 사용자는 작업 마무리 시 최초 기획한 설계대로 유사도 기능이 구현됐는지
확인하도록 요청했다. 이는 새 기능이나 acceptance 재실행 요구가 아니라 기존 목표의
최종 적합성 검토다. 위 원문과 SHA-256을 기준으로 아래 요구를 실제 구현·테스트·운영
증거에 연결한다. 원문은 변경하지 않으며 후속 장애 수정으로 목표를 축소하지 않는다.

| 원문 요구 | 마무리 때 확인할 내용 |
|---|---|
| 핵심 착상 전이 | 같은 소재·개념·공식 또는 일반 풀이 단계의 유사성과 결정적 착상의 전이를 구분하는가 |
| 조건의 역할 | 주어진 조건·숨은 관계·결정적 추론·질문·오개념을 정본 풀이보고서와 정확한 참조로 연결하는가 |
| 후보와 판정 분리 | 로컬 임베딩은 후보를 찾고, 점수만으로 대응·정확성·승인·표절을 확정하지 않는가 |
| 조건 대응과 차이 | Codex 쌍 비교가 A→B의 조건·추론 대응, 적용되지 않는 부분과 추가 추론을 근거와 함께 남기는가 |
| 개념·소재·착상 구분 | facet과 메타데이터를 구분하며 content-only·착상·메타데이터 보조를 동일한 인가 모집단에서 비교하는가 |
| 기존 시스템 활용 | GraphRAG와 승인된 문항·풀이보고서를 대체하지 않고 실제 사용자 권한·pin·해시·Orchestrator 경계를 유지하는가 |
| 사람의 풀이 전이 평가 | 기존 optional 계약·owner·기록과 모델 가설의 분리를 보존하는가; 이후 사용자 지시에 따라 신규 평가·점수표는 완료 조건이 아님 |
| 실험과 제한 | 기존 검색 대비 결과·실행 예산·실패·미검증 항목을 재현 가능하게 보존하며 자동으로 성공을 꾸미지 않는가 |

최종 보고에는 각 요구의 코드/계약 위치, 관련 테스트, 실제 설치·실행 증거 및 남은
차이를 대조표로 남긴다. `SOURCE_VERIFIED`, `LIVE_VERIFIED`, `HUMAN_NOT_EVALUATED`,
`GAP`을 구분하고, 구현 누락은 기존 범위 안에서 보완한다. 필요한 운영 인증·권한과
실행 gate만 구분하며 사람 평가를 완료의 선행 조건으로 다시 추가하지 않는다.
source PASS를 전체 설계·교육 품질 PASS로 확대하지 않는다.

현재 읽기 전용 사전 대조에서는 profile → 후보 → 근거 연결 A→B 비교 → 별도 사람 평가의
소스 경로를 확인했다. 그러나 첫 실제 READ 실패로 corpus 후보 성능·worker 비교·사람
label은 아직 확인하지 못했다. 최종 대조에서는 소재·개념·착상별 설명이 실제 결과에
구분되는지, 차이/추가 추론의 빈 배열이 정말 해당 없음인지, 메타데이터의 실제 활용 범위가
구조·수식·승인 보고서 summary로 한정된다는 점도 명시적으로 확인한다. 합성 테스트의
순위나 모델 가설을 사용자의 실제 풀이 전이 평가로 대체하지 않는다.

현재 `HumanTransferEvaluation`은 exact pair/rubric/reviewer/UTC와 전이 위치를 검증하는
frozen 계약이고 `evaluate_transfer_ranking`은 이미 인가·해결된 입력의 순수 지표 함수다.
이 두 기능만으로 실제 사람 label 등록 경로가 구현됐다고 볼 수 없어,
[작은 human owner 설계](ITEM_INFERENCE_TRANSFER_HUMAN_REVIEW_OWNER.md)에 따라 기존
Orchestrator 게시/조회 경계와 owner-local CLI를 보완했다. 실제 current principal,
exact pair/source/rubric와 reviewer를 확인하고 bundle/record를 별도 immutable Artifact로
저장한다. source 검증·설치·실제 사람 판단은 각각 별개다. 별도 평가 GUI를 사후 필수 조건으로
추가하지 않으며, schema/pure metric/모델 가설만으로 사람 평가 또는 전체 goal 완료를 선언하지 않는다.

## 첫 구현 checkpoint와 후속 순서

[첫 구현·실험 기록](ITEM_INFERENCE_TRANSFER_FIRST_CHECKPOINT.md)과
[worker binding 설계](ITEM_INFERENCE_TRANSFER_WORKER_BINDING.md)에 실행 범위와 미검증 항목을 기록했다.
[제출·준비·실행 검증](ITEM_INFERENCE_TRANSFER_THIRD_CHECKPOINT.md)은 새 source 경계와
임시 PostgreSQL 동시성 검증을 기록하며, 실제 자료/worker/운영 품질 승인은 포함하지 않는다.
[인증 자료 조회·전용 실행 연결](ITEM_INFERENCE_TRANSFER_FOURTH_CHECKPOINT.md)은 source API,
Catalog owner, pure staging, bootstrap, V21 resolver와 Runner의 후속 검증 및 아직 없는 실제
호출부·운영 증거를 구분한다.
[모집단·쌍 재인가](ITEM_INFERENCE_TRANSFER_CORPUS_SCOPE.md),
[전용 실행 목적](ITEM_INFERENCE_TRANSFER_EXECUTION_PURPOSE.md),
[staged 실험](ITEM_INFERENCE_TRANSFER_EXPERIMENT.md)은 추가 설계·검증 경계다.
F1–F4 source 구현 완료를 F5–F6 또는 전체 goal 완료로 해석하지 않는다.
HTTP replay/목적 전용 결과 resolution 및 아직 남은 실제 운영 호출부의 설계는
[owner 호출부 후속 설계](ITEM_INFERENCE_TRANSFER_OWNER_INVOCATION_DESIGN.md)에 기록한다.
후속 source 구현·검증은 [다섯 번째 checkpoint](ITEM_INFERENCE_TRANSFER_FIFTH_CHECKPOINT.md)에
기록한다. 그 checkpoint의 source 검증과 이후 실제 공유 release를 구분하며,
설치된 격리 CPU launcher/control owner의 실제 corpus·control 발행·human gate는 대기다.
실제 guiadmin 승인 이후 인증 owner 호출과 독립 CPU 설치 경계는
[여섯 번째 checkpoint](ITEM_INFERENCE_TRANSFER_SIXTH_CHECKPOINT.md)에 구분해서 기록한다.
그 이후 실제 설치 component map, no-forward 실패/권한 수정 및 남은 운영 gate는
[live acceptance 기록](ITEM_INFERENCE_TRANSFER_LIVE_ACCEPTANCE.md)에서 확인한다.

1. compatible shared release는 READ 응답 크기 분류 보완을 포함한 `f12fb971`로 successor 설치했다. 이전 `7383d1c6` 실행에서 실제 `guiadmin` original corpus 520/520과 exact Graph/preset metadata 및 query-free PREPARE 79,325.809 ms 완료를 확인했다. 실제 첫 READ는 terminal 실패했고 CPU forward는 실행하지 않았다. 실제 요청의 동일 overflow 원인 여부는 UNKNOWN으로 유지한다. 같은 공식 경로·exact pins·입력 receipt를 보존하며 기존 V2 검색·활성 preset은 바꾸지 않는다. 새 실제-principal 최소 READ 진단 뒤 같은 execution의 복구를 판단한다.
2. 실제 corpus의 deterministic profile 길이·E5 token overflow 비율·source resolution query/file-read 비용부터 측정한다. 긴 조건을 버려 성공시키지 않는다. 필요한 facet/chunk successor는 측정 후 별도 설계한다.
3. 동일한 authorized target 집합에서 lexical/Graph, content-only, concrete-facet, metadata 보조의 후보 집합을 비교한다. 사람 label이 없으면 recall/quality PASS를 만들지 않는다.
4. compatible exact-purpose support plan·instruction·runtime/policy release를 준비하고 기존 Orchestrator를 통한 bounded pair comparison을 수행한다. 기존 support/PDF preset의 purpose를 바꾸거나 worker를 직접 실행하지 않는다.
5. 검증 가능한 대응·차이와 독립 개념·소재·착상 설명의 canonical 결과를 제공한다. 필요한 운영 인증·권한과 미측정 교육 효과는 구분한다. 사람 평가 묶음·점수표·human gate는 추가하지 않는다.

## 실제 snapshot 비용 발견과 요청범위 재사용 설계 — 2026-10-10

실제 original corpus 520/520 조회와 metadata 확인은 성공했다. 다음 query-free snapshot
PREPARE는 API request `req_9044d63519bde9fb1eef0c6c4762baa8`에서 120,107.849 ms 후
종료됐다. CPU 실행과 입력 receipt 작성 전이다. Catalog의 동기 handler는 소켓 timeout으로
취소되지 않으므로, 관측 실패만으로 재제출하거나 새 identity를 만들지 않는다.

source inspection에서 기존 request-scoped Artifact cache는 raw bytes와 exact PDF/PNG
hash 검사만 재사용한다. 같은 extraction batch의 manifest/acceptance/result/layout에 대한
JSON Schema·Pydantic 전체 검증과 item/work-unit/decision 목록 탐색은 문항마다 반복된다.
이는 batch의 문항 수 B에 대해 O(B²) 반복이 될 수 있다. live 병목의 정확한 비중은 아직
측정하지 않았으며 전체 Graph 반복 파싱이나 PDF 520회 재hash로 해석하지 않는다.

1. **책임/경계:** 기존 Catalog source resolver에서 immutable extraction provenance의
   typed decode/index 비용만 줄인다. snapshot·검색·worker·권한 경계는 그대로다.
2. **정본:** 등록된 exact Artifact member bytes와 released schema가 정본이며 cached
   typed value/index는 조회 한 번의 파생물이다. DB·NAS·원문은 수정하지 않는다.
3. **identity/revision:** Artifact ID, revision ID, member, raw SHA, schema, media, byte bound를
   key로 분리한다. path나 extraction batch logical ID만으로 검증 결과를 재사용하지 않는다.
4. **resolution:** cache miss는 기존 raw-member resolution, hash, JSON Schema 및 Pydantic
   검증을 모두 수행한다. hit도 문항별 현재 lifecycle/approval/decision/source-chain 대조를
   생략하지 않는다. cache는 권한 증거가 아니며 다른 요청·actor와 공유하지 않는다.
5. **access pattern:** 동일 exact member의 반복 decode와 work-unit/item/decision key lookup.
   전체 batch 재검증·선형 탐색을 unique-member decode와 keyed lookup으로 바꾼다.
6. **구조/index:** 요청범위 typed cache와 dict index를 사용한다. 기존 duplicate/cardinality
   검사 의미를 보존한다. byte/entry budget은 명시적으로 제한하고 budget 밖은 uncached
   기존 검증으로 fallback한다. 전역 cache, 새 DB/index, durable permission cache는 없다.
7. **복잡도/규모:** B개의 Item과 D개의 공유 member에 대해 decode/index build는 각 member
   한 번, Item lookup은 평균 O(1)을 목표로 한다. 메모리는 bounded typed dependencies에
   비례한다. synthetic shared-batch 검사에서 parse/validation 횟수와 scaling을 기록한다.
8. **transaction/concurrency:** 기존 단일 capture/request의 lifetime에서만 재사용한다.
   현재 actor와 source 관계는 기존 transaction에서 계속 확인한다. 다음 capture는 새 cache다.
9. **dependency/ownership:** typed provenance decoding/index를 이름이 분명한 기존 Catalog
   책임 아래 둔다. domain/contracts에서 SQL·filesystem·cache adapter를 import하지 않는다.
10. **failure/retry:** 실패 결과는 cache하지 않는다. stale revision/hash/schema mismatch,
    duplicate/ambiguous provenance는 기존 stable error로 실패한다. 구현 수정 후 replay는
    기존 read contract와 exact source pins로 수행하고 이전 timeout 증거를 보존한다.
11. **대안/검증:** timeout 확대나 source 수 축소는 반복 비용을 해결하지 못한다. 새 검색
    framework 없이 existing request cache/resolver를 확장한다. exact output equivalence,
    cache key 분리, live-state 재확인, 요청 간 격리, budget fallback, repeated-batch 비용,
    기존 source/retrieval/snapshot 회귀를 검증한다. released schema/migration 변경은 없다.

## Admission과 공식 Graph 조회의 단일 transaction 재사용 — 2026-10-11

실제 같은 입력의 PREPARE는 85,908 ms에 완료됐지만 첫 READ는 120,090 ms에
UNAVAILABLE로 종료됐다. CPU launch는 0이다. 이번 조회의 지배적 병목과 실제 응답
크기는 아직 UNKNOWN이다. 소스에서는 full-population admission과 각 query의 공식
retrieval이 별도 immutable provenance cache를 만들어 같은 member를 반복 검증한다.
이는 이전 문항별 공유-batch 최적화와 다른 호출 경계다.

1. **책임/경계:** 기존 `KnowledgeRetrievalApplicationService`가 owner-local
   `ReadOnlyKnowledgeReuseContext`를 만들고, snapshot adapter는 공개 context만 전달한다.
   `create_read_only_reuse_context(session, scope)`, 기존 pool/retrieve의 optional keyword
   `reuse_context`를 사용한다. 새 wire schema·DB·queue·dependency는 필요하지 않다.
2. **정본:** 기존 immutable Artifact member와 typed provenance가 정본이다. cache는
   같은 owner read transaction의 성공한 byte/decode/index 검사를 재사용하는 파생물이다.
3. **identity/revision:** service/Artifact reader·Session·실제 transaction identity와 exact
   Graph pointer·policy revision/hash·actual actor/role/permissions·source classes·query kind·
   evidence budget을 bind한다. Artifact cache key와 provenance decoder key는 유지한다.
4. **resolution:** 각 public call의 Graph/policy/authorization, association/run SQL,
   Item lifecycle/approval/decision/lineage 및 exact source-pointer 검사는 그대로 실행한다.
   이들의 결과·권한·ranking·whole resolved-source maps는 context에 캐시하지 않는다.
5. **access pattern:** pool 및 최대 네 query 사이에서 같은 exact Artifact/provenance의
   반복 read/hash/decode/index를 재사용한다. 새로운 source는 기존 resolver로 확인한다.
6. **구조/index:** 기존 bounded Artifact cache와 PastExam typed provenance cache만 공유한다.
   association/run/declared/resolved/pointer maps는 매 call 새로 만든다. 현재 Item-only scope에
   불필요한 EducationalDocument cache나 전역 registry는 공유하지 않는다.
7. **복잡도/규모:** Q개 overlapping 조회의 공유 immutable member 검증은 O(Q·D)에서
   보존 상한 내 O(D)로 줄인다. source별 현재 검사는 유지한다. Artifact 64 MiB와 provenance
   64 MiB/1,024 members/100,000 index rows 상한 및 uncached fallback은 불변이다.
   Artifact 검증 key 보존도 4,096개로 제한한다. 초과 member는 기존 전체 검증을 수행하며
   보존만 하지 않는다. 이는 source/query/result 상한을 줄이는 변경이 아니다.
8. **transaction/concurrency:** snapshot의 단일 REPEATABLE READ / READ ONLY transaction
   안에서만 context를 생성·사용한다. 다른 Session/service/scope/transaction 또는 종료된
   transaction 사용은 거부한다. 다음 READ는 새 context다. thread/global/영속 cache는 없다.
9. **dependency/ownership:** context/cache/resolver는 Catalog infrastructure/application 책임이다.
   snapshot은 private cache에 접근하지 않는다. domain/contract는 SQL·filesystem을 import하지 않는다.
10. **failure/retry:** 실패 검사는 캐시하지 않는다. 기존 오류·timeout·adaptive split 의미는
    바꾸지 않으며 자동 retry나 execution identity 변경은 없다. source 수정은 실패 이력과 별개다.
11. **대안/검증:** timeout 확대·source 축소·새 async framework는 중복 비용을 해결하지 못한다.
    작은 context 재사용으로 한정한다. exact output/order 동등성, 매 call authorization/lifecycle,
    session/transaction/scope 격리, 실패 비보존, key 분리, 상한 fallback, 520+4 overlap의
    synthetic 검증 횟수와 기존 source/retrieval/snapshot 회귀를 확인한다. 합성 complexity
    증거는 실제 latency PASS로 확대하지 않는다.

### 스키마 초기화 비용과 문서 검증 비용의 분리

소스 합성 fixture를 같은 구조로 520회씩 세 표본 반복했다. root 재실행 중앙값은
전체 295 schema cold registry 구성 1.622초(프로세스 최초 1회), warm validator 구성
0.387초, fake reader의 V10 evidence row 전체 검증 2.907초, 64단계/64개 연결 report의
JSON Schema 검증 5.563초다. warm public 검증 10,920회 동안 registry 재구성은 0회였다.
따라서 매 row마다 전체 registry를 재구성한다는 가정으로 새 전역 validator cache를
추가하지 않는다. 기존 bounded provenance fixture의 네 member는 repeated hit에도
총 read 4회였다. 이는 실제 기출 520개의 DB/NAS/보고서 길이·지연을 측정한 값이 아니다.
운영 조회·인증·모델 호출은 모두 0이다.

재현 도구는 `/tmp/eom-catalog-schema-cost-diagnostic.py`, SHA-256
`bb532c241c994fd71529e862ffbbeaf14390d99fc0aa08060af044f341c64e1d`이며,
explicit `eom-core` interpreter와 source PYTHONPATH를 사용했다. 긴 결과나 실제 문항
payload는 Git/Slack에 넣지 않는다. 측정 결과로 deadline 확대·권한 생략을 정당화하지 않는다.

### 변경 경계의 source 동결 검증

root fresh 회귀는 Catalog source/provenance/retrieval/ChatRAG/pair authorization,
snapshot producer/service/transport/staging/binding/diagnostics, V11 service, API snapshot,
release inventory/wheel 및 dependency boundary를 함께 실행해 **559 PASS / 26.22초**다.
소스 2개와 새 context 테스트 strict mypy 3파일 PASS, 수정 Python 5파일 Ruff/format 및
diff 검사 PASS다. Starlette의 기존 httpx TestClient deprecation warning 1개는 유지한다.
선행 overlapping suite와 합산하지 않는다. 초기 fixture의 새 필수 keyword 누락과
작성 중 test-only typing/lint 오류는 바로잡고 위 fresh 실행으로 확인했다.

합성 admission 520개와 네 query의 64개씩 source 검사에서 권한 확인 5회,
현재 source 확인 776회는 동일했다. 공유 member read는 20→4회, 각 provenance schema
검증은 5→1회이며 반환된 pool/query fixture와 순서는 정확히 같았다. 다른 session/
service/reader/thread/scope/Graph/policy/transaction 및 종료·nested transaction을 거부한다.
따뜻한 decoder cache에서도 실제 pure source resolver의 decision·coverage·Artifact 승인·
revision·lineage 변경을 거부했다. key 분리·실패 비보존·상한 fallback·다음 transaction
재검증도 확인했다. authority/SQL/ranking 일부는 명시적인 fake port이며 실제 운영
인가나 latency PASS를 대신하지 않는다.

기존 wire schema/definition/instruction bytes, 원래 input/execution과 설계 원문 SHA는
변경하지 않았다. 실제 compatible 배포·동일 입력 조회·CPU·최대 두 pair 및 replay는
source 검증과 별도 gate이며 아직 PENDING이다. 사람 평가는 필요하지 않다.
