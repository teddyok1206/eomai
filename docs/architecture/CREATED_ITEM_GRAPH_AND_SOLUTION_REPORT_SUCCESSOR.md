# 창작 문항 풀이보고서·Graph 게시 후속 계약

상태: 설계 결정 및 구현 게이트. 2026-10-27 UTC. 이 문서는 원본 XLSX/ZIP만으로 Item 승인이나 Graph 게시가 완료됐다는 뜻이 아니다.

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

현재 구현은 페이지 세트 스키마·검증 모델과 Orchestrator의 **격리 렌더 어댑터**까지다. Artifact publisher, 정확한 Catalog PDF resolution, Workflow/slot admission은 아직 연결되지 않았으므로 이 단계의 소스 테스트만으로 운영 창작 분석이 가능하다고 표시하지 않는다. 개발 셸 계정에는 새 systemd transient unit 생성 권한이 없어 격리 runner의 실제 운영 실행 검증도 별도 운영 경계에서 필요하다.

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
