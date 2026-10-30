# 풀이보고서 양식과 무관한 임베딩 입력

2026-10-29 UTC. 사용자 요구: 같은 풀이 정보가 보고서 양식 때문에 다른 유사도로
취급되지 않아야 한다. 이는 과학적 내용이 다른 보고서까지 같은 점수를 보장한다는 뜻이 아니다.

## 현재 확인한 경계

기출 520개는 accepted V10 풀이보고서 → `accepted-solution-comparison/1.0` profile →
`CONCRETE_FACETS`로 연결된다. 이 입력은 report JSON 전체가 아니라 구체적 claim 텍스트다.
등록된 AI의 독립 검토는 별도 `registered-item-review-comparison/1.0` family다.
가져온 창작의 source solution V1/V2는 공식 조회에 보존되지만, 이 둘 중 하나로 위장해
임베딩되지 않는다. 현재 기존 accepted-report resolver는 창작 보고서를 누락 보고서로 센다.
**Graph 등록 호환성과 풀이 임베딩 준비 완료는 다른 상태다.**

## 좁은 공통 표현과 책임

1. 책임은 Catalog의 결정적 projection이다. worker는 공개 가능한 풀이를 기록하고, 기존
   application이 source/Item/Graph/보고서 Artifact의 실제 권한·schema·hash·lifecycle을 검증한다.
   projection에 typed 값이 들어왔다는 사실은 저장·승인·권한의 증명이 아니다.
2. 정본은 원래 보고서와 exact Item/source/accepted-analysis 또는 등록 계보다. 비교 텍스트는
   재계산 가능한 파생 값이며 원문/기존 Graph/보고서를 수정하지 않는다.
3. `public-solution-text/1.0`은 공통으로 존재하는 **검증 가능한 풀이 단계의 내용**만 담는다.
   기출의 rationale/outcome과 창작의 reasoning_summary를 원래 순서대로 연결한다.
   보고서 family, 제목, ID, JSON key, step 번호, source 출처, 경고는 수치 feature에 넣지 않는다.
4. Unicode NFC와 공백 표현만 정규화한다. 단위·음수·부정·첨자·지수·수식 기호를 삭제하거나
   NFKC로 바꾸지 않는다. 과학 문장을 임의 요약·잘라내기·재서술하지 않는다.
5. 공개 풀이가 없으면 `UNAVAILABLE`이다. 독립 검토의 결론만 있는 보고서를 전체 풀이로
   바꾸거나, 빈 필드를 다른 source의 해설로 채우지 않는다. 실제 정보량 차이는 coverage로
   남기며 0점이나 동등한 정보로 표현하지 않는다.
6. 원문 답과 독립 답의 불일치·모든 경고는 원래 보고서/계보에 남는다. 동일한 경고 문구가
   많다는 이유로 두 문항을 유사하다고 계산하지 않는다. 필요 시 별도 품질 필터가 사용한다.
7. 접근은 한 보고서의 순서 순회 O(text bytes), 임시 공간 O(text bytes)다. 정렬/검색 DB나
   별도 model/queue/cache가 필요 없다. normalized text hash는 내용 재사용 키이며 다른
   source의 identity/권한을 합치는 키가 아니다.
8. 계약/domain 값은 IO를 하지 않는다. 파일·NAS·DB 해석은 기존 Catalog/Orchestrator adapter가
   소유한다. 정규화 함수를 worker와 임베딩 GPU에 각각 복제하지 않는다.
9. transaction은 원래 source admission과 increment owner 경계다. 같은 원문/recipe는 같은
   text hash이며, 내용 변경은 새 encoding이다. 기존 FAILED·accepted·index history를 덮지 않는다.
10. 현재 GPU/QUERY의 pinned recipe/namespace는 그대로 둔다. 새 공통 view를 실제 인덱스에
    적용하려면 **명시적인 successor recipe/namespace/source evidence 계약**을 먼저 추가하고
    같은 표현으로 query/candidate를 모두 인코딩한다. 구 벡터와 새 벡터를 섞지 않는다.
11. 단순 대안인 raw JSON 임베딩은 양식·ID·경고의 영향과 출처 혼동을 만든다. 기존 renderer를
    제자리 교체하면 released input hash 의미가 바뀐다. 따라서 공통 파생 표현을 추가하되
    기존 recipe와 이력은 보존한다.

