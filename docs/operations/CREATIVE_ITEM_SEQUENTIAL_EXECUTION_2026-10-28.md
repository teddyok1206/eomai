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

## 고정 대상의 연속 처리

실제 Studio 세션으로 전체 대상의 source revision/observation hash, 원래 task owner, 추출·분석 preset/정책/Workflow/Pack을 한 번 승인해 작은 `creative-learning-cohort/1.0` Artifact에 고정한다. 로그인 세션을 장기 보존하거나 관리자 권한을 모델에 넘기지 않는다. 이후 claim은 저장된 owner의 현재 권한과 exact source를 재검사한다. U keyset 조회로 대상 metadata만 모으며 작업·등록·분석의 기존 고유키와 Graph CAS를 재사용한다. 별도 queue나 DB migration은 없다. 메모리 cursor와 작은 status JSON은 파생 관측값이며 재시작 시 정본에서 완료 여부를 다시 확인한다. 단일 root-owned service lock과 기존 queue/slot lease가 중복 실행을 막는다. 우선 3개만 공식 조회까지 확인하고 같은 cohort의 실행 한도를 전체로 늘린다.

아직 PDF가 준비되지 않은 source는 Catalog 소유의 기존 preview application service로만 준비한다. 고정된 설치본의 작은 로컬 adapter가 `eom-catalog-manager` service identity에서 기존 converter unit을 사용하며 기존 preview key로 재전송을 복구한다. 부모가 고정 target/owner/source를 먼저 검증하고 준비 후 다시 검증한다. worker에 NAS/DB 권한을 주거나 root 권한으로 Office 파일을 파싱하지 않는다. 변환 bytes는 기존 Artifact 하나만 정본이며 coordinator는 bounded staged input만 읽는다. 원래 Catalog socket의 peer 권한과 API 사용자 정책을 넓히지 않는다. 과학적 의문점과 기술적 무결성 실패를 구분하며 후자는 explicit stop으로 남긴다.

구현 집중 검사 103개와 임시 PostgreSQL의 admitted base-analysis/Graph 검사 6개 PASS. 이전 전체 9개 중 오래된 document-creation fixture 3개는 현행 preset/retired Workflow admission과 맞지 않아 이 경로의 PASS로 합산하지 않았다. ontology 음성 사례는 현행 staging이 잘못된 edge를 제거하므로, 그 정규화만 test fixture에서 우회해 application acceptance가 raw/historical 부적합 edge를 독립 거부함을 확인했다. 운영 validator나 허용 Workflow를 느슨하게 바꾸지 않았다. 등록 고유키 경합/중단 복구 2개 PASS는 별도 기록을 유지한다. 이 소스/DB 검사는 실제 3건의 Graph·공식 조회 성공을 대신하지 않는다.

2026-10-28 첫 Graph 게시가 성공했다: U 10310의 기존 accepted 분석을 재사용하여 `graphrev_4b6c4e7eab8aa329c4666475085776bf`에 추가했다. worker를 다시 실행하거나 원문/불일치 기록을 변경하지 않았다. `ANSWER_DISAGREEMENT`, `SOURCE_EDITORIAL_ANSWER_NOT_UNAMBIGUOUS`가 남아 있으며 이는 수록 거부가 아니라 조회할 주의사항이다. 공식 보고서 조회까지 포함하는 3개 검증은 아직 진행 중이다.

30분 운영 확인은 별도 read-only systemd timer로 수행한다. 설치본의 observation adapter는 고정 cohort의 bounded 파생 status와 실행 service 상태만 읽고, stale/중단/기술 실패를 구분한다. DB/NAS·모델·queue에 접근하거나 자동 retry/상태 변경을 하지 않는다. 결과는 journal에 남기며 개발 Slack reporter를 운영 기능으로 넣지 않는다. 완료 증거는 여전히 Item/accepted analysis/Graph/공식 조회의 정본 pointer이고 status 숫자로 대체하지 않는다. 전체 실행 전환 후 timer를 활성화하며 rollback은 이 신규 service/timer의 stop/disable이다.

설치는 `scripts/catalog/install_creative_learning_owner.py`가 고정한 신규 service/timer/metadata-only env만 담당하며 모델 작업은 시작하지 않는다. canary 한도 3과 전체 한도는 같은 admitted cohort revision에서만 변경한다. wheel 설치의 umask가 `site-packages`를 root-only로 만들 수 있으므로, 새 immutable prefix를 동결하기 전에 directory 0555/file 0444로 정규화하고 Catalog identity의 import를 확인한다. 이미 실행 중인 API/GPU 또는 이전 maintenance prefix의 권한은 바꾸지 않는다. 설치 도구는 보호된 template/정확한 cohort ID·revision과 state directory를 검사하며 DB migration·비밀번호 저장·다른 서비스 재시작은 하지 않는다.

