# 생성 문항 검토 근거의 증분 RAG 연결 — 운영 검증 완료

확인 시각: 2026-10-20 04:37 UTC. 이번 생성 문항 source 연결 목표의 종료 증거다.
전체 EOM 제품·모든 검색 소비자의 신규 호환성·교육 품질을 승인하는 문서는 아니다.

## 결론과 실제 사용자 검증

승인 생성 문항의 기존 독립 REVIEW 결론 → 실제 accepted Graph → 기존 INDEX의 자동
증분·등록 → 실제 사용자 API의 대상 자체 VECTOR 검색·읽기까지 연결했다.
같은 실제 guiadmin 세션에서 중간 승인·진단 pause 없이 아래 검증을 마쳤다.

| 확인 | 실제 결과 |
|---|---|
| 원 mixed 준비와 같은-key 재전송 | 두 번200/READY, reply 동일 |
| mixed context |200 두 번, 전체 typed 값 동일, 후보8개 |
| 대상 자체 VECTOR |CONTENT_ONLY rank1, cosine 표시0.849387 |
| 근거 구분 |REGISTERED_ITEM_REVIEW_SOLUTION; 기출 V10으로 위장하지 않음 |
| 원 V1 history 준비 재전송 | 저장된 원 READY reply와 정확히 동일 |
| 원 V1 context |200 두 번, 전체 typed 값 동일, 후보8개 |
| 종료 |FINITE_HTTP_CANARY_COMPLETED; 이 세션의 failure event0 |
| 최종 검증의 새 QUERY/문항/Chat/model |0; 원 완료 요청의 재전송·읽기만 수행 |

password는 로그인 직후 폐기하고 token은 같은 process memory에만 뒀다. 다른 사용자의
세션 복사·권한 사칭·TTL 연장·저장 credential 자동 로그인은 없다. 끝난 client process는
종료됐고 원 finally에서 메모리 세션을 닫았다. 정상 로그인/감사 DB 기록이 없었다는 뜻은 아니다.

## 원 기획과의 대조

원 설계: [검토 근거](../architecture/REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_DESIGN.md),
[운영 통합](../architecture/REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_DESIGN.md),
[상위 설계](../architecture/SYSTEM_RAG_SIMILARITY_AND_INCREMENTAL_EMBEDDING_DESIGN.md).

| 원 요구 | 구현·실제 증거 |
|---|---|
| 기존 검토 풀이 재사용 | 최종 REVIEW/등록/receipt closure 해석; 가짜 V10·재풀이 없음 |
| 공식 Graph 결합 | 별도 승인된 accepted V2 분석1건과 기존 Graph owner의 실제 출판 |
| 자동 증분 | INDEX21 reconciliation이 missing demand42개를 선택·완료; 대상1개 포함 |
| 기존 벡터 보존 | CONTENT baseline479개 encoding·shard row 변경/누락0; owned 신규42개와 baseline 교집합0 |
| 혼합 계약·영속 무결성 | binding2/index2/namespace2, 실제0058 FK/XOR CHECK/partial UNIQUE·동시성/replay 회귀 |
| 실제 검색·읽기·역사 호환성 | 이번 HTTP VECTOR/read_twice/같은-key 및 원 V1 exact reply/read PASS |
| 권한 철회·복구 | INDEX21 실제 DISABLED45 기동 거부/native0, 같은 revision ACTIVE46 복구 |
| 역할 경계 | 실제 제한 PG 역할 회귀; worker 직접 DB/NAS 쓰기·외부 LLM API 없음 |

증분은 모델 가중치를 계속 학습한다는 뜻이 아니다. 승인·출판되어 eligibility를 충족한
자료를 기존 runner가 찾아, 정확한 text/space/partition/recipe의 동일 encoding을 재사용하고
필요한 새 encoding만 만든다. 승인 Item이라는 이유로 accepted Graph 분석을 건너뛰거나
구버전 REVIEW까지 자동 지원하지 않는다. 생성 REVIEW는 원 정답·선지/진술·검증 결론의
별도 근거 계열이며 기출의 accepted V10 풀이와 혼동하지 않는다.