## 구현·검증과 활성화 구분

첫 단계는 공통 값 계약과 기출/창작 V1/V2 어댑터다. 같은 풀이를 다른 field/step 분할,
줄바꿈·ID·출처로 표현해도 **실제 encode에 쓸 text와 text hash가 같음**을 확인한다.
단위/부정/수치 변경에는 hash가 달라야 한다. 원래 보고서가 불변인지도 검사한다.
이후 기존 incremental registry에 successor view를 연결하고, 원래 520개와 창작 표본을 같은
모델/recipe로 재인코딩해 활성화한다. 없는 전체 풀이를 검토 결론으로 대체하지 않는다.

공통 값/어댑터의 source test PASS만으로 운영 유사도 검색 적용 완료라고 보고하지 않는다.
실제 운영 source capture → 동일 recipe query/candidate → increment binding → 검색 검증이
끝나기 전 상태는 `SOLUTION_EMBEDDING_ALIGNMENT_PENDING`이다. 현재 3건 Graph canary와
고정 원문 등록은 계속할 수 있지만 이 상태를 embedding-ready로 표시하지 않는다.

### 2026-10-29 첫 구현 검증

JSON Schema 2020-12/패키지 mirror와 frozen 공통 값, 기출 상세 보고서 및 창작 V1/V2의
순수 adapter를 추가했다. 새 정규화 회귀 18개를 포함해 기존 projection/공식 보고서/혼합
Graph 관련 42개 PASS, core Ruff·format·mypy PASS다. 같은 사실의 field/step 분할·공백·
한글 Unicode 조합 차이에 같은 encode text/hash, 수치·단위·부정·지수 변경에는 다른 hash를
확인했다. V1의 제출 shape hash는 원래 optional-field 존재 여부를 보존해 검증한다.
정규화된 model dump에 defaults를 넣어 과거 hash를 재해석하지 않는다.

**현재는 source-only 공통 projection이며, 기존 renderer의 동작이나 GPU/QUERY 인덱스는
바꾸지 않았다.** 후속 namespace·source binding 및 실제 질의/후보 연결은 미완료다.

### 필드별 근거 규칙 수정 후 회귀 확인 — 2026-10-29

창작 원문의 필드별 출처 정책을 정리한 `4b08abf8` 배포 뒤, 원래 canary 3건의 실제
role-result pointer와 공통 풀이 text SHA가 배포 전과 같음을 대조했다. 해당 변경은
출제의도·배점의 근거 영역과 미확정 독립 풀이의 검증/생성 안내이며, 이 문서의 projection과
기존 임베딩 renderer/recipe/space를 제자리 교체하지 않는다.

추가 회귀에서 OTHER 근거의 출제의도·배점·편집 관찰을 바꿔도 같은 공개 풀이의 text/hash와
CPU/CUDA encoding identity는 같고 report hash는 다름을 확인했다. 미확정 풀이의 editorial
관찰 유무도 풀이 내용이 같으면 수치 feature를 바꾸지 않는다. 단위·수치·부정·첨자·지수는
보존하며, 위조된 답안은 projection 진입 시 재검증으로 거부한다. 실제 벡터 추론/새 인덱싱을
실행한 검사가 아니며, 같은 내용과 같은 인코더 입력을 보장하는 계약 검사다.

새 실행에서 풀이 **내용 자체가 달라지는 것**은 양식 차이가 아니다. 이때 새 hash/벡터가
생기는 것은 정상이며 유사도 점수 불변을 주장하지 않는다. 기존 source/accepted-analysis
binding과 권한은 text hash가 같아도 합쳐지지 않는다. 관련 232개 회귀 PASS이며, 실제 운영
공통 query/candidate 연결 상태는 여전히 `SOLUTION_EMBEDDING_ALIGNMENT_PENDING`이다.

## 운영 연결 후속 구현 — 2026-10-29

이번 범위는 기존 증분 인코딩·등록·조회 application을 확장하는 것이며 새 검색 엔진이나
벡터 저장소를 만들지 않는다. 과거 인덱스·실패 기록·고정 QUERY 실행환경은 보존한다.