## 2026-10-29 실제 연속 실행에서 확인한 경계

- 실제 guiadmin 인증과 자체 테스트 세션 logout이 성공했다. 전체 1,053 target의 고정 cohort는 `creativecohort_fa7c6a7691dc890c546ccf700e77436d`, 정본 revision은 `rev_55de21e864244c90b7fb73f29f78c4b4`다. 등록 정책/대상은 다시 로그인해 재제출하지 않는다.
- owner wheel은 `9ce6ee239e20f65b40600dedbd0b4275e9019093`, SHA `107db69749040bb6ebda1aaf43eadab641c03a4ba5ecc538c5258ce54ec2cf7d`다. Catalog identity import, service 실행, read-only observer의 `OK`/exit 0을 실제 확인했다. 설치 보조 도구의 parent directory 누락은 `2c8ce81d`에서 수정했다. API/Web/GPU 설치본은 교체하지 않았다.
- U 10310은 02:19 UTC에 원문 수록/accepted base/공유 Graph/공식 SOLUTION_REPORT 조회와 warning closure까지 VERIFIED 됐다. 기존 worker/analysis 결과를 재사용했다.
- U 10311은 02:19:46–02:30:09 UTC에 실제 support05에서 실행됐다. Job `job_098991890d0843e3a222092cdb551ac1`은 SUCCEEDED, Workflow `workflow_518e91583462499a8833a855be047487`는 COMPLETED이며 원래 role-result는 NEEDS_DECISION/proposal=null이다. 모델/실행 실패가 아니라 입력 계약의 원문 표현 부족이다. 원문 표 안의 장치 그림을 가리킬 verified crop pointer가 없고, 창작 문항에 배점 표지가 없다. 별도 첨부 기출의 배점을 빌려 쓰거나 그림을 만들어 넣지 않은 판단은 보존한다.
- 결과적으로 owner는 `CREATIVE_SOURCE_ITEM_UNREADABLE`로 explicit stop했다. 이 사례를 과학적 오류나 실제 OCR 불능이라고 재해석하지 않는다. 3건 PASS가 아니며, 나머지 자동 실행/30분 timer 전환도 아직 미실행이다. 이 문항을 건너뛰어 쉬운 표본 3개만 통과시키지 않는다.
- UI의 슬롯 표시 오류는 재현되지 않았다. 위 Job의 정확한 auth binding에 lease가 존재했고 종료 후 RELEASED 됐다. 실제 배포 JS는 같은 active-lease 값을 5초 간격으로 읽는다. 11:30 KST 이후 슬롯이 대기로 보인 것은 실제 종료/등록 대기 상태와 일치한다. owner의 등록 대기를 Codex 실행 중으로 표시하지 않는다.
- GPU INDEX는 2026-10-28 20:10:37 UTC `LOCAL_INDEXING_SERVICE_UNAVAILABLE`로 종료한 상태를 읽기 전용으로 관측했다. QUERY는 기존 PID/설치본으로 active다. 이 작업에서 실패 기록이나 GPU runtime pin을 변경·재시작하지 않았다.

### 필요한 좁은 successor 설계 (구현/활성화 전)

