# 창작 문항 순차 풀이·Graph 등록 실행

2026-10-28 UTC. 사용자가 실제 슬롯 실행과 순차 Graph 등록을 승인했다. 이전의 실행 직전 준비 종료선과 구분한다.

## 실행 범위와 순서

- 입력은 완료된 import `extimport_d2019be75aa943636bfa8b7fb7f4a92e`의 정확한 최종본 연결 후보 1,053개다. 전체 관찰 1,297행을 완료 문항 수로 세지 않는다. 초안·반려·파일 연결 예외 14개를 자동 승격하지 않는다.
- 기존 표본 고유번호 `10310`의 준비된 Workflow부터 시작한다. 기존 support 슬롯 `05`, 동시 상한 1, 고정된 `gpt-5.6-terra/xhigh` 실행 계획을 사용한다. 다른 슬롯·Codex 인증·기출/교과서·GPU runtime pin은 바꾸지 않는다.
- 원본과 기출 첨부 영역을 분리한 구조화 추출·풀이 제안을 먼저 확인한다. 실제 결과 수락, 정본 Item/출처 연결, accepted 분석, Graph CAS, 창작 풀이보고서 successor의 역추적이 준비되기 전에는 전체를 실행하지 않는다.
- 최신 사용자 지시: 풀이 중 의문점·정답/해설 불일치가 있어도 **원문 등록을 막지 않는다**. 원문/편집 답안을 수정하지 않고 공개 가능한 풀이·서로 다른 판단·미해결 사항을 별도 보고서에 보존하며, 나중에 공식 조회한 Codex가 이를 함께 읽어야 한다. 원문 수록 승인과 과학적 정확성 검증을 혼동하지 않는다. 기존 worker의 `NEEDS_DECISION` 결과 자체를 `PROPOSED`로 바꾸지 않고, 후속 등록 정책이 이 결과를 `REGISTER_WITH_REVIEW_WARNINGS`로 수록한다.
- 파일·문항을 읽을 수 없거나 source 철회·pointer/hash 불일치가 있는 기술적 실패는 내용으로 꾸미지 않는다. 원천 자료와 실패/미독해 보고를 남기고 원문 내용을 발명하지 않는다.
- 후속 사용자 지시: 문항 약 3개가 차례대로 정본/풀이/Graph 등록과 Codex 조회까지 연결되는 것을 확인한 뒤 나머지 자동 처리를 열고, 이후에는 GPU 임베딩처럼 기본 30분 간격으로 모니터링한다. 주의사항이 있는 문항도 원문/보고서/Graph 연결이 검증되면 이 3건에 포함할 수 있다.

## 시작 경계의 설계 결정

1. 책임: Workflow application은 준비된 작업의 START 명령만 소유한다. 실제 인증과 현재 원본 인가는 기존 Identity/Catalog, 페이지 Artifact 검증은 Orchestrator를 사용한다.
2. 정본: 저장된 Workflow의 original request, READY step, resolved V27 plan과 Catalog 원본/페이지 Artifact다. CLI 파일은 기존 `ExternalItemLearningRoleSelection` 계약의 작은 선택값이며 권한이 아니다.
3. identity: Workflow·step·plan ID와 각각의 고정 hash를 비교한다. source revision과 Artifact revision을 경로나 고유번호로 대체하지 않는다.
4. 해석 검사: 원본과 현재 권한, immutable request/plan 및 페이지 file-set의 schema/media/member/hash/lifecycle을 기존 resolver로 재검증한다. stale이면 latest로 바꾸지 않는다.
5. 접근: Workflow/step/plan PK 조회, Workflow별 START command indexed lookup과 원자적 단일 claim이다.
6. 구조: 기존 Workflow row lock, command unique key, 기존 FIFO command queue·worker lease를 재사용한다. 새 queue/table/index/worker protocol은 없다.
7. 규모: 시작은 고정 수 indexed lookup과 한 문항의 bounded 페이지 검증이다. 후보 순회는 기존 U keyset projection의 25개 이하 페이지를 재사용하고 전체 원본을 매번 복사하지 않는다.
8. 경합: 한 caller root transaction에서 Workflow lock→source/page 검증→기존 START 확인/생성→늦은 재인가를 수행한다. 긴 모델 실행 동안 DB transaction을 유지하지 않는다.
9. 의존 방향: CLI 인증 adapter→Workflow 시작 application→기존 계약/port. Catalog adapter가 source 권한을 구현하고 Orchestrator가 파일·NAS commit을 소유한다. worker 간 통신이나 worker의 DB/NAS 쓰기는 없다.
10. 실패/재전송: START identity는 고정 selection과 실제 owner에서 도출한다. 중복 시작은 원래 명령을 반환하며 FAILED 이력을 성공으로 바꾸거나 새 요청으로 우회하지 않는다. 시작 후 처리 여부가 불명확하면 원래 명령을 조회한다.
11. 배제한 대안: DB에 명령을 직접 INSERT하거나 일반 CLI의 합성 human actor로 시작하면 실제 원본/권한 경계를 건너뛰므로 사용하지 않는다. 준비 단계에 `--start` boolean을 붙이지 않고 별도 시작 use case를 둔다.

