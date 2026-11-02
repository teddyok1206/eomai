# DB 유사도 검색: 목록·기록·완료 결과 재열람

2026-11-02 UTC. 사용자가 기존 결과 문항을 DB 조회에서 여는 데 성공했다고 확인했다.
그 경로와 원 검색·GPU INDEX를 유지하면서 후속 사용자 기능을 완성한다.
이 문서는 구현 계획이며, 아래 운영 검증이 끝나기 전에는 완료 상태를 뜻하지 않는다.

## 사용자 기능과 완료 조건

1. 검색 입력은 순서 있는 문항 목록이다. 최소1개, 최대32개이며 같은 등록 revision은 중복
   실행하지 않는다. 단일 문항도 같은 목록 경로를 쓴다.
2. 조회에서 문항들을 검색 목록에 담고 결과 개수(문항마다 상위1–64개, 기본5개)를 정한다.
   검색 시작 후 이 값과 문항 목록은 원 요청에 고정한다. 변경은 명시적인 새 검색이다.
3. 유사도 탭은 기준 문항 목록, 선택 기준 문항의 작은 미리보기, 해당 결과 목록을 보여준다.
   미리보기는 기존 인증된 Item/PDF projection을 재사용한다. 원문 파일 경로나 NAS 경로를
   browser 입력으로 받지 않는다. 결과 문항은 기존 조회 탭의 상세·배치 기능으로 연다.
4. 로그인한 실제 사용자의 최근 검색을 새로고침·재로그인 이후에도 다시 열 수 있다.
   다른 사용자의 기록·선택·결과는 노출하지 않는다. 관리 권한만으로 타인을 가장하지 않는다.
5. 완료한 검색의 ‘결과 확인’은 기존 결과 읽기다. 화면의 기존 목록을 지우거나 계산 중으로
   바꾸지 않는다. 새 QUERY prepare/native launch를 만들지 않으며 원 ranking/pin을 유지한다.
   ‘새 검색 시작’은 별개의 명시적 intent다. 같은 문항으로 새 임베딩 범위를 검색할 때도 새 key를
   사용하고 예전 결과를 덮지 않는다. 접수 timeout 재확인은 원 key를 유지한다.
6. 진행 중 조회는 원 요청/key를 관찰한다. timeout을 미접수로 해석하거나 새 key로 제출하지
   않는다. 일부 기준 문항이 완료돼도 다른 문항의 실패를 성공으로 바꾸지 않는다.
   기준 PDF 미리보기는 인증된 동일 Studio에서만 frame할 수 있다. 정확한 preview.pdf의200
   application/pdf 응답만 SAMEORIGIN으로 허용하고 로그인·관리·오류·일반 다운로드의 DENY는 유지한다.
7. GPU의 연속 처리 이점은 실제 단일2회와 동일2문항 묶음의 launch/model-load/실행/결과 읽기를
   분리 측정한다. 테스트 수나 READY만으로 실제 사용자 검색 성공·가속을 선언하지 않는다.
8. 최종 사용자 보고에는 실제 활성 projection을 확인해 문제 내용·공개 풀이보고서·메타데이터가
   각각 벡터 입력/검색 범위/결과 설명 중 어디에 쓰이는지 쉬운 말로 설명한다. 숨겨진 모델 사고
   과정을 저장·사용한다고 설명하지 않는다. 점수가 풀이 동일성의 백분율이나 과학적 정확성을
   보장하지 않는다는 점도 짧은 예로 구분한다.

## 경계·정본·revision

- Catalog는 원 DB 선택을 등록 Item과 고정 Graph/policy/public-solution으로 해석한다.
  기존 V1 선택 계약은 보존하고, V2 목록 계약을 JSON Schema 2020-12부터 추가한다.
- Orchestrator의 기존 public prepare4는 이미1–32개의 source revision을 지원한다.
  이를 한 번 호출하여 기존 유한 GPU batch owner에 맡긴다. 문항마다 별도 HTTP 검색32회를
  실행하는 구현, 새 queue/vector DB/model service는 만들지 않는다.
- 수치 결과·벡터·원문·풀이보고서의 정본은 기존 Artifact/Registry/Graph/Workflow다.
  검색 기록은 실제 operator, immutable 입력 목록, top_k, 원 key, 고정 query와 완료 selector만
  담는 작은 application 기록이다. 결과 문항 내용·벡터·PDF·전체 worker 결과를 DB에 복사하지 않는다.
- 논리 검색 ID, 검색 intent hash, 원 query request hash, 각 Workflow/revision/Artifact/hash를
  구분한다. 검색 완료 포인터는 한 번 연결되면 다른 계산의 결과로 바꾸지 않는다.
- 결과 재열람도 실제 현재 권한, 원 Graph/policy/source lifecycle, revision/hash를 기존 Catalog
  reader에서 확인한다. 캐시한 화면이나 history row를 권한·근거 검증의 대체물로 쓰지 않는다.

## 접근 구조·저장·동시성

- 주요 접근은 operator별 최근순 keyset pagination, owner+key 유일 조회, search ID 단건,
  ordered source 목록 및 revision-keyed 결과 metadata 병합이다. set으로 중복을 검사한다.