1. **책임:** worker는 원문 영역·구조·풀이·필요한 crop recipe를 제안하고, Orchestrator가 exact source에서 crop을 생성·검증·commit한 후 Catalog가 정본 Item을 materialize한다. 원본 HWP/HWPX/PDF는 수정하지 않는다.
2. **정본/계보:** 기존 source revision/observation, page-set과 role-result Artifact가 정본이다. 미해결 제안과 후속 제안을 각각 immutable pointer로 연결한다. 기존 1.33/result 1.0/Workflow/cohort는 제자리 수정하지 않는다.
3. **새 계약:** JSON Schema를 먼저 정의하는 successor에서 임시 source-image reference(영역 ID/페이지/bbox)와 실제 Artifact pointer를 구별한다. 아직 생성되지 않은 hash/Artifact ID를 worker가 채우지 않는다. 독립 풀이/불일치는 시각자료 materialization 완료 여부와 분리해 보존한다.
4. **해석:** crop은 검증된 TARGET_ITEM 영역 내부의 exact page에서만 허용한다. 원본 첨부 영역이나 최신 source를 대체 입력으로 사용하지 않는다. receipt는 source page hash·geometry·output PNG hash를 고정하며 기존 crop isolation/Artifact commit 경계를 재사용한다.
5. **배점:** 원문 미표기를 제안 불능의 근거로 삼지 않는다. successor에서 관측 배점과 미표기 상태를 구별하고, canonical 계약의 합법적인 0은 미표기 변환 정책/주의사항과 함께 해석하도록 설계한다. 첨부 기출의 2/3점을 추측해 채우거나 출판용 배점 확정으로 간주하지 않는다.
6. **접근/규모:** source/작업 key indexed lookup, region ID map, crop recipe/hash set으로 O(regions+crops) 처리한다. 동일 source/rectangle/renderer의 파생물은 고유키로 재사용하고 기존 page bytes를 반복 복사하지 않는다.
7. **트랜잭션:** proposal→crop Artifact→canonical Item→accepted analysis→공유 Graph CAS를 기존 짧은 멱등 단계로 연결한다. 모델/렌더링 동안 DB transaction을 열어 두지 않는다. 신규 queue/table/framework는 기본 범위 밖이다.
8. **의존:** 계약/순수 draft compiler는 adapter를 import하지 않는다. CLI/상주 owner가 기존 Orchestrator/Catalog application을 조합하며 worker가 NAS/DB에 직접 쓰지 않는다.
9. **복구:** 이번 결과는 보존하고 정확한 해결 입력/후속 실행 계보를 남긴다. COMPLETED/FAILED 이력을 덮지 않는다. 후속 입력을 새 정책으로 admission해야 하는 경우 지원된 successor 경계만 사용하며 구 고정 cohort를 몰래 latest로 바꾸지 않는다.
10. **검증:** missing crop/표 안 그림/배점 미표기/첨부 영역 차단, 잘못된 geometry/hash, 중단 후 crop/등록 replay, 같은 슬롯 동시성, 실제 3건과 공식 풀이·주의사항 조회를 확인한다. 원본 정보가 부족하면 source와 보고서를 보존하고 이유를 명시한다.
11. **배제한 대안:** 전체 페이지를 그림으로 넣으면 별도 기출/메타데이터가 섞인다. 임의 이미지·Artifact hash 생성은 위조다. 배점 필수를 전역 완화하거나 읽을 수 있는 다음 문항만 골라 PASS 처리하는 것은 이번 실패 경계를 해결하지 않는다.

### successor 구성요소 구현 현황 (아직 소스 전용)

- `creative-source-item-draft/1.0` JSON Schema와 frozen model은 native paragraph/equation/table/statement를 유지하고, 그림만 `source_image`의 observed region reference로 표현한다. worker가 Artifact ID/경로/hash를 만들어 넣는 branch는 없다. `PRINTED`/`UNPRINTED` 배점 상태와 독립 풀이의 미검증 상태도 분리한다.
- `external-item-learning-result/2.0`은 시각자료 정본 변환이 미완료여도 공개 가능한 독립 풀이를 별도 `solution_report`로 보존한다. 원문 source answer와 독립 answer의 차이는 그대로 기록한다. 부모 영역 containment·첨부 기출/편집 해설 영역 overlap·선지 참조·풀이 단계·region closure를 검증한다.
- 순수 draft compiler는 owner가 검증해 전달한 이미지 집합이 recipe와 정확히 일치할 때만 canonical Item을 구성한다. UNPRINTED의 canonical 0은 `source_score_state`와 `SOURCE_SCORE_NOT_PRINTED`를 함께 보존해야 하며, 원문에서 관측한 0점과 구별한다. 아직 Registry application에 연결하지 않았다.
- 기존 PDF renderer에 별도 visual crop 진입점을 추가했다. 동일 `-scale-to 2400` frame과 고정 Poppler binary hash를 사용해 source rectangle만 렌더링하고 중복 region은 한 번만 materialize한다. untrusted PDF는 기존 eom-image systemd isolation에서만 파싱하며 이 adapter는 NAS/DB에 쓰지 않는다. 합성 PDF를 실제 Poppler로 렌더링한 geometry/hash/중복/변조/renderer drift 검사도 통과했다. crop receipt Artifact commit은 후속 연결 사항이다.
- V2는 worker의 미서명 body와 owner가 기본값을 정규화한 뒤 SHA를 붙이는 저장 result를 분리했다. 모델이 SHA를 제출하면 거부한다. nullable table caption 등 기본값이 저장/재조회에서 hash를 바꾸지 않도록 round-trip을 검사했다. 기존 V1 의미/bytes는 변경하지 않았다.
- 집중 계약/compiler/real synthetic-PDF 회귀 56개 PASS. 별도 broader 공유 Graph/보고서 회귀 84개 PASS는 중복을 합산하지 않는다. 설치된 predecessor와 대조해 기존 workflow-role 1.0.1/1.4.0/1.33.0의 schema bundle hash가 동일함도 확인했다.
- 아직 필요한 연결: successor role/Workflow·실행 설정, 검증된 crop derivation의 Orchestrator commit, source lineage/report reader·등록 adapter, 고정 cohort의 명시적 successor/recovery, 호환 운영 배포 및 실제 3건 재검증. 이 소스 검사를 운영 성공 또는 목표 달성으로 보고하지 않는다. 기존 owner는 중단 상태, 전체 연속 처리와 30분 timer는 미활성 상태로 유지한다.

