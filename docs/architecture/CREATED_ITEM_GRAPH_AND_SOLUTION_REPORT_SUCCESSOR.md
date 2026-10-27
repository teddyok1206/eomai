# 창작 문항 풀이보고서·Graph 게시 후속 계약

상태: 설계 결정 및 구현 게이트. 2026-10-27 UTC. 이 문서는 원본 XLSX/ZIP만으로 Item 승인이나 Graph 게시가 완료됐다는 뜻이 아니다.

## 이번 목표의 사용자 지정 종료선

2026-10-27 사용자 추가 지시: 슬롯 계정의 주간 사용 한도가 소진됐을 수 있으므로 **실제 Codex 풀이보고서 작성 직전까지 확실하게 준비·검증되면 이번 goal 달성으로 간주**한다. 실제 Codex 호출·풀이보고서 생성은 수행하지 않는다. 기존 source-only 등록, 메타데이터/파일 보존, DB GUI, 조립 초안, 권한·불변 이력 조건은 유지한다.

준비 완료는 고정 source/page Artifact, 소유자에 묶인 저장 작업, 실행 설정/슬롯 입력 연결, 실패·재전송·복구의 무과금 검증과 실제 환경의 실행 전 점검으로 입증한다. 미연결 코드를 숨긴 채 ‘실행만 하면 된다’고 표현하지 않는다. 실제 모델 결과·정본 승격·Graph 게시와 원본 HWP 편집 합본의 미지원 상태는 각각 남은 범위로 명시하고 성공한 것으로 재해석하지 않는다.

## 경계와 현재 사실

`PAST_EXAM`은 기출 occurrence와 실제 PDF 페이지 위치를 가진 승인 문항이다. `APPROVED_ITEM`은 occurrence 없이 승인된 정본 Item Revision이다. 기존 `knowledge-analysis-request/10.0`은 전자의 V9 시각 분석·문제/해설 페이지 anchor에 고정되어 있다. 기존 ordinary-item Graph publisher는 EOM authoring/review/registration Workflow의 역할 결과·receipt를 요구한다. 업로드한 N제 원본은 어느 쪽 이력도 자동으로 갖지 않는다. 따라서 V10 또는 ordinary publisher의 검사를 느슨하게 하는 일은 금지한다.

사용자 명칭 `창작`은 기출변형·자유출제의 검증된 출처 분류다. Graph source class는 당분간 현행 `APPROVED_ITEM`을 유지하고, 창작 여부는 검증된 Item Origin profile과 외부 U source revision 연결로 판별한다. 이 구분을 질의·화면·수출 결과에서 유지한다. source-only 원본은 Graph 근거 검색에 들어가지 않는다.

2026-10-27 읽기 전용 입력 집계: Y열 분류는 기출변형 1,056행·자유출제 241행이다. 최종본 후보는 832행·235행, 정확한 원본 파일 연결 후보는 820행·233행이다. 반려·초안·14개 연결 예외는 자동 worker claim 대상이 아니다. W열의 0/1/빈칸은 분류를 신뢰할 수 없으므로 Y열의 원값 및 검증된 source revision을 사용한다. 이 숫자는 운영 accepted Item/Graph 게시 건수가 아니다.

이 1,053개 연결 후보를 엑셀 행 순서의 `(U, 행 번호, 최종 교정 단계, ZIP 멤버 SHA-256)` 목록으로 직렬화한 읽기 전용 target-set hash는 `sha256:3705a73413fe8a442f00360283592b1ca0e8024029a9dce56700a708a4f36155`다. 운영 Intake 후에는 원본 Artifact pointer와 mapping revision을 포함한 새 target-set identity를 발행해야 하며, 이 사전 조사 해시를 승인 receipt나 worker 권한으로 사용하지 않는다.

## 최초 기출 Graph 설계와의 호환성 대조

이 대조는 최초 [GraphRAG 설계](EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md), 구현된 [Snapshot 영속 계약](EDUCATION_GRAPH_SNAPSHOT_PERSISTENCE_V1.md), [기출 풀이보고서 ADR](../adr/0073-additive-past-exam-solution-reports.md), 현행 Graph publisher source를 기준으로 한다. **설계상 호환 가능**과 **현재 운영에서 이 아카이브가 게시 가능**은 다른 판정이다. 후자는 아직 아니다.

| 기존 기출 Graph 불변식 | 창작 아카이브 적용 | 현재 확인한 간극·차단 게이트 |
|---|---|---|
| Graph는 Item/Document 원본을 복제하지 않는 파생 snapshot이고 accepted 분석·출처·해시만 pin한다 | 동일한 Catalog Graph snapshot/adjacency/publisher를 재사용한다 | XLSX source-only 행을 Graph node로 바로 넣지 않는다. 각 행의 정본 Item Revision과 accepted 분석이 먼저 필요하다 |
| 노드·edge마다 검증 가능한 원본 anchor가 있어야 한다 | 외부 source revision의 정확한 Office Artifact와 승인 Item 요소를 함께 가리키는 anchor를 만든다 | HWP/HWPX→PDF 화면 좌표는 변환기에 종속된 파생 위치다. 원본 source/member/hash와 변환 identity를 함께 고정하지 않은 PDF 좌표 단독 증거는 거부한다 |
| `PAST_EXAM`은 실제 시험 occurrence·문제/해설 페이지를 요구한다 | 창작 출처는 기존 `APPROVED_ITEM` source class와 검증된 origin profile을 사용한다 | 원본이 기출변형이어도 그 자체는 기출 occurrence가 아니다. 가짜 시험·페이지 anchor나 V9/V10 기출 요청을 만들지 않는다 |
| 분석 worker는 제안만 하고 Orchestrator/Catalog가 승인·Artifact commit·Graph CAS를 소유한다 | 기존 6개 슬롯 중 별도 1개를 bounded claim/lease로 사용하고 결과는 같은 검증 경계를 거친다 | tmux pane은 모니터링 화면일 뿐 작업 정본이 아니다. 슬롯을 열기 전 source→Item 추출 계약, 권한, queue/claim, 실패 복구를 검증해야 한다 |
| 풀이보고서는 accepted base 분석의 additive successor이고 내부 비공개 사고 과정이 아니다 | 단계별 공개 가능한 풀이, 정답·해설 비교, 개념↔출제요소 연결을 별도 Artifact에 기록한다 | 기출 V10은 V9/페이지 anchor에 묶여 있으므로 창작용 successor 계약이 필요하다. 보고서 누락을 Graph 게시 실패와 혼동하지 않는다 |
| publication은 기대 Graph head와 exact source/analysis를 확인한 원자적 CAS이며 과거 snapshot은 불변이다 | 기존 `AutomaticItemGraphPublicationService`의 final validation/CAS를 재사용한다 | 현행 ordinary/25문항 adapter는 실제 authoring/review/registration Workflow receipt 또는 25개 slot을 요구한다. 아카이브에 없는 receipt를 합성하지 않고 출처 검증 adapter만 추가한다 |

