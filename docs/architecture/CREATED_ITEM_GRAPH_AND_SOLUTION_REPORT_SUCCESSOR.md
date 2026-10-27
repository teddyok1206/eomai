# 창작 문항 풀이보고서·Graph 게시 후속 계약

상태: 설계 결정 및 구현 게이트. 2026-10-27 UTC. 이 문서는 원본 XLSX/ZIP만으로 Item 승인이나 Graph 게시가 완료됐다는 뜻이 아니다.

## 경계와 현재 사실

`PAST_EXAM`은 기출 occurrence와 실제 PDF 페이지 위치를 가진 승인 문항이다. `APPROVED_ITEM`은 occurrence 없이 승인된 정본 Item Revision이다. 기존 `knowledge-analysis-request/10.0`은 전자의 V9 시각 분석·문제/해설 페이지 anchor에 고정되어 있다. 기존 ordinary-item Graph publisher는 EOM authoring/review/registration Workflow의 역할 결과·receipt를 요구한다. 업로드한 N제 원본은 어느 쪽 이력도 자동으로 갖지 않는다. 따라서 V10 또는 ordinary publisher의 검사를 느슨하게 하는 일은 금지한다.

사용자 명칭 `창작`은 기출변형·자유출제의 검증된 출처 분류다. Graph source class는 당분간 현행 `APPROVED_ITEM`을 유지하고, 창작 여부는 검증된 Item Origin profile과 외부 U source revision 연결로 판별한다. 이 구분을 질의·화면·수출 결과에서 유지한다. source-only 원본은 Graph 근거 검색에 들어가지 않는다.

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
10. **실패·재시도:** hash/권한/형식/답안/풀이 불명확은 해당 U를 격리하고 다른 행을 성공으로 꾸미지 않는다. 동일 idempotency key+입력은 기존 결과 조회, 다른 입력은 conflict다. worker 실패 기록은 보존한다. 승인 분석 없는 보고서, 보고서 없는 최종 창작 완료, origin proof 없는 Graph 게시는 fail-closed한다. 그래프 게시 실패 시 Item과 보고서를 지우지 않고 exact predecessor head에서 재시도한다.
11. **더 단순한 대안:** 원본 행을 `APPROVED_ITEM` Graph node로 바로 삽입하거나 V10에 가짜 PDF anchor를 채우거나 ordinary publisher에 가짜 Workflow receipt를 넣는 방법은 코드가 짧아도 근거·권한·재현성을 깨므로 배제한다. 새 벡터 DB/Graph DB를 만드는 것도 기존 Catalog Graph 계약을 중복하므로 배제한다.

## 프로토콜 구현 순서

1. 외부 source revision과 검증된 정본 Item Revision을 연결하는 schema/command를 먼저 정의한다. 원본만 있는 행은 이 연결이 없다.
2. 창작 풀이보고서 successor의 request/worker proposal/receipt/accepted result를 schema-first로 추가한다. V10의 풀이 단계·선지 진단·출제요소 연결 의미는 재사용하되, V9 page-image reference index 대신 승인 Item Content·해설 및 검증된 원본 위치를 anchor authority로 정의한다. 기존 V1–V10 bytes와 과거 보고서는 변경하지 않는다.
3. accepted report가 해당 accepted base와 Item Revision에 유일하게 연결됨을 DB 제약과 application guard로 검증한다. 중단·동시성·재전송은 disposable PostgreSQL에서 시험한다.
4. 창작 origin 검증 application이 accepted source/Item/analysis/report/권한을 확인하고 기존 `AutomaticItemGraphPublicationService`에 후보를 넘긴다. 새 Graph 저장 엔진은 만들지 않는다.
5. DB의 `창작` 검색은 published Graph에서만 교육과정/개념 결과를 얻는다. 원본 전용 A:AF 결과와 공통 화면에서 명확히 분리하고 Graph 미게시·보고서 대기·게시 완료를 별도 상태로 표시한다.
6. 실제 업로드 자료는 소수 표본에서 추출→풀이→승인→보고서→Graph→검색·다운로드 검증 후 bounded chunk로 확대한다. 모호한 14개 파일 대응은 자동 승격하지 않는다.

## 장기 실행 슬롯과 진행 판정

이번 아카이브는 일괄 Graph 삽입 대상이 아니다. 원본 Intake가 완료된 뒤에도 각 문항은 `SOURCE_ONLY → 추출 제안 → 검증된 정본 Item → accepted 분석 → accepted 풀이보고서 → Graph 게시`를 순서대로 통과해야 한다. 기존 기출 520건 처리처럼 Catalog의 영속 작업/claim과 Orchestrator의 worker lease를 사용한다. tmux 창이나 한 번의 CLI 실행을 작업 상태의 정본으로 삼지 않는다.

- 기존 6개 Codex 슬롯 중 **한 슬롯만** 창작 추출·풀이 작업에 할당하는 후속 실행 정책을 만든다. 실제 slot ID는 운영 중인 A/S·문서 검토·출제 작업과 capacity policy를 조회한 뒤 고정하고, 동시 창작 작업 상한은 1이다. 기존 사용자의 대화형 작업을 굶기거나 GPU INDEX/QUERY 실행 핀을 변경하지 않는다.
- runner는 `(source revision, selected edition, task kind, contract revision)`의 고정 키로 대기 작업을 원자적으로 claim한다. 만료 lease는 기존 supported reconcile을 거치고, 동일 작업의 재전송은 기존 result/receipt를 돌려준다. 실패 이력을 성공으로 바꾸거나 다른 identity로 중복 제출하지 않는다.
- 추출·풀이·검토의 각 단계마다 worker는 로컬 staging input만 읽고 구조화 proposal만 낸다. Orchestrator/Catalog가 schema·pointer·해시·정답 일치·승인 조건을 검사한 뒤 Artifact와 DB 상태를 commit한다. Graph publisher는 accepted 분석과 풀이보고서가 모두 준비된 문항만 최대 기존 batch 상한 안에서 게시한다.
- 진행률은 전체 XLSX 행 수가 아니라 `최종본 후보 / 파일 연결 확정 / 정본 승격 / 풀이보고서 승인 / Graph 게시 / 격리`를 서로 다른 분모와 함께 표시한다. source-only 행은 Graph 미게시로 남긴다. 14개 연결 예외, 답안 불명확, 추출 신뢰도 부족은 자동 승격하지 않고 별도 사유로 남긴다.
- 운영 모니터링은 GPU 보조 작업처럼 과도하게 폴링하지 않고, 기본 30분 간격의 read-only projection과 `BLOCKED`/종료 milestone에서 확인한다. 새로운 worker를 켜기 전에는 별도 Codex 슬롯의 실제 인증·capacity·기존 작업 영향·재시작/중단 복구를 검증한다.

## 종료 증거

- 원본/정본/분석/보고서/Graph의 각 ID·revision·hash가 하나의 U에서 역추적된다.
- Codex의 검증 가능한 풀이 단계·정답/해설 비교·개념 출제 연결이 정본 Item과 일치하며 승인된 결과 Artifact로 남는다.
- 동일 U/Item/분석의 재전송·경합에서 중복 accepted successor 또는 중복 Graph membership이 0이다.
- 원본 전용 행은 Graph 근거 또는 풀이보고서 완료로 보이지 않고, 게시된 창작만 Graph 검색에 나타난다.
- 기출 V10과 ordinary/25문항 게시의 historical replay가 그대로 통과한다.