소스 단계에서 `workflow-role/1.34.0` / `external-item-learning-result@2.0` wire를 추가했다. 원본 source/page/work-input 1.0과 기존 `ExternalItemLearningWorkerRequest`는 그대로 재사용한다. 새 work-input이나 parallel worker request framework를 만들지 않는다. V2 report/draft만 다른 결과이며 source/page const와 페이지 수를 generation schema에 고정하고, owner가 검증한 기본값에만 SHA를 부여한다. wire 입력/결과/Codex projection/멱등 decode·선행 hash/무승인 실행 차단 집중 19개 PASS. 새 wire가 등록됐다는 사실은 실행 활성화가 아니다. 기존 plan 27은 Workflow 1.0.0에 고정돼 있으므로 후속 Workflow/plan도 explicit successor로 연결해야 한다. 이전 cohort/결과는 수정하지 않는다. 후속 preset이 이전 purpose/Workflow의 기본 설정을 뜻하지 않게 바꾸지 않도록 버전별 호환성·instruction pin을 함께 검사한다.

사용자가 이전 architecture 문서의 변경을 그대로 별도 커밋하도록 승인했다. `94b1329e`에 68줄을 내용 수정 없이 보존했으며 정상 릴리스의 dirty-tree 조건을 우회하지 않았다. 추가 Studio 로그인은 이 문서 보존/소스 개발 과정에 필요하지 않았다.

### 기출 520건과의 저장·조회 호환성 확인

사용자 요청에 따라 2026-10-29 03:18 UTC 운영 Graph를 읽기 전용으로 대조했다.
baseline `graphrev_7870b0fb03b7dfb64179e53182bf3999`의 accepted source는 1,015개
(교과서 분석 범위 495 + 기출 520)이고, U10310 추가 후 같은 Graph에 1,016개다.
문서 수/분석 범위 수/문항 수를 혼합하지 않는다. 기존 membership/Artifact·revision·hash
변경 0, 기존 node identity 17,000개와 edge identity 40,652개 누락/재발급 0을 확인했다.
기출의 accepted V10 보고서는 base당 정확히 1개씩 520개다. 창작 노드 29개 중 3개는
교과서·기출 source pointer도 함께 갖는다. 세 source의 대표 accepted 분석은 공식
resolver로 모두 읽혔다. 전체 기출을 재실행하거나 운영 데이터를 수정하지 않았다.

합성 기출 520 + 창작 + 교과서를 공통 projector에 함께 넣는 회귀 4개와 관련 구버전/조회
포함 집중 99개 PASS(중복 포함). 상세 근거·차이·다음 구현의 불변 조건은
`docs/architecture/CREATIVE_PAST_EXAM_GRAPH_COMPATIBILITY.md`에 기록했다.
입력 결과 V2/plan 28의 source-only 후속 작업은 이 저장 호환성과 별개로 계속 진행한다.
창작 독립 보고서를 기존 accepted V10 상세 보고서라고 과장하지 않으며, 현재 실제 끝단
검증은 여전히 1/3이다. 전체 연속 실행/30분 timer는 아직 활성화하지 않았다.

### source-visual successor 실행 연결 (소스 전용)

Workflow `2.0.0` / role `1.34.0` / plan `28.0` / result `2.0`을 한 호환 family로
정의했다. 기존 `external-item-learning` purpose와 Workflow 1/plan 27은 그대로 남고,
새 purpose는 `creative-source-learning`이다. 버전별 profile lookup은 불변 table이며
latest fallback이 아니다. 같은 work-input/page Artifact 1.0을 재사용한다.

준비·START·Orchestrator result admission·page materialization은 그 exact family를 확인한다.
구 plan에 새 result 또는 새 plan에 구 result를 넣으면 capacity claim 전에 거부한다.
원문 권한과 page-set 무결성은 실행 전·결과 commit 전에 다시 검사한다. terminal replay는
기존 성공/실패 상태를 보존하고 모델을 다시 실행하지 않는다. 기존 schema의 bytes나
Workflow/cohort pin을 바꾸지 않으며, 새 definition/control을 운영에서 발행·활성화하지 않았다.