따라서 **ontology·Graph 저장 엔진·기출 layer를 바꿀 필요는 없다.** 필요한 것은 원본 Office 위치를 신뢰 가능한 Item 요소 anchor로 해석하는 구조화 추출/검수 계약, 창작 출처 Item 승격 근거, additive 풀이보고서 successor, 그리고 기존 Graph owner를 호출하는 창작 전용 publication adapter다. 이 네 경계 중 하나라도 빠지면 코덱스가 내용을 풀었더라도 `GRAPH_PUBLISHED` 또는 `SOLUTION_REPORT_ACCEPTED`로 표시하지 않는다.

운영 화면 검증에 사용한 고유번호 `10310`의 고정 3교 PDF는 한 페이지 안에 **왼쪽 창작 문항, 오른쪽 해설·편집 메타데이터, 오른쪽 아래 원본 기출 첨부**가 함께 배치돼 있다. 2026-10-27 UTC에 검증된 파생 PDF SHA-256은 `sha256:d1e2915b7981f8dd4c9df433aad442cb983706c638270532e2cd31ecbadd17fb`다. 따라서 페이지 전체 OCR을 곧바로 한 Item 본문으로 채택하면 해설이나 기출 원본이 문항에 섞인다. 추출 후속 계약은 `TARGET_ITEM / EDITORIAL_SOLUTION / REFERENCE_ORIGINAL / OTHER` 역할별 페이지 영역과 그 판정 근거를 구조화 제안으로 받아야 한다. 영역은 변환 PDF의 파생 좌표이므로 원본 HWP Artifact Revision·변환 manifest·PDF hash를 함께 고정하고, 원본 기출 첨부를 이번 창작 Item의 정본이나 `PAST_EXAM` occurrence로 승격하지 않는다. 이 실물 사례를 첫 슬롯 표본으로 사용하되 영역 제안의 자동 수락은 금지한다.

실행 순서는 `source-only → 정확한 원본/파생 위치 pin → Codex 구조화 추출 제안 → 내용·정답·원본 대조 및 Item 승인 → accepted base 분석 → Graph 게시 → additive 풀이보고서 수락 → 검색/역추적`이다. 실제 코덱스 슬롯은 추출·풀이 단계에 사용하되 worker가 Registry/Graph/NAS에 직접 쓰지 않는다. 대량 작업은 대표 표본 1건의 원본↔Item↔풀이↔Graph 역추적과 중단/재전송 검증을 통과한 뒤에만 bounded chunk로 넓힌다.

2026-10-27의 첫 구현 계약은 `external-item-learning-source/1.0`과 `external-item-learning-result/1.0`이다. 입력은 U의 source revision·원본 observation hash·정확한 Office→PDF 파생 manifest를 고정한다. 출력은 페이지 안의 `TARGET_ITEM`, `EDITORIAL_SOLUTION`, `REFERENCE_ORIGINAL`, `OTHER` 영역, 각 정본 요소의 영역 출처, 공개 가능한 풀이 요약과 답안 대조를 담은 **제안**이다. PDF 좌표는 0–10000 정규화 사각형이므로 파생 PDF hash와 변환 manifest 없이 단독 근거로 사용하지 않는다. 원본 기출 첨부는 새 창작 문항 또는 해설의 출처로 매핑할 수 없고, 읽을 수 없는 영역이나 답안 불일치는 `NEEDS_DECISION`으로 격리한다. 해설 텍스트만은 편집 해설 영역에서 제안할 수 있으나, 실제 승인 전에는 원본 문제와 답안의 사람/검증 경계를 통과해야 한다. 이 결과 스키마의 검증 PASS는 Item Registry 등록·Graph 게시 허가가 아니다.

제안의 `content_region_map`은 형식상 그럴듯한 경로만 허용하지 않는다. 실제 `AssessmentItemContent` 안에서 경로를 해석하고 제목, 모든 본문 블록, 상호작용, 정답, 해설, 점수의 필수 출처 매핑을 확인한다. 문항 본문·선지는 `TARGET_ITEM`에만, 해설은 `TARGET_ITEM` 또는 `EDITORIAL_SOLUTION`에만 연결할 수 있다. `REFERENCE_ORIGINAL`은 어느 정본 요소나 풀이 단계의 근거로도 허용하지 않는다. 작업자가 일부 근거를 못 읽었으면 없는 내용으로 보충하지 않고 `NEEDS_DECISION`을 반환한다.

Codex 슬롯 입력에는 PDF 경로만 주지 않는다. `external-item-learning-page-set/1.0`은 정확한 preview Artifact Revision·PDF SHA, 고정된 `pdfinfo`/`pdftoppm` 바이너리 해시, 2400px 렌더 프로필, 순서가 연속된 각 페이지 PNG의 멤버/해시/크기를 기록한다. Orchestrator는 PDF를 허가·해시 검증한 뒤 기존 `eom-image`의 시스템 격리 경계에서 입력을 `pdfinfo` 1회와 전체 페이지 `pdftoppm` 1회에만 전달한다. 단일 Poppler 출력의 PNG 경계·CRC·페이지 수·크기를 확인해 로컬에 단계별로 놓고, 검증된 PNG+manifest만 Artifact로 commit한다. worker에게는 읽기 전용 로컬 staging 사본만 전달한다. PDF 자체는 preview Artifact를 계속 참조하고 페이지 세트에 복제하지 않는다. 이 파생 페이지 세트가 준비되지 않았거나 PDF identity와 다르면 worker claim 전 중단한다. 페이지 세트는 그래프 출처나 정본 Item이 아니라 시각 분석 입력이다. 운영 계정에서 PDF를 직접 해석하거나 페이지마다 원본 PDF를 반복 전달하는 경로는 사용하지 않는다.

현재 구현은 페이지 세트 스키마·검증 모델, Catalog의 current source/preview 재인가 및 bounded PDF 일회 읽기, Orchestrator의 **격리 렌더 어댑터**, 기존 resumable `ControlFileSetPublisher`를 호출하는 전용 게시 어댑터, exact Artifact Revision의 file-set closure를 다시 검사해 PNG만 worker workspace에 놓는 materializer까지다. Catalog 읽기와 Orchestrator 게시 사이의 저장된 작업·권한·cross-service 전송, Workflow/slot admission은 아직 남아 있으므로 이 단계의 소스 테스트만으로 운영 창작 분석이 가능하다고 표시하지 않는다. 특히 workflow-runner의 Catalog private socket 권한은 현재 유사도 조회 한 operation으로 제한되어 있다. 창작 PDF를 얻기 위해 이 제한을 암묵적으로 넓히거나 Catalog/NAS를 우회하지 않는다. 개발 셸 계정에는 새 systemd transient unit 생성 권한이 없어 격리 runner의 실제 운영 실행 검증도 별도 운영 경계에서 필요하다.