- 최근 기록은 기존 owner history가 원 DB 선택과 전체 목록을 복원할 수 있는지 먼저 확인한다.
  가능하면 그 metadata projection을 사용한다. 단기 TTL idempotency 응답 cache를 영속 기록으로
  전용하지 않는다. 불가능한 필드가 있으면 API-owned 작은 검색 기록만 추가하고 이유·필드·index를
  schema에 명시한다. 다른 서비스 테이블을 직접 갱신하지 않는다.
- 새 기록이 필요한 경우 owner+idempotency-key UNIQUE, owner+created_at+ID B-tree,
  operator FK와 bounded typed metadata/JSON 조건을 둔다. 이미지·결과 본문·binary 열은 없다.
  규모 N에 최근순 O(log N + page), 목록 처리 O(M), 결과 병합 O(MK), M≤32/K≤64를 목표로 한다.
- 접수 transaction은 작은 intent/pin 기록만 담당한다. 모델 실행·원문/Artifact I/O·긴 Catalog RPC
  동안 DB row lock을 잡지 않는다. 고정 pin/완료 selector 연결은 compare-and-swap이며 동시 replay는
  기존 owner claim/unique key와 함께 중복 계산을 방지한다.
- 기존 완료 selector가 있으면 GET result는 실행 API를 호출하지 않는다. 진행 중 확인에 필요한
  관찰은 existing owner의 원 key와 pin만 사용한다. 새 source capture/새 index 선택은 하지 않는다.

## 성능 점검

1. 현 GUI가 실제 batch 입력을 전달하는지 확인한다. 현재는 DB consumer가 단일 source만 보낸다.
2. GPU 모델 cold load, query encoding, ranking, Artifact publication, canonical result read,
   DB navigation metadata 시간을 분리한다. ‘계산 중’과 ‘기존 결과 확인 중’을 분리 표시한다.
3. 같은 scope의 여러 문항은 기존 GPU finite batch 경로로 전달해 모델 한 번 로드의 이점을 쓴다.
   CPU는 기존 resource routing 정책의 fallback이며 임의의 모델/공간 혼합을 허용하지 않는다.
4. 느린 completed read는 기존 담당 reader의 bounded source/index 검증에서 원인을 측정한다.
   권한/원문 pin 검사를 삭제하거나 browser cosine으로 대체하지 않는다. 측정 없는 persistent cache,
   global singleton 모델 서버나 새 background queue는 추가하지 않는다.
5. GPU 전체 재임베딩·진행 중 QUERY는 중단/재시작하지 않는다. 새 QUERY 소비자 배포는 실제 실행
   완료 경계에 맞춘다. INDEX·Web/API/QUERY release의 호환 pin을 명시한다.

## 구현 순서와 실제 검증

기록 저장 결정: native parent는 실행용 selection Artifact만 보존하며 원래 DB external 선택과
UI 목록 intent 전체를 API의 owner별 최근 기록으로 제공하지 않는다. API-owned
`item_db_similarity_searches` 한 테이블에 bounded input/query/child selector metadata만 저장한다.
접수는 POST, 진행 확인은 같은 search ID의 POST(check), 완료 결과는 ordinal별 GET으로 분리한다.
check의 HTTP 멱등 key는 그 search ID다. native 계산에는 저장된 원래 key만 사용한다.
GET 결과는 QUERY prepare/dispatch를 호출할 수 없다. 목록 전체의 무거운 completed read32회를
한 HTTP 응답에 모으지 않고 사용자가 고른 기준 문항 하나만 지연 조회한다.
owner/key UNIQUE와 owner/created_at/search_id index, operator FK를 둔다. 원 input은 불변이고
query 최초 연결/children 관측은 짧은 row-lock transaction으로 병합한다. 완료 child는 역행·교체하지
않는다. 긴 Catalog/RPC는 transaction 밖이다. 기존 native FAILED/Artifact는 갱신하지 않는다.
새 기록은 기능 활성화 이후 요청부터 저장하며 구 Workflow를 가짜 신규 검색으로 재등록하지 않는다.

- A: 기존 GUI 성공·원 계산 보존을 기록하고 completed 재조회 UI의 잘못된 초기화를 재현한다.
- B: 최소 설계와 JSON Schema→typed 목록/기록/완료 selector 계약, input1/32/중복/상위 개수 검증.
- C: Catalog 목록 capture→기존 public prepare4 batch 연결, 완료 read 분리와 최근 기록 application.
- D: 기준 문항 목록·top_k·최근 기록·선택 기준 문항 미리보기와 기존 결과→조회 이동을 연결한다.
- E: focused/schema/RBAC/멱등/동시 CAS·중단·replay disposable PostgreSQL, wheel/RECORD,
  independent installed simulation과 browser fixture 검증. 운영 DB를 pytest 대상으로 쓰지 않는다.
- F: 실제 HTTPS에서 단일1건/목록2건, 기록 다시 열기/재로그인 후 기록, 각 기준 미리보기,
  결과 문항→조회→배치, top_k, 완료 재조회를 검증한다. 같은 key의 Workflow/native 개수와 결과
  hash가 변하지 않는 것을 확인한다. 기존 FAILED 기록은 보존한다.