1. **책임/경계**: Catalog가 실제 operator 또는 이미 인가된 indexing service의 기존 Graph
   source-resolution 경계를 거쳐 공개 풀이와 근거를 캡처한다. 순수 계약/projection은 권한을
   부여하지 않는다. 새 worker가 DB/NAS를 읽거나 등록 역할을 맡지 않는다.
2. **정본**: 기출 accepted V10 successor와 가져온 창작의 등록 lineage/완료 role result가
   각각 정본이다. 공통 텍스트는 명시적 후속 recipe의 파생 입력이다. 창작을 V10 successor나
   등록 AI review로 가장하지 않고 evidence kind를 구분한다.
3. **식별**: 기존 Item/Item Revision, Graph/policy revision, base analysis, Artifact Revision과
   SHA를 유지한다. 공통 text SHA가 같아도 서로 다른 source/binding은 합치지 않는다.
4. **포인터**: 기출의 solution evidence pointer를 재사용하고 창작은 정확한 lineage member와
   role-result member를 핀한다. 조회·수명·원문·Job/Workflow 완료·schema/media/hash 및 실제
   Graph membership을 기존 owner가 확인한다. 누락/철회/변조는 명시적 오류다.
5. **접근 패턴**: 인가된 source 집합의 ordered traversal, revision별 indexed lookup, 같은
   encoding key의 dedup/reuse, namespace head의 compare-and-swap다. 문항 1개당 별도 전체
   Graph 탐색이나 SQL 목록 재조회는 하지 않는다.
6. **구조/index**: source/evidence는 typed discriminated union, 계산 입력은 기존
   EmbeddingTextInput/encoding identity, cache와 binding은 기존 registry를 사용한다.
   새로운 의미의 recipe/namespace를 명시하고 기존 index 의미를 제자리 변경하지 않는다.
7. **규모/비용**: bounded 페이지마다 O(source 수 + 실제 풀이 bytes), map/set membership은
   평균 O(1)이다. 기존 source-first keyset paging을 재사용하며 한 페이지·실제 숫자 추론
   batch의 1,024 한도는 유지한다. 새 public family의 전체 metadata head만 최대 16,384개,
   공개 풀이 캡처는 합계 64 MiB로 제한한다. 이전 index/plan family의 1,024 한도는 그대로다.
   페이지 경계의 중복과 최종 전체 membership 변경을 거부하고, 상한을 넘기면 명시적으로
   실패한다. 520+1053보다 큰 현재 범위를 수용하기 위한 bounded successor이지 무제한 보장이 아니다.
   파생 text가 기존 encoder의 262,144 UTF-8 byte 한도를 넘으면 unavailable로 표시하며 자르지 않는다.
8. **동시성**: 현재 read transaction의 identity/source/provenance를 재검증한다. 등록은 기존
   encoding unique key와 index head CAS를 재사용한다. 슬롯 순차 등록과 인코딩 claim은 서로의
   작업을 중복 실행하지 않는다. 실행 중 runtime pin을 바꾸지 않는다.
9. **의존성**: 계약 → 순수 공통 projection → Catalog source owner → 기존 registry/Orchestrator
   adapter 순서다. CLI/UI는 이 use case를 호출하며 직접 SQL/NAS로 검색하지 않는다.
10. **실패/재실행**: 동일 source/recipe/space는 동일 파생 입력이며 완료 encoding은 재사용한다.
    불완전한 풀이·warning은 정본에 보존하고 없는 본문을 다른 해설로 채우지 않는다. 실패한
    Job을 성공으로 바꾸지 않는다. 기존 namespace fallback은 명시적으로 구분한다.
11. **더 단순한 대안과 한계**: 기존 CONCRETE_FACETS renderer에 창작 JSON을 그대로 끼우면
    양식 편향과 source-family 위장이 생긴다. 인코더만 호출하는 임시 별도 인덱스는 기존
    권한·수명·중복·검색 계약을 우회한다. 따라서 기존 registry의 명시적 successor를 선택한다.

### 기존 실행 그래프 재사용