후속 Catalog source-read 입구는 `ActorContext`의 복사된 권한 목록을 신뢰하지 않고, 실제 API operator·session의 활성/미폐기/미만료 상태와 인증 시각을 DB에서 다시 확인한다. 현재 역할의 `CONTENT_INTAKE_READ`, `WORKFLOW_START`, `KNOWLEDGE_ANALYSIS_CREATE`가 모두 있어야 원본/파생 PDF를 열 수 있다. 소스 테스트는 정상·권한 변경·세션 폐기/만료·계정 비활성/비밀번호 변경·세션-계정 불일치에서 파일이 열리지 않는 것을 확인했다. **이 검사는 대화형 제출 입구에만 해당한다.** 저장된 worker claim 시점에는 만료된 브라우저 세션을 흉내 내지 않고, 저장된 operator identity·현재 권한과 pin된 source/Artifact를 별도 application 경계에서 재인가해야 한다. 아래의 저장 application 후보와 별개로 운영 제출·claim 연결은 아직 없으므로 슬롯 활성화는 계속 차단한다.

후속 구현으로 Catalog에 저장된 작업 소유자 ID를 받는 `reauthorize_external_creative_learning_claim_source`와 `read_external_creative_learning_claim_input` 읽기 경계가 추가됐다. 이들은 브라우저 세션을 사용하지 않고 현재 계정 활성 상태·삭제/비밀번호 변경 여부·세 권한 및 정확한 source/preview pointer를 다시 확인한다. PDF가 필요한 때에는 기대 크기·SHA를 확인하며 bounded materialization 후 stream을 닫는다. 소유자 ID는 향후 영속 작업에서만 가져와야 하며 worker 요청값을 신뢰하면 안 된다. 계정 변경·source stale·PDF hash 회귀를 포함한 소스 테스트는 통과했지만, 이 함수 자체는 작업 생성·원자적 claim·페이지 staged materialization·슬롯 실행을 구현하거나 허용하지 않는다.

### 영속 Workflow 제출 경계의 구현 결정

새 queue/table을 만들지 않고 기존 `workflow_instances`/고유 idempotency key/active request hash와 append-only 초기 event를 재사용한다. 입력은 기존 `WorkflowRequest(EXTERNAL_ITEM_LEARNING_REQUEST)`와 불변 `external-item-learning-work-input/1.0`이다. 이 문서는 메시지의 기존 schema나 기출 계약을 변경하지 않는다.

- Catalog가 원본/권한의 정본이고 Workflow repository는 작업 identity·멱등 저장의 owner다. Workflow application은 작은 source-authorizer port를 호출하며 Catalog adapter가 현재 operator와 exact source/preview를 재인가한다. 도메인/계약은 SQL·NAS를 import하지 않는다.
- 정확한 `external-item-learning@1.0.0`, 단일 support 추출→종료 DAG, role `1.33.0`, 입력·정의 hash와 실제 operator를 검증한 뒤에만 저장한다. native/비교 작업의 runtime context나 임의 context를 혼합하지 않는다. 재전송에서도 source를 재인가하고, 저장 후 같은 root에서 한 번 더 확인해 중간 권한/source 변경을 거부한다.
- 빈번한 접근은 idempotency key/active request hash의 indexed lookup이다. 창작 전용 fingerprint에 실제 owner를 포함해 다른 계정의 active 작업이 재사용되지 않게 하며, 기존 작업 계열의 hash bytes는 바꾸지 않는다. 한 작업의 O(k) 입력 검증은 bounded page manifest 크기에 비례하고 binary는 DB에 넣지 않는다.
- 경쟁 생성은 기존 unique 제약과 savepoint/replay를 사용한다. 실패한 늦은 재인가에서는 caller root를 rollback하며 새 identity로 우회하지 않는다. 작업 stage는 AUTHORING이 아니라 KNOWLEDGE_ANALYSIS다.
- 더 단순한 generic 무검증 저장은 owner가 다른 작업 재사용과 임의 원본 입력을 허용할 수 있어 배제한다. 이 제출 경계가 구현돼도 실제 command enqueue·claim·Orchestrator source/page 재검증 및 수락을 연결하기 전까지 슬롯은 비활성이다.

2026-10-27 18:31 UTC 소스 검증: 위 제출 gate와 Catalog source-authorizer adapter를 구현했다. 새 요청 ID만 바꿔도 같은 고정 source/page 작업의 fingerprint는 달라지지 않으며, 다른 요청 ID의 replay는 원래 요청을 덮어쓰지 않고 conflict 처리한다. 같은 root의 늦은 계정 확인에는 ORM identity-map의 옛 값을 쓰지 않도록 `populate_existing`을 적용했다. 새 DB migration·dependency는 없다.

- Workflow 생성 경계 관련 unit **274 PASS**, 최종 Catalog/창작 admission focused **38 PASS**, 수정 source 3개 mypy 및 Ruff PASS.
- 보호된 disposable PostgreSQL에서 기존 외부 문항/조립 검사와 새 저장 검사를 합쳐 **13 PASS**. 같은 key와 다른 key의 동시 동일 입력, owner별 분리, exact replay, 초기 event 1개, 늦은 source 거부 후 rollback을 검증했다. 이 테스트의 source-authorizer는 명시적인 합성 fixture이므로 실제 운영 원본 권한이나 슬롯 실행의 PASS를 뜻하지 않는다. 임시 DB `20261027182549_ad3868a6`은 공식 cleanup으로 제거했다.
- 넓은 unit 실행에서 사전부터 실패하던 private QUERY 음성 fixture 2건은 수정 전 HEAD의 별도 source snapshot에서도 재현했다. 해당 fixture가 실제로 테스트하려는 ‘definition 미허용’ 조건을 명시하도록만 수정했고 private QUERY production 동작은 바꾸지 않았다.
- 이 변경은 아직 platform/API 운영 배포·HTTP 제출 입구·command enqueue·worker claim·Graph 게시를 연결하지 않은 **소스 후보**다. 이미 확인된 DB GUI 운영 릴리스와 혼동하지 않는다.

HTTP의 다음 입력 계약 `external-item-learning-start/1.0`은 `import_id`, U, exact `source_revision_id`, 행의 `observation_sha256`, 선택 2/3교만 받는다. 운영자 ID·권한·Artifact 경로나 worker 입력은 받지 않는다. Catalog는 현재 U lookup과 **이 네 가지 고정 입력**을 비교한 후에만 파생 PDF를 연다. 화면을 열어둔 사이 source revision·관찰·교정 선택이 바뀌면 `EXTERNAL_CREATIVE_SOURCE_STALE`로 거부하며 latest로 자동 대체하지 않는다. JSON Schema 2020-12와 Pydantic 및 현재성/권한 회귀 테스트가 준비됐다. 아직 HTTP route·Catalog 전송·영속 Workflow/claim·page Artifact 게시를 연결하지 않았으므로 이 요청 계약을 운영 기능으로 표시하지 않는다.