## 현재 상태

시작 application을 연결하고 실제 표본 1건을 실행했다. 정본 수락·Graph 게시·장기 자동 처리는 아직 완료가 아니다. 표본부터 실제 불변 output/receipt로 기록한 후 bounded 순차 실행을 연다. 진행률은 원본 준비·실행·제안 수락·정본 등록·Graph 게시·보고서·격리로 나누고 정기 확인은 30분 간격으로 제한한다.

## 첫 실제 실행

- 설치 도구 source: `a8786e66d6bca40cf19370cbe577ff966cf720e4`; 별도 보호된 maintenance wheel. 실제 API/Runner는 `204ee18c7a4cf61c179a1b2953c2deca44d04b1e`, GPU owner의 기존 pin도 유지했다.
- wheel SHA-256: `731cd4d6adfbe46f2991dc37b20884843a4262ae3dbde5990499c4701e59f996`, 표준 RECORD와 설치 CLI 분리 PREPARE/START 도움말 검사 통과.
- source/CLI/인가 회귀 189개 PASS, mypy/Ruff/format PASS. 새 disposable DB의 migration 왕복과 동시 START·늦은 거부·중단 rollback을 포함한 20개 PASS. 같은 DB를 다시 쓴 이전 실행은 이미 released된 합성 preset 때문에 기존 control fixture 1건이 거부됐고, 이를 운영 결함으로 바꾸지 않고 새 disposable DB에서 전체를 확인했다.
- 실제 guiadmin 로그인 성공, START command 저장 후 해당 테스트 session만 로그아웃. root/worker 인증 파일·사용자 비밀번호 변경 없음.
- U `10310`: `workflow_cb2b0260c9fa4a31b7863da88b3e7a9d`, `wfcmd_12b7f2d0392f4f2fbc1df0b94fcfc82e`, `job_b112fe8c8bcc46b3a8ca195098e282fa`. 슬롯 `05`의 실제 ACTIVE lease와 모델 실행을 확인했다.
- Workflow/command/Job: `COMPLETED` / `SUCCEEDED` / `SUCCEEDED`.
- 결과: `extlearnresult_019c7e8a5f5e4e30ac439eb4d4b9e201`, hash `sha256:27e9ce1625043cce165551d6502e59e8150735ff685ef27b92eec56ca8fa189c`.
- 정본 worker 결과: `artifact_a728b1094d4941e38183cb86a6b8488d` / `rev_7c5a0a612dba4697b570c87c18ce4688`, primary JSON SHA `sha256:549990d746dc7d5713c4e9adb7fc4270f8ec4acfa88ba1068bd4fa44304ccdc0`.
- 제안 상태 `NEEDS_DECISION`: 문제·편집 해설·첨부 기출을 분리했고, 문항을 native 표와 진술문으로 제안했지만 편집 답안과 독립 풀이의 `ANSWER_DISAGREEMENT`를 보고했다. 이는 worker가 제기한 불일치이며 원문 오류 확정이 아니다. 이후 사용자가 이런 의문점은 등록을 막지 말고 보고서에 남기도록 정책을 정했다. 원래 결과 상태·편집 답안은 보존하고 주의사항을 동반한 원문 등록 경계를 추가한다.