집중 실행/기존 materializer/준비/START/계약 회귀 **137개 PASS**. V2 실행은 로컬 synthetic
worker로 검증했고 실제 Codex/운영 DB/NAS를 사용한 acceptance가 아니다. 관련 core의
Ruff·format·mypy PASS. 추가 연결은 crop derivation receipt/Orchestrator publication,
등록·보고서 reader와 명시적 cohort successor다. 실제 3건과 장기 owner 전환은 아직 미완료다.

### crop commit·등록·공식 보고서 연결 (소스 전용)

`creative-source-visual-set/1.0` receipt를 schema-first로 정의했다. 원문 source/work hash,
exact role-result Artifact, PDF SHA, delivered page Artifact, 고정 renderer, normalized/pixel
rectangle과 PNG member/SHA를 묶는다. worker가 Artifact ID를 제안하지 않으며 기존
`ControlFileSetPublisher`만 NAS commit을 소유한다. 반복 참조는 같은 crop 한 개를 사용한다.
성공 replay는 PNG를 재생성하지 않고 exact publication을 읽는다. 중단된 commit은 같은
작업 키로 결정적인 로컬 입력만 재준비하고 기존 owner의 resumable 검사를 통과해야 한다.
FAILED/conflict 또는 손상된 성공 Artifact를 성공으로 고치지 않는다.

Registry는 source/권한을 먼저 확인하고 crop rendering을 DB transaction 밖에서 수행한다.
실제 NAS commit 직전과 직후에도 Catalog 소유의 현재 source 권한을 확인한다. 최종 등록은
동일 role/work를 다시 해석하고 기존 registration-key fence와 source revision 검사를 사용한다.
이미 등록된 결과는 저장된 lineage/derivation을 검증해 반환하며 새 코드 commit을 이유로
새 이미지 포인터나 문항 revision을 만들지 않는다. 같은 원문에 대한 별도 결과는 기존 정본을
덮는 대신 충돌로 남는다. 일반 문항 삭제/다른 컴포넌트 권한 변경과는 무관하다.

V2 공식 보고서는 원문 답안/독립 답안·공개 풀이 단계·모든 conflict·원래 NEEDS_DECISION을
같이 보여준다. UNPRINTED의 canonical 0은 SOURCE_SCORE_NOT_PRINTED와 원래 배점 상태를
함께 보존하고 해당 warning 누락을 거부한다. 원문이 과학적으로 틀렸다는 판단만으로 원문을
수정하거나 수록을 거부하지 않는다. resolver는 구 family와 새 family를 명시적으로 나누고
role의 Job/Workflow/step뿐 아니라 logical Artifact/revision도 실제 Job과 대조한다.

등록 Pack `external-creative-item/1.1.0`은 기존 metadata/item-type bytes를 유지하고
Workflow 1/2, role 1.33/1.34를 명시적으로 지원한다. 1.0.0과 과거 Item은 변경하지 않았다.
이 Pack/control은 아직 운영 발행/활성화하지 않았다.

2026-10-29 소스 집중 회귀 **359개 PASS**(창작/입력/실행/Graph/보고서 전체, 이전 숫자와 중복).
새 crop adapter는 합성 PDF를 실제 Poppler로 처리했다. 별도 fresh disposable PostgreSQL에서
등록 키 경합/rollback 2개와 실제 crop Artifact의 동시 commit/COMMITTING 복구 2개,
합계 **4개 PASS**를 확인했다. 후자는 같은 Job·Artifact·revision으로 복구되며 실제 소스
admission/Graph 성공을 뜻하지 않는다. migration 왕복 head는 20261027_0062, 새 migration은
없다. 초기 test helper의 manifest dict 접근 오류는 fixture만 수정하고 fresh DB에서 재검증했다.
이 단계에서 만든 disposable DB 두 개는 공식 cleanup으로 제거했고 운영 데이터는 수정하지
않았다. core Ruff·format·mypy, diff와 shell syntax 검사 PASS.

남은 활성화 범위는 새 목적의 실행 설정/원문 표현 지침 발행, 부모 cohort를 고정 참조하는
명시적 successor/recovery, 호환 wheel 배포와 U10311/U10312 실제 순차 검증이다. 운영은
여전히 표본 1/3이며 전체 연속 실행/30분 timer를 켜지 않았다. 기존 API/Web/GPU/QUERY
runtime pin과 과거 실패/의사결정 기록을 보존한다.