registry의02:17 UTC 관측은 mixed CONTENT521/CONCRETE457/METADATA521,
legacy520/457/520이다. view별 분모·current head·이번 QUERY의 pinned index를 구분한다.
모든 view의 기출520개 coverage나 current head로의 묵시적 변경을 주장하지 않는다.
기출520개 분석·기존 벡터·원 실패/성공 이력은 보존한다. 상세 baseline/완료 영수증은
[중간 운영 기록](REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_2026-10-19.md)에 있다.
최종 읽기와 INDEX·QUERY 연결의 Codex 풀이 호출은0이지만 전체 목표의 별도 승인 Graph
V2 분석1건까지 모델 호출0으로 확대하지 않는다.

## 정확한 identity와 검증 hash

- anchor: `item_149b7ef9184141d597ce15ead72fd149` /
  `itemrev_72ab539bd96c4ba6993bc1f5dc678989`의 genuine V10 근거.
- 대상: `item_07b817a17dce4f4cb13ee60a02014a00` /
  `itemrev_b6e626a764644e37b428cd914f920bb6`.
  profile semantic SHA:
  `sha256:4bb3a05fbb97d87bbc283b47c83792e4d0d464e7bc05656d0b7161275f304a19`.
- mixed 원 key: `registered-review-mixed-query-20261019-b6e626a7-01`,
  Workflow `workflow_0941e1741dd34d3382265fc28a590da7`,
  준비 request SHA `sha256:21b636d21f088892a166655380e6fc40f40319f18c7320d1d2173acd9470b3d5`.
  두 READ의 context semantic SHA:
  `sha256:79d0b4ec4b9206a48d063a415e3c2ff26c91f2ea6b02044b1d456f731d7fe034`.
- 원 V1 key: `goal-http-reference-query-20261015-01`,
  Workflow `workflow_a0833f96b5154c3da4c5e5961eb9a209`,
  준비 request SHA `sha256:258c0567f807fb1e4c43b4107809acb7dec5a37add2c7c06082c2b26e3e0ae3f`.
  두 READ의 context semantic SHA:
  `sha256:8594b59e8845b352001e18e8f73e982245e8c8122ee181d8e7472e36e181fb1d`.

context SHA는 HTTP body raw SHA나 Artifact Revision ID가 아니다. 원 요청/Workflow,
semantic context와 실제 NAS member의 raw hash를 별도로 유지한다. 대상 DOCUMENT
encoding은 `sha256:3efca006c82e251445400025ee33167c72889781b39e2013ee3c62a31c793a1e`,
row14다. canonical shard는 `artifact_b8e75f5f75ce4278b2da37125477782d` /
`rev_d08f45c47f6045d489cba263b14d1191`, `shard.json`,
`eom://schemas/knowledge/embedding-vector-shard/1.0`, raw SHA
`sha256:26956f04ad77e957c5769a186b6a5d9105f87f09d242dc46d58820f39220c506`다.
문항·보고서·binary vector는 Git으로 복제하지 않는다.

sanitized event10개의 로컬 진단 기록:
`/tmp/eom-completed-query-diagnostic.k8hMWDWl/actual-http-read-acceptance-202610200437.jsonl`,
raw SHA `ef4744ccc1a0935c310794f1b1d5105a2bf3a888a59226aee4bcd38e44cab778`.
password/token·문항/worker 본문이 없고 completion1/failure0이다.

## 실제 release set·응답시간·복구