슬롯 요청은 `external-item-learning-work-input/1.0`이라는 작은 불변 값으로 고정한다. 원본 `learning-source`와 `learning-page-set`을 반복 바이너리 없이 담고, 페이지 Artifact의 논리 ID·Revision, primary manifest member의 schema/media/SHA와 file-set manifest SHA를 별도로 pin한다. 생성자 검증은 source↔page-set↔Artifact primary SHA를 일치시킨다. 슬롯 시작과 결과 수락 시에는 Catalog의 **현재** 원본 선택·권한을 다시 확인하고, Orchestrator가 승인 Artifact의 전체 member closure·media·hash를 검증한 뒤 로컬 읽기 전용 staging으로 놓는다. `(source revision, edition, 입력 계약, 페이지 Artifact Revision)`이 작업의 멱등 키 재료이며, 재시도는 동일 포인터만 재사용한다. 초기 약 1천 건, 확장 수십만 건에서 조회는 인덱스 키 기반 O(log n), 한 요청 materialization은 최대 32페이지·256MiB에 선형이다. 원본 PDF를 worker에게 무권한 NAS 경로로 주거나, 페이지 파일 경로만 저장하는 더 단순한 방식은 권한·재현성 경계를 깨므로 쓰지 않는다. 새 DB/queue/cache는 이 입력 계약 자체에 필요 없다.

`resolved-execution-plan/27.0` 후보는 위 작업 입력, 게시된 프리셋·정의·용량 정책의 revision, 기존 `support` 풀의 창작 분석 단계와 전용 instruction bundle을 하나의 재현 가능한 해시로 묶는다. 이 단계는 worker에게 읽기 전용·네트워크 차단·일반 지식 차단을 요구한다. schema/typed validation과 기존 control-plane 테이블에 재전송을 구분해 기록하는 resolver는 구현됐다. 실제 source/page 및 저장 작업에 묶인 실행 context 없이는 Orchestrator의 명시적 비활성 차단을 유지한다.

2026-10-27 운영 read-only 확인: V27 plan 저장 건수는 **0**이며 설치된 fixed-host capacity는 기존 `worker-capacity-policy/1.3`이다. 이 정책의 `support`는 slot05·상한 1, `customer-support`는 slot06·상한 1이다. 따라서 아직 미발행인 V27 후보의 불필요한 `creative-learning` 풀을 기존 `support`로 정리한다. 새 capacity schema·풀·슬롯·host 상한을 만들거나 기존 capacity revision을 수정하지 않는다. 별도 창작 프리셋·instruction과 exact 작업/step/context로 목적을 검증하고, 기존 slot05 claim/lease로 분석 실행을 한 번에 1건으로 제한한다. 기존 분석 작업과 경쟁하면 대기하며 A/S slot06은 점유하지 않는다. 이 결정은 미발행 후보에만 적용하고 과거 plan/lease/control bytes는 변경하지 않는다.

역할 메시지의 후속 규격 `workflow-role/1.33.0`은 위 입력과 `external-item-learning-result/1.0` 제안만 허용하는 `support` 1단계다. JSON Schema 2020-12 정본·패키지 리소스, Pydantic 모델, Codex 출력용 projection, 정확한 source/page 결합 검사와 1단계 Workflow 정의의 소스 테스트까지 준비했다. 모델이 결과 해시를 생략하면 Orchestrator 검증 경계에서 정확한 제출 본문의 해시를 계산하며, 잘못 제출한 해시는 덮어쓰지 않고 거부한다. **Workflow 정의 파일은 아직 운영 admission 또는 활성화가 아니다.** 저장된 작업/운영자 권한에 묶인 Catalog source read, 페이지 Artifact materialization, 실행 프리셋과 결과 수락을 **한 호환 release 경계**로 닫은 뒤에만 Codex 슬롯 실행이나 Graph 게시를 표시한다.

### 실제 호출 없는 Orchestrator 실행 연결 검증

2026-10-27 18:47 UTC. Orchestrator의 기존 역할 실행 경로에 `ExternalItemLearningExecutionContext`를 연결하는 소스 후보를 추가했다. 이는 서버 composition이 제공하는 source-authorizer callback과 기존 file-set publisher의 작은 불변 조합이며, worker JSON에 실리는 authority가 아니다. 상위 application은 저장된 Workflow/step/실제 owner에서 callback을 만들어야 한다. 현재 production composition에는 아직 연결하지 않았다.

- 명시적 context가 없으면 기존 `CONTROL_CREATIVE_LEARNING_NOT_ACTIVATED` 차단을 유지한다. context가 있어도 support/extract/정확한 결과 규격·입력과 V27 plan row의 ID·revision·hash·시각이 일치해야 한다. 다른 작업·escalation·Graph 문항 context를 섞으면 job 생성 전에 거부한다.
- 원본 권한·입력 페이지 Artifact를 먼저 검증하고, 기존 capacity의 `KNOWLEDGE_ANALYSIS`로 claim한다. 입력 파일 배치와 마지막 source 재인가가 끝난 후에만 실제 worker launch 경계로 넘어간다. 배치 실패는 ‘시작됐을 수 있음’으로 처리하지 않고 lease를 반납한다.
- 결과 수락 전에는 exact source/page Artifact를 다시 확인한다. source 철회·페이지 manifest 불일치는 실패 이력을 남기고 Artifact commit을 막는다. terminal replay는 현재 권한을 재확인하되 worker를 다시 켜거나 FAILED 상태를 성공으로 바꾸지 않는다.
- 페이지 file-set의 승인/identity/hash/canonical path 검사 규칙은 기존 게시 모듈의 한 read 함수로 모아 실행 전 검사와 worker materializer가 함께 사용한다. binary를 새 DB 행이나 메시지로 복사하지 않는다. 독립 수명 없는 실행 context를 새 registry/framework로 만들지 않는다.
- 관련 역할 실행/materializer unit **341 PASS**, 수정 source 4개 mypy·Ruff PASS. 그 안의 새 실행 테스트는 합성 Job/트랜잭션과 **비-Codex worker 대역**만 사용했다. 실제 Codex 호출·systemd worker 시작·운영 DB/NAS write는 0회이며, 실제 Catalog 전송·제출 준비·운영 release 전 점검은 아직 남아 있다.

### Runner→Catalog 현재 원본 재인가 계약

기존 private socket에 runner 전용 `AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT` 읽기 operation 하나만 추가한다. 새 검색 서버나 공유 인증 자격을 만들지 않는다. JSON Schema 2020-12의 작은 selection은 Workflow·step·plan ID/plan hash·work-input hash만 담고 operator/session/권한/원본 경로는 받지 않는다. Catalog가 저장된 Workflow와 step에서 실제 owner 및 정확한 원본을 얻어 현재 권한과 source/preview를 다시 검증한다. 논리 entity/revision/hash는 기존 work input에 보존된다.

정본은 기존 Workflow/step/plan과 Catalog source/Artifact이며 selection은 indexed key lookup용 포인터다. 조회는 고정 수 key lookup과 한 문항의 bounded Artifact 검증으로 O(log n + input bytes)이고 새 table/index/cache가 필요 없다. 요청 root에서 현재 데이터를 읽을 뿐 state transition·command enqueue·모델 호출·NAS commit은 없다. 응답은 요청 canonical SHA와 확인한 source SHA 또는 안전한 오류 코드만 반환하며 성공을 캐시하지 않는다. source 철회·stale·다른 owner/step/plan 선택은 거부하고 latest로 바꾸지 않는다.

