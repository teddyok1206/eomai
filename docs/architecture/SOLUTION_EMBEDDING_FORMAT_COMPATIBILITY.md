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