04:37 UTC API LIVE/READY, API·QUERY·Catalog·INDEX·Chat owner/worker의6개 service가
active/Result=success/NRestarts0이다. 실제 API application은60af9e5d, 공유 platform/
API contracts와 Chat은66f387bf, QUERY/Catalog는 cold SDK2eef9b20, INDEX21은e013d350,
DB는0058이다. 이를 모두 현재 Git HEAD나 동일 commit으로 표시하지 않는다.

App-only receipt·복구 wheel·provider before/after는
`/var/lib/eom-api-deadline-60af9e5d-v2/`에 있다. component receipt raw SHA는
`1a360c3b67b3ca094ff40ed03a72d060c0c666475518b51c5a9951db3d8e606c`다.
PID/invocation, 실패·normal stop·권한/metadata 보정과 복구 상세는
[제한시간·배포 기록](REFERENCE_QUERY_PREPARATION_TIMEOUT_2026-10-20.md)에 보존했다.
과거 실패를 성공으로 바꾸거나 canonical 데이터·기존 deployment record를 고치지 않았다.
다음 공용 배포는 이 App-only 선택과 Catalog PYTHONPATH override를 inventory하고,
수정이 포함된 호환 release로 정렬한 뒤 override를 제거해야 한다.

속도 향상은 주장하지 않는다. 실제 mixed compose는58.287/58.742초, V1은28.352/
28.686초였다. 단계 계측이지 RPC 전체시간이나 일반 SLO 표본이 아니다. READ adapter만
90초의 유한 monotonic budget, 검증 client의 READ outer budget만120초다. 일반 API·준비·
인증 timeout, 전체600초/freshness900초, 현재 권한·source·schema·hash·수치·late fence는
유지한다. 추가 성능 개선은 실측에 근거한 별도 후속 작업이다.

## ‘핵심 착상 근거 부족’의 뜻

‘풀이가 없다’, ‘임베딩이 실패했다’, ‘두 문제가 안 비슷하다’는 판정이 아니다.
저장된 보고서·검토 기록만으로 **두 문항의 결정적 착상이 같다는 강한 주장까지 뒷받침할
명시적 근거가 충분하지 않다**는 뜻이다.

독립 정답, 선지/진술의 참·거짓, 검증 결론과 원문 위치는 보존해 검색에 활용한다. 그러나
그 결론만으로 어떤 관찰에서 어떤 관계를 세웠고, 어느 추론이 필수였으며, 다른 문항의
풀이 단계와 어떻게 대응하는지까지 자동 증명되는 것은 아니다. registered REVIEW에는
전체 풀이 DAG/decisive-inference 근거가 없다는 limitation을 명시한다. 없는 중간 단계나
원문 위치를 만들어 확신도를 높이지 않는다.

유사도와 Graph 근거는 검토할 후보를 찾는 보조 수단이다. 공통 내용/단어/메타데이터가
비슷한 것과 핵심 풀이가 같은 것은 별개다. 이번1위·0.849387도 ‘같은 풀이 확률’이나
‘84.9% 동일’이 아니다. 반올림 표시값을 순위 계산에 대입하지 않는다. 더 강한 판단은
실제 명시적 근거가 확보된 successor의 별도 요구로 다루며 새 풀이/사람 평가를 이번 종료
gate에 추가하지 않는다.

## 완료 범위 밖

- CPU/CUDA 여섯 비교는 NOT_STARTED; CPU 기본값 유지, GPU 우수성/전환 주장 없음.
- fresh V1-on-new-Graph·모든 private Chat의 신규 실제 호환성은 NOT_RUN/이번 종료 범위 밖.
- 실제 service 권한 철회/복구와 개별 source ACL revoke를 구분한다. 후자는 실행하지 않았다.
- 교육적 유사성·문항/시각 품질의 사람 평가·일반 정확도 확정은 하지 않았다.
- 새 문항/25문항/HWPX·반복 풀이를 이 검증을 위해 생성하지 않았다.

소스·격리 DB·배포·실제 HTTP 증거를 합쳐 이번 검토 근거 연결 목표를 완료한다.
