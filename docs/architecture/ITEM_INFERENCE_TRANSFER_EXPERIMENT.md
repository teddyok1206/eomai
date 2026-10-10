# F5: staged CPU 표현 비교 실험

2026-10-10 UTC. 구현 후보이며 운영 검색·인가·교육 품질 PASS가 아니다.

## 설계 절차

1. **경계:** Catalog producer가 실제 operator와 pinned Graph/policy로 source/report/content를 입장·해석하고 전체 모집단을 공개 직전 재인가한다. Orchestrator가 입력을 workspace에 materialize하고 결과를 검증·commit한다. CPU harness는 이미 준비된 로컬 입력과 읽기 전용 모델만 사용한다. staged actor 문자열은 권한이 아니며 harness는 현재 권한을 확인했다고 주장하지 않는다.
2. **정본:** approved Item/accepted report/Graph/policy/Artifact가 정본이다. profile, text view, 벡터와 실험 결과는 파생 관측이다. content-only는 supported resolver의 canonical Item 본문에서 준비하며 해설/정답/내부 ID를 제외한다. metadata는 accepted report/source의 명시한 소규모 필드만 사용하고 원문 provenance를 유지한다.
3. **identity:** 실험 ID/revision/request hash, exact profile ID/revision/hash, model manifest, view recipe와 population hash를 구분한다. 경로는 identity가 아니다. 기존 profile/worker/source 계약 bytes와 원문 설계는 변경하지 않는다.
4. **resolution:** frozen 입력의 profile canonical hash/source membership/Graph pins, text hash/원본 Artifact pointer, metadata evidence pins, query membership, baseline refs를 검증한다. 파일의 byte bound/hash/schema를 workspace에서 검증한다. latest substitution이나 approval 문자열을 통한 권한 부여는 없다.
5. **access pattern:** keyed exact lookup, set membership/dedup, ordered immutable corpus, 실제 tokenizer 길이 측정, view별 encode-once, bounded query ranking, append-only 실행 증거다.
6. **구조:** map/set/tuple과 canonical JSON staged contract를 사용한다. 최초 입력은 최대 1024 profiles와 16 queries, top-K 기본 8이다. per-input byte bound를 별도로 지킨다. 영속 vector cache/DB/ANN/queue는 없다.
7. **복잡도:** token 검사는 총 text 길이에 선형, 각 view encoding은 N에 비례한다. 임시 matrix 공간 O(Nd), Q개 exact 비교 O(QNd)와 bounded 정렬이다. query마다 후보를 재-encode하지 않는다. model forward 비용을 O(Nd)라고 부르지 않는다.
8. **transaction:** producer admission snapshot을 pin하되 CPU 실행 동안 DB transaction을 유지하지 않는다. 다른 operator의 scope를 섞지 않는다. 전체 population의 재인가 실패는 counts/hash를 포함한 결과 publication을 막는다.
9. **dependency:** standalone JSON Schema 2020-12 이후 frozen 모델과 pure use case를 추가한다. numerical/filesystem behavior는 optional adapter/CLI에만 있다. torch를 core에 추가하지 않는다. direct-module public imports를 사용한다.
10. **failure:** missing view/empty/byte bound/token overflow를 구분하고 원문을 자르지 않는다. 세 view 모두 encodable인 공통 집합과 제외 사유를 공개한다. threshold 미달은 INSUFFICIENT_ENCODING_COVERAGE다. model/hash/runtime 변화는 오류다. 실패를 성공으로 바꾸지 않는다.
11. **대안:** toy script에 text만 붙이면 권한/provenance/분모가 사라지고 기존 ranker를 query별 반복하면 neural work가 중복된다. 별도 retrieval 플랫폼 대신 작은 staged experiment 계약과 기존 offline backend를 재사용한다.

## 입력과 view recipe

request는 actor/Graph/policy/projection/population pins, exact model spec, 고정 view recipe, admitted entries, exact queries, optional supplied official Graph baseline와 budgets를 담는다. producer가 준비한 원본 문항 text와 metadata만 사용한다. harness는 source를 fetch하거나 staged actor를 impersonate하지 않는다. 공식 baseline이 materialize되지 않았으면 NOT_MATERIALIZED로 남긴다.

세 view는 CONTENT_ONLY(원문 문항 text), CONCRETE_FACETS(현재 exact profile claim text), METADATA_ONLY(accepted evidence의 bounded fields)다. metadata에 ID/path/exam filename을 넣지 않는다. 시각 원본을 보지 않은 text-only 실험은 그림 pixels를 검사했다고 주장하지 않는다.

실제 tokenizer와 prefix/special tokens를 포함해 truncation=False로 모든 view를 측정한다. empty/missing/UTF8 limit/512-token overflow를 별도 관측한다. ranking은 세 view의 공통 encodable 집합과 해당 집합에 속한 queries만 사용한다. query 자체는 candidate에서 제외한다. 부족한 coverage를 채우려고 원문을 요약하거나 일부 claim을 몰래 제외하지 않는다. claim/facet aggregation은 별도 reviewed recipe successor다.

## 결과와 실행 증거