## 목표 완료 기준과 자동 처리 경계

사용자가 2026-10-28 이 작업을 goal로 지정했다. 전체 1,053건의 학습이 끝나야 goal 완료인 것은 아니다. 표본 3개의 실제 정본/보고서/Graph/조회 및 중단·중복 방지 경계를 확인한 뒤, 같은 고정 대상의 나머지를 슬롯 05·동시 1개로 계속 처리하도록 운영에 연결하고 30분 모니터링으로 전환하면 이 goal의 종료선이다. 전체 완료율과 goal의 준비/자동 실행 완료를 분리해 보고한다.

지금 확인한 추가 연결 범위는 source-only 아카이브의 정본 등록, 창작 origin/분석/보고서 수락, 공유 Graph publication adapter, 주의사항을 포함한 RAG read와 저장된 실제 operator에 귀속되는 장기 실행이다. 기존 일반 Item 승인이나 기출 V9/V10의 의미를 느슨하게 해 우회하지 않는다. 새 브라우저 로그인은 이 장기 작업을 실제 사용자 권한으로 한 번 제출할 때 필요할 수 있으나, 저장된 작업을 처리하는 도중에는 만료된 브라우저 session을 가장하지 않고 현재 계정/권한/source를 claim마다 재인가한다.

## 원문 수록·주의사항 동반 등록의 최소 연결 설계

현재 HWP 원본과 XLSX의 Intake는 `ANALYSIS_PENDING`이다. 이를 일괄 `ACCEPTED`로 바꾸거나, 기존 기출 Origin/occurrence를 합성해 창작 등록에 재사용하지 않는다. 원본 아카이브에 맞는 source→Item 계보를 기존 `SOURCE_REFERENCE` component의 새 작은 불변 계약으로 기록한다. 기출 publisher는 그대로 두고 창작 adapter가 이 계보를 검증한 뒤 기존 `AutomaticItemGraphPublicationService`를 호출한다.