의존 방향은 Runner application의 socket adapter → 기존 Catalog private service → Catalog source owner다. 서버는 실제 peer UID로 runner의 이 operation만 허용하며, API·worker가 operator ID를 공급해 가장할 수 없다. 더 단순한 runner의 Catalog/NAS 직접 읽기나 전체 socket operation 허용은 기존 격리 경계를 깨므로 배제한다. 재전송은 같은 읽기를 다시 인가하며 작업·Artifact를 새로 만들지 않는다.

2026-10-27 소스 후보 검증: Catalog 서버/composition/기존 read 경계를 포함한 관련 unit **412 PASS**, 최종 신규 authorization unit **30 PASS**, 수정 source 7개 mypy 및 Ruff/format PASS. 신규 검사는 실제 로컬 Unix socket과 합성 저장소/현재 UID로 요청·응답 결합, 호출마다 재인가, source 철회, runner 전용 operation, 잘못된 프레임·hash를 검사했다. 설치된 운영 socket/실제 DB 원본/실제 슬롯의 PASS가 아니며 Codex 호출은 0회다. 새 source 연결은 아직 운영 배포하지 않았다.

### 실행하지 않는 준비 application

기존 Workflow 저장 application 위에 준비 use case 하나를 둔다. 입력은 이미 Orchestrator가 게시한 exact source/page work input, 실제 제출 operator, 멱등 key다. 대화형 인증은 호출자가 확인하고 현재 source 권한은 기존 Catalog authorizer가 다시 확인한다. 페이지는 기존 Orchestrator file-set owner에서 승인·멤버·SHA·정본 경로를 재검증한다. worker JSON이나 임의 runtime-context로 권한을 받지 않는다.

caller root transaction 안에서 기존 Workflow unique/idempotency 저장 → Workflow row lock → V27 plan 고정 → READY step/append-only event 한 번 저장으로 끝낸다. 주요 접근은 고유 key와 `(workflow_id, step_key, attempt)` index이므로 고정 수 O(log n) 조회와 bounded 한 문항 검증이다. 새 table/index/queue가 필요 없다. 재전송에서도 원본과 page를 재인가하고 동일 exact request/plan/step만 돌려준다. 시작·완료·실패 이력이 이미 있는 작업을 새 ‘준비 성공’으로 바꾸지 않는다. 늦은 권한/source 거부는 caller root 전체 rollback이다.

**이 use case에는 enqueue/claim/worker-start 호출이 없다.** 기존 runner는 START command가 있어야 실행하므로 READY step만으로 모델이 실행되지 않는다. 다음에 승인된 시작 application이 기존 command 경계를 사용할 수 있으며 준비와 시작을 boolean flag 하나로 합치지 않는다. 단순히 generic start를 호출한 다음 즉시 중지하는 대안은 실제 추론이 시작될 경합을 만들기 때문에 배제한다. 이 내부 application은 사용자용 시작 버튼이나 실제 원본의 운영 준비 증거를 대신하지 않는다.

2026-10-27 19:20 UTC 소스 후보: `prepare_external_item_learning_workflow`를 구현했다. 관련 역할·입력·materializer·인가·준비 unit **108 PASS**, 신규 준비 source mypy 및 Ruff/format PASS. disposable PostgreSQL의 외부 문항/조립/창작 저장 검사 **16 PASS** 안에서 같은 key/다른 key 동시 준비가 Workflow 1개·READY step 1개·event 2개·command 0개로 수렴하고, 마지막 source 재인가 거부 시 전부 rollback되는 것을 확인했다. 이 DB 검사의 source/page/plan port는 명시적인 합성 fixture이며 운영 source/preset 검증이라고 주장하지 않는다. 임시 DB `20261027191917_496e92b3`은 공식 cleanup으로 제거했다. 실제 Codex 호출과 실행 명령 생성은 0회다.

남은 종료 게이트는 **실제 원본 1건의 격리 page Artifact 준비**, **전용 instruction/preset/capacity의 공식 고정**, **호환 운영 설치본에서 source→저장 작업→plan→worker staging의 실행 전 점검**이다. 창작 definition의 신규 작업 admission과 실제 START는 이 연결 없이 먼저 열지 않는다. 소스 unit 또는 합성 DB PASS만으로 목표 완료를 선언하지 않는다.

### 기존 control owner를 재사용하는 지침·프리셋 준비

전용 플랫폼/역할 지침은 기존 `control_markdown` 및 `instruction-bundle-manifest/1.0` Artifact owner로 게시한다. 역할 지침은 기출 V10의 공개 가능한 풀이·정답 비교와 기존 추출의 closed source anchor 규칙을 창작용 region 계약에 맞춰 재사용하며, 새로운 비공개 사고 과정 저장이나 Graph ID 합성을 요구하지 않는다. 지침 원문은 source config, 게시된 Artifact revision이 실행 시 정본이고 경로는 저장 위치일 뿐이다.

프리셋 준비는 이미 released인 exact fixed-host V4 capacity와 기존 `support`/slot05/상한 1을 검증하고 기존 preset lifecycle로 **DRAFT만** 만든다. 새 capacity나 slot/auth 상태를 쓰지 않는다. instruction logical key·revision·schema/media/hash와 두 component의 layer/path를 검증하고, 같은 desired policy는 indexed preset key/최신 revision 조회와 기존 control advisory lock으로 중복 draft 없이 replay한다. 큰 지침 bytes는 Artifact에만 있고 DB에는 pointer/작은 policy만 남는다. 작업자 또는 caller가 주장한 권한은 받지 않고 상위 authenticated application의 현재 권한 port를 mutation 직전/직후 확인한다.

이 단계는 새 queue/registry/bootstrap wire contract를 만들지 않는다. 내부 immutable 값과 기존 generic control schema를 사용한다. Artifact commit과 control transaction은 독립 경계이므로 나중 실패 시 게시 이력은 보존하고 같은 입력으로 복구한다. 더 단순한 released preset 직접 삽입은 evaluation/release invariant를 우회하므로 금지한다. 준비 함수에는 평가 PASS 생성, release/activation, 모델 가용성 갱신, Codex 호출, START enqueue가 없다. 실제 availability/quota와 과학적 품질은 이 DRAFT의 PASS가 아니다.

2026-10-27 19:45 UTC 소스 후보 검증: 위 instruction 게시 및 DRAFT application을 구현하고, 실행 계획 후보를 기존 `support` 풀에 맞췄다. 관련 실행·control·Artifact unit **134 PASS**, package resource/wheel·설치 스크립트·설정·역할 규격 unit **59 PASS**, 수정 source 4개 mypy 및 Ruff/format/shell syntax PASS. 실제 disposable PostgreSQL의 외부 문항 전체 검사 **17 PASS**를 재전송 실행에서도 확인했다. 신규 control 검사는 실제 Orchestrator Artifact commit과 실제 generic control 저장/논리 잠금을 사용하되 원문·권한 port는 합성이다. 지침의 exact replay는 Artifact 3개를 재사용하고, 동시 준비는 DRAFT revision 1개/current activation 없음/evaluation 0개로 수렴한다. 늦은 권한 거부나 다른 모델 재전송은 기존 초안을 변경하지 않는다. 임시 DB `20261027193933_c44bb0ef`은 공식 cleanup으로 제거했다.

