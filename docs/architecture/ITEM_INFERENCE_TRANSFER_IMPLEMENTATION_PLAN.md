# 문항 핵심 착상 전이: 구현·검증 계획

상태 시각: 2026-10-10 UTC. 이 문서는 구현 계획이며 운영 활성화·교육 품질 PASS 증거가 아니다.

## 보존한 설계와 목표

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
| F2 | pinned offline local embedding adapter와 exact ranking | dependency isolation, malformed vectors·ties·permission-prefilter tests; 실제 CPU benchmark 별도 | source 및 실제 CPU toy 실행 완료; production 설치·격리 미검증 |
| F3 | Catalog opt-in authorized candidate read use case | actual actor/policy/Graph admission 재사용, 별도 후보 예산·provenance, 기본 retrieval 무변경 | source·격리 PostgreSQL SQL 검증 완료; 실제 corpus 비용 미측정 |
| F4 | Orchestrator 경유 bounded Codex pair comparison | exact A/B, condition+decisive mapping, 차이/새 추론, unsupported/insufficient 처리, schema validation | source wrapper·사용자별 제출·V21 resolver·Runner composition 검증; bootstrap owner 호출·실제 worker·compatible release 대기 |
| F5 | 기존 검색 대비 bounded 실험·human scorecard | lexical/content-only/crux/metadata ablation, recall·latency·memory, 사람이 전이 위치를 평가 | staged 계약·encode-once harness·실모델 3-view 합성 smoke 완료; 실제 corpus/Graph 비교·human 평가 대기 |
| F6 | 문서·회귀·supported 운영 연결 | 설치 package 검증·compatible release·opt-in activation; 교육 판정은 독립 gate | 인증 snapshot API/private Catalog 및 Runner source 연결·임시 설치/DB 검증; 실제 호출부·설치·인증 운영 gate 대기 |

## 비교 표현과 판정

비교 facet은 given condition, intermediate relation, decisive inference, asked judgement, misconception으로 나눈다. deterministic profile은 기존 report 문구와 explicit concept-assessment role을 배열한 **비교용 자료**이며, 새 숨은 조건이나 결정적 착상을 발견했다고 주장하지 않는다. 의미를 새로 추출한 Codex profile은 원문과 구분하고 model/prompt/request/result pins 및 참조를 남긴다.

쌍 비교는 A→B 방향, 각각의 조건·추론 refs, 공유되는 착상, 대응하지 않는 조건, 필요한 새 추론을 필수로 한다. 모델의 `STRUCTURAL_ANALOGY`나 `NEAR_IDENTICAL_CANDIDATE`는 과학적 타당성·사람의 체감·표절 판정·승인 상태가 아니다. 부족한 자료는 `INSUFFICIENT`다.

사람에게는 “A를 풀고 얻은 핵심 아이디어가 B의 어느 부분에 도움이 되는가?”를 묻는다. label은 `표현만 유사 / 같은 개념 다른 착상 / 착상 전이 / 사실상 동일 / 판정 불가`다. exact pair·rubric·reviewer·UTC 판단·도움이 된 부분을 별도 기록한다. synthetic expected label이나 model 출력으로 human PASS를 만들지 않는다.

## 실행 예산·검증과 활성화

- 먼저 source/fake adapter/synthetic tests를 수행한다. 기존 520 보고서를 재생성하거나 새 문항을 출제하지 않는다.
- 모델 후보는 공식 primary documentation에서 license·upstream revision·files·pooling·tokenizer를 확인한다. 초기 BGE-M3는 **조사 후보**이며 설치·EOM 품질이 확인됐다는 뜻이 아니다.
- 실제 모델 실험은 offline local runtime, exact manifest, bounded corpus/pair budget과 공유 GPU capacity를 고정한 후 수행한다. CPU-first로 측정한다. 새 core dependency나 무제한 worker 호출은 하지 않는다.
- 실제 corpus는 supported Catalog retrieval/read/source resolution을 통해 실제 operator 권한으로 읽는다. worker에게 DB/NAS나 impersonated ADMIN을 주지 않는다. report 기반 임베딩은 answer-bearing 접근이다.
- 기존 V2 `HYBRID_LOCAL_MULTIHOP` request나 Evidence V2–V5의 bytes/해석을 바꾸지 않는다. 새 index/model/projection pins는 별도 opt-in request에 명시한다. 벡터 후보가 Graph placement를 위조하지 않는다.
- pure/schema/unit/type/dependency tests → opt-in 실제 local benchmark → bounded Orchestrator comparison → 필요한 disposable DB/live release gate 순서다. 실행하지 않은 것은 PENDING으로 보고한다.
- formatter/linter/mypy/focused regressions와 released schema hash inventory를 확인한다. runtime/model files, vectors, 긴 결과·로그·평가 Artifact는 Git에 넣지 않는다.
- Slack은 F1/F3 구현·검증, 실제 실행 gate, 실험 발견/범위 변경, BLOCKED/완료 등 중요한 milestone만 보고한다. 원문 프롬프트·문항·worker 결과·full log·secret은 보내지 않는다.

## 사람에게 모아둘 확인 사항

1. 실제 서로 다른 소재지만 조건·착상이 대응하는 pair가 유용하게 검색되는가.
2. 같은 소재·공식인데 착상이 다른 pair를 구별하는가.
3. “착상이 연결됨” 설명에 실제 대응 조건과 새 추론이 나오는가.
4. A를 푼 사람이 B를 풀 때 느끼는 도움이 모델 제안과 일치하는가.

위 사항은 자동 기술 검증과 분리해 최종 검토 묶음에 모은다. 사람 평가 전에는 `HUMAN_TRANSFER_REVIEW=NOT_EVALUATED`다.

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
아직 없는 실제 호출부와 HTTP replay/목적 전용 결과 resolution의 설계는
[owner 호출부 후속 설계](ITEM_INFERENCE_TRANSFER_OWNER_INVOCATION_DESIGN.md)에 기록한다.
해당 문서는 source 구현·운영 활성화가 아닌 후속 protocol-first 설계다.

1. 실제 actor의 supported Catalog read 경계를 사용할 수 있는 compatible release와 exact Graph/policy scope를 준비한다. 기존 V2 검색·활성 preset을 바꾸지 않는 opt-in 경로로 제한한다.
2. 실제 corpus의 deterministic profile 길이·E5 token overflow 비율·source resolution query/file-read 비용부터 측정한다. 긴 조건을 버려 성공시키지 않는다. 필요한 facet/chunk successor는 측정 후 별도 설계한다.
3. 동일한 authorized target 집합에서 lexical/Graph, content-only, concrete-facet, metadata 보조의 후보 집합을 비교한다. 사람 label이 없으면 recall/quality PASS를 만들지 않는다.
4. compatible exact-purpose support plan·instruction·runtime/policy release를 준비하고 기존 Orchestrator를 통한 bounded pair comparison을 수행한다. 기존 support/PDF preset의 purpose를 바꾸거나 worker를 직접 실행하지 않는다.
5. 검증 가능한 대응·차이와 사람용 전이 평가 묶음을 제공한다. human gate와 필요한 운영 승인만 분리해 보고한다.