새 의미는 recipe2 / public entry1 / source-plan3 / index3 / service source policy1.4에
명시한다. 숫자 계산은 기존 IncrementalEmbeddingInput/Result1 및 shard1이고, 실행 DAG는
기존 `local-embedding-index@2.0.0`의 `encode_batch → complete` 그대로다. 이 정의에는
source-plan family나 report field가 들어 있지 않고 application 동작·한도·numeric result가
바뀌지 않으므로 불필요한 새 DAG 버전은 만들지 않는다. public request/ownership/completion은
별도 successor로 plan3와 실제 public binding을 핀하고, 과거 request2를 public로 재해석하지 않는다.
새 source policy 없이 구 service의 허용 범위를 늘리거나 기존 runtime configuration에
선택되지 않은 namespace를 끼워 넣지 않는다. 실제 활성화는 호환 설치본·정확한 정책 pin·
문서/질의 양쪽의 실행 증거가 필요하다.

### 구현·활성화 순서

1. source-family별 정확한 근거 pointer와 공통 encoder 입력의 schema/typed contract,
   동등한 text의 encoding identity·원문 불변·missing/oversize/위조 거부 회귀.
2. 기존 Catalog source owner에서 기출/창작 근거를 같은 인가 범위로 캡처. N+1 없는 bounded
   metadata capture를 먼저 확보하고 existing lineage/완료 결과 검증을 공유한다.
3. 기존 registry/plan/index/query의 명시적 successor namespace를 연결하고, disposable DB에서
   binding 동시성·멱등·CAS·중단 복구를 검증. predecessor bytes·encoding history는 보존.
4. 호환 release 후 고정된 표본으로 실제 document/query 인코딩·binding·검색과 재전송 검증.
   질의와 후보 양쪽이 같은 recipe를 쓰는 증거가 있어야 운영 완료로 표시한다.

### 병행 관측

등록은 기존 30분 읽기 전용 timer와 실제 Job/분석/Graph 전이로 관측한다. 임베딩은 INDEX와
QUERY를 분리하여 관측하며 PID/마지막 batch/고정 실행환경/실패를 구분한다. 착수 당시
등록 8/1053 이후 문항이 계속 진행 중이고 QUERY는 active지만, GPU INDEX는 2026-10-28
20:10 UTC의 `LOCAL_INDEXING_SERVICE_UNAVAILABLE`로 중단된 상태다. 이를 진행 중으로
표시하지 않는다. 기존 실패 pin의 무조건 재시작 대신 정확한 원인과 지원 recovery 경계를
확인하며, 새 source 공간의 activation과 기존 INDEX 복구를 서로 다른 증거로 남긴다.

### Native/registry 연결 검사 체크포인트

2026-10-29의 [실행 기록](../operations/PUBLIC_SOLUTION_EMBEDDING_CONNECTION_2026-10-29.md)에
schema/migration·실제 disposable transaction·동시성·중단 재개 결과와 운영 미완료 경계를
분리해 기록한다. source-plan3 → 숫자 input/result1 → index/binding3 → completion3 경로가
실제 임시 DB에서 끝나더라도 QUERY와 candidate의 동일 recipe 운영 검색이 확인되기 전에는
`SOLUTION_EMBEDDING_ALIGNMENT_PENDING`을 유지한다.

### QUERY 수치 결과와 source 의미의 분리

Public QUERY는 기존 query1/1.1을 새 recipe로 제자리 변경하지 않는다. query input/result2는
공개 풀이 recipe2와 QUERY/DOCUMENT space pair를 명시하며, 실제 수치 row/shard/encoding
identity와 encoder는 기존 것을 사용한다. 이 view에는 공개 풀이 한 개만 들어가며 원문의
format/ID/warning은 넣지 않는다. source와 정책은 별도 similarity/native owner가 검증한다.
새 result2를 result1이라고 표시하거나 기존 fixed QUERY1 DAG에 위장 연결하지 않는다.
후속 native definition/metadata·선택 정책을 정확하게 연결한 뒤 실제 검색을 활성화한다.

### 2026-10-30 자동 증분 활성화 목표

[새 운영 체크포인트](../operations/CREATIVE_INCREMENTAL_EMBEDDING_ACTIVATION_2026-10-30.md)에서
public INDEX의 batch1.3·owner6 연결, 기존 기출 view 보존, 같은 source의 CPU/CUDA pairing을
검증한다. 기존 numeric wire/자원 lease/등록 owner를 재사용한다. 공식 QUERY/검색 소비와
실제 창작 5건의 운영 검증이 남아 있으므로 alignment 상태는 아직 PENDING이다.