지침 원문은 `config/control-plane/external-item-learning-v1/instructions/`에 기록했으며 기존 fallback prompt와 결과 hash 생략 규칙을 일치시켰다. 설치 inventory에 exact 창작 definition/fallback prompt를 추가했지만 **설치 스크립트를 운영에서 실행하지 않았고**, 기존 설정·auth·슬롯·capacity는 변경하지 않았다. 운영의 V27 plan 0건 및 fixed-host V4 확인은 read-only transaction의 실제 조회이고, 새 지침/프리셋/원본 작업이 운영에 준비됐다는 뜻은 아니다.

다음 작업은 **실제 인증을 받는 한 준비 entry point**에 Catalog 원본 읽기 → Orchestrator 격리 렌더/페이지 게시 → 기존 control evaluation/release → 저장 Workflow/plan/READY step과 실행 전 materialization을 연결하는 것이다. 이 entry point는 마지막에 시작 명령을 enqueue하지 않는다. 임의 operator ID나 옛 session을 만들어 넣지 않고 기존 identity service의 실제 인증과 현재 권한을 사용해야 한다. source helper 또는 DRAFT만 만든 상태를 최종 준비 완료로 보고하지 않는다.

19:50 UTC 패키지 checkpoint: source commit `42f265b03bf7b66d819aaae51404f12bd825dde1`을 푸시하고 기존 `scripts/api/deploy_release.sh --build-only`를 통과했다. source archive/wheel RECORD 및 설치 simulation PASS. 추가로 새 창작 모듈 6개를 **wheel에서만** 불러와 각 모듈 경로가 임시 설치본 아래인지 확인했고, `workflow-role/1.33.0` 입력 및 support 풀로 고정된 V27 스키마를 로드했다. Codex 호출·운영 설치·서비스 재시작은 없다.

- build directory: `/tmp/eom-api-build/42f265b03bf7b66d819aaae51404f12bd825dde1.fEhf10/dist`
- `eom_platform-0.1.0-py3-none-any.whl`: `sha256:7764421550fda9707b9af70461fc35872ff9314e0ac8360c8ca44eb7c35ae1cd`
- `eom_application_api-0.1.0-py3-none-any.whl`: `sha256:770a8e5b7ce648a15d51f9916c6a956508b0f310f8c32946e15a3465d2bd4eeb`

위 build는 운영 release가 아니라 **후속 연결 구현 전 소스 후보의 설치 검증**이다. runtime activation이나 슬롯 준비 완료의 대체 증거로 사용하지 않는다. GPU INDEX는 마지막 19:42 UTC 조회에서 동일 PID `734655`와 시작 시각 `2026-10-26 00:32:30 UTC`, active/running을 유지했다.

### 인증된 실행 전 준비 입구의 연결 결정

하나의 privileged 운영 CLI가 기존 Identity `AuthService`로 실제 로그인하고, 메모리 안의 access token으로 현재 operator·session·필요 권한을 다시 확인한 뒤 Catalog application을 호출한다. 인증 DTO/작업 소유자는 실제 인증 결과에서만 얻으며 caller가 operator ID·permission·옛 session을 입력해 가장할 수 없다. 비밀번호는 숨김 TTY 입력만 받고 token/비밀번호/원본 PDF를 report·명령행·파일에 저장하지 않는다. 정상/실패 종료 시 이 CLI가 만든 session만 로그아웃한다. 이것은 관리자용 로컬 composition이며 Codex worker나 일반 API에 DB/NAS 접근을 추가하는 경로가 아니다.

입력은 기존 `external-item-learning-start/1.0`의 exact source selection과 고정된 지침/source commit/시각/멱등 key이며, 이 CLI의 실제 동작은 **PREPARE, NOT START**다. 기존 wire schema는 바꾸지 않는다. application이 Catalog 원본/PDF 읽기 → Orchestrator 격리 렌더/페이지 Artifact → generic control lifecycle → owner-bound Workflow/V27/READY step을 순서대로 조정한다. 원본/PDF/지침 정본은 기존 Artifact이고 DB에는 작은 pointer와 manifest만 저장한다. root별 commit을 하나의 distributed transaction으로 부르지 않는다. 중간 실패의 immutable Artifact는 보존하고 exact source·멱등 key로 재개한다. source/관찰/교정본/지침/계획이 바뀌면 conflict로 중단하며 latest로 대체하지 않는다.

새 초기 control release는 기존 generic `ExecutionPresetEvaluationReport`의 `NON_LIVE/CONTRACT_VALIDATION`, quality score 없음으로 기록한다. 실제 실행하는 검사는 role protocol/schema, exact instruction metadata, 기존 support capacity, 정확한 policy 및 기존 `non_live_invocation_cases`의 CLI 인자/transport 양·음성 검사뿐이다. 과학적 품질·계정의 사용 자격·quota 또는 모델 추론 PASS가 아니다. 2026-10-27 저장된 support05 가용 모델 projection은 빈 목록이므로 이를 fresh capability PASS로 꾸미거나 OBSERVE/추론을 자동 실행하지 않는다. 초기 policy 준비와 실제 worker claim을 구별하고, 실제 시작 시 기존 current account/model/capacity/lease 검사는 그대로 유지한다. 기존 model-selection successor의 fresh-capability gate를 변경하거나 우회하지 않는다.

control 초기 release는 해당 exact DRAFT/policy에 대한 검증 보고서와 pointer를 기존 lifecycle에 넘길 뿐이고 START/slot/auth/계정 상태를 변경하지 않는다. 재전송은 이미 published인 **동일** 초기 policy와 exact 평가 pointer만 재사용하며, 다른 policy나 누락된 평가 이력은 거부한다. 자료 준비는 actual source/page/plan과 source 재인가를 검사하고, worker workspace materialization은 launch 호출 없이 끝낸다. 더 단순한 ‘root이므로 operator/session을 만들기’ 또는 ‘일단 START 후 바로 중단’은 각각 인증과 무실행 경계를 깨므로 배제한다.

## 필수 설계 절차