같은 저장소 후보 `d7858b56`을 archive에서 wheel로 만들어 별도 임시 target에 설치했다.
wheel SHA는 `73d4177acd909eef932ea4bb47b404e3fc6707fe711659822686b5c08dd0b358`이며
RECORD와 installed-only import/schema 해석 PASS다. 새 plan 28/crop schema가 포함되고
구 role 1.0.1/1.4/1.33 bundle hash는 그대로다. 최초 pip 산출물의 0664 권한은 verifier가
거부했고, 해당 후보 파일만 요구되는 private 0600으로 바꾼 후 재검증했다. 검사를 완화하지
않았다. 이 wheel은 소스 후보 확인용이며 운영 shared runtime에 설치하지 않았다.

후속 실제 definition 발행을 위해 기존 공통 admission table에도 정확한
external-item-learning 2.0.0 ↔ role 1.34.0 pair를 추가했다. DB definition active/preset/source
권한 검사를 대체하거나 Workflow 1의 기본 설정을 바꾸지 않는다. profile과 admission의
일치 및 기존 version admission 집중 38개 PASS다. 추가 admission 회귀의 최초 235개 중
234개 PASS/1개는 구 expected matrix가 새 pair를 누락한 fixture 차이였고, 그 expected
successor 목록을 보완해 해당 집중 검사를 재실행했다. 이는 운영 발행·START 증거가 아니다.

### 고정 source cohort의 좁은 continuation 설계

1. 책임은 기존 cohort application/순차 owner에 있다. 새 queue/framework를 만들지 않는다.
2. 원래 cohort Artifact와 targets/정책 pin이 정본이며 원래 1,053개 목록은 수정하지 않는다.
3. 작은 `creative-learning-continuation/1.0`은 부모 cohort member pointer를 고정 참조한다.
   새 실행 identity/Workflow 2 hash/추출 preset/등록 Pack만 저장하고 targets를 복제하지 않는다.
4. 부모의 Artifact/revision/schema/media/hash/lifecycle과 target-set SHA·owner 일치를 검사한다.
   부모가 V1이 아니거나 target/owner가 다르면 상속 admission이 아니다.
5. 접근은 source/등록 unique key indexed lookup, 고정 targets의 순서 순회와 Graph CAS다.
6. continuation 해석은 부모 metadata를 한 번 읽는 O(targets), 추가 저장은 O(1)이다.
7. 추출·등록·분석은 기존 짧은 transaction/lease를 사용한다. 완료한 source는 exact 등록
   lineage를 재검증해 재사용하고, 멈춘 구 실행은 보존한 채 명시적 새 family 작업으로 잇는다.
8. contracts에는 frozen value만, application에 admission/권한, Orchestrator에 Artifact
   commit, CLI/runner에는 조합만 둔다. worker의 DB/NAS 접근은 여전히 금지다.
9. 원래 admission의 실제 owner를 매 claim/control 변경에 현재 IAM/source로 재검증한다.
   browser session을 보존하거나 운영자를 사칭하지 않는다. 같은 transition은 멱등 replay다.
10. 설치/배포/START를 별개로 기록한다. 실패 이력을 덮거나 3개 검증 전에 전체 실행하지 않는다.
11. 부모 targets 전체를 새 schema로 복사하거나 구 cohort pin을 수정하는 대안은 불필요한
    복제/재해석이므로 쓰지 않는다. 별도 DB table/migration도 필요 없다.

continuation application/CLI와 원래 source set을 공유하는 process lock을 연결했다. 등록된
source는 exact source revision/observation/edition과 기존 lineage를 검증해 재사용하며, 미등록
source만 후속 Workflow 2로 준비한다. 원래 cohort와 실패 결과를 수정하지 않는다.
창작·기존 추출 unit 회귀 366개 PASS, 프로토콜 hash 충돌 거부를 추가한 control/continuation/
Graph 집중 27개 PASS(서로 중복 포함), core Ruff·format·mypy PASS다. fresh disposable DB에서
기존/후속 control 발행·동시성·멱등 및 원래 설정 불변 검사를 포함한 20개 PASS다.
첫 DB 실행은 새 role protocol 등록이 빠져 명시적으로 거부됐으며, 기존 protocol owner를
같은 control transaction에서 호출하도록 보완했다. hash 불일치 검사는 유지한다.
새 migration·모델 실행·운영 활성화는 이 검증에서 하지 않았다.

추가 사용자 요구: 풀이보고서의 입력 family/양식 차이만으로 임베딩 유사도가 달라지지 않도록
실제 similarity projection을 별도로 추적한다. 없는 풀이 정보를 만들어 채우거나 원래 보고서/
현재 임베딩 인덱스의 identity·bytes를 제자리 변경하지 않는다. 아직 이 요구의 검증·배포는
완료되지 않았다.