1. **책임:** Catalog가 원문 수록 정책·등록·주의사항과 source 계보를 확인한다. 기존 Registry와 분석/Graph application이 각자 정본을 소유하며 Orchestrator만 Artifact를 커밋한다.
2. **정본:** 원본 Office/PDF·Notion 관찰은 기존 source revision이고, worker 결과는 이미 승인된 exact role-result Artifact다. 수록 Item Content는 원문과 AI 풀이를 구분해 materialize하는 별도 정본이다.
3. **identity/버전:** source ID/revision·관찰 hash, work/plan 선택, role-result pointer/hash, 수록 content hash와 registration policy를 계보 receipt로 pin한다. 외부 U는 metadata일 뿐 DB ID가 아니다.
4. **해석:** source 현재성/권한, 완료 step↔Job↔role-result, JSON Schema/Pydantic, region closure와 실제 페이지를 확인한다. 일치하지 않는 pointer나 첨부 기출에서 내용을 보충하지 않는다.
5. **원문/풀이 분리:** 원문 편집 답안이 AI의 독립 답안과 다르면 원문 답안은 그대로 수록한다. 독립 답안·풀이·불일치는 기존 worker 결과를 고정 참조해 별도 보고서로 읽는다. 명확한 원문 답안/해설의 materialization과 그 근거 region·변환 전후 hash를 기록하고 과거 worker 결과는 수정하지 않는다.
6. **자료구조:** 기존 고유 registration key를 `creative-source:<source_id>`로 사용해 한 외부 논리 문항이 새 Item들로 증식하지 않게 한다. 같은 source revision은 replay, 다른 revision은 명시적인 후속 수정 경계로 거부한다. 모든 원본 A:AF 값은 기존 source observation에 그대로 남는다.
7. **규모/접근:** key/immutable revision 직접 조회와 제한된 manifest 순회다. binary는 DB에 넣지 않으며 role-result 전체나 HWP/PDF를 서비스 사이에서 반복 복사하지 않는다. 기존 Job/Artifact indexed identity와 U keyset projection을 우선 재사용하고 새 검색/queue framework를 만들지 않는다.
8. **트랜잭션:** Artifact commit→Registry 등록→기존 knowledge analysis→Graph CAS는 독립 멱등 단계다. 긴 모델 실행 동안 transaction을 잡지 않고, 각 단계의 exact pointer로 중단 후 재개한다. 동시 등록·중단·재전송은 disposable DB에서 검증한다.
9. **의존:** CLI/상주 composition→Catalog use case→기존 계약/Registry/analysis/Graph port. 원본 읽기와 파일 materialization은 기존 Catalog/Orchestrator adapter가 소유한다. worker는 proposal만 반환한다.
10. **정책과 실패:** 과학적 의문점은 `REGISTER_WITH_REVIEW_WARNINGS`로 보존한다. 원본 미독해와 source/hash/권한 실패는 다른 상태다. 어느 상태도 원본 삭제나 기존 FAILED→성공 변경으로 처리하지 않는다. Codex용 보고서 projection은 의문점·편집 답안·독립 판단을 함께 내보내고 수록 승인을 정답 정확성 보장으로 표현하지 않는다.
11. **간단한 대안 배제:** 원본 Intake 상태를 바꾸거나 `PAST_EXAM`/기출 Origin을 붙이면 없는 승인·시험 이력을 만들게 된다. 새 범용 origin/queue를 도입하는 대신 기존 component pointer와 source에 맞는 검증 adapter를 사용한다. 별도 `ItemOriginProfile`이 필요한 후속 기능에서는 이 계보를 authority로 삼는 정식 successor를 추가하며 기존 V1을 느슨하게 하지 않는다.

## 등록 경계 구현과 첫 적용

`bbf79e5b`는 원문 수록·계보·주의사항 조회·기존 Graph 분석 연결을 별도 maintenance wheel로 설치했다. API/Runner/GPU의 운영 설치본은 교체하지 않았다. schema/반환값·원문 분리·공식 채팅 조회 등 집중 63개, 전용 설정 포함 45개 테스트와 disposable DB의 실제 registration-key 동시성/중단 복구 2개를 확인했다. 동일 사례를 중복 합산한 독립 총계로 표현하지 않는다.

U 10310은 원문 수록과 원래 role-result를 참조하는 보고서 component를 저장했다. 이후 Graph 분석 생성 transaction은 전용 preset이 `workflow-role/1.6.0`만 허용하고 실제 기본 Workflow가 요구하는 1.4를 누락해 거부됐다. 모델 실행이나 실패 상태 재해석 없이 해당 transaction은 rollback됐으며 원문 수록 결과는 보존한다. 초기 preset은 수정하지 않고, 원래 검증된 knowledge-analysis preset의 호환 protocol family 전체와 동일한 모델/지침을 물려받는 successor로 보완한다. capacity는 이미 released된 V4 support(slot05·동시1)만 사용하며 기존 knowledge-analysis preset과 capacity를 변경하지 않는다. 불완전한 초기 전용 release를 일반적으로 허용하는 예외가 아니라 그 exact predecessor의 successor 발행 경계이며, 다음 정상 release부터는 같은 family를 exact replay한다.

실제 후속 분석은 슬롯 05에서 `workflow-role/1.4.0`으로 성공했다. Item은 `item_57e2a7c088b84ac7aa4e68bb9ab93eb4` / `itemrev_bcef1215ccc6469a8c07335f0fb86ffe`, 분석은 `analysisrun_7d22184840974c3a9893ea224a9544eb`다. 구조화 답안의 원문 표지를 단정할 수 없는 경우도 `SOURCE_EDITORIAL_ANSWER_NOT_UNAMBIGUOUS` 주의사항으로 남고 원문 파일과 독립 판단을 구별한다.