- G: GPU 단일 연속과 묶음 측정 결과·한계, actual source/release와 preserved INDEX를 기록하고
  Git/README의 변경된 사용자 기능 및 중요한 Slack milestone을 보고한다.

완료 판단은 F의 실제 사용자 기능과 G의 운영 증거다. 기존 벡터 삭제, 채팅 검색 확장, 창작
풀이보고서의 별도 장애 복구는 이 기능 완성을 대신하지 않으며 필요하면 별도 작업으로 둔다.

## 현재 점수에 들어가는 데이터 — 사용자 설명의 근거

운영 public QUERY 설정의 projection은 `public-solution-text/1.0`, 실제 활성 view는
`CONCRETE_FACETS`/`FORMAT_NEUTRAL_PUBLIC_SOLUTION`이다. 구현의
`project_public_solution_text` → `prepare_public_solution_encoding` → QUERY/DOCUMENT
벡터 비교를 확인한다. 레시피에 선언된 다른 필드 이름만 보고 사용하지 않는 입력까지 사용한다고
설명하지 않는다.

- **직접 비교하는 텍스트:** 정식 등록된 공개 풀이보고서의 단계별 풀이 설명이다. 기출 보고서는
  각 단계의 `rationale`와 `outcome`, 창작 V1/V2는 `reasoning_summary`를 원래 순서대로 잇는다.
  공백·줄바꿈과 유니코드 NFC를 정규화해 보고서 JSON 포장이나 필드 분리가 점수를 좌우하지 않게 한다.
- **문제 내용:** 발문·선지 전체를 별도 문자열로 덧붙이거나 원본 PDF/그림 픽셀을 직접 비교하는
  경로가 아니다. 풀이 설명에 나타나는 조건·과학 개념·관계·판단은 그 설명을 통해 간접 반영된다.
- **메타데이터와 Graph:** 문항 종류·등록 상태·출처·Graph 소속·권한·버전/해시는 대상 선택,
  준비 여부/정본 검증, 결과 열람에 사용한다. 제목·고유번호·단원명이 같다는 이유로 현재 점수에
  별도 가산점을 주거나 메타데이터 전체를 공개 풀이 벡터에 섞지 않는다.
- **수치 의미:** 해당 로컬 모델의 정규화된 벡터에 대한 cosine 순위다. 현재 저장된 후보 중
  가까운 것을 찾는 값이지 ‘풀이가 몇 퍼센트 같다’, 표절 확률 또는 정답/과학 정확성 판정이 아니다.
  같은 개념을 설명하는 문장이 비슷해도 실제 핵심 착상이 다를 수 있고, 반대 경우도 있다.
- **저장 범위:** 읽을 수 있도록 작성한 공개 풀이 설명을 쓰는 것이며 모델 내부의 숨겨진 사고
  과정을 저장하거나 읽는다고 주장하지 않는다. 데이터가 없는 문항을 임의 텍스트로 보충하지 않는다.

같은 공통 텍스트 규칙을 쓰더라도 서로 다른 작성자가 보고서 내용을 다르게 쓰면 벡터가 달라질
수 있다. 양식 차이를 줄이는 것과 의미까지 동일하게 보장하는 것은 구분한다. CPU/GPU 공간은
고정된 별도 numerical identity로 검증하며 서로 다른 공간의 벡터를 그대로 섞지 않는다.

## 소스 검증 체크포인트 — 2026-11-02

- 사용자 확인으로 종전 GUI의 실제 결과→문항 열기는 성공 기준선으로 닫았다.
- V2 목록 capture는 입력 순서를 보존하고 같은 Graph의 metadata/소속 조회를 묶는다.
 2개/32개에 metadata SQL2회와 membership1회, 원 Graph별 권한 검증을 사용한다.
  원래 source별 identity/lifecycle/hash 검사와 Catalog의 공식 public source capture는 유지한다.
- 새 API는 목록 접수/진행 확인/기록 조회/기준 문항별 GET 결과를 분리한다. GET 결과에는
  prepare/dispatch 호출 경로가 없다. 완료 상태는 완료 selector의 불변 연결이며 결과 본문 cache가 아니다.
- 제한된 runtime role로 기록 읽기/row lock 허용, 원 input/owner/hash/key UPDATE 거부를 임시 DB에서
  확인했다. UNIQUE 동시4접수, owner 분리, keyset cursor, 완료 뒤 늦은 PENDING 병합과 migration
  68↔69 왕복을 확인했다. 실제 운영 DB에는 이 시점의 schema69를 적용하지 않았다.
- 실제 Chromium의 원 repository HTML/CSS/controller와 합성 API로 목록/미리보기 영역/기록/
  결과→조회/배치, 늦은 A/B 응답과 viewport를 검사했다. 이는 운영 인증/GPU 검증의 대체물이 아니다.
- GPU INDEX process/config와 원 계산은 유지했다. 관측된 GPU bindings는348/1003이며
  API/Web/QUERY 신규 release, 실제2문항 GPU batch 및 단일/연속 대비 측정은 다음 단계다.