저장소 후보 `92dbdc19`의 정식 build-only wheel RECORD는 PASS였으나 installed definition
simulation이 새 Workflow 2의 staging 누락을 발견해 거부했다. 운영 설치는 시작하지 않았다.
기존 equality gate를 완화하지 않고 두 창작 definition/role/result family를 실제 staging과
검사 대상에 모두 넣었다. 해당 release coverage/role 회귀 9개, shell syntax·Ruff·mypy PASS다.

### 모델 시작 전 실패의 명시적 후속 준비

호환 배포 `efdb7c67`과 continuation 발행은 완료했으나 U10311의 새 Workflow는 Catalog
원문 권한 확인이 구 family만 허용하여 Job 생성 전에 실패했다. 원래 FAILED는 보존한다.
공통 profile의 definition/role/result 정확한 조합을 확인하도록 수정하며 권한 검사를 완화하지
않는다. 구/새 family 및 혼합 버전 거부, 실제 Unix socket 회귀 포함 62개 PASS다.

1. 복구 책임은 기존 Workflow preparation application에 둔다. worker를 직접 실행하지 않는다.
2. 정본은 admitted cohort, exact 원문/work/plan과 FAILED Workflow/step, 기존 Job/command다.
3. 기존 실패는 그대로 두고 새 Workflow 하나를 만든다. immutable recovery 값은 두 ID와
   source/work/definition hash, 원래 owner를 연결하며 기존 append-only event에 저장한다.
4. 원래 source 권한과 원본 pin을 재확인하고, 실패 step의 Job ID뿐 아니라 유일한 Job
   idempotency key 조회에서도 Job이 없음을 증명해야 한다. 살아 있는 command도 거부한다.
5. 접근은 PK/Job unique key와 workflow별 event sequence index다. 큰 자료를 복사하지 않는다.
6. 후속 key는 predecessor/work/definition hash에서 결정하고 parent row lock으로 중복 준비를
   막는다. 원래 1,053개 대상과 정책/모델 pin, 단계당 실행 횟수는 바꾸지 않는다.
7. 준비는 한 DB transaction이다. 같은 복구의 재전송은 같은 successor로 돌아오고 중단은
   기존 Artifact/DB 경계로 rollback한다. 실패 이력을 성공으로 변경하지 않는다.
8. Cohort application은 지원 Workflow use case를 호출하고, 순차 owner는 기록된 successor
   pointer만 해석한다. Catalog가 Workflow row를 직접 고치거나 root가 worker를 실행하지 않는다.
9. recovery 기록이 없으면 기존 실패에서 멈춘다. 과학적 불일치나 실제 worker 실패는 이 좁은
   'Job 생성 전' 복구로 우회할 수 없다. 복구 준비와 START는 별개다.
10. 이벤트 연결은 bounded immutable chain, seen-ID set으로 순환을 거부한다. 기존 등록 unique
    source key/현재 operator 권한/Graph CAS는 계속 적용된다. 새 table/index/migration은 없다.
11. FAILED를 READY로 바꾸거나 새 key만 임의 발급하는 대안은 원래 실패와 중복 실행 근거를
    잃으므로 쓰지 않는다. 별도 queue/framework 대신 현재 preparation/event를 확장한다.

2026-10-29 04:46–04:48 UTC 실제 적용: API/shared runner `efdb7c67` 배포·RECORD·설치본
definition 검사·migration 0062 확인·격리 검사·READY PASS. continuation은
`creativecohort_672605303b6e3e27b9e57fcc6938beb3` /
`rev_36fc4e4e415f4e609e2033f7a4ab48dc`이며 원래 target-set 1,053개/SHA는 유지했다.
QUERY는 API Requires 관계로 중지된 것을 확인해 같은 `07ec7b32` prefix/config로 재시작했다.
GPU INDEX는 원래 10-28 20:10:37 UTC FAILED 상태와 pin을 그대로 보존했다. 현재 worker
lease·진행 HWPX·chat은 0이었으며, 오래된 native 임베딩 Job/command는 수정하지 않았다.

U10310은 원래 Item/분석/Graph/공식 보고서로 다시 VERIFIED. U10311 후속 Workflow
`workflow_96b5f78cb4384555852cccdd170f4ef4`는 원문 권한 family 누락 때문에 FAILED이며
`steprun_121c981a8b784f54bb8da1b45a2e719e`의 platform Job은 없었다. 원래 V1 결과와 이
실패는 보존한다. 전체 연속 실행/30분 timer는 아직 미활성화, 실제 표본 종료선은 1/3이다.