Graph 접근 정책은 임의의 가장 최근 revision이 아니라 기존 Graph 자동 등록 owner가 고정한 `accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9`를 사용한다. 다른 용도의 임베딩 정책은 지원 GraphRAG 정책이 아니며 초기 후보 확인에서 기존 validator가 이를 거부했다. 이후 cohort admission은 공식 retrieval service의 supported policy preflight를 통과한 exact revision/hash만 보관한다. 정책이나 역할을 넓혀 검색을 통과시키지 않는다.

## 과거 검토자 계정에 대한 Graph 연결 보완

1. **발견:** 이미 게시된 Graph의 framework 검토자 계정이 비활성화되면, 단순 자동 Item 추가까지 새 검토로 취급하여 거부했다. 계정 재활성화나 과거 review 변경으로 우회하지 않는다.
2. **책임/정본:** 공통 Graph publication owner가 검토 계보를 해석한다. 정본은 exact PUBLISHED snapshot의 검증된 manifest와 structure Artifact다. 새로운 요청자의 현재 권한 검증은 별도로 유지한다.
3. **pin:** 기존 publication command의 expected prior snapshot ID를 사용하고 그 revision의 schema/media/hash/승인 상태/멤버십을 기존 resolver로 확인한다. historical lookup은 current/latest 대체가 아니다.
4. **허용 범위:** 기존 deterministic automatic-extension 함수로 candidate를 재계산했을 때 완전히 같아야 한다. outline·curriculum units·기존 source binding·기존 alignment·reviewer는 보존되고 새 자동 alignment의 prior snapshot도 exact base여야 한다.
5. **불허 범위:** 새 framework, 검토자 교체, 과거 binding 수정/삭제, 다른 base에 붙인 alignment는 상속 검토로 승인하지 않는다. fresh review 경계는 그대로다. 자동 확장을 human review라고 기록하지 않는다.
6. **자료구조/규모:** snapshot PK와 corpus graph index로 조회하고, binding map/set 비교와 deterministic 재계산은 O(n)이다. 새 DB schema/index/queue/worker protocol은 없다.
7. **경합/실패:** structure commit과 최종 publication에서 각각 exact base를 확인하고 기존 Graph-head CAS를 보존한다. stale head는 오류이며 재시도에 latest를 조용히 끼워 넣지 않는다. 실패 후보 Artifact와 이전 성공 snapshot은 보존한다.
8. **간단한 대안 배제:** reviewer ACTIVE 검사를 전역 제거하면 새 미검토 framework까지 통과할 수 있다. 현재 publisher를 과거 검토자로 바꾸면 없는 사람 검토를 만들게 된다. exact 검토 계보를 재사용하는 좁은 경계가 필요하다.
9. **검증:** outline/reviewer 변경·다른 base·retired/missing reviewer·기존 active 경로·다른 정책 family 거부를 포함해 공유 Graph/검색/창작 연결 집중 114개 PASS. 이는 운영 Graph 게시 완료를 뜻하지 않으며 실제 표본 3건은 별도 완료 기준이다.

같은 역사적 계보 규칙은 과거 Item alignment의 검토자·자동 연결 요청자에도 적용한다. 현재 actor가 비활성화됐다는 이유만으로 이미 게시된 동일한 binding을 무효화하지 않되, exact prior snapshot의 검증된 structure에 같은 alignment SHA가 있어야 한다. 새 binding과 현재 publisher의 권한, source/accepted-result/Evidence Bundle/policy 검증은 생략하지 않는다. membership set은 한 publication 요청 안에서만 한 번 해석하며 IAM 권한 cache가 아니다. actor·기존 binding 변조·증거 검증 회귀와 창작 조회/코호트 관련 집중 74개가 통과했다(기존 114개와 중복 범위 포함).