결과는 request/model/recipe/population pins, coverage rows, common pool hash, view별 exact rank, integer cosine-millionths/latency-milliseconds/RSS-KiB, encoding 요청/문장 수와 limitations를 담는다. 점수 정수화는 출력에만 적용하며 순위는 full precision으로 정한다. 전체 peak RSS를 view별 독립 memory라고 주장하지 않는다.

human_transfer_review=NOT_EVALUATED, current_authorization=NOT_VERIFIED_BY_HARNESS, production_activation=NOT_PERFORMED를 고정한다. rank 변화는 진단이며 교육적 PASS가 아니다. 실제 corpus·protected OS isolation·Codex pair 실행은 이 source-only 구현의 acceptance에 포함하지 않는다.

data_provenance는 AUTHORIZED_CORPUS_SNAPSHOT 또는 TEST_ONLY_SYNTHETIC를 입력과 결과에 동일하게 기록한다. 합성 입력의 producer_admission은 SYNTHETIC_NON_AUTHORITATIVE이며 실제 Catalog 인가를 주장하지 않는다. 실모델 PINNED_MODEL 실행과 합성 입력 TEST_ONLY_SYNTHETIC는 독립 축이다. 실제 모델이 합성 입력을 처리해도 실제 corpus 검증이나 현재 권한 검증으로 승격하지 않는다.

## 검증

현재 recipe의 CONCRETE_FACETS는 asked judgement/outcome/misconception을 포함한 exact report claims이며 답안 관련 판단이 포함될 수 있다. answer-free crux-only 표현이라고 부르지 않는다. CONTENT_ONLY는 답/해설을 제외하고 METADATA_ONLY는 filename/internal ID를 제외한다. 실제 데이터 측정 후 다른 recipe가 필요하면 successor로 설계한다.

scope의 population_scope는 ALL_ADMITTED_GRAPH_ITEMS 또는 OCCURRENCE_BACKED_PAST_EXAM을 명시하며 policy는 exact accessrev identity를 유지한다. baseline result_sha256는 supplied ordered baseline body 자체의 canonical self-hash이고 원래 official Artifact hash라고 주장하지 않는다. 이 구현의 budgets는 입력·문장·query·thread/batch 상한이며 hard wall-time/RSS OS enforcement를 구현했다는 주장은 아니다. protected runtime의 OS 제한은 후속 gate다.

공식 supplied Graph baseline의 순서는 그대로 보존한다. token 초과로 제외된 후보가 있을 수 있으므로 SUPPLIED_NOT_REEXECUTED는 동일 공통 모집단에서 비교 평가했다는 뜻이 아니다. 두 후보 집합이 같다는 별도 증거 없이는 lexical 대 embedding 품질 비교를 주장하지 않으며 임의로 재정렬하거나 baseline 후보를 없애지 않는다.

schema/model mirror, canonical self-hash, model_copy forgery, duplicate/dangling pins, source/view mismatch, same-population 공통 분모, stable ties, overflow/no truncation, encode-once, integer wire output, fake-backend TEST_ONLY, NOT_EVALUATED와 current-auth 미검증 상태를 테스트한다. 실제 모델/DB/NAS/Codex/다운로드는 opt-in 후속 gate다.

## Source 실행 경계

public use case는 `eom_catalog_service.inference_transfer_experiment.run_staged_inference_transfer_experiment`이다. `TokenMeasuredEmbeddingBackend`를 주입하며 `token_lengths`와 `encode`가 동일한 prefix/tokenizer/special-token 정책을 사용해야 한다. 실제 backend는 별도의 Python 3.12 CPU 환경에서만 구성하고 core에는 numerical dependency를 설치하지 않는다. batch/thread 상한은 backend 구성에 명시적으로 전달한다.

실험 CLI는 `scripts/embedding/run_inference_transfer_experiment.py`이며 운영 API 또는 검색 tool에 자동 연결되지 않는다.

```text
<isolated-python> scripts/embedding/run_inference_transfer_experiment.py
  --workspace <absolute-owned-local-workspace>
  --request request.json
  --request-sha256 <pinned-canonical-request-sha256>
  --output result.json
  --model-store <read-only-pinned-store>
  --model-owner-uid <explicit-owner-uid>
```

CLI는 workspace와 부모의 symlink/unsafe writable ancestry를 거부하며 파일 이름만 workspace에 상대적으로 허용한다. input은 fd 기반 bounded read와 owner/regular-file/single-link/안정성, 중복 JSON member, schema/hash/budget를 확인한다. output은 fd 기반 새 파일 O_EXCL/0600으로만 생성하며 기존 output을 덮어쓰지 않는다. NAS 경로는 worker 출력 workspace로 허용하지 않는다. 파일의 검증·commit와 전체 모집단 재인가는 지원된 Orchestrator/Catalog 경계의 후속 구현 책임이다.

`tests/unit/inference_transfer_experiment_fixtures.py`의 fixture는 TEST_ONLY_SYNTHETIC이며 실제 source 내용·인가·Graph 검색 결과가 아니다. source-only 테스트 및 같은 pinned local model을 사용한 별도 synthetic CPU smoke를 구분해 기록한다. synthetic CPU smoke 성공은 real-corpus admission/coverage/교육 품질/OS isolation을 닫지 않는다.