위 source-authority 보완과 명시적 no-Job recovery의 소스 회귀: 창작·기존 추출·공통 풀이
projection 407개 PASS, 추가 link 변조 거부를 포함한 복구 집중 18개 PASS(부분 중복).
fresh disposable PostgreSQL에서 22개 PASS, 마지막 link 검사 이후 동시 복구/늦은 권한
거부 rollback 두 사례만 같은 guarded DB의 새 synthetic 대상으로 다시 실행해 2개 PASS다.
같은 predecessor에 successor 1개/기존 FAILED 보존/START command 0/예외 시 orphan 0을
확인했다. 원래 role Job key의 bytes는 유지하고 공통 함수로 옮겨 indexed 부재 확인에
재사용한다. core Ruff·format·mypy PASS. 이 수정·복구 기능은 아직 운영 배포 전이다.

추가로 다른 active-equivalent READY 실행에 복구 계보를 덮어쓰는 것을 명시적으로 거부했다.
복구 unit 19개와 fresh disposable DB의 동시 준비/늦은 거부/다른 active 보존 3개 PASS이며
이 DB와 앞선 22개 검증 DB는 공식 cleanup으로 제거했다. 후보 `8acd992d`와 `085cc260`은
정식 build-only/설치본 simulation/RECORD PASS였고 아직 운영 설치하지 않았다.

V2 추출의 core prompt도 점검해, 구 placeholder가 명시하는 result@1.0을 새 family에
넘기지 않도록 분리했다. V1 파일과 그 경로·지침은 그대로 유지한다. V2는 exact source-
visual bundle/주어진 schema/독립 공개 풀이/result@2.0만 지시하는 고정 core를 사용한다.
실제 executor의 prompt 전달과 구버전 선택/role hash 회귀 20개, engine Ruff·format·mypy
PASS다. 아직 새로운 worker 실행이나 새 결과 성공을 의미하지 않는다.

### 검증 거부된 모델 결과의 명시적 재실행 준비 (2026-10-29)

U10311의 V2 Job은 객관식 정답을 choice/text 양쪽에 넣어 WORKER_RESULT_INVALID로
실패했다. 원문이나 과학 판단 문제가 아니다. 기존 canonical/Pydantic XOR 검사는 유지하고,
V2 생성용 schema에서 객관식/서술형/미결정 답안을 anyOf로 구분한다. 기존 V1 및 released
schema bytes는 바꾸지 않고 실패 응답을 자동 고치거나 성공 처리하지 않는다.

실제 Job이 있으므로 no-Job 복구는 적용할 수 없다. 같은 Workflow preparation 경계에
명시적 invalid-result 복구를 추가한다. 정본은 기존 cohort/source/work/definition/preset,
FAILED Workflow/step/Job이며, 새 작은 immutable event는 이전 Job과 새 Workflow를 연결한다.
큰 입력·파일은 복사하지 않는다. PK/unique Job key 및 workflow event index로 조회하며
한 predecessor row lock/transaction에서 successor 하나만 준비한다. 예상 비용은 bounded
indexed lookup과 기존 event sequence append다. 새 table/index/queue/migration은 없다.

조건은 일치하는 WORKER_RESULT_INVALID terminal Job, commit 진입 이력 및 Artifact 없음,
active lease/command 없음, 동일 원래 owner/source/plan 재인가다. COMMITTING/성공/불명확한
Job은 거부한다. 준비는 worker 실행이 아니며 START는 기존 owner가 별도 수행한다.
중복 요청은 같은 pointer를 반환하고, 실패는 caller transaction rollback한다. 과거 FAILED,
과학적 NEEDS_DECISION, 원본 답/해설은 변경하지 않는다. 자동 무한 재시도하지 않는다.
기존 successor resolver만 typed event 두 종류를 해석한다. 임의 key 재발급이나 FAILED를
READY로 변경하는 대안은 중복·감사 계보를 잃으므로 사용하지 않는다.

소스 검증: 창작·기존 추출·풀이 projection 432개 PASS, Ruff·format·mypy PASS.
fresh disposable PostgreSQL migration 왕복/0062 PASS 및 관련 저장소 26개 PASS이며,
두 복구 사유 모두 동시 준비 1개·기존 실패 보존·늦은 권한 거부 rollback·다른 active
실행 보존을 검증했다. 초기 synthetic Job fixture의 protocol flush 누락을 수정했다.
재사용 DB에서 instruction 전체 건수 검사가 기존 실행 자료를 합산한 실패는 별도 보존했고,
운영 DB가 아닌 새 DB에서 전체 suite를 재실행했다. 아직 새 모델 결과 성공은 아니다.