1. **책임과 경계:** Catalog application은 exact 외부 원본→정본 Item 승격 근거, 승인, 분석, 보고서, Graph 게시를 조정한다. Orchestrator만 worker 실행과 Artifact commit을 지휘한다. worker는 DB/NAS에 직접 쓰지 않는다. Web/API는 typed 명령과 조회만 제공한다.
2. **정본:** 외부 행·파일의 Content Intake Artifact Revision, 승인된 Item Revision과 Item Origin profile, accepted Knowledge Analysis base, accepted solution-report Artifact, 게시된 Graph Snapshot이 각각 자기 영역의 정본이다. 원본 HWP/PDF와 파생 텍스트를 동일시하지 않는다.
3. **논리 ID/리비전:** `(source_namespace,U)`는 외부 source의 업무 식별자다. `source_revision_id`, `item_id`, `item_revision_id`, `analysis_run_id`, `graph_snapshot_revision_id`는 별개다. 같은 U의 새 교정본은 새 source revision이며 accepted Item Revision을 제자리 수정하지 않는다.
4. **포인터 검증:** 한 승격 제안은 workbook 행/시트/셀 관찰 해시, 선택 교정본 source-file/Artifact Revision/member/media/hash, 구조화 결과·검토/승인 receipt, Item content/manifest/hash, Origin profile, accepted base 분석의 정확한 ID/hash를 고정한다. 각 사용 전에 존재·권한·lifecycle·schema/media/member·hash·현재 선택 의미를 재검증한다. 불일치에는 latest 대체가 없다.
5. **주 접근:** 외부 U exact/keyset, source revision→Item revision 역조회, Item revision→accepted base/풀이보고서, pinned Graph Snapshot→Item node→교육과정/개념 edge, 해당 사용자의 권한 확인. 교육과정/개념 검색은 기존 Catalog Graph read/retrieval을 사용하고 원본 A:AF 필터는 별도의 정확한 Catalog 조회다.
6. **구조·인덱스:** `(namespace,U)` unique, source revision/current pointer, Item Origin reverse lookup, analysis source-revision index, accepted successor unique/idempotency, Graph snapshot/node/edge B-tree 및 기존 adjacency를 우선 사용한다. 새 인덱스는 실제 access plan이 필요할 때만 추가한다. 중복 집합은 set/map, ordered output은 불변 tuple, 감사 이력은 append-only다.
7. **규모와 비용:** 초기 외부 행 1,297, 연결 후보 1,053, 최종 확장 수십만을 가정한다. 임포트는 bounded chunk, 중복 확인은 인덱스 기반 O(log n), 한 문항 검증은 그 문항의 bounded 멤버/anchor에 비례한다. Graph publication은 accepted proposal 수와 파생 node/edge 수에 선형이고, 온라인 검색은 bounded Graph traversal/page다. HWP/PNG/PDF/보고서 본문은 DB에 저장하지 않는다.
8. **트랜잭션·동시성:** Content Intake와 Item Registry의 기존 트랜잭션을 우회하지 않는다. 한 U의 승격은 exact source revision과 승인 결정을 고정한다. 두 실행의 동일 source→accepted Item 충돌은 unique/CAS에서 거부한다. Graph 게시 전 source/current Item/policy/Graph head를 재검증하고 기존 publisher의 CAS로 immutable successor snapshot을 만든다. 부분 완료는 각각의 불변 이력으로 남긴다.
9. **의존 방향:** JSON Schema 2020-12 → Pydantic value/command → Catalog application → 기존 Item Registry, Artifact, Graph publisher 어댑터. 원본 변환/텍스트 추출은 격리 adapter다. 도메인 모델이 SQL·파일시스템·HTTP를 import하지 않는다.
10. **실패·재시도:** hash/권한/형식/답안/풀이 불명확은 해당 U를 격리하고 다른 행을 성공으로 꾸미지 않는다. 동일 idempotency key+입력은 기존 결과 조회, 다른 입력은 conflict다. worker 실패 기록은 보존한다. 승인 분석 없는 Graph 게시, 승인 분석 없는 보고서, 보고서 없는 최종 창작 학습 완료, origin proof 없는 Graph 게시는 fail-closed한다. 그래프 게시 실패 시 Item과 보고서를 지우지 않고 exact predecessor head에서 재시도한다.
11. **더 단순한 대안:** 원본 행을 `APPROVED_ITEM` Graph node로 바로 삽입하거나 V10에 가짜 PDF anchor를 채우거나 ordinary publisher에 가짜 Workflow receipt를 넣는 방법은 코드가 짧아도 근거·권한·재현성을 깨므로 배제한다. 새 벡터 DB/Graph DB를 만드는 것도 기존 Catalog Graph 계약을 중복하므로 배제한다.

### 인증된 PREPARE 소스 검증 체크포인트

2026-10-27 UTC. 로컬 운영 입구 `eomctl content external-items learning prepare`와 Catalog 준비 application을 연결했다. 실제 로그인에서 얻은 operator/session 및 현재 네 권한을 사용하고, 정확한 source selection → 기존 Orchestrator 페이지/지침 Artifact → 초기 NON_LIVE control release → Workflow/plan/READY step → 임시 worker staging을 검사한다. 입력 source commit은 설치된 API build metadata와 runtime commit 모두에 일치해야 한다. 새 dependency는 없다. API application import는 이 명시적 운영 명령 안에서만 수행하여 기존 Identity 인증 정책·token codec을 재사용하며, 따라서 이 명령은 호환 platform/API 설치본에서만 실행한다. 일반 eomctl import에 API wheel을 강제하지 않는다.

- 최종 focused unit **168 PASS**, 변경 source 9개 mypy·Ruff/format PASS.
- 새 disposable DB `20261027203534_395c2253`에서 migration roundtrip 및 외부 문항/조립/준비 검사 **17 PASS**. 실제 SQL의 Identity 초기 로그인/공식 비밀번호 변경/현재 인증, generic preset release, Artifact commit, Workflow/plan/READY 저장, 동일 요청 replay, staging materialization, 로그아웃 후 거부를 검증했다. 원본 Office/PDF 읽기만 합성 fixture이며 실제 운영 파일/격리 systemd/runner UID PASS는 아니다. 실행 명령·platform job·Codex 호출은 0개다. 임시 DB는 공식 cleanup 완료했다.
- 이 체크포인트는 **소스 후보**다. 다음은 새 wheel의 코드 closure/RECORD, 호환 운영 설치, 실제 원본 1건의 무실행 PREPARE다. 주간 quota·모델 사용 가능 여부는 확인하지 않았으며 실제 호출을 통한 검사도 하지 않는다.

## 프로토콜 구현 순서

1. 외부 source revision과 검증된 정본 Item Revision을 연결하는 schema/command를 먼저 정의한다. 원본만 있는 행은 이 연결이 없다.
2. 창작 풀이보고서 successor의 request/worker proposal/receipt/accepted result를 schema-first로 추가한다. V10의 풀이 단계·선지 진단·출제요소 연결 의미는 재사용하되, V9 page-image reference index 대신 승인 Item Content·해설 및 검증된 원본 위치를 anchor authority로 정의한다. 기존 V1–V10 bytes와 과거 보고서는 변경하지 않는다.
3. accepted report가 해당 accepted base와 Item Revision에 유일하게 연결됨을 DB 제약과 application guard로 검증한다. 중단·동시성·재전송은 disposable PostgreSQL에서 시험한다.
4. 창작 origin 검증 application이 accepted source/Item/analysis/권한을 확인하고 기존 `AutomaticItemGraphPublicationService`에 후보를 넘긴다. 새 Graph 저장 엔진은 만들지 않는다. 기출 520건의 실제 처리처럼 accepted base analysis가 먼저 Graph에 게시되고 풀이보고서가 additive successor로 뒤따를 수 있다. 보고서 대기 중에도 `GRAPH_PUBLISHED`와 `SOLUTION_REPORT_PENDING`을 서로 다른 상태로 표시한다. 둘 다 끝나야 이 작업의 창작 학습 완료다.
5. DB의 `창작` 검색은 published Graph에서만 교육과정/개념 결과를 얻는다. 원본 전용 A:AF 결과와 공통 화면에서 명확히 분리하고 Graph 미게시·보고서 대기·게시 완료를 별도 상태로 표시한다.
6. 실제 업로드 자료는 소수 표본에서 추출→풀이→승인→보고서→Graph→검색·다운로드 검증 후 bounded chunk로 확대한다. 모호한 14개 파일 대응은 자동 승격하지 않는다.

## 장기 실행 슬롯과 진행 판정

이번 아카이브는 일괄 Graph 삽입 대상이 아니다. 원본 Intake가 완료된 뒤에도 각 문항은 `SOURCE_ONLY → 추출 제안 → 검증된 정본 Item → accepted 분석`을 먼저 통과한다. 그 후 Graph 게시와 additive 풀이보고서는 각자 불변 결과와 재시도 경계를 가진 후속 작업이며 둘 다 끝나야 전체 창작 학습이 완료된다. 기존 기출 520건 처리처럼 Catalog의 영속 작업/claim과 Orchestrator의 worker lease를 사용한다. tmux 창이나 한 번의 CLI 실행을 작업 상태의 정본으로 삼지 않는다.

- 기존 6개 Codex 슬롯 중 **한 슬롯만** 창작 추출·풀이 작업에 할당하는 후속 실행 정책을 만든다. 실제 slot ID는 운영 중인 A/S·문서 검토·출제 작업과 capacity policy를 조회한 뒤 고정하고, 동시 창작 작업 상한은 1이다. 기존 사용자의 대화형 작업을 굶기거나 GPU INDEX/QUERY 실행 핀을 변경하지 않는다.
- runner는 `(source revision, selected edition, task kind, contract revision)`의 고정 키로 대기 작업을 원자적으로 claim한다. 만료 lease는 기존 supported reconcile을 거치고, 동일 작업의 재전송은 기존 result/receipt를 돌려준다. 실패 이력을 성공으로 바꾸거나 다른 identity로 중복 제출하지 않는다.
- 추출·풀이·검토의 각 단계마다 worker는 로컬 staging input만 읽고 구조화 proposal만 낸다. Orchestrator/Catalog가 schema·pointer·해시·정답 일치·승인 조건을 검사한 뒤 Artifact와 DB 상태를 commit한다. Graph publisher는 accepted base 분석이 준비된 문항만 기존 batch 상한 안에서 게시하고, 풀이보고서 결과는 별도의 정확한 Item/analysis revision에 결합한다.
- 진행률은 전체 XLSX 행 수가 아니라 `최종본 후보 / 파일 연결 확정 / 정본 승격 / 풀이보고서 승인 / Graph 게시 / 격리`를 서로 다른 분모와 함께 표시한다. source-only 행은 Graph 미게시로 남긴다. 14개 연결 예외, 답안 불명확, 추출 신뢰도 부족은 자동 승격하지 않고 별도 사유로 남긴다.
- 운영 모니터링은 GPU 보조 작업처럼 과도하게 폴링하지 않고, 기본 30분 간격의 read-only projection과 `BLOCKED`/종료 milestone에서 확인한다. 새로운 worker를 켜기 전에는 별도 Codex 슬롯의 실제 인증·capacity·기존 작업 영향·재시작/중단 복구를 검증한다.

## 종료 증거

- 원본/정본/분석/보고서/Graph의 각 ID·revision·hash가 하나의 U에서 역추적된다.
- Codex의 검증 가능한 풀이 단계·정답/해설 비교·개념 출제 연결이 정본 Item과 일치하며 승인된 결과 Artifact로 남는다.
- 동일 U/Item/분석의 재전송·경합에서 중복 accepted successor 또는 중복 Graph membership이 0이다.
- 원본 전용 행은 Graph 근거 또는 풀이보고서 완료로 보이지 않고, 게시된 창작만 Graph 검색에 나타난다.
- 기출 V10과 ordinary/25문항 게시의 historical replay가 그대로 통과한다.

## 검증 뒤 재사용 기능으로 승격할 경계

이번 N제 아카이브는 등록 파이프라인의 첫 실사용 입력이다. 소수 표본과 전체 대상에서
중단·재전송·정본/Graph/보고서 역추적이 검증되기 전에는 이를 범용 사용자 기능으로
표시하지 않는다. 검증 뒤에는 출처별 임포터를 늘리는 대신 **하나의 등록 입력 계약**을
공개한다. 계약의 필수 정보는 원본 Artifact Revision·SHA·media/member, 문항별 원본 위치,
문제/해설 대응, 외부 식별자(있을 때), 편집본 선택·승인 근거, 제안한 정본 콘텐츠와
신뢰도/미해결 항목이다. XLSX의 A:AF나 PDF의 페이지 좌표 같은 출처별 관찰값은
손실 없이 별도 source observation에 남기고, 공통 계약의 필수 정본 필드인 것처럼
가장하지 않는다.

향후 PDF 교재·시험지·해설지는 Content Intake가 원본과 페이지를 먼저 고정한다.
Orchestrator를 통해 실행된 Codex worker는 그 고정 입력에서 문항 구획, 문제-해설
연결, 텍스트·표·그림 위치, 정답과 근거를 **구조화 제안**으로 돌려준다. worker에게
DB/Graph/NAS 쓰기 권한을 주지 않는다. Catalog application이 JSON Schema 2020-12와
Pydantic으로 제안을 검사하고 원본 페이지/좌표·해시·권한을 재확인한 뒤, 기존과 같은
정본 Item 등록·분석·Graph·풀이보고서 경계에 넘긴다. PDF의 문항 위치가 모호하거나
해설 대응이 불명확하면 그 문항만 `NEEDS_DECISION`으로 격리하며 임의로 합치거나
승인하지 않는다. 원본 PDF는 수정하지 않는다.

PDF용 입력 어댑터를 구현할 시점에는 먼저 이번 아카이브에서 검증된 공통 계약과
실제 실패 유형을 기준으로 schema successor를 작성한다. XLSX/HWP의 U 번호를 PDF에
강제로 요구하지 않고, PDF에는 원본 document/page/region과 파일 내 문항 번호를
별도 source identity로 사용한다. 기존 기출 `PAST_EXAM` occurrence가 확인되지 않은
교재 문항을 기출로 위장하지 않으며, 교육과정/교과서 원문 근거와 창작 문항의
출처·권리 상태를 분리한다.

기능 승격의 gate는 대표 문항의 사람이 확인 가능한 원본↔정본 대조, 문제/해설 대응,
정답·풀이 검증, 중복/재전송 방지, 같은 Item Revision에서의 Graph·보고서 역추적,
권한별 검색과 실패 격리다. 단순 PDF 텍스트 추출 성공 또는 worker 제안 스키마 PASS만으로
등록 파이프라인 완료라고 판정하지 않는다.
